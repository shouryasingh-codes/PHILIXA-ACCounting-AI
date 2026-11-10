import copy,secrets,unittest
from types import SimpleNamespace
from fastapi import HTTPException
from app.services import bill_evaluation_service as evaluation,purchase_draft_service as drafts
from app.models.purchase_draft import PurchaseDraft
from app.services.tally_sync import now
import scripts.test_tally_sync as fixtures

CONTENT=dict(party_name='Supplier',invoice_number='D9-METRICS',entry_date='2026-10-02',lines=[dict(item_name='Cement',quantity='2',rate='100',unit='bags')])
class Metrics(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.DurableTests.asyncSetUp(self)
        self.cid=self.company.id
        self.row=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.cid,content=CONTENT))
    asyncTearDown=fixtures.DurableTests.asyncTearDown
    async def test_corrections_numeric_equivalence_and_missing_time(self):
        result=await evaluation.metrics(self.db,self.principal,self.row['id']);self.assertIsNone(result['active_review_ms']);self.assertIsNone(result['provider_cost_usd']);self.assertIsNone(result['savings_percent'])
        content=copy.deepcopy(CONTENT);content['lines'][0]['quantity']='3'
        row=await drafts.save_draft(self.db,self.principal,self.row['id'],drafts.DraftSave(revision=0,content=content))
        self.assertEqual((await evaluation.metrics(self.db,self.principal,row['id']))['correction_count'],1)
        content['lines'][0]['rate']='100.00'
        await drafts.save_draft(self.db,self.principal,row['id'],drafts.DraftSave(revision=row['revision'],content=content))
        self.assertEqual((await evaluation.metrics(self.db,self.principal,row['id']))['correction_count'],1)
    async def test_review_time_idempotent_scoped_and_bounded(self):
        sample=evaluation.ReviewSample(event_id=secrets.token_hex(16),revision=0,active_ms=4200)
        await evaluation.record_review(self.db,self.principal,self.row['id'],sample)
        self.assertTrue((await evaluation.record_review(self.db,self.principal,self.row['id'],sample))['duplicate'])
        self.assertEqual((await evaluation.metrics(self.db,self.principal,self.row['id']))['active_review_ms'],4200)
        other=SimpleNamespace(**{**vars(self.principal),'organization_id':'other'})
        with self.assertRaises(HTTPException):await evaluation.metrics(self.db,other,self.row['id'])
        with self.assertRaises(ValueError):evaluation.ReviewSample(event_id='f'*32,revision=0,active_ms=60001)
        with self.assertRaises(HTTPException):await evaluation.record_review(self.db,self.principal,self.row['id'],evaluation.ReviewSample(event_id='a'*32,revision=99,active_ms=1))
    async def test_unknown_provider_cost_not_silently_zero(self):
        evaluation.record(self.db,self.principal,'extraction_attempt',dict(latency_ms=120,provider_cost_usd=None,success=False),draft_id=self.row['id'])
        await self.db.commit()
        result=await evaluation.metrics(self.db,self.principal,self.row['id']);self.assertIsNone(result['provider_cost_usd']);self.assertEqual(result['processing_latency_ms'],120)
    async def test_cached_extraction_attempt_records_latency_and_local_cost(self):
        from app.models.bill_document import BillDocument
        from app.models.bill_evaluation import BillEvaluationMetric
        from app.services.invoice_extraction_jobs import extract_bill_document
        from sqlalchemy import select
        raw=dict(supplier_name='Supplier',buyer_name='Pilot Test',invoice_number='D9-CACHED',invoice_date='2026-10-02',lines=[dict(item_name='Cement',quantity='2',unit='bags',rate='100')],total_amount=200,confidence={})
        doc=BillDocument(id=secrets.token_hex(16),organization_id=self.org,user_id=self.user,company_id=self.cid,filename='dummy.pdf',media_type='application/pdf',size=1,sha256=secrets.token_hex(32),object_key='synthetic',status='ready',page_count=1,attempts=0,generation=0,created_at=now(),updated_at=now(),extraction_status='queued',extraction_generation=1,extraction_result=raw)
        self.db.add(doc);await self.db.commit()
        await extract_bill_document({},doc.id)
        event=await self.db.scalar(select(BillEvaluationMetric).where(BillEvaluationMetric.document_id==doc.id,BillEvaluationMetric.kind=='extraction_attempt'))
        self.assertTrue(event.data['success']);self.assertEqual(event.data['provider_cost_usd'],'0');self.assertGreaterEqual(event.data['latency_ms'],0)

class Scoring(unittest.TestCase):
    def test_missing_fields_and_extra_lines_cannot_improve_accuracy(self):
        from scripts.evaluate_day9 import score
        expected={'invoice_number':'A','lines':[{'quantity':'2','rate':'100'}]}
        missing=score(expected,{'invoice_number':'A','lines':[]});self.assertEqual(missing['total'],3);self.assertEqual(missing['correction_count'],2)
        extra=score(expected,{'invoice_number':'A','lines':[{'quantity':'2','rate':'100'},{'quantity':'1','rate':'200'}]});self.assertFalse(extra['exact_bill'])
    def test_independent_truth_tax_values_and_identity(self):
        import json
        from pathlib import Path
        from decimal import Decimal
        import scripts.test_gst_purchase as masters
        bills=json.loads(Path('scripts/fixtures/day9/golden.json').read_text())['bills']
        from app.services.tally_connector import value
        for b in bills:
            self.assertEqual(b['supplier_gstin'],value(masters.catalog(b['inter'])['ledgers'][0],'PARTYGSTIN'))
            self.assertEqual(Decimal(b['taxable_total'])+sum(map(Decimal,b['expected_taxes'].values()))+Decimal(b['round_off']),Decimal(b['invoice_total']))

if __name__=='__main__':unittest.main()
