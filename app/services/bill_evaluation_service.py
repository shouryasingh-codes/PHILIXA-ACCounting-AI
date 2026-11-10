"""Measurement is distinct from correctness: missing timing/cost stays unknown."""
import secrets
from decimal import Decimal,InvalidOperation
from datetime import datetime,timezone
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from app.models.bill_evaluation import BillEvaluationMetric as Metric

NUMERIC={'quantity','rate','discount_amount','discount_percent','gst_rate','taxable_amount','invoice_discount','round_off','invoice_total','CGST','SGST','IGST','UTGST'}
def flatten(value,path=''):
    if isinstance(value,dict):
        return {k:v for key,item in value.items() for k,v in flatten(item,f'{path}.{key}' if path else key).items()}
    if isinstance(value,list):return {k:v for index,item in enumerate(value) for k,v in flatten(item,f'{path}.{index}').items()}
    return {path:value}

def equivalent(path,left,right):
    if left in (None,'') and right in (None,''):return True
    if path.split('.')[-1] in NUMERIC:
        try:return Decimal(str(left))==Decimal(str(right))
        except (InvalidOperation,ValueError,TypeError):pass
    return left==right

def changed_fields(before,after):
    a,b=flatten(before),flatten(after)
    return sorted(k for k in a.keys()|b.keys() if not equivalent(k,a.get(k),b.get(k)))

def record(db,principal,kind,data,document_id=None,draft_id=None,event_id=None):
    db.add(Metric(id=event_id or secrets.token_hex(16),organization_id=principal.organization_id,user_id=principal.user_id,
        document_id=document_id,draft_id=draft_id,kind=kind,data=data,created_at=datetime.now(timezone.utc)))

class ReviewSample(BaseModel):
    model_config=ConfigDict(extra='forbid')
    event_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    revision:int=Field(ge=0)
    active_ms:int=Field(gt=0,le=60000)

async def record_review(db,principal,draft_id,sample):
    from app.services import purchase_draft_service as drafts
    from fastapi import HTTPException
    row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
    if sample.revision>row.revision:raise HTTPException(409,'Unknown future draft revision.')
    old=await db.get(Metric,sample.event_id)
    if old:
        if (old.organization_id,old.user_id,old.draft_id)!=(principal.organization_id,principal.user_id,row.id):raise HTTPException(409,'Review event already used.')
        return {'recorded':False,'duplicate':True}
    record(db,principal,'active_review',dict(active_ms=sample.active_ms,revision=sample.revision,method='client_active_visible_focused_idle_15s'),draft_id=row.id,document_id=row.document_id,event_id=sample.event_id)
    await db.commit();return {'recorded':True,'duplicate':False}

async def metrics(db,principal,draft_id):
    from app.services import purchase_draft_service as drafts
    row=await drafts.scoped_draft(db,principal,draft_id)
    scope=(Metric.draft_id==row.id)|((Metric.document_id==row.document_id)&(Metric.kind=='extraction_attempt')) if row.document_id else Metric.draft_id==row.id
    events=list(await db.scalars(select(Metric).where(Metric.organization_id==principal.organization_id,Metric.user_id==principal.user_id,scope).order_by(Metric.created_at)))
    corrections=[e for e in events if e.kind=='correction'];review=[e for e in events if e.kind=='active_review'];attempts=[e for e in events if e.kind=='extraction_attempt']
    costs=[e.data.get('provider_cost_usd') for e in attempts]
    return dict(draft_id=row.id,correction_count=sum(e.data['count'] for e in corrections),correction_saves=len(corrections),
        active_review_ms=sum(e.data['active_ms'] for e in review) if review else None,review_time_method='client active estimate; unobserved/closed-tab intervals may be missing',
        extraction_attempts=[e.data for e in attempts],processing_latency_ms=sum(e.data['latency_ms'] for e in attempts) if attempts else None,
        posting_events=[e.data for e in events if e.kind in ('posting_queued','posting_result')],
        authorization_events=[dict(e.data,recorded_at=e.created_at.isoformat()) for e in events if e.kind=='posting_authorized'],
        provider_cost_usd=str(sum((Decimal(str(c)) for c in costs),Decimal(0))) if costs and all(c is not None for c in costs) else None,
        manual_tally_baseline_ms=None,savings_percent=None,real_world_accuracy='unverified')

async def posting_event(db,action,kind):
    from app.models.purchase_draft import PurchaseDraft
    from types import SimpleNamespace
    row=await db.scalar(select(PurchaseDraft).where(PurchaseDraft.action_id==action.token))
    if not row:return
    data=dict(action_id=action.token,status=action.status)
    if kind=='posting_result':
        queued=await db.scalar(select(Metric).where(Metric.draft_id==row.id,Metric.kind=='posting_queued').order_by(Metric.created_at.desc()))
        if queued and queued.data.get('action_id')==action.token:data['queued_to_result_ms']=round((datetime.now(timezone.utc)-queued.created_at).total_seconds()*1000)
    record(db,SimpleNamespace(organization_id=action.organization_id,user_id=action.user_id),kind,data,document_id=row.document_id,draft_id=row.id)
