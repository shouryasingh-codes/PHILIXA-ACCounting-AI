"""Chat GST handoff and existing validated preview; synthetic masters only."""
import unittest
from unittest.mock import patch,AsyncMock
from sqlalchemy import select,func
from fastapi import HTTPException
from app.models.tally import TallyAction,TallySnapshot
from app.models.purchase_draft import PurchaseDraft
from app.services import tally_sync as sync,purchase_draft_service as drafts,purchase_tax_service as tax
from app.services.business_command_service import ParsedCommand,CommandRequest,guard_tally_scope
from app.services.tally_connector import TallyError
from app.services.tally_sync_protocol import serialize_catalog
import scripts.test_gst_purchase as gst_fixtures
from scripts.test_gst_purchase import catalog,profile,content


class ChatGST(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=gst_fixtures.Durable.asyncSetUp
    asyncTearDown=gst_fixtures.Durable.asyncTearDown

    async def command(self,**changes):
        parsed=ParsedCommand(intent='purchase_create',**{'item_name':'Cement','party_name':'Supplier','quantity':'5','unit':'bags','rate':'350',**changes})
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))):
            return await sync.preview_purchase(self.db,self.principal,parsed)

    async def test_chat_partial_draft_preserves_values_without_guessing_or_posting(self):
        result=await self.command(rate=None,party_name=None)
        self.assertNotIn('preview',result)
        view=await drafts.read_draft(self.db,self.principal,result['gst_purchase_draft']['id'])
        self.assertEqual(view['company_id'],self.company.id)
        c=view['content'];self.assertEqual(c['tax_treatment'],'regular_domestic_goods')
        self.assertEqual(c['lines'][0]['quantity'],'5')
        for k in ('supplier_gstin','place_of_supply','invoice_number','entry_date','expected_taxes','invoice_total'):self.assertIsNone(c[k])
        for k in ('gst_rate','hsn','rate'):self.assertIsNone(c['lines'][0][k])
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(TallyAction).where(TallyAction.organization_id==self.org)),0)

    async def test_repeated_command_reopens_working_copy_without_overwriting_edits(self):
        first=await self.command();did=first['draft_id']
        row=await drafts.read_draft(self.db,self.principal,did)
        c=row['content'];c['invoice_number']='KEEP-EDIT'
        await drafts.save_draft(self.db,self.principal,did,drafts.DraftSave(revision=0,content=c))
        again=await self.command()
        self.assertEqual(again['draft_id'],did)
        self.assertEqual((await drafts.read_draft(self.db,self.principal,did))['content']['invoice_number'],'KEEP-EDIT')
        separate=await self.command(purchase_context='a'*32)
        self.assertNotEqual(separate['draft_id'],did,'separate chats cannot silently share the same working purchase')

    async def test_complete_review_uses_gst_compiler_and_disabled_acceptance_stays_disabled(self):
        first=await self.command();did=first['draft_id']
        with self.assertRaises(HTTPException):await drafts.preview_draft(self.db,self.principal,did,drafts.DraftPreview(revision=0))
        await self.db.rollback()
        # Rollback expires ORM fixtures; capture company from persisted draft.
        row=await drafts.read_draft(self.db,self.principal,did)
        await tax.save_profile(self.db,self.principal,row['company_id'],tax.TaxProfileSave(revision=0,**profile()))
        saved=await drafts.save_draft(self.db,self.principal,did,drafts.DraftSave(revision=0,content=content()))
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))),patch('app.services.purchase_memory_service.prepare_preview',AsyncMock()),patch.dict('os.environ',{'PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED':'0'}):
            result=await drafts.preview_draft(self.db,self.principal,did,drafts.DraftPreview(revision=saved['revision']))
            self.assertFalse(result['preview']['can_confirm'])
            action=await self.db.get(TallyAction,result['preview']['token'])
            self.assertEqual(action.payload['operation'],'purchase_gst')
            self.assertEqual(action.payload['total'],'1167.00')
            self.assertEqual(action.status,'preview')
            with self.assertRaises(HTTPException):await sync.confirm_queued(self.db,self.principal,action)

    async def test_unknown_gst_state_not_treated_as_gst(self):
        data=catalog();data['companies']=[]
        snapshot=await self.db.get(TallySnapshot,self.company.id);snapshot.catalog=serialize_catalog(data);await self.db.commit()
        result=await self.command()
        self.assertNotIn('gst_purchase_draft',result);self.assertNotIn('preview',result)

    async def test_explicit_tax_on_non_gst_is_not_silently_dropped(self):
        from scripts.test_tally import FakeTally
        data=await FakeTally().catalog('Pilot Test')
        data['cost_centres_enabled']=False
        snapshot=await self.db.get(TallySnapshot,self.company.id);snapshot.catalog=serialize_catalog(data);await self.db.commit()
        result=await self.command(purchase_tax_review=True)
        self.assertNotIn('preview',result);self.assertIn('non-GST',result['response'])


class Guards(unittest.TestCase):
    def test_gst_purchase_routes_to_review_but_advanced_or_stock_changes_stay_blocked(self):
        for word in ('GST','CGST','discount','जीएसटी'):
            request=CommandRequest(text='Cement purchase '+word,intent='purchase_create')
            result=guard_tally_scope(request,ParsedCommand(intent='purchase_create'))
            self.assertTrue(result.purchase_tax_review);self.assertIsNone(result.unsupported_reason)
        for text,intent in [('purchase batch GST','purchase_create'),('stock count GST','stock_count_set')]:
            result=guard_tally_scope(CommandRequest(text=text,intent=intent),ParsedCommand(intent=intent))
            self.assertTrue(result.unsupported_reason)


if __name__=='__main__':unittest.main()
