"""PostgreSQL owns extraction state; Redis only wakes the worker."""
import asyncio
import logging
import secrets
import time
import os
from datetime import timedelta
from types import SimpleNamespace
from sqlalchemy import select,or_,and_
from fastapi import HTTPException
from app.database.session import AsyncSessionLocal
from app.models.bill_document import BillDocument
from app.models.organization_membership import OrganizationMembership
from app.services import bill_document_service as docs, invoice_extraction as extractor
log=logging.getLogger(__name__)

async def enqueue(row,pool=None):
    from app.core.arq import get_arq_pool
    pool=pool or get_arq_pool()
    if pool:
        try:await pool.enqueue_job('extract_bill_document',row.id,_queue_name=docs.QUEUE,
            _job_id=f'bill-extract:{row.id}:{row.extraction_generation}:{row.extraction_attempts}')
        except Exception:log.warning('Extraction enqueue unavailable; durable recovery will retry.')

async def request_extraction(db,principal,document_id,split=False,pool=None):
    row=await docs.document_for(db,principal,document_id,lock=True)
    if row.status!='ready':raise HTTPException(409,'File check must finish before extraction.')
    existing=(await extractor.list_document_drafts(db,principal,document_id))['drafts']
    reusable=[d for d in existing if bool((d.get('extraction_metadata') or {}).get('is_split_draft'))==split]
    if reusable:
        await db.commit()
        return {'document_id':row.id,'status':'needs_review','drafts':reusable}
    if row.extraction_status in ('queued','processing'):
        if row.extraction_split!=split:raise HTTPException(409,'Another extraction is processing; wait for it to finish.')
        await db.commit();return {'document_id':row.id,'status':row.extraction_status,'drafts':[]}
    row.extraction_status='queued';row.extraction_split=split;row.extraction_error=None
    row.extraction_attempts=0;row.extraction_generation+=1;row.extraction_next_attempt_at=None
    row.extraction_lease_token=None;row.extraction_lease_until=None
    await db.commit();await enqueue(row,pool)
    return {'document_id':row.id,'status':'queued','drafts':[]}

async def recover(ctx):
    async with AsyncSessionLocal() as db:
        rows=await db.scalars(select(BillDocument).where(or_(
            and_(BillDocument.extraction_status=='queued',or_(BillDocument.extraction_next_attempt_at.is_(None),BillDocument.extraction_next_attempt_at<=docs.now())),
            and_(BillDocument.extraction_status=='processing',BillDocument.extraction_lease_until<=docs.now())),BillDocument.trashed_at.is_(None)).limit(100))
        for row in rows:await enqueue(row,ctx['redis'])

async def extract_bill_document(ctx,document_id):
    from app.services.invoice_ai_budget import extraction_slot
    async with extraction_slot() as locked:
        if not locked:return  # Durable queue recovery wakes it later; no attempt spent.
        try:
            await _extract_bill_document(ctx,document_id)
        finally:
            from app.services.chat_attachments import wake
            await wake(ctx,document_id)

async def _extract_bill_document(ctx,document_id):
    async with AsyncSessionLocal() as db:
        row=await db.scalar(select(BillDocument).where(BillDocument.id==document_id).with_for_update())
        if not row or row.trashed_at or row.status!='ready' or row.extraction_status not in ('queued','processing'):return
        if row.extraction_lease_until and row.extraction_lease_until>docs.now():return
        if row.extraction_next_attempt_at and row.extraction_next_attempt_at>docs.now():return
        if row.extraction_attempts>=2:
            row.extraction_status='error';row.extraction_error='Extraction interrupted repeatedly. Retry extraction.';await db.commit();return
        member=await db.get(OrganizationMembership,(row.user_id,row.organization_id))
        if not member or member.status!='active' or member.role not in ('owner','admin'):
            row.extraction_status='error';row.extraction_error='Workspace permission unavailable.';await db.commit();return
        principal=SimpleNamespace(organization_id=row.organization_id,user_id=row.user_id,role=member.role)
        try:await docs.document_for(db,principal,document_id)
        except HTTPException:
            row.extraction_status='error';row.extraction_error='Company unavailable in this workspace.';await db.commit();return
        token=secrets.token_hex(16);row.extraction_lease_token=token;row.extraction_lease_until=docs.now()+timedelta(seconds=360)
        row.extraction_status='processing';row.extraction_attempts+=1
        source=row;split=row.extraction_split;await db.commit()
    started=time.perf_counter();raw=None
    from app.services.bill_evaluation_service import record
    from app.core.config import get_settings
    settings=get_settings()
    local_only=source.extraction_result is not None or (source.media_type in ('image/png','image/jpeg') and os.getenv('PHILIXA_LOCAL_OCR_ENABLED','0')=='1') or not (settings.gemini_api_key or settings.ai_api_key)
    if os.getenv('PHILIXA_LAYOUT_REVIEW_ENABLED','0')=='1' or os.getenv('PHILIXA_OCR_SEMANTIC_REVIEW_ENABLED','0')=='1':local_only=False
    measurement={'attempt':source.extraction_attempts,'generation':source.extraction_generation,'provider_cost_usd':'0' if local_only else None,
        'cost_basis':'no external provider call; local compute cost excluded' if local_only else 'provider billing/price unavailable; not treated as zero'}
    try:
        raw=source.extraction_result
        if raw is None:
            from app.services.invoice_ai_budget import paid_scope
            with paid_scope(source):
                raw=await asyncio.wait_for(extractor.extract_invoice_data(await docs.original_bytes(source),source.media_type),timeout=240 if os.getenv('PHILIXA_LAYOUT_REVIEW_ENABLED','0')=='1' else 270)
        if raw.get('layout_evidence'):
            import hashlib,json
            from app.services import document_storage
            artifact=json.dumps(raw.pop('layout_evidence'),ensure_ascii=False,separators=(',',':')).encode()
            key=f'{source.organization_id}/{source.user_id}/{source.company_id}/{source.id}/layout/{source.extraction_generation}-{hashlib.sha256(artifact).hexdigest()}.json'
            await asyncio.to_thread(document_storage.put,key,artifact,'application/json')
            raw['layout_artifact']={'key':key,'source_sha256':source.sha256,'reader_version':raw.get('reader_version'),'generation':source.extraction_generation}
        telemetry=raw.get('semantic_telemetry') or {}
        if telemetry.get('model_calls'):
            measurement.update(provider_cost_usd=None,cost_basis='Groq invoked; actual monetary billing unavailable',model_calls=telemetry['model_calls'],usage=telemetry.get('usage',{}))
        async with AsyncSessionLocal() as db:
            await extractor.process_document_extraction(db,principal,document_id,split=split,raw_result=raw,lease_token=token)
            record(db,principal,'extraction_attempt',{**measurement,'latency_ms':round((time.perf_counter()-started)*1000),'success':True,'method':raw.get('extraction_method','cached_or_structured')},document_id=document_id)
            await db.commit()
    except asyncio.CancelledError:raise
    except Exception as exc:
        # Persist a safe error; never include provider URLs, keys or raw invoice data in logs.
        message=str(exc.detail)[:500] if isinstance(exc,HTTPException) else 'Extraction failed. Retry or review the original manually.'
        from app.services.invoice_ai_budget import BudgetPaused,TransientExtraction,pause_waiting
        paused=isinstance(exc,BudgetPaused)
        transient=isinstance(exc,(TransientExtraction,TimeoutError))
        from app.ai.groq_gateway import QuotaDeferred
        quota=isinstance(exc,QuotaDeferred)
        if quota:
            message='AI capacity busy; original saved. Retry extraction later.'
            transient=exc.reason in ('minute_quota','provider_unavailable') and exc.retry_at and exc.retry_at<=docs.now()+timedelta(seconds=120)
        async with AsyncSessionLocal() as db:
            row=await db.scalar(select(BillDocument).where(BillDocument.id==document_id).with_for_update())
            if not row or row.extraction_lease_token!=token:return
            row.extraction_lease_token=None;row.extraction_lease_until=None;row.extraction_error=message
            row.extraction_status='paused_budget' if paused else 'queued' if transient and row.extraction_attempts<2 else 'error'
            row.extraction_next_attempt_at=docs.now()+timedelta(seconds=30*row.extraction_attempts) if row.extraction_status=='queued' else None
            if quota and row.extraction_status=='queued':row.extraction_next_attempt_at=exc.retry_at
            if paused and exc.pause_all:await pause_waiting(db,message)
            record(db,principal,'extraction_attempt',{**measurement,'latency_ms':round((time.perf_counter()-started)*1000),'success':False,'method':raw.get('extraction_method') if isinstance(raw,dict) else None},document_id=document_id)
            await db.commit()
