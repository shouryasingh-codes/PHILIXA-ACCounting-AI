"""Controller invariants independent of model/network/database availability."""
import unittest
from app.services.task_agent_runtime import Tool, ToolResult, run, TransientReadError
from pydantic import BaseModel, ConfigDict

class Empty(BaseModel):
    model_config = ConfigDict(extra='forbid')


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_rationale_is_not_a_public_reply(self):
        async def choose(state, schemas):
            return dict(kind='needs_input', tool=None, arguments={},
                        summary='User wants info about a bill. Ask which bill.')
        result = await run({'messages':['explain this']}, [], choose, self.persist, self.budget)
        self.assertNotIn('User wants', result['summary'])
        self.assertNotIn('Ask which', result['summary'])

    async def test_public_question_is_separate_from_internal_rationale(self):
        async def choose(state, schemas):
            return dict(kind='needs_input', tool=None, arguments={},
                        summary='Two plausible invoices require disambiguation.',
                        user_response='Kaunsa bill check karun: pehla ya doosra?')
        result = await run({'messages':['explain this']}, [], choose, self.persist, self.budget)
        self.assertEqual(result['summary'], 'Kaunsa bill check karun: pehla ya doosra?')

    async def test_routing_seed_runs_once_without_replanning(self):
        class DraftArgs(BaseModel):
            message_index:int
            updates:list[dict]
        async def unavailable(*args):raise AssertionError('No duplicate classification/planning call')
        execute=__import__('unittest.mock',fromlist=['AsyncMock']).AsyncMock(return_value=ToolResult(
            status='needs_input',data={'response':'Supplier?'}))
        seed={'kind':'tool','tool':'create_purchase_draft','arguments':{'message_index':0,
            'updates':[{'path':'lines.0.quantity','value':'5','quote':'5'}]},'summary':'Draft'}
        result=await run({'messages':['5 bags'],'routing_first_step':seed},
            [Tool('create_purchase_draft','Draft',DraftArgs,'draft',self.authorize,execute)],
            unavailable,self.persist,unavailable)
        execute.assert_awaited_once();self.assertEqual(result['model_rounds'],0)
        self.assertNotIn('routing_first_step',result)
    async def test_attached_bill_seed_validates_same_draft_without_model_or_write(self):
        from unittest.mock import AsyncMock
        class Args(BaseModel):draft_id:str
        async def forbidden(*args):raise AssertionError('Unexpected planning or submission')
        execute=AsyncMock(return_value=ToolResult(status='needs_input',data={'response':'Supplier mapping required','issues':[{'code':'supplier_missing'}]}))
        state={'messages':['Prepare the attached purchase'],'attachment_document_ids':['doc'],'draft_id':'saved',
               'tool_groups':['documents','purchase'],'outcome':'draft','routing_first_step':{'kind':'tool','tool':'purchase_context','arguments':{'draft_id':'saved'},'summary':'Validate'}}
        tools=[Tool('purchase_context','Validate',Args,'draft',self.authorize,execute)]
        result=await run(state,tools,forbidden,self.persist,forbidden)
        execute.assert_awaited_once_with({'draft_id':'saved'})
        self.assertEqual(result['status'],'needs_input');self.assertNotIn('action_id',result)
        state['routing_first_step']['arguments']['draft_id']='another'
        with self.assertRaises(ValueError):await run(state,tools,forbidden,self.persist,forbidden)

    async def test_unstarted_help_does_not_need_model_or_tools(self):
        async def unavailable(*args):raise AssertionError('Help needs no model or budget')
        result=await run({'messages':['stock kitna hai','whatyou can do for me']},
            [],unavailable,self.persist,unavailable)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['model_rounds'],0)

    async def test_exact_stock_question_works_when_model_quota_is_exhausted(self):
        class StockArgs(BaseModel):
            item_name:str
        async def unavailable(*args):raise AssertionError('No model/budget needed for exact stock read')
        async def execute(args):
            self.assertEqual(args,{'item_name':'*'})
            return ToolResult(status='ok',verified=True,data={'response':'Paint 18 cans',
                'stock_results':[{'data_source':'live','items':[{'item':'Paint','quantity':'18'}]}]})
        result=await run({'outcome':'answer','company_id':'permitted','messages':['stock kitna hai']},
            [Tool('read_stock','Stock',StockArgs,'read',self.authorize,execute)],unavailable,self.persist,unavailable)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['model_rounds'],0)
        self.assertEqual(result['summary'],'Paint 18 cans')

    async def test_saved_stock_returns_without_second_model_or_quota_call(self):
        calls=[]
        async def choose(state,schemas):
            calls.append(1)
            if len(calls)>1:raise AssertionError('No second model call for stock result')
            return dict(kind='tool',tool='read_stock',arguments={},summary='Read')
        async def execute(args):
            return ToolResult(status='ok',verified=False,data={'response':'Saved stock: Paint 18 cans; timestamp shown',
                'stock_results':[{'data_source':'saved','items':[{'item':'Paint','quantity':'18'}]}]})
        result=await run({'outcome':'answer'},[Tool('read_stock','Stock',Empty,'read',self.authorize,execute)],choose,self.persist,self.budget)
        self.assertEqual(len(calls),1)
        self.assertIn('Paint 18',result['summary'])
        self.assertNotEqual(result['status'],'completed')
    async def test_premature_purchase_question_gets_one_bounded_tool_correction(self):
        async def execute(args):
            return ToolResult(status='needs_input',data={'draft_id':'saved','response':'Kis supplier se liya?'})
        decisions=iter([
            dict(kind='needs_input',tool=None,arguments={},summary='Need rate and invoice'),
            dict(kind='tool',tool='create_purchase_draft',arguments={},summary='Partial draft')])
        async def choose(state,schemas):return next(decisions)
        tool=Tool('create_purchase_draft','Partial purchase',Empty,'draft',self.authorize,execute)
        result=await run({'company_id':'company','messages':['5 bags cement kharide']},[tool],choose,self.persist,self.budget)
        self.assertEqual(result['draft_id'],'saved')
        self.assertEqual(result['summary'],'Kis supplier se liya?')
        self.assertEqual(result['model_rounds'],2)

    async def asyncSetUp(self):
        self.saved = []
        self.calls = 0

    async def persist(self, state):
        import copy
        self.saved.append(copy.deepcopy(state))

    async def budget(self):
        pass

    async def authorize(self, args):
        pass

    async def execute(self, args):
        self.calls += 1
        return ToolResult(status='ok', data={'stock': '25'}, verified=True)

    def tool(self, execute=None, effect='read'):
        return Tool('stock', 'Read stock', Empty, effect, self.authorize, execute or self.execute)

    async def test_model_finish_is_not_accounting_completion(self):
        async def choose(state, schemas):
            return dict(kind='finish', tool=None, arguments={}, summary='Done')
        result = await run({'observations': [{'verified': True}]}, [], choose, self.persist, self.budget)
        self.assertEqual(result['status'], 'needs_input')

    async def test_repeat_blocked_and_pending_saved_before_execution(self):
        async def choose(state, schemas):
            return dict(kind='tool', tool='stock', arguments={}, summary='Read')
        result = await run({}, [self.tool()], choose, self.persist, self.budget)
        self.assertEqual(self.calls, 1)
        first_pending=next(s for s in self.saved if s.get('executions'))
        self.assertEqual(first_pending['executions'][0]['status'], 'pending')
        self.assertEqual(result['status'], 'needs_input')

    async def test_interrupted_write_not_replayed(self):
        async def choose(*args):
            self.fail('Model must not run before reconciliation')
        result = await run({'executions': [{'status': 'pending', 'effect': 'write'}]},
            [self.tool()], choose, self.persist, self.budget)
        self.assertEqual(result['status'], 'verification_pending')
        self.assertEqual(self.calls, 0)

    async def test_transient_read_exactly_one_retry(self):
        async def execute(args):
            self.calls += 1
            if self.calls == 1:
                raise TransientReadError()
            return ToolResult(status='needs_input')
        async def choose(*args):
            return dict(kind='tool', tool='stock', arguments={}, summary='Read')
        await run({}, [self.tool(execute)], choose, self.persist, self.budget)
        self.assertEqual(self.calls, 2)

    async def test_write_never_retried(self):
        async def execute(args):
            self.calls += 1
            raise TransientReadError()
        async def choose(*args):
            return dict(kind='tool', tool='stock', arguments={}, summary='Write')
        with self.assertRaises(TransientReadError):
            await run({}, [self.tool(execute, 'write')], choose, self.persist, self.budget)
        self.assertEqual(self.calls, 1)

    async def test_unknown_tool_rejected_without_execution(self):
        async def choose(*args):
            return dict(kind='tool', tool='shell', arguments={}, summary='Run')
        with self.assertRaises(ValueError):
            await run({}, [self.tool()], choose, self.persist, self.budget)
        self.assertEqual(self.calls, 0)

    async def test_budget_denial_prevents_model_call(self):
        async def budget():
            raise ValueError('cap reached')
        async def choose(*args):
            self.fail('Paid model must not run after cap')
        with self.assertRaises(ValueError):
            await run({},[],choose,self.persist,budget)

    async def test_denied_permission_prevents_execution(self):
        async def authorize(args):
            raise PermissionError('membership changed')
        async def choose(*args):
            return dict(kind='tool',tool='stock',arguments={},summary='read')
        from dataclasses import replace
        with self.assertRaises(PermissionError):
            await run({},[replace(self.tool(),authorize=authorize)],choose,self.persist,self.budget)
        self.assertEqual(self.calls,0)

    async def test_interrupted_read_can_recover_once(self):
        async def choose(*args):
            return dict(kind='tool',tool='stock',arguments={},summary='read')
        import hashlib,json
        key=hashlib.sha256(json.dumps(['stock',{}],sort_keys=True).encode()).hexdigest()
        result=await run({'executions':[{'key':key,'tool':'stock','effect':'read','status':'pending'}]},
            [self.tool()],choose,self.persist,self.budget)
        self.assertEqual(self.calls,1)
        self.assertEqual(result['executions'][0]['status'],'interrupted_read')

    async def test_budget_failure_before_adapter_is_not_unknown_write(self):
        from app.services.task_agent_runtime import ExecutionNotStarted
        async def execute(args):raise ExecutionNotStarted()
        async def choose(*args):return dict(kind='tool',tool='stock',arguments={},summary='prepare')
        with self.assertRaises(ExecutionNotStarted):
            await run({},[self.tool(execute,'draft')],choose,self.persist,self.budget)
        self.assertEqual(self.saved[-1]['executions'][0]['status'],'not_started')

    async def test_finish_without_proof_cannot_claim_done(self):
        async def choose(*args):return dict(kind='finish',tool=None,arguments={},summary='Entry posted successfully')
        result=await run({},[],choose,self.persist,self.budget)
        self.assertEqual(result['status'],'needs_input')
        self.assertNotIn('posted successfully',result['summary'])


if __name__ == '__main__':
    unittest.main()
