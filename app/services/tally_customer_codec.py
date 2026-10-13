"""One typed customer master operation. Safe to bundle without DB/AI imports."""
import hashlib
import json
import re
import uuid
from xml.etree import ElementTree as ET
from app.services.tally_connector import tag, name, value, decimal, TallyError, TallyRejected

GROUP = 'Sundry Debtors'

def ledger_fingerprint(row):
    fields = ('GUID','PARENT','EMAIL','LEDGERMOBILE','ISBILLWISEON','ISCOSTCENTRESON','OPENINGBALANCE','PARTYGSTIN')
    return hashlib.sha256(json.dumps({'name':name(row), **{k:value(row,k) for k in fields}},sort_keys=True).encode()).hexdigest()

def validate_payload(p, config, company):
    expected = {'operation','company','name','parent','guid','mode','target_guid','fingerprint','email','phone','client_id','client_version'}
    if not isinstance(p,dict) or set(p)!=expected or p['operation']!='customer_ledger_create':
        raise TallyError('Invalid customer ledger payload.')
    if not isinstance(config,dict) or config.get('test_company') is not True or config.get('company')!=company or p['company']!=company:
        raise TallyError('Configured test company authorization required.')
    if p['parent']!=GROUP or p['mode'] not in ('create','link'):
        raise TallyError('Only customer ledgers supported; existing ledger groups are never changed.')
    if any(not isinstance(p[k],str) or len(p[k])>250 or any(ord(c)<32 for c in p[k]) for k in ('name','guid','target_guid','fingerprint','client_version')):
        raise TallyError('Invalid ledger identity.')
    if not p['name'].strip() or p['name']!=p['name'].strip() or len(p['name'])>120:
        raise TallyError('Customer name required.')
    uuid.UUID(p['guid'])
    if (p['mode']=='link' and (not p['target_guid'] or not re.fullmatch('[a-f0-9]{64}',p['fingerprint']))) or (p['mode']=='create' and (p['target_guid'] or p['fingerprint'])):
        raise TallyError('Invalid ledger precondition.')
    if p['client_id'] is not None and (type(p['client_id']) is not int or p['client_id']<=0):raise TallyError('Invalid customer identity.')
    if p['email'] is not None and (not isinstance(p['email'],str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',p['email']) or len(p['email'])>254):raise TallyError('Invalid customer email.')
    if p['phone'] is not None and (not isinstance(p['phone'],str) or not re.fullmatch(r'\+?[0-9]{10,15}',p['phone'])):raise TallyError('Invalid customer phone.')

def ledger_xml(p):
    root=ET.Element('ENVELOPE');tag(tag(root,'HEADER'),'TALLYREQUEST','Import Data')
    body=tag(tag(root,'BODY'),'IMPORTDATA');desc=tag(body,'REQUESTDESC')
    tag(desc,'REPORTNAME','All Masters');tag(tag(desc,'STATICVARIABLES'),'SVCURRENTCOMPANY',p['company'])
    ledger=tag(tag(tag(body,'REQUESTDATA'),'TALLYMESSAGE',**{'xmlns:UDF':'TallyUDF'}),'LEDGER',NAME=p['name'],ACTION='Create')
    languages=tag(ledger,'LANGUAGENAME.LIST');names=tag(languages,'NAME.LIST',TYPE='String')
    tag(names,'NAME',p['name']);tag(names,'NAME','PhilixaAction:'+p['guid']);tag(languages,'LANGUAGEID','1033')
    for k,v in [('NAME',p['name']),('GUID',p['guid']),('PARENT',GROUP),('OPENINGBALANCE','0'),('ISBILLWISEON','No'),('ISCOSTCENTRESON','No'),('NOTES','Philixa customer action:'+p['guid'])]:tag(ledger,k,v)
    if p['email']:tag(ledger,'EMAIL',p['email'])
    if p['phone']:tag(ledger,'LEDGERMOBILE',p['phone'])
    return ET.tostring(root,encoding='unicode')

def matches_created(row,p):
    aliases=[n.text for n in row.findall('LANGUAGENAME.LIST/NAME.LIST/NAME')]
    return value(row,'GUID')==p['guid'] or value(row,'NOTES')=='Philixa customer action:'+p['guid'] or 'PhilixaAction:'+p['guid'] in aliases

def verify_created(row,p):
    return verify_fields(row,p) and matches_created(row,p)

def verify_fields(row,p):
    try:
        if decimal(value(row,'OPENINGBALANCE') or '0')!=0:return False
    except TallyError:return False
    return (name(row)==p['name'] and value(row,'PARENT')==GROUP and bool(value(row,'GUID'))
            and value(row,'ISBILLWISEON').casefold()=='no'
            and value(row,'ISCOSTCENTRESON').casefold()=='no'
            and (not p['email'] or value(row,'EMAIL')==p['email'])
            and (not p['phone'] or value(row,'LEDGERMOBILE')==p['phone']))

async def execute_customer(operation,connector,company,identity,p,config,journal_path):
    from app.services.tally_sync_protocol import journal
    validate_payload(p,config,company)
    key=identity+':customer:'+p['guid']
    with journal(journal_path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS customer_receipts (key TEXT PRIMARY KEY, master_id TEXT NOT NULL)')
        receipt=db.execute('SELECT master_id FROM customer_receipts WHERE key=?',(key,)).fetchone()
    rows=await connector.collection('Ledger',company)
    exact=[r for r in rows if name(r).casefold()==p['name'].casefold()]
    marker=[r for r in rows if matches_created(r,p)] if p['mode']=='create' else []
    row=None;source='native_link';master_id=None
    if p['mode']=='link':
        if len(exact)!=1 or value(exact[0],'GUID')!=p['target_guid'] or ledger_fingerprint(exact[0])!=p['fingerprint'] or value(exact[0],'PARENT')!=GROUP:
            return {'status':'needs_review','reason':'Existing customer ledger changed; fresh preview required.'}
        row=exact[0]
    elif marker:
        if len(marker)!=1 or len(exact)!=1 or not verify_created(marker[0],p):
            return {'status':'needs_review','reason':'Customer ledger identity/details mismatch.'}
        row=marker[0];source='action_marker'
    elif receipt:
        master_id=receipt[0]
        matched=[r for r in rows if value(r,'PHILIXAMASTERID')==master_id]
        if len(matched)!=1 or len(exact)!=1 or not verify_fields(matched[0],p):
            return {'status':'needs_review','reason':'Imported native master ID/details changed; review required.'}
        row=matched[0];source='import_receipt'
    elif exact:
        return {'status':'needs_review','reason':'Same-name ledger appeared; review and link it instead of importing again.'}
    if row is not None:
        return {'status':'verified','ledger_guid':value(row,'GUID'),'ledger_name':name(row),'ledger_parent':GROUP,
                'verification_source':source,'master_id':master_id}
    if operation=='customer_ledger_validate':return {'status':'ready'}
    if operation=='customer_ledger_reconcile':return {'status':'verification_pending'}
    if operation!='customer_ledger_post':raise TallyError('Unsupported customer operation.')
    with journal(journal_path) as db:
        inserted=db.execute('INSERT OR IGNORE INTO writes VALUES (?,?)',(key,'submitting')).rowcount
    if not inserted:return {'status':'verification_pending'}
    try:
        response=await connector.post(ledger_xml(p))
        imported_id=response.findtext('.//LASTMID')
        if response.findtext('.//CREATED')=='1' and response.findtext('.//ALTERED') in (None,'0') and response.findtext('.//COMBINED') in (None,'0') and imported_id and imported_id.isdigit() and int(imported_id)>0:
            with journal(journal_path) as db:db.execute('INSERT OR IGNORE INTO customer_receipts VALUES (?,?)',(key,imported_id))
    except TallyRejected as exc:return {'status':'failed','reason':str(exc)[:300]}
    except TallyError:return {'status':'verification_pending'}
    return await execute_customer('customer_ledger_reconcile',connector,company,identity,p,config,journal_path)
