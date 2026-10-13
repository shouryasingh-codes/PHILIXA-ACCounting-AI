"""Native Tally XML only. No model-generated XML, redirects or public endpoints."""
import os
import hashlib
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET
import httpx


class TallyError(Exception):
    pass


class TallyRejected(TallyError):
    """Explicit zero-created/zero-altered import failure, safe to report as rejected."""


def tag(parent, name, value=None, **attrs):
    node = ET.SubElement(parent, name, attrs)
    if value is not None:
        node.text = str(value)
    return node


def value(node, name):
    return (node.findtext(name) or '').strip()


def name(node):
    return node.get('NAME') or value(node, 'NAME')


def decimal(value_):
    try:
        amount = Decimal(str(value_).replace(',', '').strip())
        if not amount.is_finite():
            raise InvalidOperation
        return amount
    except (InvalidOperation, ValueError):
        raise TallyError('Tally quantity/amount format supported nahi hai.')


def quantity(text, unit):
    match = re.fullmatch(r'\s*([+-]?[\d,]+(?:\.\d+)?)\s+' + re.escape(unit) + r'\s*', text)
    if not match:
        raise TallyError('Stock quantity/unit format supported nahi hai.')
    return decimal(match[1])


def stock_quantity(item, unit):
    if value(item,'BASEUNITS') != unit:
        raise TallyError('Stock item ki base unit match nahi hui.')
    numeric = item.findtext('PHILIXACLOSINGQTY')
    if numeric is not None and numeric.strip():
        return decimal(numeric)
    return quantity(value(item,'CLOSINGBALANCE'), unit)


def parse_xml(raw):
    # Tally may return numeric references for XML-forbidden control characters.
    if len(raw) > 10_000_000 or re.search(br'<!\s*(DOCTYPE|ENTITY)', raw.replace(b'\x00',b''), re.I):
        raise TallyError('Unsafe ya oversized Tally response.')
    raw = re.sub(br'&#(?:[0-8]|1[124-9]|2[0-9]|3[01]);', b'', raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise TallyError('Tally se valid XML nahi mila.')
    error = root.findtext('.//LINEERROR')
    if root.findtext('.//ERRORS') not in (None,'0') and root.findtext('.//CREATED') == '0' and root.findtext('.//ALTERED') in (None,'0'):
        raise TallyRejected((error or 'Tally import reject hui; zero vouchers created.')[:300])
    if error or root.findtext('./HEADER/STATUS') == '0':
        if root.findtext('.//CREATED') == '0' and root.findtext('.//ALTERED') in (None,'0'):
            raise TallyRejected((error or 'Tally import reject hui.')[:300])
        raise TallyError((error or 'Tally request reject hui.')[:300])
    return root


class TallyConnector:
    def __init__(self, port=None):
        host = os.getenv('PHILIXA_TALLY_HOST', 'host.docker.internal')
        if host not in {'host.docker.internal', '127.0.0.1', 'localhost'}:
            raise TallyError('Sirf local Tally endpoint supported hai.')
        port = int(port or os.getenv('PHILIXA_TALLY_PORT', '9000'))
        if not 1 <= port <= 65535:
            raise TallyError('Tally port invalid hai.')
        self.url = f'http://{host}:{port}'

    async def post(self, xml):
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
                async with client.stream('POST', self.url, content=xml.encode('utf-8'),
                                         headers={'Content-Type': 'text/xml; charset=utf-8'}) as response:
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 10_000_000:
                            raise TallyError('Tally response bahut badi hai.')
                        chunks.append(chunk)
                    return parse_xml(b''.join(chunks))
        except httpx.HTTPError:
            raise TallyError('Tally reachable nahi hai. Tally kholkar HTTP server aur company check karein.')

    async def collection(self, kind, company=None, voucher_date=None, item_query=None):
        root = ET.Element('ENVELOPE')
        header = tag(root, 'HEADER')
        for key, text in [('VERSION','1'),('TALLYREQUEST','Export'),('TYPE','Collection'),('ID','PhilixaRead')]:
            tag(header,key,text)
        desc = tag(tag(root,'BODY'),'DESC')
        variables = tag(desc,'STATICVARIABLES')
        tag(variables,'SVEXPORTFORMAT','$$SysName:XML')
        if company:
            tag(variables,'SVCURRENTCOMPANY',company)
        if voucher_date:
            for key in ('SVFROMDATE','SVTODATE'):
                tag(variables,key,voucher_date.replace('-',''), TYPE='Date')
        if kind == 'StockItem' and voucher_date:
            # Current-period closing stock, not just movements on the as-of day.
            variables.remove(variables.find('SVFROMDATE'))
            tag(variables, 'SVFROMDATE', '19000101', TYPE='Date')
            tag(variables, 'SVCURRENTDATE', voucher_date.replace('-',''), TYPE='Date')
        message = tag(tag(desc,'TDL'),'TDLMESSAGE')
        collection = tag(message,'COLLECTION', NAME='PhilixaRead', ISMODIFY='No')
        tag(collection,'TYPE',kind)
        methods = ('Name','GUID','BaseUnits','AdditionalUnits','ClosingBalance') if kind == 'StockItem' and item_query else ('*',)
        for method in methods: tag(collection,'NATIVEMETHOD',method)
        if kind == 'Ledger':
            tag(collection,'COMPUTE','PhilixaMasterID : $MasterID')
            tag(collection,'NATIVEMETHOD','PhilixaMasterID')
        if kind == 'StockItem':
            if item_query:
                # Quoted TDL literal, never model-generated expression/XML.
                if any(c in item_query for c in ('"', '\\', '\n', '\r')):
                    raise TallyError('Item query contains unsupported characters; shorter item name use karein.')
                literal = item_query
                tag(collection, 'FILTER', 'PhilixaItemFilter')
                tag(message, 'SYSTEM', f'$$Lower:$Name Contains $$Lower:"{literal}"', TYPE='Formulae', NAME='PhilixaItemFilter')
            tag(collection,'NATIVEMETHOD','ClosingBalance')
            tag(collection,'COMPUTE','PhilixaClosingQty : $$Number:$ClosingBalance')
            tag(collection,'NATIVEMETHOD','PhilixaClosingQty')
        if kind == 'Voucher':
            for method in ('AllInventoryEntries.*','AllInventoryEntries.BatchAllocations.*',
                           'AllInventoryEntries.AccountingAllocations.*','AllLedgerEntries.*',
                           'AllLedgerEntries.BillAllocations.*'):
                tag(collection,'NATIVEMETHOD',method)
        result = await self.post(ET.tostring(root,encoding='unicode'))
        rows = result.findall('.//' + kind.upper())
        # Tally also emits unnamed master tags in response metadata. Those are
        # not masters (and must not count as a second godown in setup checks).
        return rows if kind == 'Voucher' else [row for row in rows if name(row)]

    async def catalog(self, company):
        companies = await self.collection('Company')
        selected = [c for c in companies if name(c) == company]
        if len(selected) != 1:
            raise TallyError('Selected company Tally mein loaded nahi hai.')
        # Fail closed: do not infer non-GST from an absent tax flag.
        non_gst = value(selected[0],'ISGSTON').casefold() == 'no'
        items = await self.collection('StockItem', company)
        ledgers = await self.collection('Ledger', company)
        godowns = await self.collection('Godown', company)
        units = await self.collection('Unit', company)
        groups = await self.collection('Group', company)
        stock_groups = await self.collection('StockGroup',company)
        tax_units = await self.collection('TaxUnit',company) if not non_gst else []
        return {'companies':selected,'stock_groups':stock_groups,'tax_units':tax_units,'non_gst':non_gst,
                'cost_centres_enabled':value(selected[0],'ISCOSTCENTRESON').casefold() != 'no',
                'items':items, 'ledgers':ledgers, 'godowns':godowns, 'units':units, 'groups':groups}


def voucher_xml(payload):
    """Single-item item-invoice schema based on TallyHelp sample XML."""
    root = ET.Element('ENVELOPE')
    tag(tag(root,'HEADER'),'TALLYREQUEST','Import Data')
    body = tag(tag(root,'BODY'),'IMPORTDATA')
    desc = tag(body,'REQUESTDESC')
    tag(desc,'REPORTNAME','Vouchers')
    tag(tag(desc,'STATICVARIABLES'),'SVCURRENTCOMPANY',payload['company'])
    message = tag(tag(body,'REQUESTDATA'),'TALLYMESSAGE')
    kind = payload['voucher_type']
    purchase = kind == 'Purchase'
    voucher = tag(message,'VOUCHER', REMOTEID=payload['guid'], VCHTYPE=kind, ACTION='Create', OBJVIEW='Invoice Voucher View')
    for key, text in {'DATE':payload['date'].replace('-',''), 'GUID':payload['guid'],
                      'VOUCHERTYPENAME':kind,'PARTYLEDGERNAME':payload['party'],
                      'PERSISTEDVIEW':'Invoice Voucher View','ISINVOICE':'Yes',
                      'NARRATION':'Philixa action ' + payload['guid']}.items():
        tag(voucher,key,text)
    total = decimal(payload['total'])
    inv_amount = -total if purchase else total
    party = tag(voucher,'LEDGERENTRIES.LIST')
    tag(party,'LEDGERNAME',payload['party'])
    tag(party,'ISDEEMEDPOSITIVE','No' if purchase else 'Yes')
    tag(party,'ISPARTYLEDGER','Yes')
    tag(party,'AMOUNT',-inv_amount)
    bill = tag(party,'BILLALLOCATIONS.LIST')
    tag(bill,'NAME',payload['guid'])
    tag(bill,'BILLTYPE','New Ref')
    tag(bill,'AMOUNT',-inv_amount)
    item = tag(voucher,'ALLINVENTORYENTRIES.LIST')
    tag(item,'STOCKITEMNAME',payload['item'])
    tag(item,'ISDEEMEDPOSITIVE','Yes' if purchase else 'No')
    tag(item,'RATE',f"{payload['rate']}/{payload['unit']}")
    qty = f"{payload['quantity']} {payload['unit']}"
    for key,text in [('AMOUNT',inv_amount),('ACTUALQTY',qty),('BILLEDQTY',qty)]:
        tag(item,key,text)
    batch = tag(item,'BATCHALLOCATIONS.LIST')
    for key,text in [('GODOWNNAME',payload['godown']),('BATCHNAME','Primary Batch'),
                     ('AMOUNT',inv_amount),('ACTUALQTY',qty),('BILLEDQTY',qty)]:
        tag(batch,key,text)
    allocation = tag(item,'ACCOUNTINGALLOCATIONS.LIST')
    tag(allocation,'LEDGERNAME',payload['ledger'])
    tag(allocation,'ISDEEMEDPOSITIVE','Yes' if purchase else 'No')
    tag(allocation,'AMOUNT',inv_amount)
    return ET.tostring(root,encoding='unicode')


def matches_action(voucher, p):
    if value(voucher,'GUID') == p['guid']:return True
    # Tally may assign its own native GUID on import. Require both explicit
    # action markers; matching accounting amounts alone never establishes identity.
    # Native exports contain a compact LEDGERENTRIES row with empty bill
    # placeholders, and the actual bill references in ALLLEDGERENTRIES.
    parties=[row for row in voucher.findall('ALLLEDGERENTRIES.LIST')
             if value(row,'LEDGERNAME')==p['party']]
    if not parties:
        parties=[row for row in voucher.findall('LEDGERENTRIES.LIST')
                 if value(row,'LEDGERNAME')==p['party']]
    bills=parties[0].findall('BILLALLOCATIONS.LIST') if len(parties)==1 else []
    bills=[row for row in bills if value(row,'NAME')]
    return (bool(value(voucher,'GUID')) and value(voucher,'NARRATION')=='Philixa action '+p['guid']
            and len(parties)==1 and len(bills)==1
            and value(bills[0],'NAME')==p['guid'])


def verify_voucher(voucher, p):
    """A GUID alone is insufficient: compare the approved financial/inventory fields."""
    if value(voucher,'ISCANCELLED').casefold() == 'yes' or value(voucher,'ISOPTIONAL').casefold() == 'yes':
        return False
    if not matches_action(voucher,p):return False
    if any(value(voucher,k) != expected for k,expected in {
        'DATE':p['date'].replace('-',''),'VOUCHERTYPENAME':p['voucher_type'],
        'PARTYLEDGERNAME':p['party']}.items()):
        return False
    items = voucher.findall('ALLINVENTORYENTRIES.LIST')
    parties = voucher.findall('LEDGERENTRIES.LIST') or voucher.findall('ALLLEDGERENTRIES.LIST')
    if len(items) != 1 or len(parties) != 1:
        return False
    item = items[0]
    allocations = item.findall('ACCOUNTINGALLOCATIONS.LIST')
    batches = item.findall('BATCHALLOCATIONS.LIST')
    if len(allocations) != 1 or len(batches) != 1:
        return False
    try:
        amount = decimal(p['total']) * (-1 if p['voucher_type']=='Purchase' else 1)
        return (value(item,'STOCKITEMNAME') == p['item']
                and quantity(value(item,'ACTUALQTY'),p['unit']) == decimal(p['quantity'])
                and quantity(value(item,'BILLEDQTY'),p['unit']) == decimal(p['quantity'])
                and decimal(value(item,'RATE').split('/')[0]) == decimal(p['rate'])
                and value(item,'RATE').partition('/')[2].strip() == p['unit']
                and decimal(value(item,'AMOUNT')) == amount
                and value(allocations[0],'LEDGERNAME') == p['ledger']
                and decimal(value(allocations[0],'AMOUNT')) == amount
                and value(batches[0],'GODOWNNAME') == p['godown']
                and value(batches[0],'BATCHNAME') == 'Primary Batch'
                and quantity(value(batches[0],'ACTUALQTY'),p['unit']) == decimal(p['quantity'])
                and quantity(value(batches[0],'BILLEDQTY'),p['unit']) == decimal(p['quantity'])
                and decimal(value(batches[0],'AMOUNT')) == amount
                and value(parties[0],'LEDGERNAME') == p['party']
                and decimal(value(parties[0],'AMOUNT')) == -amount)
    except TallyError:
        return False


def company_identity(row):
    return value(row, 'GUID') or 'name:' + hashlib.sha256(name(row).encode()).hexdigest()


def stock_row(item, units):
    unit = value(item, 'BASEUNITS')
    raw = value(item, 'CLOSINGBALANCE')
    simple = [u for u in units if name(u) == unit and value(u, 'ISSIMPLEUNIT').lower() == 'yes']
    numeric = None
    limitation = None
    if len(simple) == 1 and value(item, 'ADDITIONALUNITS') in ('', 'Not Applicable'):
        numeric = str(stock_quantity(item, unit))
    else:
        limitation = 'Compound/alternate unit: raw Tally quantity; no conversion or total.'
    return {'item': name(item), 'unit': unit, 'quantity': numeric, 'raw_quantity': raw, 'limitation': limitation}


async def local_operation(operation, company=None, identity=None, as_of=None, port=None, item_query=None):
    """Shared by developer transport and packaged helper; only two read operations."""
    connector = TallyConnector(port=port)
    companies = await connector.collection('Company')
    descriptors = [{'identity': company_identity(c), 'name': name(c)} for c in companies]
    if operation == 'discover':
        return {'companies': descriptors}
    if operation != 'stock':
        raise TallyError('Unsupported helper operation.')
    matches = [c for c in descriptors if c['identity'] == identity and c['name'] == company]
    if len(matches) != 1 or sum(c['name'] == company for c in descriptors) != 1:
        raise TallyError('Company unavailable or renamed; connection approval dobara karein.')
    items = await connector.collection('StockItem', company, as_of, item_query=item_query)
    units = await connector.collection('Unit', company)
    return {'company': company, 'identity': identity, 'items': [stock_row(i, units) for i in items], 'as_of': as_of}


