"""Scoped PostgreSQL attachment linking and continuation; no AI or Tally writes."""
import copy,os,unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from fastapi import HTTPException
from sqlalchemy import select,delete,func
from app.models.chat_attachment import ChatBillMessage,ChatBillAttachment
from app.models.agent_task import AgentTask
from app.models.bill_document import BillDocument
from app.services import chat_attachments as service,business_conversation_service as chats
from app.services import purchase_draft_service as drafts
from app.services.business_command_service import CommandRequest
from scripts.test_bill_documents import DocumentTests


class AttachmentTests(unittest.IsolatedAsyncioTestCase):
    upload=DocumentTests.upload
    async def asyncSetUp(self):
        await DocumentTests.asyncSetUp(self)
        self.flags=patch.dict(os.environ,PHILIXA_CHAT_ATTACHMENTS_ENABLED='1',PHILIXA_TASK_AGENT_ENABLED='1');self.flags.start()
        self.dispatch=patch.object(service.tasks,'enqueue',AsyncMock());self.dispatch.start()
        self.chat=await chats.create_conversation(self.db,self.principal,chats.ConversationCreate(organization_id=self.org))
        self.doc=(await self.upload())['document']['id']
    async def asyncTearDown(self):
        self.dispatch.stop();self.flags.stop();await self.db.rollback()
        mids=select(ChatBillMessage.id).where(ChatBillMessage.organization_id==self.org)
        await self.db.execute(delete(ChatBillAttachment).where(ChatBillAttachment.message_id.in_(mids)))
        await self.db.execute(delete(ChatBillMessage).where(ChatBillMessage.organization_id==self.org))
        await self.db.execute(delete(AgentTask).where(AgentTask.organization_id==self.org));await self.db.commit()
        await DocumentTests.asyncTearDown(self)
    def request(self,**changes):
        return CommandRequest(**dict(conversation_id=self.chat['id'],conversation_revision=0,
            request_id='attachment-test-123456',attachments=[{'document_id':self.doc}],**changes))
    async def test_atomic_link_replay_restoration_and_no_duplicate_draft(self):
        first=await service.accept(self.db,self.principal,self.request())
        again=await service.accept(self.db,self.principal,self.request())
        self.assertEqual(first['task_id'],again['task_id'])
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(ChatBillMessage).where(ChatBillMessage.organization_id==self.org)),1)
        restored=await chats.read_conversation(self.db,self.principal,self.chat['id'])
        self.assertEqual(restored['messages'][0]['data']['chat_attachments'][0]['document_id'],self.doc)
        self.assertEqual(restored['messages'][1]['data']['task_id'],first['task_id'])
        with self.assertRaises(HTTPException) as error:await service.accept(self.db,self.principal,self.request(text='changed'))
        self.assertEqual(error.exception.status_code,409)
    async def test_stale_revision_and_foreign_source_reject_entire_link(self):
        request=self.request();request.conversation_revision=3
        with self.assertRaises(HTTPException):await service.accept(self.db,self.principal,request)
        request=self.request();request.attachments[0].document_id='f'*32
        with self.assertRaises(HTTPException):await service.accept(self.db,self.principal,request)
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(ChatBillMessage).where(ChatBillMessage.organization_id==self.org)),0)
    async def test_read_status_never_starts_extraction_and_wait_is_durable(self):
        result=await service.accept(self.db,self.principal,self.request())
        row=await self.db.get(AgentTask,result['task_id']);state=copy.deepcopy(row.state)
        with patch('app.services.invoice_extraction_jobs.request_extraction',AsyncMock()) as extract:
            await service.source_context(self.db,self.principal,state,self.company.id)
            await chats.read_conversation(self.db,self.principal,self.chat['id'])
            extract.assert_not_awaited()
            pending=await service.advance(self.db,self.principal,state,self.company.id)
            self.assertEqual(pending['status'],'waiting_context');extract.assert_not_awaited()
    async def test_existing_source_draft_adopted_without_recreation(self):
        row=await self.db.get(BillDocument,self.doc);row.status='ready';row.page_count=1;row.extraction_status='done';await self.db.commit()
        draft=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,content={'invoice_number':'CHAT-DUMMY','invoice_total':'1167'}))
        from app.models.purchase_draft import PurchaseDraft
        d=await self.db.get(PurchaseDraft,draft['id']);d.document_id=self.doc;await self.db.commit()
        with patch('app.services.invoice_extraction_jobs.request_extraction',AsyncMock()) as extract:
            state=await service.advance(self.db,self.principal,{'attachment_document_ids':[self.doc]},self.company.id)
            self.assertEqual(state['draft_id'],draft['id']);self.assertIn('1167',state['summary']);extract.assert_not_awaited()
            second=await service.advance(self.db,self.principal,state,self.company.id)
            self.assertEqual(second['draft_id'],draft['id'])
    async def test_bill_action_routes_to_same_saved_task_and_replays_without_new_draft(self):
        from app.models.purchase_draft import PurchaseDraft
        from app.models.business_route import BusinessRoute
        from app.services import business_router as router,intent_router_model as model
        doc=await self.db.get(BillDocument,self.doc);doc.status='ready';doc.page_count=1;doc.extraction_status='needs_review';await self.db.commit()
        saved=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,content={'invoice_number':'LINK-TEST'}))
        draft=await self.db.get(PurchaseDraft,saved['id']);draft.document_id=self.doc;await self.db.commit()
        accepted=await service.accept(self.db,self.principal,self.request(text='Please prepare this invoice for Tally'))
        task=await self.db.get(AgentTask,accepted['task_id']);task.state={**task.state,**await service.advance(self.db,self.principal,copy.deepcopy(task.state),self.company.id)};task.status='needs_input';await self.db.commit()
        async def classify(text,context,ident):
            return model.resolve(model.WireRoute(intent='bill_processing',context_relation='continue_current',document_draft_id=draft.id),context),{}
        request=CommandRequest(text='Prepare this saved invoice for entry',conversation_id=self.chat['id'],conversation_revision=1,
                               task_id=task.id,request_id='same-bill-action-123')
        try:
            with patch('app.services.intent_router_model.classify',side_effect=classify) as classification, patch('app.jobs.task_agent_jobs.principal_for',AsyncMock(return_value=self.principal)):
                result=await router.route(self.db,self.principal,request)
                replay=await router.route(self.db,self.principal,request)
            self.assertEqual(result['task_id'],task.id);self.assertEqual(replay['task_id'],task.id)
            self.assertEqual(classification.await_count,1)
            await self.db.refresh(task)
            self.assertEqual(task.state['draft_id'],draft.id);self.assertEqual(task.state['routing_first_step']['tool'],'purchase_context')
            self.assertIn('purchase',task.state['tool_groups']);self.assertEqual(task.state['outcome'],'draft')
            self.assertEqual(await self.db.scalar(select(func.count()).select_from(PurchaseDraft).where(PurchaseDraft.document_id==self.doc)),1)
            self.assertIsNone(draft.action_id)
        finally:
            await self.db.rollback();await self.db.execute(delete(BusinessRoute).where(BusinessRoute.organization_id==self.org));await self.db.commit()

    async def test_wrong_owner_and_disabled_company_are_denied(self):
        other=SimpleNamespace(**{**self.principal.__dict__,'user_id':'other'})
        with self.assertRaises(HTTPException):await service.accept(self.db,other,self.request())
        self.company.enabled=False;await self.db.commit()
        with self.assertRaises(HTTPException):await service.accept(self.db,self.principal,self.request())

    async def test_worker_pool_dispatch_and_no_second_extraction(self):
        doc=await self.db.get(BillDocument,self.doc);doc.status='ready';doc.page_count=1;await self.db.commit()
        pool=object();state={'attachment_document_ids':[self.doc]}
        with patch('app.services.invoice_extraction_jobs.enqueue',AsyncMock()) as enqueue:
            first=await service.advance(self.db,self.principal,state,self.company.id,queue=pool)
            self.assertEqual(first['status'],'waiting_context')
            enqueue.assert_awaited_once();self.assertIs(enqueue.call_args.args[1],pool)
            second=await service.advance(self.db,self.principal,first,self.company.id,queue=pool)
            self.assertEqual(second['status'],'waiting_context');self.assertEqual(enqueue.await_count,1)

    async def test_recovery_restores_dispatch_without_browser_or_model(self):
        accepted=await service.accept(self.db,self.principal,self.request())
        row=await self.db.get(AgentTask,accepted['task_id']);row.status='waiting_context';await self.db.commit()
        redis=SimpleNamespace(enqueue_job=AsyncMock())
        await service.wake({'redis':redis},self.doc)
        redis.enqueue_job.assert_awaited_once()
        self.assertEqual(redis.enqueue_job.call_args.args[:2],('execute_agent_task',row.id))
        await self.db.refresh(row);self.assertEqual(row.status,'queued')

    async def test_removed_source_redacts_authoritative_chat_result(self):
        accepted=await service.accept(self.db,self.principal,self.request())
        from app.services import bill_document_service as docs
        doc=await self.db.get(BillDocument,self.doc);doc.status='ready';await self.db.commit()
        await docs.set_trash(self.db,self.principal,self.doc)
        with self.assertRaises(HTTPException):await service.tasks.scoped(self.db,self.principal,accepted['task_id'])
        restored=await chats.read_conversation(self.db,self.principal,self.chat['id'])
        self.assertNotIn('data',restored['messages'][1]);self.assertIn('unavailable',restored['messages'][1]['text'])

    async def test_router_uses_attachment_index_and_does_not_resume_bill_for_help(self):
        from app.services import business_router as router
        from app.services.intent_router import RouteDecision
        from app.models.business_route import BusinessRoute
        from app.models.purchase_draft import PurchaseDraft
        doc=await self.db.get(BillDocument,self.doc);doc.status='ready';doc.page_count=2;await self.db.commit()
        accepted=await service.accept(self.db,self.principal,self.request())
        for number,total in [('A-1','662'),('A-2','23')]:
            data=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,
                content={'invoice_number':number,'invoice_total':total}))
            draft=await self.db.get(PurchaseDraft,data['id']);draft.document_id=self.doc
            draft.extraction_metadata={'source_pages':[1 if number=='A-1' else 2],'is_split_draft':True}
            await self.db.commit()
        task=await self.db.get(AgentTask,accepted['task_id']);before=copy.deepcopy(task.state)
        request=CommandRequest(text='Could you explain your capabilities?',conversation_id=self.chat['id'],
            conversation_revision=1,request_id='routing-attachment-help-123')
        context=await router.context_for(self.db,self.principal,request)
        self.assertEqual(context['task_id'],task.id)
        self.assertEqual(len(context['attachment_index'][0]['drafts']),2)
        self.assertNotIn('content',str(context['attachment_index']))
        decision=RouteDecision(intent='help',relation='switch_topic',handler='direct_reply',reason='semantic',conversational_reply='Main supported stock, reports aur bills mein help kar sakti hoon.')
        with patch.object(router,'reserve_model',AsyncMock()),patch('app.services.intent_router_model.classify',AsyncMock(return_value=(decision,{}))),patch('app.jobs.task_agent_jobs.principal_for',AsyncMock(return_value=self.principal)):
            result=await router.route(self.db,self.principal,request)
        self.assertEqual(result['response_kind'],'product_help');self.assertNotIn('attachment_sources',result)
        await self.db.refresh(task);self.assertEqual(task.state,before)
        target=context['attachment_index'][0]['drafts'][1]['id']
        decision=RouteDecision(intent='document_question',relation='switch_topic',handler='domain_document',
            target_draft_id=target,document_fields=['invoice_total'],reason='semantic')
        follow=request.model_copy(update={'text':'second bill ka total','request_id':'routing-second-bill-123456'})
        with patch.object(router,'reserve_model',AsyncMock()),patch('app.services.intent_router_model.classify',AsyncMock(return_value=(decision,{}))),patch('app.jobs.task_agent_jobs.principal_for',AsyncMock(return_value=self.principal)):
            result=await router.route(self.db,self.principal,follow)
        self.assertEqual(result['response_kind'],'document_answer');self.assertEqual(result['draft_id'],target)
        self.assertNotIn('task_id',result);self.assertNotIn('attachment_sources',result)
        await self.db.refresh(task);self.assertEqual(task.state,before)
        for d in (await self.db.scalars(select(PurchaseDraft).where(PurchaseDraft.document_id==self.doc))).all():self.assertIsNone(d.action_id)
        await self.db.execute(delete(BusinessRoute).where(BusinessRoute.organization_id==self.org));await self.db.commit()

    async def test_bill_field_read_is_scoped_and_does_not_use_tally_history(self):
        from app.services.task_agent_tools import registry
        doc=await self.db.get(BillDocument,self.doc);doc.status='ready';doc.page_count=1;await self.db.commit()
        draft=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,content={'invoice_total':'1167'}))
        from app.models.purchase_draft import PurchaseDraft
        row=await self.db.get(PurchaseDraft,draft['id']);row.document_id=self.doc;await self.db.commit()
        tools=registry(self.db,self.principal,self.company.id,{'attachment_document_ids':[self.doc],'outcome':'draft'})
        tool=next(t for t in tools if t.name=='read_bill_fields')
        args={'draft_id':row.id,'fields':['invoice_total']}
        await tool.authorize(args);result=await tool.execute(args)
        self.assertEqual(result.data['values'],{'invoice_total':'1167'});self.assertIn('1167',result.data['response'])
        self.assertTrue(result.verified)
        with self.assertRaises(HTTPException):await tool.authorize({'document_id':'f'*32})

    async def test_model_context_is_source_index_not_duplicate_ocr_dump(self):
        from app.services.task_agent_model import planner_context
        import json
        context=json.loads(planner_context({'attachment_document_ids':[self.doc],'messages':['Is bill ka total?'],
            'attachment_sources':[{'document_id':self.doc,'filename':'dummy.pdf','drafts':[{'id':'d'*32,'revision':4,
                'content':{'invoice_total':'1167'},'extraction_metadata':{'raw_text':'private duplicate '*10000}}]}],
            'observations':[]},[]))
        self.assertNotIn('raw_text',str(context));self.assertEqual(context['task']['attachment_sources'][0]['drafts'][0]['revision'],4)

    async def test_parallel_acceptance_has_one_message_and_task(self):
        import asyncio
        from app.database.session import AsyncSessionLocal
        async def accept():
            async with AsyncSessionLocal() as db:return await service.accept(db,self.principal,self.request())
        first,second=await asyncio.gather(accept(),accept())
        self.assertEqual(first['task_id'],second['task_id'])
        count=await self.db.scalar(select(func.count()).select_from(ChatBillMessage).where(ChatBillMessage.organization_id==self.org))
        self.assertEqual(count,1)

    async def test_bill_reference_order_and_ambiguity(self):
        first={'id':'first','content':{'invoice_number':'INV-1'}}
        second={'id':'second','content':{'invoice_number':'INV-2'}}
        one={'filename':'first.pdf','drafts':[first]};two={'filename':'second.pdf','drafts':[second]}
        choices=[(one,first),(two,second)]
        for message in ('second bill ka total','2nd invoice','doosra bill batao','दूसरा बिल'):
            self.assertEqual(service.referenced_bill_ids(message,choices),['second'])
        self.assertEqual(service.referenced_bill_ids('is bill ka total',choices),[])
        self.assertEqual(service.referenced_bill_ids('first.pdf ka total',choices),['first'])
        self.assertEqual(service.referenced_bill_ids('invoice INV-2 ka tax',choices),['second'])
        self.assertEqual(service.referenced_bill_ids('99th bill',choices),[])
        self.assertEqual(service.referenced_bill_ids('invoice INV-12 ka total',choices),[])

    async def test_explicit_retry_is_revisioned_idempotent_and_has_no_guessed_fields(self):
        accepted=await service.accept(self.db,self.principal,self.request())
        task=await self.db.get(AgentTask,accepted['task_id']);task.status='needs_input';await self.db.commit()
        request=service.tasks.TaskResume(expected_revision=0,request_id='retry-attachments-123456',retry_documents=True)
        retried=await service.tasks.resume(self.db,self.principal,task.id,request)
        replayed=await service.tasks.resume(self.db,self.principal,task.id,request)
        self.assertEqual(retried['task_id'],replayed['task_id']);self.assertEqual(retried['task_revision'],1)
        await self.db.refresh(task);self.assertTrue(task.state['attachment_retry']);self.assertTrue(task.state['attachment_initial'])
        self.assertNotIn('content',task.state)

    async def test_failure_without_draft_never_offers_review_bill(self):
        doc=await self.db.get(BillDocument,self.doc);doc.status='ready';doc.extraction_status='error'
        doc.extraction_error='Unsupported table layout';await self.db.commit()
        result=await service.advance(self.db,self.principal,{'attachment_document_ids':[self.doc]},self.company.id)
        self.assertNotIn('Review bill',result['summary']);self.assertIn('draft nahi bana',result['summary'])
        self.assertEqual(result['issues'][0]['code'],'document_extraction_failed')

if __name__=='__main__':unittest.main()
