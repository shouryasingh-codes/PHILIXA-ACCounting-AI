"""Scoped full-receipt linkage and dispatch proof, never an invoice substitute."""
import copy
from fastapi import HTTPException
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import select
from app.models.tally import TallyAction,TallyReadCompany
from app.models.purchase_draft import PurchaseDraft
from app.services import purchase_draft_service as drafts,tally_sync as sync
from app.services.tally_connector import TallyError
from app.services import tally_receipt_link as codec,tally_goods_receipt as receipts

class LinkRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=0)
    receipt_draft_id:str=Field(pattern='^[a-f0-9]{32}$')
    receipt_revision:int=Field(ge=0)

async def available(db,principal,company_id):
    await drafts.company_for(db,principal,company_id)
    actions=(await db.scalars(select(TallyAction).where(TallyAction.company_id==company_id,TallyAction.status=='verified'))).all()
    consumed={a.preconditions['receipt_link_source']['receipt_action_id'] for a in actions if (a.preconditions or {}).get('receipt_link_source')}
    rows=(await db.scalars(select(PurchaseDraft).where(PurchaseDraft.company_id==company_id,PurchaseDraft.organization_id==principal.organization_id,PurchaseDraft.user_id==principal.user_id))).all()
    native={a.token:a for a in actions if a.payload.get('operation')=='goods_receipt' and a.token not in consumed}
    return {'receipts':[{'id':r.id,'revision':r.revision,'supplier':native[r.action_id].payload['party'],
        'received_on':native[r.action_id].payload['date'],'tracking':native[r.action_id].payload['tracking'],
        'items':native[r.action_id].payload['items']} for r in rows if r.action_id in native]}

async def source(db,principal,row,request):
    original=await drafts.scoped_draft(db,principal,request.receipt_draft_id,lock=True)
    if original.id==row.id or original.company_id!=row.company_id or original.revision!=request.receipt_revision:
        raise HTTPException(409,'Receipt company/revision mismatch.')
    action=await db.get(TallyAction,original.action_id,populate_existing=True)
    company=await drafts.company_for(db,principal,row.company_id)
    if not action or action.status!='verified' or action.payload.get('operation')!='goods_receipt' or action.target_identity!={'company':company.identity}:
        raise HTTPException(409,'Verified native Receipt Note required before invoice linkage.')
    return original,action

async def link(db,principal,draft_id,request):
    row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
    old=await drafts.editable_action(db,row,request.revision)
    if (row.extraction_metadata or {}).get('goods_receipt'):raise HTTPException(409,'Supplier bill must be a separate invoice draft.')
    if not row.content.get('invoice_number') or not row.content.get('entry_date'):raise HTTPException(422,'Actual invoice reference/date required.')
    original,action=await source(db,principal,row,request)
    candidate={'operation':'purchase_gst' if row.content.get('tax_treatment') else 'purchase_multi',
        'company':action.payload['company'],'party':row.content.get('party_name'),
        'godown':row.content.get('godown') or action.payload['godown'],'date':row.content['entry_date'],
        'items':[{'item':l.get('item_name'),'unit':l.get('unit'),'quantity':l.get('quantity')} for l in row.content['lines']]}
    try:codec.validate_link(candidate,action.payload)
    except (TallyError,TypeError,KeyError) as exc:raise HTTPException(422,str(exc))
    if old and old.status=='preview':old.status='expired'
    row.action_id=None;row.revision+=1;row.updated_at=sync.now()
    row.extraction_metadata={**(row.extraction_metadata or {}),'receipt_link_source':{
        'receipt_draft_id':original.id,'receipt_revision':original.revision,'receipt_action_id':action.token}}
    drafts.record_event(db,row,principal.user_id,'receipt_linked',row.extraction_metadata['receipt_link_source'])
    await db.commit();return await drafts.view(db,row)

async def guard(db,action):
    proof=(action.preconditions or {}).get('receipt_link_source')
    if not proof:return
    original=await db.get(PurchaseDraft,proof['receipt_draft_id'],populate_existing=True)
    native=await db.get(TallyAction,proof['receipt_action_id'],populate_existing=True)
    company=await db.get(TallyReadCompany,action.company_id,populate_existing=True)
    if not original or not native or not company or original.organization_id!=action.organization_id or original.company_id!=action.company_id or original.revision!=proof['receipt_revision'] or original.action_id!=native.token or native.status!='verified' or native.payload!=(action.preconditions or {}).get('receipt_link') or native.target_identity!={'company':company.identity}:
        raise TallyError('Original receipt identity/evidence changed; review linkage.')
    codec.validate_link(action.payload,native.payload)

async def bind_preview(db,principal,row,result):
    proof=(row.extraction_metadata or {}).get('receipt_link_source')
    if not proof:return result
    request=LinkRequest(revision=row.revision,receipt_draft_id=proof['receipt_draft_id'],receipt_revision=proof['receipt_revision'])
    _,original=await source(db,principal,row,request)
    action=await db.get(TallyAction,result['preview']['token'])
    codec.validate_link(action.payload,original.payload)
    action.preconditions={**(action.preconditions or {}),'receipt_link_source':copy.deepcopy(proof),'receipt_link':copy.deepcopy(original.payload)}
    action.xml_payload=codec.linked_xml(action.xml_payload,action.payload,original.payload)
    result['preview']['lines'].append('Linked Receipt Note: '+original.payload['tracking']+' · full quantities; stock must not increase twice.')
    if not receipts.RECEIPT_CODEC_CERTIFIED:
        result['preview']['can_confirm']=False
        result['preview']['blockers'].append('Native tracked receipt/invoice acceptance pending.')
    company=await drafts.company_for(db,principal,row.company_id)
    device=await sync.bound_device(db,company)
    ready=False
    if device:
        from app.core.redis import get_redis_client
        redis=await get_redis_client()
        try:ready=bool(await redis.exists('tally:v11online:'+device.id))
        finally:await redis.aclose()
    if not ready:
        result['preview']['can_confirm']=False
        result['preview']['blockers'].append('Linked invoice requires a paired protocol 11 connector.')
    await db.commit();return result

async def guard_unlinked(db,company_id,party,items,linked_source=None):
    actions=(await db.scalars(select(TallyAction).where(TallyAction.company_id==company_id,
        TallyAction.status.in_(('queued','submitting','verification_pending','verified'))))).all()
    receipts_open=[a for a in actions if a.payload.get('operation')=='goods_receipt' and a.payload.get('party')==party and any(l['item'] in items for l in a.payload['items'])]
    consumed={a.preconditions['receipt_link_source']['receipt_action_id'] for a in actions if a.status=='verified' and (a.preconditions or {}).get('receipt_link_source')}
    selected=(linked_source or {}).get('receipt_action_id')
    if any(a.token not in consumed and a.token!=selected for a in receipts_open):
        raise HTTPException(409,'Matching bill-pending Receipt Note exists. Link the invoice to that receipt; a new untracked purchase can double stock.')
