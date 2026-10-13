"""PostgreSQL-authoritative snapshots and purchase outbox."""
import hashlib
import json
import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, text
from app.models.tally import TallyAction, TallyConnection, TallyDevice, TallyReadCompany, TallySnapshot
from app.services.tally_connector import TallyError, name, value, decimal, voucher_xml
from app.services.tally_sync_protocol import deserialize_catalog, fingerprint, validate_purchase

logger = logging.getLogger(__name__)
ACTIVE = ('queued','submitting','verification_pending')
def uncertain(action):
    return action.status in ('submitting','verification_pending') or bool((action.result or {}).get('uncertain'))
def now(): return datetime.now(timezone.utc)
def config_data(cfg):
    return {k:getattr(cfg,k) for k in ('company','godown','purchase_ledger','sales_ledger','test_company')}

@asynccontextmanager
async def company_lock(company_id):
    from app.database.session import async_engine
    async with async_engine.connect() as conn:
        device_id=await conn.scalar(select(TallyReadCompany.device_id).where(TallyReadCompany.id==company_id))
        # All companies on a paired endpoint serialize, not just one company.
        lock_identity=device_id or 'local-tally-endpoint'
        key=int(hashlib.sha256(lock_identity.encode()).hexdigest()[:8],16)&0x7fffffff
        locked=await conn.scalar(text('SELECT pg_try_advisory_xact_lock(73922,:key)'),{'key':key})
        yield bool(locked)

async def bound_device(db, company):
    if not company.enabled: raise TallyError('Company approval revoked.')
    if not company.device_id: return None
    device=await db.get(TallyDevice,company.device_id,populate_existing=True)
    if not device or device.revoked or device.organization_id!=company.organization_id:
        raise TallyError('Helper revoked/unavailable.')
    return device

async def operation(db, company, kind, **params):
    from app.services.tally_bridge import request_job
    from app.services.tally_sync_protocol import execute_sync
    device=await bound_device(db,company)
    if device:
        return await request_job(device,kind,company=company.name,identity=company.identity,**params)
    params.pop('action_id',None)
    return await execute_sync(kind,company=company.name,identity=company.identity,**params)

async def capture_snapshot(db, company):
    device=await bound_device(db,company)
    version=device.credential_hash if device else None
    stamp=datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()
    manifest=await operation(db,company,'snapshot_start',as_of=stamp)
    if (manifest.get('company'),manifest.get('identity'),manifest.get('as_of'))!=(company.name,company.identity,stamp):
        raise TallyError('Snapshot company/date mismatch.')
    hashes=manifest.get('hashes')
    if not isinstance(hashes,list) or len(hashes)>10000: raise TallyError('Snapshot manifest invalid.')
    catalog=dict(manifest['flags']);catalog.update({k:[] for k in ('items','units','godowns','ledgers')})
    if catalog.get('groups_complete') is True:
        catalog['groups'] = []
    stock=[];size=0
    for index,expected in enumerate(hashes):
        reply=await operation(db,company,'snapshot_page',generation=manifest['generation'],page=index)
        records=reply.get('records')
        if reply.get('generation')!=manifest['generation'] or reply.get('page')!=index or not isinstance(records,list):
            raise TallyError('Snapshot page mismatch.')
        encoded=json.dumps(records,sort_keys=True).encode();size+=len(encoded)
        if size>40_000_000 or hashlib.sha256(encoded).hexdigest()!=expected: raise TallyError('Snapshot incomplete/oversized.')
        for record in records:
            if record.get('kind')=='stock':stock.append(record['row'])
            elif record.get('kind') in ('items','units','godowns','ledgers','groups','companies','stock_groups','tax_units'):catalog.setdefault(record['kind'], []).append(record['row'])
            else:raise TallyError('Invalid snapshot record.')
    masters=deserialize_catalog(catalog)
    from app.services.tally_stock import validate_stock_data
    validate_stock_data({'items':stock})
    if sorted(i['item'] for i in stock)!=sorted(name(i) for i in masters['items']):raise TallyError('Snapshot stock coverage mismatch.')
    collected=datetime.fromisoformat(manifest['collected_at'])
    if collected.tzinfo is None or collected>now()+timedelta(minutes=1):raise TallyError('Invalid snapshot time.')
    await db.refresh(company)
    current=await bound_device(db,company)
    if company.identity!=manifest['identity'] or company.name!=manifest['company'] or (current.credential_hash if current else None)!=version:
        raise TallyError('Company/helper changed during snapshot.')
    return dict(generation=manifest['generation'],identity=company.identity,device_version=version,as_of=stamp,
                collected_at=collected,catalog=catalog,items=stock)

async def publish_snapshot(db,company,data):
    snapshot=await db.get(TallySnapshot,company.id)
    if snapshot:
        for key,val in data.items():setattr(snapshot,key,val)
    else:db.add(TallySnapshot(company_id=company.id,**data))
    company.refresh_requested=False

async def refresh_company(db, company):
    async with company_lock(company.id) as locked:
        if not locked:return False
        actions=list((await db.scalars(select(TallyAction).where(TallyAction.company_id==company.id,TallyAction.status.in_(('submitting','verification_pending','needs_review'))))).all())
        if any(uncertain(a) for a in actions):return False
        data=await capture_snapshot(db,company)
        await publish_snapshot(db,company,data);await db.commit()
        return True

async def saved_snapshot(db,company):
    device=await bound_device(db,company)
    snapshot=await db.get(TallySnapshot,company.id)
    if snapshot and snapshot.identity==company.identity and snapshot.device_version==(device.credential_hash if device else None):return snapshot
    return None

async def stock_projection(db, company, item, base, unit, snapshot_time=None):
    from app.services.tally_multi_purchase_service import action_lines
    actions=list((await db.scalars(select(TallyAction).where(TallyAction.company_id==company.id,TallyAction.status.in_((*ACTIVE,'needs_review'))))).all())
    relevant=[a for a in actions if any(l.get('item')==item and l.get('unit')==unit for l in action_lines(a.payload))]
    pending_verification=any(uncertain(a) for a in relevant)
    # MCP payloads hold inventory under arguments.items/sources/destinations,
    # rather than the legacy purchase's single item/unit pair. An opaque or
    # uncertain MCP write can affect stock even when that pair is absent.
    # Until its operation-specific stock projection is certified, do not claim
    # an expected stock total from the old snapshot.
    if any(getattr(a,'backend',None)=='mcp' for a in actions):pending_verification=True
    if any(getattr(a,'backend',None) not in (None,'python') for a in relevant):pending_verification=True
    pending=sum((decimal(l['quantity']) for a in relevant if a.status=='queued' and a.payload.get('operation')!='stock_count_set' and getattr(a,'backend',None) in (None,'python')
        for l in action_lines(a.payload) if l.get('item')==item and l.get('unit')==unit),Decimal(0))
    if any(a.payload.get('operation')=='stock_count_set' for a in relevant):pending_verification=True
    # A refresh may have captured a queued action's external effect after dispatch.
    # The company lock prevents that transition while a snapshot is published.
    expected=None if pending_verification or base is None else str(decimal(base)+pending)
    return {'pending_quantity':str(pending),'expected_quantity':expected,'sync_status':'verification_pending' if pending_verification else 'queued' if pending else 'synced'}

async def preview_purchase(db,principal,parsed,draft=None):
    from app.services.tally_business import admin, fields_for_selection
    from app.services.tally_stock import resolve_scope
    admin(principal)
    if parsed.unsupported_reason:return {'response':parsed.unsupported_reason}
    cfg=await db.get(TallyConnection,principal.organization_id)
    if not cfg or not cfg.test_company:return {'response':'Purchase writes ke liye non-GST test company configure karein.','connect_tally':True}
    scope=await resolve_scope(db,principal,parsed)
    if not parsed.company_id and len(scope)>1:
        return {'response':'Purchase kis company mein? Company select karein.','tally_choices':[
            {'name':c.name,'command':fields_for_selection(parsed,'company_id',c.id)} for c in scope]}
    if len(scope)!=1 or scope[0].name!=cfg.company:return {'response':'Purchase sirf approved configured test company mein supported hai.'}
    company=scope[0]
    try:
        snapshot=await saved_snapshot(db,company)
        refresh_error=None
        # Refresh when reachable, but preserve usable saved masters offline.
        try:
            await refresh_company(db,company)
            snapshot=await saved_snapshot(db,company)
        except TallyError as exc:refresh_error=str(exc)
        if not snapshot:
            if refresh_error and any(label in refresh_error for label in ('update Philixa Tally Connector','update Philixa Connect')):
                return {'response':'Helper connected hai, lekin purana version chal raha hai. Saved stock aur purchase sync ke liye Philixa Tally Connector update karein; pairing dobara zaroori nahi.','connect_tally':True,'helper_update_required':True}
            return {'response':'Complete saved masters available nahi. '+(refresh_error or 'Snapshot sync pending; thodi der baad retry karein.'),'connect_tally':True}
        catalog=deserialize_catalog(snapshot.catalog)
        if not parsed.item_name:return {'response':'Kis item ki purchase? Item ka naam bataiye.'}
        from app.services.tally_business import match
        items=match(catalog['items'],parsed.item_name)
        if len(items)!=1:return {'response':'Item nahi mila.' if not items else 'Kaunsa item?','tally_choices':[
            {'name':name(i),'command':fields_for_selection(parsed,'item_name',name(i))} for i in items]}
        prior=list((await db.scalars(select(TallyAction).where(TallyAction.company_id==company.id,TallyAction.status.in_(('submitting','verification_pending','needs_review'))))).all())
        from app.services.tally_multi_purchase_service import action_lines
        if any(uncertain(a) and (a.backend=='mcp' or any(l.get('item')==name(items[0]) for l in action_lines(a.payload))) for a in prior):
            return {'response':'Is item ki earlier entry verification pending hai. Pehle status/manual review karein; duplicate purchase na banayein.'}
        missing=[k for k in ('party_name','quantity','unit','rate') if getattr(parsed,k) is None or getattr(parsed,k)=='']
        if missing:return {'response':'Purchase ke liye '+', '.join(missing)+' bataiye.','tally_form':fields_for_selection(parsed,'item_name',name(items[0]))}
        parties=match(catalog['ledgers'],parsed.party_name)
        if len(parties)!=1:return {'response':'Supplier nahi mila.' if not parties else 'Kaunsa supplier?','tally_choices':[
            {'name':name(p),'command':fields_for_selection(parsed,'party_name',name(p))} for p in parties]}
        if parsed.godown and parsed.godown!=cfg.godown:raise TallyError('Configured godown use karein.')
        entry_date=parsed.entry_date or datetime.now(ZoneInfo('Asia/Kolkata')).date()
        qty,rate=decimal(parsed.quantity),decimal(parsed.rate)
        row=next(i for i in snapshot.items if i['item']==name(items[0]))
        payload={'company':company.name,'godown':cfg.godown,'party':name(parties[0]),'item':name(items[0]),'quantity':str(qty),
                 'unit':parsed.unit,'rate':str(rate),'total':str((qty*rate).quantize(Decimal('.01'))),'voucher_type':'Purchase',
                 'ledger':cfg.purchase_ledger,'date':entry_date.isoformat(),'guid':str(uuid.uuid4()),'stock_before':row['quantity'] or '',
                 'master_fingerprint':''}
        payload['master_fingerprint']=fingerprint(catalog,payload)
        validate_purchase(catalog,payload,config_data(cfg))
        device=await bound_device(db,company)
        token=secrets.token_hex(16);stamp=now()
        action=TallyAction(token=token,organization_id=principal.organization_id,user_id=principal.user_id,session_id=principal.session_id,
            company_id=company.id,device_version=device.credential_hash if device else None,created_at=stamp,expires_at=stamp+timedelta(minutes=15),
            connection_version=cfg.version,payload=payload,xml_payload=voucher_xml(payload),status='preview',attempts=0)
        db.add(action)
        from app.services.purchase_draft_service import attach_preview
        draft_id=await attach_preview(db,principal,action,draft)
        await db.commit()
        return {'response':'Purchase preview check karein. Confirm par Philixa save karega; Tally available hote hi sync hogi.',
            'draft_id':draft_id,
            'preview':{'token':token,'title':'Purchase — test company','can_confirm':True,'blockers':[],'send':False,
                'lines':[f'Company: {company.name}',f'Supplier: {payload["party"]}',f'Item: {payload["item"]}',f'Quantity: {qty} {parsed.unit}',
                         f'Rate: ₹{rate}',f'Total: ₹{payload["total"]} (non-GST)',f'Date: {entry_date}',f'Godown: {cfg.godown}',
                         f'Masters last synced: {snapshot.collected_at.isoformat()}']}}
    except (TallyError,ValueError) as exc:return {'response':str(exc)}

def action_result(action):
    labels={'draft':'Count request saved; live review pending.','awaiting_review':'Count ready for live review. Fresh confirmation required.','queued':'Philixa mein saved; Tally sync pending.','submitting':'Tally posting started; verification pending.',
            'verification_pending':'Entry verification pending. Dobara entry na banayein.', 'needs_review':'Entry needs review. Naya preview banayein.',
            'failed':'Tally ne entry reject ki. Details/date check karein.', 'cancelled':'Unsubmitted purchase cancel kar di.',
            'verified':'Purchase Tally mein saved aur verified hai.','expired':'Preview expire ho gaya.','preview':'Preview abhi confirm nahi hua.'}
    result=dict(action.result or {})
    result.update(response=result.get('response') or labels.get(action.status,action.status),sync_status=action.status,
                  tally_status=action.status,action_id=action.token,tally_action=action.token)
    if action.payload.get('operation')=='stock_count_set':
        from app.services.tally_count import count_capability
        capability=count_capability()
        result['count_capability']=capability
        result['count_review_available']=capability['available'] and action.status in ('draft','awaiting_review','preview','needs_review') and not result.get('uncertain')
        if action.status=='verified':
            result['response']='Actual stock count Tally mein saved aur verified hai.'
        elif action.status=='cancelled':
            result['response']='Unsubmitted count request cancel kar di. Tally stock change nahi hua.'
        elif not capability['available'] and action.status in ('draft','awaiting_review','preview'):
            result['response']=capability['reason']+' Saved draft retained hai.'
    if getattr(action,'backend',None)=='mcp':
        result['mcp_review_available']=action.status=='draft'
    if action.payload.get('operation')=='customer_ledger_create':
        if not (action.result or {}).get('response'):
            result['response']={'queued':'Customer request saved; Tally ledger sync pending. Philixa customer abhi linked nahi hai.',
                'submitting':'Tally customer ledger posting; verification pending.',
                'verification_pending':'Customer ledger verification pending. Duplicate request na banayein.',
                'cancelled':'Unsubmitted customer request cancelled.',
                'preview':'Customer ledger preview abhi confirm nahi hua.'}.get(action.status,result['response'])
    return result

async def invalidate_actions(db,company_ids):
    if not company_ids:return
    actions=list((await db.scalars(select(TallyAction).where(TallyAction.company_id.in_(company_ids),TallyAction.status.in_(ACTIVE)).with_for_update())).all())
    for action in actions:
        action.result={'uncertain':uncertain(action),'response':'Company/helper access badal gaya. Pending entry needs review; automatic transfer/posting nahi hogi.'}
        action.status='needs_review'

async def confirm_queued(db,principal,action,approve=True,status_only=False):
    from app.services.tally_business import admin
    if (action.organization_id,action.user_id,action.session_id)!=(principal.organization_id,principal.user_id,principal.session_id):
        raise HTTPException(410,'Purchase preview nahi mila.')
    admin(principal)
    if status_only:return action_result(action)
    if not approve and action.status in ('preview','queued','draft','awaiting_review'):
        action.status='cancelled';action.result=None;await db.commit();return action_result(action)
    if getattr(action,'backend',None) not in (None,'python'):
        raise HTTPException(409,'MCP writes need operation-specific durable dispatch and live acceptance. Approval blocked.')
    if action.status!='preview':return action_result(action)
    if action.payload.get('operation')=='stock_count_set':
        from app.services.tally_count import count_capability
        if not count_capability()['available']:return action_result(action)
    if action.expires_at<=now():
        action.status='expired';await db.commit();raise HTTPException(410,'Preview expire ho gaya.')
    company=await db.get(TallyReadCompany,action.company_id)
    cfg=await db.get(TallyConnection,principal.organization_id)
    if not company or company.organization_id!=principal.organization_id:raise HTTPException(410,'Company unavailable.')
    try:device=await bound_device(db,company)
    except TallyError as exc:raise HTTPException(410,str(exc))
    if not cfg or cfg.version!=action.connection_version or cfg.company!=company.name or (device.credential_hash if device else None)!=action.device_version:
        raise HTTPException(410,'Company/helper/config changed. Naya preview banayein.')
    if action.payload.get('operation')=='customer_ledger_create' and action.target_identity!={'company':company.identity}:
        raise HTTPException(410,'Customer company identity changed. Naya preview banayein.')
    if action.payload.get('operation') in ('purchase_multi','purchase_gst') and action.target_identity!={'company':company.identity}:
        raise HTTPException(410,'Purchase company identity changed. Naya preview banayein.')
    if action.payload.get('operation')=='purchase_gst':
        from app.services.purchase_tax_service import ensure_approved_profile,acceptance_enabled
        if not acceptance_enabled():raise HTTPException(409,'GST live Tally acceptance pending; posting locked.')
        try:await ensure_approved_profile(db,action)
        except TallyError as exc:raise HTTPException(409,str(exc))
    action.status='queued';action.next_attempt_at=now();action.result=None
    action.approved_arguments=dict(action.payload)
    await db.commit()
    return action_result(action)

async def process_action(db,action,company):
    # Never send an uncertain MCP action through the legacy Python purchase backend.
    if getattr(action,'backend',None) not in (None,'python'):
        if getattr(action,'backend',None)=='mcp' and action.status=='draft':return
        was_uncertain=uncertain(action)
        action.status='needs_review'
        action.result={'uncertain':was_uncertain,'response':'Original backend unavailable; operation-specific reconciliation required.'}
        await db.commit();return
    from app.models.organization_membership import OrganizationMembership
    from app.models.organization import Organization
    from app.models.user import User
    membership=await db.get(OrganizationMembership,(action.user_id,action.organization_id),populate_existing=True)
    org=await db.get(Organization,action.organization_id)
    user=await db.get(User,action.user_id,populate_existing=True)
    cfg=await db.get(TallyConnection,action.organization_id,populate_existing=True)
    try:device=await bound_device(db,company)
    except TallyError:
        was_uncertain=uncertain(action)
        action.status='needs_review';action.result={'uncertain':was_uncertain};await db.commit();return
    valid=org and org.is_active and user and user.is_active and membership and membership.status=='active' and membership.role in ('owner','admin')
    valid=valid and cfg and cfg.test_company and cfg.version==action.connection_version and cfg.company==company.name
    valid=valid and (device.credential_hash if device else None)==action.device_version
    if not valid:
        was_uncertain=uncertain(action)
        action.status='needs_review';action.result={'uncertain':was_uncertain};await db.commit();return
    if action.payload.get('operation')=='customer_ledger_create':
        if action.approved_arguments!=action.payload or action.target_identity!={'company':company.identity}:
            action.result={'uncertain':uncertain(action),'response':'Approved customer payload changed; review required.'}
            action.status='needs_review';await db.commit();return
        from app.services.tally_customer import process_customer
        return await process_customer(db,action,company,cfg)
    count=action.payload.get('operation')=='stock_count_set'
    multi=action.payload.get('operation') in ('purchase_multi','purchase_gst')
    if multi and (action.approved_arguments!=action.payload or action.target_identity!={'company':company.identity}):
        action.result={'uncertain':uncertain(action),'response':'Approved multi-item payload changed; review required.'}
        action.status='needs_review';await db.commit();return
    gst=action.payload.get('operation')=='purchase_gst'
    if gst:
        from app.services.purchase_tax_service import ensure_approved_profile,acceptance_enabled
        try:
            if action.status=='queued':await ensure_approved_profile(db,action)
        except TallyError as exc:
            action.status='needs_review';action.result={'uncertain':uncertain(action),'response':str(exc)};await db.commit();return
        if not acceptance_enabled() and action.status=='queued':
            action.status='needs_review';action.result={'uncertain':False,'response':'GST live acceptance pending; posting locked.'};await db.commit();return
    prefix='purchase_gst_' if gst else 'stock_count_' if count else 'purchase_multi_' if multi else 'purchase_'
    params={'payload':action.payload,'config':config_data(cfg),'action_id':action.token}
    if count and action.status in ('draft','awaiting_review'):
        reply=await operation(db,company,prefix+'validate',**params)
        await db.refresh(action,with_for_update=True)
        if action.status not in ('draft','awaiting_review'):return
        if reply.get('status')=='ready':action.status='awaiting_review';action.result=None;await db.commit()
        return
    if action.status=='queued':
        if count:
            other=list((await db.scalars(select(TallyAction).where(TallyAction.company_id==company.id,TallyAction.token!=action.token,TallyAction.status.in_(ACTIVE)))).all())
            from app.services.tally_multi_purchase_service import action_lines
            if any(any(l.get('item')==action.payload['item'] for l in action_lines(x.payload)) for x in other):
                action.status='needs_review';action.result={'uncertain':False,'response':'Earlier item entries must settle; fresh review required.'};await db.commit();return
        try:
            reply=await operation(db,company,prefix+'validate',**params)
        except TallyError as exc:
            if 'needs review' in str(exc).lower() or 'Invalid' in str(exc):
                action.status='needs_review';await db.commit();return
            raise
        if reply.get('status')=='verified':pass
        elif reply.get('status')!='ready':
            action.status='needs_review';action.result={'uncertain':False,'response':str(reply.get('reason') or 'Validation failed; review the bill and create a fresh preview.')[:300]};await db.commit();return
        else:
            # Confirmation/cancellation can race the read-only validation request.
            await db.refresh(action,with_for_update=True)
            if action.status!='queued':return
            if gst:
                try:await ensure_approved_profile(db,action)
                except TallyError as exc:
                    action.status='needs_review';action.result={'uncertain':False,'response':str(exc)};await db.commit();return
            action.status='submitting';await db.commit()
            reply=await operation(db,company,prefix+'post',**params)
    else:reply=await operation(db,company,prefix+'reconcile',**params)
    await db.refresh(action)
    if action.status not in ACTIVE:return
    if reply.get('status')=='verified':
        # Keep pending/uncertain until both voucher verification and snapshot succeed.
        snapshot=await capture_snapshot(db,company)
        await db.refresh(action,with_for_update=True)
        if action.status not in ACTIVE:return
        await publish_snapshot(db,company,snapshot)
        action.status='verified';action.result={'response':f'{"Physical Stock" if count else "Purchase"} voucher {reply["voucher_number"]} Tally mein saved aur verified hai.',
                                                'voucher_number':reply['voucher_number'],'company':company.name}
    elif reply.get('status') in ('failed','needs_review'):
        was_uncertain=uncertain(action)
        action.status=reply['status'];action.result={'uncertain':bool(reply.get('uncertain',was_uncertain and action.status=='needs_review'))}
        if action.status=='failed':
            reason=reply.get('reason')
            if isinstance(reason,str) and reason.strip():
                action.result['response']='Tally ne entry reject ki: '+reason[:300]+' Approved date: '+action.payload['date']+'. Naya preview banakar details/date correct karein.'
        if action.result['uncertain']:action.result['response']='Tally voucher/entry ko manually review karein. Result approved details se verify nahi hua; duplicate entry na banayein.'
    else:action.status='verification_pending';action.result=None
    await db.commit()

async def sync_tick(ctx):
    from app.database.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        # Rollback expires every ORM instance, including later companies in a
        # preloaded list. Keep scalar IDs and explicitly reload after failures.
        company_ids=list((await db.scalars(select(TallyReadCompany.id).where(TallyReadCompany.enabled.is_(True)))).all())
        for company_id in company_ids:
            company=await db.get(TallyReadCompany,company_id,populate_existing=True)
            if not company or not company.enabled:continue
            async with company_lock(company_id) as locked:
                if not locked:continue
                blocked=list((await db.scalars(select(TallyAction).where(TallyAction.company_id==company.id,
                    TallyAction.status=='needs_review'))).all())
                # An unresolved imported voucher can affect any subsequent stock snapshot.
                # Freeze this company's dispatch until its uncertain result is reviewed.
                if any(uncertain(action) for action in blocked):continue
                actions=list((await db.scalars(select(TallyAction).where(TallyAction.company_id==company.id,
                    TallyAction.status.in_((*ACTIVE,'draft','awaiting_review'))).order_by(TallyAction.created_at))).all())
                for action in actions:
                    if action.next_attempt_at and action.next_attempt_at>now():break
                    try:await process_action(db,action,company)
                    except TallyError as exc:
                        await db.refresh(action,with_for_update=True)
                        if action.status=='submitting':action.status='verification_pending'
                        if action.payload.get('operation')!='customer_ledger_create':
                            update_required='update' in str(exc).lower() and 'connector' in str(exc).lower()
                            action.result={'response':('Connector update required; saved pairing remains valid.' if update_required else 'Tally/Connector unavailable; automatic retry pending. Duplicate entry na banayein.'),
                                'helper_update_required':update_required,'connect_tally':update_required}
                        if action.payload.get('operation')=='customer_ledger_create':
                            if 'update required' in str(exc).lower():
                                action.result={'response':'Customer request saved. Tally customer ledger ke liye updated Connector install karein; pairing dobara zaroori nahi.', 'helper_update_required':True,'connect_tally':True}
                            else:action.result={'response':'Customer request saved; Tally/Connector unavailable ya verification pending. Automatic retry hoga; duplicate entry na banayein.'}
                    except Exception as exc:
                        await db.rollback()
                        logger.error('tally_sync outcome=error failure_type=%s',type(exc).__name__)
                        break
                    if action.status in ACTIVE:
                        action.attempts+=1;action.next_attempt_at=now()+timedelta(seconds=min(300,15*2**min(action.attempts-1,5)))
                        await db.commit()
                        # Preserve ordered processing; do not stack writes behind uncertain import.
                        break
                company=await db.get(TallyReadCompany,company_id,populate_existing=True)
                if not company or not company.enabled:continue
                review=list((await db.scalars(select(TallyAction).where(TallyAction.company_id==company.id,
                    TallyAction.status.in_(('submitting','verification_pending','needs_review'))))).all())
                unresolved=any(uncertain(a) for a in review)
                snapshot=await db.get(TallySnapshot,company.id)
                if not unresolved and (company.refresh_requested or not snapshot or snapshot.collected_at<now()-timedelta(minutes=5)):
                    try:
                        data=await capture_snapshot(db,company);await publish_snapshot(db,company,data);await db.commit()
                    except TallyError:await db.rollback()
