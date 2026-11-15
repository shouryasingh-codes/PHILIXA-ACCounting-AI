"""Provider tests use a fake HTTP transport; never transmit an API key."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from app.services import ai_engine_manager as engine


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_gemini_runtime_reuses_transport_and_closes_on_shutdown(self):
        clients=[];requests=[]
        async def send(request):
            requests.append(request)
            return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{}'}]}}]})
        def factory(**kwargs):
            client=httpx.AsyncClient(transport=httpx.MockTransport(send),**kwargs)
            clients.append(client);return client
        with patch.object(engine,'get_settings',return_value=SimpleNamespace(gemini_api_key='test')),patch.object(engine,'http_client',factory):
            async with engine.transport_lifespan():
                for _ in range(2):await engine.call_gemini_json('s','u',timeout_seconds=1)
                self.assertEqual(len(clients),1)
                self.assertFalse(clients[0].is_closed)
            self.assertTrue(clients[0].is_closed)
        self.assertEqual(len(requests),2)

    async def test_gemini_timeout_records_safe_stage_not_request_contents(self):
        async def send(request):
            trace=request.extensions['trace']
            await trace('connection.connect_tcp.started',{'host':'SECRET'})
            await trace('connection.connect_tcp.complete',{'return_value':'SECRET'})
            await trace('http11.send_request_body.complete',{'request':'PRIVATE BILL'})
            await trace('http11.receive_response_headers.started',{'headers':'SECRET'})
            await asyncio.sleep(60)
        factory=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(send),**kw)
        with patch.object(engine,'get_settings',return_value=SimpleNamespace(gemini_api_key='TEST-SECRET')),patch.object(engine,'http_client',factory):
            with self.assertRaises(engine.EngineTimeout) as caught:
                await engine.call_gemini_json('PRIVATE BILL','private input',timeout_seconds=.03)
        diagnostic=caught.exception.diagnostic
        self.assertEqual(diagnostic['phase'],'response_headers')
        self.assertGreaterEqual(diagnostic['request_sent_ms'],0)
        self.assertNotIn('SECRET',json.dumps(diagnostic));self.assertNotIn('PRIVATE',json.dumps(diagnostic))

    async def test_cancelled_request_does_not_close_shared_pool_or_repeat_request(self):
        calls=[];clients=[]
        async def send(request):
            calls.append(1)
            if len(calls)==1:await asyncio.sleep(60)
            return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{}'}]}}]})
        def factory(**kw):
            client=httpx.AsyncClient(transport=httpx.MockTransport(send),**kw)
            clients.append(client);return client
        with patch.object(engine,'get_settings',return_value=SimpleNamespace(gemini_api_key='test')),patch.object(engine,'http_client',factory):
            async with engine.transport_lifespan():
                with self.assertRaises(engine.EngineTimeout):await engine.call_gemini_json('s','u',timeout_seconds=.02)
                async with engine.transport_lifespan():
                    text,_=await engine.call_gemini_json('s','u',timeout_seconds=1)
                self.assertEqual(text,'{}');self.assertFalse(clients[0].is_closed)
                self.assertEqual(len(clients),1);self.assertEqual(len(calls),2)
            self.assertTrue(clients[0].is_closed)

    async def test_worker_owns_and_closes_transport_even_if_recovery_fails(self):
        from app.jobs import document_jobs
        with patch.object(engine,'start_transport',AsyncMock()) as start,patch.object(engine,'close_transport',AsyncMock()) as close,patch.object(document_jobs,'recover_bill_documents',AsyncMock(side_effect=RuntimeError('recovery failed'))):
            with self.assertRaises(RuntimeError):await document_jobs.startup({})
        start.assert_awaited_once();close.assert_awaited_once()
        dispose=AsyncMock()
        with patch.object(engine,'close_transport',AsyncMock()) as close,patch.object(document_jobs,'async_engine',SimpleNamespace(dispose=dispose)):
            await document_jobs.shutdown({})
        close.assert_awaited_once();dispose.assert_awaited_once()

    async def test_supplier_subject_and_requested_data_are_separate(self):
        from app.services.intent_router_model import WireRoute,resolve,routing_schema
        values=routing_schema()['properties']['intent']['enum']
        self.assertIn('supplier_query',values)
        self.assertNotIn('supplier_read',values);self.assertNotIn('purchase_history_read',values)
        for data,expected in [('purchases','purchase_history_read'),('profile','supplier_read'),('list','supplier_read')]:
            wire=WireRoute(intent='supplier_query',party_name='Vendor' if data!='list' else None,
                supplier_question={'data':data,'quote':'source question'})
            compiled=resolve(wire,{})
            self.assertEqual(compiled.intent,expected);self.assertEqual(compiled.handler,'domain_read')
            self.assertIsNone(compiled.target_task_id)
        with self.assertRaises(ValueError):resolve(WireRoute(intent='supplier_query',party_name='Vendor'),{})

    async def test_related_reads_do_not_inherit_task_execution_authority(self):
        from app.services.intent_router_model import WireRoute,resolve
        context={'task_id':'a'*32,'draft_id':'b'*32,'can_continue':False,
            'attachment_index':[{'drafts':[{'id':'b'*32}]}]}
        variants=[{'intent':'purchase_history_read','party_name':'Sharma Traders'},
            {'intent':'stock_read','item_name':'*'},
            {'intent':'report_read','report':'get_purchase_register'},
            {'intent':'supplier_read','party_name':'Sharma Traders'},
            {'intent':'document_question','document_draft_id':'b'*32,'document_fields':['invoice_total']}]
        for fields in variants:
            with self.subTest(intent=fields['intent']):
                decision=resolve(WireRoute(**fields,context_relation='continue_current'),context)
                self.assertIn(decision.handler,('domain_read','domain_document'))
                self.assertEqual(decision.relation,'switch_topic')
                self.assertEqual(decision.reported_context_relation,'continue_current')
                self.assertIsNone(decision.target_task_id)
                self.assertFalse(decision.explicit_fields)
        with self.assertRaises(ValueError):
            resolve(WireRoute(intent='compound',context_relation='continue_current'),context)

    async def test_gemini_wire_schema_keeps_shape_and_server_keeps_limits(self):
        from app.services.intent_router_model import WireRoute,routing_schema
        schema=engine.gemini_wire_schema(routing_schema())
        encoded=json.dumps(schema)
        self.assertNotIn('$ref',encoded);self.assertNotIn('maxItems',encoded)
        self.assertEqual(schema['required'],list(schema['properties']))
        self.assertIn('supplier_query',schema['properties']['intent']['enum'])
        self.assertNotIn('supplier_read',schema['properties']['intent']['enum'])
        self.assertEqual(schema['properties']['explicit_fields']['items']['required'],['path','value','quote'])
        with self.assertRaises(ValueError):
            WireRoute(intent='purchase',explicit_fields=[{'path':'party_name','value':'X','quote':'X'}]*101)

    async def test_supplier_word_does_not_force_a_list(self):
        from app.services.intent_router import fast_route
        for message in ['Supplier se Cement purchase karna hai','Which items did we buy from this vendor?','Supplier se maal kharida hai']:
            self.assertIsNone(fast_route(message,{}))

    async def test_planner_uses_task_provider_not_changed_ui_default(self):
        from app.services import task_agent_model as planner
        wire={'kind':'needs_input','tool':None,'arguments_json':'{}','summary':'internal','user_response':'Supplier batayein.'}
        with patch.object(engine,'get_active_engine',AsyncMock(return_value='groq')),patch.object(engine,'call_gemini_json',AsyncMock(return_value=(json.dumps(wire),{'provider':'gemini'}))) as gemini,patch.object(planner,'_post_json',side_effect=AssertionError('No Groq call')):
            _,usage=await planner.choose({'provider':'gemini','messages':['new purchase']},[])
        gemini.assert_awaited_once();self.assertEqual(usage['provider'],'gemini')

    async def test_supplier_history_is_read_only_not_purchase_task(self):
        from app.services.intent_router_model import WireRoute, resolve
        from app.services.intent_router import validate_evidence
        for message in ['Sharma Traders se kya khareeda hai','What have we bought from Sharma Traders?', 'शर्मा से क्या खरीदा था?']:
            supplier='शर्मा' if message.startswith('शर्मा') else 'Sharma Traders'
            decision=resolve(WireRoute(intent='purchase_history_read',party_name=supplier),{})
            validate_evidence(decision,message,{})
            self.assertEqual(decision.handler,'domain_read')
            self.assertFalse(decision.explicit_fields)

    async def test_pinned_provider_ignores_changed_default(self):
        with engine.provider_scope('gemini'):
            self.assertEqual(await engine.get_active_engine(), 'gemini')
        with self.assertRaises(ValueError):
            with engine.provider_scope('unknown'): pass

    async def test_schema_and_actual_model_usage(self):
        seen=[]
        async def send(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"intent":"help"}'}]}}], 'usageMetadata':{'promptTokenCount':12,'candidatesTokenCount':3}})
        factory=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(send),**kw)
        with patch.object(engine,'get_settings',return_value=SimpleNamespace(gemini_api_key='TEST-SECRET',ai_api_key=None)),patch.object(engine,'http_client',factory):
            text,usage=await engine.call_gemini_json('system','input',schema={'type':'object'},timeout_seconds=1)
        self.assertEqual(len(seen),1)
        self.assertEqual(seen[0]['generationConfig']['responseJsonSchema'],{'type':'object'})
        self.assertEqual(usage['provider'],'gemini')
        self.assertTrue(usage['model'])
        self.assertEqual(json.loads(text)['intent'],'help')

    async def test_503_does_not_walk_model_fallbacks(self):
        calls=[]
        async def send(request):
            calls.append(1);return httpx.Response(503,text='TEST-SECRET invoice private')
        factory=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(send),**kw)
        with patch.object(engine,'get_settings',return_value=SimpleNamespace(gemini_api_key='TEST-SECRET',ai_api_key=None)),patch.object(engine,'http_client',factory):
            with self.assertRaises(engine.EngineRequestError) as error:
                await engine.call_gemini_json('system','input',timeout_seconds=1)
        self.assertEqual(len(calls),1)
        self.assertEqual(error.exception.status,503)
        self.assertNotIn('SECRET',str(error.exception))

    async def test_deadline_cancels_transport(self):
        cancelled=asyncio.Event()
        async def send(request):
            try:await asyncio.sleep(60)
            finally:cancelled.set()
        factory=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(send),**kw)
        with patch.object(engine,'get_settings',return_value=SimpleNamespace(gemini_api_key='test',ai_api_key=None)),patch.object(engine,'http_client',factory):
            with self.assertRaises(TimeoutError):
                await engine.call_gemini_json('s','u',timeout_seconds=.02)
        self.assertTrue(cancelled.is_set())

    async def test_truncated_output_is_not_accepted(self):
        async def send(request):
            return httpx.Response(200,json={'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'{}'}]}}]})
        factory=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(send),**kw)
        with patch.object(engine,'get_settings',return_value=SimpleNamespace(gemini_api_key='test',ai_api_key=None)),patch.object(engine,'http_client',factory):
            with self.assertRaises(engine.EngineRequestError):await engine.call_gemini_json('s','u')

    async def test_engine_switch_failure_never_reports_success(self):
        with patch.object(engine,'get_redis_client',AsyncMock(side_effect=OSError('redis down'))):
            with self.assertRaises(engine.EngineRequestError):await engine.set_active_engine('gemini')

if __name__=='__main__':unittest.main()
