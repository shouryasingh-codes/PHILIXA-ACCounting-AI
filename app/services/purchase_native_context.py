"""Durable native-history refreshes, safe to recover after Redis/worker restart."""
import hashlib,json,secrets
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from sqlalchemy import select,or_
from sqlalchemy.dialects.postgresql import insert
from fastapi import HTTPException
from app.models.purchase_agent import PurchaseHistoryCache
from app.models.purchase_draft import PurchaseDraft
from app.services import purchase_draft_service as drafts,tally_sync as sync
from app.services.purchase_identity import exact_master,master_identity,master_fingerprint
from app.services.tally_connector import TallyError,value
from app.services.tally_sync_protocol import deserialize_catalog
from app.services.tally_purchase_history import validate_query,digest_query

TTL=timedelta(minutes=15)

def history_unit_matches(requested,historical,native):
    """Only a bag/bags spelling alias, never a quantity/unit conversion."""
    if requested==historical:return True
    return historical==native and {str(requested).casefold(),str(native).casefold()}=={'bag','bags'}

def suggestion_version(suggestion):
    return hashlib.sha256(json.dumps(suggestion,sort_keys=True).encode()).hexdigest()

def choose_supplier_suggestion(results):
    """Require complete coverage and one supplier with usable matching evidence."""
    if not results or any(c.get('status')!='ready' or not c.get('complete') for _,c in results):
        return None
    candidates=[(supplier,c['suggestions']) for supplier,c in results if c.get('suggestions')]
    # Conflicting/unusable prices from another supplier are still evidence of
    # multiple suppliers, not proof that only the usable-price supplier exists.
    evidenced=[supplier for supplier,c in results if c.get('matching_history') or c.get('suggestions')]
    if len(candidates)!=1 or len(evidenced)!=1:return None
    supplier,evidence=candidates[0]
    return dict(supplier=supplier,rates=evidence,requires_confirmation=True)

async def conversation_history(db,principal,row,catalog):
    """Bounded read-only discovery; never edits supplier/rate or authorises posting."""
    import copy
    from app.services.tally_connector import name,value
    if row.content.get('party_name'):
        return await context(db,principal,row)
    # Avoid broad scans or deciding identities from spelling similarity.
    suppliers=[name(v) for v in catalog['ledgers'] if value(v,'PARENT')=='Sundry Creditors']
    if not suppliers or len(suppliers)>3 or len(set(suppliers))!=len(suppliers):
        return {'status':'needs_identity','suggestions':[]}
    if any(l.get('rate') is not None for l in row.content.get('lines',[])):
        return {'status':'needs_identity','suggestions':[]}
    results=[]
    for supplier in suppliers:
        content=copy.deepcopy(row.content);content['party_name']=supplier
        candidate=SimpleNamespace(id=row.id,company_id=row.company_id,content=content)
        results.append((supplier,await context(db,principal,candidate)))
    suggestion=choose_supplier_suggestion(results)
    failure=next((c for _,c in results if c.get('status') in ('error','unavailable','needs_identity')),None)
    return {'status':'error' if failure else 'ready' if all(c.get('status')=='ready' for _,c in results) else 'pending',
            'reason':failure.get('reason') if failure else None,
            'suggestions':[], 'supplier_suggestion':suggestion}

def enabled():
    import os
    return os.getenv('PHILIXA_PURCHASE_AGENT_ENABLED','0')=='1'

def fresh(stamp):return stamp is not None and sync.now()-TTL <= stamp <= sync.now()+timedelta(seconds=30)

async def binding_for(db,company,catalog):
    device=await sync.bound_device(db,company)
    return {'company_identity':company.identity,'device_version':device.credential_hash if device else None}

def query_for(content,catalog):
    from datetime import date
    from zoneinfo import ZoneInfo
    today=datetime.now(ZoneInfo('Asia/Kolkata')).date()
    ceiling=min(date.fromisoformat(content.get('entry_date') or str(today)),today)
    supplier=exact_master(catalog,'supplier',content.get('party_name'))
    items=[]
    for line in content['lines']:
        item=exact_master(catalog,'item',line.get('item_name'))
        entry=dict(name=item.get('NAME') or item.findtext('NAME'),id=master_identity(item))
        if entry not in items:items.append(entry)
    return validate_query(dict(supplier=supplier.get('NAME') or supplier.findtext('NAME'),supplier_id=master_identity(supplier),
        items=items,from_date=(ceiling-timedelta(days=179)).isoformat(),to_date=ceiling.isoformat()))

def fingerprints(catalog,query):
    return {'supplier':master_fingerprint(exact_master(catalog,'supplier',query['supplier'])),
            'items':{v['id']:master_fingerprint(exact_master(catalog,'item',v['name'])) for v in query['items']}}

async def enqueue(row,pool=None):
    from app.core.arq import get_arq_pool
    from app.services.bill_document_service import QUEUE
    pool=pool or get_arq_pool()
    owned=False
    try:
        if pool is None:
            # ARQ workers have ctx['redis'], but not the web app's global pool.
            # A task-created history job must not wait for the minute cron.
            from arq.connections import create_pool,RedisSettings
            from app.core.config import get_settings
            pool=await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
            owned=True
        await pool.enqueue_job('refresh_purchase_history',row.id,_queue_name=QUEUE,
            _job_id=f'purchase-context:{row.id}:{row.attempts}:{row.updated_at.timestamp()}')
    except Exception:pass # Committed PostgreSQL state is recovered by cron.
    finally:
        if owned:await pool.aclose()

async def context(db,principal,row,force=False):
    company=await drafts.company_for(db,principal,row.company_id)
    snapshot=await sync.saved_snapshot(db,company)
    if not snapshot:return {'status':'unavailable','reason':'Tally masters sync karein.','suggestions':[]}
    catalog=deserialize_catalog(snapshot.catalog)
    try:
        query=query_for(row.content,catalog)
        binding={**await binding_for(db,company,catalog),**fingerprints(catalog,query)}
    except (TallyError,ValueError,TypeError):
        return {'status':'needs_identity','suggestions':[]}
    # Historical prices are unnecessary when every current price is explicitly
    # grounded in the user's message. Never call incomplete history "complete";
    # only this current-master context is complete. Full-FY duplicate checks
    # remain independent in the proposal/compiler.
    provenance=(getattr(row,'extraction_metadata',None) or {}).get('agent_provenance',{})
    explicit_rates=bool(row.content.get('lines')) and all(
        line.get('rate') is not None and
        (proof:=provenance.get(f'lines.{index}.rate',{})).get('status')=='explicit' and
        proof.get('source_type')=='user_message' and str(proof.get('value'))==str(line['rate'])
        for index,line in enumerate(row.content.get('lines',[])))
    if explicit_rates and fresh(snapshot.collected_at):
        proof={'query':query,'binding':binding}
        version=hashlib.sha256(json.dumps([proof,snapshot.generation],sort_keys=True).encode()).hexdigest()
        return dict(status='ready',history_status='not_required',history_complete=None,complete=True,
            coverage='Current explicit rates and fresh native masters; historical rates not used.',
            rate_context=proof,collected_at=snapshot.collected_at.isoformat(),
            master_generation=snapshot.generation,evidence_version=version,suggestions=[])
    key=hashlib.sha256(json.dumps([principal.organization_id,company.id,query,binding],sort_keys=True).encode()).hexdigest()
    cache=await db.get(PurchaseHistoryCache,key,populate_existing=True)
    if cache is None:
        await db.execute(insert(PurchaseHistoryCache).values(id=key,organization_id=principal.organization_id,
            company_id=company.id,draft_id=row.id,user_id=principal.user_id,query=query,binding=binding,
            data={},status='queued',attempts=0,updated_at=sync.now()).on_conflict_do_nothing())
        await db.commit();cache=await db.get(PurchaseHistoryCache,key)
        await enqueue(cache)
    elif force or (cache.status=='ready' and (not fresh(cache.collected_at) or not fresh(snapshot.collected_at))):
        if cache.status!='processing':
            cache.status='queued';cache.error=None;cache.attempts=0;cache.updated_at=sync.now()
            cache.draft_id=row.id;cache.user_id=principal.user_id
            await db.commit();await enqueue(cache)
    current=cache.status=='ready' and fresh(cache.collected_at) and fresh(snapshot.collected_at)
    suggestions=[];rate_checks=[]
    if current:
        records=cache.data.get('records',[])
        for index,line in enumerate(row.content['lines']):
            if line.get('rate') is not None:
                rate_checks.append({'field':f'{index}:rate','status':'provided','reason':'Current rate already supplied; history cannot replace it.'})
                continue
            item=exact_master(catalog,'item',line.get('item_name'))
            matches=[r for r in records if r['item_id']==master_identity(item) and history_unit_matches(line.get('unit'),r['unit'],value(item,'BASEUNITS'))]
            if not matches:
                rate_checks.append({'field':f'{index}:rate','status':'unresolved','reason':'No same native item/base-unit purchase in the complete scoped history.'})
                continue
            latest=max(r['entry_date'] for r in matches);matches=[r for r in matches if r['entry_date']==latest]
            if len({r['rate'] for r in matches})!=1:
                rate_checks.append({'field':f'{index}:rate','status':'conflict','reason':'Latest matching purchases have different rates; ask actual rate.'})
                continue
            evidence=matches[0]
            rate_checks.append({'field':f'{index}:rate','status':'suggested','reason':'Latest matching native purchase; requires current transaction confirmation.'})
            suggestions.append(dict(field=f'{index}:rate',value=evidence['rate'],source='native_tally_purchase',
                source_id=evidence['voucher_id'],alteration_id=evidence['alteration_id'],entry_date=latest,
                invoice_number=evidence['invoice_number'],observed_at=cache.collected_at.isoformat(),requires_confirmation=True))
    version=hashlib.sha256(json.dumps([key,cache.generation,snapshot.generation,current],sort_keys=True).encode()).hexdigest()
    return dict(status='ready' if current else 'stale' if cache.status=='ready' else cache.status,
        reason=cache.error,cache_id=key,generation=cache.generation,master_generation=snapshot.generation,
        collected_at=cache.collected_at.isoformat() if cache.collected_at else None,evidence_version=version,
        suggestions=suggestions,rate_checks=rate_checks,matching_history=bool(cache.data.get('records')) if current else False,complete=current,job_id=key)

async def permitted_job(db,row):
    from app.models.organization_membership import OrganizationMembership
    from app.models.user import User
    member=await db.get(OrganizationMembership,(row.user_id,row.organization_id),populate_existing=True)
    user=await db.get(User,row.user_id,populate_existing=True)
    if not member or member.status!='active' or member.role not in ('owner','admin') or not user or not user.is_active:
        raise TallyError('Purchase context permission changed.')
    principal=SimpleNamespace(organization_id=row.organization_id,user_id=row.user_id,role=member.role,session_id='context-worker')
    draft=await drafts.scoped_draft(db,principal,row.draft_id)
    if draft.company_id!=row.company_id:raise TallyError('History draft company changed.')
    company=await drafts.company_for(db,principal,row.company_id)
    catalog=deserialize_catalog((await sync.saved_snapshot(db,company)).catalog)
    if {**await binding_for(db,company,catalog),**fingerprints(catalog,row.query)}!=row.binding:
        raise TallyError('History masters/device changed. Refresh context.')
    return company

async def refresh_purchase_history(ctx,cache_id):
    from app.database.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        row=await db.scalar(select(PurchaseHistoryCache).where(PurchaseHistoryCache.id==cache_id).with_for_update())
        if not row or row.status not in ('queued','processing'):return
        if row.status=='processing' and row.lease_until and row.lease_until>sync.now():return
        if row.attempts>=2:row.status='error';row.error='History read retry limit reached.';await db.commit();return
        token=secrets.token_hex(16);row.lease_token=token;row.lease_until=sync.now()+timedelta(seconds=240)
        row.status='processing';row.attempts+=1;await db.commit()
        try:
            company=await permitted_job(db,row)
            # Refresh current master evidence before treating history as usable.
            await sync.refresh_company(db,company)
            company=await permitted_job(db,row)
            manifest=await sync.operation(db,company,'purchase_history_read',payload=row.query)
            expected={'company':company.name,'identity':company.identity,'query':digest_query(row.query)}
            if any(manifest.get(k)!=v for k,v in expected.items()):raise TallyError('History manifest identity mismatch.')
            hashes=manifest.get('hashes')
            import re
            if not isinstance(hashes,list) or len(hashes)>50 or not re.fullmatch('[a-f0-9]{32}',manifest.get('generation','')):raise TallyError('History page limit exceeded.')
            records=[];size=0
            for page,digest in enumerate(hashes):
                reply=await sync.operation(db,company,'purchase_history_read',payload=row.query,generation=manifest['generation'],page=page)
                if any(reply.get(k)!=v for k,v in expected.items()) or reply.get('generation')!=manifest['generation'] or reply.get('page')!=page:
                    raise TallyError('History page identity mismatch.')
                entries=reply.get('records');encoded=json.dumps(entries,sort_keys=True).encode();size+=len(encoded)
                if not isinstance(entries,list) or len(entries)>100 or size>10_000_000 or hashlib.sha256(encoded).hexdigest()!=digest:
                    raise TallyError('History page incomplete/oversized.')
                records.extend(entries)
            if len(records)!=manifest.get('count') or len(records)>5000 or manifest.get('complete') is not True:
                raise TallyError('History incomplete; no rate suggestion available.')
            from decimal import Decimal,InvalidOperation
            seen=set();item_ids={v['id'] for v in row.query['items']}
            for record in records:
                try:
                    if record['supplier_id']!=row.query['supplier_id'] or record['item_id'] not in item_ids or not row.query['from_date']<=record['entry_date']<=row.query['to_date']:
                        raise ValueError()
                    if record['supplier_fingerprint']!=row.binding['supplier'] or record['item_fingerprint']!=row.binding['items'][record['item_id']]:raise ValueError()
                    key=(record['voucher_id'],record['item_id'])
                    if key in seen or not record['voucher_id'] or not record['alteration_id']:raise ValueError()
                    seen.add(key)
                    rate=Decimal(record['rate'])
                    if not rate.is_finite() or rate<=0:raise ValueError()
                except (KeyError,TypeError,ValueError,InvalidOperation):raise TallyError('History record evidence invalid.')
            stamp=datetime.fromisoformat(manifest['collected_at'])
            if stamp.tzinfo is None or not fresh(stamp):raise TallyError('History capture stale.')
            await db.refresh(row)
            if row.lease_token!=token:return
            await permitted_job(db,row)
            row.data={'records':records};row.generation=manifest['generation'];row.collected_at=stamp
            row.status='ready';row.error=None
        except (TallyError,HTTPException,ValueError,KeyError,TypeError,AttributeError) as exc:
            await db.rollback();row=await db.get(PurchaseHistoryCache,cache_id,populate_existing=True)
            if row.lease_token!=token:return
            message=str(exc)
            transient=any(v in message.lower() for v in ('timeout','reachable','offline'))
            row.status='queued' if transient and row.attempts<2 else 'error'
            row.error='Tally history abhi available nahi; connector/company check karke Refresh karein.' if transient else 'History incomplete ya masters badle hain; refresh/review karein.'
            if 'protocol 10' in message or '3.7' in message:
                row.error='Native history ke liye Philixa Tally Connector 3.7 update karein; pairing retained rahegi.'
        row.lease_token=None;row.lease_until=None;row.updated_at=sync.now();await db.commit()

async def recover(ctx):
    from app.database.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        rows=(await db.scalars(select(PurchaseHistoryCache).where(or_(PurchaseHistoryCache.status=='queued',
            (PurchaseHistoryCache.status=='processing') & (PurchaseHistoryCache.lease_until<=sync.now()))).limit(100))).all()
        for row in rows:await enqueue(row,ctx['redis'])

async def guard_action(db,action):
    from app.services.goods_receipt_link_service import guard as receipt_link_guard
    await receipt_link_guard(db,action)
    receipt_proof=(action.preconditions or {}).get('receipt_draft')
    if receipt_proof:
        receipt_row=await db.get(PurchaseDraft,receipt_proof['id'],populate_existing=True)
        if not receipt_row or receipt_row.organization_id!=action.organization_id or receipt_row.company_id!=action.company_id or receipt_row.revision!=receipt_proof['revision'] or receipt_row.action_id!=action.token:
            raise TallyError('Receipt draft changed; create a fresh preview.')
    proof=(action.preconditions or {}).get('purchase_agent')
    if not proof:return
    row=await db.get(PurchaseDraft,proof['draft_id'],populate_existing=True)
    if not row or row.company_id!=action.company_id or row.organization_id!=action.organization_id or row.revision!=proof['revision']:
        raise TallyError('Purchase proposal changed; review again.')
    cache=await db.get(PurchaseHistoryCache,proof['cache_id'],populate_existing=True) if proof.get('cache_id') else None
    company=await db.get(__import__('app.models.tally',fromlist=['TallyReadCompany']).TallyReadCompany,action.company_id,populate_existing=True)
    snapshot=await sync.saved_snapshot(db,company)
    if not snapshot or not fresh(snapshot.collected_at):raise TallyError('Purchase masters stale; refresh and review.')
    if cache and (cache.status!='ready' or not fresh(cache.collected_at) or cache.generation!=proof.get('generation')):
        raise TallyError('Purchase context changed/stale; refresh and review.')
    if proof.get('cache_id') and not cache:raise TallyError('Purchase history evidence missing.')
    if cache:
        catalog=deserialize_catalog(snapshot.catalog)
        if cache.binding!={**await binding_for(db,company,catalog),**fingerprints(catalog,cache.query)}:
            raise TallyError('Purchase master identities changed; review again.')
    rate_context=proof.get('rate_context')
    if rate_context:
        catalog=deserialize_catalog(snapshot.catalog)
        query=query_for(row.content,catalog)
        if query!=rate_context.get('query') or rate_context.get('binding')!={**await binding_for(db,company,catalog),**fingerprints(catalog,query)}:
            raise TallyError('Explicit-rate master identities changed; review again.')
