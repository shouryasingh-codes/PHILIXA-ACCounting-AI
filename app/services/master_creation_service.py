"""Revision-bound master previews and paired-device durable dispatch."""
import copy,hashlib,json,secrets,uuid
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from app.models.tally import TallyAction,TallyConnection
from app.services import purchase_draft_service as drafts,tally_sync as sync
from app.services.tally_connector import name,value,TallyError
from app.services.tally_sync_protocol import deserialize_catalog
from app.services.tally_master_actions import BASE,validate,verified,KINDS,xml

def digest(content):return hashlib.sha256(json.dumps(content,sort_keys=True,default=str).encode()).hexdigest()

async def guard(db,action):
    ref=(action.preconditions or {}).get('master_draft',{})
    from app.models.purchase_draft import PurchaseDraft
    row=await db.get(PurchaseDraft,ref.get('id'),populate_existing=True)
    if not row or row.organization_id!=action.organization_id or row.company_id!=action.company_id or row.user_id!=action.user_id or row.revision!=ref.get('revision') or row.action_id!=ref.get('action_id') or digest(row.content)!=ref.get('hash'):
        raise TallyError('Master source draft changed; create a fresh preview.')
    if row.document_id:
        from app.models.bill_document import BillDocument
        source=await db.get(BillDocument,row.document_id,populate_existing=True)
        if not source or source.trashed_at is not None:raise TallyError('Master source document unavailable; review required.')
    return row

def preview(action,ready=True):
    lines=[f"Company: {action.payload['company']}",'Create only; no purchase voucher, opening stock/balance or GST rate/HSN is being entered.']
    for m in action.payload['masters']:lines.append(m['kind']+': '+m['name']+' · '+json.dumps(m['fields'],ensure_ascii=False))
    lines.append('GST registration type, HSN and item tax rates are not inferred; configure/review those separately before purchase posting.')
    return {'token':action.token,'title':'Create missing Tally masters','can_confirm':ready,'blockers':[] if ready else ['Online protocol 12 connector required. Install a trusted supported connector update; no master write is enabled on this connection.'],'send':False,'lines':lines}

async def connector_ready(device):
    from app.core.redis import get_redis_client
    redis=await get_redis_client()
    try:return bool(await redis.exists('tally:v12online:'+device.id))
    finally:await redis.aclose()

async def prepare(db,principal,draft_id,create_supplier=True,create_items=True,unit_definitions=None,item_units=None):
    row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
    await drafts.editable_action(db,row,row.revision)
    company=await drafts.company_for(db,principal,row.company_id)
    # Serialize previews across all drafts targeting this native company.
    from app.models.tally import TallyReadCompany
    await db.scalar(select(TallyReadCompany.id).where(TallyReadCompany.id==company.id).with_for_update())
    cfg=await db.get(TallyConnection,principal.organization_id)
    if not cfg or not cfg.test_company or cfg.company!=company.name:raise HTTPException(409,'Approved test-company setup required.')
    device=await sync.bound_device(db,company)
    if not device:raise HTTPException(409,'Paired connector required; server-local Tally fallback is disabled for master creation.')
    ready=await connector_ready(device)
    snapshot=await sync.saved_snapshot(db,company)
    from app.services.purchase_native_context import fresh
    if not snapshot or not fresh(snapshot.collected_at):raise HTTPException(409,'Sync current Tally masters before preparing this review.')
    if create_items and item_units:
        updated_content=copy.deepcopy(row.content or {})
        applied={}
        for idx,line in enumerate(updated_content.get('lines') or []):
            if str(line.get('unit') or '').strip():
                continue
            chosen=str(item_units.get(str(idx)) or item_units.get(str(line.get('item_name') or '')) or '').strip()
            if chosen:
                if len(chosen)>50:raise HTTPException(422,'Unit name maximum 50 characters ho sakta hai.')
                line['unit']=chosen
                applied[str(idx)]=chosen
        if applied:
            row.content=updated_content
            row.revision+=1
            row.updated_at=sync.now()
            drafts.record_event(db,row,principal.user_id,'master_unit_selected',{'units':applied})
            await db.flush()
    cat=deserialize_catalog(snapshot.catalog);guid=str(uuid.uuid4());masters=[]
    def add(kind,label,fields):
        if any(m['kind']==kind and m['name']==label for m in masters):return
        matches=[r for r in cat[KINDS[kind]] if name(r).casefold()==label.casefold()]
        if matches:raise HTTPException(409,'Same-name master already exists; map/review it instead of creating: '+label)
        masters.append(dict(kind=kind,name=label,guid=str(uuid.uuid5(uuid.UUID(guid),kind+':'+label)),fields=fields))
    units={name(u) for u in cat['units']};definitions={}
    for definition in unit_definitions or []:
        if set(definition)!={'name','decimal_places','uqc'} or definition['name'] in definitions:raise HTTPException(422,'Explicit unique unit name, precision and UQC required.')
        definitions[definition['name']]=definition
    if create_items:
        for line in row.content.get('lines') or []:
            label=line.get('item_name');unit=line.get('unit')
            if not label or not unit:raise HTTPException(422,'Exact item name and unit required; no default Nos or OCR renaming.')
            matches=[r for r in cat['items'] if name(r).casefold()==label.casefold()]
            if matches:
                if len(matches)!=1 or name(matches[0])!=label or value(matches[0],'BASEUNITS')!=unit:raise HTTPException(409,'Existing item/unit conflict; map explicitly.')
                continue
            if unit not in units:
                d=definitions.get(unit)
                if not d:raise HTTPException(422,'New unit '+unit+' needs explicit decimal_places and UQC; supply unit settings for review.')
                add('UNIT',unit,{**BASE['UNIT'],'DECIMALPLACES':str(d['decimal_places']),'GSTREPUOM':d['uqc']});units.add(unit)
            add('STOCKITEM',label,{**BASE['STOCKITEM'],'BASEUNITS':unit})
    if create_supplier:
        supplier=row.content.get('party_name')
        if not supplier:raise HTTPException(422,'Exact supplier name required.')
        existing=[r for r in cat['ledgers'] if name(r).casefold()==supplier.casefold()]
        if existing:
            if len(existing)!=1 or name(existing[0])!=supplier or value(existing[0],'PARENT')!='Sundry Creditors':raise HTTPException(409,'Supplier ledger conflicts; map explicitly.')
        else:
            fields=dict(BASE['LEDGER'])
            if row.content.get('supplier_gstin'):fields['PARTYGSTIN']=row.content['supplier_gstin']
            add('LEDGER',supplier,fields)
    if not masters:return {'response':'Required names already exist in Tally. Continue purchase review; no masters created.','draft_id':row.id}
    payload=dict(operation='masters_create',company=company.name,guid=guid,masters=masters)
    try:validate(payload,sync.config_data(cfg),company.name)
    except (TallyError,ValueError) as exc:raise HTTPException(422,str(exc))
    ref=dict(id=row.id,revision=row.revision,hash=digest(row.content),action_id=row.action_id)
    pending=(await db.scalars(select(TallyAction).where(TallyAction.company_id==company.id,TallyAction.status.in_(('preview',*sync.ACTIVE,'needs_review'))))).all()
    for action in pending:
        if action.payload.get('operation')!='masters_create':continue
        if action.status=='preview' and action.expires_at<=sync.now():continue
        if action.user_id==principal.user_id and action.session_id==principal.session_id and (action.preconditions or {}).get('master_draft')==ref:
            wanted=[{k:m[k] for k in ('kind','name','fields')} for m in masters]
            saved=[{k:m[k] for k in ('kind','name','fields')} for m in action.payload['masters']]
            if wanted==saved:return {'response':'Existing master request retained; no duplicate action.','draft_id':row.id,'preview':preview(action,ready)} if action.status=='preview' else sync.action_result(action)
        raise HTTPException(409,'Resolve earlier master request in this company before creating another.')
    device=await sync.bound_device(db,company);stamp=sync.now()
    action=TallyAction(token=secrets.token_hex(16),organization_id=principal.organization_id,user_id=principal.user_id,session_id=principal.session_id,company_id=company.id,
        connection_version=cfg.version,device_version=device.credential_hash,created_at=stamp,expires_at=stamp+timedelta(minutes=15),payload=payload,xml_payload=xml(payload),
        status='preview',attempts=0,backend='python',schema_version=5,target_identity={'company':company.identity},preconditions={'master_draft':ref})
    db.add(action);await db.commit()
    return {'response':'Missing masters ka preview ready hai. Confirm ke pehle Tally mein kuch create nahi hua.' if ready else 'Master preview saved hai. Trusted protocol 12 connector update required; abhi master creation blocked hai.','draft_id':row.id,'preview':preview(action,ready)}

async def process(db,action,company,cfg):
    if not company.device_id or action.approved_arguments!=action.payload or action.target_identity!={'company':company.identity}:raise TallyError('Approved master identity changed.')
    # After uncertain submission only reconcile; never turn an edit into a resend.
    if action.status=='queued':await guard(db,action)
    params=dict(payload=action.payload,config=sync.config_data(cfg),action_id=action.token)
    if action.status=='queued':
        result=await sync.operation(db,company,'masters_validate',**params)
        if result.get('status')=='ready':
            await db.refresh(action,with_for_update=True)
            if action.status!='queued':return
            await guard(db,action)
            action.status='submitting';await db.commit()
            result=await sync.operation(db,company,'masters_post',**params)
    else:result=await sync.operation(db,company,'masters_reconcile',**params)
    await db.refresh(action,with_for_update=True)
    if action.status not in sync.ACTIVE:return
    if result.get('status')=='verified':
        snapshot=await sync.capture_snapshot(db,company);cat=deserialize_catalog(snapshot['catalog'])
        for m in action.payload['masters']:
            rows=[r for r in cat[KINDS[m['kind']]] if name(r).casefold()==m['name'].casefold()]
            if len(rows)!=1 or not verified(rows[0],m):raise TallyError('Fresh snapshot master verification mismatch.')
        await sync.publish_snapshot(db,company,snapshot)
        action.status='verified';action.verification_result=result;action.result={'response':'Approved Tally masters created aur native snapshot se verified. Purchase voucher abhi create nahi hua; purchase review continue karein.'}
    elif result.get('status') in ('failed','needs_review'):
        action.status=result['status'];action.result={'response':result.get('reason','Master review required.'),'uncertain':action.status!='failed'}
    else:action.status='verification_pending';action.result={'response':'Master creation verification pending; same action reconcile hogi, dobara import nahi.'}
    await db.commit()
