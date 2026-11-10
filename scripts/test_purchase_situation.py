import unittest
from unittest.mock import AsyncMock,patch
from fastapi import HTTPException
from sqlalchemy import select,func
from app.services import purchase_situation as intake,purchase_draft_service as drafts
from app.models.tally import TallyAction
from scripts.test_goods_receipt import Receipts


class Evidence(unittest.TestCase):
    def test_buying_does_not_imply_delivery_or_bill(self):
        self.assertEqual(intake.extract('Sharma se 5 Cement bags kharide'),{})
        self.assertEqual(intake.extract('pata nahi'),{})
        self.assertEqual(intake.extract('Agar maal aa gaya aur bill baad mein toh kya?'),{})

    def test_explicit_pending_receipt_and_tax_basis_are_separate(self):
        result=intake.extract('Maal aa gaya, bill baad mein. Received date: 02-10-2026. GST alag lagega.')
        self.assertEqual(result['bill_status']['value'],'pending')
        self.assertEqual(result['goods_status']['value'],'received')
        self.assertEqual(result['received_on']['value'],'2026-10-02')
        self.assertEqual(result['rate_basis']['value'],'tax_exclusive')
        self.assertNotIn('invoice_number',result)

    def test_negative_and_conflicting_evidence(self):
        result=intake.extract('Maal abhi nahi aaya, bill pending')
        self.assertEqual(result['goods_status']['value'],'not_received')
        with self.assertRaises(HTTPException):intake.extract('Bill mil gaya, bill baad mein')


class Routing(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=Receipts.asyncSetUp
    asyncTearDown=Receipts.asyncTearDown
    create=Receipts.create

    async def row(self):
        result=await self.create()
        return await drafts.scoped_draft(self.db,self.principal,result['id'])

    async def test_received_bill_pending_builds_receipt_without_invoice_questions(self):
        row=await self.row()
        await intake.capture(self.db,self.principal,row,'Maal aa gaya, bill baad mein. Received date: 02-10-2026. GST alag lagega.')
        before=await self.db.scalar(select(func.count()).select_from(TallyAction))
        base={'issues':[],'proposal':{'content':row.content},'response':'Invoice number chahiye.'}
        with patch('app.services.purchase_agent.state',new=AsyncMock(return_value=base)):
            result=await intake.state(self.db,self.principal,row.id)
        self.assertTrue(result['receipt_ready'])
        self.assertEqual(result['goods_receipt']['received_on'],'2026-10-02')
        self.assertEqual(result['goods_receipt']['rate_basis'],'tax_exclusive')
        self.assertIsNone(row.content.get('invoice_number'))
        self.assertEqual(before,await self.db.scalar(select(func.count()).select_from(TallyAction)))
        reopened=await drafts.scoped_draft(self.db,self.principal,row.id)
        result=await intake.state(self.db,self.principal,reopened.id)
        self.assertTrue(result['receipt_ready'])

    async def test_pending_bill_without_received_goods_cannot_start_receipt(self):
        row=await self.row()
        await intake.capture(self.db,self.principal,row,'Bill baad mein')
        with patch('app.services.purchase_agent.state',new=AsyncMock(return_value={'issues':[],'response':'pending'})):
            result=await intake.state(self.db,self.principal,row.id)
        self.assertIn('Maal',result['response'])
        self.assertNotIn('goods_receipt',row.extraction_metadata)

    async def test_inclusive_receipt_is_actionable_review_not_ready(self):
        row=await self.row()
        await intake.capture(self.db,self.principal,row,'Maal aa gaya, bill baad mein. Received date: 02-10-2026. GST included.')
        with patch('app.services.purchase_agent.state',new=AsyncMock(return_value={'issues':[],'response':'pending'})):
            result=await intake.state(self.db,self.principal,row.id)
        self.assertFalse(result['receipt_ready'])
        self.assertIn('stock valuation',result['response'])
        self.assertIsNone(row.action_id)

    async def test_confirmed_rate_not_asked_again_when_bill_situation_unknown(self):
        row=await self.row()
        with patch('app.services.purchase_agent.state',new=AsyncMock(return_value={'issues':[],'response':'pending'})):
            result=await intake.state(self.db,self.principal,row.id)
        self.assertNotIn('rate',result['response'].casefold())
        self.assertEqual(result['situation_choices'],['Bill mil gaya','Bill baad mein'])

    async def test_native_unit_spelling_resolves_without_user_roundtrip(self):
        from app.services.purchase_conversation import prepare
        row=await self.row()
        content=dict(row.content);content['lines']=[{**line,'unit':'bag'} for line in content['lines']]
        row.content=content;await self.db.commit()
        row,_,notes=await prepare(self.db,self.principal,row)
        self.assertEqual(row.content['lines'][0]['unit'],'bags')
        self.assertEqual(row.content['lines'][0]['quantity'],'5')
        self.assertEqual(row.content['lines'][0]['rate'],'350')
        self.assertTrue(any('spelling' in note for note in notes))

    async def test_existing_invoice_cannot_silently_switch(self):
        row=await self.row();row.content={**row.content,'invoice_number':'REAL-REFERENCE'};await self.db.commit()
        with self.assertRaises(HTTPException):await intake.capture(self.db,self.principal,row,'Maal aa gaya, bill baad mein')
        self.assertNotIn('goods_receipt',row.extraction_metadata or {})

    async def test_not_received_blocks_stock_purchase_preview(self):
        row=await self.row()
        await intake.capture(self.db,self.principal,row,'Bill mil gaya. Maal abhi nahi aaya.')
        with patch('app.services.purchase_agent.state',new=AsyncMock(return_value={'issues':[],'proposal':{'can_prepare_preview':True}})):
            result=await intake.state(self.db,self.principal,row.id)
        self.assertFalse(result['proposal']['can_prepare_preview'])
        self.assertTrue(any(i['kind']=='blocked' for i in result['issues']))


if __name__=='__main__':unittest.main()
