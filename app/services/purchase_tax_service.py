"""Scoped GST review, configuration and durable preview. No implicit posting."""
import os
import secrets
import uuid
from datetime import timedelta
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from fastapi import HTTPException
from app.models.tally import PurchaseTaxProfile,TallyConnection,TallyAction
from app.services import purchase_draft_service as drafts,tally_sync as sync
from app.services.tally_connector import TallyError,name,value
from app.services.tally_sync_protocol import deserialize_catalog
from app.services import tally_gst_purchase as gst

def acceptance_enabled():return os.getenv('PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED','1')=='1'

class TaxProfileSave(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    revision:int=Field(ge=0)
    ledgers:dict[str,str]
    rounding_ledger:str|None=Field(default=None,max_length=200)

async def profile_view(db,principal,company_id):
    company=await drafts.company_for(db,principal,company_id)
    snapshot=await sync.saved_snapshot(db,company)
    catalog=deserialize_catalog(snapshot.catalog) if snapshot else None
    row=await db.get(PurchaseTaxProfile,company_id,populate_existing=True)
    candidates={h:[] for h in gst.HEADS}
    if catalog:
        for ledger in catalog['ledgers']:
            if value(ledger,'PARENT')=='Duties & Taxes' and value(ledger,'TAXTYPE').casefold()=='gst' and gst.tax_head(value(ledger,'GSTDUTYHEAD')) in candidates:
                candidates[gst.tax_head(value(ledger,'GSTDUTYHEAD'))].append(name(ledger))
    defaults={h:labels[0] for h,labels in candidates.items() if len(labels)==1}
    return {'revision':row.revision if row else 0,'profile':row.data if row else {'ledgers':defaults,'rounding_ledger':None},
        'candidates':candidates,'rounding_candidates':[name(r) for r in catalog['ledgers'] if value(r,'PARENT') in ('Indirect Expenses','Indirect Incomes') and value(r,'GSTAPPLICABLE').casefold() in ('no','not applicable','notapplicable')] if catalog else [],
        'gst_enabled':bool(catalog and catalog.get('companies') and value(catalog['companies'][0],'ISGSTON').casefold()=='yes'),
        'posting_available':acceptance_enabled(),'tax_masters_available':bool(catalog and catalog.get('companies'))}

async def save_profile(db,principal,company_id,request):
    company=await drafts.company_for(db,principal,company_id)
    await db.refresh(company,with_for_update=True)
    row=await db.get(PurchaseTaxProfile,company_id,populate_existing=True,with_for_update=True)
    if request.revision!=(row.revision if row else 0):raise HTTPException(409,'GST setup changed; reload before saving.')
    if not request.ledgers or any(h not in gst.HEADS or not isinstance(label,str) or not 1<=len(label)<=200 for h,label in request.ledgers.items()):raise HTTPException(422,'Select exact supported tax ledgers.')
    if len(set(request.ledgers.values()))!=len(request.ledgers):raise HTTPException(422,'Each tax head needs its own ledger.')
    snapshot=await sync.saved_snapshot(db,company)
    if not snapshot:raise HTTPException(409,'Sync company masters first.')
    catalog=deserialize_catalog(snapshot.catalog)
    try:
        for h,label in request.ledgers.items():
            ledger=gst.exact(catalog['ledgers'],label)
            if value(ledger,'PARENT')!='Duties & Taxes' or value(ledger,'TAXTYPE').casefold()!='gst' or gst.tax_head(value(ledger,'GSTDUTYHEAD'))!=('SGST' if h=='UTGST' else h):raise TallyError('Tax ledger type/head mismatch.')
        if request.rounding_ledger:
            ledger=gst.exact(catalog['ledgers'],request.rounding_ledger)
            if value(ledger,'PARENT') not in ('Indirect Expenses','Indirect Incomes') or value(ledger,'GSTAPPLICABLE').casefold() not in ('no','not applicable','notapplicable'):raise TallyError('Non-taxable rounding ledger required.')
    except TallyError as exc:raise HTTPException(422,str(exc))
    data={'ledgers':request.ledgers,'rounding_ledger':request.rounding_ledger}
    if row:row.data=data;row.revision+=1
    else:row=PurchaseTaxProfile(company_id=company_id,data=data,revision=1);db.add(row)
    await db.commit();return await profile_view(db,principal,company_id)

async def ensure_approved_profile(db,action):
    row=await db.get(PurchaseTaxProfile,action.company_id,populate_existing=True)
    if not row or row.data!=action.payload.get('tax_profile') or row.revision!=(action.preconditions or {}).get('tax_profile_revision'):
        raise TallyError('Company GST setup changed; create a fresh preview.')

async def compile_draft(db,principal,row,content):
    company=await drafts.company_for(db,principal,row.company_id)
    config=await db.get(TallyConnection,principal.organization_id,populate_existing=True)
    if not config or config.company!=company.name or not config.test_company:raise TallyError('Configure the approved GST test company first.')
    profile=await db.get(PurchaseTaxProfile,row.company_id,populate_existing=True)
    if not profile:raise TallyError('Save company GST/rounding ledger setup first.')
    snapshot=await sync.saved_snapshot(db,company)
    if not snapshot:raise TallyError('Complete saved masters required.')
    catalog=deserialize_catalog(snapshot.catalog)
    payload=gst.compile_purchase(catalog,content.model_dump(mode='json'),profile.data,sync.config_data(config),str(uuid.uuid4()))
    return company,config,profile,payload

async def tax_check(db,principal,draft_id):
    row=await drafts.scoped_draft(db,principal,draft_id)
    try:
        company,config,profile,payload=await compile_draft(db,principal,row,drafts.DraftContent.model_validate(row.content))
        return {'supported':True,'tax_mode':payload['tax_mode'],'items':payload['items'],'tax_ledgers':payload['tax_ledgers'],'taxable_total':payload['taxable_total'],'round_off':payload['round_off'],'total':payload['total'],'posting_available':acceptance_enabled()}
    except (TallyError,ValueError,TypeError) as exc:raise HTTPException(422,str(exc))

async def preview_gst(db,principal,row,content):
    revision=row.revision
    try:
        company=await drafts.company_for(db,principal,row.company_id)
        try:await sync.refresh_company(db,company)
        except TallyError:pass
        company,config,profile,payload=await compile_draft(db,principal,row,content)
        prior=await db.scalars(select(TallyAction).where(TallyAction.company_id==company.id,TallyAction.status.in_(('submitting','verification_pending','needs_review'))))
        from app.services.tally_multi_purchase_service import action_lines
        affected={r['item'] for r in payload['items']}
        if any(sync.uncertain(a) and (a.backend=='mcp' or any(r.get('item') in affected for r in action_lines(a.payload))) for a in prior):raise TallyError('Resolve earlier uncertain item entries before another purchase.')
        await db.refresh(row,with_for_update=True)
        if row.revision!=revision:raise TallyError('Draft changed during tax-master refresh; reopen it.')
        device=await sync.bound_device(db,company);stamp=sync.now()
        action=TallyAction(token=secrets.token_hex(16),organization_id=principal.organization_id,user_id=principal.user_id,session_id=principal.session_id,
            company_id=company.id,device_version=device.credential_hash if device else None,connection_version=config.version,
            created_at=stamp,expires_at=stamp+timedelta(minutes=15),payload=payload,xml_payload=gst.gst_xml(payload),schema_version=3,
            target_identity={'company':company.identity},preconditions={'tax_profile_revision':profile.revision},status='preview',attempts=0)
        db.add(action);await drafts.attach_preview(db,principal,action,row);await db.commit()
        lines=[f'Company: {company.name}',f'Supplier: {payload["party"]} · {payload["supplier_gstin"]}',f'Invoice: {payload["invoice_number"]}',f'Date: {payload["date"]}',f'Tax mode: {payload["tax_mode"]}']
        lines.extend(f'{i+1}. {r["item"]}: taxable ₹{r["taxable"]}; discount ₹{r["discount"]}; GST {r["gst_rate"]}%' for i,r in enumerate(payload['items']))
        lines.extend(f'{r["head"]} → {r["ledger"]}: ₹{r["amount"]}' for r in payload['tax_ledgers'])
        lines.extend([f'Disclosed round-off: ₹{payload["round_off"]}',f'Grand total: ₹{payload["total"]}'])
        return {'draft_id':row.id,'response':'GST preview ready for review.' if acceptance_enabled() else 'GST calculation ready. Real Tally acceptance pending; posting locked.',
            'preview':{'token':action.token,'title':'Purchase · GST test company','can_confirm':acceptance_enabled(),'blockers':[] if acceptance_enabled() else ['Real GST Tally fixtures not yet verified.'],'lines':lines}}
    except (TallyError,ValueError,TypeError) as exc:return {'response':str(exc)}
