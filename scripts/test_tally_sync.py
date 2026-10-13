"""Durable sync regressions. Isolated DB fixtures, no real Tally/provider writes."""
import asyncio
import copy
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from xml.etree import ElementTree as ET
from sqlalchemy import delete
from fastapi import HTTPException
from app.database.session import AsyncSessionLocal
from app.models.organization import Organization
from app.models.user import User
from app.models.organization_membership import OrganizationMembership
from app.models.tally import TallyReadCompany, TallyDevice, TallySnapshot, TallyAction, TallyConnection
from app.services import tally_sync as sync, tally_sync_protocol as protocol, tally_stock as stock
from app.services import portfolio_copilot_service as graph, business_command_service as commands
from app.services.tally_connector import TallyError, TallyRejected, name, stock_row, voucher_xml
from scripts.test_tally import FakeTally, node

def catalog():
    data=asyncio.run(FakeTally().catalog('Pilot Test'))
    data['cost_centres_enabled']=False
    return data

class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'journal.sqlite3'
        self.fake=FakeTally()
        self.data=await self.fake.catalog('Pilot Test');self.data['cost_centres_enabled']=False
        self.cfg={'company':'Pilot Test','godown':'Main Location','purchase_ledger':'Purchase','sales_ledger':'Sales','test_company':True}
        self.p={'company':'Pilot Test','godown':'Main Location','party':'Supplier','item':'Cement','quantity':'5','unit':'bags','rate':'350',
                'total':'1750.00','voucher_type':'Purchase','ledger':'Purchase','date':'2026-04-01','guid':str(uuid.uuid4()),'stock_before':'20','master_fingerprint':''}
        self.p['master_fingerprint']=protocol.fingerprint(self.data,self.p)
        self.vouchers=[];self.posts=0
        async def collection(kind,company=None,voucher_date=None,**kwargs):
            if kind=='Company':return [node('COMPANY','Pilot Test',GUID='identity')]
            if kind=='Voucher':return self.vouchers
            return self.data['items'] if kind=='StockItem' else []
        async def post(xml):
            self.posts+=1
            v=ET.fromstring(xml).find('.//VOUCHER');ET.SubElement(v,'VOUCHERNUMBER').text='42'
            self.vouchers.append(v);return ET.Element('REPLY')
        self.connector=SimpleNamespace(collection=collection,catalog=AsyncMock(return_value=self.data),post=post)
        self.patch=patch.object(protocol,'TallyConnector',return_value=self.connector);self.patch.start()
    async def asyncTearDown(self):self.patch.stop();self.tmp.cleanup()
    async def execute(self,kind):
        return await protocol.execute_sync(kind,company='Pilot Test',identity='identity',payload=self.p,config=self.cfg,journal_path=self.path)
    async def test_duplicate_delivery_and_verified_fields(self):
        self.assertEqual((await self.execute('purchase_post'))['status'],'verified')
        self.assertEqual((await self.execute('purchase_post'))['status'],'verified')
        self.assertEqual(self.posts,1)
        self.vouchers[0].find('PARTYLEDGERNAME').text='Wrong supplier'
        self.assertEqual((await self.execute('purchase_reconcile'))['status'],'needs_review')
    async def test_uncertain_send_never_reimports(self):
        async def lost(xml):self.posts+=1;raise TallyError('timeout')
        self.connector.post=lost
        self.assertEqual((await self.execute('purchase_post'))['status'],'verification_pending')
        self.assertEqual((await self.execute('purchase_post'))['status'],'verification_pending')
        self.assertEqual(self.posts,1)
    async def test_tally_assigned_guid_reconciles_without_reimport(self):
        await self.execute('purchase_post')
        self.vouchers[0].find('GUID').text=str(uuid.uuid4())
        self.assertEqual((await self.execute('purchase_reconcile'))['status'],'verified')
        self.assertEqual((await self.execute('purchase_post'))['status'],'verified')
        self.assertEqual(self.posts,1)
        self.vouchers[0].find('NARRATION').text='unrelated'
        self.assertEqual((await self.execute('purchase_reconcile'))['status'],'verification_pending')
    async def test_action_markers_do_not_override_changed_financial_fields(self):
        await self.execute('purchase_post');self.vouchers[0].find('GUID').text=str(uuid.uuid4())
        self.vouchers[0].find('ALLINVENTORYENTRIES.LIST/ACTUALQTY').text='6 bags'
        self.assertEqual((await self.execute('purchase_reconcile'))['status'],'needs_review')
    async def test_native_export_bill_reference_in_full_ledger(self):
        await self.execute('purchase_post')
        v=self.vouchers[0];v.find('GUID').text=str(uuid.uuid4())
        compact=v.find('LEDGERENTRIES.LIST')
        full=copy.deepcopy(compact);full.tag='ALLLEDGERENTRIES.LIST';v.append(full)
        compact.remove(compact.find('BILLALLOCATIONS.LIST'))
        ET.SubElement(compact,'BILLALLOCATIONS.LIST')
        self.assertEqual((await self.execute('purchase_reconcile'))['status'],'verified')
        extra=ET.SubElement(full,'BILLALLOCATIONS.LIST');ET.SubElement(extra,'NAME').text='another-reference'
        self.assertEqual((await self.execute('purchase_reconcile'))['status'],'verification_pending')
    async def test_restart_journal_and_cross_midnight_date(self):
        with protocol.journal(self.path) as db:db.execute('INSERT INTO writes VALUES (?,?)',('identity:'+self.p['guid'],'submitting'))
        self.assertEqual((await self.execute('purchase_post'))['status'],'verification_pending')
        self.assertEqual(self.posts,0)
        self.assertEqual(self.p['date'],'2026-04-01')
    async def test_master_change_requires_review(self):
        self.data['units'][0].find('DECIMALPLACES').text='2'
        self.assertEqual((await self.execute('purchase_validate'))['status'],'needs_review')
    async def test_explicit_rejection_not_saved(self):
        async def reject(xml):raise TallyRejected('date disallowed')
        self.connector.post=reject
        reply=await self.execute('purchase_post')
        self.assertEqual(reply['status'],'failed')
        self.assertEqual(reply['reason'],'date disallowed')
        self.assertEqual((await self.execute('purchase_post'))['status'],'verification_pending')
        self.assertEqual(self.posts,0)
    async def test_zero_rounded_total_rejected(self):
        self.p.update(rate='0.01',quantity='0.01',total='0.00')
        with self.assertRaises(TallyError):protocol.validate_purchase(self.data,self.p,self.cfg)
    async def test_snapshot_pages_no_first_100_truncation(self):
        self.data['items']=[node('STOCKITEM',f'Cement {i}',BASEUNITS='bags',ISBATCHWISEON='No',CLOSINGBALANCE='0 bags') for i in range(205)]
        manifest=await protocol.execute_sync('snapshot_start',company='Pilot Test',identity='identity',as_of='2026-10-08',journal_path=self.path)
        items=[]
        for page in range(len(manifest['hashes'])):
            result=await protocol.execute_sync('snapshot_page',company='Pilot Test',identity='identity',generation=manifest['generation'],page=page,journal_path=self.path)
            items.extend(r for r in result['records'] if r['kind']=='stock')
        self.assertEqual(len(items),205)
        with self.assertRaises(TallyError):await protocol.execute_sync('snapshot_page',company='Pilot Test',identity='identity',generation=manifest['generation'],page=999,journal_path=self.path)

class DurableTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db=AsyncSessionLocal();self.org=uuid.uuid4().hex;self.user=uuid.uuid4().hex
        self.principal=SimpleNamespace(organization_id=self.org,user_id=self.user,session_id='session',role='owner')
        self.db.add(Organization(id=self.org,name='Sync test',slug=self.org))
        self.db.add(User(id=self.user,email=self.user+'@example.invalid',hashed_password='synthetic'))
        await self.db.flush()
        self.db.add(OrganizationMembership(user_id=self.user,organization_id=self.org,role='owner',status='active'))
        self.company=TallyReadCompany(id=uuid.uuid4().hex,organization_id=self.org,identity='identity',name='Pilot Test',enabled=True,aliases=[],member_ids=[],refresh_requested=False)
        self.db.add(self.company)
        self.cfg=TallyConnection(organization_id=self.org,company='Pilot Test',godown='Main Location',purchase_ledger='Purchase',sales_ledger='Sales',test_company=True,version=1)
        self.db.add(self.cfg);await self.db.flush()
        data=await FakeTally().catalog('Pilot Test');data['cost_centres_enabled']=False
        self.snapshot={'generation':uuid.uuid4().hex,'identity':'identity','device_version':None,'as_of':'2026-10-08','collected_at':sync.now(),
                       'catalog':protocol.serialize_catalog(data),'items':[stock_row(i,data['units']) for i in data['items']]}
        self.db.add(TallySnapshot(company_id=self.company.id,**self.snapshot));await self.db.commit()
        self.parsed=commands.ParsedCommand(intent='purchase_create',item_name='Cement',party_name='Supplier',quantity='5',unit='bags',rate='350')
    async def asyncTearDown(self):
        await self.db.rollback()
        await self.db.execute(delete(TallyAction).where(TallyAction.organization_id==self.org))
        await self.db.execute(delete(Organization).where(Organization.id==self.org))
        await self.db.execute(delete(User).where(User.id==self.user));await self.db.commit();await self.db.close()
    async def preview(self):
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('Tally closed'))):
            result=await sync.preview_purchase(self.db,self.principal,self.parsed)
        self.assertIn('preview',result);return await self.db.get(TallyAction,result['preview']['token'])
    async def test_offline_preview_confirm_idempotency_projection_cancel(self):
        action=await self.preview()
        await sync.confirm_queued(self.db,self.principal,action)
        self.assertEqual(action.status,'queued')
        await sync.confirm_queued(self.db,self.principal,action)
        projection=await sync.stock_projection(self.db,self.company,'Cement','20','bags')
        self.assertEqual(projection['expected_quantity'],'25')
        await sync.confirm_queued(self.db,self.principal,action,approve=False)
        self.assertEqual((await sync.stock_projection(self.db,self.company,'Cement','20','bags'))['expected_quantity'],'20')
    async def test_worker_continues_after_rollback_without_expired_orm_access(self):
        from contextlib import asynccontextmanager
        from unittest.mock import Mock
        action=await self.preview()
        await sync.confirm_queued(self.db,self.principal,action)
        company_id=self.company.id
        original_scalars=self.db.scalars
        first=True
        async def scalars(statement,*args,**kwargs):
            nonlocal first
            if first:
                first=False
                return Mock(all=lambda:[company_id,company_id])
            return await original_scalars(statement,*args,**kwargs)
        @asynccontextmanager
        async def session():yield self.db
        @asynccontextmanager
        async def locked(_):yield True
        processor=AsyncMock(side_effect=RuntimeError('synthetic transient failure'))
        with patch('app.database.session.AsyncSessionLocal',session),patch.object(self.db,'scalars',scalars),patch.object(sync,'company_lock',locked),patch.object(sync,'process_action',processor),patch.object(sync,'capture_snapshot',AsyncMock(side_effect=TallyError('offline'))):
            await sync.sync_tick({})
        self.assertEqual(processor.await_count,2)
    async def test_mcp_nested_inventory_write_does_not_claim_expected_stock(self):
        action=await self.preview()
        action.backend='mcp';action.status='verification_pending'
        action.payload={'operation':'mcp_write','tool':'create_stock_journal',
            'arguments':{'sources':[{'stockItem':'Cement','qty':5,'unit':'bags'}]}}
        await self.db.commit()
        projection=await sync.stock_projection(self.db,self.company,'Cement','20','bags')
        self.assertIsNone(projection['expected_quantity'])
        self.assertEqual(projection['pending_quantity'],'0')
        self.assertEqual(projection['sync_status'],'verification_pending')
    async def test_expiry_wrong_session_changed_configuration(self):
        action=await self.preview();other=SimpleNamespace(**vars(self.principal));other.session_id='other'
        with self.assertRaises(HTTPException):await sync.confirm_queued(self.db,other,action)
        action.expires_at=sync.now()-timedelta(minutes=1)
        with self.assertRaises(HTTPException):await sync.confirm_queued(self.db,self.principal,action)
        action=await self.preview();self.cfg.version=2;await self.db.commit()
        with self.assertRaises(HTTPException):await sync.confirm_queued(self.db,self.principal,action)
    async def test_offline_graph_stock_uses_saved_data(self):
        request=commands.CommandRequest(intent='stock_read',fields=commands.CommandFields(item_name='Cement'))
        with patch.object(stock,'local_operation',AsyncMock(side_effect=TallyError('Tally closed'))),patch.object(commands,'plan_command',AsyncMock(return_value=commands.ParsedCommand(intent='stock_read',item_name='Cement'))):
            result=await graph.run_business_graph(request,self.principal,self.db)
        self.assertEqual(result['data_source'],'saved');self.assertIn('Last synced',result['response'])
        self.assertEqual(result['stock_results'][0]['items'][0]['quantity'],'20')
    async def test_no_snapshot_is_unknown_not_zero(self):
        await self.db.execute(delete(TallySnapshot).where(TallySnapshot.company_id==self.company.id));await self.db.commit()
        with patch.object(stock,'local_operation',AsyncMock(side_effect=TallyError('Tally closed'))):
            result=await stock.read_stock(self.db,self.principal,commands.ParsedCommand(intent='stock_read',item_name='Cement'))
        self.assertEqual(result['stock_results'][0]['status'],'unavailable')
    async def test_old_helper_explains_update_without_repairing(self):
        await self.db.execute(delete(TallySnapshot).where(TallySnapshot.company_id==self.company.id));await self.db.commit()
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('Setup needed: update Philixa Connect for saved data and purchase sync.'))):
            result=await sync.preview_purchase(self.db,self.principal,self.parsed)
        self.assertTrue(result['helper_update_required']);self.assertIn('pairing dobara zaroori nahi',result['response'])
    async def test_old_helper_cannot_downgrade_or_consume_v2_jobs(self):
        import json
        from app.core.redis import get_redis_client
        from app.api.v1.routes_tally_bridge import jobs,helper_status
        device=TallyDevice(id=uuid.uuid4().hex,organization_id=self.org,credential_hash='synthetic',revoked=False)
        self.db.add(device);self.company.device_id=device.id;await self.db.commit()
        redis=await get_redis_client();job_id=uuid.uuid4().hex
        keys=['tally:online:'+device.id,'tally:protocol:'+device.id,'tally:v2online:'+device.id,'tally:queue:'+device.id,'tally:queue:v2:'+device.id,'tally:job:'+job_id]
        try:
            await redis.set('tally:online:'+device.id,'1',ex=45)
            await jobs(2,device,self.db)
            await jobs(1,device,self.db)
            status=await helper_status(self.principal,self.db)
            self.assertEqual(status['protocol_version'],2);self.assertFalse(status['helper_update_required'])
            job={'id':job_id,'operation':'snapshot_start','device_id':device.id,'organization_id':self.org,'credential_version':'synthetic','company':self.company.name,'identity':self.company.identity,'as_of':'2026-10-08'}
            await redis.set('tally:job:'+job_id,json.dumps(job),ex=30)
            await redis.rpush('tally:queue:v2:'+device.id,json.dumps(job))
            self.assertIsNone((await jobs(1,device,self.db))['job'])
            self.assertEqual((await jobs(2,device,self.db))['job']['id'],job_id)
        finally:
            await redis.delete(*keys);await redis.aclose()
            from app.core.redis import close_redis_pool
            await close_redis_pool()
    async def test_uncertain_stock_projection_and_no_cancel(self):
        action=await self.preview();action.status='submitting';await self.db.commit()
        self.assertIsNone((await sync.stock_projection(self.db,self.company,'Cement','20','bags'))['expected_quantity'])
        await sync.confirm_queued(self.db,self.principal,action,approve=False);self.assertEqual(action.status,'submitting')
    async def test_verification_snapshot_atomic_removes_pending(self):
        action=await self.preview();await sync.confirm_queued(self.db,self.principal,action)
        data=copy.deepcopy(self.snapshot);data['items'][0]['quantity']='25'
        responses=[{'status':'ready'},{'status':'verified','voucher_number':'42'}]
        with patch.object(sync,'operation',AsyncMock(side_effect=responses)),patch.object(sync,'capture_snapshot',AsyncMock(return_value=data)):
            await sync.process_action(self.db,action,self.company)
        self.assertEqual(action.status,'verified')
        snap=await sync.saved_snapshot(self.db,self.company)
        projection=await sync.stock_projection(self.db,self.company,'Cement',snap.items[0]['quantity'],'bags')
        self.assertEqual(projection['expected_quantity'],'25');self.assertEqual(projection['pending_quantity'],'0')
    async def test_changed_authority_and_revoked_company(self):
        action=await self.preview();await sync.confirm_queued(self.db,self.principal,action)
        member=await self.db.get(OrganizationMembership,(self.user,self.org));member.role='member';await self.db.commit()
        with patch.object(sync,'operation',AsyncMock()) as operation:await sync.process_action(self.db,action,self.company)
        operation.assert_not_awaited();self.assertEqual(action.status,'needs_review')
        self.company.enabled=False;await self.db.commit()
        with self.assertRaises(TallyError):await sync.saved_snapshot(self.db,self.company)
    async def test_cancel_racing_validation_does_not_post(self):
        action=await self.preview();await sync.confirm_queued(self.db,self.principal,action)
        async def validate(*args,**kwargs):
            async with AsyncSessionLocal() as other:
                row=await other.get(TallyAction,action.token);row.status='cancelled';await other.commit()
            return {'status':'ready'}
        with patch.object(sync,'operation',AsyncMock(side_effect=validate)) as call:
            await sync.process_action(self.db,action,self.company)
        self.assertEqual(call.await_count,1);self.assertEqual(action.status,'cancelled')
    async def test_snapshot_failure_after_import_keeps_uncertainty(self):
        action=await self.preview();await sync.confirm_queued(self.db,self.principal,action)
        with patch.object(sync,'operation',AsyncMock(side_effect=[{'status':'ready'},{'status':'verified','voucher_number':'42'}])),patch.object(sync,'capture_snapshot',AsyncMock(side_effect=TallyError('timeout'))):
            with self.assertRaises(TallyError):await sync.process_action(self.db,action,self.company)
        self.assertEqual(action.status,'submitting')
        self.assertIsNone((await sync.stock_projection(self.db,self.company,'Cement','20','bags'))['expected_quantity'])
    async def test_helper_replacement_invalidates_saved_data(self):
        device=TallyDevice(id=uuid.uuid4().hex,organization_id=self.org,credential_hash='old',revoked=False)
        self.db.add(device);await self.db.flush();self.company.device_id=device.id
        snapshot=await self.db.get(TallySnapshot,self.company.id);snapshot.device_version='old';await self.db.commit()
        self.assertIsNotNone(await sync.saved_snapshot(self.db,self.company))
        device.credential_hash='new';await self.db.commit()
        self.assertIsNone(await sync.saved_snapshot(self.db,self.company))
    async def test_uncertain_mismatch_blocks_duplicate_preview(self):
        action=await self.preview();action.status='needs_review';action.result={'uncertain':True};await self.db.commit()
        with patch.object(sync,'refresh_company',AsyncMock(return_value=False)):
            result=await sync.preview_purchase(self.db,self.principal,self.parsed)
        self.assertNotIn('preview',result);self.assertIn('duplicate',result['response'])
    async def test_revocation_retains_submission_uncertainty(self):
        action=await self.preview();action.status='submitting';await self.db.commit()
        await sync.invalidate_actions(self.db,[self.company.id]);await self.db.commit()
        self.assertEqual(action.status,'needs_review');self.assertTrue(action.result['uncertain'])
        self.assertIsNone((await sync.stock_projection(self.db,self.company,'Cement','20','bags'))['expected_quantity'])
    async def test_incomplete_refresh_keeps_complete_snapshot(self):
        with patch.object(sync,'capture_snapshot',AsyncMock(side_effect=TallyError('Snapshot incomplete'))):
            with self.assertRaises(TallyError):await sync.refresh_company(self.db,self.company)
        snap=await sync.saved_snapshot(self.db,self.company);self.assertEqual(snap.generation,self.snapshot['generation'])
    async def test_add_stock_clarifies_purchase_vs_adjustment(self):
        result=await commands.execute_command(commands.CommandRequest(text='5 bags add'),self.principal,self.db,
            commands.ParsedCommand(intent='inventory_add',item_name='Cement',quantity='5',unit='bags'))
        self.assertIn('stock adjustment',result['response']);self.assertEqual(result['tally_choices'][0]['command']['intent'],'purchase_create')
        parsed=commands.guard_tally_scope(commands.CommandRequest(text='Cement ke 5 bags add krdo'),self.parsed)
        self.assertEqual(parsed.intent,'inventory_add')
    async def test_fresh_stock_question_leaves_unfinished_purchase(self):
        from app.api.v1.routes_voice import BusinessTurn
        request=commands.CommandRequest(text='cement kitna hai hamare pass',conversation_history=[BusinessTurn(role='user',content='add 5 cement bags'),BusinessTurn(role='assistant',content='Purchase ke liye party_name, rate bataiye.')])
        parsed=commands.guard_tally_scope(request,self.parsed)
        self.assertEqual(parsed.intent,'stock_read');self.assertIsNone(parsed.rate);self.assertIsNone(parsed.party_name)
        with patch.object(commands,'plan_command',AsyncMock(return_value=parsed)),patch.object(stock,'local_operation',AsyncMock(side_effect=TallyError('offline'))):
            result=await graph.run_business_graph(request,self.principal,self.db)
        self.assertIn('Last synced',result['response']);self.assertEqual(result['stock_results'][0]['items'][0]['quantity'],'20')
        self.assertFalse(commands.fresh_stock_question('Cement stock mein 5 bags add karo'))
    async def test_fresh_stock_interpreter_does_not_send_purchase_history(self):
        from unittest.mock import Mock
        import json
        provider=SimpleNamespace(generate_json=Mock(return_value=json.dumps({'intent':'stock_read','item_name':'Cement'})))
        settings=SimpleNamespace(ai_economy_provider='fake',ai_economy_model='fake',ai_review_provider='fake',ai_review_model='fake')
        request=commands.CommandRequest(text='Cement ka stock kitna hai?',conversation_history=[{'role':'user','content':'Purchase from Supplier at 350'}])
        with patch.object(commands,'get_settings',return_value=settings),patch.object(commands,'get_ai_provider',return_value=provider):
            parsed=await commands.interpret(request)
        self.assertEqual(parsed.intent,'stock_read');self.assertIn('"history": []',provider.generate_json.call_args.args[1])

    async def test_multiturn_purchase_reaches_form_then_preview_without_posting(self):
        from unittest.mock import Mock
        from sqlalchemy import select
        import json
        outputs=[
            {'intent':'purchase_create','item_name':'Cement','party_name':'Supplier'},
            {'intent':'purchase_create','item_name':'Cement','party_name':'Supplier','quantity':'8','unit':'bags'},
            {'intent':'purchase_create','item_name':'Cement','party_name':'Supplier','quantity':'8','unit':'bags','rate':'350'},
        ]
        provider=SimpleNamespace(generate_json=Mock(side_effect=[json.dumps(p) for p in outputs]))
        settings=SimpleNamespace(ai_economy_provider='fake',ai_economy_model='fake',ai_review_provider='fake',ai_review_model='fake')
        # Optional interpretation hints are not part of this test. Avoid sharing
        # the application's Redis pool across unittest's per-test event loops.
        cache=SimpleNamespace(get=AsyncMock(return_value=None),aclose=AsyncMock())
        history=[]
        with patch.object(commands,'get_settings',return_value=settings),patch.object(commands,'get_ai_provider',return_value=provider), \
                patch.object(commands,'get_redis_client',AsyncMock(return_value=cache)), \
                patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))):
            for index,text in enumerate(('Supplier se Cement purchase karna hai','quantity 8 bags','rate 350 per bag')):
                request=commands.CommandRequest(text=text,conversation_history=history)
                result=await graph.run_business_graph(request,self.principal,self.db)
                if index<2:
                    self.assertIn('tally_form',result)
                    self.assertEqual(result['tally_form']['intent'],'purchase_create')
                    self.assertNotIn('preview',result)
                else:
                    self.assertIn('preview',result)
                    action=await self.db.get(TallyAction,result['preview']['token'])
                    self.assertEqual(action.status,'preview')
                    self.assertEqual(action.payload['quantity'],'8')
                    self.assertEqual(action.payload['total'],'2800.00')
                history.extend([{'role':'user','content':text},{'role':'assistant','content':result['response']}])
        self.assertEqual(provider.generate_json.call_count,3)
        # Only an unapproved preview exists; text follow-ups cannot enqueue/post.
        actions=list((await self.db.scalars(select(TallyAction).where(TallyAction.organization_id==self.org))).all())
        self.assertEqual([a.status for a in actions],['preview'])

if __name__=='__main__':unittest.main()
