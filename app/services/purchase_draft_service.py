"""Scoped, revisioned drafts. Saving a draft never queues a Tally write."""
import copy
import secrets
from datetime import date, datetime, timezone
from typing import Literal
from decimal import Decimal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from app.models.purchase_draft import PurchaseDraft, PurchaseDraftEvent
from app.models.bill_document import BillDocument
from app.models.tally import TallyReadCompany, TallyAction
from app.services.tally_business import admin


class DraftLine(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    item_name: str | None = Field(default=None, max_length=200)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=6)
    unit: str | None = Field(default=None, max_length=50)
    rate: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    discount_amount: Decimal | None = Field(default=None,ge=0,max_digits=16,decimal_places=2)
    discount_percent: Decimal | None = Field(default=None,ge=0,lt=100,decimal_places=2)
    gst_rate: Decimal | None = Field(default=None,ge=0,le=100,decimal_places=3)
    hsn: str | None = Field(default=None,max_length=8)
    taxable_amount: Decimal | None = Field(default=None,ge=0,max_digits=20,decimal_places=2)


class DraftContent(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    party_name: str | None = Field(default=None, max_length=200)
    item_name: str | None = Field(default=None, max_length=200)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=6)
    unit: str | None = Field(default=None, max_length=50)
    rate: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    entry_date: date | None = None
    godown: str | None = Field(default=None, max_length=200)
    invoice_number: str | None = Field(default=None, max_length=100)
    tax_treatment: Literal['regular_domestic_goods'] | None = None
    supplier_gstin: str | None = Field(default=None,max_length=15)
    place_of_supply: str | None = Field(default=None,pattern=r'^\d{2}$')
    invoice_discount: Decimal | None = Field(default=None,ge=0,max_digits=20,decimal_places=2)
    round_off: Decimal | None = Field(default=None,ge=-1,le=1,decimal_places=2)
    invoice_total: Decimal | None = Field(default=None,ge=0,max_digits=20,decimal_places=2)
    expected_taxes: dict[str,Decimal] | None = None
    unsupported_treatments: list[str] = Field(default_factory=list,max_length=20)
    lines: list[DraftLine] | None = Field(default=None,min_length=1,max_length=100)

    @model_validator(mode='after')
    def one_shape(self):
        if self.expected_taxes is not None and (any(k not in ('CGST','SGST','IGST','UTGST') or not v.is_finite() or v<0 or v>Decimal('1000000000000') for k,v in self.expected_taxes.items())):
            raise ValueError('Invalid invoice tax amounts.')
        if self.tax_treatment and self.lines is None:raise ValueError('GST requires item lines.')
        if self.lines is not None and any(getattr(self,k) is not None for k in ('item_name','quantity','unit','rate')):
            raise ValueError('Use lines or the legacy single item fields, not both.')
        return self


def draft_lines(content):
    return content.get('lines') or [{k:content.get(k) for k in ('item_name','quantity','unit','rate')}]


def draft_totals(content):
    amounts=[str((Decimal(line['quantity'])*Decimal(line['rate'])).quantize(Decimal('.01')))
        if line.get('quantity') and line.get('rate') else None for line in draft_lines(content)]
    return {'line_totals':amounts,'total':str(sum((Decimal(x) for x in amounts),Decimal(0))) if all(x is not None for x in amounts) else None}


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    company_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    content: DraftContent = Field(default_factory=DraftContent)


class DraftSave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0)
    content: DraftContent


class DraftPreview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0)


async def company_for(db, principal, company_id):
    admin(principal)
    company = await db.scalar(select(TallyReadCompany).where(
        TallyReadCompany.id == company_id,
        TallyReadCompany.organization_id == principal.organization_id,
        TallyReadCompany.enabled.is_(True)))
    if not company:
        raise HTTPException(404, 'Company unavailable in this workspace.')
    return company


async def scoped_draft(db, principal, draft_id, lock=False):
    admin(principal)
    query = select(PurchaseDraft).join(TallyReadCompany, PurchaseDraft.company_id == TallyReadCompany.id).where(
        PurchaseDraft.id == draft_id, PurchaseDraft.organization_id == principal.organization_id,
        PurchaseDraft.user_id == principal.user_id, TallyReadCompany.organization_id == principal.organization_id,
        TallyReadCompany.enabled.is_(True))
    if lock:
        query = query.with_for_update(of=PurchaseDraft).execution_options(populate_existing=True)
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(404, 'Bill draft nahi mila.')
    return row


def record_event(db, row, actor, kind):
    db.add(PurchaseDraftEvent(id=secrets.token_hex(16), draft_id=row.id, revision=row.revision,
        actor_id=actor, kind=kind, snapshot=copy.deepcopy(row.content), action_id=row.action_id,
        created_at=datetime.now(timezone.utc)))


async def view(db, row):
    action = await db.get(TallyAction, row.action_id, populate_existing=True) if row.action_id else None
    if action:
        status = action.status
        editable = status not in ('queued','submitting','verification_pending','verified','needs_review') or (status=='needs_review' and isinstance(action.result,dict) and action.result.get('uncertain') is False)
    else:
        status = 'needs_review' if getattr(row, 'extraction_metadata', None) else 'draft'
        editable = True
    doc_id = getattr(row, 'document_id', None)
    doc = await db.get(BillDocument, doc_id, populate_existing=True) if doc_id else None
    return {'id':row.id, 'company_id':row.company_id,
        'document_id': doc_id, 'document_filename': doc.filename if doc else None,
        'content':copy.deepcopy(row.content),
        **draft_totals(row.content),
        'extraction_metadata': getattr(row, 'extraction_metadata', None),
        'revision':row.revision, 'action_id':row.action_id, 'status':status,
        'editable':editable,
        'created_at':row.created_at.isoformat(), 'updated_at':row.updated_at.isoformat()}


async def list_companies(db, principal):
    admin(principal)
    rows = await db.scalars(select(TallyReadCompany).where(
        TallyReadCompany.organization_id == principal.organization_id, TallyReadCompany.enabled.is_(True)
    ).order_by(TallyReadCompany.name))
    return {'companies':[{'id':r.id,'name':r.name} for r in rows]}


async def company_masters(db,principal,company_id):
    from app.services.tally_sync import saved_snapshot
    from app.services.tally_sync_protocol import deserialize_catalog
    from app.services.tally_connector import name,value,TallyError
    from app.services.tally_validation import validate_item
    company=await company_for(db,principal,company_id)
    snapshot=await saved_snapshot(db,company)
    if not snapshot:return {'suppliers':[],'items':[],'saved_masters':False}
    catalog=deserialize_catalog(snapshot.catalog);items=[]
    for item in catalog['items']:
        unit=value(item,'BASEUNITS')
        try:validate_item(catalog,item,unit)
        except TallyError:continue
        items.append({'name':name(item),'unit':unit})
    return {'suppliers':[name(r) for r in catalog['ledgers'] if value(r,'PARENT')=='Sundry Creditors'][:2000],
        'items':items[:2000],'saved_masters':True,'last_synced':snapshot.collected_at.isoformat()}


async def list_drafts(db, principal):
    admin(principal)
    rows = await db.scalars(select(PurchaseDraft).join(TallyReadCompany, PurchaseDraft.company_id == TallyReadCompany.id).where(
        PurchaseDraft.organization_id == principal.organization_id, PurchaseDraft.user_id == principal.user_id,
        TallyReadCompany.organization_id == principal.organization_id, TallyReadCompany.enabled.is_(True)
    ).order_by(PurchaseDraft.updated_at.desc(), PurchaseDraft.id.desc()).limit(100))
    return {'drafts':[await view(db,row) for row in rows]}


async def create_draft(db, principal, request):
    await company_for(db, principal, request.company_id)
    stamp = datetime.now(timezone.utc)
    row = PurchaseDraft(id=secrets.token_hex(16), organization_id=principal.organization_id,
        user_id=principal.user_id, company_id=request.company_id, content=request.content.model_dump(mode='json'),
        revision=0, action_id=None, created_at=stamp, updated_at=stamp)
    db.add(row)
    await db.flush()
    record_event(db,row,principal.user_id,'created')
    await db.commit()
    return await view(db,row)


async def read_draft(db, principal, draft_id):
    return await view(db,await scoped_draft(db,principal,draft_id))


async def editable_action(db, row, revision):
    if row.revision != revision:
        raise HTTPException(409, 'Draft doosre tab mein badla hai. Dobara kholein.')
    action = await db.scalar(select(TallyAction).where(TallyAction.token == row.action_id)
        .with_for_update().execution_options(populate_existing=True)) if row.action_id else None
    safe_review=bool(action and action.status=='needs_review' and isinstance(action.result,dict) and action.result.get('uncertain') is False)
    if action and action.status not in ('preview','expired','cancelled','failed') and not safe_review:
        raise HTTPException(409, 'Posted/pending entry edit nahi kar sakte. Pehle status review karein.')
    return action


async def save_draft(db, principal, draft_id, request):
    row = await scoped_draft(db,principal,draft_id,lock=True)
    action = await editable_action(db,row,request.revision)
    content = request.content.model_dump(mode='json')
    if row.content == content:
        await db.commit()
        return await view(db,row)
    if action and action.status == 'preview':
        action.status = 'expired'  # Old token must never approve edited values.
    row.content = content
    row.action_id = None
    row.revision += 1
    row.updated_at = datetime.now(timezone.utc)
    record_event(db,row,principal.user_id,'edited')
    await db.commit()
    return await view(db,row)


async def audit_draft(db, principal, draft_id):
    await scoped_draft(db,principal,draft_id)
    events = await db.scalars(select(PurchaseDraftEvent).where(PurchaseDraftEvent.draft_id == draft_id)
        .order_by(PurchaseDraftEvent.revision))
    return {'events':[{'revision':e.revision,'kind':e.kind,'actor_id':e.actor_id,
        'content':e.snapshot,'action_id':e.action_id,'created_at':e.created_at.isoformat()} for e in events]}


async def attach_preview(db, principal, action, row=None):
    """Called within the existing preview transaction. No independent commit."""
    p = action.payload
    if p.get('operation')=='purchase_gst':
        content=DraftContent.model_validate(p['source']).model_dump(mode='json')
    elif p.get('operation')=='purchase_multi':
        content=DraftContent(party_name=p['party'],entry_date=p['date'],godown=p['godown'],
            invoice_number=row.content.get('invoice_number') if row else None,
            lines=[DraftLine(item_name=l['item'],quantity=l['quantity'],unit=l['unit'],rate=l['rate']) for l in p['items']]).model_dump(mode='json')
    else:
        content = DraftContent(party_name=p['party'],item_name=p['item'],quantity=p['quantity'],
            unit=p['unit'],rate=p['rate'],entry_date=p['date'],godown=p['godown']).model_dump(mode='json')
    if row is None:
        row = PurchaseDraft(id=secrets.token_hex(16),organization_id=principal.organization_id,
            user_id=principal.user_id,company_id=action.company_id,revision=0,
            content=content,created_at=action.created_at,updated_at=action.created_at)
        db.add(row)
    else:
        row.content = content
        row.revision += 1
        row.updated_at = datetime.now(timezone.utc)
    await db.flush()  # Persist action before linking the FK.
    row.action_id = action.token
    await db.flush()
    record_event(db,row,principal.user_id,'preview_created')
    return row.id


async def preview_draft(db, principal, draft_id, request):
    from app.services.business_command_service import ParsedCommand
    from app.services import tally_sync
    row = await scoped_draft(db,principal,draft_id,lock=True)
    action = await editable_action(db,row,request.revision)
    meta=row.extraction_metadata or {}
    if meta.get('multiple_invoices_detected') and not meta.get('is_split_draft'):
        raise HTTPException(422, 'Multiple invoices: split and review separate drafts before preview.')
    content = DraftContent.model_validate(row.content)
    if content.unsupported_treatments:raise HTTPException(422,'Unsupported invoice treatments: '+', '.join(content.unsupported_treatments))
    required=('party_name','entry_date') if content.lines is not None else ('party_name','item_name','quantity','unit','rate','entry_date')
    missing = [key for key in required
        if not getattr(content,key)]
    if content.lines is not None:
        missing += [f'line {i+1}: {key}' for i,line in enumerate(content.lines)
            for key in ('item_name','quantity','unit','rate') if not getattr(line,key)]
    if missing:
        raise HTTPException(422, 'Preview ke liye fill karein: '+', '.join(missing))
    if action and action.status == 'preview':
        action.status = 'expired'
        await db.flush()
    if content.tax_treatment:
        from app.services.purchase_tax_service import preview_gst
        result=await preview_gst(db,principal,row,content)
    elif content.lines is not None:
        if content.invoice_total is not None:
            expected=draft_totals(content.model_dump(mode='json'))['total']
            if expected is None or Decimal(expected)!=content.invoice_total.quantize(Decimal('.01')):raise HTTPException(422,'Original invoice total differs from line total. Review taxes/discounts; no adjustment made.')
        if any(content.model_dump().get(k) for k in ('invoice_discount','round_off','expected_taxes','supplier_gstin')) or any(l.discount_amount or l.discount_percent or l.gst_rate for l in content.lines):
            raise HTTPException(422,'Tax/discount fields require supported GST treatment; values cannot be silently ignored.')
        from app.services.tally_multi_purchase_service import preview_multi_purchase
        result=await preview_multi_purchase(db,principal,row,content)
    else:
        parsed = ParsedCommand(intent='purchase_create',company_id=row.company_id,**content.model_dump(exclude={'lines','invoice_number','tax_treatment','supplier_gstin','place_of_supply','invoice_discount','round_off','invoice_total','expected_taxes','unsupported_treatments'}))
        result = await tally_sync.preview_purchase(db,principal,parsed,draft=row)
    if 'preview' not in result:
        await db.rollback()
        raise HTTPException(409,result['response'])
    return result
