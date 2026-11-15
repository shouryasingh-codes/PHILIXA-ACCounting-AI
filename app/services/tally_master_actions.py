"""Native create-only master actions. No database, model or local-server fallback."""
import re
import uuid
from contextlib import closing
from datetime import date
from xml.etree import ElementTree as ET
from app.services.tally_connector import tag,name,value,decimal,TallyError,TallyRejected

KINDS={'LEDGER':'ledgers','STOCKITEM':'items','UNIT':'units'}
BASE={
    'LEDGER':{'PARENT':'Sundry Creditors','OPENINGBALANCE':'0','ISBILLWISEON':'Yes','ISCOSTCENTRESON':'No'},
    'STOCKITEM':{'OPENINGBALANCE':'0','ISBATCHWISEON':'No','ISPERISHABLEON':'No','HASMFGDATE':'No','ISADDLCOSTTRACKINGON':'No','ISSERIALNUMBERON':'No'},
    'UNIT':{'ISSIMPLEUNIT':'Yes'},
}

def validate(p,config,company):
    if not isinstance(p,dict) or set(p)!={'operation','company','guid','masters'} or p['operation']!='masters_create':raise TallyError('Invalid master action.')
    if config.get('test_company') is not True or config.get('company')!=company or p['company']!=company:raise TallyError('Approved test company required.')
    uuid.UUID(p['guid'])
    if not isinstance(p['masters'],list) or not 1<=len(p['masters'])<=101:raise TallyError('Master batch limit exceeded.')
    seen=set()
    for m in p['masters']:
        if set(m)!={'kind','name','guid','fields'} or m['kind'] not in KINDS:raise TallyError('Invalid master definition.')
        if not isinstance(m['name'],str) or not m['name'].strip() or m['name']!=m['name'].strip() or len(m['name'])>200 or any(ord(c)<32 for c in m['name']):raise TallyError('Invalid master name.')
        uuid.UUID(m['guid'])
        key=(m['kind'],m['name'].casefold())
        if key in seen:raise TallyError('Duplicate master definition.')
        seen.add(key);f=m['fields'];required=BASE[m['kind']]
        allowed=set(required)|({'PARTYGSTIN'} if m['kind']=='LEDGER' else {'BASEUNITS'} if m['kind']=='STOCKITEM' else {'DECIMALPLACES','GSTREPUOM'})
        if not isinstance(f,dict) or set(f)-allowed or any(f.get(k)!=v for k,v in required.items()):raise TallyError('Unsupported master fields.')
        if any(not isinstance(v,str) or len(v)>200 or any(ord(c)<32 for c in v) for v in f.values()):raise TallyError('Invalid master value.')
        if m['kind']=='STOCKITEM' and not f.get('BASEUNITS'):raise TallyError('Explicit native unit required.')
        if m['kind']=='UNIT' and (f.get('DECIMALPLACES') not in tuple(map(str,range(7))) or not re.fullmatch(r'[A-Z]{3}-[A-Z ]+',f.get('GSTREPUOM',''))):raise TallyError('Explicit unit precision/UQC required.')
        if f.get('PARTYGSTIN'):
            from app.services.tally_gst_purchase import gstin_state
            gstin_state(f['PARTYGSTIN'])

def xml(p):
    root=ET.Element('ENVELOPE');tag(tag(root,'HEADER'),'TALLYREQUEST','Import Data')
    body=tag(tag(root,'BODY'),'IMPORTDATA');desc=tag(body,'REQUESTDESC');tag(desc,'REPORTNAME','All Masters')
    tag(tag(desc,'STATICVARIABLES'),'SVCURRENTCOMPANY',p['company']);data=tag(body,'REQUESTDATA')
    for m in p['masters']:
        row=tag(tag(data,'TALLYMESSAGE',**{'xmlns:UDF':'TallyUDF'}),m['kind'],NAME=m['name'],ACTION='Create')
        tag(row,'NAME',m['name']);tag(row,'GUID',m['guid'])
        if m['kind']!='UNIT':
            names=tag(tag(row,'LANGUAGENAME.LIST'),'NAME.LIST',TYPE='String');tag(names,'NAME',m['name']);tag(names,'NAME','PhilixaMaster:'+m['guid'])
        for k,v in m['fields'].items():tag(row,k,v)
    return ET.tostring(root,encoding='unicode')

def verified(row,m):
    marker=value(row,'GUID')==m['guid'] or 'PhilixaMaster:'+m['guid'] in [r.text for r in row.findall('LANGUAGENAME.LIST/NAME.LIST/NAME')]
    if not marker or name(row)!=m['name'] or not value(row,'GUID'):return False
    for k,v in m['fields'].items():
        actual=value(row,k)
        if k=='OPENINGBALANCE':
            if decimal(actual or '0')!=0:return False
        elif actual.casefold()!=v.casefold():return False
    return True

async def execute(operation,connector,company,identity,p,config,journal_path):
    from app.services.tally_sync_protocol import journal
    validate(p,config,company)
    cat=await connector.catalog(company);found=[]
    for m in p['masters']:
        matches=[r for r in cat[KINDS[m['kind']]] if name(r).casefold()==m['name'].casefold()]
        if matches and (len(matches)!=1 or not verified(matches[0],m)):
            return {'status':'needs_review','reason':'Master name/identity or approved fields conflict; no overwrite allowed.'}
        found.append(bool(matches))
    if all(found):return {'status':'verified','masters':[{'kind':m['kind'],'name':m['name'],'guid':m['guid']} for m in p['masters']]}
    key=identity+':masters:'+p['guid']
    with closing(journal(journal_path)) as db,db:sent=db.execute('SELECT 1 FROM writes WHERE key=?',(key,)).fetchone()
    if sent or any(found):return {'status':'verification_pending','reason':'Partial/uncertain master import; reconcile same action, never resend.'}
    # Fresh unit dependencies must still exist; never silently substitute a unit.
    pending_units={m['name'] for m in p['masters'] if m['kind']=='UNIT'}
    for m in p['masters']:
        if m['kind']=='STOCKITEM' and m['fields']['BASEUNITS'] not in pending_units and sum(name(r)==m['fields']['BASEUNITS'] for r in cat['units'])!=1:raise TallyError('Native unit disappeared; review required.')
    if operation=='masters_validate':return {'status':'ready'}
    if operation=='masters_reconcile':return {'status':'verification_pending'}
    if operation!='masters_post':raise TallyError('Unsupported master operation.')
    with closing(journal(journal_path)) as db,db:
        inserted=db.execute('INSERT OR IGNORE INTO writes VALUES (?,?)',(key,'submitting')).rowcount
    if not inserted:return {'status':'verification_pending'}
    try:await connector.post(xml(p))
    except TallyRejected as exc:return {'status':'failed','reason':str(exc)[:200]}
    except TallyError:return {'status':'verification_pending'}
    return await execute('masters_reconcile',connector,company,identity,p,config,journal_path)
