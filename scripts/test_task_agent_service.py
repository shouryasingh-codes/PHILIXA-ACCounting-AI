"""Task lifecycle tests; unique synthetic identities, no Tally operations."""
import os
import secrets
import unittest
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
from fastapi import HTTPException
from sqlalchemy import delete
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask, AgentRun, AgentExecution
from app.services import task_agent_service as service


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_stock_topic_switch_preserves_prior_purchase_task(self):
        from app.api.v1.routes_business import command
        from app.services.business_command_service import CommandRequest
        from unittest.mock import AsyncMock
        from app.services.intent_router import RouteDecision
        decision=RouteDecision(intent='stock_read',relation='switch_topic',handler='domain_read',item_name='*',reason='semantic')
        with patch.object(service,'enqueue',AsyncMock()),patch.object(service.drafts,'list_companies',AsyncMock(return_value={'companies':[]})), \
             patch('app.services.business_router.reserve_model',AsyncMock()), \
             patch('app.services.intent_router_model.classify',AsyncMock(return_value=(decision,{}))), \
             patch('app.jobs.task_agent_jobs.principal_for',AsyncMock(return_value=self.principal)):

            first=await self.create()
            row=await self.db.get(AgentTask,first['task_id'])
            row.state={**row.state,'draft_id':'a'*32,'summary':'Purchase pending'};row.status='needs_input'
            await self.db.commit()
            original=dict(row.state)
            result=await command(CommandRequest(text='inventory dikhao',task_id=row.id,expected_revision=0,request_id='stock-topic-switch-123456'),self.principal,self.db)
            self.assertNotIn('task_id',result)
            self.assertEqual(result['issues'][0]['code'],'company_required')
            await self.db.refresh(row)
            self.assertEqual(row.state,original)
            self.assertEqual(row.revision,0)

    async def asyncSetUp(self):
        self.flag = patch.dict(os.environ,{'PHILIXA_TASK_AGENT_ENABLED':'1','PHILIXA_INTENT_ROUTER_ENABLED':'0'})
        self.flag.start()
        self.enqueue_patch=patch.object(service,'enqueue',AsyncMock());self.enqueue_patch.start()
        self.db = AsyncSessionLocal()
        self.principal = SimpleNamespace(organization_id='agent-test-'+secrets.token_hex(8),
            user_id='user',role='owner',session_id='synthetic-session')

    async def asyncTearDown(self):
        await self.db.rollback()
        from sqlalchemy import select
        ids = list((await self.db.scalars(select(AgentTask.id).where(
            AgentTask.organization_id == self.principal.organization_id))).all())
        for model in (AgentExecution,AgentRun):
            await self.db.execute(delete(model).where(model.task_id.in_(ids)))
        await self.db.execute(delete(AgentTask).where(AgentTask.id.in_(ids)))
        await self.db.commit()
        await self.db.close()
        self.enqueue_patch.stop()
        self.flag.stop()

    async def create(self):
        return await service.create(self.db,self.principal,service.TaskCreate(
            message='Read permitted companies',request_id='test-request-123456'))

    async def test_context_refresh_is_durable_and_idempotent(self):
        first=await self.create()
        row=await self.db.get(AgentTask,first['task_id'])
        row.state={**row.state,'draft_id':'a'*32}
        await self.db.commit()
        request=service.TaskResume(expected_revision=0,request_id='context-refresh-123456',context_refresh=True)
        result=await service.resume(self.db,self.principal,row.id,request)
        self.assertEqual(result['revision'],1)
        await self.db.refresh(row)
        self.assertTrue(row.state['selection_refresh'])
        self.assertEqual((await service.resume(self.db,self.principal,row.id,request))['revision'],1)

    async def test_unknown_details_save_without_model_or_enqueue(self):
        first=await self.create()
        row=await self.db.get(AgentTask,first['task_id'])
        row.state={**row.state,'draft_id':'a'*32,'observations':[{'data':{'purchase_assistant':{'draft_id':'a'*32},'response':'Bill number batayein.'}}]}
        await self.db.commit()
        request=service.TaskResume(expected_revision=0,request_id='unknown-details-123456',message='pata nahi')
        from unittest.mock import AsyncMock
        with patch.object(service,'enqueue',new=AsyncMock()) as queued:
            result=await service.resume(self.db,self.principal,row.id,request)
            queued.assert_not_awaited()
            self.assertIn('blank',result['response'])
            self.assertNotIn('Bill number batayein',result['response'])
            self.assertEqual(result['draft_id'],'a'*32)
            self.assertEqual((await service.resume(self.db,self.principal,row.id,request))['revision'],1)

    async def test_creation_idempotence_and_changed_payload(self):
        first = await self.create()
        self.assertEqual(first['task_id'],(await self.create())['task_id'])
        with self.assertRaises(HTTPException) as caught:
            await service.create(self.db,self.principal,service.TaskCreate(
                message='Different task',request_id='test-request-123456'))
        self.assertEqual(caught.exception.status_code,409)

    async def test_other_workspace_cannot_read(self):
        first = await self.create()
        other = SimpleNamespace(**{**vars(self.principal),'organization_id':'other'})
        with self.assertRaises(HTTPException) as caught:
            await service.scoped(self.db,other,first['task_id'])
        self.assertEqual(caught.exception.status_code,404)

    async def test_stale_revision_and_repeat_answer(self):
        first = await self.create()
        request = service.TaskResume(expected_revision=0,request_id='resume-request-123456',message='My answer')
        result = await service.resume(self.db,self.principal,first['task_id'],request)
        self.assertEqual(result['revision'],1)
        self.assertEqual((await service.resume(self.db,self.principal,first['task_id'],request))['revision'],1)
        with self.assertRaises(HTTPException) as caught:
            await service.resume(self.db,self.principal,first['task_id'],service.TaskResume(
                expected_revision=0,request_id='different-request-123456',message='stale'))
        self.assertEqual(caught.exception.status_code,409)

    async def test_cancel_does_not_delete_accounting_data(self):
        first = await self.create()
        result = await service.cancel(self.db,self.principal,first['task_id'],0)
        self.assertEqual(result['status'],'cancelled')
        self.assertIn('no Tally voucher deleted',result['response'])

    async def test_default_off_prevents_creation(self):
        with patch.dict(os.environ,{'PHILIXA_TASK_AGENT_ENABLED':'0'}):
            with self.assertRaises(HTTPException) as caught:
                await self.create()
            self.assertEqual(caught.exception.status_code,503)

    async def test_unrelated_approval_is_rejected_before_posting(self):
        first = await self.create()
        with self.assertRaises(HTTPException) as caught:
            await service.approve(self.db,self.principal,first['task_id'],service.TaskApproval(
                expected_revision=0,token='f'*32,approve=True))
        self.assertEqual(caught.exception.status_code,409)

    async def test_running_task_cannot_be_cancelled_or_revised(self):
        first = await self.create()
        row = await service.scoped(self.db,self.principal,first['task_id'],True)
        row.status='running'
        await self.db.commit()
        with self.assertRaises(HTTPException):
            await service.cancel(self.db,self.principal,first['task_id'],0)
        with self.assertRaises(HTTPException):
            await service.resume(self.db,self.principal,first['task_id'],service.TaskResume(
                expected_revision=0,request_id='new-resume-123456',message='change'))

    async def test_metrics_are_estimates_and_workspace_scoped(self):
        first=await self.create()
        self.db.add(AgentRun(id=secrets.token_hex(16),task_id=first['task_id'],revision=0,
            state={'usage':{'prompt_tokens':10000,'completion_tokens':2000}},created_at=service.now()))
        await self.db.commit()
        result=await service.metrics(self.db,self.principal,first['task_id'])
        from decimal import Decimal
        self.assertEqual(Decimal(result['estimated_model_cost_usd']),Decimal('0.00135'))
        self.assertFalse(result['time_savings_verified'])
        self.assertIn('not an invoice',result['cost_basis'])


if __name__ == '__main__':
    unittest.main()
