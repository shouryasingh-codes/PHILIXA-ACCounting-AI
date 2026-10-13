"""Physical count drafts and typed reconciliation. No model-generated vouchers."""
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from xml.etree import ElementTree as ET
from app.services.tally_connector import TallyError, TallyRejected, value, name, decimal, quantity, stock_row, tag
from app.services.tally_validation import safe_catalog, validate_item

# Flip only after an installed-version manual export and actual report acceptance
# have been checked in and reviewed. Unproven XML must never write accounting data.
COUNT_CODEC_CERTIFIED = False

COUNT_UNAVAILABLE = ('Actual stock count correction abhi available nahi hai: Tally Physical Stock '
                     'voucher aur resulting stock ki verification pending hai. '
                     'Is request se Tally stock change nahi hua. Ye connection ki problem nahi hai.')

def count_capability():
    return {'available': COUNT_CODEC_CERTIFIED,
            'code': None if COUNT_CODEC_CERTIFIED else 'physical_stock_acceptance_pending',
            'reason': None if COUNT_CODEC_CERTIFIED else COUNT_UNAVAILABLE}

def is_count(action):
    return action.payload.get('operation') == 'stock_count_set'

def count_xml(p):
    root=ET.Element('ENVELOPE');tag(tag(root,'HEADER'),'TALLYREQUEST','Import Data')
    body=tag(tag(root,'BODY'),'IMPORTDATA');desc=tag(body,'REQUESTDESC')
    tag(desc,'REPORTNAME','Vouchers');tag(tag(desc,'STATICVARIABLES'),'SVCURRENTCOMPANY',p['company'])
    v=tag(tag(tag(body,'REQUESTDATA'),'TALLYMESSAGE'),'VOUCHER',REMOTEID=p['guid'],VCHTYPE='Physical Stock',ACTION='Create')
    for k,t in {'DATE':p['date'].replace('-',''),'GUID':p['guid'],'VOUCHERTYPENAME':'Physical Stock',
                'NARRATION':'Philixa count '+p['guid'],'REFERENCE':p['guid'],'ISINVOICE':'No',
                'PERSISTEDVIEW':'Invoice Voucher View','DIFFACTUALQTY':'Yes'}.items():tag(v,k,t)
    i=tag(v,'ALLINVENTORYENTRIES.LIST');tag(i,'STOCKITEMNAME',p['item']);tag(i,'ISDEEMEDPOSITIVE','Yes');tag(i,'ACTUALQTY',p['target_quantity']+' '+p['unit'])
    b=tag(i,'BATCHALLOCATIONS.LIST');tag(b,'GODOWNNAME',p['godown']);tag(b,'BATCHNAME','Primary Batch');tag(b,'ACTUALQTY',p['target_quantity']+' '+p['unit'])
    return ET.tostring(root,encoding='unicode')

def count_matches(v,p):
    return (value(v,'GUID')==p['guid'] or
            value(v,'NARRATION')=='Philixa count '+p['guid'] and
            (value(v,'REFERENCE')==p['guid'] or v.get('REMOTEID')==p['guid']))

def verify_count(v,p):
    if not count_matches(v,p) or any(value(v,k).casefold()=='yes' for k in ('ISCANCELLED','ISOPTIONAL')):return False
    if value(v,'DATE')!=p['date'].replace('-','') or value(v,'VOUCHERTYPENAME')!='Physical Stock':return False
    if value(v,'DIFFACTUALQTY').casefold()!='yes':return False
    rows=v.findall('ALLINVENTORYENTRIES.LIST')
    if len(rows)!=1:return False
    i=rows[0];b=i.findall('BATCHALLOCATIONS.LIST')
    try:return (value(i,'STOCKITEMNAME')==p['item'] and quantity(value(i,'ACTUALQTY'),p['unit'])==decimal(p['target_quantity'])
                and len(b)==1 and value(b[0],'GODOWNNAME')==p['godown'] and value(b[0],'BATCHNAME')=='Primary Batch'
                and quantity(value(b[0],'ACTUALQTY'),p['unit'])==decimal(p['target_quantity']))
    except TallyError:return False

def validate_count(catalog,p,config):
    expected={'operation','company','item','unit','godown','target_quantity','counted_at','reason','date','guid','baseline','revision'}
    if set(p)!=expected or p['operation']!='stock_count_set' or any(not isinstance(v,str) or len(v)>2000 for v in p.values()):raise TallyError('Invalid count payload.')
    if set(config)!={'company','godown','purchase_ledger','sales_ledger','test_company'}:raise TallyError('Invalid configuration.')
    from types import SimpleNamespace
    safe_catalog(catalog,SimpleNamespace(**config))
    if p['company']!=config['company'] or p['godown']!=config['godown']:raise TallyError('Count configuration changed.')
    stamp=datetime.fromisoformat(p['counted_at']);today=datetime.now(ZoneInfo('Asia/Kolkata')).date()
    if not stamp.tzinfo or stamp.astimezone(ZoneInfo('Asia/Kolkata')).date()!=today or p['date']!=today.isoformat():raise TallyError('Count date expired/backdated. Fresh count required.')
    if stamp>datetime.now(ZoneInfo('Asia/Kolkata')):raise TallyError('Future count time unsupported.')
    if not p['reason'].strip():raise TallyError('Count correction reason required.')
    uuid.UUID(p['guid']);qty=decimal(p['target_quantity'])
    items=[i for i in catalog['items'] if name(i)==p['item']]
    if len(items)!=1:raise TallyError('Count item missing/ambiguous.')
    unit=validate_item(catalog,items[0],p['unit']);places=value(unit,'DECIMALPLACES')
    if not places.isdigit() or not 0<=int(places)<=6 or qty<0 or qty!=qty.quantize(Decimal(1).scaleb(-int(places))):raise TallyError('Invalid actual count precision.')

async def baseline(connector,company,p,exclude_own=False):
    catalog=await connector.catalog(company)
    rows=await connector.collection('StockItem',company,p['date'])
    items=[r for r in rows if name(r)==p['item']]
    if len(items)!=1:raise TallyError('Count item missing/ambiguous.')
    stock=stock_row(items[0],catalog['units'])
    if stock['quantity'] is None:raise TallyError('Simple stock quantity required.')
    # Whole-company revision is conservative, including same-quantity edits.
    vouchers=await connector.collection('Voucher',company)
    fields=('GUID','BASEUNITS','ADDITIONALUNITS','ISBATCHWISEON','DECIMALPLACES','PARENT')
    data={'catalog':{k:[{'name':name(x),**{f:value(x,f) for f in fields}} for x in catalog[k]] for k in ('items','units','ledgers','godowns')},
          'vouchers':sorted(ET.tostring(v,encoding='unicode') for v in vouchers if not (exclude_own and count_matches(v,p)))}
    revision=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    return catalog,stock['quantity'],revision

async def execute_count(operation,connector,company,identity,p,config,journal_path):
    from app.services.tally_sync_protocol import journal
    if not isinstance(p,dict) or p.get('company')!=company:raise TallyError('Invalid count company.')
    if not COUNT_CODEC_CERTIFIED:return {'status':'blocked','reason':COUNT_UNAVAILABLE,'code':'physical_stock_acceptance_pending'}
    # Unbilled inventory must be explicitly proved disabled, never inferred.
    companies=await connector.collection('Company')
    c=next((x for x in companies if name(x)==company),None)
    if c is None or value(c,'ISDELIVERYNOTE').casefold()!='no':return {'status':'blocked','reason':'Receipt/delivery tracking capability not verified.'}
    vouchers=await connector.collection('Voucher',company,p['date'])
    found=[v for v in vouchers if count_matches(v,p)]
    if found:
        if len(found)!=1 or not verify_count(found[0],p) or not value(found[0],'VOUCHERNUMBER'):return {'status':'needs_review','uncertain':True}
        _,qty,revision=await baseline(connector,company,p,exclude_own=True)
        if decimal(qty)!=decimal(p['target_quantity']) or revision!=p['revision']:return {'status':'needs_review','uncertain':True}
        return {'status':'verified','voucher_number':value(found[0],'VOUCHERNUMBER')}
    if operation=='stock_count_reconcile':return {'status':'verification_pending'}
    catalog,qty,revision=await baseline(connector,company,p);validate_count(catalog,p,config)
    if operation=='stock_count_validate':return {'status':'ready','baseline':qty,'revision':revision}
    if p['revision']!=revision or decimal(p['baseline'])!=decimal(qty):return {'status':'needs_review','uncertain':False,'reason':'Live baseline changed; fresh confirmation required.'}
    with journal(journal_path) as db:
        inserted=db.execute('INSERT OR IGNORE INTO writes VALUES (?,?)',(identity+':'+p['guid'],'submitting')).rowcount
    if not inserted:return {'status':'verification_pending'}
    try:await connector.post(count_xml(p))
    except TallyRejected as exc:return {'status':'failed','reason':str(exc)[:300]}
    except TallyError:return {'status':'verification_pending'}
    return await execute_count('stock_count_reconcile',connector,company,identity,p,config,journal_path)

async def create_draft(db,principal,parsed):
    from fastapi import HTTPException
    from sqlalchemy import select
    from app.models.tally import TallyAction,TallyConnection,TallyReadCompany
    from app.services.tally_business import admin,fields_for_selection
    from app.services.tally_stock import resolve_scope
    from app.services.tally_sync import now,bound_device
    admin(principal)
    if parsed.unsupported_reason:return {'response':parsed.unsupported_reason}
    if not COUNT_CODEC_CERTIFIED:
        return {'response':COUNT_UNAVAILABLE,'count_capability':count_capability()}
    companies=await resolve_scope(db,principal,parsed)
    if not parsed.company_id:
        return {'response':'Actual count kis company ka hai? Company confirm karein.','tally_choices':[
            {'name':c.name,'command':fields_for_selection(parsed,'company_id',c.id)} for c in companies]}
    if len(companies)!=1:raise HTTPException(404,'Permitted company unavailable.')
    c=companies[0];cfg=await db.get(TallyConnection,principal.organization_id)
    if not cfg or not cfg.test_company or cfg.company!=c.name:return {'response':'Count correction sirf configured non-GST test company mein supported hai.'}
    if any(getattr(parsed,k) is None or getattr(parsed,k)=='' for k in ('item_name','target_quantity','unit','counted_at','reason')):
        return {'response':'Actual final count, item, unit, count time aur reason bataiye.','tally_form':{'intent':'stock_count_set','fields':parsed.model_dump(mode='json',exclude={'intent'})}}
    from app.services.tally_sync import saved_snapshot
    from app.services.tally_sync_protocol import deserialize_catalog
    snapshot=await saved_snapshot(db,c)
    if not snapshot:return {'response':'Complete saved masters required. Pehle company sync karein.'}
    catalog=deserialize_catalog(snapshot.catalog)
    from app.services.tally_validation import match
    items=match(catalog['items'],parsed.item_name)
    if len(items)!=1:return {'response':'Canonical item choose karein.','tally_choices':[{'name':name(i),'command':fields_for_selection(parsed,'item_name',name(i))} for i in items]}
    p={'operation':'stock_count_set','company':c.name,'item':name(items[0]),'unit':parsed.unit,'godown':cfg.godown,
       'target_quantity':str(parsed.target_quantity),'counted_at':parsed.counted_at.isoformat(),'reason':parsed.reason,
       'date':parsed.counted_at.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat(),'guid':str(uuid.uuid4()),'baseline':'','revision':''}
    try:validate_count(catalog,p,{'company':cfg.company,'godown':cfg.godown,'purchase_ledger':cfg.purchase_ledger,'sales_ledger':cfg.sales_ledger,'test_company':cfg.test_company})
    except (TallyError,ValueError) as exc:return {'response':str(exc)}
    device=await bound_device(db,c);stamp=now()
    a=TallyAction(token=secrets.token_hex(16),organization_id=principal.organization_id,user_id=principal.user_id,session_id=principal.session_id,
        company_id=c.id,device_version=device.credential_hash if device else None,created_at=stamp,expires_at=stamp+timedelta(minutes=15),
        connection_version=cfg.version,payload=p,xml_payload='',status='draft',attempts=0)
    db.add(a);await db.commit()
    from app.services.tally_sync import action_result
    return action_result(a)

async def review(db,principal,a):
    from fastapi import HTTPException
    from sqlalchemy import select
    from app.models.tally import TallyAction,TallyConnection,TallyReadCompany
    from app.services.tally_business import admin
    from app.services.tally_sync import now,bound_device,operation,config_data,company_lock
    admin(principal)
    if (a.organization_id,a.user_id,a.session_id)!=(principal.organization_id,principal.user_id,principal.session_id) or not is_count(a):raise HTTPException(404,'Count draft unavailable.')
    if a.status not in ('draft','awaiting_review','preview','needs_review'):raise HTTPException(409,'Count already submitted or closed.')
    if (a.result or {}).get('uncertain'):raise HTTPException(409,'Uncertain submission needs manual review; no replacement.')
    if not COUNT_CODEC_CERTIFIED:
        from app.services.tally_sync import action_result
        return action_result(a)
    c=await db.get(TallyReadCompany,a.company_id);cfg=await db.get(TallyConnection,principal.organization_id)
    if not c or c.organization_id!=principal.organization_id or not cfg or cfg.version!=a.connection_version:raise HTTPException(409,'Company/configuration changed.')
    device=await bound_device(db,c)
    if (device.credential_hash if device else None)!=a.device_version:raise HTTPException(409,'Helper changed; draft invalid.')
    async with company_lock(c.id) as locked:
        if not locked:raise HTTPException(409,'Company busy; retry review.')
        pending=list((await db.scalars(select(TallyAction).where(TallyAction.company_id==c.id,TallyAction.status.in_(('queued','submitting','verification_pending','needs_review'))))).all())
        if any(x.token!=a.token and x.payload.get('item')==a.payload['item'] and (x.status!='needs_review' or (x.result or {}).get('uncertain')) for x in pending):raise HTTPException(409,'Earlier item entries must settle before correction.')
        reply=await operation(db,c,'stock_count_validate',payload=a.payload,config=config_data(cfg),action_id=a.token)
        if reply.get('status')!='ready':return {'response':reply.get('reason','Count capability needs review.'),'tally_action':a.token,'sync_status':a.status}
        await db.refresh(a,with_for_update=True)
        if a.status not in ('draft','awaiting_review','preview','needs_review'):raise HTTPException(409,'Draft changed.')
        a.payload={**a.payload,'baseline':reply['baseline'],'revision':reply['revision']};a.xml_payload=count_xml(a.payload)
        a.status='preview';a.expires_at=now()+timedelta(minutes=15);a.result=None;await db.commit()
    p=a.payload
    return {'response':'Live count preview check karein. Confirm ke baad hi Tally mein correction hogi.',
      'preview':{'token':a.token,'title':'Actual stock count — test company','can_confirm':True,'blockers':[],'send':False,
      'lines':[f'Company: {p["company"]}',f'Item: {p["item"]}',f'Godown: {p["godown"]}',f'Live book stock: {p["baseline"]} {p["unit"]}',
               f'Actual counted: {p["target_quantity"]} {p["unit"]}',f'Difference: {decimal(p["target_quantity"])-decimal(p["baseline"])} {p["unit"]}',
               f'Count time: {p["counted_at"]}',f'Reason: {p["reason"]}']}}
