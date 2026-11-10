"""Real DB selection transactions; provider and native posting never run."""
import secrets,unittest
from datetime import timedelta
from unittest.mock import AsyncMock,patch
from sqlalchemy import delete
from fastapi import HTTPException
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.models.tally import TallySnapshot
from app.services import task_agent_service as tasks,purchase_draft_service as drafts
from app.services.task_agent_selection import offers
from app.services.purchase_identity import exact_master,master_identity,master_fingerprint
from app.services.tally_sync_protocol import deserialize_catalog
import scripts.test_tally_sync as fixtures

class SelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.DurableTests.asyncSetUp(self)
        from scripts.purchase_fixture_support import master_ids
        await master_ids(self.db,self.company.id)
        draft=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,
            content={'lines':[{'item_name':'Cement','quantity':'5','unit':'bags','rate':'350'}]}))
        snapshot=await self.db.get(TallySnapshot,self.company.id)
        master=exact_master(deserialize_catalog(snapshot.catalog),'supplier','Supplier')
        self.task=AgentTask(id=secrets.token_hex(16),organization_id=self.org,user_id=self.user,company_id=self.company.id,
            revision=0,status='needs_input',request_id=secrets.token_hex(16),request_hash='f'*64,created_at=tasks.now(),updated_at=tasks.now(),
            state={'draft_id':draft['id'],'messages':['5 bags Cement'],'session_id':'session','observations':[{'data':{
                'proposal':{'revision':0},'evidence_version':'evidence','selection_context':{'generation':snapshot.generation,
                    'masters':[{'field':'party_name','value':'Supplier','native_id':master_identity(master),'fingerprint':master_fingerprint(master)}]}}}]})
        self.task_id=self.task.id
        self.db.add(self.task);await self.db.commit()
        self.flag=patch.dict('os.environ',{'PHILIXA_TASK_SELECTIONS_ENABLED':'1','PHILIXA_TASK_AGENT_ENABLED':'1'});self.flag.start()
        self.queue=patch.object(tasks,'enqueue',AsyncMock());self.queue.start()
    async def asyncTearDown(self):
        self.flag.stop();self.queue.stop();await self.db.rollback()
        await self.db.execute(delete(AgentTask).where(AgentTask.id==self.task_id));await self.db.commit()
        await fixtures.DurableTests.asyncTearDown(self)
    def request(self,typed=False):
        offer=offers(self.task)[0]
        return tasks.TaskResume(expected_revision=0,request_id='selection-request-123456',message='Supplier',
            selection=None if typed else tasks.TaskSelection(reference=offer['reference'],draft_revision=0,evidence_version='evidence'))
    async def test_repeat_done_is_zero_call_selection_not_posting(self):
        import copy
        hint={'supplier':'Supplier','rates':[{'field':'0:rate','value':'999'}],'requires_confirmation':True}
        state=copy.deepcopy(self.task.state)
        state['observations'][-1]['data']['purchase_context']={'supplier_suggestion':hint}
        self.task.state=state;await self.db.commit()
        request=tasks.TaskResume(expected_revision=0,request_id='repeat-done-12345678',message='done')
        with patch('app.services.purchase_native_context.conversation_history',new=AsyncMock(return_value={'supplier_suggestion':hint})), \
             patch('app.services.task_agent_model.choose',new=AsyncMock()) as model:
            result=await tasks.resume(self.db,self.principal,self.task.id,request)
            model.assert_not_awaited()
        saved=await drafts.read_draft(self.db,self.principal,result['draft_id'])
        self.assertEqual(saved['content']['party_name'],'Supplier')
        self.assertEqual(saved['content']['lines'][0]['rate'],'350')
        self.assertIsNone(saved['content']['invoice_number'])
        self.assertIsNone(saved['content']['entry_date'])
        self.assertIsNone(result['action_id'])
        self.assertEqual(result['status'],'queued')

    async def test_exact_choice_zero_model_calls_and_idempotent(self):
        request=self.request()
        with patch('app.services.task_agent_model.choose',AsyncMock()) as model:
            first=await tasks.resume(self.db,self.principal,self.task.id,request)
            second=await tasks.resume(self.db,self.principal,self.task.id,request)
            self.assertEqual(first['revision'],second['revision']);model.assert_not_awaited()
        async with AsyncSessionLocal() as fresh:
            saved=await drafts.read_draft(fresh,self.principal,first['draft_id'])
            self.assertEqual(saved['content']['party_name'],'Supplier')
            self.assertEqual(saved['content']['lines'][0]['rate'],'350')
            self.assertEqual(saved['revision'],1);self.assertIsNone(saved['action_id'])
            self.assertEqual(saved['extraction_metadata']['agent_provenance']['party_name']['source_type'],'user_selection')
    async def test_typed_exact_choice_uses_same_path(self):
        result=await tasks.resume(self.db,self.principal,self.task.id,self.request(typed=True))
        row=await self.db.get(AgentTask,self.task.id,populate_existing=True)
        self.assertTrue(row.state['selection_refresh']);self.assertEqual(result['revision'],1)
    async def test_changed_snapshot_rejects_stale_offer(self):
        request=self.request();snapshot=await self.db.get(TallySnapshot,self.company.id);snapshot.generation=secrets.token_hex(16)
        from app.services.tally_sync_protocol import serialize_catalog
        catalog=deserialize_catalog(snapshot.catalog);exact_master(catalog,'supplier','Supplier').set('ALTERID','changed')
        snapshot.catalog=serialize_catalog(catalog);await self.db.commit()
        with self.assertRaises(HTTPException) as caught:await tasks.resume(self.db,self.principal,self.task.id,request)
        self.assertEqual(caught.exception.status_code,409)
    async def test_transaction_failure_rolls_back_draft_and_request(self):
        request=self.request()
        with patch.object(self.db,'commit',AsyncMock(side_effect=RuntimeError('synthetic commit failure'))):
            with self.assertRaises(RuntimeError):await tasks.resume(self.db,self.principal,self.task.id,request)
        await self.db.rollback()
        async with AsyncSessionLocal() as fresh:
            task=await fresh.get(AgentTask,self.task_id)
            saved=await drafts.read_draft(fresh,self.principal,task.state['draft_id'])
            self.assertIsNone(saved['content']['party_name']);self.assertEqual(task.revision,0)

if __name__=='__main__':unittest.main()
