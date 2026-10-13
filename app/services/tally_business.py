"""Scoped stock queries and durable approval/verification of test-company vouchers."""
import secrets
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, text
from app.models.tally import TallyConnection, TallyAction
from app.services.tally_connector import TallyConnector, TallyError, TallyRejected, name, value, decimal, quantity, stock_quantity, voucher_xml, verify_voucher, matches_action


def admin(principal):
    if principal.role not in ('owner','admin'):
        raise HTTPException(403, 'Tally configuration aur writes owner/admin ke liye hain.')


def match(rows, query):
    query = (query or '').strip().casefold()
    exact = [row for row in rows if name(row).casefold() == query]
    return exact or [row for row in rows if query and query in name(row).casefold()]


from app.services.tally_validation import uses_cost_centres, safe_catalog, validate_item


def fields_for_selection(parsed, field, resolved):
    fields = parsed.model_dump(mode='json',exclude={'intent'})
    fields[field] = resolved
    return {'intent':parsed.intent,'fields':fields}


async def handle_command(db, principal, parsed):
    if parsed.intent == 'purchase_create':
        from app.services.tally_sync import preview_purchase
        from app.models.tally import TallyReadCompany
        approved=await db.scalar(select(TallyReadCompany.id).where(TallyReadCompany.organization_id==principal.organization_id,TallyReadCompany.enabled.is_(True)))
        if approved:
            return await preview_purchase(db,principal,parsed)
    cfg = await db.get(TallyConnection,principal.organization_id)
    if not cfg:
        return {'response':'Pehle Connect Tally kholkar test company connect karein.', 'connect_tally':True}
    if parsed.intent != 'stock_read':
        admin(principal)
    if parsed.unsupported_reason:
        return {'response':'Is pilot mein single-item, non-GST purchase/sale hi supported hai. ' + parsed.unsupported_reason}
    try:
        connector = TallyConnector()
        catalog = await connector.catalog(cfg.company)
        if not parsed.item_name:
            return {'response':'Kis item ka stock/entry? Item select karein.', 'tally_choices':[
                {'name':name(item),'command':fields_for_selection(parsed,'item_name',name(item))} for item in catalog['items'][:100]]}
        items = match(catalog['items'],parsed.item_name)
        if len(items) != 1:
            return {'response':'Item nahi mila.' if not items else 'Kaunsa item? Select karein.',
                    'tally_choices':[{'name':name(item),'command':fields_for_selection(parsed,'item_name',name(item))} for item in items[:100]]}
        item = items[0]
        unit = value(item,'BASEUNITS')
        balance = stock_quantity(item,unit)
        if parsed.intent == 'stock_read':
            timestamp = datetime.now(ZoneInfo('Asia/Kolkata')).isoformat(timespec='seconds')
            return {'response':f"{cfg.company}: {name(item)} ka current stock {balance} {unit} hai.\nTally se read: {timestamp}",
                    'source':'Tally live read','stock':{'item':name(item),'quantity':str(balance),'unit':unit,'read_at':timestamp}}
        safe_catalog(catalog,cfg)
        required = {'party_name':parsed.party_name,'quantity':parsed.quantity,'unit':parsed.unit,'rate':parsed.rate}
        missing = [key for key,val in required.items() if val is None or val == '']
        if missing:
            return {'response':'Entry ke liye ' + ', '.join(missing) + ' bataiye. Details neeche bhar sakte hain.',
                    'tally_form':fields_for_selection(parsed,'item_name',name(item))}
        parties = match(catalog['ledgers'],parsed.party_name)
        if len(parties) != 1:
            return {'response':'Party nahi mili; pehle Tally mein banayein.' if not parties else 'Kaunsi party? Select karein.',
                    'tally_choices':[{'name':name(p),'command':fields_for_selection(parsed,'party_name',name(p))} for p in parties[:100]]}
        party = parties[0]
        kind = 'Purchase' if parsed.intent == 'purchase_create' else 'Sales'
        required_group = 'Sundry Creditors' if kind=='Purchase' else 'Sundry Debtors'
        if value(party,'PARENT') != required_group:
            raise TallyError(f'Party direct {required_group} group mein honi chahiye. Cash/subgroup entries is pilot mein supported nahi hain.')
        if uses_cost_centres(catalog, party):
            raise TallyError('Cost-centre party supported nahi hai.')
        validate_item(catalog,item,parsed.unit)
        qty, rate = decimal(parsed.quantity), decimal(parsed.rate)
        unit_row = match(catalog['units'],parsed.unit)[0]
        places = value(unit_row,'DECIMALPLACES')
        if not places.isdigit() or not 0 <= int(places) <= 6:
            raise TallyError('Unit decimal precision verify nahi hui.')
        if qty != qty.quantize(Decimal(1).scaleb(-int(places))):
            raise TallyError('Quantity unit ki allowed decimal precision se zyada hai.')
        if kind=='Sales' and qty > balance:
            raise TallyError(f'Stock insufficient hai: {balance} {parsed.unit} available.')
        current = datetime.now(ZoneInfo('Asia/Kolkata')).date()
        entry_date = parsed.entry_date or current
        if entry_date != current:
            raise TallyError('Is pilot mein sirf aaj ki entry supported hai.')
        if parsed.godown and parsed.godown != cfg.godown:
            raise TallyError('Sirf configured godown supported hai.')
        total = (qty * rate).quantize(Decimal('0.01'))
        if total <= 0:
            raise TallyError('Total positive hona chahiye.')
        payload = {'company':cfg.company,'godown':cfg.godown,'party':name(party),'item':name(item),
                   'quantity':str(qty),'unit':parsed.unit,'rate':str(rate),'total':str(total),
                   'voucher_type':kind,'ledger':cfg.purchase_ledger if kind=='Purchase' else cfg.sales_ledger,
                   'date':entry_date.isoformat(),'guid':str(uuid.uuid4()),'stock_before':str(balance)}
        token = secrets.token_hex(16)
        now = datetime.now(timezone.utc)
        db.add(TallyAction(token=token,organization_id=principal.organization_id,user_id=principal.user_id,
                           session_id=principal.session_id,created_at=now,expires_at=now+timedelta(minutes=15),
                           connection_version=cfg.version,payload=payload,xml_payload=voucher_xml(payload),status='preview'))
        await db.commit()
        return {'response':'Tally entry ka preview check karein. Abhi voucher save nahi hua.',
                'preview':{'token':token,'title':kind+' entry — test company','lines':[
                    f"Company: {cfg.company}",f"Party: {payload['party']}",f"Item: {payload['item']}",
                    f"Godown: {cfg.godown}",f"Quantity: {qty} {parsed.unit}",f"Rate: ₹{rate}/{parsed.unit}",
                    f"Total: ₹{total} (non-GST)",f"Date: {entry_date}",f"Ledger: {payload['ledger']}"],
                    'can_confirm':True,'blockers':[],'send':False}}
    except TallyError as exc:
        return {'response':str(exc),'connect_tally':True}


async def reconcile(db, action, connector):
    p = action.payload
    pending = {'response':'Tally entry ka result verification pending hai. Dobara entry na banayein; Status check dabayein.',
               'tally_status':'verification_pending','tally_action':action.token}
    try:
        vouchers = await connector.collection('Voucher',p['company'],p['date'])
        found = [v for v in vouchers if matches_action(v,p)]
        if len(found)==1 and verify_voucher(found[0],p):
            number = value(found[0],'VOUCHERNUMBER')
            if not number:
                raise TallyError('Voucher number missing.')
            items = await connector.collection('StockItem',p['company'])
            item = next((i for i in items if name(i)==p['item']),None)
            if item is None:
                raise TallyError('Updated stock missing.')
            balance = stock_quantity(item,p['unit'])
            result = {'response':f"Tally mein {p['voucher_type']} voucher {number} saved aur verified hai.\n{p['item']}: current stock {balance} {p['unit']}.",
                      'tally_status':'verified','voucher_number':number,'stock':str(balance),'company':p['company']}
            action.status='verified'
        elif found:
            result={'response':'Voucher mila lekin approved details match nahi hui. Tally mein manually check karein; dobara import nahi hoga.',
                    'tally_status':'verification_mismatch','tally_action':action.token}
            action.status='verification_mismatch'
        else:
            result=pending
            action.status='verification_pending'
    except TallyError:
        result=pending
        action.status='verification_pending'
    action.result=result
    await db.commit()
    return result


async def confirm_action(db, principal, token, approve=True, status_only=False):
    # A dedicated DB connection holds a workspace lock across the pre-import commit.
    # This serializes our stock writes without relying on an in-process/Docker lock.
    from app.database.session import async_engine
    exists = await db.scalar(select(TallyAction.token).where(TallyAction.token==token))
    if exists is None:
        return None
    lock_id=zlib.crc32(principal.organization_id.encode()) & 0x7fffffff
    async with async_engine.connect() as lock_connection:
        locked=await lock_connection.scalar(text('SELECT pg_try_advisory_xact_lock(73921, :key)'),{'key':lock_id})
        if not locked:
            raise HTTPException(409,'Tally action process ho raha hai. Status check karein; duplicate entry na banayein.')
        # This independent transaction closes/rolls back on return or cancellation,
        # automatically releasing the lock; no advisory lock can leak into the pool.
        return await _confirm_action(db,principal,token,approve,status_only)


async def _confirm_action(db, principal, token, approve=True, status_only=False):
    # Existence is probed without exposing another user's approval.
    action = await db.scalar(select(TallyAction).where(TallyAction.token==token).with_for_update())
    if action is None:
        return None
    if action.payload.get('operation')=='inventory_clarification':raise HTTPException(409,'Clarification is not an executable preview.')
    if action.company_id:
        from app.services.tally_sync import confirm_queued
        return await confirm_queued(db,principal,action,approve,status_only)
    if (action.organization_id,action.user_id,action.session_id) != (principal.organization_id,principal.user_id,principal.session_id):
        raise HTTPException(410,'Tally preview nahi mila ya expire ho gaya.')
    admin(principal)
    if action.status in ('verified','cancelled','failed','expired','verification_mismatch'):
        return action.result
    if action.status in ('submitting','verification_pending'):
        # Read-only reconciliation never reimports, even after a restart or timeout.
        return await reconcile(db,action,TallyConnector())
    if status_only:
        return {'response':'Ye preview abhi confirm nahi hua.','tally_status':'preview'}
    if not approve:
        action.status='cancelled'
        action.result={'response':'Cancel kar diya. Tally mein kuch save nahi hua.'}
        await db.commit()
        return action.result
    if action.expires_at <= datetime.now(timezone.utc):
        action.status='expired'
        action.result={'response':'Preview expire ho gaya. Naya preview banayein.'}
        await db.commit()
        raise HTTPException(410,action.result['response'])
    cfg = await db.get(TallyConnection,principal.organization_id)
    try:
        if not cfg or cfg.version != action.connection_version or cfg.company != action.payload['company']:
            raise TallyError('Connection badal gaya. Naya preview banayein.')
        connector=TallyConnector()
        catalog=await connector.catalog(cfg.company)
        safe_catalog(catalog,cfg)
        p=action.payload
        item=next((i for i in catalog['items'] if name(i)==p['item']),None)
        party=next((i for i in catalog['ledgers'] if name(i)==p['party']),None)
        group='Sundry Creditors' if p['voucher_type']=='Purchase' else 'Sundry Debtors'
        if item is None or party is None or value(party,'PARENT')!=group or uses_cost_centres(catalog,party):
            raise TallyError('Item/party master badal gaya. Naya preview banayein.')
        unit_row=validate_item(catalog,item,p['unit'])
        places=value(unit_row,'DECIMALPLACES')
        if not places.isdigit() or not 0<=int(places)<=6 or decimal(p['quantity']) != decimal(p['quantity']).quantize(Decimal(1).scaleb(-int(places))):
            raise TallyError('Unit precision badal gayi. Naya preview banayein.')
        balance=stock_quantity(item,p['unit'])
        if p['voucher_type']=='Sales' and balance<decimal(p['quantity']):
            raise TallyError('Ab stock insufficient hai. Naya preview banayein.')
        if p['date'] != datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat():
            raise TallyError('Entry date beet gayi. Naya preview banayein.')
        # Check for an existing GUID before first write as well as after it.
        vouchers=await connector.collection('Voucher',p['company'],p['date'])
        if any(matches_action(v,p) for v in vouchers):
            return await reconcile(db,action,connector)
    except TallyError as exc:
        action.status='failed'
        action.result={'response':str(exc),'tally_status':'failed'}
        await db.commit()
        return action.result
    # Commit BEFORE external write. A crash cannot turn the action into a retryable preview.
    action.status='submitting'
    await db.commit()
    try:
        reply=await connector.post(action.xml_payload)
        rejected=(value(reply,'ERRORS') not in ('','0') or reply.findtext('.//ERRORS') not in (None,'0'))
        if rejected:
            # Still reconcile: partial imports must not be blindly retried.
            action.status='verification_pending'
    except TallyRejected as exc:
        action.status='failed'
        action.result={'response':'Tally ne entry reject ki: '+str(exc),'tally_status':'failed'}
        await db.commit()
        return action.result
    except TallyError:
        pass
    # Serialize result updates after the in-flight import; concurrent confirmations only read.
    await db.refresh(action,with_for_update=True)
    if action.status=='verified':
        return action.result
    return await reconcile(db,action,connector)
