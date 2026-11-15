"""Bounded read-only supplier purchases, using the existing native history protocol."""
import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.services import purchase_draft_service as drafts, tally_sync as sync
from app.services.tally_connector import TallyError, name, value
from app.services.purchase_identity import exact_master, master_identity, master_fingerprint
from app.services.tally_sync_protocol import deserialize_catalog
from app.services.tally_purchase_history import validate_query, digest_query


def unavailable(reason):
    return {'response': reason, 'status': 'needs_input', 'data_source': 'unavailable',
            'history_complete': False, 'response_kind': 'purchase_history', 'can_resume': False}


def _verified_action_records(actions, supplier_name: str, start_iso: str, end_iso: str,
                             existing_vouchers: set[str], *, allowed_ops: tuple[str, ...],
                             after_ts=None) -> list[dict]:
    """Convert verified TallyAction purchase/receipt vouchers into normalized history rows."""
    from app.services.tally_multi_purchase_service import action_lines

    out: list[dict] = []
    target = supplier_name.strip().casefold()
    for action in actions:
        payload = action.payload or {}
        op = payload.get('operation')
        if op not in allowed_ops:
            continue
        if op != 'goods_receipt' and after_ts is not None and action.created_at <= after_ts:
            continue
        if (payload.get('party') or '').strip().casefold() != target:
            continue
        entry_date = (payload.get('date') or '').strip()
        if not (start_iso <= entry_date <= end_iso):
            continue
        voucher_id = (payload.get('guid') or '').strip() or f'action-{action.created_at.isoformat()}'
        if voucher_id in existing_vouchers:
            continue
        invoice_no = (payload.get('invoice_number') or payload.get('tracking') or '').strip()
        label = 'Receipt Note' if op == 'goods_receipt' else 'Verified Tally Voucher'
        for line in action_lines(payload):
            item_name = (line.get('item') or '').strip()
            if not item_name:
                continue
            try:
                qty = Decimal(str(line.get('quantity') or '0'))
                rate = Decimal(str(line.get('rate') or '0'))
            except (InvalidOperation, ValueError):
                continue
            if qty <= 0 or rate < 0:
                continue
            amount = (qty * rate).quantize(Decimal('0.01'))
            out.append({
                'voucher_id': voucher_id,
                'invoice_number': invoice_no,
                'entry_date': entry_date,
                'supplier': supplier_name,
                'item': item_name,
                'quantity': str(qty.normalize() if qty == qty.to_integral_value() else qty),
                'unit': str(line.get('unit') or '').strip(),
                'rate': str(rate.quantize(Decimal('0.01')) if rate != rate.to_integral_value() else rate.quantize(Decimal('1'))),
                'amount': str(amount),
                'source_label': label,
            })
    return out


async def _load_db_history(db, company_id: str, supplier_name: str, start_iso: str, end_iso: str,
                           *, include_cache: bool, existing_vouchers: set[str]):
    """Load verified TallyAction rows and optionally PurchaseHistoryCache rows from PostgreSQL."""
    if not hasattr(db, 'scalars'):
        return [], None
    from app.models.tally import TallyAction
    from app.models.purchase_agent import PurchaseHistoryCache

    cache_records: list[dict] = []
    cache_collected_at = None
    cache_ts = None
    seen_vouchers = set(existing_vouchers)
    if include_cache:
        cache_rows = (await db.scalars(
            select(PurchaseHistoryCache)
            .where(PurchaseHistoryCache.company_id == company_id, PurchaseHistoryCache.status == 'ready')
            .order_by(PurchaseHistoryCache.collected_at.desc(), PurchaseHistoryCache.updated_at.desc())
        )).all()
        target = supplier_name.strip().casefold()
        for row in cache_rows:
            if ((row.query or {}).get('supplier') or '').strip().casefold() != target:
                continue
            raw_recs = (row.data or {}).get('records') or []
            filtered = [r for r in raw_recs if start_iso <= (r.get('entry_date') or '') <= end_iso]
            if filtered or cache_collected_at is None:
                cache_records = filtered
                cache_ts = row.collected_at
                cache_collected_at = row.collected_at.isoformat() if row.collected_at else None
                for r in filtered:
                    if r.get('voucher_id'):
                        seen_vouchers.add(str(r['voucher_id']))
                if filtered:
                    break
    actions = (await db.scalars(
        select(TallyAction)
        .where(TallyAction.company_id == company_id, TallyAction.status == 'verified')
        .order_by(TallyAction.created_at.desc())
    )).all()
    allowed_ops = ('goods_receipt', 'purchase_multi', 'purchase_gst') if include_cache else ('goods_receipt',)
    action_records = _verified_action_records(
        actions, supplier_name, start_iso, end_iso, seen_vouchers,
        allowed_ops=allowed_ops, after_ts=cache_ts if include_cache else None)
    return cache_records + action_records, cache_collected_at


async def read(db, principal, company_id, supplier, from_date=None, to_date=None):
    # A default search window is explicitly labelled, never an invented invoice date.
    today = datetime.now(ZoneInfo('Asia/Kolkata')).date()
    try:
        end = today if to_date is None else today.fromisoformat(to_date)
        start = end-timedelta(days=180) if from_date is None else today.fromisoformat(from_date)
    except (ValueError,TypeError):
        return unavailable('Purchase history ka valid date range batayein (YYYY-MM-DD).')
    if not 0 <= (end-start).days <= 180 or end > today:
        return unavailable('Purchase history ke liye 180 din tak ka non-future date range dein.')
    company = None
    party = None
    live_protocol_started = False
    try:
        async with asyncio.timeout(30):
            company = await drafts.company_for(db, principal, company_id)
            identity, device_id = company.identity, company.device_id
            snapshot = await sync.saved_snapshot(db, company)
            if snapshot is not None:
                try:
                    party = exact_master(deserialize_catalog(snapshot.catalog), 'supplier', supplier)
                except TallyError:
                    party = None
            if snapshot is None or sync.now()-snapshot.collected_at > timedelta(minutes=15):
                captured = await sync.capture_snapshot(db, company)
                catalog = deserialize_catalog(captured['catalog'])
            else:
                catalog = deserialize_catalog(snapshot.catalog)
            party = exact_master(catalog, 'supplier', supplier)
            items = catalog.get('items', [])
            # No partial catalog silently becomes "no purchases".
            if not 1 <= len(items) <= 100:
                return unavailable('Is company ki item coverage ke liye narrower purchase report chahiye; history complete verify nahi hui.')
            query = validate_query({'supplier': name(party), 'supplier_id': master_identity(party),
                'items': [{'name': name(i), 'id': master_identity(i)} for i in items],
                'from_date': start.isoformat(), 'to_date': end.isoformat()})
            await db.commit()  # No transaction/row lock held during connector I/O.
            manifest = await sync.operation(db, company, 'purchase_history_read', payload=query)
            live_protocol_started = True
            binding = {'company': company.name, 'identity': identity, 'query': digest_query(query)}
            hashes = manifest.get('hashes')
            if (any(manifest.get(k) != v for k,v in binding.items()) or
                manifest.get('complete') is not True or not isinstance(hashes,list) or len(hashes)>50 or
                not re.fullmatch('[a-f0-9]{32}',str(manifest.get('generation',''))) or
                type(manifest.get('count')) is not int or not 0<=manifest['count']<=5000):
                raise TallyError('Incomplete history manifest')
            collected = datetime.fromisoformat(manifest['collected_at'])
            if collected.tzinfo is None or not -60 <= (sync.now()-collected).total_seconds() <= 120:
                raise TallyError('History capture stale')
            records=[];size=0
            for page, expected in enumerate(hashes):
                reply=await sync.operation(db,company,'purchase_history_read',payload=query,
                    generation=manifest['generation'],page=page)
                entries=reply.get('records')
                encoded=json.dumps(entries,sort_keys=True).encode();size+=len(encoded)
                if (any(reply.get(k)!=v for k,v in binding.items()) or
                    reply.get('generation')!=manifest['generation'] or reply.get('page')!=page or
                    not isinstance(entries,list) or not 1<=len(entries)<=100 or size>10_000_000 or
                    hashlib.sha256(encoded).hexdigest()!=expected):
                    raise TallyError('History page incomplete')
                records.extend(entries)
            if len(records)!=manifest['count']:raise TallyError('History row coverage mismatch')
            indexed={master_identity(i):i for i in items};seen=set()
            for row in records:
                item=indexed[row['item_id']]
                qty,rate,amount=(Decimal(row[k]) for k in ('quantity','rate','amount'))
                key=(row['voucher_id'],row['item_id'])
                if (key in seen or not row['voucher_id'] or not row['alteration_id'] or
                    row['supplier_id']!=query['supplier_id'] or row['supplier']!=name(party) or
                    row['supplier_fingerprint']!=master_fingerprint(party) or
                    row['item_fingerprint']!=master_fingerprint(item) or row['item']!=name(item) or
                    row['unit']!=value(item,'BASEUNITS') or not start.isoformat()<=row['entry_date']<=end.isoformat() or
                    not all(v.is_finite() and v>0 for v in (qty,rate,amount)) or
                    abs(qty*rate-amount)>Decimal('.01') or Decimal(row.get('discount','0').rstrip('%'))!=0):
                    raise TallyError('History source evidence invalid')
                seen.add(key)
            # Recheck grants/device/master identity after transport, including a concurrent refresh.
            current=await drafts.company_for(db,principal,company_id)
            await db.refresh(current)
            await drafts.company_for(db,principal,company_id)
            if current.identity!=identity or current.device_id!=device_id:raise TallyError('Company changed')
            await sync.bound_device(db,current)
            latest=await sync.saved_snapshot(db,current)
            if latest:
                fresh=deserialize_catalog(latest.catalog)
                for kind,master in [('supplier',party),*[('item',i) for i in items]]:
                    if master_fingerprint(exact_master(fresh,kind,name(master)))!=master_fingerprint(master):
                        raise TallyError('Masters changed during history read')
    except (TallyError,TimeoutError,ValueError,KeyError,TypeError,InvalidOperation):
        if not live_protocol_started and company is not None and party is not None and hasattr(db, 'scalars'):
            await drafts.company_for(db, principal, company_id)
            fallback, cache_collected_at = await _load_db_history(
                db, company.id, name(party), start.isoformat(), end.isoformat(),
                include_cache=True, existing_vouchers=set())
            if fallback:
                fallback.sort(key=lambda r: (r.get('entry_date', ''), r.get('voucher_id', '')), reverse=True)
                heading = (f"{company.name} — {name(party)} se purchases (Saved verified records; Tally abhi live nahi hai)\n"
                           f"Period: {start.isoformat()} se {end.isoformat()}.")
                lines = [heading]
                for row in fallback[:50]:
                    src = row.get('source_label') or 'Cached Tally line'
                    lines.append(f"• {row['entry_date']}: {row['item']} — {row['quantity']} {row['unit']} × ₹{row['rate']} = ₹{row['amount']} ({src}); bill {row.get('invoice_number') or 'reference missing'}")
                return {'response': '\n'.join(lines), 'status': 'completed', 'response_kind': 'purchase_history',
                        'data_source': 'cached', 'history_complete': False, 'collected_at': cache_collected_at,
                        'history_records': fallback[:50], 'history_count': len(fallback),
                        'period': {'from': start.isoformat(), 'to': end.isoformat()}, 'can_resume': False}
        return unavailable('Tally purchase history complete verify nahi hui. Connector, supplier aur date range check karke dobara try karein; purchases na hone ka claim nahi kiya.')
    extra_actions, _ = await _load_db_history(
        db, company.id, name(party), start.isoformat(), end.isoformat(),
        include_cache=False, existing_vouchers={str(r['voucher_id']) for r in records if r.get('voucher_id')})
    if extra_actions:
        records = list(records) + extra_actions
    records.sort(key=lambda r:(r['entry_date'],r['voucher_id']),reverse=True)
    heading=f"{company.name} — {name(party)} se purchases\nPeriod: {start.isoformat()} se {end.isoformat()} (180 din tak ka search)."
    lines=[heading]
    for row in records[:50]:
        src = row.get('source_label') or 'Tally line amount'
        lines.append(f"• {row['entry_date']}: {row['item']} — {row['quantity']} {row['unit']} × ₹{row['rate']} = ₹{row['amount']} ({src}); bill {row['invoice_number'] or 'reference missing'}")
    if not records:lines.append('Is verified period aur covered stock items mein koi matching Purchase voucher line nahi mili.')
    if len(records)>50:lines.append(f'Pehli 50/{len(records)} lines dikhayi hain; narrower period de sakte hain.')
    return {'response':'\n'.join(lines),'status':'completed','response_kind':'purchase_history',
        'data_source':'live','history_complete':True,'collected_at':collected.isoformat(),
        'history_records':records[:50],'history_count':len(records),'period':{'from':start.isoformat(),'to':end.isoformat()},'can_resume':False}
