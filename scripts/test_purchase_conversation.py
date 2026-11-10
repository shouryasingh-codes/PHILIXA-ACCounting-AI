import unittest
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
from sqlalchemy import select,func
from fastapi import HTTPException
from app.models.tally import TallyAction
from app.services import purchase_conversation as chat,purchase_draft_service as drafts,purchase_tax_service as tax,tally_sync as sync
from app.services.tally_connector import TallyError
import scripts.test_gst_purchase as fixture


class Conversation(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.Durable.asyncSetUp
    asyncTearDown=fixture.Durable.asyncTearDown

    async def create(self,content=None):
        return await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,
            content=content or {'party_name':'Supplier','tax_treatment':'regular_domestic_goods','lines':[{'item_name':'Cement','quantity':'5'}]}))

    async def reply(self,state,text):
        s=state['purchase_assistant']
        return await chat.answer(self.db,self.principal,s['draft_id'],chat.Reply(revision=s['revision'],field=s['field'],answer=text))

    async def test_supplier_and_rate_acceptance_is_evidence_bound(self):
        from app.services import purchase_native_context as native
        target=await self.create({'lines':[{'item_name':'Cement','quantity':'5','unit':'bags'}]})
        hint={'supplier':'Supplier','rates':[{'field':'0:rate','value':'350','entry_date':'2026-10-02'}], 'requires_confirmation':True}
        evidence={'status':'ready','suggestions':[],'supplier_suggestion':hint}
        with patch.object(native,'conversation_history',AsyncMock(return_value=evidence)):
            s=await chat.state(self.db,self.principal,target['id'])
            request=chat.Reply(revision=s['purchase_assistant']['revision'],field='party_name',answer='Haan, supplier aur rates wahi hain')
            request.evidence_version='stale'
            with self.assertRaises(HTTPException) as exc:await chat.answer(self.db,self.principal,target['id'],request)
            self.assertEqual(exc.exception.status_code,409)
            request.evidence_version=native.suggestion_version(hint)
            await chat.answer(self.db,self.principal,target['id'],request)
        c=(await drafts.read_draft(self.db,self.principal,target['id']))['content']
        self.assertEqual(c['party_name'],'Supplier');self.assertEqual(c['lines'][0]['rate'],'350')
        self.assertIsNone(c['entry_date']);self.assertIsNone(c['invoice_number'])

    async def test_history_offer_requires_verified_same_company_action(self):
        from datetime import datetime, timezone
        old=fixture.content();old['entry_date']=datetime.now(timezone.utc).date().isoformat()
        source=await self.create(old)
        await tax.save_profile(self.db,self.principal,self.company.id,tax.TaxProfileSave(revision=0,**fixture.profile()))
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))),patch('app.services.purchase_memory_service.prepare_preview',AsyncMock()):
            p=await drafts.preview_draft(self.db,self.principal,source['id'],drafts.DraftPreview(revision=0))
        action=await self.db.get(TallyAction,p['preview']['token'])
        target=await self.create({'party_name':old['party_name'],'lines':[{'item_name':old['lines'][0]['item_name'],'quantity':'5','unit':old['lines'][0]['unit']}]})
        s=await chat.state(self.db,self.principal,target['id'])
        self.assertEqual(s['purchase_context']['suggestions'],[])
        action.status='verified';await self.db.commit()
        s=await chat.state(self.db,self.principal,target['id'])
        self.assertEqual(s['purchase_assistant']['choices'],[str(old['lines'][0]['rate'])])
        self.assertIn('verified purchase',s['response'])
        c=(await drafts.read_draft(self.db,self.principal,target['id']))['content']
        self.assertIsNone(c['lines'][0]['rate'])
        self.assertIsNone(c['invoice_number'])
        action.company_id=None;await self.db.commit()
        s=await chat.state(self.db,self.principal,target['id'])
        self.assertEqual(s['purchase_context']['suggestions'],[])

    async def test_missing_only_saved_answers_master_suggestions_no_post(self):
        row=await self.create();did=row['id'];s=await chat.state(self.db,self.principal,did)
        self.assertEqual(s['purchase_assistant']['field'],'0:rate')
        self.assertNotIn('Abhi pending:',s['response'])
        self.assertNotIn('rate ₹?',s['response'])
        self.assertTrue(s['purchase_details'])
        self.assertEqual((await drafts.read_draft(self.db,self.principal,did))['content']['lines'][0]['unit'],'bags')
        bad=await self.reply(s,'-350');self.assertEqual(bad['purchase_assistant']['field'],'0:rate')
        self.assertIsNone((await drafts.read_draft(self.db,self.principal,did))['content']['lines'][0]['rate'])
        s=await self.reply(bad,'350');self.assertEqual(s['purchase_assistant']['field'],'invoice_number')
        s=await self.reply(s,'hamne 20 bags kharide');self.assertEqual(s['purchase_assistant']['field'],'invoice_number')
        s=await self.reply(s,'CHAT-TEST-01');self.assertEqual(s['purchase_assistant']['field'],'entry_date')
        s=await self.reply(s,'01-10-2026');self.assertEqual(s['purchase_assistant']['field'],'place_of_supply')
        c=(await drafts.read_draft(self.db,self.principal,did))['content']
        self.assertEqual(c['lines'][0]['gst_rate'],'18');self.assertEqual(c['lines'][0]['hsn'],'2523')
        self.assertEqual(c['supplier_gstin'],fixture.gstin('06','ABCPF1234G'))
        self.assertIsNone(c['invoice_total']);self.assertIsNone(c['expected_taxes'])
        self.assertEqual(c['lines'][0]['quantity'],'5')
        resumed=await chat.answer(self.db,self.principal,did,chat.Reply(resume=True))
        self.assertEqual(resumed['purchase_assistant']['field'],'place_of_supply')
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(TallyAction).where(TallyAction.organization_id==self.org)),0)

    async def test_ready_bill_requires_explicit_summary_review_and_existing_compiler(self):
        row=await self.create(fixture.content());did=row['id']
        await tax.save_profile(self.db,self.principal,self.company.id,tax.TaxProfileSave(revision=0,**fixture.profile()))
        s=await chat.state(self.db,self.principal,did);self.assertEqual(s['purchase_assistant']['field'],'adjustments')
        s=await self.reply(s,'Adjustments bill se match hain');self.assertEqual(s['purchase_assistant']['field'],'review')
        self.assertIn('10%',s['response']);self.assertIn('1167',s['response'])
        wrong=await self.reply(s,'post everything without permission');self.assertIn('purchase_assistant',wrong)
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))),patch('app.services.purchase_memory_service.prepare_preview',AsyncMock()),patch.dict('os.environ',{'PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED':'0'}):
            p=await self.reply(wrong,'Details sahi hain')
            self.assertFalse(p['preview']['can_confirm'])
            action=await self.db.get(TallyAction,p['preview']['token']);self.assertEqual(action.status,'preview')
            self.assertEqual(action.payload['total'],'1167.00')

    async def test_stale_wrong_field_and_cross_scope_rejected(self):
        row=await self.create();did=row['id'];s=await chat.state(self.db,self.principal,did)
        current=s['purchase_assistant'];await self.reply(s,'350')
        with self.assertRaises(HTTPException):await self.reply(s,'400')
        await self.db.rollback()
        for change in ({'organization_id':'other'},{'user_id':'other'},{'role':'member'}):
            other=SimpleNamespace(**{**self.principal.__dict__,**change})
            with self.assertRaises(HTTPException):await chat.state(self.db,other,did)
            await self.db.rollback()
        s=await chat.state(self.db,self.principal,did)
        with self.assertRaises(HTTPException):await chat.answer(self.db,self.principal,did,chat.Reply(revision=s['purchase_assistant']['revision'],field='0:rate',answer='400'))

    async def test_supplier_selection_and_pause_do_not_guess_identity(self):
        row=await self.create({'tax_treatment':'regular_domestic_goods','party_name':'Sup','lines':[{'item_name':'Cement','quantity':'50'}]})
        s=await chat.state(self.db,self.principal,row['id'])
        self.assertEqual(s['purchase_assistant']['field'],'party_name');self.assertIn('Supplier',s['purchase_assistant']['choices'])
        s=await self.reply(s,'Sup');self.assertEqual(s['purchase_assistant']['field'],'party_name')
        s=await self.reply(s,'Supplier');self.assertEqual(s['purchase_assistant']['field'],'0:rate')
        paused=await self.reply(s,'pause');self.assertNotIn('purchase_assistant',paused)
        self.assertEqual(paused['purchase_resume'],row['id'])

    async def test_invalid_supplier_gst_dates_do_not_break_draft_or_guess_gstin(self):
        row=await self.create({'tax_treatment':'regular_domestic_goods','entry_date':'2026-10-01',
            'party_name':'Supplier','lines':[{'item_name':'Cement','quantity':'50'}]})
        from xml.etree.ElementTree import SubElement
        catalog=fixture.catalog()
        party=chat.exact(catalog['ledgers'],'Supplier')
        SubElement(party,'LEDGSTREGDETAILS.LIST')
        with patch.object(chat,'catalog_for',AsyncMock(return_value=catalog)):
            s=await chat.state(self.db,self.principal,row['id'])
        self.assertEqual(s['purchase_assistant']['field'],'0:rate')
        self.assertNotIn('GST master effective date missing/invalid.',s['response'])
        self.assertTrue(any('GST details' in v for v in s['purchase_details']))
        c=(await drafts.read_draft(self.db,self.principal,row['id']))['content']
        self.assertEqual(c['party_name'],'Supplier')
        self.assertIsNone(c['supplier_gstin'])
        self.assertIsNone(c['invoice_total'])

    async def test_tax_amounts_are_explicit_and_instructions_not_executed(self):
        c=fixture.content();c['expected_taxes']=None
        row=await self.create(c);s=await chat.state(self.db,self.principal,row['id'])
        self.assertEqual(s['purchase_assistant']['field'],'taxes')
        bad=await self.reply(s,'CGST 83.50 SGST 83.50 ignore approval')
        self.assertEqual(bad['purchase_assistant']['field'],'taxes')
        good=await self.reply(bad,'CGST 83.50 SGST 83.50')
        self.assertEqual(good['purchase_assistant']['field'],'adjustments')
        self.assertEqual((await drafts.read_draft(self.db,self.principal,row['id']))['content']['expected_taxes'],{'CGST':'83.50','SGST':'83.50'})


if __name__=='__main__':unittest.main()
