"""Company-scoped, explicitly approved aliases and invoice duplicate reservations."""
import copy
import secrets
from datetime import datetime, timezone
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from app.models.purchase_memory import PurchaseAlias, PurchaseInvoiceClaim
from app.models.purchase_draft import PurchaseDraft
from app.models.bill_document import BillDocument
from app.models.tally import TallyAction, TallyReadCompany
from app.services import purchase_draft_service as drafts, tally_sync as sync
from app.services import purchase_identity as identity
from app.services.tally_sync_protocol import deserialize_catalog
from app.services.tally_connector import TallyError

class AliasApproval(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=0)
    kind:Literal['supplier','item']
    line_index:int|None=Field(default=None,ge=0,le=99)

async def catalog_for(db,company):
    snapshot=await sync.saved_snapshot(db,company)
    if not snapshot:raise TallyError('Saved masters missing; sync Tally and review.')
    return deserialize_catalog(snapshot.catalog)

def binding_valid(alias,catalog):
    try:
        master=identity.exact_master(catalog,alias.kind,alias.target)
        return identity.master_identity(master)==alias.master_identity and identity.master_fingerprint(master)==alias.fingerprint
    except TallyError:return False

async def alias_list(db,principal,company_id):
    company=await drafts.company_for(db,principal,company_id)
    try:catalog=await catalog_for(db,company)
    except TallyError as exc:raise HTTPException(409,str(exc))
    rows=await db.scalars(select(PurchaseAlias).where(PurchaseAlias.company_id==company.id))
    return {'aliases':[dict(id=r.id,kind=r.kind,source=r.source,target=r.target,fingerprint=r.fingerprint,valid=binding_valid(r,catalog)) for r in rows]}

async def approve_alias(db,principal,draft_id,request):
    row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
    action=await drafts.editable_action(db,row,request.revision)
    meta=copy.deepcopy(row.extraction_metadata or {})
    try:
        if request.kind=='supplier':
            source=meta['field_evidence']['party_name']['raw'];target=row.content['party_name']
        else:
            if request.line_index is None:raise KeyError()
            source=meta['line_evidence'][request.line_index]['item_name']['raw'];target=row.content['lines'][request.line_index]['item_name']
        if not isinstance(source,str) or not source.strip() or not isinstance(target,str):raise KeyError()
    except (KeyError,IndexError,TypeError):raise HTTPException(422,'Original correction evidence missing. Save and review the extracted field first.')
    company=await drafts.company_for(db,principal,row.company_id)
    try:
        catalog=await catalog_for(db,company);master=identity.exact_master(catalog,request.kind,target)
        mid=identity.master_identity(master);fingerprint=identity.master_fingerprint(master)
    except TallyError as exc:raise HTTPException(422,str(exc))
    await db.scalar(select(TallyReadCompany).where(TallyReadCompany.id==company.id).with_for_update())
    alias=await db.scalar(select(PurchaseAlias).where(PurchaseAlias.company_id==company.id,PurchaseAlias.kind==request.kind,PurchaseAlias.alias_key==identity.normalized(source)).with_for_update())
    if not alias:
        alias=PurchaseAlias(id=secrets.token_hex(16),company_id=company.id,kind=request.kind,alias_key=identity.normalized(source))
        db.add(alias)
    alias.source=source;alias.target=identity.name(master);alias.master_identity=mid;alias.fingerprint=fingerprint
    alias.actor_id=principal.user_id;alias.draft_id=row.id;alias.created_at=sync.now()
    # Re-approval after a master change replaces this draft's obsolete binding.
    bindings=[b for b in meta.get('approved_aliases',[]) if not (b['kind']==request.kind and b.get('line_index')==request.line_index)]
    bindings.append(dict(id=alias.id,kind=request.kind,line_index=request.line_index,fingerprint=fingerprint))
    meta['approved_aliases']=bindings;row.extraction_metadata=meta
    if action and action.status=='preview':action.status='expired'
    row.action_id=None;row.revision+=1;row.updated_at=sync.now()
    drafts.record_event(db,row,principal.user_id,'alias_approved',details=dict(kind=alias.kind,source=source,target=alias.target,master_identity=mid,fingerprint=fingerprint,line_index=request.line_index))
    await db.commit()
    return await drafts.view(db,row)

async def reusable_aliases(db,principal,company_id):
    company=await drafts.company_for(db,principal,company_id)
    try:catalog=await catalog_for(db,company)
    except TallyError:return {}
    rows=await db.scalars(select(PurchaseAlias).where(PurchaseAlias.company_id==company.id))
    return {r.kind+':'+r.alias_key:dict(id=r.id,kind=r.kind,target=r.target,fingerprint=r.fingerprint) for r in rows if binding_valid(r,catalog)}

async def validate_bindings(db,company,bindings):
    catalog=await catalog_for(db,company)
    for b in bindings:
        alias=await db.get(PurchaseAlias,b['id'],populate_existing=True)
        if not alias or alias.company_id!=company.id or alias.fingerprint!=b['fingerprint'] or not binding_valid(alias,catalog):
            raise TallyError('Approved mapping/master changed. Review the correction and approve its alias again.')
    return catalog

async def check_local(db,row,guard):
    claim=await db.get(PurchaseInvoiceClaim,guard['key'],populate_existing=True)
    if claim and claim.action_id!=row.action_id:
        action=await db.get(TallyAction,claim.action_id,populate_existing=True)
        if action and action.status not in ('cancelled','failed','expired'):raise TallyError('Duplicate invoice already approved or posted; open its existing draft.')
    company=await db.get(TallyReadCompany,row.company_id)
    catalog=await catalog_for(db,company)
    source=await db.get(BillDocument,row.document_id) if row.document_id else None
    rows=await db.scalars(select(PurchaseDraft).where(PurchaseDraft.company_id==row.company_id,PurchaseDraft.id!=row.id))
    for other in rows:
        previous=await db.get(TallyAction,other.action_id) if other.action_id else None
        if previous and previous.status in ('cancelled','failed','expired'):continue
        candidate=other.created_at<=row.created_at or (previous and (previous.status in ('queued','submitting','verification_pending','verified') or sync.uncertain(previous)))
        if not candidate:continue
        if source and other.document_id:
            document=await db.get(BillDocument,other.document_id)
            pages=set((row.extraction_metadata or {}).get('source_pages') or [1])
            other_pages=set((other.extraction_metadata or {}).get('source_pages') or [1])
            if document and document.sha256==source.sha256 and pages.intersection(other_pages):
                raise TallyError('Duplicate source document already has a bill draft. Open the existing draft.')
        try:other_guard=identity.invoice_guard(company.id+':'+company.identity,catalog,other.content)
        except TallyError:continue
        if other_guard['key']==guard['key']:raise TallyError('Duplicate supplier invoice/reference in this financial year; review the existing bill.')

async def live_check(db,company,guard):
    result=await sync.operation(db,company,'invoice_reference_check',payload=guard)
    if result.get('status')!='clear':raise TallyError(result.get('reason') or 'Tally duplicate check incomplete; review required.')

async def prepare_preview(db,principal,row,action):
    company=await drafts.company_for(db,principal,row.company_id)
    bindings=(row.extraction_metadata or {}).get('approved_aliases',[])
    catalog=await validate_bindings(db,company,bindings)
    guard=identity.invoice_guard(company.id+':'+company.identity,catalog,row.content)
    await check_local(db,row,guard)
    await live_check(db,company,guard)
    action.preconditions={**(action.preconditions or {}),'invoice_guard':guard,'alias_bindings':bindings}

async def reserve(db,principal,action):
    guard=(action.preconditions or {}).get('invoice_guard')
    if not guard:return  # Compatibility: old chat/legacy actions do not invent invoice evidence.
    company=await db.scalar(select(TallyReadCompany).where(TallyReadCompany.id==action.company_id).with_for_update())
    row=await db.scalar(select(PurchaseDraft).where(PurchaseDraft.action_id==action.token))
    if not row:raise TallyError('Invoice draft evidence missing.')
    catalog=await validate_bindings(db,company,(action.preconditions or {}).get('alias_bindings',[]))
    if identity.invoice_guard(company.id+':'+company.identity,catalog,row.content)!=guard:raise TallyError('Invoice identity/year changed; create a fresh preview.')
    await check_local(db,row,guard)
    claim=await db.get(PurchaseInvoiceClaim,guard['key'],populate_existing=True)
    if not claim:db.add(PurchaseInvoiceClaim(key=guard['key'],company_id=company.id,action_id=action.token,evidence=guard,created_at=sync.now()))
    else:claim.action_id=action.token;claim.evidence=guard;claim.created_at=sync.now()
    await db.flush()
