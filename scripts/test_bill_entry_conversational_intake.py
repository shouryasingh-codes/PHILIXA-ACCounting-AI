"""Test upgraded bill attachment conversational intake flow and Tally blockers articulation."""
import copy, os, unittest
from unittest.mock import AsyncMock, patch
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, delete

from app.models.chat_attachment import ChatBillMessage, ChatBillAttachment
from app.models.agent_task import AgentTask
from app.models.bill_document import BillDocument
from app.models.purchase_draft import PurchaseDraft
from app.services import chat_attachments as service, business_conversation_service as chats
from app.services import purchase_draft_service as drafts
from app.services.business_command_service import CommandRequest
from app.services.intent_router import is_bill_entry_intent
from app.services.task_agent_runtime import Tool, ToolResult, run, format_tally_blockers
from scripts.test_bill_documents import DocumentTests


class Empty(BaseModel):
    model_config = ConfigDict(extra='forbid')


class BillEntryIntakeTests(unittest.IsolatedAsyncioTestCase):
    upload = DocumentTests.upload

    async def asyncSetUp(self):
        await DocumentTests.asyncSetUp(self)
        self.flags = patch.dict(os.environ, PHILIXA_CHAT_ATTACHMENTS_ENABLED='1', PHILIXA_TASK_AGENT_ENABLED='1')
        self.flags.start()
        self.dispatch = patch.object(service.tasks, 'enqueue', AsyncMock())
        self.dispatch.start()
        self.chat = await chats.create_conversation(self.db, self.principal, chats.ConversationCreate(organization_id=self.org))
        self.doc = (await self.upload())['document']['id']

    async def asyncTearDown(self):
        self.dispatch.stop()
        self.flags.stop()
        await self.db.rollback()
        mids = select(ChatBillMessage.id).where(ChatBillMessage.organization_id == self.org)
        await self.db.execute(delete(ChatBillAttachment).where(ChatBillAttachment.message_id.in_(mids)))
        await self.db.execute(delete(ChatBillMessage).where(ChatBillMessage.organization_id == self.org))
        await self.db.execute(delete(AgentTask).where(AgentTask.organization_id == self.org))
        await self.db.commit()
        await DocumentTests.asyncTearDown(self)

    def request(self, text, **changes):
        return CommandRequest(**dict(
            conversation_id=self.chat['id'],
            conversation_revision=0,
            request_id='entry-intake-test-' + os.urandom(8).hex(),
            text=text,
            attachments=[{'document_id': self.doc}],
            **changes
        ))

    async def test_upload_with_entry_commands_sets_verified_entry_outcome(self):
        phrases = [
            'tally mai entry krde',
            'ye bill tally me chadhado',
            'is bil ki entry krna',
            'is bill ko tally me daal do'
        ]
        for phrase in phrases:
            self.assertTrue(is_bill_entry_intent(phrase), f"Failed intent check for: {phrase}")
            chat = await chats.create_conversation(self.db, self.principal, chats.ConversationCreate(organization_id=self.org))
            doc = (await self.upload())['document']['id']
            req = CommandRequest(**dict(
                conversation_id=chat['id'],
                conversation_revision=0,
                request_id='entry-intake-test-' + os.urandom(8).hex(),
                text=phrase,
                attachments=[{'document_id': doc}]
            ))
            accepted = await service.accept(self.db, self.principal, req)
            task = await self.db.get(AgentTask, accepted['task_id'])
            self.assertEqual(task.state['outcome'], 'verified_entry', f"Failed outcome for: {phrase}")
            self.assertIn('purchase', task.state['tool_groups'], f"Failed tool_groups for: {phrase}")

    async def test_upload_without_entry_command_retains_answer_outcome(self):
        req = self.request('is bill me kya likha hai?')
        accepted = await service.accept(self.db, self.principal, req)
        task = await self.db.get(AgentTask, accepted['task_id'])
        self.assertEqual(task.state['outcome'], 'answer')
        self.assertNotIn('purchase', task.state['tool_groups'])

    async def test_advance_with_entry_intent_triggers_purchase_context_seed(self):
        doc = await self.db.get(BillDocument, self.doc)
        doc.status = 'ready'
        doc.page_count = 1
        doc.extraction_status = 'needs_review'
        await self.db.commit()

        saved = await drafts.create_draft(self.db, self.principal, drafts.DraftCreate(
            company_id=self.company.id,
            content={'party_name': 'TimeNet Solutions', 'invoice_number': 'TVM/101', 'invoice_total': '384798.00'}
        ))
        draft = await self.db.get(PurchaseDraft, saved['id'])
        draft.document_id = self.doc
        await self.db.commit()

        req = self.request('tally mai entry krde')
        accepted = await service.accept(self.db, self.principal, req)
        task = await self.db.get(AgentTask, accepted['task_id'])

        advanced = await service.advance(self.db, self.principal, copy.deepcopy(task.state), self.company.id)
        self.assertEqual(advanced['outcome'], 'verified_entry')
        self.assertEqual(advanced['draft_id'], draft.id)
        self.assertIn('purchase', advanced['tool_groups'])
        self.assertIsNotNone(advanced.get('routing_first_step'))
        self.assertEqual(advanced['routing_first_step']['tool'], 'purchase_context')
        self.assertEqual(advanced['routing_first_step']['arguments']['draft_id'], draft.id)

    def test_format_tally_blockers_timenet_scenario(self):
        state = {
            'draft_id': 'd1',
            'attachment_sources': [{
                'drafts': [{
                    'id': 'd1',
                    'content': {'party_name': 'TimeNet Solutions', 'invoice_total': '384798.00'}
                }]
            }]
        }
        data = {
            'proposal': {
                'content': {
                    'party_name': 'TimeNet Solutions',
                    'invoice_total': '384798.00',
                    'lines': [{'item_name': f'Item {i}'} for i in range(1, 7)]
                },
                'totals': {'invoice_total': '384798.00'}
            },
            'issues': [
                {'field': 'party_name', 'kind': 'identity', 'message': 'Kis supplier se liya?'},
                *[{'field': f'{i}:item_name', 'kind': 'identity', 'message': f'Item {i+1}: kaunsa Tally item?'} for i in range(6)]
            ]
        }
        articulation = format_tally_blockers(state, data)
        self.assertIsNotNone(articulation)
        # Check requirements:
        # 1. Mention supplier name and total amount
        self.assertIn('TimeNet Solutions', articulation)
        self.assertTrue('3,84,798.00' in articulation or '384798.00' in articulation)
        # 2. State clearly which masters are missing in Tally
        self.assertIn('Sundry Creditors me nahi hai', articulation)
        self.assertIn('6 stock items missing', articulation)
        # 3. Ask clearly: 'Kya main Tally me [Supplier] ka Sundry Creditor ledger bana doon ya kisi existing ledger se map karna hai?'
        self.assertIn('Kya main Tally me TimeNet Solutions ka Sundry Creditor ledger bana doon ya kisi existing ledger se map karna hai?', articulation)

    def test_format_tally_blockers_supplier_missing_only(self):
        state = {}
        data = {
            'proposal': {
                'content': {'party_name': 'Sharma Traders', 'invoice_total': '15000.00'}
            },
            'issues': [
                {'field': 'party_name', 'kind': 'identity', 'message': 'Kis supplier se liya?'}
            ]
        }
        articulation = format_tally_blockers(state, data)
        self.assertIn('Sharma Traders', articulation)
        self.assertTrue('15,000.00' in articulation or '15000.00' in articulation)
        self.assertIn('Sharma Traders Sundry Creditors me nahi hai', articulation)
        self.assertIn('Kya main Tally me Sharma Traders ka Sundry Creditor ledger bana doon ya kisi existing ledger se map karna hai?', articulation)

    def test_format_tally_blockers_no_blockers_returns_none(self):
        state = {}
        data = {
            'proposal': {
                'content': {'party_name': 'Existing Supplier', 'invoice_total': '1000.00'}
            },
            'issues': []
        }
        self.assertIsNone(format_tally_blockers(state, data))

    async def test_runtime_executes_purchase_context_and_articulates_blockers_without_model(self):
        class ContextArgs(BaseModel):
            draft_id: str

        data = {
            'proposal': {
                'content': {
                    'party_name': 'TimeNet Solutions',
                    'invoice_total': '384798.00',
                    'lines': [{'item_name': f'Part {i}'} for i in range(6)]
                }
            },
            'issues': [
                {'field': 'party_name', 'kind': 'identity', 'message': 'Kis supplier se liya?'},
                *[{'field': f'{i}:item_name', 'kind': 'identity', 'message': f'Item {i+1}'} for i in range(6)]
            ]
        }

        async def execute(args):
            return ToolResult(status='needs_input', data=data)

        async def forbidden_choose(*args):
            raise AssertionError("Model choose must not be called when purchase_context is seeded")

        async def dummy_persist(state):
            pass

        async def dummy_auth(args):
            pass

        tool = Tool('purchase_context', 'Context', ContextArgs, 'draft', dummy_auth, execute)

        state = {
            'messages': ['ye bill tally me chadhado'],
            'draft_id': 'saved_draft_123',
            'attachment_document_ids': ['doc_123'],
            'tool_groups': ['documents', 'purchase'],
            'outcome': 'verified_entry'
        }

        result = await run(state, [tool], forbidden_choose, dummy_persist, None)
        self.assertEqual(result['status'], 'needs_input')
        self.assertEqual(result['model_rounds'], 0)
        self.assertIn('TimeNet Solutions', result['summary'])
        self.assertTrue('3,84,798.00' in result['summary'] or '384798.00' in result['summary'])
        self.assertIn('Sundry Creditors me nahi hai', result['summary'])
        self.assertIn('6 stock items missing', result['summary'])
        self.assertIn('Kya main Tally me TimeNet Solutions ka Sundry Creditor ledger bana doon ya kisi existing ledger se map karna hai?', result['summary'])


if __name__ == '__main__':
    unittest.main()
