"""Global invoice-AI reservation cap, fail closed before every paid HTTP request."""
import os,secrets
from contextvars import ContextVar
from contextlib import contextmanager,asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal,InvalidOperation
from fastapi import HTTPException
from sqlalchemy import select,func,text,update
from app.models.invoice_ai_budget import InvoiceAIBudgetDebit as Debit
from app.models.bill_document import BillDocument

scope=ContextVar('invoice_paid_scope',default=None)

def budget_day():
    return datetime.now(ZoneInfo('Asia/Kolkata')).date()

class BudgetPaused(HTTPException):
    def __init__(self,detail=None):
        self.pause_all=detail is None
        super().__init__(503,detail or 'Daily invoice AI budget unavailable/exhausted. Paid extraction paused; configure budget or resume later.')

class TransientExtraction(HTTPException):
    def __init__(self,detail):super().__init__(503,detail)

def limits():
    try:
        values=[Decimal(os.getenv(key,'0')) for key in ('PHILIXA_INVOICE_AI_DAILY_CAP_USD','PHILIXA_INVOICE_AI_MAX_REQUEST_USD')]
        if any(not v.is_finite() or v<=0 or v>Decimal('1000000000') or v.as_tuple().exponent < -8 for v in values):raise ValueError()
        return values
    except (InvalidOperation,ValueError):raise BudgetPaused() from None

@contextmanager
def paid_scope(row):
    token=scope.set((row.organization_id,row.id,row.extraction_generation,row.extraction_attempts))
    try:yield
    finally:scope.reset(token)

async def reserve_paid_call():
    from app.database.session import AsyncSessionLocal
    identity=scope.get()
    if not identity:raise BudgetPaused('Paid invoice extraction needs a durable document job and configured budget.')
    cap,amount=limits()
    org,document,generation,attempt=identity
    if attempt not in (1,2):raise BudgetPaused('Extraction automatic attempt limit reached; review required.')
    async with AsyncSessionLocal() as db:
        await db.execute(text('SELECT pg_advisory_xact_lock(73924,1)'))
        row=await db.get(BillDocument,document,populate_existing=True)
        if not row or row.organization_id!=org or row.extraction_generation!=generation or row.extraction_attempts!=attempt or row.extraction_status!='processing':
            raise BudgetPaused('Extraction job scope changed; paid call stopped.')
        existing=await db.scalar(select(Debit.id).where(Debit.document_id==document,Debit.generation==generation,Debit.attempt==attempt))
        if existing:raise BudgetPaused('This extraction attempt already reserved a paid call. Review before resuming.')
        today=budget_day()
        used=await db.scalar(select(func.coalesce(func.sum(Debit.reserved_usd),0)).where(Debit.day==today))
        if used+amount>cap:raise BudgetPaused()
        db.add(Debit(id=secrets.token_hex(16),organization_id=org,document_id=document,generation=generation,attempt=attempt,day=today,reserved_usd=amount,created_at=datetime.now(ZoneInfo('UTC'))))
        if used+amount>=cap:
            await pause_waiting(db,BudgetPaused().detail)
        await db.commit()

async def pause_waiting(db,message):
    # The cap is global to this deployment/provider account. Free cached/local
    # work does not consume it; already-started calls keep their reserved debit.
    condition=[BillDocument.status=='ready',BillDocument.extraction_status=='queued',BillDocument.extraction_result.is_(None)]
    if os.getenv('PHILIXA_LOCAL_OCR_ENABLED','0')=='1':condition.append(BillDocument.media_type=='application/pdf')
    await db.execute(update(BillDocument).where(*condition).values(extraction_status='paused_budget',extraction_error=message,extraction_next_attempt_at=None))

@asynccontextmanager
async def extraction_slot():
    from app.database.session import async_engine
    async with async_engine.connect() as conn:
        locked=await conn.scalar(text('SELECT pg_try_advisory_xact_lock(73924,2)'))
        yield bool(locked)
