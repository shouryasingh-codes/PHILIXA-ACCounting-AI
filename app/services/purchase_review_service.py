"""Day 6 review queue. Each approval uses the existing durable dispatch guard."""
from datetime import datetime, timezone
from types import SimpleNamespace
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, exists
from app.models.bill_document import BillDocument
from app.models.purchase_draft import PurchaseDraft
from app.models.tally import TallyAction, TallyReadCompany
from app.services import purchase_draft_service as drafts

VIEWS = ('processing', 'needs_attention', 'ready', 'posting', 'verified')

class ApprovalItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    draft_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    revision: int = Field(ge=0)
    action_id: str = Field(pattern=r'^[a-f0-9]{32}$')

class BulkApproval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[ApprovalItem] = Field(min_length=1, max_length=50)

    @model_validator(mode='after')
    def distinct(self):
        if len({i.draft_id for i in self.items}) != len(self.items):
            raise ValueError('Select each bill only once.')
        return self

def ready_reason(action, principal):
    if not action or action.status != 'preview': return 'Create a fresh validated preview.'
    if (action.organization_id,action.user_id,action.session_id) != (principal.organization_id,principal.user_id,principal.session_id): return 'Review a fresh preview in this session.'
    expiry=action.expires_at
    if expiry.tzinfo is None: expiry=expiry.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc): return 'Preview expired; validate again.'
    if action.payload.get('operation') not in (None,'purchase_multi','purchase_gst') or (action.payload.get('operation') is None and not all(action.payload.get(k) for k in ('item','party','total'))):
        return 'Unsupported purchase approval.'
    if action.backend not in (None,'python'): return 'Unsupported posting backend.'
    if action.payload.get('operation') == 'purchase_gst':
        from app.services.purchase_tax_service import acceptance_enabled
        if not acceptance_enabled(): return 'GST live acceptance pending; posting locked.'
    return None

def bucket(status, ready=False):
    if ready: return 'ready'
    if status in ('queued','submitting','verification_pending'): return 'posting'
    if status == 'verified': return 'verified'
    return 'needs_attention'

async def queue(db, principal, view='all', offset=0, limit=100):
    drafts.admin(principal)
    if view not in ('all', *VIEWS): raise HTTPException(400, 'Unknown review view.')
    # Scope first; filter and paginate afterwards so each view has correct counts.
    query=select(PurchaseDraft).join(TallyReadCompany).where(
        PurchaseDraft.organization_id==principal.organization_id,
        PurchaseDraft.user_id==principal.user_id,
        TallyReadCompany.organization_id==principal.organization_id,
        TallyReadCompany.enabled.is_(True),drafts.active_source_filter()).order_by(PurchaseDraft.updated_at.desc(),PurchaseDraft.id)
    bills=[]
    for row in await db.scalars(query):
        item=await drafts.view(db,row)
        action=await db.get(TallyAction,row.action_id) if row.action_id else None
        reason=ready_reason(action,principal)
        if reason is None and (action.preconditions or {}).get('alias_bindings'):
            from app.services.purchase_memory_service import validate_bindings
            from app.services.tally_connector import TallyError
            try:await validate_bindings(db,await db.get(TallyReadCompany,row.company_id),action.preconditions['alias_bindings'])
            except TallyError as exc:reason=str(exc)
        item.update(kind='draft',queue_bucket=bucket(item['status'],reason is None),
                    ready=reason is None,review_reason=reason)
        doc=await db.get(BillDocument,row.document_id) if row.document_id else None
        if doc and doc.extraction_status in ('queued','processing') and not row.action_id:
            item.update(queue_bucket='processing',ready=False,review_reason='Extraction in progress.')
        bills.append(item)
    docs=await db.scalars(select(BillDocument).join(TallyReadCompany).where(
        BillDocument.organization_id==principal.organization_id,BillDocument.user_id==principal.user_id,
        TallyReadCompany.organization_id==principal.organization_id,TallyReadCompany.enabled.is_(True),BillDocument.trashed_at.is_(None),
        ~exists(select(PurchaseDraft.id).where(PurchaseDraft.document_id==BillDocument.id)))
        .order_by(BillDocument.created_at.desc(),BillDocument.id))
    for doc in docs:
        processing=doc.status in ('queued','processing') or doc.extraction_status in ('queued','processing')
        bills.append(dict(id=doc.id,kind='document',document_id=doc.id,document_filename=doc.filename,
            company_id=doc.company_id,queue_bucket='processing' if processing else 'needs_attention',
            status=doc.extraction_status or doc.status,ready=False,
            review_reason=doc.extraction_error or doc.error_code or 'Open Upload bills to extract/retry this document.'))
    counts={key:sum(b['queue_bucket']==key for b in bills) for key in VIEWS}
    filtered=[b for b in bills if view=='all' or b['queue_bucket']==view]
    return dict(bills=filtered[offset:offset+limit],counts=counts,total=len(filtered),offset=offset,limit=limit)

async def approve_one(db, principal, item):
    row=await drafts.scoped_draft(db,principal,item.draft_id,lock=True)
    if row.revision != item.revision or row.action_id != item.action_id:
        raise HTTPException(409,'Stale draft/preview. Reopen and review current values.')
    action=await db.scalar(select(TallyAction).where(TallyAction.token==row.action_id)
        .with_for_update().execution_options(populate_existing=True))
    reason=ready_reason(action,principal)
    if reason: raise HTTPException(409,reason)
    from app.services.tally_sync import confirm_queued
    result=await confirm_queued(db,principal,action,approve=True)
    if result.get('sync_status') != 'queued': raise HTTPException(409,'Bill was not queued; refresh status.')
    return dict(draft_id=item.draft_id,ok=True,status='queued',response=result['response'])

async def bulk_approve(db, principal, request):
    drafts.admin(principal)
    # Rollback expires ORM-backed Principal properties; retain the authenticated IDs.
    principal=SimpleNamespace(organization_id=principal.organization_id,user_id=principal.user_id,
                              session_id=principal.session_id,role=principal.role)
    results=[]
    for item in request.items:
        # Commit/rollback each item: failed bill must not undo successful approvals.
        try:
            result=await approve_one(db,principal,item)
            await db.commit()
        except HTTPException as exc:
            await db.rollback()
            result=dict(draft_id=item.draft_id,ok=False,status='conflict' if exc.status_code==409 else 'error',response=exc.detail)
        except Exception:
            await db.rollback()
            result=dict(draft_id=item.draft_id,ok=False,status='error',response='Approval failed for this bill. Refresh and review; other bills continue.')
        results.append(result)
    return dict(results=results,approved=sum(r['ok'] for r in results),failed=sum(not r['ok'] for r in results))
