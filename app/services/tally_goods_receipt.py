"""Tracked inventory receipts. Shared codec; never infer invoices or GST credit."""
import hashlib,json,uuid
from datetime import date,datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from xml.etree import ElementTree as ET
from app.services.tally_connector import TallyError,TallyRejected,decimal,name,value,tag,quantity
from app.services.purchase_identity import exact_master
from app.services.tally_validation import validate_item,uses_cost_centres

# 2026-11-02 native test-company proofs: automatic Receipt Note 2 and
# Receipt Note 1 -> GST purchase 23, with invoice stock delta zero.
# Supported scope remains simple units, one godown, full receipt linkage.
RECEIPT_CODEC_CERTIFIED=True

def fingerprint(catalog,p):
    from app.services.tally_sync_protocol import fingerprint as relevant_fingerprint
    # Stock movement/last purchase metadata must not invalidate its own receipt.
    return hashlib.sha256(json.dumps([relevant_fingerprint(catalog,{**p,**line}) for line in p['items']]).encode()).hexdigest()

def validate(catalog,p,config):
    keys={'operation','company','party','godown','ledger','date','guid','tracking','items','master_fingerprint'}
    if not isinstance(p,dict) or set(p)!=keys or p['operation']!='goods_receipt':raise TallyError('Invalid receipt payload.')
    if any(not isinstance(p[k],str) or not p[k] or len(p[k])>250 for k in keys-{'items'}):raise TallyError('Invalid receipt header.')
    uuid.UUID(p['guid'])
    if not p['tracking'].startswith('PH-GRN-') or len(p['tracking'])>80:raise TallyError('Invalid receipt tracking.')
    if date.fromisoformat(p['date'])>datetime.now(ZoneInfo('Asia/Kolkata')).date():raise TallyError('Future receipt unsupported.')
    if not config or config.get('test_company') is not True or any(p[k]!=config.get(c) for k,c in [('company','company'),('godown','godown'),('ledger','purchase_ledger')]):
        raise TallyError('Explicit configured test company required.')
    party=exact_master(catalog,'supplier',p['party'])
    ledger=[r for r in catalog['ledgers'] if name(r)==p['ledger']]
    if len(ledger)!=1 or value(ledger[0],'PARENT')!='Purchase Accounts' or uses_cost_centres(catalog,ledger[0]) or uses_cost_centres(catalog,party):raise TallyError('Unsupported receipt ledger/cost centres.')
    if len(catalog['godowns'])!=1 or name(catalog['godowns'][0])!=p['godown']:raise TallyError('Single approved godown required.')
    if not isinstance(p['items'],list) or not 1<=len(p['items'])<=100:raise TallyError('Receipt requires 1–100 lines.')
    seen=set()
    for line in p['items']:
        if not isinstance(line,dict) or set(line)!={'item','unit','quantity','rate'} or any(not isinstance(v,str) or len(v)>250 for v in line.values()):raise TallyError('Invalid receipt line.')
        if line['item'] in seen:raise TallyError('Repeated receipt item unsupported.')
        seen.add(line['item'])
        unit=validate_item(catalog,exact_master(catalog,'item',line['item']),line['unit'])
        places=value(unit,'DECIMALPLACES');qty=decimal(line['quantity']);rate=decimal(line['rate'])
        if not places.isdigit() or not 0<=int(places)<=6 or not 0<qty<Decimal('1000000') or not 0<rate<Decimal('10000000000') or rate!=rate.quantize(Decimal('.01')) or qty!=qty.quantize(Decimal(1).scaleb(-int(places))):raise TallyError('Invalid receipt precision.')
    if fingerprint(catalog,p)!=p['master_fingerprint']:raise TallyError('Receipt masters changed; review again.')

def receipt_xml(p):
    root=ET.Element('ENVELOPE');tag(tag(root,'HEADER'),'TALLYREQUEST','Import Data')
    body=tag(tag(root,'BODY'),'IMPORTDATA');desc=tag(body,'REQUESTDESC');tag(desc,'REPORTNAME','Vouchers')
    tag(tag(desc,'STATICVARIABLES'),'SVCURRENTCOMPANY',p['company'])
    v=tag(tag(tag(body,'REQUESTDATA'),'TALLYMESSAGE'),'VOUCHER',REMOTEID=p['guid'],VCHTYPE='Receipt Note',ACTION='Create',OBJVIEW='Invoice Voucher View')
    for k,val in {'DATE':p['date'].replace('-',''),'GUID':p['guid'],'VOUCHERTYPENAME':'Receipt Note',
        'PARTYLEDGERNAME':p['party'],'PERSISTEDVIEW':'Invoice Voucher View','ISINVOICE':'No',
        'VOUCHERNUMBER':p['tracking'],'REFERENCE':p['tracking'],'NARRATION':'Philixa goods receipt '+p['guid']+'; supplier bill pending'}.items():tag(v,k,val)
    total=sum(((decimal(l['quantity'])*decimal(l['rate'])).quantize(Decimal('.01')) for l in p['items']),Decimal('0.00'))
    # Native Receipt Notes contain notional balancing ledger allocations. Their
    # voucher type/tracking determines inventory-only effect, not absent rows.
    party=tag(v,'LEDGERENTRIES.LIST')
    for k,val in [('LEDGERNAME',p['party']),('ISDEEMEDPOSITIVE','No'),('ISPARTYLEDGER','Yes'),('AMOUNT',total)]:tag(party,k,val)
    for line in p['items']:
        item=tag(v,'ALLINVENTORYENTRIES.LIST');qty=line['quantity']+' '+line['unit']
        amount=-(decimal(line['quantity'])*decimal(line['rate'])).quantize(Decimal('.01'))
        for k,val in [('STOCKITEMNAME',line['item']),('ISDEEMEDPOSITIVE','Yes'),('RATE',line['rate']+'/'+line['unit']),('ACTUALQTY',qty),('BILLEDQTY',qty),('AMOUNT',amount)]:tag(item,k,val)
        batch=tag(item,'BATCHALLOCATIONS.LIST')
        for k,val in [('GODOWNNAME',p['godown']),('BATCHNAME','Primary Batch'),('TRACKINGNUMBER',p['tracking']),('ORDERNO','Not Applicable'),('ACTUALQTY',qty),('BILLEDQTY',qty),('AMOUNT',amount)]:tag(batch,k,val)
        allocation=tag(item,'ACCOUNTINGALLOCATIONS.LIST')
        for k,val in [('LEDGERNAME',p['ledger']),('ISDEEMEDPOSITIVE','Yes'),('AMOUNT',amount)]:tag(allocation,k,val)
    return ET.tostring(root,encoding='unicode')

def identity_matches(v,p):
    return value(v,'GUID')==p['guid'] or (value(v,'REFERENCE')==p['tracking'] and (value(v,'REMOTEID')==p['guid'] or value(v,'NARRATION').startswith('Philixa goods receipt '+p['guid']+';')))

def verify(v,p):
    if not identity_matches(v,p) or any(value(v,k)!=val for k,val in {'DATE':p['date'].replace('-',''),'VOUCHERTYPENAME':'Receipt Note','PARTYLEDGERNAME':p['party'],'REFERENCE':p['tracking']}.items()):return False
    if any(value(v,k).casefold()=='yes' for k in ('ISCANCELLED','ISOPTIONAL')):return False
    lines=v.findall('ALLINVENTORYENTRIES.LIST')
    if len(lines)!=len(p['items']):return False
    try:
        if value(v,'ISINVOICE').casefold()!='no':return False
        total=sum(((decimal(l['quantity'])*decimal(l['rate'])).quantize(Decimal('.01')) for l in p['items']),Decimal('0.00'))
        ledger_rows=v.findall('ALLLEDGERENTRIES.LIST') or v.findall('LEDGERENTRIES.LIST')
        parties=[r for r in ledger_rows if value(r,'LEDGERNAME')==p['party']]
        if len(parties)!=1 or decimal(value(parties[0],'AMOUNT'))!=total:return False
        purchase=[r for r in ledger_rows if value(r,'LEDGERNAME')==p['ledger']]
        if len(purchase)>1 or (purchase and decimal(value(purchase[0],'AMOUNT'))!=-total):return False
        if any(value(r,'LEDGERNAME') not in (p['party'],p['ledger']) for r in ledger_rows):return False
        for expected in p['items']:
            matched=[r for r in lines if value(r,'STOCKITEMNAME')==expected['item']]
            if len(matched)!=1:return False
            line=matched[0];batch=line.findall('BATCHALLOCATIONS.LIST');alloc=line.findall('ACCOUNTINGALLOCATIONS.LIST')
            amount=-(decimal(expected['quantity'])*decimal(expected['rate'])).quantize(Decimal('.01'))
            if len(batch)!=1 or len(alloc)!=1:return False
            if any(value(batch[0],k)!=val for k,val in [('TRACKINGNUMBER',p['tracking']),('GODOWNNAME',p['godown']),('BATCHNAME','Primary Batch')]):return False
            if value(alloc[0],'LEDGERNAME')!=p['ledger'] or decimal(value(alloc[0],'AMOUNT'))!=amount:return False
            if value(line,'RATE')!=expected['rate']+'/'+expected['unit']:return False
            for r in (line,batch[0]):
                if quantity(value(r,'ACTUALQTY'),expected['unit'])!=decimal(expected['quantity']) or quantity(value(r,'BILLEDQTY'),expected['unit'])!=decimal(expected['quantity']) or decimal(value(r,'AMOUNT'))!=amount:return False
        return True
    except (TallyError,ValueError,TypeError):return False

async def execute(operation,connector,company,identity,p,config,journal_path):
    from app.services.tally_sync_protocol import journal
    if not isinstance(p,dict) or p.get('company')!=company:raise TallyError('Receipt company mismatch.')
    if operation not in ('goods_receipt_validate','goods_receipt_post','goods_receipt_reconcile'):raise TallyError('Unsupported receipt operation.')
    vouchers=await connector.collection('Voucher',company,p['date'],from_date=p['date'])
    if len(vouchers)>5000:raise TallyError('Receipt read coverage exceeded.')
    found=[v for v in vouchers if identity_matches(v,p)]
    if found:
        if len(found)!=1 or not verify(found[0],p) or not value(found[0],'VOUCHERNUMBER'):return {'status':'needs_review','uncertain':True,'reason':'Native receipt/tracking mismatch.'}
        return {'status':'verified','voucher_number':value(found[0],'VOUCHERNUMBER'),'tracking':p['tracking']}
    if operation=='goods_receipt_reconcile':return {'status':'verification_pending'}
    if not RECEIPT_CODEC_CERTIFIED:return {'status':'needs_review','uncertain':False,'reason':'Native tracked-receipt acceptance pending.'}
    types=await connector.collection('VoucherType',company)
    active=[r for r in types if name(r)=='Receipt Note' and value(r,'ISACTIVE').casefold()=='yes']
    if len(active)!=1:return {'status':'needs_review','uncertain':False,'reason':'Receipt Note voucher type inactive/missing. Tally mein activate karke fresh preview karein.'}
    validate(await connector.catalog(company),p,config)
    if any(value(v,'REFERENCE')==p['tracking'] or any(value(b,'TRACKINGNUMBER')==p['tracking'] for b in v.findall('.//BATCHALLOCATIONS.LIST')) for v in vouchers):return {'status':'needs_review','uncertain':False,'reason':'Receipt tracking already exists under another action.'}
    if operation=='goods_receipt_validate':return {'status':'ready'}
    with journal(journal_path) as db:
        inserted=db.execute('INSERT OR IGNORE INTO writes VALUES (?,?)',(identity+':'+p['guid'],'submitting')).rowcount
        previous=db.execute('SELECT status FROM writes WHERE key=?',(identity+':'+p['guid'],)).fetchone()[0]
    if not inserted:return {'status':'failed','reason':'Earlier receipt import explicitly rejected; create a fresh reviewed preview.'} if previous=='rejected' else {'status':'verification_pending'}
    try:
        imported=await connector.post(receipt_xml(p))
        # Tally can return EXCEPTIONS:1 without LINEERROR/ERRORS. Zero-created
        # is an explicit failed import, not proof that a receipt was saved.
        if imported is not None and value(imported,'CREATED')=='0' and value(imported,'ALTERED') in ('','0') and (decimal(value(imported,'EXCEPTIONS') or '0')>0 or decimal(value(imported,'ERRORS') or '0')>0):
            with journal(journal_path) as db:db.execute('UPDATE writes SET status=? WHERE key=?',('rejected',identity+':'+p['guid']))
            return {'status':'failed','reason':'Tally import created zero vouchers; exception reported. Check Receipt Note activation/configuration.'}
    except TallyRejected as exc:return {'status':'failed','reason':str(exc)[:300]}
    except TallyError:return {'status':'verification_pending'}
    return await execute('goods_receipt_reconcile',connector,company,identity,p,config,journal_path)
