"""Day 7 isolated DB + pure connector tests. No provider or real Tally calls."""
import copy
import tempfile
import unittest
import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from fastapi import HTTPException
from app.models.purchase_draft import PurchaseDraft
from app.models.bill_document import BillDocument
from app.models.tally import TallyAction,TallySnapshot
from app.models.purchase_memory import PurchaseInvoiceClaim
from app.services import purchase_memory_service as memory,purchase_identity as identity,purchase_draft_service as drafts,tally_sync as sync
from app.services import invoice_extraction as extraction
from app.services.tally_connector import TallyError,tag
from app.services.tally_sync_protocol import deserialize_catalog,serialize_catalog
import scripts.test_tally_sync as fixtures
from scripts.purchase_fixture_support import master_ids

CONTENT=dict(party_name='Supplier',entry_date='2026-10-02',invoice_number='INV-7',lines=[dict(item_name='Cement',quantity='2',rate='100',unit='bags')])

class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.DurableTests.asyncSetUp(self)
        await master_ids(self.db,self.company.id)
        guard=patch.object(memory,'live_check',AsyncMock());guard.start();self.addCleanup(guard.stop)
    asyncTearDown=fixtures.DurableTests.asyncTearDown
    async def create(self,reference='INV-7'):
        return await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,content={**CONTENT,'invoice_number':reference}))
    async def evidence(self):
        row=await self.create()
        native=await self.db.get(PurchaseDraft,row['id'])
        native.extraction_metadata={'field_evidence':{'party_name':{'raw':'My supplier OCR'}},'line_evidence':[{'item_name':{'raw':'Cement OCR'}}]}
        await self.db.commit();return row
    async def test_explicit_alias_reused_and_master_change_invalidates(self):
        row=await self.evidence()
        self.assertEqual(await memory.reusable_aliases(self.db,self.principal,self.company.id),{})
        await memory.approve_alias(self.db,self.principal,row['id'],memory.AliasApproval(revision=0,kind='supplier'))
        await memory.approve_alias(self.db,self.principal,row['id'],memory.AliasApproval(revision=1,kind='item',line_index=0))
        aliases=await memory.reusable_aliases(self.db,self.principal,self.company.id)
        raw=dict(supplier_name='My supplier OCR',invoice_number='NEXT',invoice_date='2026-10-02',lines=[dict(item_name='Cement OCR',quantity='2',rate='100',unit='bags',confidence=.99)],total_amount='200',confidence={})
        result=extraction.verify_and_match(raw,dict(suppliers=['Supplier'],items=[dict(name='Cement',unit='bags')],approved_aliases=aliases))
        self.assertEqual(result['party_name'],'Supplier');self.assertEqual(result['lines'][0]['item_name'],'Cement')
        self.assertEqual(result['line_evidence'][0]['item_name']['raw'],'Cement OCR');self.assertEqual(len(result['approved_aliases']),2)
        self.assertEqual((await drafts.read_draft(self.db,self.principal,row['id']))['revision'],2)
        doc=BillDocument(id=secrets.token_hex(16),organization_id=self.org,user_id=self.user,company_id=self.company.id,filename='next-photo.png',media_type='image/png',size=1,sha256=secrets.token_hex(32),object_key='synthetic',status='ready',page_count=1,attempts=0,generation=0,created_at=sync.now(),updated_at=sync.now())
        self.db.add(doc);await self.db.commit()
        saved=await extraction.process_document_extraction(self.db,self.principal,doc.id,raw_result=copy.deepcopy(raw))
        self.assertEqual(saved['draft']['content']['party_name'],'Supplier')
        self.assertEqual(saved['draft']['content']['lines'][0]['item_name'],'Cement')
        self.assertEqual(len(saved['draft']['extraction_metadata']['approved_aliases']),2)
        from app.models.tally import TallyReadCompany
        other=TallyReadCompany(id=secrets.token_hex(16),organization_id=self.org,identity='other-company',name='Other company',enabled=True,aliases=[],member_ids=[],refresh_requested=False)
        self.db.add(other);await self.db.flush()
        original=await self.db.get(TallySnapshot,self.company.id)
        self.db.add(TallySnapshot(company_id=other.id,generation='other',identity=other.identity,device_version=None,as_of=original.as_of,collected_at=sync.now(),catalog=copy.deepcopy(original.catalog),items=copy.deepcopy(original.items)))
        await self.db.commit()
        self.assertEqual(await memory.reusable_aliases(self.db,self.principal,other.id),{})

        self.assertIsNone(saved['draft']['action_id'])

        snapshot=await self.db.get(TallySnapshot,self.company.id);catalog=deserialize_catalog(snapshot.catalog)
        catalog['items'][0].find('BASEUNITS').text='pcs';snapshot.catalog=serialize_catalog(catalog);await self.db.commit()
        aliases=await memory.reusable_aliases(self.db,self.principal,self.company.id)
        self.assertNotIn('item:cement ocr',aliases)
        with self.assertRaises(TallyError):await memory.validate_bindings(self.db,self.company,result['approved_aliases'])
    async def test_stale_alias_request_and_cross_workspace_rejected(self):
        row=await self.evidence()
        with self.assertRaises(HTTPException):await memory.approve_alias(self.db,self.principal,row['id'],memory.AliasApproval(revision=5,kind='supplier'))
        other=SimpleNamespace(**{**vars(self.principal),'organization_id':'other'})
        with self.assertRaises(HTTPException):await memory.approve_alias(self.db,other,row['id'],memory.AliasApproval(revision=0,kind='supplier'))
    async def test_renamed_reformatted_invoice_blocked_and_reservation_persisted(self):
        first=await self.create()
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))):
            await drafts.preview_draft(self.db,self.principal,first['id'],drafts.DraftPreview(revision=0))
        first=await drafts.read_draft(self.db,self.principal,first['id']);action=await self.db.get(TallyAction,first['action_id'])
        guard=action.preconditions['invoice_guard']
        await sync.confirm_queued(self.db,self.principal,action)
        self.assertEqual((await self.db.get(PurchaseInvoiceClaim,guard['key'])).action_id,action.token)
        second=await self.create(' inv-7 ')
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))):
            with self.assertRaises(HTTPException) as error:await drafts.preview_draft(self.db,self.principal,second['id'],drafts.DraftPreview(revision=0))
        self.assertIn('Duplicate',str(error.exception.detail))
    async def test_same_source_cannot_evade_duplicate_by_editing_reference(self):
        first,second=await self.create(),await self.create('EDITED-REFERENCE')
        doc=BillDocument(id=secrets.token_hex(16),organization_id=self.org,user_id=self.user,company_id=self.company.id,filename='renamed.png',media_type='image/png',size=1,sha256='7'*64,object_key='synthetic',status='ready',attempts=0,generation=0,created_at=sync.now(),updated_at=sync.now())
        self.db.add(doc);await self.db.flush()
        for r in (first,second):(await self.db.get(PurchaseDraft,r['id'])).document_id=doc.id
        await self.db.commit()
        second=await self.db.get(PurchaseDraft,second['id'])
        catalog=await memory.catalog_for(self.db,self.company)
        guard=identity.invoice_guard(self.company.identity,catalog,second.content)
        with self.assertRaises(TallyError):await memory.check_local(self.db,second,guard)
    async def test_punctuation_and_fuzzy_names_are_only_suggestions(self):
        self.assertFalse(extraction.match_supplier('ABC-Ltd',['ABC Ltd'])['matched'])
        self.assertFalse(extraction.match_item('Cement-OPC',[{'name':'Cement OPC','unit':'bags'}])['matched'])
        self.assertFalse(extraction.match_supplier('Supplier',['Supplier','supplier'])['matched'])

    async def test_missing_reference_or_date_and_year_boundary(self):
        catalog=await memory.catalog_for(self.db,self.company)
        for field in ('invoice_number','entry_date'):
            with self.assertRaises(TallyError):identity.invoice_guard('identity',catalog,{**CONTENT,field:None})
        a=identity.invoice_guard('identity',catalog,{**CONTENT,'entry_date':'2026-03-31'})
        b=identity.invoice_guard('identity',catalog,{**CONTENT,'entry_date':'2026-04-01'})
        self.assertNotEqual(a['key'],b['key'])
        self.assertNotEqual(b['key'],identity.invoice_guard('other-company',catalog,CONTENT)['key'])

class NativeDuplicateTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_purchase_checked_over_full_year_and_cancelled_ignored(self):
        from scripts.test_tally_sync import node
        supplier=node('LEDGER','Supplier',GUID='supplier-id',PARENT='Sundry Creditors')
        catalog={'ledgers':[supplier],'items':[]}
        guard=identity.invoice_guard('identity',catalog,CONTENT)
        voucher=node('VOUCHER','',GUID='old',VOUCHERTYPENAME='Purchase',PARTYLEDGERNAME='Supplier',REFERENCE=' inv-7 ',DATE='20260930')
        connector=SimpleNamespace(catalog=AsyncMock(return_value=catalog),collection=AsyncMock(return_value=[voucher]),post=AsyncMock())
        self.assertEqual((await identity.check_native(connector,'Pilot Test',guard))['status'],'duplicate')
        connector.collection.assert_awaited_with('Voucher','Pilot Test','2027-03-31',from_date='2026-04-01')
        tag(voucher,'ISCANCELLED','Yes')
        self.assertEqual((await identity.check_native(connector,'Pilot Test',guard))['status'],'clear')
        connector.post.assert_not_awaited()
        voucher.remove(voucher.find('ISCANCELLED'));voucher.find('REFERENCE').text=''
        self.assertEqual((await identity.check_native(connector,'Pilot Test',guard))['status'],'review_required')
        voucher.find('REFERENCE').text='INV-7';voucher.find('VOUCHERTYPENAME').text='Custom Purchase'
        self.assertEqual((await identity.check_native(connector,'Pilot Test',guard))['status'],'review_required')
    async def test_duplicate_blocks_gst_and_multi_post_before_write(self):
        from scripts.test_tally_sync import node
        from app.services import tally_gst_purchase as gst,tally_multi_purchase as multi
        supplier=node('LEDGER','Supplier',GUID='supplier-id',PARENT='Sundry Creditors')
        catalog={'ledgers':[supplier],'items':[]};guard=identity.invoice_guard('identity',catalog,CONTENT)
        voucher=node('VOUCHER','',GUID='old',VOUCHERTYPENAME='Purchase',PARTYLEDGERNAME='Supplier',REFERENCE='INV-7',DATE='20261002')
        connector=SimpleNamespace(catalog=AsyncMock(return_value=catalog),collection=AsyncMock(return_value=[voucher]),post=AsyncMock())
        for module,prefix,validate,execute in [(gst,'purchase_gst','validate',gst.execute),(multi,'purchase_multi','validate_multi',multi.execute_multi)]:
            with patch.object(module,validate,return_value=None):
                result=await execute(prefix+'_post',connector,'Pilot Test','identity',dict(operation=prefix,company='Pilot Test',date='2026-10-02',guid='new'),{'invoice_guard':guard},'unused-test-journal')
            self.assertEqual(result['status'],'needs_review');self.assertFalse(result['uncertain'])
        connector.post.assert_not_awaited()

class LegacyReferenceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.ProtocolTests.asyncSetUp
    asyncTearDown=fixtures.ProtocolTests.asyncTearDown
    async def test_post_and_reconcile_verify_reference_and_never_resend(self):
        from app.services import tally_sync_protocol as protocol
        from app.services.tally_connector import name
        supplier=next(r for r in self.data['ledgers'] if name(r)=='Supplier');tag(supplier,'GUID','supplier-legacy')
        self.p['master_fingerprint']=protocol.fingerprint(self.data,self.p)
        guard=identity.invoice_guard('identity',self.data,dict(party_name='Supplier',invoice_number='LEGACY-7',entry_date=self.p['date']))
        cfg={**self.cfg,'invoice_guard':guard}
        first=await protocol.execute_sync('purchase_post',company='Pilot Test',identity='identity',payload=self.p,config=cfg,journal_path=self.path)
        self.assertEqual(first['status'],'verified',first);self.assertEqual(self.posts,1)
        self.vouchers[0].find('REFERENCE').text='changed'
        again=await protocol.execute_sync('purchase_reconcile',company='Pilot Test',identity='identity',payload=self.p,config=cfg,journal_path=self.path)
        self.assertEqual(again['status'],'needs_review');self.assertEqual(self.posts,1)

    async def test_multi_post_with_real_guard_config_and_reference(self):
        from app.services import tally_multi_purchase as multi
        from scripts.test_multi_purchase import payload
        from app.services import tally_sync_protocol as protocol
        from app.services.tally_connector import name
        supplier=next(r for r in self.data['ledgers'] if name(r)=='Supplier');tag(supplier,'GUID','supplier-multi')
        p=payload(self.p);p['master_fingerprint']=multi.fingerprint_multi(self.data,p)
        guard=identity.invoice_guard('identity',self.data,dict(party_name='Supplier',invoice_number='MULTI-7',entry_date=p['date']))
        result=await multi.execute_multi('purchase_multi_post',self.connector,'Pilot Test','identity',p,{**self.cfg,'invoice_guard':guard},self.path)
        self.assertEqual(result['status'],'verified',result);self.assertEqual(self.posts,1)
        self.assertEqual(self.vouchers[0].find('REFERENCE').text,'multi-7')

class GstReferenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_gst_post_with_real_guard_config(self):
        import uuid
        from xml.etree import ElementTree as ET
        from app.services import tally_gst_purchase as gst
        from app.services.tally_connector import parse_xml
        import scripts.test_gst_purchase as f
        catalog=f.catalog();content=f.content();config=f.config()
        p=gst.compile_purchase(catalog,content,f.profile(),config,str(uuid.uuid4()))
        guard=identity.invoice_guard('identity',catalog,content);vouchers=[];posts=[]
        async def collection(*args,**kwargs):return vouchers
        async def post(xml):
            posts.append(xml);v=parse_xml(xml.encode()).find('.//VOUCHER');tag(v,'VOUCHERNUMBER','7');vouchers.append(v);return ET.Element('REPLY')
        connector=SimpleNamespace(catalog=AsyncMock(return_value=catalog),collection=collection,post=post)
        with tempfile.TemporaryDirectory() as tmp:
            result=await gst.execute('purchase_gst_post',connector,'Pilot Test','identity',p,{**config,'invoice_guard':guard},tmp+'/journal')
        self.assertEqual(result['status'],'verified',result);self.assertEqual(len(posts),1)

if __name__=='__main__':unittest.main()
