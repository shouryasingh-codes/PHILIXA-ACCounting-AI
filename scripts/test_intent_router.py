"""Routing contracts/security; no paid/provider/native Tally calls."""
import unittest
from app.services.intent_router import RouteDecision,fast_route,validate_evidence,first_step
from app.services.intent_router_model import payload


class Contracts(unittest.TestCase):
    def test_help_and_stock_are_not_posting(self):
        for message in ('whatyou can do for me','tu maire liye kiya kr sakta hai','आप क्या कर सकते हैं'):
            self.assertIsNone(fast_route(message,{}))
        decision=fast_route('stock kitna hai',{'task_id':'a'*32})
        self.assertEqual((decision.handler,decision.relation),('domain_read','switch_topic'))

    def test_document_target_must_be_an_authorized_candidate(self):
        context={'attachment_index':[{'drafts':[{'id':'a'*32}]}]}
        decision=RouteDecision(intent='document_question',relation='switch_topic',handler='domain_document',
            target_draft_id='b'*32,document_fields=['invoice_total'],reason='semantic')
        with self.assertRaises(ValueError):validate_evidence(decision,'second bill total',context)
        self.assertEqual(validate_evidence(decision.model_copy(update={'target_draft_id':'a'*32}),'second bill',context).target_draft_id,'a'*32)

    def test_independent_intent_compiles_relation_without_binding_task(self):
        from app.services.intent_router_model import WireRoute,resolve
        context={'task_id':'a'*32,'can_continue':True}
        help_route=resolve(WireRoute(intent='help',context_relation='switch_topic',conversational_reply='I can explain my capabilities.'),context)
        self.assertIsNone(help_route.target_task_id)
        compiled=resolve(WireRoute(intent='help',context_relation='standalone',conversational_reply='I can explain my capabilities.'),context)
        self.assertEqual(compiled.relation,'switch_topic')
        self.assertEqual(compiled.reported_context_relation,'standalone')
        self.assertIsNone(compiled.target_task_id)
        with self.assertRaises(ValueError):resolve(WireRoute(intent='task_reply',context_relation='standalone'),context)
        unclear=resolve(WireRoute(intent='clarification',context_relation='unclear'),context)
        self.assertEqual(unclear.handler,'clarify')

    def test_exact_offer_needs_current_focus(self):
        context={'task_id':'a'*32,'can_continue':True,'choices':['Sharma Traders'],'focused':True}
        self.assertEqual(fast_route('Sharma Traders',context).target_task_id,'a'*32)
        self.assertIsNone(fast_route('Sharma Traders',{**context,'focused':False}))
        self.assertEqual(fast_route('haan',context).handler,'clarify')
        self.assertIsNone(fast_route('Sharma Traders aur rate 340',context))

    def test_mixed_mutation_must_not_be_swallowed(self):
        for message in ('stock bata aur 5 bags add kar','what can you do and post entry',
                        'stock 5 bags ghata do','rate 350 nahi 340 hai'):
            self.assertIsNone(fast_route(message,{}))

    def test_model_cannot_choose_write_for_help_or_target_other_task(self):
        with self.assertRaises(ValueError):RouteDecision(intent='help',relation='standalone',handler='agent',reason='bad')
        decision=RouteDecision(intent='task_reply',relation='continue_current',handler='domain_continuation',
            target_task_id='b'*32,reason='bad')
        with self.assertRaises(ValueError):validate_evidence(decision,'Sharma',{'task_id':'a'*32,'can_continue':True})

    def test_grounded_purchase_seed_avoids_duplicate_understanding(self):
        fields=[{'path':'lines.0.item_name','value':'Cement','quote':'Cement'},
                {'path':'lines.0.quantity','value':'5','quote':'5'},
                {'path':'lines.0.rate','value':'350','quote':'350'}]
        decision=RouteDecision(intent='purchase',relation='standalone',handler='agent',reason='explicit',explicit_fields=fields)
        validate_evidence(decision,'5 Cement bags rate 350',{})
        seed=first_step(decision,{'company_id':'c'*32})
        self.assertEqual(seed['tool'],'create_purchase_draft')
        self.assertEqual(seed['arguments']['updates'][2]['value'],'350')
        with self.assertRaises(ValueError):validate_evidence(decision,'5 Cement bags',{})

    def test_named_read_requires_evidence_and_wire_is_strict(self):
        decision=RouteDecision(intent='stock_read',relation='standalone',handler='domain_read',item_name='Steel',reason='read')
        with self.assertRaises(ValueError):validate_evidence(decision,'Cement stock bata',{})
        schema=payload('Stock?',{})['response_format']['json_schema']['schema']
        self.assertEqual(set(schema['required']),set(schema['properties']))
        self.assertFalse(schema['additionalProperties'])

    def test_numeric_answer_is_only_for_a_focused_typed_question(self):
        context={'task_id':'a'*32,'draft_id':'b'*32,'can_continue':True,'focused':True,'pending_field':'0:rate'}
        result=fast_route('340',context)
        self.assertEqual(result.explicit_fields[0].path,'lines.0.rate')
        self.assertIsNone(fast_route('340',{**context,'focused':False}))
        self.assertIsNone(fast_route('340',{}))

    def test_report_period_must_not_be_silently_dropped(self):
        decision=RouteDecision(intent='report_read',relation='standalone',handler='domain_read',report='get_purchase_register',reason='read')
        with self.assertRaises(ValueError):validate_evidence(decision,'Show last month purchase report',{})
        explicit=decision.model_copy(update={'report_dates':[]})
        self.assertEqual(validate_evidence(explicit,'Show purchase report',{}).report,'get_purchase_register')


if __name__=='__main__':unittest.main()
