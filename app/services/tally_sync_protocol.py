"""Typed Tally operations shared with the helper. No database/provider imports."""
import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from app.services.tally_connector import (TallyConnector, TallyError, TallyRejected,
    company_identity, decimal, name, value, stock_row, voucher_xml, verify_voucher, parse_xml, matches_action)
from app.services.tally_validation import safe_catalog, validate_item, uses_cost_centres, match

PROTOCOL_VERSION = 8
OPERATIONS = ('discover', 'stock', 'snapshot_start', 'snapshot_page', 'purchase_validate', 'purchase_post', 'purchase_reconcile', 'stock_count_validate', 'stock_count_post', 'stock_count_reconcile', 'mcp_read', 'mcp_compile', 'customer_ledger_validate', 'customer_ledger_post', 'customer_ledger_reconcile')
OPERATIONS += ('purchase_gst_validate','purchase_gst_post','purchase_gst_reconcile')
OPERATIONS += ('purchase_multi_validate','purchase_multi_post','purchase_multi_reconcile')

def fingerprint(catalog, payload):
    """Only relevant master rules; changing stock does not invalidate purchases."""
    selected = {}
    rules = {
        'items': ('item', ('GUID','BASEUNITS','ADDITIONALUNITS','ISBATCHWISEON','ISPERISHABLEON','HASMFGDATE','ISADDLCOSTTRACKINGON','ISSERIALNUMBERON')),
        'units': ('unit', ('GUID','ISSIMPLEUNIT','DECIMALPLACES')),
        'godowns': ('godown', ('GUID',)),
        'ledgers': ('party', ('GUID','PARENT','ISCOSTCENTRESON','ISBILLWISEON')),
    }
    for kind, (field, flags) in rules.items():
        rows = [r for r in catalog[kind] if name(r) == payload[field]]
        if len(rows) != 1: raise TallyError('Master missing/ambiguous; needs review.')
        selected[kind] = {f: value(rows[0], f) for f in flags}
    ledgers = [r for r in catalog['ledgers'] if name(r) == payload['ledger']]
    if len(ledgers) != 1: raise TallyError('Purchase ledger missing.')
    selected['purchase'] = {f: value(ledgers[0], f) for f in ('GUID','PARENT','ISCOSTCENTRESON')}
    selected['flags'] = [catalog['non_gst'], catalog['cost_centres_enabled'], sorted(name(g) for g in catalog['godowns'])]
    return hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()

def validate_purchase(catalog, p, config):
    expected = {'company','godown','party','item','quantity','unit','rate','total','voucher_type','ledger','date','guid','stock_before','master_fingerprint'}
    if set(p) != expected or p['voucher_type'] != 'Purchase': raise TallyError('Invalid purchase payload.')
    if any(not isinstance(v,str) or len(v)>2000 for v in p.values()): raise TallyError('Invalid purchase fields.')
    if set(config) != {'company','godown','purchase_ledger','sales_ledger','test_company'} or config['test_company'] is not True:
        raise TallyError('Test company authorization required.')
    cfg = SimpleNamespace(**config)
    safe_catalog(catalog, cfg)
    if p['company'] != cfg.company or p['godown'] != cfg.godown or p['ledger'] != cfg.purchase_ledger:
        raise TallyError('Purchase configuration changed; needs review.')
    if date.fromisoformat(p['date']) > datetime.now(ZoneInfo('Asia/Kolkata')).date(): raise TallyError('Future purchase date unsupported.')
    uuid.UUID(p['guid'])
    item = next((r for r in catalog['items'] if name(r)==p['item']), None)
    party = next((r for r in catalog['ledgers'] if name(r)==p['party']), None)
    if item is None or party is None or value(party,'PARENT')!='Sundry Creditors' or uses_cost_centres(catalog, party):
        raise TallyError('Item/supplier changed; needs review.')
    unit = validate_item(catalog, item, p['unit'])
    places = value(unit, 'DECIMALPLACES')
    qty, rate = decimal(p['quantity']), decimal(p['rate'])
    if not places.isdigit() or not 0<=int(places)<=6 or qty<=0 or rate<=0 or rate != rate.quantize(Decimal('.01')):
        raise TallyError('Invalid quantity/rate precision.')
    if qty != qty.quantize(Decimal(1).scaleb(-int(places))) or decimal(p['total'])<=0 or decimal(p['total']) != (qty*rate).quantize(Decimal('.01')):
        raise TallyError('Invalid purchase total/quantity.')
    if fingerprint(catalog, p) != p['master_fingerprint']:
        raise TallyError('Approved masters changed; needs review.')

def serialize_catalog(catalog):
    return {k: [ET.tostring(r, encoding='unicode') for r in v] if isinstance(v,list) else v for k,v in catalog.items()}

def deserialize_catalog(data):
    if not isinstance(data,dict) or type(data.get('non_gst')) is not bool or type(data.get('cost_centres_enabled')) is not bool:
        raise TallyError('Invalid snapshot flags.')
    result = {k:data[k] for k in ('non_gst','cost_centres_enabled')}
    for kind, tag in [('items','STOCKITEM'),('units','UNIT'),('godowns','GODOWN'),('ledgers','LEDGER'),('groups','GROUP'),('companies','COMPANY'),('stock_groups','STOCKGROUP'),('tax_units','TAXUNIT')]:
        if kind in ('groups','companies','stock_groups','tax_units') and kind not in data:
            result[kind] = []  # Older snapshots remain readable; completeness is labelled by the caller.
            continue
        if not isinstance(data.get(kind),list): raise TallyError('Incomplete snapshot.')
        rows = [parse_xml(s.encode()) for s in data[kind] if isinstance(s,str)]
        if len(rows)!=len(data[kind]) or any(r.tag!=tag or not name(r) for r in rows): raise TallyError('Invalid snapshot master.')
        if len({name(r) for r in rows})!=len(rows): raise TallyError('Ambiguous master identity.')
        result[kind] = rows
    return result

def journal(path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS writes (key TEXT PRIMARY KEY, status TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS snapshots (key TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL)')
    return db

async def execute_sync(operation, *, company, identity, port=None, as_of=None, payload=None, config=None,
                       generation=None, page=None, journal_path='data/tally-local-sync.sqlite3'):
    connector = TallyConnector(port)
    companies = await connector.collection('Company')
    matches = [c for c in companies if name(c)==company and company_identity(c)==identity]
    if len(matches)!=1 or sum(name(c)==company for c in companies)!=1: raise TallyError('Company unavailable or renamed.')
    if operation.startswith('purchase_gst_'):
        from app.services.tally_gst_purchase import execute
        return await execute(operation,connector,company,identity,payload,config,journal_path)
    if operation.startswith('purchase_multi_'):
        from app.services.tally_multi_purchase import execute_multi
        return await execute_multi(operation,connector,company,identity,payload,config,journal_path)
    if operation.startswith('customer_ledger_'):
        if value(matches[0],'ISGSTON').casefold()!='no':raise TallyError('Customer ledger pilot requires a verified non-GST test company.')
        from app.services.tally_customer_codec import execute_customer
        return await execute_customer(operation,connector,company,identity,payload,config,journal_path)
    if operation.startswith('stock_count_'):
        from app.services.tally_count import execute_count
        return await execute_count(operation,connector,company,identity,payload,config,journal_path)
    if operation == 'snapshot_start':
        date.fromisoformat(as_of)
        catalog = await connector.catalog(company)
        catalog['items'] = await connector.collection('StockItem', company, as_of)
        data = serialize_catalog(catalog)
        data['groups_complete'] = 'groups' in catalog
        data['tax_masters_complete'] = 'companies' in catalog and 'stock_groups' in catalog
        stock = [stock_row(i,catalog['units']) for i in catalog['items']]
        # Bounded wire pages. All pages belong to one captured generation.
        pages, current = [], []
        for kind in ('items','units','godowns','ledgers','groups','companies','stock_groups','tax_units'):
            records = [{'kind':kind,'row':r} for r in data.pop(kind, [])]
            if kind=='items': records += [{'kind':'stock','row':r} for r in stock]
            for record in records:
                if len(json.dumps(record).encode())>250_000: raise TallyError('Snapshot record too large.')
                if len(current)>=100 or len(json.dumps(current+[record]).encode())>250_000:
                    pages.append(current);current=[]
                current.append(record)
        if current: pages.append(current)
        generation = uuid.uuid4().hex
        hashes = [hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest() for p in pages]
        with journal(journal_path) as db:
            db.execute('DELETE FROM snapshots WHERE created < ?', (datetime.now(timezone.utc).timestamp()-600,))
            db.execute('INSERT INTO snapshots VALUES (?,?,?)',(generation,json.dumps({'company':company,'identity':identity,'pages':pages}),datetime.now(timezone.utc).timestamp()))
        return {'company':company,'identity':identity,'as_of':as_of,'generation':generation,
                'collected_at':datetime.now(timezone.utc).isoformat(),'flags':data,'hashes':hashes}
    if operation == 'snapshot_page':
        with journal(journal_path) as db:
            record=db.execute('SELECT payload,created FROM snapshots WHERE key=?',(generation,)).fetchone()
        if not record or record[1]<datetime.now(timezone.utc).timestamp()-600: raise TallyError('Snapshot expired.')
        stored=json.loads(record[0])
        if (stored['company'],stored['identity'])!=(company,identity) or type(page)!=int or not 0<=page<len(stored['pages']):
            raise TallyError('Invalid snapshot page.')
        return {'generation':generation,'page':page,'records':stored['pages'][page]}
    if operation not in ('purchase_validate','purchase_post','purchase_reconcile'): raise TallyError('Unsupported operation.')
    if not isinstance(payload,dict) or payload.get('company')!=company: raise TallyError('Invalid purchase.')
    if operation != 'purchase_reconcile':
        catalog=await connector.catalog(company)
        try:validate_purchase(catalog,payload,config)
        except (TallyError,ValueError,TypeError):return {'status':'needs_review','reason':'Purchase masters/configuration invalid or changed.'}
    vouchers=await connector.collection('Voucher',company,payload['date'])
    found=[v for v in vouchers if matches_action(v,payload)]
    if found:
        if len(found)!=1 or not verify_voucher(found[0],payload) or not value(found[0],'VOUCHERNUMBER'):
            return {'status':'needs_review','reason':'Voucher details mismatch.'}
        return {'status':'verified','voucher_number':value(found[0],'VOUCHERNUMBER')}
    if operation=='purchase_validate': return {'status':'ready'}
    if operation=='purchase_reconcile': return {'status':'verification_pending'}
    key=identity+':'+payload['guid']
    with journal(journal_path) as db:
        inserted=db.execute('INSERT OR IGNORE INTO writes VALUES (?,?)',(key,'submitting')).rowcount
    if not inserted: return {'status':'verification_pending'}
    try:
        await connector.post(voucher_xml(payload))
    except TallyRejected as exc:
        return {'status':'failed','reason':str(exc)[:300]}
    except TallyError:
        return {'status':'verification_pending'}
    return await execute_sync('purchase_reconcile', company=company,identity=identity,port=port,
                             payload=payload,journal_path=journal_path)
