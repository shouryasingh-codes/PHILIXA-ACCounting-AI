"""Real PostgreSQL budget/worker gates; all provider HTTP calls mocked."""
import asyncio
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch,AsyncMock
from sqlalchemy import select,delete,func
from scripts import test_invoice_extraction as fixture
from app.database.session import AsyncSessionLocal
from app.models.bill_document import BillDocument
from app.models.invoice_ai_budget import InvoiceAIBudgetDebit as Debit
from app.services import invoice_ai_budget as budget,invoice_extraction_jobs as jobs
from app.services.invoice_extraction import _post_invoice_json
from app.jobs.document_jobs import DocumentWorkerSettings

class Limits(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await fixture.InvoiceExtractionTests.asyncSetUp(self)
  self.env=patch.dict('os.environ',{'PHILIXA_INVOICE_AI_DAILY_CAP_USD':'0.02','PHILIXA_INVOICE_AI_MAX_REQUEST_USD':'0.01'})
  self.env.start()
  self.day=patch.object(budget,'budget_day',return_value=date(2000,1,1));self.day.start()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as db:
   await db.execute(delete(Debit).where(Debit.organization_id==self.org));await db.commit()
  self.day.stop();self.env.stop()
  await fixture.InvoiceExtractionTests.asyncTearDown(self)
 upload_and_ready=fixture.InvoiceExtractionTests.upload_and_ready
 request_fresh=fixture.InvoiceExtractionTests.request_fresh
 async def queued(self,label):
  doc=await self.upload_and_ready(fixture.synthetic_invoice_pdf(invoice_no=label))
  await self.request_fresh(doc)
  return doc
 async def row(self,doc):
  async with AsyncSessionLocal() as db:return await db.get(BillDocument,doc)
 async def debit_total(self):
  async with AsyncSessionLocal() as db:
   return await db.scalar(select(func.coalesce(func.sum(Debit.reserved_usd),0)).where(Debit.organization_id==self.org))
 async def paid_extract(self,*args):
  await _post_invoice_json('https://example.invalid',{}, {})
  raise ValueError('Stop before creating a draft in this gate test')
 async def test_one_transient_retry_only_and_no_refund(self):
  doc=await self.queued('RETRY')
  response=type('R',(),{'status_code':503})()
  with patch.object(jobs.extractor,'extract_invoice_data',side_effect=self.paid_extract),patch('httpx.AsyncClient.post',AsyncMock(return_value=response)) as post:
   await jobs.extract_bill_document({},doc)
   self.assertEqual((await self.row(doc)).extraction_status,'queued')
   async with AsyncSessionLocal() as db:
    row=await db.get(BillDocument,doc);row.extraction_next_attempt_at=None;await db.commit()
   await jobs.extract_bill_document({},doc);await jobs.extract_bill_document({},doc)
   row=await self.row(doc)
   self.assertEqual((row.extraction_status,row.extraction_attempts),('error',2))
   self.assertEqual(post.await_count,2)
  self.assertEqual(await self.debit_total(),Decimal('0.02'))
 async def test_permanent_failure_has_no_retry(self):
  doc=await self.queued('AUTH')
  response=type('R',(),{'status_code':401})()
  with patch.object(jobs.extractor,'extract_invoice_data',side_effect=self.paid_extract),patch('httpx.AsyncClient.post',AsyncMock(return_value=response)) as post:
   await jobs.extract_bill_document({},doc);await jobs.extract_bill_document({},doc)
   self.assertEqual(post.await_count,1)
   self.assertEqual((await self.row(doc)).extraction_status,'error')
 async def test_cap_pauses_remaining_and_recovery_never_resumes(self):
  first=await self.queued('CAP1');second=await self.queued('CAP2');third=await self.queued('CAP3')
  response=type('R',(),{'status_code':401})()
  with patch.dict('os.environ',{'PHILIXA_INVOICE_AI_DAILY_CAP_USD':'0.01'}),patch.object(jobs.extractor,'extract_invoice_data',side_effect=self.paid_extract),patch('httpx.AsyncClient.post',AsyncMock(return_value=response)) as post:
   await jobs.extract_bill_document({},first)
   self.assertEqual((await self.row(third)).extraction_status,'paused_budget')
   await jobs.extract_bill_document({},second)
   self.assertEqual((await self.row(second)).extraction_status,'paused_budget')
   self.assertEqual((await self.row(third)).extraction_status,'paused_budget')
   await jobs.extract_bill_document({},third)
   redis=type('Redis',(),{'enqueue_job':AsyncMock()})()
   jobs.enqueue.reset_mock()
   await jobs.recover({'redis':redis})
   ids=[c.args[0].id for c in jobs.enqueue.await_args_list]
   self.assertNotIn(third,ids)
   await self.request_fresh(second);await jobs.extract_bill_document({},second)
   self.assertEqual(post.await_count,1)
  self.assertEqual(await self.debit_total(),Decimal('0.01'))
 async def test_concurrent_budget_admission_and_duplicate_attempt(self):
  ids=[await self.queued('RACE1'),await self.queued('RACE2')]
  rows=[]
  async with AsyncSessionLocal() as db:
   for doc in ids:
    row=await db.get(BillDocument,doc);row.extraction_status='processing';row.extraction_attempts=1;rows.append(row)
   await db.commit()
  async def reserve(row):
   with budget.paid_scope(row):await budget.reserve_paid_call()
  with patch.dict('os.environ',{'PHILIXA_INVOICE_AI_DAILY_CAP_USD':'0.01'}):
   results=await asyncio.gather(*(reserve(r) for r in rows),return_exceptions=True)
   self.assertEqual(sum(r is None for r in results),1)
   self.assertEqual(sum(isinstance(r,budget.BudgetPaused) for r in results),1)
   winner=rows[results.index(None)]
   with self.assertRaises(budget.BudgetPaused):await reserve(winner)
  self.assertEqual(await self.debit_total(),Decimal('0.01'))
 async def test_unset_cap_stops_before_http(self):
  doc=await self.queued('UNSET')
  with patch.dict('os.environ',{'PHILIXA_INVOICE_AI_DAILY_CAP_USD':'0'}),patch.object(jobs.extractor,'extract_invoice_data',side_effect=self.paid_extract),patch('httpx.AsyncClient.post',AsyncMock()) as post:
   await jobs.extract_bill_document({},doc)
   post.assert_not_awaited()
   self.assertEqual((await self.row(doc)).extraction_status,'paused_budget')
 async def test_global_single_slot(self):
  self.assertEqual(DocumentWorkerSettings.max_jobs,1)
  async with budget.extraction_slot() as first:
   self.assertTrue(first)
   async with budget.extraction_slot() as second:self.assertFalse(second)
  async with budget.extraction_slot() as released:self.assertTrue(released)
