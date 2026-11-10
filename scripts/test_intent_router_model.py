import json,unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.services import intent_router_model as model
from app.services.intent_router import RouteDecision


class ModelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings=SimpleNamespace(ai_api_key='synthetic-not-a-key',groq_api_key=None,ai_economy_model='openai/gpt-oss-20b')
        self.patches=[patch.object(model,'ready',return_value=True),patch.object(model,'get_settings',return_value=self.settings),
            patch.object(model,'GroqProvider',return_value=SimpleNamespace(base_url='https://api.groq.com/openai/v1/chat/completions')),
            patch.object(model.groq_gateway,'enabled',return_value=True)]
        for p in self.patches:p.start()

    async def asyncTearDown(self):
        for p in self.patches:p.stop()

    def response(self,value,finish='stop'):
        return {'choices':[{'finish_reason':finish,'message':{'content':json.dumps(value)}}],'usage':{'total_tokens':100}}

    async def test_existing_bill_action_continues_exact_draft_not_field_read(self):
        from app.services.intent_router import first_step,validate_evidence
        context={'task_id':'a'*32,'draft_id':'b'*32,'can_continue':True,'attachment_document_ids':['c'*32],
                 'attachment_index':[{'drafts':[{'id':'b'*32,'revision':0}]}]}
        for text in ('Is invoice ko Tally entry ke liye prepare karo','Please post this uploaded purchase','is bill ki entry karo'):
            wire=model.WireRoute(intent='bill_processing',context_relation='continue_current',document_draft_id='b'*32)
            with patch.object(model,'_post_json',return_value=self.response(wire.model_dump())) as post:
                decision,_=await model.classify(text,context,'d'*32)
            self.assertEqual(decision.handler,'domain_continuation');self.assertEqual(decision.target_task_id,'a'*32)
            self.assertEqual(first_step(decision,context)['tool'],'purchase_context');post.assert_called_once()
        context['attachment_index'][0]['drafts'].append({'id':'e'*32})
        ambiguous=model.resolve(model.WireRoute(intent='bill_processing',context_relation='continue_current'),context)
        self.assertEqual(ambiguous.handler,'clarify')
        foreign=model.resolve(model.WireRoute(intent='bill_processing',context_relation='continue_current',document_draft_id='f'*32),context)
        self.assertEqual(foreign.handler,'clarify')
        with self.assertRaises(ValueError):model.resolve(model.WireRoute(intent='help',context_relation='continue_current',conversational_reply='Help'),context)
        # Model returning purchase with continue_current for an active draft resolves seamlessly to bill_processing continuation
        single_context={'task_id':'a'*32,'draft_id':'b'*32,'can_continue':True,'attachment_index':[{'drafts':[{'id':'b'*32,'revision':0}]}]}
        purch_continue=model.resolve(model.WireRoute(intent='purchase',context_relation='continue_current'),single_context)
        self.assertEqual(purch_continue.intent,'bill_processing')
        self.assertEqual(purch_continue.handler,'domain_continuation')
        self.assertEqual(purch_continue.target_draft_id,'b'*32)

    async def test_one_shared_gateway_attempt(self):
        decision=model.WireRoute(intent='help',conversational_reply='I can help with supported tasks.')
        with patch.object(model,'_post_json',return_value=self.response(decision.model_dump())) as post:
            result,usage=await model.classify('How could you help?',{},'a'*32)
        post.assert_called_once();self.assertEqual(post.call_args.kwargs['max_attempts'],1)
        self.assertEqual(post.call_args.kwargs['timeout_seconds'],7);self.assertEqual(result.handler,'direct_reply')

    async def test_conversation_reply_comes_from_same_call_and_stays_out_of_domain(self):
        cases=[('tera naam kya hai','Mera naam Philixa hai.'),
               ('How are you different from a person?', 'I am an AI assistant, not a person.'),
               ('Shukriya, bye','Shukriya! Phir milte hain.')]
        for message,answer in cases:
            wire=model.WireRoute(intent='smalltalk',conversational_reply=answer)
            with patch.object(model,'_post_json',return_value=self.response(wire.model_dump())) as post:
                decision,_=await model.classify(message,{},'a'*32)
            self.assertEqual(decision.conversational_reply,answer)
            self.assertIsNone(decision.target_task_id)
            post.assert_called_once()
        with self.assertRaises(ValueError):
            model.resolve(model.WireRoute(intent='smalltalk'),{})
        with self.assertRaises(ValueError):
            model.resolve(model.WireRoute(intent='stock_read',item_name='*',conversational_reply='Stock 50'),{})

    async def test_identity_reply_is_not_bound_to_supplier_or_task(self):
        context={'task_id':'a'*32,'can_continue':True,'choices':['Synthetic Supplier']}
        wire=model.WireRoute(intent='smalltalk',context_relation='switch_topic',
            conversational_reply="I do not know your name yet. What should I call you?")
        with patch.object(model,'_post_json',return_value=self.response(wire.model_dump())) as post:
            result,_=await model.classify('Do you know who I am?',context,'b'*32)
        self.assertEqual(result.intent,'smalltalk')
        self.assertIsNone(result.target_task_id)
        self.assertEqual(result.conversational_reply,wire.conversational_reply)
        post.assert_called_once()

    async def test_capability_manifest_is_server_supplied_and_matches_registry(self):
        import ast
        from pathlib import Path
        from app.services.assistant_capabilities import SUPPORTED_TOOL_NAMES
        tree=ast.parse(Path('app/services/task_agent_tools.py').read_text(encoding='utf-8'))
        actual={n.args[0].value for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='Tool' and n.args and isinstance(n.args[0],ast.Constant)}
        self.assertTrue(set(SUPPORTED_TOOL_NAMES)<=actual)
        body=model.payload('Could you search?',{})
        content=json.loads(body['messages'][-1]['content'])
        self.assertIn('product_capabilities',content)
        self.assertIn('No internet search',content['product_capabilities']['limitations'][0])
        wire=model.WireRoute(intent='help',conversational_reply='I cannot browse the internet.')
        with patch.object(model,'_post_json',return_value=self.response(wire.model_dump())):
            decision,_=await model.classify('Could you research online?',{},'a'*32)
        self.assertEqual(decision.conversational_reply,wire.conversational_reply)
        self.assertIsNone(decision.target_task_id)

    async def test_compact_prompt_keeps_authority_and_budget(self):
        from app.ai.groq_gateway import estimate
        body=model.payload('What can you do?',{})
        self.assertLess(estimate(body),3400)
        self.assertEqual(body['max_completion_tokens'],1024)
        self.assertIn('Never invent',model.SYSTEM)
        self.assertIn('exact current-message quotes',model.SYSTEM)
        self.assertIn('permissions or posting approval',model.SYSTEM)

    async def test_supplier_answer_has_no_document_target(self):
        context={'task_id':'a'*32,'draft_id':'b'*32,'can_continue':True}
        wire=model.WireRoute(intent='task_reply',context_relation='continue_current',
            explicit_fields=[{'path':'party_name','value':'Sharma Traders','quote':'Sharma Traders'}])
        with patch.object(model,'_post_json',return_value=self.response(wire.model_dump())):
            decision,usage=await model.classify('Supplier Sharma Traders hai',context,'a'*32)
        self.assertEqual(decision.target_task_id,'a'*32)
        self.assertIsNone(decision.target_draft_id)
        self.assertEqual(decision.explicit_fields[0].value,'Sharma Traders')

    async def test_truncated_or_malformed_output_does_not_get_repaired(self):
        for response in (self.response({},finish='length'),self.response({'handler':'shell'})):
            with patch.object(model,'_post_json',return_value=response) as post:
                with self.assertRaises((ValueError,model.RoutingOutputError)):
                    await model.classify('stock bata',{},'a'*32)
            post.assert_called_once()

    async def test_uninitialized_model_never_transmits(self):
        with patch.object(model,'ready',return_value=False),patch.object(model,'_post_json') as post:
            with self.assertRaises(model.RoutingNotSent):await model.classify('help',{},'a'*32)
        post.assert_not_called()


if __name__=='__main__':unittest.main()
