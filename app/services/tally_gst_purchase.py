"""Protocol v8: bounded domestic goods purchases. No DB/provider dependencies.

Rates come from effective native masters, never from a hardcoded GST schedule.
All monetary comparison happens at a paisa; no balancing adjustment is invented.
"""
import copy
import hashlib
import json
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from xml.etree import ElementTree as ET
from app.services.tally_connector import TallyError, TallyRejected, decimal, name, value, tag, matches_action, quantity, voucher_xml
from app.services.tally_validation import validate_item, uses_cost_centres

HEADS=('CGST','SGST','IGST','UTGST')
PAISA=Decimal('.01')

def gst_units(catalog):
    # Native Tally also exports an empty Default Tax Unit for non-GST taxes.
    return [r for r in catalog.get('tax_units',[]) if r.get('TAXTYPE','').upper()=='GST'
            or value(r,'GSTREGNUMBER') or any(value(d,'REGISTRATIONTYPE') for d in r.findall('GSTREGISTRATIONDETAILS.LIST'))]

def tax_head(text):
    return 'SGST' if text.upper() in ('SGST/UTGST','UTGST') else text.upper()

def money(v): return decimal(v).quantize(PAISA,rounding=ROUND_HALF_UP)

def exact(rows,label):
    found=[r for r in rows if name(r)==label]
    if len(found)!=1:raise TallyError(f'Master missing/ambiguous: {label}. Sync and select the exact master.')
    return found[0]

def gstin_state(text):
    if not isinstance(text,str) or not re.fullmatch(r'[0-9]{2}[A-Z]{3}[ABCFGHJLPT][A-Z][0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]',text):
        raise TallyError('Valid regular GSTIN required; unregistered/import/SEZ/composition cases unsupported.')
    if not 1<=int(text[:2])<=38:raise TallyError('Unsupported GST state code.')
    alphabet='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';factor=2;total=0
    for char in reversed(text[:-1]):
        n=alphabet.index(char)*factor;total+=n//36+n%36;factor=1 if factor==2 else 2
    if alphabet[(36-total%36)%36]!=text[-1]:raise TallyError('GSTIN checksum mismatch. Verify original/master.')
    return text[:2]

def effective(rows,stamp):
    candidates=[]
    for row in rows:
        raw=value(row,'APPLICABLEFROM') or value(row,'FROMDATE')
        try:when=date.fromisoformat(raw) if '-' in raw else datetime.strptime(raw,'%Y%m%d').date()
        except ValueError:raise TallyError('GST master effective date missing/invalid.')
        if when<=date.fromisoformat(stamp):candidates.append((when,row))
    if not candidates:return None
    newest=max(d for d,_ in candidates);matches=[r for d,r in candidates if d==newest]
    if len(matches)!=1:raise TallyError('Conflicting GST details for invoice date.')
    return matches[0]

def registration(company,stamp):
    rows=company.findall('GSTREGISTRATIONDETAILS.LIST')
    row=effective(rows,stamp) if rows else company
    if row is None:raise TallyError('Company GST registration missing for invoice date.')
    if (value(row,'GSTREGISTRATIONTYPE') or value(row,'REGISTRATIONTYPE')).casefold()!='regular':raise TallyError('Only a regular company GST registration is supported.')
    gst=value(row,'GSTIN') or value(row,'GSTREGISTRATIONNUMBER') or value(row,'PARTYGSTIN') or value(row,'GSTREGNUMBER')
    if not gst and rows:
        current=effective(rows,datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat())
        if row is not current:raise TallyError('Historical registration number missing; cannot use current GSTIN for old invoice.')
        gst=value(company,'GSTREGNUMBER') or value(company,'GSTREGISTRATIONNUMBER')
    gstin_state(gst)
    if rows and len({value(r,'GSTIN') or value(r,'GSTREGISTRATIONNUMBER') for r in rows})>1:
        raise TallyError('Multiple company GST registrations require explicit tax-unit support.')
    return gst

def master_rate(catalog,item,purchase,company,stamp):
    # Nearest explicit item/stock-group rules take precedence. Purchase/group/company
    # inheritance is considered only when no item-level effective rule exists.
    sources=[item];parent=value(item,'PARENT');visited=set()
    while parent and parent not in ('Primary','Not Applicable'):
        if parent in visited:raise TallyError('Stock group cycle; GST source ambiguous.')
        visited.add(parent);group=exact(catalog.get('stock_groups',[]),parent);sources.append(group);parent=value(group,'PARENT')
    sources.append(purchase);parent=value(purchase,'PARENT');visited=set()
    while parent and parent not in ('Primary','Not Applicable'):
        if parent in visited:raise TallyError('Ledger group cycle; GST source ambiguous.')
        visited.add(parent);group=exact(catalog.get('groups',[]),parent);sources.append(group);parent=value(group,'PARENT')
    sources.append(company)
    priority=effective(company.findall('CMPGSTDETAILS.LIST'),stamp)
    if priority is not None:
        source_priority=value(priority,'GSTSOURCEPRIORITY').casefold()
        if source_priority and source_priority not in ('stock item','stock item first','stock items','item first'):
            raise TallyError('Company GST source priority requires native fixture validation; unsupported hierarchy.')
    for source in sources:
        detail=effective(source.findall('GSTDETAILS.LIST'),stamp)
        if detail is None:continue
        if value(detail,'TAXABILITY').casefold()!='taxable' or value(detail,'ISREVERSECHARGEAPPLICABLE').casefold() not in ('','no') or decimal(value(detail,'REVERSECHARGERATE') or 0):
            raise TallyError('Exempt/nil/unknown/reverse-charge GST treatment unsupported.')
        supply=value(detail,'SUPPLYTYPE') or value(source,'GSTTYPEOFSUPPLY') or value(item,'GSTTYPEOFSUPPLY')
        if supply.casefold()!='goods':raise TallyError('Only domestic regular goods are supported; supply type missing/services unsupported.')
        if value(detail,'GSTINELIGIBLEITC').casefold()=='yes' or value(detail,'GSTCALCSLABONMRP').casefold()=='yes':raise TallyError('Ineligible ITC/MRP slab cases unsupported.')
        if any(list(r) for r in detail.findall('.//GSTSLABRATES.LIST')):raise TallyError('Slab GST rates unsupported.')
        rates={}
        for row in detail.findall('.//RATEDETAILS.LIST'):
            head=tax_head(value(row,'GSTRATEDUTYHEAD'))
            rate=decimal(value(row,'GSTRATE'))
            if head not in HEADS:
                if rate or decimal(value(row,'GSTRATEPERUNIT') or 0):raise TallyError('Cess/other tax unsupported.')
                continue
            if value(row,'GSTRATEVALUATIONTYPE').casefold() not in ('based on value','on value') or decimal(value(row,'GSTRATEPERUNIT') or 0):
                raise TallyError('GST valuation type missing or per-unit cess unsupported.')
            if head in rates and rates[head]!=rate:raise TallyError('State-specific/conflicting tax rates unsupported.')
            rates[head]=rate
        total=rates.get('IGST')
        split=rates.get('CGST',Decimal(0))+rates.get('SGST',rates.get('UTGST',Decimal(0)))
        if total is None:total=split
        if not 0<total<=100 or (split and split!=total) or (rates.get('CGST') is not None and rates['CGST']*2!=total):
            raise TallyError('Missing/ambiguous GST rate in masters.')
        hsn_detail=effective(source.findall('HSNDETAILS.LIST'),stamp)
        hsn=value(hsn_detail,'HSNCODE') or value(hsn_detail,'HSN') if hsn_detail is not None else value(detail,'HSNCODE') or value(detail,'HSN')
        if not re.fullmatch(r'\d{4,8}',hsn):raise TallyError('Goods HSN missing/unsupported in GST masters.')
        return total,hsn,name(source),{'STOCKITEM':'Stock Item','STOCKGROUP':'Stock Group','LEDGER':'Ledger','GROUP':'Group','COMPANY':'Company'}[source.tag]
    raise TallyError('No effective item/group/purchase/company GST details. Sync complete GST masters.')

def fingerprint(catalog,p):
    def canonical(row):
        row=copy.deepcopy(row)
        for child in row.iter():
            child.text=(child.text or '').strip() or None
            child.tail=None
            child.attrib=dict(sorted(child.attrib.items()))
        return ET.tostring(row,encoding='unicode')
    chosen={}
    selection={'companies':[p['company']],'items':[r['item'] for r in p['items']],
        'ledgers':[p['party'],p['ledger'],*p['tax_profile']['ledgers'].values()],
        'godowns':[p['godown']],'units':[r['unit'] for r in p['items']]}
    if p['tax_profile'].get('rounding_ledger'):selection['ledgers'].append(p['tax_profile']['rounding_ledger'])
    for kind,labels in selection.items():
        chosen[kind]=[]
        for label in sorted(set(labels)):
            row=copy.deepcopy(exact(catalog.get(kind,[]),label))
            for field in ('CLOSINGBALANCE','PHILIXACLOSINGQTY','OPENINGBALANCE'):
                for child in list(row.findall(field)):row.remove(child)
            chosen[kind].append(canonical(row))
    for kind in ('groups','stock_groups','tax_units'):
        chosen[kind]=sorted(canonical(r) for r in catalog.get(kind,[]))
    chosen['flags']=[catalog['non_gst'],catalog['cost_centres_enabled']]
    return hashlib.sha256(json.dumps(chosen,sort_keys=True).encode()).hexdigest()

def validate_setup(catalog,config):
    if not config.get('test_company'):raise TallyError('Separate test company authorization required.')
    company=exact(catalog.get('companies',[]),config['company'])
    if value(company,'ISGSTON').casefold()!='yes':raise TallyError('GST must be enabled in the selected company.')
    units=gst_units(catalog)
    if len(units)>1:raise TallyError('Multiple GST tax units unsupported.')
    registration(units[0] if units else company,datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat())
    if len(catalog['godowns'])!=1 or name(catalog['godowns'][0])!=config['godown']:raise TallyError('Single configured godown required.')
    for field,parent in [('purchase_ledger','Purchase Accounts'),('sales_ledger','Sales Accounts')]:
        row=exact(catalog['ledgers'],config[field])
        if value(row,'PARENT')!=parent or uses_cost_centres(catalog,row):raise TallyError('Configured account group/flags unsupported.')

def compile_purchase(catalog,content,profile,config,guid):
    if not isinstance(config,dict) or config.get('test_company') is not True:raise TallyError('Explicitly configured test company required.')
    uuid.UUID(guid)
    stamp=content.get('entry_date');date.fromisoformat(stamp)
    if date.fromisoformat(stamp)>datetime.now(ZoneInfo('Asia/Kolkata')).date():raise TallyError('Future invoice date unsupported.')
    if content.get('tax_treatment')!='regular_domestic_goods' or content.get('unsupported_treatments'):
        raise TallyError('Select supported domestic regular goods; unsupported invoice treatments block posting.')
    if not content.get('invoice_number'):raise TallyError('Supplier invoice number required.')
    company=exact(catalog.get('companies',[]),config['company'])
    if value(company,'ISGSTON').casefold()!='yes' or catalog['non_gst']:raise TallyError('GST-enabled company required.')
    tax_units=gst_units(catalog)
    if tax_units and len(tax_units)!=1:raise TallyError('Multiple tax units unsupported; select registration explicitly.')
    company_gstin=registration(tax_units[0] if tax_units else company,stamp);company_state=gstin_state(company_gstin)
    if content.get('place_of_supply')!=company_state:raise TallyError('Place of supply must match receiving company state; bill-to/ship-to exceptions unsupported.')
    party=exact(catalog['ledgers'],content.get('party_name'))
    party_details=effective(party.findall('LEDGSTREGDETAILS.LIST'),stamp) or party
    if value(party,'PARENT')!='Sundry Creditors' or value(party_details,'GSTREGISTRATIONTYPE').casefold()!='regular':raise TallyError('Regular registered supplier required.')
    supplier_gstin=value(party_details,'GSTIN') or value(party,'PARTYGSTIN');supplier_state=gstin_state(supplier_gstin)
    if supplier_gstin==company_gstin:raise TallyError('Supplier and receiving company GSTIN cannot be the same.')
    if content.get('supplier_gstin')!=supplier_gstin:raise TallyError('Invoice GSTIN does not match supplier master.')
    purchase=exact(catalog['ledgers'],config['purchase_ledger'])
    if value(purchase,'PARENT')!='Purchase Accounts':raise TallyError('Purchase ledger group invalid.')
    if uses_cost_centres(catalog,party) or uses_cost_centres(catalog,purchase):raise TallyError('Cost centres unsupported.')
    if content.get('godown') not in (None,'',config['godown']):raise TallyError('Godown mismatch.')
    exact(catalog['godowns'],config['godown'])
    if len(catalog['godowns'])!=1:raise TallyError('Pilot requires one configured godown.')
    if not isinstance(profile,dict) or set(profile)!= {'ledgers','rounding_ledger'} or not isinstance(profile['ledgers'],dict) or any(h not in HEADS for h in profile['ledgers']):
        raise TallyError('Invalid company tax ledger configuration.')
    heads=('IGST',) if supplier_state!=company_state else ('CGST','UTGST' if company_state in ('04','25','26','31','35','38') else 'SGST')
    selected={}
    for head in heads:
        ledger=exact(catalog['ledgers'],profile['ledgers'].get(head))
        if value(ledger,'PARENT')!='Duties & Taxes' or value(ledger,'TAXTYPE').casefold()!='gst' or tax_head(value(ledger,'GSTDUTYHEAD'))!=('SGST' if head=='UTGST' else head) or uses_cost_centres(catalog,ledger):
            raise TallyError(f'Configured {head} ledger has unsupported tax flags/group.')
        selected[head]=name(ledger)
    lines=content.get('lines')
    if not isinstance(lines,list) or not 1<=len(lines)<=100:raise TallyError('1–100 item lines required.')
    prepared=[]
    for line in lines:
        item=exact(catalog['items'],line.get('item_name'));unit=validate_item(catalog,item,line.get('unit'))
        uqc_rule=effective([r for r in unit.findall('REPORTINGUQCDETAILS.LIST') if list(r)],stamp)
        uqc=value(uqc_rule,'REPORTINGUQCNAME') if uqc_rule is not None else value(unit,'GSTREPUOM')
        if not re.fullmatch(r'[A-Z]{3}-[A-Z ]+',uqc):raise TallyError('GST unit/UQC mapping missing or unsupported; configure the native unit master.')
        qty=decimal(line.get('quantity'));rate=decimal(line.get('rate'))
        places=value(unit,'DECIMALPLACES')
        if not places.isdigit() or not 0<=int(places)<=6 or qty<=0 or qty>=1000000 or rate<=0 or rate>=10000000000 or money(rate)!=rate or qty!=qty.quantize(Decimal(1).scaleb(-int(places))):
            raise TallyError('Invalid quantity/rate precision.')
        gross=money(qty*rate);discount=decimal(line.get('discount_amount') or 0);percent=decimal(line.get('discount_percent') or 0)
        if discount and percent:raise TallyError('Use amount OR percent discount per line.')
        if percent<0 or percent>=100:raise TallyError('Invalid line discount percent.')
        if percent:discount=money(gross*percent/100)
        if discount<0 or discount>=gross or discount!=money(discount):raise TallyError('Invalid line discount amount.')
        tax_rate,hsn,source,source_type=master_rate(catalog,item,purchase,company,stamp)
        if line.get('gst_rate') is None or decimal(line['gst_rate'])!=tax_rate:raise TallyError('Invoice GST rate missing or differs from effective master.')
        if line.get('hsn')!=hsn:raise TallyError('Invoice HSN missing or differs from effective master.')
        prepared.append({'item':name(item),'quantity':str(qty),'rate':str(rate),'unit':line['unit'],'gross':str(gross),'discount':str(discount),
            'taxable':str(gross-discount),'gst_rate':str(tax_rate),'hsn':hsn,'uqc':uqc,'gst_source':source,'gst_source_type':source_type,'stock_before':value(item,'CLOSINGBALANCE')})
    subtotal=sum((decimal(r['taxable']) for r in prepared),Decimal(0))
    header=decimal(content.get('invoice_discount') or 0)
    if header<0 or header>=subtotal or money(header)!=header:raise TallyError('Invoice discount must be a disclosed pre-tax amount below taxable subtotal.')
    # Allocate cents proportionally; deterministic largest remainder preserves the disclosed discount.
    allocations=[(header*decimal(r['taxable'])/subtotal) for r in prepared]
    shares=[a.quantize(PAISA,rounding='ROUND_DOWN') for a in allocations]
    remaining=int((header-sum(shares))/PAISA)
    ranking=sorted(range(len(shares)),key=lambda i:(allocations[i]-shares[i],-i),reverse=True)
    for i in ranking[:remaining]:shares[i]+=PAISA
    totals={h:Decimal(0) for h in heads}
    for i,row in enumerate(prepared):
        row['discount']=str(decimal(row['discount'])+shares[i]);base=money(decimal(row['taxable'])-shares[i]);row['taxable']=str(base)
        if base<=0:raise TallyError('Discount removes an entire line; unsupported.')
        row['taxes']={h:str(money(base*decimal(row['gst_rate'])/(100 if h=='IGST' else 200))) for h in heads}
        if lines[i].get('taxable_amount') is None or money(lines[i]['taxable_amount'])!=base:raise TallyError(f'Line {i+1}: invoice taxable amount mismatch/missing.')
        for h in heads:totals[h]+=decimal(row['taxes'][h])
    expected=content.get('expected_taxes')
    if not isinstance(expected,dict) or set(expected)!=set(heads) or any(money(expected[h])!=money(totals[h]) for h in heads):
        raise TallyError('Invoice tax breakup missing/mismatched; no hidden adjustment allowed.')
    roundoff=decimal(content.get('round_off') or 0)
    if abs(roundoff)>1 or roundoff!=money(roundoff):raise TallyError('Disclosed round-off must be at most ₹1 with paisa precision.')
    if roundoff:
        rounding=exact(catalog['ledgers'],profile.get('rounding_ledger'))
        if value(rounding,'PARENT') not in ('Indirect Expenses','Indirect Incomes') or uses_cost_centres(catalog,rounding) or value(rounding,'GSTAPPLICABLE').casefold() not in ('not applicable','notapplicable','no'):
            raise TallyError('Explicit non-taxable rounding ledger required.')
    taxable=sum((decimal(r['taxable']) for r in prepared),Decimal(0));total=money(taxable+sum(totals.values())+roundoff)
    if content.get('invoice_total') is None or money(content['invoice_total'])!=total:raise TallyError('Invoice grand total mismatch/missing; difference was not adjusted.')
    result={'operation':'purchase_gst','company':config['company'],'godown':config['godown'],'party':name(party),'ledger':config['purchase_ledger'],
        'voucher_type':'Purchase','date':stamp,'guid':guid,'invoice_number':content['invoice_number'],'company_gstin':company_gstin,
        'gst_registration':name(tax_units[0]) if tax_units else '',
        'company_state_name':value(company,'STATENAME'),
        'supplier_state_name':value(party_details,'STATE') or value(party,'LEDSTATENAME') or value(party,'STATENAME'),
        'supplier_gstin':supplier_gstin,'place_of_supply':company_state,'tax_mode':'inter' if heads==('IGST',) else 'intra',
        'items':prepared,'tax_ledgers':[{'head':h,'ledger':selected[h],'amount':str(money(totals[h]))} for h in heads],
        'taxable_total':str(taxable),'round_off':str(roundoff),'total':str(total),'tax_profile':profile,'source':content,'master_fingerprint':''}
    result['master_fingerprint']=fingerprint(catalog,result)
    return result

def validate(catalog,p,config):
    try:
        expected=compile_purchase(catalog,p['source'],p['tax_profile'],config,p['guid'])
        for original,recomputed in zip(p['items'],expected['items']):recomputed['stock_before']=original['stock_before']
        if expected!=p:raise TallyError('Approved GST payload/masters changed; fresh review required.')
    except (KeyError,TypeError,ValueError) as exc:raise TallyError('Invalid GST payload.') from exc

def gst_xml(p):
    first=p['items'][0]
    legacy={**p,'item':first['item'],'unit':first['unit'],'quantity':first['quantity'],'rate':first['rate']}
    root=ET.fromstring(voucher_xml(legacy));voucher=root.find('.//VOUCHER')
    tag(voucher,'REFERENCE',p['invoice_number']);tag(voucher,'REFERENCEDATE',p['date'].replace('-',''))
    tag(voucher,'PARTYGSTIN',p['supplier_gstin']);tag(voucher,'GSTREGISTRATIONTYPE','Regular');tag(voucher,'CONSIGNEEGSTIN',p['company_gstin'])
    tag(voucher,'CMPGSTIN',p['company_gstin']);tag(voucher,'ISGSTOVERRIDDEN','No')
    for key,text in {'GSTREGISTRATION':p.get('gst_registration'),'CMPGSTSTATE':p.get('company_state_name'),'PLACEOFSUPPLY':p.get('company_state_name'),'STATENAME':p.get('supplier_state_name'),'CMPGSTREGISTRATIONTYPE':'Regular','COUNTRYOFRESIDENCE':'India'}.items():
        if text:tag(voucher,key,text)
    for entry in list(voucher.findall('ALLINVENTORYENTRIES.LIST')):voucher.remove(entry)
    for row in p['items']:
        single={**legacy,'item':row['item'],'quantity':row['quantity'],'rate':row['rate'],'unit':row['unit'],'total':row['taxable']}
        inv=ET.fromstring(voucher_xml(single)).find('.//ALLINVENTORYENTRIES.LIST')
        if decimal(row['discount']):tag(inv,'DISCOUNT',str(decimal(row['discount'])/decimal(row['gross'])*100))
        tag(inv,'GSTOVRDNISREVCHARGEAPPL','No');tag(inv,'GSTOVRDNTAXABILITY','Taxable');tag(inv,'GSTOVRDNTYPEOFSUPPLY','Goods')
        tag(inv,'GSTOVRDNHSNCODE',row['hsn']);tag(inv,'GSTHSNNAME',row['hsn'])
        tag(inv,'GSTITEMUQC',row['uqc']);tag(inv,'GSTITEMUQCUOM',row['unit'])
        tag(inv,'GSTHSNINFERAPPLICABILITY','As per Masters/Company');tag(inv,'GSTRATEINFERAPPLICABILITY','As per Masters/Company')
        source_type=row['gst_source_type'];tag(inv,'GSTSOURCETYPE',source_type);tag(inv,'HSNSOURCETYPE',source_type)
        suffix={'Stock Item':'ITEM','Stock Group':'STOCKGROUP','Ledger':'LEDGER','Group':'GROUP','Company':None}[source_type]
        if suffix:
            tag(inv,'GST'+suffix+'SOURCE',row['gst_source']);tag(inv,'HSN'+suffix+'SOURCE',row['gst_source'])
        for head in ('CGST','SGST/UTGST','IGST'):
            detail=tag(inv,'RATEDETAILS.LIST');tag(detail,'GSTRATEDUTYHEAD',head);tag(detail,'GSTRATEVALUATIONTYPE','Based on Value')
            tag(detail,'GSTRATE',decimal(row['gst_rate'])/(1 if head=='IGST' else 2))
        for head in ('Cess','State Cess'):
            detail=tag(inv,'RATEDETAILS.LIST');tag(detail,'GSTRATEDUTYHEAD',head);tag(detail,'GSTRATEVALUATIONTYPE','&#4; Not Applicable' if head=='Cess' else 'Based on Value');tag(detail,'GSTRATE','0');tag(detail,'GSTRATEPERUNIT','0')
        voucher.append(inv)
    for row in p['tax_ledgers']:
        entry=tag(voucher,'LEDGERENTRIES.LIST');tag(entry,'LEDGERNAME',row['ledger']);tag(entry,'ISDEEMEDPOSITIVE','Yes');tag(entry,'ISPARTYLEDGER','No');tag(entry,'AMOUNT',-decimal(row['amount']))
    if decimal(p['round_off']):
        entry=tag(voucher,'LEDGERENTRIES.LIST');tag(entry,'LEDGERNAME',p['tax_profile']['rounding_ledger']);tag(entry,'ISDEEMEDPOSITIVE','Yes' if decimal(p['round_off'])>0 else 'No');tag(entry,'ISPARTYLEDGER','No');tag(entry,'AMOUNT',-decimal(p['round_off']))
    return ET.tostring(root,encoding='unicode').replace('&amp;#4;','&#4;')

def verify(v,p):
    try:
        if not matches_action(v,p) or any(value(v,k)!=text for k,text in {'DATE':p['date'].replace('-',''),'VOUCHERTYPENAME':'Purchase','PARTYLEDGERNAME':p['party'],'REFERENCE':p['invoice_number'],'REFERENCEDATE':p['date'].replace('-',''),'CMPGSTIN':p['company_gstin'],'PARTYGSTIN':p['supplier_gstin']}.items()):return False
        if value(v,'ISCANCELLED').casefold()=='yes' or value(v,'ISOPTIONAL').casefold()=='yes':return False
        if p.get('gst_registration') and value(v,'GSTREGISTRATION')!=p['gst_registration']:return False
        if p.get('company_state_name') and value(v,'PLACEOFSUPPLY')!=p['company_state_name']:return False
        entries=v.findall('ALLLEDGERENTRIES.LIST') or v.findall('LEDGERENTRIES.LIST')
        expected={p['party']:decimal(p['total']),**{r['ledger']:-decimal(r['amount']) for r in p['tax_ledgers']}}
        if decimal(p['round_off']):expected[p['tax_profile']['rounding_ledger']]=-decimal(p['round_off'])
        # AllLedgerEntries includes the purchase account projected from inventory
        # allocations; LedgerEntries excludes that projection in older exports.
        if any(value(r,'LEDGERNAME')==p['ledger'] for r in entries):expected[p['ledger']]=-decimal(p['taxable_total'])
        if len(entries)!=len(expected) or {value(r,'LEDGERNAME'):decimal(value(r,'AMOUNT')) for r in entries}!=expected:return False
        party=next(r for r in entries if value(r,'LEDGERNAME')==p['party']);bills=[r for r in party.findall('BILLALLOCATIONS.LIST') if value(r,'NAME')]
        if len(bills)!=1 or value(bills[0],'NAME')!=p['guid'] or value(bills[0],'BILLTYPE')!='New Ref' or decimal(value(bills[0],'AMOUNT'))!=decimal(p['total']):return False
        remaining=list(v.findall('ALLINVENTORYENTRIES.LIST'))
        if len(remaining)!=len(p['items']):return False
        for row in p['items']:
            found=None
            for item in remaining:
                if value(item,'STOCKITEMNAME')!=row['item'] or quantity(value(item,'BILLEDQTY'),row['unit'])!=decimal(row['quantity']) or quantity(value(item,'ACTUALQTY'),row['unit'])!=decimal(row['quantity']):continue
                if not value(item,'RATE').endswith('/'+row['unit']) or decimal(value(item,'RATE').rsplit('/',1)[0])!=decimal(row['rate']) or decimal(value(item,'AMOUNT'))!=-decimal(row['taxable']):continue
                batches=item.findall('BATCHALLOCATIONS.LIST');alloc=item.findall('ACCOUNTINGALLOCATIONS.LIST')
                if len(batches)!=1 or len(alloc)!=1 or value(batches[0],'GODOWNNAME')!=p['godown'] or decimal(value(batches[0],'AMOUNT'))!=-decimal(row['taxable']) or quantity(value(batches[0],'ACTUALQTY'),row['unit'])!=decimal(row['quantity']) or quantity(value(batches[0],'BILLEDQTY'),row['unit'])!=decimal(row['quantity']) or value(alloc[0],'LEDGERNAME')!=p['ledger'] or decimal(value(alloc[0],'AMOUNT'))!=-decimal(row['taxable']):continue
                if decimal(row['discount']) and abs(decimal(value(item,'DISCOUNT'))*decimal(row['gross'])/100-decimal(row['discount']))>PAISA/2:continue
                tax_rates=[r for r in item.findall('RATEDETAILS.LIST') if value(r,'GSTRATEDUTYHEAD')]
                rates={};invalid=False
                for r in tax_rates:
                    head=tax_head(value(r,'GSTRATEDUTYHEAD'));rate=decimal(value(r,'GSTRATE'))
                    if head in rates or decimal(value(r,'GSTRATEPERUNIT') or 0):invalid=True;break
                    rates[head]=rate
                    if head not in HEADS and rate:invalid=True;break
                    if head in HEADS and (value(r,'GSTRATEVALUATIONTYPE').casefold() not in ('based on value','on value') or rate!=decimal(row['gst_rate'])/(1 if head=='IGST' else 2)):invalid=True;break
                required={'SGST' if h=='UTGST' else h for h in row['taxes']}
                if invalid or not required.issubset(rates):continue
                if (value(item,'GSTOVRDNHSNCODE') or value(item,'GSTHSNNAME'))!=row['hsn']:continue
                if value(item,'GSTITEMUQC')!=row['uqc'] or value(item,'GSTITEMUQCUOM')!=row['unit']:continue
                if value(item,'GSTOVRDNTAXABILITY')!='Taxable' or value(item,'GSTOVRDNTYPEOFSUPPLY')!='Goods':continue
                found=item;break
            if found is None:return False
            remaining.remove(found)
        return True
    except (TallyError,ValueError,KeyError,TypeError,StopIteration):return False

async def execute(operation,connector,company,identity,p,config,journal_path):
    from app.services.tally_sync_protocol import journal
    if not isinstance(p,dict) or p.get('operation')!='purchase_gst' or p.get('company')!=company:raise TallyError('Invalid GST operation.')
    if operation!='purchase_gst_reconcile':
        try:validate(await connector.catalog(company),p,config)
        except TallyError as exc:return {'status':'needs_review','reason':str(exc)}
    found=[v for v in await connector.collection('Voucher',company,p['date']) if matches_action(v,p)]
    if found:
        if len(found)!=1 or not verify(found[0],p) or not value(found[0],'VOUCHERNUMBER'):return {'status':'needs_review','reason':'Tax-ledger/invoice/line verification mismatch.'}
        return {'status':'verified','voucher_number':value(found[0],'VOUCHERNUMBER'),'tax_ledgers':p['tax_ledgers']}
    if operation=='purchase_gst_validate':return {'status':'ready'}
    if operation=='purchase_gst_reconcile':return {'status':'verification_pending'}
    if operation!='purchase_gst_post':raise TallyError('Unsupported GST operation.')
    # Native Day 5 practice fixtures accepted; the explicit kill switch can still lock writes.
    import os
    if os.getenv('PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED','1')!='1':return {'status':'needs_review','reason':'GST live acceptance pending; posting is locked.'}
    with journal(journal_path) as db:
        inserted=db.execute('INSERT OR IGNORE INTO writes VALUES (?,?)',(identity+':'+p['guid'],'submitting')).rowcount
    if not inserted:return {'status':'verification_pending'}
    try:await connector.post(gst_xml(p))
    except TallyRejected as exc:return {'status':'failed','reason':str(exc)[:300]}
    except TallyError:return {'status':'verification_pending'}
    return await execute('purchase_gst_reconcile',connector,company,identity,p,config,journal_path)
