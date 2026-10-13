"""Isolated ARQ queue; durable leases recover worker/Redis interruptions."""
import asyncio
import secrets
from datetime import timedelta
from sqlalchemy import select,or_,and_
from arq.cron import cron
from arq.connections import RedisSettings
from fastapi import HTTPException
from app.core.config import get_settings
from app.database.session import AsyncSessionLocal,async_engine
from app.models.bill_document import BillDocument
from app.services import bill_document_service as docs


async def validate_bill_document(ctx,document_id):
    async with AsyncSessionLocal() as db:
        row=await db.scalar(select(BillDocument).where(BillDocument.id==document_id).with_for_update())
        if not row or row.status not in ('queued','processing'):return
        if row.status=='processing' and row.lease_until and row.lease_until>docs.now():return
        if row.next_attempt_at and row.next_attempt_at>docs.now():return
        if row.attempts>=3:
            row.status='error';row.error_code='processing_error';row.lease_token=None;row.lease_until=None;await db.commit();return
        token=secrets.token_hex(16);row.lease_token=token;row.lease_until=docs.now()+timedelta(seconds=120)
        row.status='processing';row.attempts+=1;row.updated_at=docs.now();await db.commit()
        source=row
    result=None;error=None;permanent=False
    try:result=await docs.parse(await docs.original_bytes(source))
    except ValueError as exc:error=str(exc) if str(exc) in docs.ERRORS else 'corrupt_document';permanent=True
    except HTTPException as exc:
        error='checksum_mismatch' if exc.status_code==409 else 'storage_unavailable';permanent=exc.status_code==409
    except TimeoutError:error='validation_timeout'
    except asyncio.CancelledError:raise  # Lease remains recoverable after worker shutdown.
    except Exception:error='storage_unavailable'
    async with AsyncSessionLocal() as db:
        row=await db.scalar(select(BillDocument).where(BillDocument.id==document_id).with_for_update())
        if not row or row.lease_token!=token:return
        row.lease_token=None;row.lease_until=None;row.updated_at=docs.now()
        if result:
            row.status='ready';row.error_code=None;row.page_count=result['page_count'];row.media_type=result['media_type'];row.next_attempt_at=None
        else:
            row.error_code=error
            row.status='rejected' if permanent else 'error' if row.attempts>=3 else 'queued'
            row.next_attempt_at=docs.now()+timedelta(seconds=30*row.attempts) if row.status=='queued' else None
        await db.commit()


async def recover_bill_documents(ctx):
    async with AsyncSessionLocal() as db:
        rows=await db.scalars(select(BillDocument).where(or_(
            and_(BillDocument.status=='queued',or_(BillDocument.next_attempt_at.is_(None),BillDocument.next_attempt_at<=docs.now())),
            and_(BillDocument.status=='processing',BillDocument.lease_until<=docs.now())))
            .order_by(BillDocument.created_at).limit(100))
        for row in rows:await docs.enqueue(row,ctx['redis'])
    from app.services.invoice_extraction_jobs import recover
    await recover(ctx)


async def startup(ctx):await recover_bill_documents(ctx)
async def shutdown(ctx):await async_engine.dispose()


from app.services.invoice_extraction_jobs import extract_bill_document


class DocumentWorkerSettings:
    functions=[validate_bill_document, extract_bill_document]
    cron_jobs=[cron(recover_bill_documents,second=0)]
    queue_name=docs.QUEUE
    redis_settings=RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs=2
    max_tries=1
    keep_result=0
    job_timeout=300
    on_startup=startup
    on_shutdown=shutdown
