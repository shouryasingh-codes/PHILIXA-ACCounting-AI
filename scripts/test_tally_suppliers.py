import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.services import tally_suppliers as suppliers, business_command_service as commands
from app.services import portfolio_copilot_service as graph
from app.services.tally_sync_protocol import serialize_catalog
from scripts.test_tally import node


class Suppliers(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.company = SimpleNamespace(id='a'*32, name='Pilot Test')
        self.catalog = {'non_gst': True, 'cost_centres_enabled': False, 'items': [], 'units': [], 'godowns': [],
            'groups': [node('GROUP','Local Suppliers',PARENT='Sundry Creditors'), node('GROUP','Cycle',PARENT='Cycle')],
            'ledgers': [node('LEDGER','Sharma Traders',PARENT='Local Suppliers',EMAIL='test@example.com'),
                        node('LEDGER','Rahul',PARENT='Sundry Debtors'), node('LEDGER','Invalid',PARENT='Cycle')]}
        self.snapshot = SimpleNamespace(catalog=serialize_catalog(self.catalog),collected_at=datetime.now(timezone.utc))

    async def read(self, intent='supplier_list', live=True, **fields):
        with patch.object(suppliers,'resolve_scope',AsyncMock(return_value=[self.company])), \
             patch.object(suppliers,'refresh_company',AsyncMock(return_value=live)), \
             patch.object(suppliers,'saved_snapshot',AsyncMock(return_value=self.snapshot)):
            return await suppliers.read_suppliers(None,None,commands.ParsedCommand(intent=intent,**fields))

    async def test_nested_groups_customer_and_cycles(self):
        self.assertEqual([r.get('NAME') for r in suppliers.supplier_rows(self.catalog)],['Sharma Traders'])
        result=await self.read()
        self.assertEqual(result['tally_choices'][0]['command']['fields']['party_name'],'Sharma Traders')
        self.assertIn('Tally live suppliers',result['response'])

    async def test_saved_is_never_live(self):
        result=await self.read(live=False)
        self.assertIn('Saved Tally suppliers',result['response']);self.assertNotIn('Tally live suppliers',result['response'])

    async def test_detail_and_customer_role(self):
        result=await self.read('supplier_read',party_name='Sharma Traders')
        self.assertIn('test@example.com',result['response'])
        result=await self.read('supplier_read',party_name='Rahul')
        self.assertIn('Sundry Debtors',result['response']);self.assertEqual(result['supplier_results'],[])

    async def test_ambiguity_requires_choice(self):
        self.catalog['ledgers'].append(node('LEDGER','Sharma Cement',PARENT='Sundry Creditors'))
        self.snapshot.catalog=serialize_catalog(self.catalog)
        result=await self.read('supplier_read',party_name='Sharma')
        self.assertEqual(len(result['tally_choices']),2);self.assertEqual(result['supplier_results'],[])

    async def test_old_snapshot_warns_incomplete(self):
        del self.snapshot.catalog['groups']
        self.assertIn('subgroup coverage unverified',(await self.read())['response'])

    async def test_revoked_grant_during_read_releases_no_ledger(self):
        with patch.object(suppliers,'resolve_scope',AsyncMock(side_effect=[[self.company],[]])), \
             patch.object(suppliers,'refresh_company',AsyncMock(return_value=True)), \
             patch.object(suppliers,'saved_snapshot',AsyncMock(return_value=self.snapshot)):
            result=await suppliers.read_suppliers(None,None,commands.ParsedCommand(intent='supplier_list'))
        self.assertNotIn('Sharma',result['response']);self.assertEqual(result['tally_choices'],[])

    async def test_fresh_questions_do_not_inherit_purchase(self):
        for text in ['hamara supplier kon hai','hamare suppliers kaun hain','Supplier list','सप्लायर कौन है']:
            parsed=await commands.interpret(commands.CommandRequest(text=text))
            self.assertEqual(parsed.intent,'supplier_list');self.assertIsNone(parsed.quantity)
        parsed=await commands.interpret(commands.CommandRequest(text='Sharma Traders ye kon hai'),tally_names={'suppliers':['Sharma Traders']})
        self.assertEqual(parsed.intent,'supplier_read')
        self.assertEqual(graph.business_route({'parsed':parsed.model_dump()}),'tally_tool')

    async def test_actual_graph_executes_typed_read_without_rag(self):
        parsed=commands.ParsedCommand(intent='supplier_list')
        with patch.object(commands,'plan_command',AsyncMock(return_value=parsed)), \
             patch.object(suppliers,'resolve_scope',AsyncMock(return_value=[self.company])), \
             patch.object(suppliers,'refresh_company',AsyncMock(return_value=True)), \
             patch.object(suppliers,'saved_snapshot',AsyncMock(return_value=self.snapshot)), \
             patch.object(commands,'business_chat',side_effect=AssertionError('No synthesis')), \
             patch('app.services.ask_client_service.AskClientService.business_history',side_effect=AssertionError('No RAG')):
            events=[e async for e in graph.business_graph.astream(
                {'request':commands.CommandRequest(intent='supplier_list').model_dump(mode='json'),'operation':'command'},
                {'configurable':{'business_runtime':(None,None)}},stream_mode='updates')]
        self.assertEqual([next(iter(e)) for e in events],['start','business_planner','tally_tool'])
        self.assertIn('Sharma Traders',str(events[-1]['tally_tool']['result']['tally_choices']))

if __name__=='__main__':unittest.main()
