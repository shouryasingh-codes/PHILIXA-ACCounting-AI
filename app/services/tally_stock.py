"""Live multi-company stock. No embeddings, generated SQL or stock cache."""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.models.tally import TallyReadCompany, TallyDevice
from app.services.tally_connector import TallyError, local_operation, decimal
logger = logging.getLogger(__name__)


def validate_stock_data(data):
    if not isinstance(data, dict) or not isinstance(data.get('items'), list):
        raise TallyError('Invalid stock response.')
    for row in data['items']:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or len(row[k]) > 2000 for k in ('item', 'unit', 'raw_quantity')):
            raise TallyError('Invalid stock item.')
        if not row['item'] or row.get('limitation') not in (None, 'Compound/alternate unit: raw Tally quantity; no conversion or total.'):
            raise TallyError('Invalid stock item.')
        if row.get('quantity') is not None:
            if not isinstance(row['quantity'], str) or len(row['quantity']) > 100:
                raise TallyError('Invalid quantity.')
            decimal(row['quantity'])


async def transport(db, organization_id, device_id, operation, **parameters):
    if device_id:
        from app.services.tally_bridge import request_job
        device = await db.get(TallyDevice, device_id)
        if not device or device.revoked or device.organization_id != organization_id:
            raise TallyError('Helper revoked/unavailable.')
        return await request_job(device, operation, **parameters)
    return await local_operation(operation, **parameters)


async def resolve_scope(db, principal, parsed):
    rows = list((await db.scalars(select(TallyReadCompany).where(
        TallyReadCompany.organization_id == principal.organization_id,
        TallyReadCompany.enabled.is_(True)).execution_options(populate_existing=True))).all())
    if principal.role not in ('owner', 'admin'):
        rows = [c for c in rows if principal.user_id in c.member_ids]
    if parsed.company_id:
        rows = [c for c in rows if c.id == parsed.company_id]
    elif parsed.company_query:
        query = parsed.company_query.strip().casefold()
        exact = [c for c in rows if query in [c.name.casefold(), *[a.casefold() for a in c.aliases]]]
        rows = exact or [c for c in rows if query in c.name.casefold()]
    return rows


def selection(parsed, **changes):
    fields = parsed.model_dump(mode='json', exclude={'intent'})
    fields.update(changes)
    return {'intent': 'stock_read', 'fields': fields}


async def read_stock(db, principal, parsed, scope=None):
    if parsed.unsupported_reason:
        return {'response': parsed.unsupported_reason}
    if parsed.godown:
        return {'response': 'Abhi company-wise stock supported hai. Godown-wise split is milestone mein available nahi hai.'}
    scope = await resolve_scope(db, principal, parsed) if scope is None else scope
    if not scope:
        return {'response': 'Permitted Tally company nahi mili. Owner/admin se company access approve karwayein.', 'connect_tally': True}
    if parsed.company_scope == 'named' and not parsed.company_query and not parsed.company_id:
        return {'response': 'Kaunsi company? Company ka naam bataiye.'}
    if parsed.company_query and not parsed.company_id and len(scope) > 1:
        return {'response': 'Kaunsi company? Naam ambiguous hai.', 'tally_choices': [
            {'name': c.name, 'command': selection(parsed, company_id=c.id)} for c in scope]}
    if not parsed.item_name:
        return {'response': 'Kis item ka stock chahiye? Item ka naam bataiye.'}
    stamp = datetime.now(ZoneInfo('Asia/Kolkata'))
    as_of = stamp.date().isoformat()
    semaphore = asyncio.Semaphore(3)
    async def read(company):
        async with semaphore:
            try:
                from app.services.tally_bridge import request_job
                operation = request_job(devices[company.device_id], 'stock', company=company.name, identity=company.identity, as_of=as_of, item_query=parsed.item_name) if company.device_id else local_operation('stock', company=company.name, identity=company.identity, as_of=as_of, item_query=parsed.item_name)
                data = await asyncio.wait_for(operation, timeout=25)
                validate_stock_data(data)
                if data.get('identity') != company.identity or data.get('company') != company.name or data.get('as_of') != as_of:
                    raise TallyError('Helper response company/date mismatch.')
                query = parsed.item_name.strip().casefold()
                exact = [i for i in data['items'] if i['item'].casefold() == query]
                matches = exact or [i for i in data['items'] if query in i['item'].casefold()]
                status = 'ok' if len(matches) == 1 else 'ambiguous' if matches else 'item_not_found'
                return {'company_id': company.id, 'company': company.name, 'status': status,
                        'items': matches, 'as_of': as_of, 'data_source':'live', 'read_at': datetime.now(ZoneInfo('Asia/Kolkata')).isoformat(timespec='seconds')}
            except (TallyError, TimeoutError, KeyError, TypeError, ValueError) as exc:
                reason = next((reason for reason in ('Helper offline', 'Tally closed', 'Setup needed', 'Company unavailable', 'timeout') if reason.casefold() in str(exc).casefold()), 'Read failed')
                snapshot=snapshots.get(company.id)
                if snapshot:
                    query=parsed.item_name.strip().casefold()
                    exact=[i for i in snapshot.items if i['item'].casefold()==query]
                    matches=exact or [i for i in snapshot.items if query in i['item'].casefold()]
                    return {'company_id':company.id,'company':company.name,'status':'ok' if len(matches)==1 else 'ambiguous' if matches else 'item_not_found',
                            'items':matches,'data_source':'saved','last_synced_at':snapshot.collected_at.isoformat(),'as_of':snapshot.as_of,'reason':reason}
                return {'company_id': company.id, 'company': company.name, 'status': 'unavailable', 'reason': reason+'; saved stock available nahi', 'items': []}
    # Sequential DB access is resolved before reads; transport does no DB lookup during concurrency.
    devices = {}
    snapshots = {}
    from app.services.tally_sync import saved_snapshot, stock_projection
    for c in scope:
        if c.device_id and c.device_id not in devices:
            devices[c.device_id] = await db.get(TallyDevice, c.device_id)
        try:
            snapshots[c.id]=await saved_snapshot(db,c)
        except TallyError:pass
    async def safe_read(c):
        if c.device_id:
            device = devices.get(c.device_id)
            if not device or device.revoked or device.organization_id != principal.organization_id:
                return {'company_id': c.id, 'company': c.name, 'status': 'unavailable', 'items': []}
        return await read(c)
    # Batches bound both tasks and Tally pressure, without truncating companies.
    results = []
    for start in range(0, len(scope), 10):
        results.extend(await asyncio.gather(*(safe_read(c) for c in scope[start:start+10])))
    # Revocation/replacement during a network read must not release accounting data.
    permitted = {c.id for c in await resolve_scope(db, principal, parsed)}
    for device in devices.values():
        if device:
            old_hash = device.credential_hash
            await db.refresh(device)
            if device.revoked or device.credential_hash != old_hash:
                permitted -= {c.id for c in scope if c.device_id == device.id}
    results = [r if r['company_id'] in permitted else {'company_id': r['company_id'], 'company': r['company'], 'status': 'unavailable', 'items': []} for r in results]
    companies={c.id:c for c in scope}
    for r in results:
        if r['status']=='ok':
            item=r['items'][0]
            r.update(await stock_projection(db,companies[r['company_id']],item['item'],item['quantity'],item['unit']))
    partial = any(r['status'] in ('unavailable', 'ambiguous') for r in results)
    has_saved=any(r.get('data_source')=='saved' for r in results)
    lines = ['Partial result — kuch companies verify nahi hui.' if partial else 'Tally stock (last synced data included):' if has_saved else 'Tally live stock:']
    choices = []
    for r in results:
        if r['status'] == 'ok':
            i = r['items'][0]
            lines.append(f"{r['company']}: {i['item']} — {i['quantity'] if i['quantity'] is not None else i['raw_quantity']} {i['unit'] if i['quantity'] is not None else ''}".strip())
            if i.get('limitation'): lines.append(i['limitation'])
            if r.get('data_source')=='saved':lines.append(f"Last synced: {r['last_synced_at']} · {r['reason']}")
            if r.get('sync_status')=='verification_pending':lines.append('Entry verification pending; expected stock abhi confirm nahi.')
            elif r.get('pending_quantity')!='0':
                lines.append(f"Pending purchase: +{r['pending_quantity']} {i['unit']}")
                lines.append(f"Expected after sync: {r['expected_quantity']} {i['unit']}" if r['expected_quantity'] is not None else 'Expected total unavailable; unit/configuration review needed.')
        elif r['status'] == 'ambiguous':
            lines.append(r['company'] + ': multiple items match; item select karein.')
            choices.extend({'name': r['company'] + ' / ' + i['item'], 'command': selection(parsed, company_id=r['company_id'], item_name=i['item'])} for i in r['items'])
        else:
            lines.append(r['company'] + (': item nahi mila.' if r['status'] == 'item_not_found' else ': '+r.get('reason','Company unavailable')+'; stock unknown.'))
    lines.append('Saved data ki as-of dates company-wise hain; no combined total.' if has_saved else f"As of: {as_of}; no combined total.")
    response = {'response': '\n'.join(lines), 'source': 'Tally saved/live read' if has_saved else 'Tally live read', 'data_source':'mixed' if has_saved and any(r.get('data_source')=='live' for r in results) else 'saved' if has_saved else 'live', 'stock_results': results,
                'coverage': {'requested': len(scope), 'checked': sum(r['status'] != 'unavailable' for r in results), 'partial': partial}, 'tally_choices': choices}
    response['coverage']['live_checked']=sum(r.get('data_source')=='live' for r in results)
    response['coverage']['saved_checked']=sum(r.get('data_source')=='saved' for r in results)
    logger.info('tally_stock requested=%d checked=%d partial=%s',len(scope),response['coverage']['checked'],partial)
    if len(results) == 1 and results[0]['status'] == 'ok':
        response['stock'] = {**results[0]['items'][0], 'read_at': results[0].get('read_at'), 'last_synced_at':results[0].get('last_synced_at')}
    return response
