"""Private source intake; PostgreSQL retains pending work even when Redis is down."""
import asyncio
import hashlib
import json
import secrets
import sys
from datetime import datetime,timezone
from fastapi import HTTPException
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import select,func,text
from app.models.bill_document import DocumentBatch,BillDocument,DocumentBatchItem
from app.services.purchase_draft_service import admin,company_for
from app.services import document_storage as storage

QUEUE='bill:intake'
ERRORS={'password_protected':'Password-protected PDF: unlocked copy upload karein.',
    'page_limit':'PDF mein 1–20 pages allowed hain. File split karke upload karein.',
    'corrupt_document':'File damaged ya unreadable hai. Clean PDF/photo upload karein.',
    'unsupported_type':'Sirf PDF, JPG aur PNG supported hain.',
    'image_limit':'Image bahut large ya multi-frame hai; smaller single photo upload karein.',
    'file_size':'File empty ya 10 MB se badi hai.',
    'storage_unavailable':'Private storage unavailable. Retry karein.',
    'validation_timeout':'File check complete nahi hua. Retry karein.',
    'checksum_mismatch':'Stored original mismatch; upload a clean copy.',
    'processing_error':'File check failed. Retry karein.'}


def now():return datetime.now(timezone.utc)


class BatchCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    company_id: str=Field(pattern=r'^[a-f0-9]{32}$')


async def batch_for(db,principal,batch_id,lock=False):
    admin(principal)
    query=select(DocumentBatch).where(DocumentBatch.id==batch_id,DocumentBatch.organization_id==principal.organization_id,DocumentBatch.user_id==principal.user_id)
    if lock:query=query.with_for_update().execution_options(populate_existing=True)
    batch=await db.scalar(query)
    if not batch:raise HTTPException(404,'Upload batch nahi mila.')
    await company_for(db,principal,batch.company_id)
    return batch


async def document_for(db,principal,document_id,lock=False):
    admin(principal)
    query=select(BillDocument).where(BillDocument.id==document_id,BillDocument.organization_id==principal.organization_id,BillDocument.user_id==principal.user_id).execution_options(populate_existing=True)
    if lock:query=query.with_for_update().execution_options(populate_existing=True)
    row=await db.scalar(query)
    if not row:raise HTTPException(404,'Document nahi mila.')
    await company_for(db,principal,row.company_id)
    return row


def view(row):
    return {'id':row.id,'filename':row.filename,'media_type':row.media_type,'size':row.size,'status':row.status,
        'extraction_status': row.extraction_status, 'extraction_error':row.extraction_error,
        'page_count':row.page_count,'error_code':row.error_code,'message':ERRORS.get(row.error_code) if row.error_code else
        {'queued':'Uploaded · file check pending','processing':'Checking file','ready':'File checked · original ready'}.get(row.status,row.status),
        'created_at':row.created_at.isoformat(),'retry_available':row.status=='error'}


async def create_batch(db,principal,request):
    await company_for(db,principal,request.company_id)
    row=DocumentBatch(id=secrets.token_hex(16),organization_id=principal.organization_id,user_id=principal.user_id,
        company_id=request.company_id,created_at=now())
    db.add(row);await db.commit()
    return {'id':row.id,'company_id':row.company_id,'created_at':row.created_at.isoformat(),'documents':[]}


async def read_batch(db,principal,batch_id):
    batch=await batch_for(db,principal,batch_id)
    rows=await db.scalars(select(BillDocument).join(DocumentBatchItem,DocumentBatchItem.document_id==BillDocument.id).where(
        DocumentBatchItem.batch_id==batch.id,BillDocument.organization_id==principal.organization_id,BillDocument.user_id==principal.user_id,
        BillDocument.company_id==batch.company_id).order_by(BillDocument.created_at,BillDocument.id).execution_options(populate_existing=True))
    return {'id':batch.id,'company_id':batch.company_id,'created_at':batch.created_at.isoformat(),'documents':[view(r) for r in rows]}


async def list_batches(db,principal):
    from app.models.tally import TallyReadCompany
    admin(principal)
    rows=await db.scalars(select(DocumentBatch).join(TallyReadCompany,DocumentBatch.company_id==TallyReadCompany.id).where(
        DocumentBatch.organization_id==principal.organization_id,DocumentBatch.user_id==principal.user_id,
        TallyReadCompany.organization_id==principal.organization_id,TallyReadCompany.enabled.is_(True))
        .order_by(DocumentBatch.created_at.desc()).limit(100))
    return {'batches':[{'id':r.id,'company_id':r.company_id,'created_at':r.created_at.isoformat()} for r in rows]}


async def enqueue(row,pool=None):
    from app.core.arq import get_arq_pool
    pool=pool or get_arq_pool()
    if pool is not None:
        try:await pool.enqueue_job('validate_bill_document',row.id,_queue_name=QUEUE,
            _job_id=f'bill-intake:{row.id}:{row.generation}:{row.attempts}')
        except Exception:pass  # Durable recovery scans the DB, not just Redis.


async def upload_document(db,principal,batch_id,file):
    # A single bounded file per request; multipart envelope has a separate cap.
    batch=await batch_for(db,principal,batch_id,lock=True)
    data=await file.read(storage.MAX_BYTES+1)
    if not data or len(data)>storage.MAX_BYTES:raise HTTPException(413,ERRORS['file_size'])
    if data.startswith(b'%PDF-'):media='application/pdf'
    elif data.startswith(b'\x89PNG\r\n\x1a\n'):media='image/png'
    elif data.startswith(b'\xff\xd8\xff'):media='image/jpeg'
    else:raise HTTPException(415,ERRORS['unsupported_type'])
    sha=hashlib.sha256(data).hexdigest()
    identity=':'.join((principal.organization_id,principal.user_id,batch.company_id,sha))
    lock_key=int(hashlib.sha256(identity.encode()).hexdigest()[:15],16)
    await db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':lock_key})
    row=await db.scalar(select(BillDocument).where(BillDocument.organization_id==principal.organization_id,
        BillDocument.user_id==principal.user_id,BillDocument.company_id==batch.company_id,BillDocument.sha256==sha))
    duplicate=row is not None
    linked=await db.get(DocumentBatchItem,(batch.id,row.id)) if row else None
    if not linked:
        count=await db.scalar(select(func.count()).select_from(DocumentBatchItem).where(DocumentBatchItem.batch_id==batch.id))
        if count>=50:raise HTTPException(409,'Batch full: maximum 50 files. New batch banayein.')
    if not row:
        filename=(file.filename or 'document').replace('\\','/').split('/')[-1]
        filename=''.join(c for c in filename if c.isprintable())[:160] or 'document'
        key=f'{principal.organization_id}/{principal.user_id}/{batch.company_id}/{sha}'
        try:await asyncio.to_thread(storage.put,key,data,media)
        except Exception:raise HTTPException(503,ERRORS['storage_unavailable']) from None
        stamp=now();row=BillDocument(id=secrets.token_hex(16),organization_id=principal.organization_id,user_id=principal.user_id,
            company_id=batch.company_id,filename=filename,media_type=media,size=len(data),sha256=sha,object_key=key,
            status='queued',attempts=0,generation=0,created_at=stamp,updated_at=stamp)
        db.add(row);await db.flush()
    if not linked:db.add(DocumentBatchItem(batch_id=batch.id,document_id=row.id))
    await db.commit()
    if row.status=='queued':await enqueue(row)
    return {'document':view(row),'duplicate':duplicate,'batch_id':batch.id}


async def original_bytes(row):
    try:data=await asyncio.to_thread(storage.read,row.object_key)
    except Exception:raise HTTPException(503,ERRORS['storage_unavailable']) from None
    if len(data)!=row.size or hashlib.sha256(data).hexdigest()!=row.sha256:
        raise HTTPException(409,ERRORS['checksum_mismatch'])
    return data


async def parse(data,mode='inspect',page=None):
    proc=await asyncio.create_subprocess_exec(sys.executable,'-m','app.services.document_validation',mode,
        *([str(page)] if page is not None else []),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:out,err=await asyncio.wait_for(proc.communicate(data),timeout=30)
    except (TimeoutError,asyncio.CancelledError):
        proc.kill();await proc.wait();raise
    if proc.returncode:raise ValueError(err.decode().strip() if err.decode().strip() in ERRORS else 'corrupt_document')
    return json.loads(out) if mode=='inspect' else out


async def retry_document(db,principal,document_id):
    row=await document_for(db,principal,document_id,lock=True)
    if row.status!='error':raise HTTPException(409,'Only failed processing can retry. Rejected file ke liye clean copy upload karein.')
    row.status='queued';row.attempts=0;row.generation+=1;row.error_code=None;row.next_attempt_at=None;row.updated_at=now()
    await db.commit();await enqueue(row);return view(row)
