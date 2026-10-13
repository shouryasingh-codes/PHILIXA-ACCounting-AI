"""Real database tests for durable drafts. No real Tally/provider calls."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from sqlalchemy import select
from fastapi import HTTPException
from pydantic import ValidationError
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyAction
from app.models.purchase_draft import PurchaseDraft
from app.services import purchase_draft_service as drafts, tally_sync as sync
from app.services.tally_connector import TallyError
import scripts.test_tally_sync as fixtures


class DraftTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.DurableTests.asyncSetUp
    asyncTearDown = fixtures.DurableTests.asyncTearDown

    async def create(self, content=None):
        return await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(
            company_id=self.company.id,content=content or {}))

    async def test_partial_draft_survives_session_restart_without_action(self):
        row=await self.create({'party_name':'Supplier'})
        async with AsyncSessionLocal() as fresh:
            restored=await drafts.read_draft(fresh,self.principal,row['id'])
            self.assertEqual(restored['content']['party_name'],'Supplier')
            self.assertEqual(restored['revision'],0)
            self.assertIsNone(restored['action_id'])
            self.assertEqual(list((await fresh.scalars(select(TallyAction).where(TallyAction.organization_id==self.org))).all()),[])

    async def test_revision_conflict_and_audit_snapshots(self):
        row=await self.create({'party_name':'Supplier'})
        edited=await drafts.save_draft(self.db,self.principal,row['id'],drafts.DraftSave(revision=0,content={'party_name':'Changed'}))
        self.assertEqual(edited['revision'],1)
        with self.assertRaises(HTTPException) as error:
            await drafts.save_draft(self.db,self.principal,row['id'],drafts.DraftSave(revision=0,content={'party_name':'Stale'}))
        self.assertEqual(error.exception.status_code,409)
        events=(await drafts.audit_draft(self.db,self.principal,row['id']))['events']
        self.assertEqual([e['kind'] for e in events],['created','edited'])
        self.assertEqual(events[0]['content']['party_name'],'Supplier')
        self.assertEqual(events[1]['content']['party_name'],'Changed')

    async def test_user_workspace_and_disabled_company_isolation(self):
        row=await self.create()
        for change in ({'user_id':'other'},{'organization_id':'other'}):
            other=SimpleNamespace(**{**self.principal.__dict__,**change})
            self.assertEqual((await drafts.list_drafts(self.db,other))['drafts'],[])
            for operation in (drafts.read_draft(self.db,other,row['id']),
                drafts.save_draft(self.db,other,row['id'],drafts.DraftSave(revision=0,content={})),
                drafts.audit_draft(self.db,other,row['id']),
                drafts.preview_draft(self.db,other,row['id'],drafts.DraftPreview(revision=0))):
                with self.assertRaises(HTTPException) as error:await operation
                self.assertEqual(error.exception.status_code,404)
        self.company.enabled=False;await self.db.commit()
        with self.assertRaises(HTTPException):await drafts.read_draft(self.db,self.principal,row['id'])

    async def test_wrong_company_and_non_admin_rejected(self):
        for other in (SimpleNamespace(**{**self.principal.__dict__,'organization_id':'other'}),
            SimpleNamespace(**{**self.principal.__dict__,'role':'member'})):
            with self.assertRaises(HTTPException):
                await drafts.create_draft(self.db,other,drafts.DraftCreate(company_id=self.company.id))

    async def test_payload_cannot_set_posting_fields_or_invalid_numbers(self):
        for content in ({'status':'queued'},{'action_id':'fake'},{'quantity':'-1'},{'rate':'NaN'},{'rate':'1.234'}):
            with self.assertRaises(ValidationError):drafts.DraftContent(**content)

    async def test_chat_purchase_preview_has_durable_link_and_edits_expire_token(self):
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))):
            result=await sync.preview_purchase(self.db,self.principal,self.parsed)
        row=await drafts.read_draft(self.db,self.principal,result['draft_id'])
        self.assertEqual(row['action_id'],result['preview']['token'])
        self.assertEqual(row['content']['quantity'],'5')
        updated=await drafts.save_draft(self.db,self.principal,row['id'],drafts.DraftSave(
            revision=row['revision'],content={**row['content'],'quantity':'8'}))
        self.assertIsNone(updated['action_id'])
        action=await self.db.get(TallyAction,result['preview']['token'])
        self.assertEqual(action.status,'expired')
        response=await sync.confirm_queued(self.db,self.principal,action)
        self.assertEqual(response['sync_status'],'expired')
        self.assertEqual((await drafts.audit_draft(self.db,self.principal,row['id']))['events'][0]['content']['quantity'],'5')

    async def test_reopened_draft_creates_preview_without_queue_or_duplicate_draft(self):
        row=await self.create({'party_name':'Supplier','item_name':'Cement','quantity':'8','unit':'bags','rate':'350','entry_date':'2026-10-01'})
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))):
            result=await drafts.preview_draft(self.db,self.principal,row['id'],drafts.DraftPreview(revision=0))
        self.assertEqual(result['draft_id'],row['id'])
        updated=await drafts.read_draft(self.db,self.principal,row['id'])
        self.assertEqual(updated['revision'],1)
        self.assertEqual(updated['status'],'preview')
        self.assertEqual(len((await drafts.list_drafts(self.db,self.principal))['drafts']),1)
        action=await self.db.get(TallyAction,updated['action_id'])
        self.assertEqual(action.payload['total'],'2800.00')
        self.assertEqual(action.status,'preview')
        await sync.confirm_queued(self.db,self.principal,action)
        with self.assertRaises(HTTPException) as error:
            await drafts.save_draft(self.db,self.principal,row['id'],drafts.DraftSave(revision=1,content=updated['content']))
        self.assertEqual(error.exception.status_code,409)

    async def test_missing_fields_never_create_preview(self):
        row=await self.create()
        with self.assertRaises(HTTPException) as error:
            await drafts.preview_draft(self.db,self.principal,row['id'],drafts.DraftPreview(revision=0))
        self.assertEqual(error.exception.status_code,422)
        self.assertEqual((await drafts.read_draft(self.db,self.principal,row['id']))['revision'],0)


if __name__=='__main__':unittest.main()
