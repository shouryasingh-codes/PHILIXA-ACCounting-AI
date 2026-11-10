"""Fail-closed digital-PDF automation on the existing verified purchase outbox.

Reservations are retained, including failed/uncertain actions. Policy edits never
reset the company-wide daily budget. Once dispatched, only reconciliation runs.
"""
import hashlib
import json
import secrets
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func, exists
from app.models.purchase_automation import PurchaseAutomationPolicy as Policy, PurchaseAutomationDecision as Decision, PurchaseAutomationReservation as Reservation
from app.models.purchase_draft import PurchaseDraft
from app.models.bill_document import BillDocument
from app.models.tally import TallyAction, TallyReadCompany, TallyConnection
from app.models.organization_membership import OrganizationMembership
from app.models.organization import Organization
from app.models.user import User
from app.services import purchase_draft_service as drafts, purchase_memory_service as memory, purchase_identity as identity, tally_sync as sync
from app.services.tally_connector import TallyError

IST=timezone(timedelta(hours=5,minutes=30))
def day():return datetime.now(IST).date()
def digest(data):return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

class PolicySave(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    revision:int=Field(ge=0)
    mode:Literal['paused','shadow','auto']='paused'
    suppliers:list[str]=Field(default_factory=list,max_length=200)
    items:list[str]=Field(default_factory=list,max_length=500)
    per_invoice:Decimal|None=Field(default=None,gt=0,max_digits=16,decimal_places=2)
    daily_amount:Decimal|None=Field(default=None,gt=0,max_digits=16,decimal_places=2)
    daily_count:int|None=Field(default=None,gt=0,le=10000)

def complete(data):return bool(data and data.get('suppliers') and data.get('items') and all(data.get(k) for k in ('per_invoice','daily_amount','daily_count')))

async def authority(db,company,actor):
    member=await db.get(OrganizationMembership,(actor,company.organization_id),populate_existing=True)
    user=await db.get(User,actor,populate_existing=True)
    org=await db.get(Organization,company.organization_id,populate_existing=True)
    if not(company.enabled and member and member.status=='active' and member.role in ('owner','admin') and user and user.is_active and org and org.is_active):
        raise TallyError('Automation owner permission changed; review required.')
    return SimpleNamespace(organization_id=company.organization_id,user_id=actor,role=member.role,session_id='automation:'+company.id)

def binding(catalog,kind,label):
    master=identity.exact_master(catalog,kind,label)
    return dict(name=label,identity=identity.master_identity(master),fingerprint=identity.master_fingerprint(master))

async def policy_view(db,principal,company_id):
    await drafts.company_for(db,principal,company_id)
    row=await db.get(Policy,company_id,populate_existing=True)
    used=await usage(db,company_id)
    data=row.data if row else dict(mode='paused',suppliers=[],items=[],per_invoice=None,daily_amount=None,daily_count=None)
    return dict(revision=row.revision if row else 0,policy=data,enabled=complete(data) and data['mode']!='paused',usage=used,day=str(day()),timezone='Asia/Kolkata')

async def save_policy(db,principal,company_id,request):
    company=await drafts.company_for(db,principal,company_id)
    await authority(db,company,principal.user_id)
    # Serialize first creation as well as edits; company scope cannot be supplied by clients.
    await db.refresh(company,with_for_update=True)
    row=await db.get(Policy,company_id,populate_existing=True,with_for_update=True)
    if request.revision!=(row.revision if row else 0):raise HTTPException(409,'Automation policy changed; reload first.')
    catalog=await memory.catalog_for(db,company) if request.mode!='paused' and (request.suppliers or request.items) else None
    data=request.model_dump(mode='json',exclude={'revision'})
    try:
        if len(set(request.suppliers))!=len(request.suppliers) or len(set(request.items))!=len(request.items):raise TallyError('Duplicate allowlist selection.')
        data['supplier_bindings']=[binding(catalog,'supplier',s) for s in request.suppliers] if request.mode!='paused' else (row.data.get('supplier_bindings',[]) if row else [])
        data['item_bindings']=[binding(catalog,'item',s) for s in request.items] if request.mode!='paused' else (row.data.get('item_bindings',[]) if row else [])
    except TallyError as exc:raise HTTPException(422,str(exc))
    if row:row.revision+=1;row.actor_id=principal.user_id;row.data=data;row.updated_at=sync.now()
    else:row=Policy(company_id=company_id,revision=1,actor_id=principal.user_id,data=data,updated_at=sync.now());db.add(row)
    # Policy edits are immutable audit events, separate from decision history.
    from app.models.purchase_automation import PurchaseAutomationPolicyEvent
    db.add(PurchaseAutomationPolicyEvent(id=secrets.token_hex(16),company_id=company_id,revision=row.revision,actor_id=principal.user_id,data=data,created_at=sync.now()))
    await db.commit()
    return await policy_view(db,principal,company_id)

async def pause_policy(db,principal,company_id):
    # Pausing must work even if masters/storage are unavailable or the form is stale.
    company=await drafts.company_for(db,principal,company_id)
    await authority(db,company,principal.user_id)
    await db.refresh(company,with_for_update=True)
    row=await db.get(Policy,company_id,populate_existing=True,with_for_update=True)
    data=row.data if row else {}
    return await save_policy(db,principal,company_id,PolicySave(revision=row.revision if row else 0,
        **{k:v for k,v in data.items() if k in PolicySave.model_fields and k not in ('mode','revision')},mode='paused'))

async def usage(db,company_id):
    count,amount=(await db.execute(select(func.count(),func.coalesce(func.sum(Reservation.amount),0)).where(Reservation.company_id==company_id,Reservation.day==day()))).one()
    return dict(count=count,amount=str(amount))

async def capacity(db,policy,amount):
    data=policy.data
    if not complete(data):raise TallyError('Automation disabled: supplier/items and every positive limit are required.')
    used=await usage(db,policy.company_id)
    if amount>Decimal(data['per_invoice']):raise TallyError('Per-invoice automation limit exceeded.')
    if used['count']+1>data['daily_count'] or Decimal(used['amount'])+amount>Decimal(data['daily_amount']):raise TallyError('Daily automation amount/count limit exceeded.')

async def approved_masters(db,company,policy,content):
    catalog=await memory.catalog_for(db,company)
    for kind,labels,key in (('supplier',[content['party_name']],'supplier_bindings'),('item',[l['item_name'] for l in drafts.draft_lines(content)],'item_bindings')):
        for label in labels:
            current=binding(catalog,kind,label)
            if current not in policy.data.get(key,[]):raise TallyError('Supplier/item is not approved or its master changed; review required.')
    return catalog

def same_amount(a,b):return Decimal(str(a or 0))==Decimal(str(b or 0))

async def source_gate(db,row,company):
    """Re-read checksum-verified original, never trust an editable OCR confidence."""
    from app.services import bill_document_service as documents, invoice_extraction as extraction
    doc=await db.get(BillDocument,row.document_id) if row.document_id else None
    if not doc or doc.company_id!=company.id or doc.status!='ready' or doc.media_type!='application/pdf':
        raise TallyError('Only complete digital text PDF sources are auto eligible; photos/scans need review.')
    raw=json.loads((await documents.parse(await documents.original_bytes(doc),'automation')).decode())
    if not raw.pop('_digital_only',False) or raw.get('multiple_invoices_detected') or raw.get('warnings'):
        raise TallyError('Scanned, mixed, ambiguous or unsupported PDF evidence needs review.')
    drafts.validate_document_company(raw,company.name)
    content=row.content
    if identity.normalized(raw.get('invoice_number'))!=identity.normalized(content.get('invoice_number')) or not raw.get('invoice_number'):
        raise TallyError('Original invoice reference evidence differs or is missing.')
    parsed=extraction.parse_date(raw.get('invoice_date'))
    if not parsed or parsed.isoformat()!=content.get('entry_date'):raise TallyError('Original invoice date evidence differs or is missing.')
    # Exact names or previously approved aliases only; fuzzy extraction suggestions cannot authorize a write.
    aliases=await memory.reusable_aliases(db,SimpleNamespace(organization_id=row.organization_id,user_id=row.user_id,role='owner'),company.id)
    verified=extraction.verify_and_match(raw,dict(suppliers=[content['party_name']],items=[{'name':l['item_name'],'unit':l['unit']} for l in drafts.draft_lines(content)],approved_aliases=aliases))
    if verified['party_name']!=content['party_name'] or not verified['field_evidence']['party_name']['matched']:
        raise TallyError('Supplier source identity is ambiguous.')
    lines=raw.get('lines') or [];target=drafts.draft_lines(content)
    if not lines or len(lines)!=len(target):raise TallyError('Complete source line evidence required.')
    for index,(source,line) in enumerate(zip(lines,target)):
        matched=verified['line_evidence'][index]['item_name']
        if not matched.get('matched') or verified['lines'][index]['item_name']!=line['item_name']:raise TallyError('Item source identity is ambiguous.')
        if identity.normalized(source.get('unit'))!=identity.normalized(line.get('unit')):raise TallyError('Original unit evidence differs.')
        for key in ('quantity','rate'):
            if not source.get(key) or not same_amount(source[key],line.get(key)):raise TallyError('Original quantity/rate evidence differs or is missing.')
        for key in ('discount_amount','discount_percent','gst_rate','taxable_amount'):
            if not same_amount(source.get(key),line.get(key)):raise TallyError('Original discount/tax/line amount evidence differs.')
        if str(source.get('hsn') or '')!=str(line.get('hsn') or ''):raise TallyError('Original HSN evidence differs.')
    total=raw.get('invoice_total',raw.get('total_amount'))
    if not total or not content.get('invoice_total') or not same_amount(total,content['invoice_total']):raise TallyError('Original grand total evidence required and must match.')
    for key in ('invoice_discount','round_off'):
        if not same_amount(raw.get(key),content.get(key)):raise TallyError('Original discount/round-off differs.')
    for key in ('tax_treatment','supplier_gstin','place_of_supply'):
        if (raw.get(key) or None)!=(content.get(key) or None):raise TallyError('Original GST evidence differs.')
    for head in ('CGST','SGST','IGST','UTGST'):
        if not same_amount((raw.get('expected_taxes') or {}).get(head),(content.get('expected_taxes') or {}).get(head)):raise TallyError('Original tax amounts differ.')
    return dict(source_sha256=doc.sha256,content_hash=digest(content),amount=str(total))

def decision_view(row):return dict(id=row.id,revision=row.revision,policy_revision=row.policy_revision,decision=row.decision,reasons=row.reasons,evidence=row.evidence,action_id=row.action_id,created_at=row.created_at.isoformat())

async def history(db,principal,draft_id):
    row=await drafts.scoped_draft(db,principal,draft_id)
    rows=await db.scalars(select(Decision).where(Decision.draft_id==row.id).order_by(Decision.created_at.desc()).limit(50))
    return {'decisions':[decision_view(r) for r in rows]}

async def evaluate(db,principal,draft_id,force=False):
    # Independent advisory transaction survives preview commits and excludes API/cron races.
    from app.database.session import async_engine
    from sqlalchemy import text
    key=int(hashlib.sha256(draft_id.encode()).hexdigest()[:8],16)&0x7fffffff
    async with async_engine.connect() as conn:
        locked=await conn.scalar(text('SELECT pg_try_advisory_xact_lock(73928,:key)'),{'key':key})
        if not locked:raise HTTPException(409,'This bill automation evaluation is already running.')
        return await _evaluate(db,principal,draft_id,force)

async def _evaluate(db,principal,draft_id,force=False):
    """One durable decision per current revision/policy; auto only with explicit mode."""
    principal=SimpleNamespace(organization_id=principal.organization_id,user_id=principal.user_id,session_id=principal.session_id,role=principal.role)
    row=await drafts.scoped_draft(db,principal,draft_id)
    company=await drafts.company_for(db,principal,row.company_id)
    policy=await db.get(Policy,company.id,populate_existing=True)
    revision=policy.revision if policy else 0
    existing=await db.scalar(select(Decision).where(Decision.draft_id==row.id,Decision.revision==row.revision,Decision.policy_revision==revision).order_by(Decision.created_at.desc()))
    if existing and not force:return decision_view(existing)
    proof={};reason=[];choice='blocked';action=None
    draft_pk=row.id;company_pk=company.id
    expected_revision=row.revision+1
    try:
        if not policy or policy.data.get('mode')=='paused' or not complete(policy.data):raise TallyError('Automation disabled/paused or required limits unset.')
        await authority(db,company,policy.actor_id)
        if policy.actor_id!=principal.user_id:raise TallyError('Only the policy owner can evaluate this personal draft for automation.')
        proof=await source_gate(db,row,company)
        await approved_masters(db,company,policy,row.content)
        await capacity(db,policy,Decimal(proof['amount']))
        if row.action_id:
            old=await db.get(TallyAction,row.action_id)
            if old and old.status not in ('preview','expired','cancelled'):raise TallyError('Bill already has an action; automatic retry prohibited.')
        # Existing compiler validates every supported total/tax, current master and native duplicate.
        await drafts.preview_draft(db,principal,row.id,drafts.DraftPreview(revision=row.revision))
        row=await db.get(PurchaseDraft,draft_pk,populate_existing=True)
        action=await db.get(TallyAction,row.action_id,populate_existing=True)
        if not (action and action.preconditions and action.preconditions.get('invoice_guard')):raise TallyError('Validated duplicate/source guard required.')
        # Preview compilation commits. Reacquire durable lock and recheck the entire authorization boundary.
        expected_action=action.token
        await db.refresh(row,with_for_update=True)
        await db.refresh(action,with_for_update=True)
        if row.action_id!=expected_action or action.status!='preview':raise TallyError('Draft/action changed during evaluation.')
        company=await db.get(TallyReadCompany,company_pk,populate_existing=True,with_for_update=True)
        policy=await db.get(Policy,company_pk,populate_existing=True,with_for_update=True)
        if policy.revision!=revision or policy.data.get('mode')=='paused':raise TallyError('Automation policy changed during validation.')
        await authority(db,company,policy.actor_id)
        if row.revision!=expected_revision:raise TallyError('Draft changed during evaluation.')
        fresh_proof=await source_gate(db,row,company)
        if fresh_proof['source_sha256']!=proof['source_sha256']:raise TallyError('Original source changed during evaluation.')
        proof=fresh_proof
        await approved_masters(db,company,policy,row.content)
        await capacity(db,policy,Decimal(proof['amount']))
        choice='auto_post'
        reason=['All digital source, approved identity, calculation, duplicate and policy gates passed.']
        if policy.data['mode']=='auto':
            reservation=Reservation(action_id=action.token,company_id=company.id,policy_revision=policy.revision,day=day(),amount=Decimal(proof['amount']),created_at=sync.now())
            db.add(reservation)
            action.preconditions={**action.preconditions,'automation':dict(policy_revision=revision,actor_id=policy.actor_id,**proof)}
            reason.append('Auto-post queued under reserved daily limits; Tally verification pending.')
            record=Decision(id=secrets.token_hex(16),company_id=company_pk,draft_id=draft_pk,revision=row.revision,policy_revision=revision,decision=choice,reasons=reason,evidence=proof,action_id=action.token,created_at=sync.now())
            db.add(record)
            await db.flush()
            await sync.confirm_queued(db,principal,action)
            return decision_view(record)
        else:reason.append('Shadow mode: human approval required. No automatic posting.')
    except (TallyError,HTTPException,ValueError,KeyError) as exc:
        detail=str(exc.detail) if isinstance(exc,HTTPException) else str(exc)
        await db.rollback()
        row=await db.get(PurchaseDraft,draft_pk,populate_existing=True)
        reason=[detail[:500] or 'Evidence validation failed; review required.']
        choice='blocked' if any(w in reason[0].lower() for w in ('duplicate','limit','disabled','paused','permission','company mismatch','already has an action')) else 'review'
    record=Decision(id=secrets.token_hex(16),company_id=company_pk,draft_id=draft_pk,revision=row.revision,policy_revision=revision,decision=choice,reasons=reason,evidence=proof,action_id=row.action_id,created_at=sync.now())
    db.add(record);await db.commit();return decision_view(record)

async def dispatch_guard(db,action):
    """Called immediately before send and again when the helper claims a write."""
    auto=(action.preconditions or {}).get('automation')
    if not auto:return
    policy=await db.get(Policy,action.company_id,populate_existing=True)
    company=await db.get(TallyReadCompany,action.company_id,populate_existing=True)
    reservation=await db.get(Reservation,action.token,populate_existing=True)
    if not policy or not company or policy.revision!=auto['policy_revision'] or policy.data.get('mode')!='auto' or not complete(policy.data):raise TallyError('Automation policy paused/changed; automatic posting stopped.')
    if policy.actor_id!=auto['actor_id'] or action.user_id!=policy.actor_id:raise TallyError('Automation actor changed.')
    await authority(db,company,policy.actor_id)
    if not reservation or reservation.policy_revision!=policy.revision or reservation.day!=day() or reservation.amount!=Decimal(auto['amount']):raise TallyError('Automation reservation missing or expired; review required.')
    row=await db.scalar(select(PurchaseDraft).where(PurchaseDraft.action_id==action.token))
    if not row or digest(row.content)!=auto['content_hash']:raise TallyError('Automatic draft evidence changed.')
    await approved_masters(db,company,policy,row.content)
    proof=await source_gate(db,row,company)
    if proof!={key:auto[key] for key in proof}:raise TallyError('Automatic source evidence changed.')

async def automation_tick(ctx):
    from app.database.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        ids=list((await db.execute(select(PurchaseDraft.id,PurchaseDraft.company_id).join(Policy,Policy.company_id==PurchaseDraft.company_id).where(
            PurchaseDraft.action_id.is_(None),PurchaseDraft.document_id.is_not(None),Policy.data['mode'].as_string().in_(('shadow','auto')),
            ~exists(select(Decision.id).where(Decision.draft_id==PurchaseDraft.id,Decision.revision==PurchaseDraft.revision,Decision.policy_revision==Policy.revision)))
            .order_by(PurchaseDraft.created_at).limit(50))).all())
        for draft_id,company_id in ids:
            try:
                policy=await db.get(Policy,company_id,populate_existing=True)
                if policy.data.get('mode')=='paused':continue
                company=await db.get(TallyReadCompany,company_id,populate_existing=True)
                principal=await authority(db,company,policy.actor_id)
                row=await db.get(PurchaseDraft,draft_id)
                if row.user_id!=principal.user_id:continue
                await evaluate(db,principal,draft_id)
            except HTTPException as exc:
                await db.rollback()
                if exc.status_code!=409:
                    import logging
                    logging.getLogger(__name__).warning('Automation evaluation unavailable for draft %s: %s',draft_id,exc.status_code)
            except Exception:
                await db.rollback()
                import logging
                logging.getLogger(__name__).exception('Automation evaluation failed for draft %s',draft_id)
