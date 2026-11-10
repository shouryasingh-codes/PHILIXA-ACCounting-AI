"""Isolated synthetic DB fixtures; never dispatch a real Tally request."""
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException
from pydantic import ValidationError
from app.models.bill_document import BillDocument
from app.models.purchase_draft import PurchaseDraft
from app.models.tally import TallyAction
from app.services import purchase_review_service as review, purchase_draft_service as drafts, tally_sync as sync
from app.services.tally_connector import TallyError
import scripts.test_tally_sync as fixtures

CONTENT=dict(party_name='Supplier',item_name='Cement',quantity='8',unit='bags',rate='350',entry_date='2026-10-01')

class ReviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.DurableTests.asyncSetUp(self)
        from scripts.purchase_fixture_support import master_ids
        await master_ids(self.db,self.company.id)
        guard=patch('app.services.purchase_memory_service.live_check',AsyncMock())
        guard.start();self.addCleanup(guard.stop)
    asyncTearDown=fixtures.DurableTests.asyncTearDown

    async def ready(self):
        row=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,content={**CONTENT,'invoice_number':__import__('secrets').token_hex(8)}))
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('synthetic offline'))):
            await drafts.preview_draft(self.db,self.principal,row['id'],drafts.DraftPreview(revision=0))
        row=await drafts.read_draft(self.db,self.principal,row['id'])
        return review.ApprovalItem(draft_id=row['id'],revision=row['revision'],action_id=row['action_id'])

    async def test_50_bill_queue_and_independent_bulk_failures(self):
        items=[await self.ready() for _ in range(50)]
        queue=await review.queue(self.db,self.principal,'ready',0,25)
        self.assertEqual(queue['total'],50)
        self.assertEqual(len(queue['bills']),25)
        second=await review.queue(self.db,self.principal,'ready',25,25)
        self.assertFalse({r['id'] for r in queue['bills']} & {r['id'] for r in second['bills']})
        # One changed bill and one expired preview between selection and approval.
        await drafts.save_draft(self.db,self.principal,items[10].draft_id,drafts.DraftSave(revision=1,content={**CONTENT,'quantity':'9'}))
        action=await self.db.get(TallyAction,items[25].action_id)
        action.expires_at=sync.now()-timedelta(seconds=1)
        await self.db.commit()
        result=await review.bulk_approve(self.db,self.principal,review.BulkApproval(items=items))
        self.assertEqual((result['approved'],result['failed']),(48,2))
        self.assertFalse(result['results'][10]['ok'])
        self.assertFalse(result['results'][25]['ok'])
        self.assertTrue(result['results'][49]['ok'])
        queue=await review.queue(self.db,self.principal)
        self.assertEqual(queue['counts']['posting'],48)
        self.assertEqual(queue['counts']['needs_attention'],2)
        repeat=await review.bulk_approve(self.db,self.principal,review.BulkApproval(items=[items[0]]))
        self.assertEqual(repeat['approved'],0)

    async def test_correction_requires_new_validation_and_uses_corrected_amount(self):
        item=await self.ready()
        original=await drafts.read_draft(self.db,self.principal,item.draft_id)
        await drafts.save_draft(self.db,self.principal,item.draft_id,drafts.DraftSave(revision=1,content={**CONTENT,'invoice_number':original['content']['invoice_number'],'quantity':'3'}))
        self.assertEqual((await review.queue(self.db,self.principal))['counts']['ready'],0)
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))):
            await drafts.preview_draft(self.db,self.principal,item.draft_id,drafts.DraftPreview(revision=2))
        row=await drafts.read_draft(self.db,self.principal,item.draft_id)
        action=await self.db.get(TallyAction,row['action_id'])
        self.assertEqual(action.payload['total'],'1050.00')
        self.assertNotEqual(action.token,item.action_id)
        stale=await review.bulk_approve(self.db,self.principal,review.BulkApproval(items=[item]))
        self.assertEqual(stale['approved'],0)
        current=review.ApprovalItem(draft_id=row['id'],revision=row['revision'],action_id=row['action_id'])
        result=await review.bulk_approve(self.db,self.principal,review.BulkApproval(items=[current]))
        self.assertEqual(result['approved'],1)

    async def test_processing_documents_and_errors_are_visible_and_scoped(self):
        stamp=sync.now()
        for i,(status,extraction) in enumerate([('queued',None),('ready','processing'),('error',None)]):
            self.db.add(BillDocument(id=f'{i:032x}',organization_id=self.org,user_id=self.user,
                company_id=self.company.id,filename=f'fixture-{i}.png',media_type='image/png',
                size=1,sha256=f'{i:064x}',object_key='synthetic',status=status,extraction_status=extraction,
                attempts=0,generation=0,created_at=stamp,updated_at=stamp))
        await self.db.commit()
        queue=await review.queue(self.db,self.principal)
        self.assertEqual(queue['counts']['processing'],2)
        self.assertEqual(queue['counts']['needs_attention'],1)
        other=SimpleNamespace(**{**vars(self.principal),'user_id':'other-user'})
        self.assertEqual((await review.queue(self.db,other))['total'],0)

    async def test_session_scope_and_exception_do_not_abort_remaining_bills(self):
        a,b=await self.ready(),await self.ready()
        action=await self.db.get(TallyAction,a.action_id);action.session_id='another-session';await self.db.commit()
        result=await review.bulk_approve(self.db,self.principal,review.BulkApproval(items=[a,b]))
        self.assertEqual((result['approved'],result['failed']),(1,1))
        with self.assertRaises(ValidationError):review.BulkApproval(items=[b,b])

    async def test_failure_rollback_releases_locks_and_later_bill_succeeds(self):
        a,b=await self.ready(),await self.ready()
        original=review.approve_one
        async def fail_one(db,principal,item):
            if item.draft_id==a.draft_id:
                await drafts.scoped_draft(db,principal,item.draft_id,lock=True)
                raise RuntimeError('synthetic database/guard failure')
            return await original(db,principal,item)
        # Real Principal reads IDs from ORM objects; rollback must not break the next item.
        from app.core.auth import Principal
        from app.models.user import User
        from app.models.organization import Organization
        principal=Principal(user=await self.db.get(User,self.user),organization=await self.db.get(Organization,self.org),role='owner',session_id='session')
        with patch.object(review,'approve_one',side_effect=fail_one):
            result=await review.bulk_approve(self.db,principal,review.BulkApproval(items=[a,b]))
        self.assertEqual((result['approved'],result['failed']),(1,1))

if __name__=='__main__':unittest.main()
