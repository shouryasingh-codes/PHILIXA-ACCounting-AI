"""Read-only native purchase evidence. Shared by server and Windows helper."""
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from app.services.tally_connector import TallyError, name, value, decimal, quantity
from app.services.purchase_identity import exact_master, master_identity, master_fingerprint

MAX_RECORDS = 5000
PAGE_SIZE = 100


def validate_query(query):
    expected = {'supplier', 'supplier_id', 'items', 'from_date', 'to_date'}
    if not isinstance(query, dict) or set(query) != expected:
        raise TallyError('Invalid purchase history query.')
    if any(not isinstance(query[k], str) or not query[k] or len(query[k]) > 250 for k in ('supplier', 'supplier_id')):
        raise TallyError('Invalid history supplier.')
    try:
        start, end = date.fromisoformat(query['from_date']), date.fromisoformat(query['to_date'])
    except (ValueError, TypeError, KeyError):
        raise TallyError('Invalid history dates.')
    if not 0 <= (end-start).days <= 180:
        raise TallyError('History window exceeds 180 days.')
    if not isinstance(query['items'], list) or not 1 <= len(query['items']) <= 100:
        raise TallyError('Invalid history items.')
    for item in query['items']:
        if not isinstance(item, dict) or set(item) != {'name', 'id'} or any(not isinstance(v, str) or not v or len(v) > 250 for v in item.values()):
            raise TallyError('Invalid history item identity.')
    return query


def digest_query(query):
    return hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()


def normalise_vouchers(vouchers, catalog, query):
    validate_query(query)
    party = exact_master(catalog, 'supplier', query['supplier'])
    if master_identity(party) != query['supplier_id']:
        raise TallyError('History supplier identity changed.')
    items = {}
    for requested in query['items']:
        item = exact_master(catalog, 'item', requested['name'])
        if master_identity(item) != requested['id']:
            raise TallyError('History item identity changed.')
        items[requested['name']] = item
    records, issues = [], []
    for voucher in vouchers:
        if value(voucher, 'ISCANCELLED').lower() == 'yes' or value(voucher, 'ISOPTIONAL').lower() == 'yes':
            continue
        if value(voucher, 'VOUCHERTYPENAME') != 'Purchase' or value(voucher, 'PARTYLEDGERNAME') != query['supplier']:
            continue
        raw = value(voucher, 'DATE')
        try:
            stamp = datetime.strptime(raw, '%Y%m%d').date().isoformat() if len(raw) == 8 else date.fromisoformat(raw).isoformat()
        except ValueError:
            issues.append('Purchase date unreadable.');continue
        if not query['from_date'] <= stamp <= query['to_date']:
            continue
        guid = value(voucher, 'GUID')
        alteration = value(voucher, 'ALTERID')
        if not guid or not alteration:
            issues.append('Voucher stable identity/alteration missing.');continue
        lines = voucher.findall('ALLINVENTORYENTRIES.LIST')
        for entry in lines:
            item_name = value(entry, 'STOCKITEMNAME')
            if item_name not in items:
                continue
            item = items[item_name];unit = value(item, 'BASEUNITS')
            try:
                if sum(value(v, 'STOCKITEMNAME') == item_name for v in lines) != 1:
                    raise TallyError('Repeated item rows require review.')
                rate_text = value(entry, 'RATE');rate_part, separator, rate_unit = rate_text.partition('/')
                if not separator or rate_unit.strip() != unit:
                    raise TallyError('History unit conversion unsupported.')
                qty = quantity(value(entry, 'BILLEDQTY'), unit)
                rate = decimal(rate_part)
                if qty <= 0 or rate <= 0:raise TallyError('Non-positive purchase history.')
                discount = value(entry, 'DISCOUNT') or '0'
                # Discount semantics must be explicit; never turn a discounted rate into a default.
                if decimal(discount.rstrip('%').strip()) != 0:
                    raise TallyError('Discounted historical line needs review.')
                amount = abs(decimal(value(entry, 'AMOUNT')))
                if abs(amount - qty*rate) > Decimal('.01'):
                    raise TallyError('History amount/rate treatment ambiguous.')
            except TallyError as exc:
                issues.append(str(exc));continue
            records.append(dict(voucher_id=guid, alteration_id=alteration, invoice_number=value(voucher, 'REFERENCE'),
                entry_date=stamp, supplier=query['supplier'], supplier_id=query['supplier_id'],
                supplier_fingerprint=master_fingerprint(party), item=item_name, item_id=master_identity(item),
                item_fingerprint=master_fingerprint(item), quantity=str(qty), unit=unit, rate=str(rate),
                amount=str(amount), discount=discount))
    records.sort(key=lambda r:(r['entry_date'],r['voucher_id'],r['item_id']),reverse=True)
    if len(records) > MAX_RECORDS:issues.append('History record limit exceeded.')
    return records[:MAX_RECORDS], sorted(set(issues))


async def execute(connector, company, identity, query, generation, page, journal_path):
    from app.services.tally_sync_protocol import journal
    import time
    query = validate_query(query)
    binding = dict(company=company,identity=identity,query=digest_query(query))
    if generation is None:
        catalog = await connector.catalog(company)
        vouchers = await connector.collection('Voucher',company,query['to_date'],from_date=query['from_date'],
                                               supplier_query=query['supplier'])
        records, issues = normalise_vouchers(vouchers,catalog,query)
        generation = uuid.uuid4().hex
        pages = [records[i:i+PAGE_SIZE] for i in range(0,len(records),PAGE_SIZE)]
        captured = datetime.now(timezone.utc).isoformat()
        stored = dict(binding=binding, pages=pages, collected_at=captured, issues=issues)
        with journal(journal_path) as db:
            db.execute('DELETE FROM snapshots WHERE created < ?', (time.time()-600,))
            db.execute('INSERT INTO snapshots VALUES (?,?,?)', ('history:'+generation,json.dumps(stored),time.time()))
        return dict(**binding,generation=generation,collected_at=captured,complete=not issues,issues=issues,
                    hashes=[hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest() for p in pages],count=len(records))
    if not isinstance(generation,str) or len(generation)!=32 or type(page) is not int:
        raise TallyError('Invalid history page.')
    with journal(journal_path) as db:
        record=db.execute('SELECT payload,created FROM snapshots WHERE key=?',('history:'+generation,)).fetchone()
    if not record or record[1] < time.time()-600:raise TallyError('History capture expired.')
    stored=json.loads(record[0])
    if stored['binding']!=binding or not 0<=page<len(stored['pages']):raise TallyError('History page scope mismatch.')
    return dict(**binding,generation=generation,page=page,records=stored['pages'][page])
