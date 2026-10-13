"""PostgreSQL owns extraction state; Redis only wakes the worker."""
import asyncio
import logging
import secrets
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

async def request_extraction(db,principal,document_id,split=False):
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
    await db.commit();await enqueue(row)
    return {'document_id':row.id,'status':'queued','drafts':[]}

async def recover(ctx):
    async with AsyncSessionLocal() as db:
        rows=await db.scalars(select(BillDocument).where(or_(
            and_(BillDocument.extraction_status=='queued',or_(BillDocument.extraction_next_attempt_at.is_(None),BillDocument.extraction_next_attempt_at<=docs.now())),
            and_(BillDocument.extraction_status=='processing',BillDocument.extraction_lease_until<=docs.now()))).limit(100))
        for row in rows:await enqueue(row,ctx['redis'])

async def extract_bill_document(ctx,document_id):
    async with AsyncSessionLocal() as db:
        row=await db.scalar(select(BillDocument).where(BillDocument.id==document_id).with_for_update())
        if not row or row.status!='ready' or row.extraction_status not in ('queued','processing'):return
        if row.extraction_lease_until and row.extraction_lease_until>docs.now():return
        if row.extraction_next_attempt_at and row.extraction_next_attempt_at>docs.now():return
        if row.extraction_attempts>=3:
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
    try:
        raw=source.extraction_result
        if raw is None:raw=await asyncio.wait_for(extractor.extract_invoice_data(await docs.original_bytes(source),source.media_type),timeout=270)
        async with AsyncSessionLocal() as db:
            await extractor.process_document_extraction(db,principal,document_id,split=split,raw_result=raw,lease_token=token)
    except asyncio.CancelledError:raise
    except Exception as exc:
        # Persist a safe error; never include provider URLs, keys or raw invoice data in logs.
        message=str(exc.detail)[:500] if isinstance(exc,HTTPException) else 'Extraction failed. Retry or review the original manually.'
        permanent=isinstance(exc,HTTPException) and exc.status_code in (403,404,409,422,503)
        async with AsyncSessionLocal() as db:
            row=await db.scalar(select(BillDocument).where(BillDocument.id==document_id).with_for_update())
            if not row or row.extraction_lease_token!=token:return
            row.extraction_lease_token=None;row.extraction_lease_until=None;row.extraction_error=message
            row.extraction_status='error' if permanent or row.extraction_attempts>=3 else 'queued'
            row.extraction_next_attempt_at=docs.now()+timedelta(seconds=30*row.extraction_attempts) if row.extraction_status=='queued' else None
            await db.commit()
