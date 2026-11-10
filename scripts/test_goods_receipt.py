import copy
import unittest
from types import SimpleNamespace
from sqlalchemy import select,func
from fastapi import HTTPException
from app.models.tally import TallyAction
from app.models.purchase_draft import PurchaseDraft,PurchaseDraftEvent
from app.services import goods_receipt_service as receipts,purchase_conversation as chat,purchase_draft_service as drafts
import scripts.test_purchase_conversation as conversation_fixture

class Receipts(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=conversation_fixture.Conversation.asyncSetUp
    asyncTearDown=conversation_fixture.Conversation.asyncTearDown
    async def create(self):
        return await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,
            content={'party_name':'Supplier','tax_treatment':'regular_domestic_goods',
                'lines':[{'item_name':'Cement','quantity':'5','unit':'bags','rate':'350'}]}))
    async def begin(self):
        target=await self.create()
        s=await chat.answer(self.db,self.principal,target['id'],chat.Reply(revision=0,field='invoice_number',answer='Bill nahi mila'))
        return target,s
    async def reply(self,s,answer):
        p=s['purchase_assistant']
        return await chat.answer(self.db,self.principal,p['draft_id'],chat.Reply(revision=p['revision'],field=p['field'],answer=answer))
    async def test_bill_pending_is_durable_and_never_creates_invoice_or_action(self):
        target,s=await self.begin()
        self.assertEqual(s['purchase_assistant']['field'],'receipt:date')
        tracking=s['goods_receipt']['tracking_reference']
        s=await self.reply(s,'02-10-2026')
        self.assertEqual(s['purchase_assistant']['field'],'receipt:basis')
        s=await self.reply(s,'GST alag lagega')
        self.assertFalse(s['goods_receipt']['posting_available'])
        self.assertEqual(s['goods_receipt']['received_on'],'2026-10-02')
        await self.db.rollback();self.db.expire_all()
        s=await chat.state(self.db,self.principal,target['id'])
        self.assertEqual(s['goods_receipt']['tracking_reference'],tracking)
        row=await drafts.read_draft(self.db,self.principal,target['id'])
        self.assertIsNone(row['content']['invoice_number']);self.assertIsNone(row['content']['entry_date'])
        self.assertIsNone(row['action_id']);self.assertNotIn('preview',s)
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(TallyAction).where(TallyAction.company_id==self.company.id)),0)
        events=list((await self.db.scalars(select(PurchaseDraftEvent).where(PurchaseDraftEvent.draft_id==target['id']))).all())
        self.assertTrue(any(e.kind=='receipt_updated' and e.snapshot.get('_event_details',{}).get('goods_receipt') for e in events))
    async def test_generic_purchase_preview_is_blocked(self):
        target,s=await self.begin()
        with self.assertRaises(HTTPException) as e:
            await drafts.preview_draft(self.db,self.principal,target['id'],drafts.DraftPreview(revision=s['purchase_assistant']['revision']))
        self.assertEqual(e.exception.status_code,409)
    async def test_stale_revision_and_cross_user_rejected(self):
        target,s=await self.begin()
        with self.assertRaises(HTTPException) as e:
            await chat.answer(self.db,self.principal,target['id'],chat.Reply(revision=0,field='receipt:date',answer='02-10-2026'))
        self.assertEqual(e.exception.status_code,409)
        other=copy.copy(self.principal);other.user_id='someone-else'
        with self.assertRaises(HTTPException):await chat.state(self.db,other,target['id'])
    async def test_resume_and_future_or_ambiguous_facts(self):
        target,s=await self.begin()
        s=await chat.answer(self.db,self.principal,target['id'],chat.Reply(resume=True))
        s=await self.reply(s,'01-01-2099')
        self.assertIsNone(s['goods_receipt']['received_on'])
        s=await self.reply(s,'02-10-2026')
        s=await self.reply(s,'without GST')
        self.assertIsNone(s['goods_receipt']['rate_basis'])
        s=await self.reply(s,'Supplier GST charge nahi kar raha')
        self.assertEqual(s['goods_receipt']['rate_basis'],'no_gst_charged')
    async def test_existing_invoice_cannot_silently_switch(self):
        target=await self.create();row=await self.db.get(PurchaseDraft,target['id'])
        row.content={**row.content,'invoice_number':'INV-1'};await self.db.commit()
        with self.assertRaises(HTTPException):await receipts.begin(self.db,self.principal,row)
    async def test_missing_facts_and_wrong_unit_are_not_receipts(self):
        target=await self.create();row=await self.db.get(PurchaseDraft,target['id'])
        c=copy.deepcopy(row.content);c['lines'][0]['unit']='kg';row.content=c;await self.db.commit()
        with self.assertRaises(HTTPException) as e:await receipts.begin(self.db,self.principal,row)
        self.assertEqual(e.exception.status_code,422)
        self.assertIsNone(receipts.receipt(row))
    async def test_pause_keeps_same_saved_receipt(self):
        target,s=await self.begin();ref=s['goods_receipt']['tracking_reference']
        result=await self.reply(s,'baad mein')
        self.assertEqual(result['purchase_resume'],target['id'])
        result=await chat.answer(self.db,self.principal,target['id'],chat.Reply(resume=True))
        self.assertEqual(result['goods_receipt']['tracking_reference'],ref)

if __name__=='__main__':unittest.main()
