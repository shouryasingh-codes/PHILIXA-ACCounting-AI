"""Durable graph/worker acceptance with injected model/tools; no paid/native IO."""
import copy
import os
import secrets
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from sqlalchemy import delete, select
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask, AgentRun, AgentExecution
from app.models.purchase_agent import PurchaseGraphCheckpoint, PurchaseGraphWrite
from app.services.task_agent_runtime import Tool, ToolResult, Decision
from pydantic import BaseModel, ConfigDict
from app.services.task_agent_service import now
from app.jobs.task_agent_jobs import execute_agent_task


class Empty(BaseModel):
    model_config=ConfigDict(extra='forbid')


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_history_resumes_without_user_message_or_model(self):
        from datetime import timedelta
        ident=secrets.token_hex(16)
        principal=SimpleNamespace(user_id='u',organization_id='auto-context-'+ident,role='owner',session_id='s')
        async with AsyncSessionLocal() as db:
            db.add(AgentTask(id=ident,organization_id=principal.organization_id,user_id='u',company_id=None,
                request_id='auto-'+ident,request_hash='d'*64,revision=0,status='queued',
                state={'draft_id':'a'*32,'selection_refresh':True,'messages':['5 bags Cement']},created_at=now(),updated_at=now()))
            await db.commit()
        redis=SimpleNamespace(enqueue_job=AsyncMock())
        try:
            with patch('app.jobs.task_agent_jobs.principal_for',new=AsyncMock(return_value=principal)), \
                 patch('app.services.purchase_situation.state',new=AsyncMock(side_effect=[
                     {'response':'Pending','purchase_context':{'native_history_status':'processing'}},
                     {'response':'Supplier aur rate suggestion ready.','purchase_context':{'native_history_status':'ready'}}])), \
                 patch('app.services.task_agent_model.choose',new=AsyncMock(side_effect=AssertionError('No model'))) as choose:
                await execute_agent_task({'redis':redis},ident,0)
                redis.enqueue_job.assert_awaited_once()
                async with AsyncSessionLocal() as db:
                    row=await db.get(AgentTask,ident)
                    self.assertEqual(row.status,'waiting_context')
                    self.assertTrue(row.state['selection_refresh'])
                    self.assertLessEqual((__import__('datetime').datetime.fromisoformat(row.state['context_auto_until'])-now()).total_seconds(),120)
                    row.state={**row.state,'provider_retry_at':(now()-timedelta(seconds=1)).isoformat()}
                    await db.commit()
                await execute_agent_task({'redis':redis},ident,0)
                choose.assert_not_awaited()
            async with AsyncSessionLocal() as db:
                row=await db.get(AgentTask,ident)
                self.assertEqual(row.status,'needs_input')
                self.assertEqual(row.state['messages'],['5 bags Cement'])
                self.assertEqual(row.state['summary'],'Supplier aur rate suggestion ready.')
        finally:
            async with AsyncSessionLocal() as db:
                for model in (AgentExecution,AgentRun):await db.execute(delete(model).where(model.task_id==ident))
                await db.execute(delete(AgentTask).where(AgentTask.id==ident))
                await db.commit()

    async def test_context_refresh_never_calls_model(self):
        ident=secrets.token_hex(16)
        principal=SimpleNamespace(user_id='u',organization_id='refresh-'+ident,role='owner',session_id='s')
        async with AsyncSessionLocal() as db:
            db.add(AgentTask(id=ident,organization_id=principal.organization_id,user_id='u',company_id=None,
                request_id='refresh-'+ident,request_hash='e'*64,revision=0,status='queued',
                state={'draft_id':'a'*32,'selection_refresh':True,'messages':['Context status']},created_at=now(),updated_at=now()))
            await db.commit()
        try:
            with patch('app.jobs.task_agent_jobs.principal_for',new=AsyncMock(return_value=principal)), \
                 patch('app.services.purchase_situation.state',new=AsyncMock(return_value={'response':'Rate batayein.'})) as proposal, \
                 patch('app.services.task_agent_model.choose',new=AsyncMock(side_effect=AssertionError('No model allowed'))) as choose:
                await execute_agent_task({},ident,0)
                choose.assert_not_awaited()
                proposal.assert_awaited_once()
            async with AsyncSessionLocal() as db:
                row=await db.get(AgentTask,ident)
                self.assertEqual(row.status,'needs_input')
                self.assertEqual(row.state['summary'],'Rate batayein.')
                self.assertNotIn('selection_refresh',row.state)
        finally:
            async with AsyncSessionLocal() as db:
                for model in (AgentExecution,AgentRun):await db.execute(delete(model).where(model.task_id==ident))
                await db.execute(delete(AgentTask).where(AgentTask.id==ident))
                await db.commit()

    async def test_graph_records_tools_and_stops_for_review(self):
        ident=secrets.token_hex(16)
        org='worker-agent-test-'+ident
        principal=SimpleNamespace(user_id='u',organization_id=org,role='owner',session_id='s')
        async with AsyncSessionLocal() as db:
            db.add(AgentTask(id=ident,organization_id=org,user_id='u',company_id=None,
                request_id='request-'+ident,request_hash='f'*64,revision=0,status='queued',
                state={'messages':['Prepare purchase'],'executions':[],'observations':[]},created_at=now(),updated_at=now()))
            await db.commit()
        calls=[]
        async def execute(args):
            calls.append('context')
            return ToolResult(status='needs_input',data={'response':'Supplier ka exact naam chahiye.'})
        async def choose(state,schemas):
            return Decision(kind='tool',tool='context',arguments={},summary='Read context'),{'prompt_tokens':20,'completion_tokens':10}
        try:
            with patch.dict(os.environ,{'PHILIXA_TASK_AGENT_ENABLED':'1','PHILIXA_TASK_AGENT_DAILY_USD':'10'}), \
                 patch('app.jobs.task_agent_jobs.billing_limits',return_value=('paid',__import__('decimal').Decimal('1'),__import__('decimal').Decimal('0'))), \
                 patch('app.jobs.task_agent_jobs.principal_for',new=AsyncMock(return_value=principal)), \
                 patch('app.services.task_agent_tools.registry',return_value=[Tool('context','Read',Empty,'read',AsyncMock(),execute)]), \
                 patch('app.services.task_agent_model.choose',new=choose):
                await execute_agent_task({},ident)
            async with AsyncSessionLocal() as db:
                row=await db.get(AgentTask,ident)
                self.assertEqual(row.status,'needs_input')
                self.assertEqual(row.state['summary'],'Supplier ka exact naam chahiye.')
                self.assertIsNone(row.lease_token)
                events=(await db.scalars(select(AgentExecution).where(AgentExecution.task_id==ident))).all()
                self.assertEqual(len(events),1)
                self.assertEqual(events[0].data['status'],'settled')
            self.assertEqual(calls,['context'])
        finally:
            async with AsyncSessionLocal() as db:
                for model in (AgentExecution,AgentRun):
                    await db.execute(delete(model).where(model.task_id==ident))
                await db.execute(delete(AgentTask).where(AgentTask.id==ident))
                for model in (PurchaseGraphWrite,PurchaseGraphCheckpoint):
                    await db.execute(delete(model).where(model.thread_id==f'agent:{ident}:0'))
                await db.commit()


if __name__=='__main__':
    unittest.main()
