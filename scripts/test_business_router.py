"""PostgreSQL routing lifecycle with mocked provider/domain reads; no native writes."""
import asyncio
import sys
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
import copy
import os
import secrets
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from fastapi import HTTPException
from sqlalchemy import delete,select
from app.models.agent_task import AgentTask,AgentRun,AgentExecution
from app.models.business_route import BusinessRoute
from app.services import business_router as router,task_agent_service as tasks
from app.services.business_command_service import CommandRequest
from app.services.intent_router import RouteDecision
from app.services.task_agent_runtime import Tool,ToolResult
from app.services.task_agent_tools import StockQuery
import scripts.test_tally_sync as fixtures


class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.DurableTests.asyncSetUp(self)
        self.patches=[patch.dict(os.environ,{'PHILIXA_TASK_AGENT_ENABLED':'1','PHILIXA_INTENT_ROUTER_ENABLED':'1'}),
            patch('app.jobs.task_agent_jobs.principal_for',new=AsyncMock(return_value=self.principal)),
            patch.object(tasks,'enqueue',new=AsyncMock()),
            patch.object(router,'reserve_model',new=AsyncMock()),
            patch('app.services.intent_router_model.classify',new=AsyncMock(return_value=(RouteDecision(intent='help',relation='standalone',handler='direct_reply',reason='semantic_help',conversational_reply='Supported tasks explained here.'),{})))]
        for p in self.patches:p.start()

    async def asyncTearDown(self):
        await self.db.rollback()
        ids=list((await self.db.scalars(select(AgentTask.id).where(AgentTask.organization_id==self.org))).all())
        for model in (AgentRun,AgentExecution):await self.db.execute(delete(model).where(model.task_id.in_(ids)))
        await self.db.execute(delete(AgentTask).where(AgentTask.id.in_(ids)))
        await self.db.execute(delete(BusinessRoute).where(BusinessRoute.organization_id==self.org))
        await self.db.commit()
        for p in self.patches:p.stop()
        await fixtures.DurableTests.asyncTearDown(self)

    def request(self,text,**kw):
        return CommandRequest(text=text,request_id=secrets.token_hex(16),**kw)

    async def test_help_is_semantic_idempotent_and_payload_reuse_rejected(self):
        request=self.request('tu maire liye kiya kr sakta hai')
        async def reserve(db,row):
            row.telemetry={**row.telemetry,'model_attempts':1}
        with patch.object(router,'reserve_model',new=AsyncMock(side_effect=reserve)):
            result=await router.route(self.db,self.principal,request)
            replay=await router.route(self.db,self.principal,request)
        self.assertEqual(result,replay);self.assertNotIn('task_id',result)
        saved=await self.db.get(BusinessRoute,result['route_id'])
        self.assertEqual(saved.telemetry['path'],'model')
        with self.assertRaises(HTTPException) as error:
            await router.route(self.db,self.principal,request.model_copy(update={'text':'purchase karo'}))
        self.assertEqual(error.exception.status_code,409)

    async def test_stock_is_direct_read_and_prior_purchase_unchanged(self):
        created=await tasks.create(self.db,self.principal,tasks.TaskCreate(message='5 Cement bags',request_id=secrets.token_hex(16),company_id=self.company.id))
        row=await tasks.scoped(self.db,self.principal,created['task_id']);row.status='needs_input';await self.db.commit()
        before=copy.deepcopy(row.state)
        execute=AsyncMock(return_value=ToolResult(status='ok',verified=False,data={'response':'Saved Cement 30 bags',
            'stock_results':[{'data_source':'saved','quantity':'30'}]}))
        authorize=AsyncMock()
        tool=Tool('read_stock','Stock',StockQuery,'read',authorize,execute)
        with patch('app.services.task_agent_tools.registry',return_value=[tool]), \
             patch.object(router,'reserve_model',new=AsyncMock(side_effect=AssertionError('No model'))):
            result=await router.route(self.db,self.principal,self.request('stock kitna hai',task_id=row.id,expected_revision=row.revision))
        self.assertEqual(result['response'],'Saved Cement 30 bags');self.assertNotIn('task_id',result)
        self.assertEqual(row.state,before);authorize.assert_awaited_once();execute.assert_awaited_once()

    async def test_model_purchase_creates_once_with_seed(self):
        message='5 Cement bags rate 350'
        decision=RouteDecision(intent='purchase',relation='standalone',handler='agent',reason='explicit',
            explicit_fields=[{'path':'lines.0.item_name','value':'Cement','quote':'Cement'},
                {'path':'lines.0.quantity','value':'5','quote':'5'},{'path':'lines.0.rate','value':'350','quote':'350'}])
        request=self.request(message,fields={'company_id':self.company.id})
        with patch.object(router,'reserve_model',new=AsyncMock()), \
             patch('app.services.intent_router_model.classify',new=AsyncMock(return_value=(decision,{'total_tokens':100}))) as classify:
            result=await router.route(self.db,self.principal,request)
            again=await router.route(self.db,self.principal,request)
        self.assertEqual(result,again);classify.assert_awaited_once()
        task=await tasks.scoped(self.db,self.principal,result['task_id'])
        self.assertEqual(task.state['routing_first_step']['tool'],'create_purchase_draft')
        self.assertEqual(len(list((await self.db.scalars(select(AgentTask).where(AgentTask.organization_id==self.org))).all())),1)

    async def test_stale_revision_cross_workspace_and_changed_authority(self):
        task=await tasks.create(self.db,self.principal,tasks.TaskCreate(message='5 Cement bags',request_id=secrets.token_hex(16),company_id=self.company.id))
        with self.assertRaises(HTTPException) as error:
            await router.route(self.db,self.principal,self.request('Sharma',task_id=task['task_id'],expected_revision=99))
        self.assertEqual(error.exception.status_code,409)
        await self.db.rollback()
        other=SimpleNamespace(**{**self.principal.__dict__,'organization_id':'other'})
        with self.assertRaises(HTTPException) as error:
            await router.route(self.db,other,self.request('help',task_id=task['task_id'],expected_revision=0))
        self.assertEqual(error.exception.status_code,404)
        await self.db.rollback()
        with patch('app.jobs.task_agent_jobs.principal_for',new=AsyncMock(side_effect=HTTPException(403,'revoked'))):
            with self.assertRaises(HTTPException):await router.route(self.db,self.principal,self.request('hi'))

    async def test_quota_failure_is_clear_not_queued(self):
        from app.ai.groq_gateway import QuotaDeferred
        with patch.object(router,'reserve_model',new=AsyncMock(side_effect=QuotaDeferred('local_cap'))):
            result=await router.route(self.db,self.principal,self.request('Could you explain your capabilities in detail?'))
        self.assertEqual(result['status'],'needs_input');self.assertNotIn('task_id',result)
        self.assertEqual(result['issues'][0]['code'],'local_cap')

    async def test_explicit_routing_retry_is_idempotent_and_cannot_retry_dispatch(self):
        from app.ai.groq_gateway import QuotaDeferred
        from app.services import business_conversation_service as chats
        conv=await chats.create_conversation(self.db,self.principal,chats.ConversationCreate(organization_id=self.org))
        request=self.request('Describe the tasks you support',conversation_id=conv['id'],conversation_revision=0)
        with patch.object(router,'reserve_model',new=AsyncMock(side_effect=QuotaDeferred('local_cap'))):
            failed=await router.route(self.db,self.principal,request)
        self.assertTrue(failed['can_retry_routing'])
        decision=RouteDecision(intent='help',relation='standalone',handler='direct_reply',reason='semantic_help',conversational_reply='I can help with supported tasks.')
        with patch.object(router,'reserve_model',new=AsyncMock()),patch('app.services.intent_router_model.classify',new=AsyncMock(return_value=(decision,{}))) as model:
            first=await router.retry(self.db,self.principal,failed['route_id'],'retry-routing-stable-1234')
            chat=await chats.scoped_conversation(self.db,self.principal,conv['id']);chat.revision+=1;await self.db.commit()
            again=await router.retry(self.db,self.principal,failed['route_id'],'retry-routing-stable-1234')
            self.assertEqual(first,again);model.assert_awaited_once()
        with self.assertRaises(HTTPException):await router.retry(self.db,self.principal,first['route_id'],'retry-completed-123456')
        self.assertEqual(first['response_kind'],'product_help')
        self.assertNotIn('task_id',first)

    async def test_free_text_task_id_is_only_a_candidate_not_required_revision(self):
        created=await tasks.create(self.db,self.principal,tasks.TaskCreate(message='5 bags',request_id=secrets.token_hex(16),company_id=self.company.id))
        row=await tasks.scoped(self.db,self.principal,created['task_id']);before=copy.deepcopy(row.state)
        result=await router.route(self.db,self.principal,self.request('what can you do',task_id=row.id))
        self.assertEqual(result['response_kind'],'product_help');self.assertEqual(row.state,before)

    async def test_social_conversation_guard_does_not_create_or_resume_accounting_task(self):
        decision=RouteDecision(intent='smalltalk',relation='standalone',handler='direct_reply',reason='semantic_smalltalk',conversational_reply='Main Philixa hoon.')
        with patch.dict(os.environ,{'PHILIXA_INTENT_ROUTER_ENABLED':'0','PHILIXA_TASK_AGENT_ENABLED':'1'}), \
             patch.object(router,'reserve_model',new=AsyncMock()), \
             patch('app.services.intent_router_model.classify',new=AsyncMock(return_value=(decision,{}))) as classify, \
             patch.object(tasks,'create',new=AsyncMock(side_effect=AssertionError('No task for social chat'))), \
             patch.object(tasks,'resume',new=AsyncMock(side_effect=AssertionError('No accounting resume'))):
            self.assertTrue(router.frontdoor_enabled());self.assertFalse(router.enabled())
            for message in ('or bata kiya haal hai','How has your day been?','Shukriya, milte hain phir'):
                result=await router.route(self.db,self.principal,self.request(message))
                self.assertEqual(result['status'],'completed')
                self.assertEqual(result['response_kind'],'smalltalk')
                self.assertEqual(result['routing_mode'],'conversation_guard')
                self.assertNotIn('task_id',result)
            self.assertEqual(classify.await_count,3)

    async def test_social_answers_are_preserved_and_replayed_without_new_call(self):
        answers=[]
        for message,answer in [('tera naam kya hai','Mera naam Philixa hai.'),('bye bro','Phir milte hain!')]:
            request=self.request(message)
            decision=RouteDecision(intent='smalltalk',relation='standalone',handler='direct_reply',
                reason='semantic',conversational_reply=answer)
            with patch.object(router,'reserve_model',AsyncMock()),patch('app.services.intent_router_model.classify',AsyncMock(return_value=(decision,{}))) as classify:
                result=await router.route(self.db,self.principal,request)
                replay=await router.route(self.db,self.principal,request)
            self.assertEqual(result['response'],answer)
            self.assertEqual(result,replay)
            classify.assert_awaited_once()
            self.assertNotIn('task_id',result)
            answers.append(result['response'])
        self.assertNotEqual(*answers)

    async def test_output_failure_retains_diagnostic_without_accounting_menu(self):
        from app.services.intent_router_model import RoutingOutputError
        request=self.request('Do you remember who I am?')
        diagnostic=[{'field':'conversational_reply','type':'value_error'}]
        with patch.object(router,'reserve_model',AsyncMock()),patch('app.services.intent_router_model.classify',AsyncMock(side_effect=RoutingOutputError(diagnostic))):
            result=await router.route(self.db,self.principal,request)
        row=await self.db.get(BusinessRoute,result['route_id'])
        self.assertEqual(row.telemetry['routing_diagnostic'],diagnostic)
        self.assertNotIn('purchase',result['response'])
        self.assertNotIn('task_id',result)

    async def test_capability_answer_is_specific_not_universal_catalogue(self):
        examples=[('Could you browse the web?', 'help', 'No web search tool is connected.'),
                  ('Can you transfer money?', 'help', 'I cannot make bank transfers.'),
                  ('Book a flight', 'unsupported', 'I cannot book flights.')]
        for message,intent,answer in examples:
            decision=RouteDecision(intent=intent,relation='standalone',handler='clarify' if intent=='unsupported' else 'direct_reply',
                reason='semantic',conversational_reply=answer)
            with patch.object(router,'reserve_model',AsyncMock()),patch('app.services.intent_router_model.classify',AsyncMock(return_value=(decision,{}))),patch.object(tasks,'create',AsyncMock(side_effect=AssertionError('No task'))):
                result=await router.route(self.db,self.principal,self.request(message))
            self.assertEqual(result['response'],answer)
            self.assertNotIn('task_id',result)

    async def test_access_rejection_is_not_unclear_input_or_quota(self):
        import urllib.error
        from app.ai.provider import AIExtractionError
        for status,reason in [(401,'provider_authentication_failed'),(403,'provider_access_denied')]:
            error=AIExtractionError('Provider rejected request')
            error.__cause__=urllib.error.HTTPError('https://api.groq.com',status,'rejected',{},None)
            with patch('app.services.intent_router_model.classify',AsyncMock(side_effect=error)):
                result=await router.route(self.db,self.principal,self.request('Explain your role'))
            self.assertEqual(result['issues'][0]['code'],reason)
            self.assertIn(str(status),result['response'])
            self.assertNotIn('task_id',result)
            row=await self.db.get(BusinessRoute,result['route_id'])
            self.assertEqual(row.telemetry['provider_http_status'],status)

    async def test_legacy_task_hint_is_scoped_and_does_not_force_social_resume(self):
        created=await tasks.create(self.db,self.principal,tasks.TaskCreate(message='5 bags',request_id=secrets.token_hex(16),company_id=self.company.id))
        task=await tasks.scoped(self.db,self.principal,created['task_id']);task.status='needs_input';await self.db.commit()
        before=copy.deepcopy(task.state)
        request=self.request('How are things?',candidate_task_id=task.id)
        context=await router.context_for(self.db,self.principal,request)
        self.assertEqual(context['task_id'],task.id)
        decision=RouteDecision(intent='smalltalk',relation='switch_topic',handler='direct_reply',reason='semantic',conversational_reply='Main Philixa hoon.')
        with patch.object(router,'reserve_model',AsyncMock()),patch('app.services.intent_router_model.classify',AsyncMock(return_value=(decision,{}))):
            result=await router.route(self.db,self.principal,request)
        self.assertNotIn('task_id',result);self.assertEqual(task.state,before)
        other=SimpleNamespace(**{**self.principal.__dict__,'organization_id':'other'})
        with self.assertRaises(HTTPException):await router.context_for(self.db,other,request)

    async def test_compatibility_business_flow_does_not_enable_unaccepted_seed(self):
        request=self.request('Cement 5 bags',fields={'company_id':self.company.id})
        decision=RouteDecision(intent='purchase',relation='standalone',handler='agent',reason='semantic_purchase',
            explicit_fields=[{'path':'lines.0.quantity','value':'5','quote':'5'}])
        with patch.dict(os.environ,{'PHILIXA_INTENT_ROUTER_ENABLED':'0'}), \
             patch.object(router,'reserve_model',new=AsyncMock()), \
             patch('app.services.intent_router_model.classify',new=AsyncMock(return_value=(decision,{}))):
            result=await router.route(self.db,self.principal,request)
        task=await tasks.scoped(self.db,self.principal,result['task_id'])
        self.assertIsNone(task.state.get('routing_first_step'))
        self.assertEqual(task.state['outcome'],'verified_entry')

    async def test_ambiguous_yes_does_not_submit(self):
        with patch.object(router,'dispatch',wraps=router.dispatch) as dispatch:
            result=await router.route(self.db,self.principal,self.request('haan'))
        self.assertEqual(result['response_kind'],'routing_clarification')
        self.assertEqual(dispatch.call_args.args[4].handler,'clarify')

    async def test_context_change_during_classification_prevents_task(self):
        task=await tasks.create(self.db,self.principal,tasks.TaskCreate(message='5 bags',request_id=secrets.token_hex(16),company_id=self.company.id))
        row=await tasks.scoped(self.db,self.principal,task['task_id']);row.status='needs_input';await self.db.commit()
        async def classify(*args):
            row.revision+=1;await self.db.commit()
            return RouteDecision(intent='task_reply',relation='continue_current',handler='domain_continuation',target_task_id=row.id,reason='reply'),{}
        with patch.object(router,'reserve_model',new=AsyncMock()),patch('app.services.intent_router_model.classify',side_effect=classify):
            with self.assertRaises(HTTPException) as error:
                await router.route(self.db,self.principal,self.request('rate 340',task_id=row.id,expected_revision=0))
        self.assertEqual(error.exception.status_code,409)

    async def test_help_topic_switch_keeps_foreground_but_yes_cannot_answer_old_task(self):
        from app.services import business_conversation_service as chats
        conv=await chats.create_conversation(self.db,self.principal,chats.ConversationCreate(organization_id=self.org))
        decision=RouteDecision(intent='purchase',relation='standalone',handler='agent',reason='new')
        with patch.object(router,'reserve_model',new=AsyncMock()),patch('app.services.intent_router_model.classify',new=AsyncMock(return_value=(decision,{}))):
            first=await router.route(self.db,self.principal,self.request('Buy Cement',conversation_id=conv['id'],conversation_revision=0))
        task=await tasks.scoped(self.db,self.principal,first['task_id']);task.status='needs_input';await self.db.commit()
        before=copy.deepcopy(task.state)
        help_result=await router.route(self.db,self.principal,self.request('what can you do',conversation_id=conv['id'],conversation_revision=0))
        self.assertNotIn('task_id',help_result)
        context=await router.context_for(self.db,self.principal,self.request('haan',conversation_id=conv['id']))
        self.assertEqual(context['task_id'],task.id);self.assertFalse(context['focused'])
        answer=await router.route(self.db,self.principal,self.request('haan',conversation_id=conv['id']))
        self.assertEqual(answer['response_kind'],'routing_clarification');self.assertEqual(task.state,before)

    async def test_parallel_duplicate_classification_is_not_sent_twice(self):
        from app.database.session import AsyncSessionLocal
        decision=RouteDecision(intent='help',relation='standalone',handler='direct_reply',reason='semantic_help',conversational_reply='I can help with supported tasks.')
        async def classify(*args):
            await asyncio.sleep(.05)
            return decision,{}
        request=self.request('Describe how you could help my business')
        async with AsyncSessionLocal() as second:
            with patch.object(router,'reserve_model',new=AsyncMock()),patch('app.services.intent_router_model.classify',side_effect=classify) as model:
                a,b=await asyncio.gather(router.route(self.db,self.principal,request),router.route(second,self.principal,request))
                model.assert_awaited_once()
        self.assertEqual(a['route_id'],b['route_id'])
        rows=list((await self.db.scalars(select(BusinessRoute).where(BusinessRoute.organization_id==self.org))).all())
        self.assertEqual(len(rows),1)

    async def test_dispatch_recovery_finds_stable_task_without_replay(self):
        decision=RouteDecision(intent='purchase',relation='standalone',handler='agent',reason='new')
        request=self.request('Buy Paint')
        original=router.dispatch
        async def interrupted(*args):
            await original(*args)
            raise ConnectionError('lost response after commit')
        with patch.object(router,'reserve_model',new=AsyncMock()),patch('app.services.intent_router_model.classify',new=AsyncMock(return_value=(decision,{}))),patch.object(router,'dispatch',side_effect=interrupted):
            uncertain=await router.route(self.db,self.principal,request)
        self.assertEqual(uncertain['issues'][0]['code'],'dispatch_uncertain')
        result=await router.route(self.db,self.principal,request)
        self.assertIn('task_id',result)
        rows=list((await self.db.scalars(select(AgentTask).where(AgentTask.organization_id==self.org))).all())
        self.assertEqual(len(rows),1)

    async def test_deleted_old_draft_does_not_break_help(self):
        created=await tasks.create(self.db,self.principal,tasks.TaskCreate(message='5 bags',request_id=secrets.token_hex(16),company_id=self.company.id))
        row=await tasks.scoped(self.db,self.principal,created['task_id'])
        row.state={**row.state,'draft_id':'f'*32};row.status='needs_input';await self.db.commit()
        result=await router.route(self.db,self.principal,self.request('what can you do',task_id=row.id,expected_revision=0))
        self.assertEqual(result['response_kind'],'product_help')

    async def test_forged_selection_fails_before_classification(self):
        with patch.object(router,'reserve_model',new=AsyncMock()) as model:
            with self.assertRaises(HTTPException) as error:
                await router.route(self.db,self.principal,self.request('Sharma',selection={'reference':'forged'}))
            self.assertEqual(error.exception.status_code,422);model.assert_not_awaited()

    async def test_invalid_model_evidence_is_clarification_not_provider_outage(self):
        from app.services.intent_router_model import RoutingOutputError
        with patch.object(router,'reserve_model',new=AsyncMock()),patch('app.services.intent_router_model.classify',new=AsyncMock(side_effect=RoutingOutputError([]))):
            result=await router.route(self.db,self.principal,self.request('Meri purani purchase badal do'))
        self.assertEqual(result['issues'][0]['code'],'routing_unclear')
        self.assertNotIn('task_id',result)


if __name__=='__main__':unittest.main()
