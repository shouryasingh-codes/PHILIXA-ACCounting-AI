"""Scoped supplier master reads. No model answers, writes, RAG or generated SQL."""
import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.services import tally_sync as sync
from app.services.purchase_identity import exact_master, master_identity
from app.services.tally_connector import TallyError, name, value
from app.services.tally_purchase_history import validate_query
from app.services.tally_stock import resolve_scope
from app.services.tally_sync import refresh_company, saved_snapshot
from app.services.tally_sync_protocol import deserialize_catalog
from app.services.tally_supplier_codec import supplier_rows

logger = logging.getLogger(__name__)


def _fallback_status_text(reason: str | None) -> str:
    """Map a live-refresh failure reason to an accurate saved-data status label."""
    text = (reason or '').casefold()
    if 'helper offline' in text or 'connector offline' in text:
        return 'Saved Tally suppliers (connector offline)'
    if 'tally closed' in text:
        return 'Saved Tally suppliers (Tally closed)'
    if 'company unavailable' in text:
        return 'Saved Tally suppliers (company unavailable)'
    if 'setup needed' in text:
        return 'Saved Tally suppliers (connector update required)'
    if 'timeout' in text:
        return 'Saved Tally suppliers (live read timeout)'
    return 'Saved Tally suppliers (live unavailable)'


def _fmt_qty(val: Decimal) -> str:
    """Format Decimal quantities concisely without losing fractional precision."""
    normalized = val.normalize()
    if normalized == normalized.to_integral_value():
        return str(normalized.quantize(Decimal('1')))
    return format(normalized, 'f')


def _norm_rate(raw: str) -> str | None:
    """Normalize equivalent rate strings like '350' and '350.00' for deduplication."""
    text = (raw or '').strip()
    if not text:
        return None
    try:
        dec = Decimal(text)
    except (InvalidOperation, ValueError):
        return text
    if dec == dec.to_integral_value():
        return str(dec.quantize(Decimal('1')))
    return str(dec.quantize(Decimal('0.01')) if dec.as_tuple().exponent < -2 else dec.normalize())


def _accumulate_history_records(aggregated: dict[tuple[str, str], dict], sup: str, records: list[dict]) -> None:
    """Accumulate positive quantities, units, and distinct rates per (supplier, item)."""
    for rec in records or []:
        item_name = (rec.get('item') or '').strip()
        if not item_name:
            continue
        try:
            qty = Decimal(str(rec.get('quantity') or '0'))
        except (InvalidOperation, ValueError):
            continue
        if qty <= 0:
            continue
        bucket = aggregated.setdefault((sup, item_name), {'qty': Decimal(0), 'unit': '', 'rates': []})
        bucket['qty'] += qty
        if not bucket['unit'] and rec.get('unit'):
            bucket['unit'] = str(rec['unit']).strip()
        rate_str = str(rec.get('rate') or '').strip()
        if rate_str and rate_str not in bucket['rates']:
            bucket['rates'].append(rate_str)


async def _load_cache_items(db, company_id: str, folded_suppliers: dict[str, str]):
    """Aggregate quantities and rates from each supplier's newest ready PurchaseHistoryCache."""
    from app.models.purchase_agent import PurchaseHistoryCache

    cache_rows = (await db.scalars(
        select(PurchaseHistoryCache)
        .where(PurchaseHistoryCache.company_id == company_id, PurchaseHistoryCache.status == 'ready')
        .order_by(PurchaseHistoryCache.collected_at.desc(), PurchaseHistoryCache.updated_at.desc())
    )).all()
    seen_suppliers: set[str] = set()
    aggregated: dict[tuple[str, str], dict] = {}
    for row in cache_rows:
        sup = folded_suppliers.get(((row.query or {}).get('supplier') or '').strip().casefold())
        if not sup or sup in seen_suppliers:
            continue
        seen_suppliers.add(sup)
        _accumulate_history_records(aggregated, sup, (row.data or {}).get('records', []))
    return aggregated, seen_suppliers


async def _load_live_tally_items(db, company, catalog: dict, missing_suppliers: list[str]) -> dict[tuple[str, str], dict]:
    """Query live Tally purchase history for uncached suppliers when item coverage is complete."""
    items = catalog.get('items', []) if catalog else []
    if not 1 <= len(items) <= 100 or not missing_suppliers:
        return {}
    today = datetime.now(ZoneInfo('Asia/Kolkata')).date()
    start = today - timedelta(days=180)
    try:
        items_payload = [{'name': name(i), 'id': master_identity(i)} for i in items]
    except TallyError:
        return {}
    aggregated: dict[tuple[str, str], dict] = {}
    for sup in missing_suppliers[:10]:
        try:
            async with asyncio.timeout(6):
                party = exact_master(catalog, 'supplier', sup)
                query = validate_query({
                    'supplier': name(party),
                    'supplier_id': master_identity(party),
                    'items': items_payload,
                    'from_date': start.isoformat(),
                    'to_date': today.isoformat(),
                })
                manifest = await sync.operation(db, company, 'purchase_history_read', payload=query)
                hashes = manifest.get('hashes')
                if manifest.get('complete') is not True or not isinstance(hashes, list) or not 0 < len(hashes) <= 10:
                    continue
                for page in range(len(hashes)):
                    reply = await sync.operation(db, company, 'purchase_history_read', payload=query,
                                                 generation=manifest['generation'], page=page)
                    entries = reply.get('records')
                    if isinstance(entries, list):
                        _accumulate_history_records(aggregated, sup, entries)
        except Exception:
            continue
    return aggregated


async def _load_action_items(db, company_id: str, folded_suppliers: dict[str, str]):
    """Aggregate quantities and rates from verified TallyAction purchase and receipt vouchers."""
    from app.models.tally import TallyAction
    from app.services.tally_multi_purchase_service import action_lines

    action_rows = (await db.scalars(
        select(TallyAction)
        .where(TallyAction.company_id == company_id, TallyAction.status == 'verified')
        .order_by(TallyAction.created_at.asc())
    )).all()
    aggregated: dict[tuple[str, str], dict] = {}
    for action in action_rows:
        payload = action.payload or {}
        op = payload.get('operation')
        if op not in (None, 'purchase_multi', 'purchase_gst', 'goods_receipt'):
            continue
        sup = folded_suppliers.get((payload.get('party') or '').strip().casefold())
        if not sup:
            continue
        for line in action_lines(payload):
            item_name = (line.get('item') or '').strip()
            if not item_name:
                continue
            try:
                qty = Decimal(str(line.get('quantity') or '0'))
            except (InvalidOperation, ValueError):
                continue
            if qty <= 0:
                continue
            bucket = aggregated.setdefault((sup, item_name), {
                'purchase_qty': Decimal(0), 'receipt_qty': Decimal(0), 'unit': '', 'rates': [],
            })
            if op == 'goods_receipt':
                bucket['receipt_qty'] += qty
            else:
                bucket['purchase_qty'] += qty
            if not bucket['unit'] and line.get('unit'):
                bucket['unit'] = str(line['unit']).strip()
            rate_str = str(line.get('rate') or '').strip()
            if rate_str and rate_str not in bucket['rates']:
                bucket['rates'].append(rate_str)
    return aggregated


async def supplier_purchased_items(db, company, supplier_names, *, catalog=None, live=False):
    """Map company-scoped suppliers to verified purchased items without double-counting cache vs actions."""
    if db is None or not supplier_names:
        return {}
    folded_suppliers = {s.casefold(): s for s in supplier_names if s}
    if not folded_suppliers:
        return {}
    cache_items, covered_suppliers = await _load_cache_items(db, company.id, folded_suppliers)
    if live and catalog:
        uncached = [s for s in supplier_names[:10] if s and s not in covered_suppliers]
        if uncached:
            live_items = await _load_live_tally_items(db, company, catalog, uncached)
            for key, bucket in live_items.items():
                cache_items.setdefault(key, bucket)
    action_items = await _load_action_items(db, company.id, folded_suppliers)
    by_supplier: dict[str, list[str]] = {}
    for sup, item_name in sorted(set(cache_items) | set(action_items)):
        c = cache_items.get((sup, item_name))
        a = action_items.get((sup, item_name))
        c_qty = c['qty'] if c else Decimal(0)
        a_purch_qty = a['purchase_qty'] if a else Decimal(0)
        receipt_qty = a['receipt_qty'] if a else Decimal(0)
        if c_qty >= a_purch_qty:
            purch_qty = c_qty
            unit = (c['unit'] if c else '') or (a['unit'] if a else '')
            raw_rates = list(c['rates']) if c else []
        else:
            purch_qty = a_purch_qty
            unit = (a['unit'] if a else '') or (c['unit'] if c else '')
            raw_rates = list(a['rates']) if a else []
        if receipt_qty > 0 and a:
            raw_rates = raw_rates + list(a['rates'])
        rates: list[str] = []
        for raw_rate in raw_rates:
            norm = _norm_rate(raw_rate)
            if norm and norm not in rates:
                rates.append(norm)
        unit_suffix = f" {unit}" if unit else ''
        if purch_qty > 0 and receipt_qty > 0:
            qty_text = f"{_fmt_qty(purch_qty)}{unit_suffix} Purchase + {_fmt_qty(receipt_qty)}{unit_suffix} Receipt Note"
        elif purch_qty > 0:
            qty_text = f"{_fmt_qty(purch_qty)}{unit_suffix}"
        else:
            qty_text = f"{_fmt_qty(receipt_qty)}{unit_suffix} Receipt Note"
        rate_suffix = ' @ ' + ' / '.join(f'₹{r}' for r in rates) if rates else ''
        open_parens = item_name.count('(') - item_name.count(')')
        display_name = item_name + (')' * open_parens) if open_parens > 0 else item_name
        by_supplier.setdefault(sup, []).append(f"{display_name} ({qty_text}{rate_suffix})")
    return by_supplier


def choice(parsed, company, ledger, multiple_companies=False):
    btn_label = f"{company.name} / {name(ledger)}" if multiple_companies else name(ledger)
    return {'name': btn_label, 'command': {
        'intent': 'supplier_read', 'fields': {'company_id': company.id, 'party_name': name(ledger)}}}


async def read_suppliers(db, principal, parsed):
    if parsed.unsupported_reason:
        return {'response': parsed.unsupported_reason}
    scope = await resolve_scope(db, principal, parsed)
    if not scope:
        return {'response': 'Permitted Tally company nahi mili. Owner/admin se company access approve karwayein.', 'connect_tally': True}
    if parsed.company_scope == 'named' and not parsed.company_query and not parsed.company_id:
        return {'response': 'Kaunsi Tally company? Company ka naam bataiye.'}
    if parsed.company_query and not parsed.company_id and len(scope) > 1:
        return {'response': 'Company naam ambiguous hai; company select karein.', 'tally_choices': [
            {'name': c.name, 'command': {'intent': parsed.intent, 'fields': {'company_id': c.id, 'party_name': parsed.party_name}}} for c in scope]}
    if parsed.intent == 'supplier_read' and not parsed.party_name:
        return {'response': 'Kis supplier ki details? Naam bataiye.'}
    lines, choices, results = [], [], []
    for company in scope:
        live = False
        live_catalog = None
        live_complete = None
        fallback_reason = None
        try:
            live = await refresh_company(db, company)
        except (TallyError, TimeoutError) as exc:
            logger.warning("Supplier live refresh failed for company %s: %s", company.name, exc)
            fallback_reason = 'timeout' if isinstance(exc, TimeoutError) else str(exc)
        if not live and fallback_reason is None and db is not None:
            # refresh_company returns False without touching Tally when a lock or uncertain
            # write blocks publishing; perform a read-only live capture without updating TallySnapshot.
            try:
                live_data = await sync.capture_snapshot(db, company)
                live_catalog = deserialize_catalog(live_data['catalog'])
                live_complete = 'groups' in live_data['catalog']
                live = True
            except (TallyError, TimeoutError) as exc:
                logger.warning("Read-only live supplier capture failed for company %s: %s", company.name, exc)
                fallback_reason = 'timeout' if isinstance(exc, TimeoutError) else str(exc)
        try:
            if live_catalog is not None:
                catalog = live_catalog
                complete = bool(live_complete)
            else:
                snapshot = await saved_snapshot(db, company)
                if not snapshot:
                    raise TallyError('No saved supplier data')
                catalog = deserialize_catalog(snapshot.catalog)
                complete = 'groups' in snapshot.catalog
            suppliers = supplier_rows(catalog)
            query = (parsed.party_name or '').strip().casefold()
            matches = suppliers
            if parsed.intent == 'supplier_read':
                exact = [l for l in suppliers if name(l).casefold() == query]
                matches = exact or [l for l in suppliers if query in name(l).casefold()]
            # Re-check grants after transport before releasing ledger data.
            if company.id not in {c.id for c in await resolve_scope(db, principal, parsed)}:
                raise TallyError('Company access changed')
            if live_catalog is not None:
                await sync.bound_device(db, company)
            elif await saved_snapshot(db, company) is None:
                raise TallyError('Device access changed')
            purchased_by_supplier = await supplier_purchased_items(
                db, company, [name(l) for l in matches[:100]], catalog=catalog, live=live)
            source = 'live' if live else 'saved'
            status_text = "Tally live suppliers" if live else _fallback_status_text(fallback_reason)
            lines.append(f"**{company.name}** — {status_text}")
            if not complete:
                lines.append('Older connector: direct Sundry Creditors ledgers only; subgroup coverage unverified. Connector update required for complete list.')
            if not matches:
                if query:
                    others = [l for l in catalog['ledgers'] if name(l).casefold() == query]
                    lines.append(f"**{parsed.party_name}**: ledger exists under `{value(others[0], 'PARENT')}`; supplier classification not verified." if len(others) == 1 else 'Matching supplier nahi mila.')
                else:
                    lines.append('Is company mein koi matching supplier nahi mila.')
            elif parsed.intent == 'supplier_read' and len(matches) == 1:
                ledger = matches[0]
                lines.extend(['', f"### {name(ledger)}", f"- **Tally group:** {value(ledger, 'PARENT')}"])
                for label, tag in [('Phone', 'LEDGERPHONE'), ('Mobile', 'LEDGERMOBILE'), ('Email', 'EMAIL'), ('Opening balance', 'OPENINGBALANCE'), ('Closing balance', 'CLOSINGBALANCE')]:
                    field = value(ledger, tag)
                    if field:
                        lines.append(f"- **{label}:** {field}")
                if db is not None and purchased_by_supplier.get(name(ledger)):
                    lines.append('- **Purchased items:** ' + ', '.join(purchased_by_supplier[name(ledger)]))
                results.append({'company_id': company.id, 'company': company.name, 'name': name(ledger), 'group': value(ledger, 'PARENT'), 'data_source': source})
            else:
                multiple_cos = len(scope) > 1
                if parsed.intent == 'supplier_read' and query:
                    lines.append(f"'{parsed.party_name}' se match hote hue {len(matches)} suppliers mile — neeche se select karein:")
                else:
                    item_filter = (parsed.item_name or '').strip()
                    item_key = item_filter.casefold()
                    filtered_matches = ([
                        l for l in matches
                        if any(item_key in entry.casefold() for entry in purchased_by_supplier.get(name(l), []))
                    ] if parsed.intent == 'supplier_list' and item_key and item_key != '*' and db is not None else [])
                    if filtered_matches:
                        lines.append(f"\n**{item_filter}** aapne in suppliers se kharida hai:\n")
                        for l in filtered_matches[:25]:
                            lines.append(f"  • {name(l)}")
                            matching_items = [e for e in purchased_by_supplier.get(name(l), []) if item_key in e.casefold()]
                            lines.append(f"    Stock/Items: {', '.join(matching_items)}")
                        matches = filtered_matches
                    else:
                        if item_key and item_key != '*':
                            lines.append(f"\n**{item_filter}** ke liye kisi supplier se verified purchase record nahi mila. Saare {len(matches)} suppliers:\n")
                        else:
                            lines.append(f"\nAapke paas kul **{len(matches)} suppliers** (Sundry Creditors) hain:\n")
                        for i, l in enumerate(matches[:25], 1):
                            lines.append(f"  • {name(l)}")
                            if db is not None:
                                items_summary = purchased_by_supplier.get(name(l))
                                lines.append(f"    Stock/Items: {', '.join(items_summary)}" if items_summary else "    Stock/Items: Koi verified purchase record nahi mila")
                        if len(matches) > 25:
                            lines.append(f"  ...aur {len(matches) - 25} suppliers")
                choices.extend(choice(parsed, company, l, multiple_cos) for l in matches[:100])
                if len(matches) > 100:
                    lines.append('Pehle 100 suppliers dikhaye gaye hain; kisi khas supplier ke liye uska naam likhkar search karein.')
        except TallyError:
            lines.append(company.name + ': supplier data unavailable; connection/company access check karein.')
    return {'response': '\n'.join(lines), 'tally_choices': choices, 'supplier_results': results}
