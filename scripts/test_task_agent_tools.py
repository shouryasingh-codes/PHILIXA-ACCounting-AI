"""Adapter evidence and immutable audit revision regressions; no provider/Tally."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.services import task_agent_tools as tools
from app.services import task_agent_service as service

class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_literal_no_discount_is_zero_but_never_zero_tax_or_rate(self):
        from app.services.purchase_message import grounded,MessageFields
        for field in ('invoice_discount','lines.0.discount_amount','lines.0.discount_percent'):
            result=grounded('No discount',MessageFields(updates=[{'path':field,'value':'0','quote':'No discount'}],unsupported_reason=None))
            self.assertEqual(result[0]['value'],'0')
        for field in ('lines.0.rate','lines.0.gst_rate'):
            with self.assertRaises(ValueError):
                grounded('No discount',MessageFields(updates=[{'path':field,'value':'0','quote':'No discount'}],unsupported_reason=None))

    def test_task_view_preserves_identity_question_and_controls(self):
        context={'status':'ready','supplier_suggestion':{'supplier':'Sharma Traders','rates':[]}}
        latest={'response':'Kis supplier se liya?','purchase_assistant':{'draft_id':'b'*32,'choices':['Sharma Traders']},
            'purchase_context':context,'issues':[{'kind':'identity','field':'party_name'}],'suggestions':[]}
        row=SimpleNamespace(id='task',company_id='a'*32,revision=1,status='needs_input',
            updated_at=datetime.now(timezone.utc),state={'summary':'We need every field',
                'observations':[{'data':latest}],'draft_id':'b'*32})
        result=service.view(row)
        self.assertEqual(result['response'],'Kis supplier se liya?')
        self.assertEqual(result['purchase_context'],context)
        self.assertEqual(result['purchase_assistant']['choices'],['Sharma Traders'])
        self.assertEqual(result['issues'][0]['kind'],'identity')
        row.state['issues']=[{'code':'provider_rate_limit'}]
        row.state['summary']='Quota busy; task saved'
        self.assertEqual(service.view(row)['response'],'Quota busy; task saved')

    async def test_supplier_history_discovery_runs_before_identity_question(self):
        from app.services import purchase_agent as agent
        with patch.object(agent.native,'conversation_history',AsyncMock(return_value={'supplier_suggestion':{'supplier':'Sharma'}})) as discovery, \
             patch.object(agent.native,'context',AsyncMock()) as direct:
            result=await agent.identity_history(None,None,None,{},[{'field':'party_name'}])
            self.assertIn('supplier_suggestion',result)
            discovery.assert_awaited_once();direct.assert_not_awaited()
            discovery.reset_mock()
            result=await agent.identity_history(None,None,None,{},[{'field':'0:item_name'}])
            self.assertEqual(result['status'],'needs_identity')
            discovery.assert_not_awaited()

    async def test_reconcile_only_matching_unsent_draft(self):
        for actual,expected in [('100','needs_input'),('101','verification_pending')]:
            row=SimpleNamespace(id='task',company_id='a'*32,revision=1,status='verification_pending',
                updated_at=datetime.now(timezone.utc),state={'messages':['Rate: 100.'],
                'executions':[{'tool':'apply_user_message','status':'pending','arguments':{
                    'draft_id':'b'*32,'revision':0,'message_index':0,'updates':[
                        {'path':'lines.0.rate','value':'100','quote':'Rate: 100.'}]}}]})
            draft=SimpleNamespace(company_id=row.company_id,action_id=None,revision=1,
                content={'lines':[{'rate':actual}]})
            with patch.object(service,'scoped',AsyncMock(return_value=row)), \
                 patch.object(service.drafts,'scoped_draft',AsyncMock(return_value=draft)):
                result=await service.read(SimpleNamespace(commit=AsyncMock()),SimpleNamespace(),'task')
                self.assertEqual(result['status'],expected)
                self.assertIsNone(result['action_id'])

    async def test_invalid_source_never_mutates_draft(self):
        db=SimpleNamespace()
        registry=tools.registry(db,SimpleNamespace(),'a'*32,{'messages':['Rate: 100.']})
        tool=next(t for t in registry if t.name=='apply_user_message')
        with patch.object(tools.drafts,'save_draft',new_callable=AsyncMock) as save:
            result=await tool.execute({'draft_id':'b'*32,'revision':0,'message_index':9,
                'updates':[{'path':'lines.0.rate','value':'100','quote':'Rate: 100.'}]})
            self.assertIn('No draft change',result.data['validation_error'])
            save.assert_not_awaited()

    async def test_evidence_event_owns_distinct_revision(self):
        row=SimpleNamespace(id='b'*32,company_id='a'*32,revision=0,
            content={'lines':[{'rate':'90'}]},extraction_metadata=None,
            updated_at=datetime.now(timezone.utc))
        db=SimpleNamespace(commit=AsyncMock())
        principal=SimpleNamespace(user_id='test-user')
        async def save(*args):
            row.content=args[-1].content.model_dump(mode='json');row.revision+=1
        from app.services.tally_connector import TallyError
        with patch.object(tools.drafts,'scoped_draft',AsyncMock(return_value=row)), \
             patch.object(tools.drafts,'company_for',AsyncMock(return_value=SimpleNamespace())), \
             patch.object(tools.drafts,'save_draft',side_effect=save), \
             patch.object(tools.drafts,'record_event') as event, \
             patch('app.services.purchase_memory_service.catalog_for',AsyncMock(side_effect=TallyError('offline'))), \
             patch('app.services.purchase_agent.state',AsyncMock(return_value={'proposal':{'revision':2}})):
            registry=tools.registry(db,principal,'a'*32,{'task_id':'task','messages':['Rate: 100.']})
            tool=next(t for t in registry if t.name=='apply_user_message')
            await tool.execute({'draft_id':row.id,'revision':0,'message_index':0,
                'updates':[{'path':'lines.0.rate','value':'100','quote':'Rate: 100.'}]})
            self.assertEqual(row.revision,2)
            self.assertEqual(row.extraction_metadata['agent_provenance']['lines.0.rate']['draft_revision'],2)
            event.assert_called_once()
            self.assertEqual(event.call_args.args[3],'task_explicit_fields')

if __name__=='__main__':unittest.main()
