"""Protocol v7 non-GST multi-line purchases. Shared by server and helper."""
import copy
import hashlib
import json
from decimal import Decimal
from xml.etree import ElementTree as ET
from app.services.tally_connector import TallyError, TallyRejected, decimal, value, voucher_xml, verify_voucher, matches_action


def legacy_line(p, line):
    return {**{k:p[k] for k in ('company','godown','party','voucher_type','ledger','date','guid')},
        **line,'master_fingerprint':''}


def fingerprint_multi(catalog, p):
    from app.services.tally_sync_protocol import fingerprint
    return hashlib.sha256(json.dumps([fingerprint(catalog,legacy_line(p,line)) for line in p['items']]).encode()).hexdigest()


def validate_multi(catalog, p, config):
    from app.services.tally_sync_protocol import validate_purchase, fingerprint
    expected={'operation','company','godown','party','voucher_type','ledger','date','guid','items','total','master_fingerprint'}
    if not isinstance(p,dict) or set(p)!=expected or p['operation']!='purchase_multi':
        raise TallyError('Invalid multi-item purchase payload.')
    if any(not isinstance(p[k],str) or len(p[k])>2000 for k in expected-{'items'}):
        raise TallyError('Invalid multi-item header.')
    if not isinstance(p['items'],list) or not 1<=len(p['items'])<=100:
        raise TallyError('Purchase requires 1–100 item lines.')
    total=Decimal(0)
    for line in p['items']:
        if not isinstance(line,dict) or set(line)!={'item','quantity','unit','rate','total','stock_before'}:
            raise TallyError('Invalid purchase line.')
        if any(not isinstance(v,str) or len(v)>2000 for v in line.values()):
            raise TallyError('Invalid purchase line fields.')
        qty,rate=decimal(line['quantity']),decimal(line['rate'])
        if qty>=Decimal('1000000') or rate>=Decimal('10000000000'):
            raise TallyError('Purchase line quantity/rate exceeds supported precision.')
        single=legacy_line(p,line);single['master_fingerprint']=fingerprint(catalog,single)
        validate_purchase(catalog,single,config)
        total+=decimal(line['total'])
    if decimal(p['total'])!=total or total<=0:
        raise TallyError('Purchase invoice total does not match item lines.')
    if p['master_fingerprint']!=fingerprint_multi(catalog,p):
        raise TallyError('Approved masters changed; needs review.')


def multi_xml(p):
    first=legacy_line(p,p['items'][0]);first['total']=p['total']
    root=ET.fromstring(voucher_xml(first));voucher=root.find('.//VOUCHER')
    for item in list(voucher.findall('ALLINVENTORYENTRIES.LIST')):voucher.remove(item)
    for line in p['items']:
        native=ET.fromstring(voucher_xml(legacy_line(p,line))).find('.//ALLINVENTORYENTRIES.LIST')
        voucher.append(native)
    return ET.tostring(root,encoding='unicode')


def verify_multi(voucher,p):
    """Match every line, including repeated items at different rates; no partial success."""
    items=voucher.findall('ALLINVENTORYENTRIES.LIST')
    if len(items)!=len(p['items']) or not matches_action(voucher,p):return False
    parties=voucher.findall('LEDGERENTRIES.LIST') or voucher.findall('ALLLEDGERENTRIES.LIST')
    if len(parties)!=1:return False
    try:
        if value(parties[0],'LEDGERNAME')!=p['party'] or decimal(value(parties[0],'AMOUNT'))!=decimal(p['total']):return False
        bill_parties=voucher.findall('ALLLEDGERENTRIES.LIST') or parties
        bills=[b for b in bill_parties[0].findall('BILLALLOCATIONS.LIST') if value(b,'NAME')]
        if len(bills)!=1 or value(bills[0],'NAME')!=p['guid'] or value(bills[0],'BILLTYPE')!='New Ref' or decimal(value(bills[0],'AMOUNT'))!=decimal(p['total']):return False
        remaining=list(items)
        for line in p['items']:
            matched=None
            for item in remaining:
                single=copy.deepcopy(voucher)
                for child in list(single.findall('ALLINVENTORYENTRIES.LIST')):single.remove(child)
                single.append(copy.deepcopy(item))
                # Legacy verification checks the party amount for a single line.
                for party in single.findall('LEDGERENTRIES.LIST')+single.findall('ALLLEDGERENTRIES.LIST'):
                    if party.find('AMOUNT') is not None:party.find('AMOUNT').text=line['total']
                if verify_voucher(single,legacy_line(p,line)):
                    matched=item;break
            if matched is None:return False
            remaining.remove(matched)
        return not remaining
    except (TallyError,KeyError,TypeError,ValueError):return False


async def execute_multi(operation, connector, company, identity, payload, config, journal_path):
    from app.services.tally_sync_protocol import journal
    p=payload
    if not isinstance(p,dict) or p.get('company')!=company or p.get('operation')!='purchase_multi':raise TallyError('Invalid multi purchase.')
    if operation!='purchase_multi_reconcile':
        try:validate_multi(await connector.catalog(company),p,config)
        except (TallyError,ValueError,TypeError,KeyError):return {'status':'needs_review','reason':'Purchase lines/masters/configuration invalid or changed.'}
    found=[v for v in await connector.collection('Voucher',company,p['date']) if matches_action(v,p)]
    if found:
        if len(found)!=1 or not verify_multi(found[0],p) or not value(found[0],'VOUCHERNUMBER'):
            return {'status':'needs_review','reason':'Voucher line details mismatch.'}
        return {'status':'verified','voucher_number':value(found[0],'VOUCHERNUMBER')}
    if operation=='purchase_multi_validate':return {'status':'ready'}
    if operation=='purchase_multi_reconcile':return {'status':'verification_pending'}
    if operation!='purchase_multi_post':raise TallyError('Unsupported multi purchase operation.')
    with journal(journal_path) as db:
        inserted=db.execute('INSERT OR IGNORE INTO writes VALUES (?,?)',(identity+':'+p['guid'],'submitting')).rowcount
    if not inserted:return {'status':'verification_pending'}
    try:await connector.post(multi_xml(p))
    except TallyRejected as exc:return {'status':'failed','reason':str(exc)[:300]}
    except TallyError:return {'status':'verification_pending'}
    return await execute_multi('purchase_multi_reconcile',connector,company,identity,p,config,journal_path)
