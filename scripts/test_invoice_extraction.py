"""Real database + storage tests for Day 4 invoice extraction and editable drafts.

Covers:
- Header & line array extraction
- Preservation of source page and field evidence
- Supplier master matching against Sundry Creditors (exact, normalized, fuzzy, unmatched)
- Stock item matching against StockItem masters with auto-filled base units
- Mathematical sanity check and highlighting of unclear values / missing lines
- Multi-invoice detection and splitting into separate drafts
- Strict safety invariant: AI extraction NEVER directly posts to Tally; creates editable draft in needs_review state
"""
import asyncio
import copy
import io
import json
import unittest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, AsyncMock
from fastapi import UploadFile, HTTPException
from sqlalchemy import select
import pymupdf
from PIL import Image

from app.database.session import AsyncSessionLocal
from app.models.bill_document import BillDocument
from app.models.purchase_draft import PurchaseDraft, PurchaseDraftEvent
from app.models.tally import TallyAction
from app.services import bill_document_service as docs, document_storage as storage, purchase_draft_service as drafts
from app.services import invoice_extraction as extractor
from app.jobs import document_jobs as jobs
from app.api.v1 import routes_bill_documents as routes
import scripts.test_tally_sync as fixtures


def synthetic_invoice_pdf(pages=1, invoice_no='INV-2026-001', supplier='UltraTech Cement Ltd', multi_inv=False):
    """Generate a realistic test invoice PDF using PyMuPDF."""
    with pymupdf.open() as doc:
        # Page 1
        p1 = doc.new_page()
        text1 = (
            f"Tax Invoice\n"
            f"Invoice No: {invoice_no}\n"
            f"Date: 2026-10-10\n"
            f"Supplier: {supplier}\n\n"
            f"Particulars\tQty\tUnit\tRate\tAmount\n"
            f"Cement\t10\tbags\t350.00\t3500.00\n"
            f"Total: 3500.00\n"
        )
        p1.insert_text((40, 60), text1)

        if pages > 1:
            for i in range(2, pages + 1):
                p = doc.new_page()
                if multi_inv:
                    text_p = (
                        f"Tax Invoice\n"
                        f"Invoice No: INV-2026-00{i}\n"
                        f"Date: 2026-10-11\n"
                        f"Supplier: Shree Ram Traders\n\n"
                        f"Particulars\tQty\tUnit\tRate\tAmount\n"
                        f"Bricks\t500\tpcs\t8.00\t4000.00\n"
                        f"Total: 4000.00\n"
                    )
                else:
                    text_p = f"Invoice continuation page {i}\nTerms and conditions\n"
                p.insert_text((40, 60), text_p)

        return doc.tobytes()


def synthetic_invoice_image(format='PNG'):
    """Generate image bill bytes."""
    out = io.BytesIO()
    Image.new('RGB', (100, 100), 'white').save(out, format=format)
    return out.getvalue()


class InvoiceExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.DurableTests.asyncSetUp(self)
        self.enqueue = patch.object(docs, 'enqueue', AsyncMock())
        self.enqueue.start()
        from app.services import invoice_extraction_jobs as extraction_jobs
        self.extraction_enqueue=patch.object(extraction_jobs,'enqueue',AsyncMock());self.extraction_enqueue.start()
        self.settings=patch.object(extractor,'get_settings',return_value=type('S',(),{'gemini_api_key':'','ai_api_key':''})());self.settings.start()
        self.batch = await docs.create_batch(self.db, self.principal, docs.BatchCreate(company_id=self.company.id))

    async def asyncTearDown(self):
        self.extraction_enqueue.stop()
        self.settings.stop()
        self.enqueue.stop()
        await self.db.rollback()
        rows = list((await self.db.scalars(select(BillDocument).where(BillDocument.organization_id == self.org))).all())
        for row in rows:
            await asyncio.to_thread(storage.remove, row.object_key)
        await fixtures.DurableTests.asyncTearDown(self)

    async def upload_and_ready(self, data, filename='invoice.pdf'):
        """Upload file and advance to ready state through worker validation."""
        result = await docs.upload_document(
            self.db, self.principal, self.batch['id'],
            UploadFile(io.BytesIO(data), filename=filename)
        )
        docid = result['document']['id']
        await jobs.validate_bill_document({}, docid)
        return docid

    # 1. Master Matching Supplier Tests
    def test_master_matching_suppliers(self):
        masters = ['UltraTech Cement Ltd', 'Shree Ram Traders', 'Ambuja Cements']

        # Exact match
        m1 = extractor.match_supplier('UltraTech Cement Ltd', masters)
        self.assertTrue(m1['matched'])
        self.assertEqual(m1['name'], 'UltraTech Cement Ltd')
        self.assertEqual(m1['method'], 'exact')
        self.assertIsNone(m1['warning'])

        # Case-insensitive
        m2 = extractor.match_supplier('ultratech cement ltd', masters)
        self.assertTrue(m2['matched'])
        self.assertEqual(m2['name'], 'UltraTech Cement Ltd')

        # Normalized match (stripping M/s or Pvt Ltd)
        m3 = extractor.match_supplier('M/s Shree Ram Traders Pvt Ltd', masters)
        self.assertFalse(m3['matched'])
        self.assertEqual(m3['suggested_match'], 'Shree Ram Traders')
        self.assertEqual(m3['method'], 'normalized')

        # Fuzzy match
        m4 = extractor.match_supplier('Ultratech Cements', masters)
        self.assertFalse(m4['matched'])
        self.assertEqual(m4['suggested_match'], 'UltraTech Cement Ltd')

        # Unmatched supplier
        m5 = extractor.match_supplier('Unknown Supplier XYZ', masters)
        self.assertFalse(m5['matched'])
        self.assertIn('not in synced Sundry Creditors', m5['warning'])

    # 2. Master Matching Item Tests
    def test_master_matching_items(self):
        masters = [
            {'name': 'Cement', 'unit': 'bags'},
            {'name': 'Steel Rod 12mm', 'unit': 'kg'},
            {'name': 'Red Bricks', 'unit': 'pcs'}
        ]

        # Exact match
        m1 = extractor.match_item('Cement', masters)
        self.assertTrue(m1['matched'])
        self.assertEqual(m1['name'], 'Cement')
        self.assertEqual(m1['unit'], 'bags')
        self.assertEqual(m1['method'], 'exact')

        # Containment match
        m2 = extractor.match_item('Steel Rod 12mm TMT', masters)
        self.assertFalse(m2['matched'])
        self.assertEqual(m2['suggested_match'], 'Steel Rod 12mm')
        self.assertIsNone(m2['unit'])

        # Unmatched item
        m3 = extractor.match_item('Alien Space Rock', masters)
        self.assertFalse(m3['matched'])
        self.assertIn('not found in synced Stock Items', m3['warning'])

    # 3. Mathematical Verification & Unclear Value Highlighting
    def test_mathematical_line_verification_and_unclear_values(self):
        masters = {
            'suppliers': ['UltraTech Cement Ltd'],
            'items': [{'name': 'Cement', 'unit': 'bags'}]
        }

        # Valid extraction: 10 * 350 = 3500
        raw_valid = {
            'invoice_number': 'INV-100',
            'invoice_date': '2026-10-10',
            'supplier_name': 'UltraTech Cement Ltd',
            'lines': [{'item_name': 'Cement', 'quantity': 10, 'unit': 'bags', 'rate': 350, 'amount': 3500, 'page_number': 1,'confidence':0.95}],
            'total_amount': 3500
        }
        res_valid = extractor.verify_and_match(raw_valid, masters)
        self.assertEqual(len(res_valid['warnings']), 0)
        self.assertFalse(res_valid['line_evidence'][0]['unclear'])
        self.assertTrue(res_valid['line_evidence'][0]['amount']['calculation_match'])

        # Mismatched line: 10 * 350 = 3800 (discrepancy)
        raw_mismatch = {
            'invoice_number': 'INV-101',
            'invoice_date': '2026-10-10',
            'supplier_name': 'UltraTech Cement Ltd',
            'lines': [{'item_name': 'Cement', 'quantity': 10, 'unit': 'bags', 'rate': 350, 'amount': 3800, 'page_number': 1,'confidence':0.95}],
            'total_amount': 3800
        }
        res_mismatch = extractor.verify_and_match(raw_mismatch, masters)
        self.assertTrue(res_mismatch['line_evidence'][0]['unclear'])
        self.assertFalse(res_mismatch['line_evidence'][0]['amount']['calculation_match'])
        self.assertTrue(any('Calculation mismatch' in w for w in res_mismatch['warnings']))

        # Missing rate: unclear line
        raw_missing_rate = {
            'invoice_number': 'INV-102',
            'invoice_date': '2026-10-10',
            'supplier_name': 'UltraTech Cement Ltd',
            'lines': [{'item_name': 'Cement', 'quantity': 10, 'unit': 'bags', 'rate': None, 'amount': None, 'page_number': 1,'confidence':0.95}],
            'total_amount': 0
        }
        res_missing = extractor.verify_and_match(raw_missing_rate, masters)
        self.assertTrue(res_missing['line_evidence'][0]['unclear'])
        self.assertTrue(any('Rate missing' in w for w in res_missing['warnings']))

        # Missing line items detection when stated total > lines sum
        raw_missing_lines = {
            'invoice_number': 'INV-103',
            'invoice_date': '2026-10-10',
            'supplier_name': 'UltraTech Cement Ltd',
            'lines': [{'item_name': 'Cement', 'quantity': 10, 'unit': 'bags', 'rate': 350, 'amount': 3500, 'page_number': 1,'confidence':0.95}],
            'total_amount': 7000  # Stated total is 7000, lines only sum to 3500
        }
        res_missing_lines = extractor.verify_and_match(raw_missing_lines, masters)
        self.assertTrue(any('Possible missing line items' in w for w in res_missing_lines['warnings']))

        # Zero extracted lines warning
        raw_zero_lines = {
            'invoice_number': 'INV-104',
            'invoice_date': '2026-10-10',
            'supplier_name': 'UltraTech Cement Ltd',
            'lines': [],
            'total_amount': 500
        }
        res_zero = extractor.verify_and_match(raw_zero_lines, masters)
        self.assertTrue(any('No line items extracted' in w for w in res_zero['warnings']))

    # 4. End-to-end PDF Extraction to Editable Draft
    async def test_extract_single_pdf_invoice_to_editable_draft(self):
        pdf_bytes = synthetic_invoice_pdf(pages=1, invoice_no='INV-2026-999', supplier='UltraTech Cement Ltd')
        docid = await self.upload_and_ready(pdf_bytes, filename='bill-single.pdf')

        # Mock company masters for testing
        with patch.object(extractor, 'company_masters', AsyncMock(return_value={
            'suppliers': ['UltraTech Cement Ltd'],
            'items': [{'name': 'Cement', 'unit': 'bags'}]
        })):
            result = await extractor.process_document_extraction(self.db, self.principal, docid)

        self.assertFalse(result['split'])
        draft = result['draft']
        self.assertEqual(draft['document_id'], docid)
        self.assertEqual(draft['document_filename'], 'bill-single.pdf')
        self.assertEqual(draft['status'], 'needs_review')
        self.assertTrue(draft['editable'])
        self.assertIsNone(draft['action_id'])  # STRICT SAFETY: no action

        # Verify extracted header & lines
        content = draft['content']
        self.assertEqual(content['party_name'], 'UltraTech Cement Ltd')
        self.assertEqual(content['invoice_number'], 'INV-2026-999')
        self.assertEqual(content['entry_date'], '2026-10-10')
        self.assertEqual(len(content['lines']), 1)
        self.assertEqual(content['lines'][0]['item_name'], 'Cement')
        self.assertEqual(Decimal(content['lines'][0]['quantity']), Decimal('10'))
        self.assertEqual(content['lines'][0]['unit'], 'bags')
        self.assertEqual(Decimal(content['lines'][0]['rate']), Decimal('350.00'))

        # Verify preservation of source page & evidence
        meta = draft['extraction_metadata']
        self.assertIsNotNone(meta)
        self.assertEqual(meta['status'], 'needs_review')
        self.assertEqual(meta['source_pages'], [1])
        self.assertEqual(meta['field_evidence']['party_name']['value'], 'UltraTech Cement Ltd')
        self.assertEqual(meta['field_evidence']['party_name']['page'], 1)
        self.assertEqual(meta['line_evidence'][0]['page_number'], 1)

    # 5. Extract Photo / Image Invoice
    async def test_extract_photo_image_invoice(self):
        img_bytes = synthetic_invoice_image('PNG')
        docid = await self.upload_and_ready(img_bytes, filename='photo_bill.png')

        with patch.object(extractor,'extract_invoice_data',AsyncMock(return_value={'supplier_name':'Supplier Photo Store','invoice_number':'TEST-1','invoice_date':'2026-10-10','lines':[{'item_name':'Photo Item','quantity':1,'rate':500,'unit':'pcs','page_number':1,'confidence':0.9}]})), patch.object(extractor, 'company_masters', AsyncMock(return_value={
            'suppliers': ['Supplier Photo Store'],
            'items': [{'name': 'Photo Item', 'unit': 'pcs'}]
        })):
            result = await extractor.process_document_extraction(self.db, self.principal, docid)

        draft = result['draft']
        self.assertEqual(draft['document_id'], docid)
        self.assertEqual(draft['document_filename'], 'photo_bill.png')
        self.assertEqual(draft['status'], 'needs_review')
        self.assertTrue(draft['editable'])
        self.assertIsNone(draft['action_id'])
        self.assertEqual(draft['content']['party_name'], 'Supplier Photo Store')

    # 6. Multi-Invoice Detection & Splitting Across Pages
    async def test_multi_invoice_detection_and_splitting(self):
        # 2-page PDF with 2 distinct invoices
        multi_pdf = synthetic_invoice_pdf(pages=2, multi_inv=True)
        docid = await self.upload_and_ready(multi_pdf, filename='multi-invoices.pdf')

        with patch.object(extractor, 'company_masters', AsyncMock(return_value={
            'suppliers': ['UltraTech Cement Ltd', 'Shree Ram Traders'],
            'items': [{'name': 'Cement', 'unit': 'bags'}, {'name': 'Bricks', 'unit': 'pcs'}]
        })):
            # Initial extraction without split creates draft flagged for review
            initial = await extractor.process_document_extraction(self.db, self.principal, docid, split=False)
            self.assertTrue(initial['metadata']['multiple_invoices_detected'])
            self.assertEqual(len(initial['metadata']['detected_invoices']), 2)
            self.assertIn('Multiple invoices detected', initial['metadata']['warnings'][0])

            # Explicit splitting creates 2 separate drafts
            split_result = await extractor.process_document_extraction(self.db, self.principal, docid, split=True)
            self.assertTrue(split_result['split'])
            self.assertEqual(len(split_result['drafts']), 2)

            # Both drafts are linked to the document and editable
            d1, d2 = split_result['drafts']
            self.assertEqual(d1['document_id'], docid)
            self.assertEqual(d2['document_id'], docid)
            self.assertEqual(d1['status'], 'needs_review')
            self.assertEqual(d2['status'], 'needs_review')
            self.assertIsNone(d1['action_id'])
            self.assertIsNone(d2['action_id'])

            # Verify line isolation: d1 has Cement only (page 1), d2 has Bricks only (page 2)
            self.assertEqual(d1['content']['party_name'], 'UltraTech Cement Ltd')
            self.assertEqual(len(d1['content']['lines']), 1)
            self.assertEqual(d1['content']['lines'][0]['item_name'], 'Cement')

            self.assertEqual(d2['content']['party_name'], 'Shree Ram Traders')
            self.assertEqual(len(d2['content']['lines']), 1)
            self.assertEqual(d2['content']['lines'][0]['item_name'], 'Bricks')

            # Listing drafts for document returns both
            listed = await extractor.list_document_drafts(self.db, self.principal, docid)
            self.assertGreaterEqual(len(listed['drafts']), 2)

    # 7. Strict Safety: AI output NEVER triggers direct posting or creates Tally actions
    async def test_strict_safety_no_tally_actions(self):
        pdf_bytes = synthetic_invoice_pdf(pages=1)
        docid = await self.upload_and_ready(pdf_bytes, filename='safety-check.pdf')

        with patch.object(extractor, 'company_masters', AsyncMock(return_value={
            'suppliers': ['UltraTech Cement Ltd'],
            'items': [{'name': 'Cement', 'unit': 'bags'}]
        })):
            result = await extractor.process_document_extraction(self.db, self.principal, docid)

        draft = result['draft']
        self.assertIsNone(draft['action_id'])
        self.assertEqual(draft['status'], 'needs_review')

        # Verify zero TallyActions were created
        actions = list((await self.db.scalars(
            select(TallyAction).where(TallyAction.organization_id == self.org)
        )).all())
        self.assertEqual(len(actions), 0)

    # 8. Editable Draft: edits update revision and preserve document linkage
    async def test_draft_editing_and_revision(self):
        pdf_bytes = synthetic_invoice_pdf(pages=1, invoice_no='INV-001')
        docid = await self.upload_and_ready(pdf_bytes, filename='editable-test.pdf')

        with patch.object(extractor, 'company_masters', AsyncMock(return_value={
            'suppliers': ['UltraTech Cement Ltd'],
            'items': [{'name': 'Cement', 'unit': 'bags'}]
        })):
            result = await extractor.process_document_extraction(self.db, self.principal, docid)

        draft_id = result['draft']['id']

        # Edit the draft (e.g. modify rate and quantity)
        new_content = copy.deepcopy(result['draft']['content'])
        new_content['lines'][0]['quantity'] = '12'
        new_content['lines'][0]['rate'] = '360.00'

        saved = await drafts.save_draft(
            self.db, self.principal, draft_id,
            drafts.DraftSave(revision=0, content=new_content)
        )

        self.assertEqual(saved['revision'], 1)
        self.assertEqual(saved['document_id'], docid)
        self.assertEqual(saved['content']['lines'][0]['quantity'], '12')
        self.assertEqual(saved['content']['lines'][0]['rate'], '360.00')

        # Read back freshly
        async with AsyncSessionLocal() as fresh:
            restored = await drafts.read_draft(fresh, self.principal, draft_id)
            self.assertEqual(restored['revision'], 1)
            self.assertEqual(restored['document_id'], docid)
            self.assertEqual(restored['document_filename'], 'editable-test.pdf')

    # 9. API Routes Verification
    async def test_api_routes_extract_drafts_split(self):
        pdf_bytes = synthetic_invoice_pdf(pages=1, invoice_no='API-INV-1')
        docid = await self.upload_and_ready(pdf_bytes, filename='api-bill.pdf')

        with patch.object(extractor, 'company_masters', AsyncMock(return_value={
            'suppliers': ['UltraTech Cement Ltd'],
            'items': [{'name': 'Cement', 'unit': 'bags'}]
        })):
            # POST /documents/{id}/extract
            res1 = await routes.extract_document(docid, self.principal, self.db)
            self.assertEqual(res1['document_id'], docid)
            self.assertEqual(res1['status'],'queued')
            await jobs.extract_bill_document({},docid)

            # GET /documents/{id}/drafts
            res2 = await routes.document_drafts(docid, self.principal, self.db)
            self.assertEqual(res2['document_id'], docid)
            self.assertEqual(len(res2['drafts']), 1)

            # POST /documents/{id}/split
            res3 = await routes.split_document(docid, self.principal, self.db)
            self.assertEqual(res3['document_id'], docid)
            await jobs.extract_bill_document({},docid)
            async with AsyncSessionLocal() as fresh:
                state=await docs.document_for(fresh,self.principal,docid)
                self.assertEqual(state.extraction_status,'error')

    def test_no_fake_photo_numbers_and_missing_units(self):
        with self.assertRaises(HTTPException) as error:
            extractor.extract_from_image_local(synthetic_invoice_image())
        self.assertEqual(error.exception.status_code,503)
        self.assertEqual(extractor._to_decimal('-350'),Decimal('-350'))
        self.assertEqual(extractor._to_decimal('(350)'),Decimal('-350'))
        for invalid in ['NaN','Infinity','3e5','350abc',True]:self.assertIsNone(extractor._to_decimal(invalid))
        raw={'supplier_name':'Supplier','invoice_date':'2026-10-10','confidence':None,'lines':[
            {'item_name':'Alien','quantity':-1,'rate':350,'confidence':0.1}]}
        v=extractor.verify_and_match(raw,{'suppliers':['Supplier'],'items':[]})
        self.assertIsNone(v['lines'][0]['quantity']);self.assertIsNone(v['lines'][0]['unit'])
        self.assertTrue(v['line_evidence'][0]['unclear'])
        self.assertEqual(v['line_evidence'][0]['quantity']['raw'],-1)
        m=extractor.match_supplier('Sharma',['Sharma Traders','Sharma Enterprises'])
        self.assertFalse(m['matched']);self.assertEqual(m['method'],'ambiguous')

    async def test_twenty_pages_and_jpeg_provider_payload(self):
        async def parse(data,mode='inspect',page=None):
            return json.dumps({'_page_count':20,'_source_text':'invoice','lines':[]}).encode() if mode=='extract' else b'\x89PNG'+bytes([page])
        settings=type('S',(),{'gemini_api_key':'fake','ai_api_key':'','ai_review_model':'gemini-2.5-flash','ai_timeout_seconds':20})()
        with patch.object(extractor,'get_settings',return_value=settings),patch.object(docs,'parse',side_effect=parse),patch.object(extractor,'call_gemini_multimodal_extraction',AsyncMock(return_value={'lines':[]})) as call:
            await extractor.extract_invoice_data(b'pdf','application/pdf')
            self.assertEqual(len(call.call_args.args[0]),20)
            self.assertEqual(call.call_args.args[0][-1],b'\x89PNG'+bytes([20]))
        from app.ai import provider
        def post(url,payload,headers,timeout_seconds):
            images=payload['contents'][0]['parts'][1:]
            self.assertEqual(len(images),20);self.assertEqual(images[0]['inline_data']['mime_type'],'image/jpeg')
            self.assertIn('response_schema',payload['generationConfig'])
            return {'candidates':[{'content':{'parts':[{'text':'{"lines":[]}'}]}}]}
        with patch.object(extractor,'get_settings',return_value=settings),patch.object(provider,'_post_json',side_effect=post):
            self.assertEqual(await extractor.call_gemini_multimodal_extraction([b'\xff\xd8\xff']*20),{'lines':[]})

    async def test_idempotent_extraction_and_split_preserve_edits(self):
        docid=await self.upload_and_ready(synthetic_invoice_pdf(pages=2,multi_inv=True))
        first=await extractor.process_document_extraction(self.db,self.principal,docid)
        repeat=await extractor.process_document_extraction(self.db,self.principal,docid)
        self.assertEqual(first['draft']['id'],repeat['draft']['id'])
        split=await extractor.process_document_extraction(self.db,self.principal,docid,split=True)
        again=await extractor.process_document_extraction(self.db,self.principal,docid,split=True)
        self.assertEqual([d['id'] for d in split['drafts']],[d['id'] for d in again['drafts']])
        self.assertEqual(split['drafts'][1]['extraction_metadata']['field_evidence']['party_name']['raw'],'Shree Ram Traders')
        with self.assertRaises(HTTPException):
            await drafts.preview_draft(self.db,self.principal,first['draft']['id'],drafts.DraftPreview(revision=0))

    async def test_queue_survives_reload_duplicate_requests_and_cancelled_worker(self):
        from app.services import invoice_extraction_jobs as queue
        docid=await self.upload_and_ready(synthetic_invoice_pdf())
        results=await asyncio.gather(*[self.request_fresh(docid) for _ in range(2)])
        self.assertTrue(all(r['status']=='queued' for r in results))
        with patch.object(extractor,'extract_invoice_data',AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):await jobs.extract_bill_document({},docid)
        async with AsyncSessionLocal() as fresh:
            row=await docs.document_for(fresh,self.principal,docid)
            self.assertEqual(row.extraction_status,'processing')
            row.extraction_lease_until=docs.now()-timedelta(seconds=1);await fresh.commit()
        redis=type('Redis',(),{'enqueue_job':AsyncMock()})()
        self.extraction_enqueue.stop()
        await queue.recover({'redis':redis})
        self.assertTrue(any(c.args[0]=='extract_bill_document' and c.args[1]==docid for c in redis.enqueue_job.call_args_list))
        self.extraction_enqueue.start()
        await jobs.extract_bill_document({},docid)
        async with AsyncSessionLocal() as fresh:
            row=await docs.document_for(fresh,self.principal,docid)
            self.assertEqual(row.extraction_status,'needs_review')
            listing=await extractor.list_document_drafts(fresh,self.principal,docid)
            self.assertEqual(len(listing['drafts']),1)
        repeated=await self.request_fresh(docid)
        self.assertEqual(repeated['drafts'][0]['id'],listing['drafts'][0]['id'])

    async def request_fresh(self,docid):
        from app.services.invoice_extraction_jobs import request_extraction
        async with AsyncSessionLocal() as fresh:return await request_extraction(fresh,self.principal,docid)

    async def test_photo_failure_is_visible_retryable_and_never_creates_action(self):
        docid=await self.upload_and_ready(synthetic_invoice_image(),filename='blank.png')
        await self.request_fresh(docid);await jobs.extract_bill_document({},docid)
        async with AsyncSessionLocal() as fresh:
            row=await docs.document_for(fresh,self.principal,docid)
            self.assertEqual(row.extraction_status,'error');self.assertIn('OCR unavailable',row.extraction_error)
            self.assertEqual((await extractor.list_document_drafts(fresh,self.principal,docid))['drafts'],[])
            self.assertEqual(list((await fresh.scalars(select(TallyAction).where(TallyAction.organization_id==self.org))).all()),[])
        retry=await self.request_fresh(docid);self.assertEqual(retry['status'],'queued')

    async def test_malformed_provider_results_fail_cleanly(self):
        for raw in [{'confidence':'wrong'},{'lines':[None]},{'lines':[{}]*101},{'detected_invoices':[None]}, {'lines':[{'page_number':22}]}]:
            with self.assertRaises(HTTPException) as error:extractor.verify_and_match(raw,{'suppliers':[],'items':[]})
            self.assertEqual(error.exception.status_code,422)

    async def test_actual_arq_worker_processes_cached_synthetic_extraction(self):
        from arq.connections import create_pool,RedisSettings
        from app.core.config import get_settings
        from app.services import invoice_extraction_jobs as queue
        docid=await self.upload_and_ready(synthetic_invoice_pdf())
        raw=extractor.extract_from_pdf_text_local(synthetic_invoice_pdf())
        async with AsyncSessionLocal() as fresh:
            row=await docs.document_for(fresh,self.principal,docid)
            row.extraction_result=raw;await fresh.commit()
        await self.request_fresh(docid)
        pool=await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        try:
            async with AsyncSessionLocal() as fresh:
                row=await docs.document_for(fresh,self.principal,docid)
                self.extraction_enqueue.stop();await queue.enqueue(row,pool);self.extraction_enqueue.start()
            for _ in range(40):
                await asyncio.sleep(0.25)
                async with AsyncSessionLocal() as fresh:
                    row=await docs.document_for(fresh,self.principal,docid)
                    if row.extraction_status not in ('queued','processing'):break
            self.assertEqual(row.extraction_status,'needs_review',row.extraction_error)
        finally:await pool.aclose()

    async def test_stale_worker_cannot_create_duplicate_or_overwrite_new_lease(self):
        docid=await self.upload_and_ready(synthetic_invoice_pdf())
        await self.request_fresh(docid)
        async def superseded(*args):
            async with AsyncSessionLocal() as fresh:
                row=await docs.document_for(fresh,self.principal,docid,lock=True)
                row.extraction_lease_token='new-worker';await fresh.commit()
            return {'supplier_name':'Supplier','lines':[]}
        with patch.object(extractor,'extract_invoice_data',side_effect=superseded):await jobs.extract_bill_document({},docid)
        async with AsyncSessionLocal() as fresh:
            row=await docs.document_for(fresh,self.principal,docid)
            self.assertEqual(row.extraction_lease_token,'new-worker')
            self.assertEqual((await extractor.list_document_drafts(fresh,self.principal,docid))['drafts'],[])


if __name__ == '__main__':
    unittest.main()
