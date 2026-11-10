"""Pure identity/duplicate rules shared by server and Windows connector."""
import hashlib
import json
import re
import copy
from datetime import date
from xml.etree import ElementTree as ET
from app.services.tally_connector import TallyError, name, value, tag

def normalized(text):
    return re.sub(r'\s+',' ',str(text or '').strip()).casefold()

def financial_year(stamp):
    try: dt=date.fromisoformat(stamp)
    except (ValueError,TypeError): raise TallyError('Invoice date/year evidence missing; review required.')
    if not 1900<=dt.year<=2100: raise TallyError('Invoice year outside supported range; review required.')
    year=dt.year if dt.month>=4 else dt.year-1
    return f'{year:04d}-04-01',f'{year+1:04d}-03-31'

def master_identity(row):
    guid=value(row,'GUID')
    mid=value(row,'PHILIXAMASTERID') or value(row,'MASTERID')
    if not guid and not mid: raise TallyError('Stable Tally master identity unavailable; sync masters and review.')
    return ('guid:'+guid) if guid else ('master:'+mid)

def master_fingerprint(row):
    row=copy.deepcopy(row)
    for parent in row.iter():
        for child in list(parent):
            if child.tag in ('CLOSINGBALANCE','OPENINGBALANCE','CLOSINGVALUE','OPENINGVALUE'): parent.remove(child)
        parent.attrib=dict(sorted(parent.attrib.items()))
        parent.text=(parent.text or '').strip() or None
        parent.tail=None
    return hashlib.sha256(ET.tostring(row,encoding='utf-8')).hexdigest()

def exact_master(catalog,kind,target):
    rows=[r for r in catalog['ledgers' if kind=='supplier' else 'items'] if normalized(name(r))==normalized(target)]
    if kind=='supplier':rows=[r for r in rows if value(r,'PARENT')=='Sundry Creditors']
    if len(rows)!=1:raise TallyError('Exact master missing/ambiguous; select a current Tally master.')
    return rows[0]

def invoice_guard(company_identity,catalog,content):
    reference=normalized(content.get('invoice_number'))
    if not reference:raise TallyError('Supplier invoice reference missing; review required before posting.')
    start,end=financial_year(content.get('entry_date'))
    master=exact_master(catalog,'supplier',content.get('party_name'))
    identity=master_identity(master)
    key=hashlib.sha256(json.dumps([company_identity,identity,reference,start],ensure_ascii=False).encode()).hexdigest()
    return dict(key=key,reference=reference,party=name(master),supplier_identity=identity,year_start=start,year_end=end)

async def check_native(connector,company,guard):
    if not isinstance(guard,dict) or set(guard)!={'key','reference','party','supplier_identity','year_start','year_end'}:
        raise TallyError('Invalid invoice duplicate guard.')
    if any(not isinstance(v,str) or len(v)>2000 for v in guard.values()):raise TallyError('Invalid invoice guard fields.')
    start,end=financial_year(guard['year_start'])
    if (start,end)!=(guard['year_start'],guard['year_end']) or not guard['reference']:
        raise TallyError('Invalid invoice year/reference evidence.')
    catalog=await connector.catalog(company)
    master=exact_master(catalog,'supplier',guard['party'])
    if master_identity(master)!=guard['supplier_identity']:raise TallyError('Supplier identity changed; review required.')
    vouchers=await connector.collection('Voucher',company,end,from_date=start)
    for v in vouchers:
        if value(v,'ISCANCELLED').lower()=='yes' or value(v,'ISOPTIONAL').lower()=='yes':continue
        purchase=value(v,'VOUCHERTYPENAME')=='Purchase'
        if not purchase and normalized(value(v,'REFERENCE'))!=guard['reference']:continue
        if normalized(value(v,'PARTYLEDGERNAME'))!=normalized(guard['party']):continue
        stamp=value(v,'DATE')
        if not re.fullmatch(r'\d{8}',stamp):return {'status':'review_required','reason':'Existing purchase year evidence unreadable; review required.'}
        iso=f'{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}'
        try:date.fromisoformat(iso)
        except ValueError:return {'status':'review_required','reason':'Existing voucher date/year is invalid; review required.'}
        if not purchase and start<=iso<=end:
            return {'status':'review_required','reason':'Matching supplier invoice reference exists in another voucher type; manual duplicate review required.'}
        if start<=iso<=end and not normalized(value(v,'REFERENCE')):
            return {'status':'review_required','reason':'An existing supplier purchase is missing its invoice reference; duplicate review required.'}
        if start<=iso<=end and normalized(value(v,'REFERENCE'))==guard['reference']:
            return {'status':'duplicate','reason':'Existing Tally purchase has this supplier invoice reference and financial year.'}
    return {'status':'clear'}

def reference_xml(xml,guard):
    if not guard or '<REFERENCE>' in xml:return xml
    root=ET.fromstring(xml);v=root.find('.//VOUCHER')
    if v.find('REFERENCE') is None:tag(v,'REFERENCE',guard['reference'])
    return ET.tostring(root,encoding='unicode')
