"""Actual graph integration and backend barriers; no provider or Tally writes."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from app.services import business_command_service as commands
from app.services import portfolio_copilot_service as graph
from app.services import tally_mcp_service as reports
from app.services import tally_sync as sync
from app.services.ask_client_service import AskClientService

class Integration(unittest.IsolatedAsyncioTestCase):
    async def test_purchase_report_noun_is_not_a_write(self):
        for text in ('Philixa Test ka purchase report 1 October 2026 se 2 October 2026 tak dikhao.',
                     'Show purchase register for October', 'Purchase report dikhao'):
            parsed=commands.guard_tally_scope(commands.CommandRequest(text=text),commands.ParsedCommand(
                intent='mcp_read',mcp_tool='get_purchase_register',mcp_arguments={'from':'2026-10-01','to':'2026-10-02'}))
            self.assertIsNone(parsed.unsupported_reason)
            self.assertEqual(parsed.mcp_arguments,{'from':'2026-10-01','to':'2026-10-02'})

    async def test_report_phrase_does_not_hide_mutation(self):
        for text in ('purchase report dikhao aur Cash ledger delete karo',
                     'purchase report update karo','purchase report dikhao aur 5 bags kharido'):
            parsed=commands.guard_tally_scope(commands.CommandRequest(text=text),commands.ParsedCommand(intent='mcp_read'))
            self.assertIsNotNone(parsed.unsupported_reason)

    async def test_report_menu_uses_graph_without_provider(self):
        with patch.dict('os.environ',{'PHILIXA_MCP_READ_ENABLED':'1'}),patch.object(commands,'get_ai_provider',side_effect=AssertionError('unexpected model')):
            parsed=await commands.interpret(commands.CommandRequest(text='Tally reports'))
            result=await reports.read_report(object(),object(),parsed)
        self.assertEqual(parsed.intent,'mcp_read');self.assertEqual(len(result['mcp_catalog']),26)
    async def test_purchase_only_rollout_does_not_enable_other_tools(self):
        with patch.dict('os.environ',{'PHILIXA_MCP_READ_ENABLED':'0','PHILIXA_PURCHASE_REPORT_ENABLED':'1'}):
            menu=await reports.read_report(object(),object(),commands.ParsedCommand(intent='mcp_read'))
            self.assertEqual([r['tool'] for r in menu['mcp_catalog']],['get_purchase_register'])
            blocked=await reports.read_report(object(),object(),commands.ParsedCommand(intent='mcp_read',mcp_tool='get_ledgers'))
            self.assertEqual(blocked['capability'],'disabled')

    async def test_report_dates_are_not_invented(self):
        with patch.dict('os.environ',{'PHILIXA_MCP_READ_ENABLED':'1'}):
            result=await reports.read_report(object(),object(),commands.ParsedCommand(intent='mcp_read',mcp_tool='get_profit_and_loss'))
        self.assertEqual(result['capability'],'report_fields_required');self.assertEqual(result['mcp_form']['fields']['mcp_arguments'],{})

    async def test_write_draft_route_uses_existing_graph(self):
        principal=SimpleNamespace(role='owner')
        request=commands.CommandRequest(intent='mcp_write')
        with patch.object(reports,'prepare_write',AsyncMock(return_value={'response':'draft'})) as draft,patch.object(commands,'get_ai_provider',side_effect=AssertionError('unexpected model')):
            events=[event async for event in graph.business_graph.astream({'request':request.model_dump(mode='json'),'operation':'command'},
                {'configurable':{'business_runtime':(principal,object())}},stream_mode='updates')]
        draft.assert_awaited_once();self.assertEqual([next(iter(e)) for e in events],['start','business_planner','tally_tool'])

    async def test_draft_menu_has_all_pinned_writes(self):
        with patch.dict('os.environ',{'PHILIXA_MCP_READ_ENABLED':'1'}):
            result=await reports.prepare_write(object(),SimpleNamespace(role='owner'),commands.ParsedCommand(intent='mcp_write'))
        self.assertEqual(len(result['mcp_write_catalog']),51)

    async def test_member_cannot_prepare_write(self):
        with self.assertRaises(HTTPException):
            await reports.prepare_write(object(),SimpleNamespace(role='member'),commands.ParsedCommand(intent='mcp_write'))

    async def test_compile_drafts_never_dispatched_by_worker(self):
        action=SimpleNamespace(backend='mcp',status='draft',result=None)
        with patch.object(sync,'operation',AsyncMock(side_effect=AssertionError('draft dispatched'))):
            await sync.process_action(object(),action,object())
        self.assertEqual(action.status,'draft')

    async def test_write_cannot_be_silently_routed_as_report(self):
        request=commands.CommandRequest(text='Cash ledger delete karo')
        parsed=commands.guard_tally_scope(request,commands.ParsedCommand(intent='mcp_read',mcp_tool='get_ledgers'))
        result=await reports.read_report(object(),object(),parsed)
        self.assertEqual(result['capability'],'blocked')
    async def test_actual_graph_without_rag_or_second_planner(self):
        request=commands.CommandRequest(intent='mcp_read',fields={'company_id':'a'*32,'mcp_tool':'get_ledgers'})
        with patch.object(reports,'read_report',AsyncMock(return_value={'response':'report'})) as report, \
             patch.object(commands,'get_ai_provider',side_effect=AssertionError('unexpected model call')), \
             patch.object(AskClientService,'business_history',side_effect=AssertionError('unexpected RAG')):
            events=[event async for event in graph.business_graph.astream(
                {'request':request.model_dump(mode='json'),'operation':'command'},
                {'configurable':{'business_runtime':(object(),object())}},stream_mode='updates')]
        self.assertEqual([next(iter(e)) for e in events],['start','business_planner','tally_tool'])
        report.assert_awaited_once()

    async def test_rollout_default_off(self):
        with patch.dict('os.environ',{'PHILIXA_MCP_READ_ENABLED':'0','PHILIXA_PURCHASE_REPORT_ENABLED':'0'}):
            result=await reports.read_report(object(),object(),commands.ParsedCommand(intent='mcp_read'))
        self.assertEqual(result['capability'],'disabled')

    async def test_wrong_operation_blocked_before_company_or_device_access(self):
        with patch.dict('os.environ',{'PHILIXA_MCP_READ_ENABLED':'1'}):
            result=await reports.read_report(object(),object(),commands.ParsedCommand(intent='mcp_read',mcp_tool='create_ledger'))
        self.assertEqual(result['capability'],'blocked')

    async def test_cross_company_requires_selection(self):
        with patch.dict('os.environ',{'PHILIXA_MCP_READ_ENABLED':'1'}),patch.object(reports,'resolve_scope',AsyncMock(return_value=[])):
            result=await reports.read_report(object(),object(),commands.ParsedCommand(intent='mcp_read',mcp_tool='get_ledgers'))
        self.assertEqual(result['capability'],'company_selection_required')

    async def test_original_backend_is_never_fallback_posted(self):
        action=SimpleNamespace(backend='mcp',status='submitting',result=None)
        db=SimpleNamespace(commit=AsyncMock())
        with patch.object(sync,'operation',AsyncMock(side_effect=AssertionError('fallback posting'))):
            await sync.process_action(db,action,object())
        self.assertEqual(action.status,'needs_review')
        self.assertTrue(action.result['uncertain'])
        db.commit.assert_awaited_once()

    async def test_unverified_backend_confirmation_blocked(self):
        principal=SimpleNamespace(organization_id='org',user_id='user',session_id='session',role='owner')
        action=SimpleNamespace(organization_id='org',user_id='user',session_id='session',backend='mcp',status='preview')
        with self.assertRaises(HTTPException) as error:
            await sync.confirm_queued(object(),principal,action)
        self.assertEqual(error.exception.status_code,409)

if __name__=='__main__':unittest.main()
