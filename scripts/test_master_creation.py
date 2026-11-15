"""Scoped master preview/authority/recovery. All native transport is synthetic."""
import asyncio,copy,tempfile,unittest,uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from xml.etree import ElementTree as ET
from fastapi import HTTPException
from sqlalchemy import select,func
from app.models.tally import TallyAction,TallyDevice,TallySnapshot
from app.services import master_creation_service as service,tally_master_actions as native,purchase_draft_service as drafts,tally_sync as sync,tally_sync_protocol as protocol,tally_bridge as bridge
from app.services.tally_connector import TallyError,TallyRejected,tag,name
from scripts import test_tally_sync as fixtures

class Native(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.guid=str(uuid.uuid4());self.payload={'operation':'masters_create','company':'Pilot Test','guid':self.guid,'masters':[
            {'kind':'UNIT','name':'Boxes','guid':str(uuid.uuid4()),'fields':{'ISSIMPLEUNIT':'Yes','DECIMALPLACES':'0','GSTREPUOM':'BOX-BOXES'}},
            {'kind':'STOCKITEM','name':'New goods','guid':str(uuid.uuid4()),'fields':{**native.BASE['STOCKITEM'],'BASEUNITS':'Boxes'}},
            {'kind':'LEDGER','name':'New supplier','guid':str(uuid.uuid4()),'fields':dict(native.BASE['LEDGER'])}]}
        self.cat={'units':[],'items':[],'ledgers':[]};self.cfg={'company':'Pilot Test','test_company':True};self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        async def post(xml):
            for row in ET.fromstring(xml).findall('.//TALLYMESSAGE/*'):self.cat[native.KINDS[row.tag]].append(copy.deepcopy(row))
        self.connector=SimpleNamespace(catalog=AsyncMock(side_effect=lambda *a:self.cat),post=AsyncMock(side_effect=post))
    async def run_op(self,op):return await native.execute('masters_'+op,self.connector,'Pilot Test','identity',self.payload,self.cfg,self.tmp.name+'/journal')
    async def test_validate_never_writes_and_post_is_verified_once(self):
        self.assertEqual((await self.run_op('validate'))['status'],'ready');self.connector.post.assert_not_awaited()
        self.assertEqual((await self.run_op('post'))['status'],'verified')
        self.assertEqual((await self.run_op('post'))['status'],'verified');self.connector.post.assert_awaited_once()
    async def test_timeout_and_restart_never_resend(self):
        self.connector.post.side_effect=TallyError('timeout')
        for _ in range(2):self.assertEqual((await self.run_op('post'))['status'],'verification_pending')
        self.connector.post.assert_awaited_once()
    async def test_partial_batch_is_not_reimported(self):
        await self.run_op('post');self.cat['items']=[]
        self.assertEqual((await self.run_op('post'))['status'],'verification_pending');self.connector.post.assert_awaited_once()
    async def test_same_name_foreign_identity_is_never_overwritten(self):
        row=ET.Element('LEDGER',NAME='New supplier');tag(row,'GUID','foreign');self.cat['ledgers']=[row]
        self.assertEqual((await self.run_op('post'))['status'],'needs_review');self.connector.post.assert_not_awaited()
    async def test_wrong_fields_do_not_verify(self):
        await self.run_op('post');self.cat['items'][0].find('BASEUNITS').text='other'
        self.assertEqual((await self.run_op('reconcile'))['status'],'needs_review')
    async def test_reject_real_company_and_arbitrary_fields(self):
        for change in ('real','field','precision'):
            with self.subTest(change=change):
                p=copy.deepcopy(self.payload);cfg=dict(self.cfg)
                if change=='real':cfg['test_company']=False
                if change=='field':p['masters'][0]['fields']['ALTERID']='9'
                if change=='precision':p['masters'][0]['fields']['DECIMALPLACES']='10'
                with self.assertRaises(TallyError):native.validate(p,cfg,'Pilot Test')
    async def test_protocol_checks_exact_native_company_before_dispatch(self):
        company=ET.Element('COMPANY',NAME='Pilot Test');tag(company,'GUID','wrong')
        with patch.object(protocol,'TallyConnector',return_value=SimpleNamespace(collection=AsyncMock(return_value=[company]))):
            with self.assertRaises(TallyError):await protocol.execute_sync('masters_post',company='Pilot Test',identity='identity',payload=self.payload,config=self.cfg)

class Preview(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.DurableTests.asyncSetUp(self)
        self.device=TallyDevice(id=uuid.uuid4().hex,organization_id=self.org,credential_hash='version',revoked=False)
        self.db.add(self.device);self.company.device_id=self.device.id
        snapshot=await self.db.get(TallySnapshot,self.company.id);snapshot.device_version='version';await self.db.commit()
        self.draft=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,content={'party_name':'New supplier','lines':[{'item_name':'New goods','quantity':'5','unit':'bags','rate':'350'}]}))
    async def asyncTearDown(self):
        from app.core.redis import close_redis_pool
        await close_redis_pool()
        await fixtures.DurableTests.asyncTearDown(self)
    async def prepare(self,**kwargs):return await service.prepare(self.db,self.principal,self.draft['id'],**kwargs)
    async def test_preview_is_scoped_idempotent_and_does_not_mark_purchase_verified(self):
        first=await self.prepare();second=await self.prepare();self.assertEqual(first['preview']['token'],second['preview']['token'])
        action=await self.db.get(TallyAction,first['preview']['token']);self.assertEqual(action.status,'preview');self.assertIsNone(action.approved_arguments)
        row=await drafts.scoped_draft(self.db,self.principal,self.draft['id']);self.assertIsNone(row.action_id);self.assertEqual(row.revision,0)
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(TallyAction).where(TallyAction.organization_id==self.org)),1)
    async def test_stale_revision_or_other_preview_invalidates_master_approval(self):
        response=await self.prepare();action=await self.db.get(TallyAction,response['preview']['token']);row=await drafts.scoped_draft(self.db,self.principal,self.draft['id']);row.revision+=1;await self.db.commit()
        with self.assertRaises(TallyError):await service.guard(self.db,action)
    async def test_no_server_local_fallback(self):
        self.company.device_id=None;await self.db.commit()
        with self.assertRaises(HTTPException) as error:await self.prepare()
        self.assertEqual(error.exception.status_code,409)
    async def test_missing_unit_configuration_blocks_not_guesses(self):
        row=await drafts.scoped_draft(self.db,self.principal,self.draft['id']);row.content={**row.content,'lines':[{**row.content['lines'][0],'unit':'Boxes'}]};await self.db.commit()
        with self.assertRaises(HTTPException):await self.prepare()
        result=await self.prepare(unit_definitions=[{'name':'Boxes','decimal_places':0,'uqc':'BOX-BOXES'}]);self.assertIn('preview',result)
    async def test_old_helper_cannot_queue_and_approval_is_explicit(self):
        result=await self.prepare();action=await self.db.get(TallyAction,result['preview']['token'])
        self.assertFalse(result['preview']['can_confirm'],'offline/old helper must visibly block confirmation')
        redis=SimpleNamespace(exists=AsyncMock(return_value=False),aclose=AsyncMock())
        with patch('app.core.redis.get_redis_client',AsyncMock(return_value=redis)):
            with self.assertRaises(HTTPException):await sync.confirm_queued(self.db,self.principal,action)
        self.assertEqual(action.status,'preview')
        redis.exists.return_value=True
        with patch('app.core.redis.get_redis_client',AsyncMock(return_value=redis)):
            await sync.confirm_queued(self.db,self.principal,action);await sync.confirm_queued(self.db,self.principal,action)
        self.assertEqual(action.status,'queued');self.assertEqual(action.approved_arguments,action.payload)
    async def test_unauthorized_company_cannot_prepare(self):
        self.cfg.test_company=False;await self.db.commit()
        with self.assertRaises(HTTPException):await self.prepare()

    async def test_verified_masters_do_not_complete_the_purchase_task(self):
        from app.models.agent_task import AgentTask
        from app.services import task_agent_service as tasks
        result=await self.prepare();token=result['preview']['token']
        task=AgentTask(id=uuid.uuid4().hex,organization_id=self.org,user_id=self.user,company_id=self.company.id,
            revision=0,status='needs_approval',request_id=uuid.uuid4().hex,request_hash='f'*64,created_at=sync.now(),updated_at=sync.now(),
            state={'action_id':token,'draft_id':self.draft['id'],'outcome':'verified_entry','summary':'Review masters','observations':[{'data':result}]})
        self.db.add(task);await self.db.commit()
        redis=SimpleNamespace(exists=AsyncMock(return_value=True),aclose=AsyncMock())
        with patch.dict('os.environ',{'PHILIXA_TASK_AGENT_ENABLED':'1'}),patch('app.core.redis.get_redis_client',AsyncMock(return_value=redis)):
            await tasks.approve(self.db,self.principal,task.id,tasks.TaskApproval(expected_revision=0,token=token,approve=True))
        action=await self.db.get(TallyAction,token);self.assertEqual(action.status,'queued')
        action.status='verified';action.result={'response':'Masters verified; purchase review remains.'};await self.db.commit()
        await tasks.read(self.db,self.principal,task.id)
        self.assertEqual(task.status,'needs_input');self.assertNotIn('action_id',task.state)

    async def test_dispatch_verifies_snapshot_without_changing_purchase_draft(self):
        result=await self.prepare();action=await self.db.get(TallyAction,result['preview']['token'])
        action.status='queued';action.approved_arguments=copy.deepcopy(action.payload);await self.db.commit()
        cat=protocol.deserialize_catalog((await self.db.get(TallySnapshot,self.company.id)).catalog)
        for m in action.payload['masters']:
            row=ET.fromstring(native.xml({'company':self.company.name,'masters':[m]})).find('.//TALLYMESSAGE/*')
            cat[native.KINDS[m['kind']]].append(row)
        snapshot={**self.snapshot,'device_version':'version','catalog':protocol.serialize_catalog(cat)}
        with patch.object(sync,'operation',AsyncMock(side_effect=[{'status':'ready'},{'status':'verified'}])) as operation,patch.object(sync,'capture_snapshot',AsyncMock(return_value=snapshot)):
            await sync.process_action(self.db,action,self.company)
        self.assertEqual(action.status,'verified');self.assertEqual(operation.await_count,2)
        draft=await drafts.scoped_draft(self.db,self.principal,self.draft['id']);self.assertIsNone(draft.action_id);self.assertEqual(draft.revision,0)

class Bridge(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=Preview.asyncSetUp
    asyncTearDown=Preview.asyncTearDown
    prepare=Preview.prepare
    async def test_old_helper_queue_isolation_and_revoked_approval_at_claim(self):
        from scripts.test_multi_purchase_bridge import redis_client
        from app.api.v1 import routes_tally_bridge as routes
        redis=await redis_client();pending=None
        with patch.object(bridge,'get_redis_client',redis_client),patch.object(routes,'get_redis_client',redis_client):
            try:
                await routes.jobs(11,self.device,self.db)
                response=await self.prepare();action=await self.db.get(TallyAction,response['preview']['token'])
                params=dict(company=self.company.name,identity=self.company.identity,payload=action.payload,config=sync.config_data(self.cfg),action_id=action.token)
                with self.assertRaises(TallyError):await bridge.request_job(self.device,'masters_validate',**params)
                await routes.jobs(12,self.device,self.db)
                await sync.confirm_queued(self.db,self.principal,action)
                pending=asyncio.create_task(bridge.request_job(self.device,'masters_validate',**params))
                for _ in range(100):
                    if await redis.llen('tally:queue:v12:'+self.device.id):break
                    await asyncio.sleep(.01)
                self.assertIsNone((await routes.jobs(11,self.device,self.db))['job'])
                job=(await routes.jobs(12,self.device,self.db))['job'];self.assertEqual(job['operation'],'masters_validate')
                await bridge.consume_result(redis,self.device,job['id'],{'data':{'status':'ready'}})
                self.assertEqual((await pending)['status'],'ready');pending=None
                row=await drafts.scoped_draft(self.db,self.principal,self.draft['id']);row.revision+=1;await self.db.commit()
                pending=asyncio.create_task(bridge.request_job(self.device,'masters_validate',**params))
                for _ in range(100):
                    if await redis.llen('tally:queue:v12:'+self.device.id):break
                    await asyncio.sleep(.01)
                with self.assertRaises(HTTPException) as error:await routes.jobs(12,self.device,self.db)
                self.assertEqual(error.exception.status_code,403)
            finally:
                if pending:pending.cancel();await asyncio.gather(pending,return_exceptions=True)
                for key in await redis.keys('tally:*'+self.device.id):await redis.delete(key)
                await redis.aclose()

class SourceGuard(unittest.IsolatedAsyncioTestCase):
    async def test_removed_source_invalidates_unsubmitted_master_review(self):
        content={'party_name':'Synthetic'}
        row=SimpleNamespace(organization_id='org',company_id='company',user_id='user',revision=1,action_id=None,content=content,document_id='source')
        action=SimpleNamespace(organization_id='org',company_id='company',user_id='user',preconditions={'master_draft':{'id':'draft','revision':1,'hash':service.digest(content),'action_id':None}})
        for source in (None,SimpleNamespace(trashed_at=sync.now())):
            with self.assertRaises(TallyError):await service.guard(SimpleNamespace(get=AsyncMock(side_effect=[row,source])),action)
