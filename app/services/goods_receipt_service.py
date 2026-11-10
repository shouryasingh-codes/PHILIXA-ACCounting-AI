"""Durable goods-received / bill-pending intake, separate from purchase invoices.

Native dispatch intentionally remains locked until tracked receipt + linked
invoice acceptance is certified. Never turn a missing invoice into a fake one.
"""
import copy
import re
import secrets
from datetime import datetime
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app.services import purchase_draft_service as drafts
from app.services.purchase_identity import exact_master
from app.services.tally_connector import TallyError,value

NO_BILL={'bill nahi hai','bill hai hi nahi','bill hai hi nhi','bill nahi','bill nhi hai','bill nhi','bill nahi mila',
         'bill abhi nahi mila','no bill','invoice nahi hai','बिल नहीं है','बिल नहीं मिला'}
BASIS={'GST alag lagega':'tax_exclusive','GST rate mein included hai':'tax_inclusive',
       'Supplier GST charge nahi kar raha':'no_gst_charged'}

def no_bill(text):return re.sub(r'[.!?]+$','',text.strip().casefold()) in NO_BILL

def receipt(row):return (row.extraction_metadata or {}).get('goods_receipt')

async def persist(db,principal,row,data,event):
    previous=await drafts.editable_action(db,row,row.revision)
    if previous and previous.status=='preview':previous.status='expired'
    row.action_id=None;row.revision+=1;row.updated_at=datetime.now(ZoneInfo('UTC'))
    row.extraction_metadata={**(row.extraction_metadata or {}),'goods_receipt':data}
    drafts.record_event(db,row,principal.user_id,event,{'goods_receipt':copy.deepcopy(data)})
    await db.commit()

async def begin(db,principal,row):
    if receipt(row):return
    if row.content.get('invoice_number') or row.document_id:
        raise HTTPException(409,'Is draft mein invoice/source hai. Pehle uska review karein; receipt mode silently switch nahi hoga.')
    from app.services.purchase_memory_service import catalog_for
    catalog=await catalog_for(db,await drafts.company_for(db,principal,row.company_id))
    try:
        exact_master(catalog,'supplier',row.content.get('party_name'))
        if not row.content.get('lines'):raise ValueError()
        for line in row.content['lines']:
            item=exact_master(catalog,'item',line.get('item_name'))
            if not line.get('unit') or value(item,'BASEUNITS')!=line['unit']:raise ValueError()
            for key in ('quantity','rate'):
                amount=Decimal(str(line.get(key)))
                if not amount.is_finite() or amount<=0:raise ValueError()
    except (TallyError,ValueError,InvalidOperation):
        raise HTTPException(422,'Receipt ke liye exact supplier/item aur confirmed quantity, unit, rate pehle chahiye.')
    await persist(db,principal,row,{'status':'bill_pending','tracking_reference':'PH-GRN-'+secrets.token_hex(12),
        'received_on':None,'rate_basis':None,'native_status':'not_posted'},'receipt_started')

def field_for(row):
    data=receipt(row)
    if not data.get('received_on'):return 'receipt:date'
    if not data.get('rate_basis'):return 'receipt:basis'
    return 'receipt:review'

async def state(db,principal,row,prefix=''):
    data=receipt(row);field=field_for(row);c=row.content
    company=await drafts.company_for(db,principal,row.company_id)
    summary=[prefix,f'{company.name} · Bill-pending receipt draft', 'Tally entry abhi nahi hui.', 'Supplier: '+(c.get('party_name') or 'pending')]
    summary += [f"{l.get('item_name') or 'Item'} · {l.get('quantity') or '?'} {l.get('unit') or ''} · rate ₹{l.get('rate') or '?'}" for l in c['lines']]
    choices=[]
    if field=='receipt:date':
        summary.append('Maal asal mein kis date ko mila? Jaise 01-11-2026. Aaj mila ho toh “Aaj mila” dabayein.');choices=['Aaj mila']
    elif field=='receipt:basis':
        summary.append('Is rate mein GST kaise hai? “GST alag” aur “GST lagta hi nahi” alag hain.');choices=list(BASIS)
    else:
        summary += ['Received: '+data['received_on'], 'Rate: '+next(k for k,v in BASIS.items() if v==data['rate_basis']),
                    'Receipt details saved hain. Receipt Note preview se posting availability aur details check karein. Stock abhi nahi badha.']
        choices=['Receipt Note preview']
    result={'response':'\n'.join(v for v in summary if v),'draft_id':row.id,'gst_purchase_draft':{'id':row.id},
        'purchase_assistant':{'draft_id':row.id,'revision':row.revision,'field':field,'choices':choices},
        'goods_receipt':{**data,'company':company.name,'posting_available':False},
        'purchase_details':['Invoice number/date aur GST credit invent nahi hue.',
            'Tracking reference: '+data['tracking_reference'],'Saved receipt hai; Tally voucher nahi.']}
    await db.commit();return result

async def answer(db,principal,row,request,catalog):
    if request.field!=field_for(row):raise HTTPException(409,'Receipt details changed. Current question reopen karein.')
    data=copy.deepcopy(receipt(row));text=(request.answer or '').strip()
    if text.casefold() in ('pause','stop','baad mein','ruk ja'):
        await db.commit()
        return {'response':'Bill-pending receipt saved hai; Tally entry nahi hui. Resume se continue kar sakte hain.',
            'draft_id':row.id,'purchase_resume':row.id,'goods_receipt':{**data,'posting_available':False}}
    if request.field=='receipt:date':
        today=datetime.now(ZoneInfo('Asia/Kolkata')).date()
        if text.casefold() in ('aaj mila','aaj','today'):stamp=today
        else:
            from app.services.invoice_extraction import parse_date
            if not re.fullmatch(r'(?:\d{4}-\d{2}-\d{2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4})',text):
                return await state(db,principal,row,'Date is format mein dein: 01-11-2026.')
            stamp=parse_date(text)
        if stamp is None or stamp>today or stamp.year<1900:return await state(db,principal,row,'Actual receipt date chahiye; future date nahi.')
        data['received_on']=stamp.isoformat()
    elif request.field=='receipt:basis':
        if text not in BASIS:return await state(db,principal,row,'Neeche exact rate option select karein; tax assume nahi karunga.')
        data['rate_basis']=BASIS[text]
    elif request.field=='receipt:review' and text=='Receipt Note preview':return await preview(db,principal,row,catalog)
    else:return await state(db,principal,row)
    try:
        exact_master(catalog,'supplier',row.content.get('party_name'))
        for line in row.content['lines']:exact_master(catalog,'item',line.get('item_name'))
    except TallyError as exc:raise HTTPException(409,str(exc))
    data['evidence']={**data.get('evidence',{}),request.field:{'message':text,'source':'user','revision':row.revision}}
    await persist(db,principal,row,data,'receipt_updated')
    return await state(db,principal,row)

async def preview(db,principal,row,catalog):
    import uuid
    from datetime import timedelta
    from app.models.tally import TallyConnection,TallyAction
    from app.services import tally_sync as sync,tally_goods_receipt as codec
    company=await drafts.company_for(db,principal,row.company_id)
    cfg=await db.get(TallyConnection,principal.organization_id)
    data=receipt(row)
    if not cfg or not cfg.test_company or cfg.company!=company.name:raise HTTPException(409,'Separate approved test company configure karein.')
    if field_for(row)!='receipt:review':raise HTTPException(422,'Receipt date/rate basis missing.')
    if data['rate_basis']=='tax_inclusive':raise HTTPException(422,'Tax-inclusive rate se stock valuation guess nahi karunga. Confirmed GST-exclusive valuation rate chahiye.')
    old=await drafts.editable_action(db,row,row.revision)
    if old and old.status=='preview':old.status='expired'
    p={'operation':'goods_receipt','company':company.name,'party':row.content['party_name'],
        'godown':cfg.godown,'ledger':cfg.purchase_ledger,'date':data['received_on'],'guid':str(uuid.uuid4()),
        'tracking':data['tracking_reference'],'items':[{'item':l['item_name'],'quantity':l['quantity'],'unit':l['unit'],'rate':l['rate']} for l in row.content['lines']], 'master_fingerprint':''}
    p['master_fingerprint']=codec.fingerprint(catalog,p);codec.validate(catalog,p,sync.config_data(cfg))
    device=await sync.bound_device(db,company);stamp=sync.now()
    blockers=[]
    if not codec.RECEIPT_CODEC_CERTIFIED:blockers.append('Native tracked-receipt + linked-invoice acceptance pending; posting locked.')
    if device:
        from app.core.redis import get_redis_client
        redis=await get_redis_client()
        try:
            if not await redis.exists('tally:v11online:'+device.id):blockers.append('Tracked Receipt Note ke liye protocol 11 connector update required.')
        finally:await redis.aclose()
    else:blockers.append('Paired protocol 11 Tally Connector required for receipt posting.')
    action=TallyAction(token=secrets.token_hex(16),organization_id=principal.organization_id,user_id=principal.user_id,
        session_id=principal.session_id,company_id=company.id,device_version=device.credential_hash if device else None,
        created_at=stamp,expires_at=stamp+timedelta(minutes=15),connection_version=cfg.version,payload=p,
        xml_payload=codec.receipt_xml(p),status='preview',attempts=0,schema_version=4,target_identity={'company':company.identity})
    db.add(action);await db.flush();row.action_id=action.token;row.revision+=1;row.updated_at=stamp
    row.extraction_metadata={**row.extraction_metadata,'goods_receipt':{**data,'receipt_action_id':action.token}}
    action.preconditions={'receipt_draft':{'id':row.id,'revision':row.revision}}
    drafts.record_event(db,row,principal.user_id,'receipt_preview',{'tracking':p['tracking'],'blockers':blockers})
    await db.commit()
    return {'response':'Receipt Note preview — abhi stock update nahi hua.','draft_id':row.id,
        'preview':{'token':action.token,'title':'Goods received · bill pending','can_confirm':not blockers,'send':False,'blockers':blockers,
            'lines':['Company: '+company.name,'Supplier: '+p['party'],'Received: '+p['date'],'Tracking: '+p['tracking'],
                *[f"{l['item']}: {l['quantity']} {l['unit']} × ₹{l['rate']}" for l in p['items']],
                'Inventory receipt only · no GST credit or supplier invoice created.']}}
