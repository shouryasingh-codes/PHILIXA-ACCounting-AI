"""Device credentials authorize only its bridge; owners authorize company access."""
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import CurrentPrincipal
from app.core.redis import get_redis_client
from app.database.session import get_db
from app.models.tally import TallyDevice, TallyReadCompany
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.services.tally_business import admin
from app.services.tally_bridge import digest, consume_result
from app.services.tally_stock import transport
from app.services.tally_connector import TallyError
from pathlib import Path
from fastapi.responses import FileResponse
from app.services.tally_diagnostics import live_key, connection_state

router = APIRouter(prefix='/integrations/tally', tags=['Tally Connect'])

def installer_path(capability='base'):
    # Prefer released builds only; never distribute an MCP candidate by accident.
    versions = ('3.5.1',) if capability=='gst_purchase' else ('3.5.1','3.5.0','3.4.0') if capability=='multi_purchase' else ('3.5.1','3.5.0','3.4.0','3.3.1','3.3.0') if capability == 'customer_ledger' else ('3.5.1','3.5.0','3.4.0','3.3.1','3.1.1')
    return next((p for version in versions if (p := Path('data/downloads/PhilixaTallyConnectorSetup-'+version+'.exe')).is_file()), None)

@router.get('/helper/download')
async def download(principal: CurrentPrincipal, capability: Literal['base','customer_ledger','multi_purchase','gst_purchase']='base'):
    admin(principal)
    path = installer_path(capability)
    if path is None: raise HTTPException(404,'Helper package not built on this deployment')
    return FileResponse(path,filename='PhilixaTallyConnectorSetup.exe',media_type='application/octet-stream')

class PairClaim(BaseModel):
    code: str = Field(pattern=r'^[A-F0-9]{12}$')
    replace: bool = False

class Permission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    identity: str = Field(min_length=1, max_length=250)
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    member_ids: list[str] = Field(default_factory=list, max_length=1000)

class CompanyApproval(BaseModel):
    mode: Literal['helper', 'local'] = 'helper'
    companies: list[Permission] = Field(max_length=1000)

class JobResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    data: dict | None = None
    error: Literal['Tally closed', 'Setup needed: enable Tally HTTP server', 'Company unavailable', 'Read failed', 'Response too large'] | None = None

class CompanyHealth(BaseModel):
    model_config = ConfigDict(extra='forbid')
    identity: str = Field(min_length=1,max_length=250)
    reachable: bool

class ConnectorHealth(BaseModel):
    model_config = ConfigDict(extra='forbid')
    connector_version: str = Field(pattern=r'^\d+\.\d+\.\d+$',max_length=30)
    startup_configured: bool
    tally_state: Literal['closed','unreachable','available']
    error_code: Literal['tally_closed','http_unreachable'] | None = None
    companies: list[CompanyHealth] = Field(default_factory=list,max_length=1000)
    mcp_build: str | None = Field(default=None,max_length=40)
    mcp_state: Literal['missing','ready','failed','disabled'] = 'missing'

async def device_auth(authorization: str = Header(default=''), db: AsyncSession = Depends(get_db)):
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Device authentication required')
    secret = authorization[7:]
    device = await db.scalar(select(TallyDevice).where(TallyDevice.credential_hash == digest(secret), TallyDevice.revoked.is_(False)))
    if not device:
        raise HTTPException(401, 'Device revoked or not paired')
    org = await db.get(Organization, device.organization_id)
    if not org or not org.is_active:
        raise HTTPException(401, 'Workspace inactive')
    return device

@router.post('/pairing/begin')
async def begin(request: Request):
    redis = await get_redis_client()
    try:
        # No forwarded-header trust; deployment proxy controls client address.
        limit_key = 'tally:pair-rate:' + (request.client.host if request.client else 'unknown')
        count = await redis.incr(limit_key)
        if count == 1: await redis.expire(limit_key, 600)
        if count > 10: raise HTTPException(429, 'Pairing limit reached; try later')
        code, secret = secrets.token_hex(6).upper(), secrets.token_urlsafe(32)
        await redis.set('tally:pair:' + code, digest(secret), ex=600)
        return {'code': code, 'credential': secret, 'expires_in': 600}
    finally:
        await redis.aclose()

@router.post('/pairing/claim')
async def claim(body: PairClaim, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    admin(principal)
    await db.scalar(select(Organization).where(Organization.id == principal.organization_id).with_for_update())
    device = await db.scalar(select(TallyDevice).where(TallyDevice.organization_id == principal.organization_id))
    if device and not device.revoked and not body.replace:
        raise HTTPException(409, 'Helper already paired; explicitly replace to revoke it')
    redis = await get_redis_client()
    try:
        hashed = await redis.getdel('tally:pair:' + body.code)
        if not hashed: raise HTTPException(410, 'Code expired or already used')
        if device:
            await redis.delete('tally:online:' + device.id, 'tally:queue:' + device.id)
            device.credential_hash, device.revoked = hashed, False
            # Reapproval required on replacement, even if company names coincide.
            rows = (await db.scalars(select(TallyReadCompany).where(TallyReadCompany.organization_id == principal.organization_id))).all()
            for row in rows: row.enabled = False
            from app.services.tally_sync import invalidate_actions
            await invalidate_actions(db,[row.id for row in rows])
        else:
            device = TallyDevice(id=secrets.token_hex(16), organization_id=principal.organization_id, credential_hash=hashed, revoked=False)
            db.add(device)
        await db.commit()
        return {'paired': True, 'device_id': device.id}
    finally:
        await redis.aclose()

@router.delete('/helper')
async def revoke(principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    admin(principal)
    await db.scalar(select(Organization).where(Organization.id == principal.organization_id).with_for_update())
    device = await db.scalar(select(TallyDevice).where(TallyDevice.organization_id == principal.organization_id))
    if device:
        device.revoked = True
        rows=list((await db.scalars(select(TallyReadCompany.id).where(TallyReadCompany.device_id==device.id))).all())
        from app.services.tally_sync import invalidate_actions
        await invalidate_actions(db,rows)
        await db.commit()
        redis = await get_redis_client()
        try: await redis.delete('tally:online:' + device.id, 'tally:v2online:'+device.id, 'tally:queue:' + device.id,'tally:queue:v2:'+device.id,'tally:v3online:'+device.id,'tally:queue:v3:'+device.id,'tally:v4online:'+device.id,'tally:queue:v4:'+device.id,'tally:v5online:'+device.id,'tally:queue:v5:'+device.id)
        finally: await redis.aclose()
    return {'revoked': True}

@router.post('/helper/heartbeat')
async def heartbeat(body: ConnectorHealth, device: TallyDevice = Depends(device_auth), db: AsyncSession = Depends(get_db)):
    rows=(await db.scalars(select(TallyReadCompany).where(TallyReadCompany.device_id==device.id,TallyReadCompany.enabled.is_(True)))).all()
    permitted={r.identity for r in rows}
    if len({c.identity for c in body.companies})!=len(body.companies) or any(c.identity not in permitted for c in body.companies):
        raise HTTPException(403,'Unapproved company diagnostic')
    data=body.model_dump();data['_credential_version']=device.credential_hash;data['received_at']=datetime.now(timezone.utc).isoformat()
    redis=await get_redis_client()
    try:
        await redis.set('tally:diagnostics:'+device.id,json.dumps(data),ex=45)
        # A closed/unreachable company invalidates prior live proof immediately.
        for row in rows:
            if body.tally_state!='available' or not any(c.identity==row.identity and c.reachable for c in body.companies):
                await redis.delete(live_key(device,row.identity))
    finally:await redis.aclose()
    return {'accepted':True}

@router.post('/setup/check')
async def check_setup(principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    from app.services.tally_stock import resolve_scope, validate_stock_data
    from types import SimpleNamespace
    rows=await resolve_scope(db,principal,SimpleNamespace(company_id=None,company_query=None))
    if not rows:raise HTTPException(409,'Approve at least one company first')
    date=datetime.now(__import__('zoneinfo').ZoneInfo('Asia/Kolkata')).date().isoformat()
    for row in rows:
        original_device=await db.get(TallyDevice,row.device_id) if row.device_id else None
        original_hash=original_device.credential_hash if original_device else None
        # Filtered collection verifies read access without exporting the whole catalog.
        try:
            data=await transport(db,principal.organization_id,row.device_id,'stock',company=row.name,identity=row.identity,
                                 as_of=date,item_query='__Philixa_connection_probe__')
            validate_stock_data(data)
            if data.get('identity')!=row.identity or data.get('company')!=row.name:raise TallyError('Company mismatch')
        except TallyError as exc:raise HTTPException(503,str(exc))
        device=await db.get(TallyDevice,row.device_id) if row.device_id else None
        if device:
            await db.refresh(device)
            await db.refresh(row)
            if device.revoked or device.credential_hash!=original_hash or not row.enabled or row.device_id!=device.id:
                raise HTTPException(409,'Connector changed; check again')
            permitted={c.id for c in await resolve_scope(db,principal,SimpleNamespace(company_id=None,company_query=None))}
            if row.id not in permitted:raise HTTPException(403,'Company permission changed')
            redis=await get_redis_client()
            try:await redis.set(live_key(device,row.identity),datetime.now(timezone.utc).isoformat(),ex=90)
            finally:await redis.aclose()
    return await helper_status(principal,db)

@router.get('/helper/status')
async def helper_status(principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    device = await db.scalar(select(TallyDevice).where(TallyDevice.organization_id == principal.organization_id, TallyDevice.revoked.is_(False)))
    rows = list((await db.scalars(select(TallyReadCompany).where(TallyReadCompany.organization_id == principal.organization_id, TallyReadCompany.enabled.is_(True)))).all())
    if principal.role not in ('owner','admin'): rows = [r for r in rows if principal.user_id in r.member_ids]
    redis = await get_redis_client()
    diagnostics=None;company_health=[]
    try:
        online = bool(device and await redis.exists('tally:online:' + device.id))
        protocol=('8' if await redis.exists('tally:v8online:'+device.id) else '7' if await redis.exists('tally:v7online:'+device.id) else '6' if await redis.exists('tally:v6online:'+device.id) else '5' if await redis.exists('tally:v5online:'+device.id) else '4' if await redis.exists('tally:v4online:'+device.id) else '3' if await redis.exists('tally:v3online:'+device.id) else '2' if await redis.exists('tally:v2online:'+device.id) else await redis.get('tally:protocol:'+device.id)) if device else None
        raw=await redis.get('tally:diagnostics:'+device.id) if device and online else None
        diagnostics=json.loads(raw) if raw else None
        if diagnostics and diagnostics.get('_credential_version')!=device.credential_hash:diagnostics=None
        reachable={c['identity']:c['reachable'] for c in (diagnostics or {}).get('companies',[])}
        for row in rows:
            proof=await redis.get(live_key(device,row.identity)) if device and online and row.device_id==device.id else None
            company_health.append({'id':row.id,'reachable':reachable.get(row.identity,False) if device and row.device_id==device.id else False,'stock_read_verified':bool(proof),'last_live_read_at':proof})
    finally: await redis.aclose()
    state=connection_state(bool(device),online,diagnostics,company_health)
    return {'connection_state':state,'setup_complete':state=='live_available','diagnostics':({k:v for k,v in diagnostics.items() if k not in ('companies','_credential_version')} if diagnostics else None),
            'company_health':company_health,'diagnostics_update_required':bool(device and online and not diagnostics),
            'paired': bool(device), 'online': online, 'can_configure': principal.role in ('owner','admin'),
            'mode': 'paired-helper' if device else 'unpaired', 'device_status': 'online' if online else 'offline',
            'read_capabilities': ['company_stock'],
            'protocol_version':int(protocol) if protocol and str(protocol).isdigit() else 1,
            'helper_update_required':bool(device and online and protocol not in ('2','3','4','5','6','7','8')),
            'count_helper_update_required':bool(device and online and protocol not in ('3','4','5','6','7','8')),
            'customer_ledger_capable':bool(device and online and protocol in ('6','7','8')),
            'customer_ledger_update_required':bool(device and protocol not in ('6','7','8')),
            'gst_purchase_capable':bool(device and online and protocol=='8'),
            'gst_purchase_update_required':bool(device and protocol!='8'),
            'multi_purchase_capable':bool(device and online and protocol in ('7','8')),
            'multi_purchase_update_required':bool(device and protocol not in ('7','8')),
            'installer_url': os.getenv('PHILIXA_CONNECT_INSTALLER_URL') or ('/api/v1/integrations/tally/helper/download?capability=multi_purchase' if device and protocol not in ('7','8') and installer_path('multi_purchase') else '/api/v1/integrations/tally/helper/download?capability=customer_ledger' if device and protocol not in ('6','7','8') and installer_path('customer_ledger') else '/api/v1/integrations/tally/helper/download' if installer_path() else None),
            'local_available': os.getenv('PHILIXA_TALLY_ALLOW_LOCAL_READS','0') == '1',
            'companies': [{'id': r.id, 'identity': r.identity, 'name': r.name, 'aliases': r.aliases, 'member_ids': r.member_ids if principal.role in ('owner','admin') else []} for r in rows]}

@router.get('/companies/discover')
async def discover(principal: CurrentPrincipal, mode: Literal['helper','local'] = 'helper', db: AsyncSession = Depends(get_db)):
    admin(principal)
    if mode == 'local' and os.getenv('PHILIXA_TALLY_ALLOW_LOCAL_READS','0') != '1':
        raise HTTPException(403, 'Local read transport disabled')
    device = await db.scalar(select(TallyDevice).where(TallyDevice.organization_id == principal.organization_id, TallyDevice.revoked.is_(False))) if mode == 'helper' else None
    if mode == 'helper' and not device: raise HTTPException(409, 'Pair helper first')
    try:
        return await transport(db, principal.organization_id, device.id if device else None, 'discover')
    except TallyError as exc: raise HTTPException(503, str(exc))

@router.put('/companies')
async def approve(body: CompanyApproval, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    admin(principal)
    initial_device = await db.scalar(select(TallyDevice).where(TallyDevice.organization_id == principal.organization_id)) if body.mode == 'helper' else None
    initial_hash = initial_device.credential_hash if initial_device else None
    discovered = await discover(principal, body.mode, db)
    descriptors = discovered['companies']
    valid = {(c['identity'], c['name']) for c in descriptors if sum(x['identity'] == c['identity'] for x in descriptors) == 1 and sum(x['name'] == c['name'] for x in descriptors) == 1}
    if len({c.identity for c in body.companies}) != len(body.companies): raise HTTPException(422,'Duplicate company')
    members = set((await db.scalars(select(OrganizationMembership.user_id).where(OrganizationMembership.organization_id == principal.organization_id, OrganizationMembership.status == 'active'))).all())
    for c in body.companies:
        if (c.identity,c.name) not in valid or not set(c.member_ids) <= members or any(not a.strip() or len(a)>200 for a in c.aliases):
            raise HTTPException(422, 'Company identity/member/alias invalid')
    await db.scalar(select(Organization).where(Organization.id == principal.organization_id).with_for_update())
    device = await db.scalar(select(TallyDevice).where(TallyDevice.organization_id == principal.organization_id, TallyDevice.revoked.is_(False))) if body.mode == 'helper' else None
    if device: await db.refresh(device)
    if body.mode == 'helper' and not device: raise HTTPException(409,'Helper changed; discover again')
    if device and (device.revoked or device.credential_hash != initial_hash): raise HTTPException(409,'Helper changed; discover again')
    previous = list((await db.scalars(select(TallyReadCompany).where(TallyReadCompany.organization_id == principal.organization_id))).all())
    for row in previous: row.enabled = False
    for c in body.companies:
        row = next((r for r in previous if r.identity == c.identity and r.device_id == (device.id if device else None)), None)
        if row is None:
            row = TallyReadCompany(id=secrets.token_hex(16),organization_id=principal.organization_id,device_id=device.id if device else None,identity=c.identity,name=c.name)
            db.add(row)
        row.name, row.enabled, row.aliases, row.member_ids = c.name, True, c.aliases, c.member_ids
        row.refresh_requested=True
    from app.services.tally_sync import invalidate_actions
    await db.flush()
    disabled=list((await db.scalars(select(TallyReadCompany.id).where(TallyReadCompany.organization_id==principal.organization_id,TallyReadCompany.enabled.is_(False)))).all())
    await invalidate_actions(db,disabled)
    await db.commit()
    return {'response':'Company access saved. Ab bina company select kiye stock pooch sakte hain.'}

@router.get('/helper/jobs')
async def jobs(protocol_version:int=1, device: TallyDevice = Depends(device_auth), db: AsyncSession = Depends(get_db)):
    redis = await get_redis_client()
    try:
        if not await redis.exists('tally:online:'+device.id):
            rows=(await db.scalars(select(TallyReadCompany).where(TallyReadCompany.device_id==device.id,TallyReadCompany.enabled.is_(True)))).all()
            for row in rows:row.refresh_requested=True
            await db.commit()
        await redis.set('tally:online:' + device.id, '1', ex=45)
        await redis.set('tally:protocol:'+device.id,str(protocol_version),ex=45)
        if protocol_version>=2:await redis.set('tally:v2online:'+device.id,'1',ex=45)
        if protocol_version>=3:await redis.set('tally:v3online:'+device.id,'1',ex=45)
        if protocol_version>=4:await redis.set('tally:v4online:'+device.id,'1',ex=45)
        if protocol_version>=5:await redis.set('tally:v5online:'+device.id,'1',ex=45)
        if protocol_version>=6:await redis.set('tally:v6online:'+device.id,'1',ex=45)
        if protocol_version>=7:await redis.set('tally:v7online:'+device.id,'1',ex=45)
        if protocol_version>=8:await redis.set('tally:v8online:'+device.id,'1',ex=45)
        # Brief polls: no database connection held during a long network wait.
        queued = await redis.lpop('tally:queue:v2:'+device.id) if protocol_version>=2 else None
        if protocol_version>=3:
            newer=await redis.lpop('tally:queue:v3:'+device.id)
            if newer:
                if queued:await redis.lpush('tally:queue:v2:'+device.id,queued)
                queued=newer
        if protocol_version>=4:
            newest=await redis.lpop('tally:queue:v4:'+device.id)
            if newest:
                if queued:
                    previous_queue='tally:queue:v3:' if json.loads(queued)['operation'].startswith('stock_count_') else 'tally:queue:v2:'
                    await redis.lpush(previous_queue+device.id,queued)
                queued=newest
        if protocol_version>=5:
            compiled=await redis.lpop('tally:queue:v5:'+device.id)
            if compiled:
                if queued:
                    op=json.loads(queued)['operation']
                    previous_queue='tally:queue:v4:' if op=='mcp_read' else 'tally:queue:v3:' if op.startswith('stock_count_') else 'tally:queue:v2:'
                    await redis.lpush(previous_queue+device.id,queued)
                queued=compiled
        if protocol_version>=6:
            customer_job=await redis.lpop('tally:queue:v6:'+device.id)
            if customer_job:
                if queued:
                    op=json.loads(queued)['operation']
                    previous_queue='tally:queue:v5:' if op=='mcp_compile' else 'tally:queue:v4:' if op.startswith('mcp_') else 'tally:queue:v3:' if op.startswith('stock_count_') else 'tally:queue:v2:'
                    await redis.lpush(previous_queue+device.id,queued)
                queued=customer_job
        if protocol_version>=7:
            multi_job=await redis.lpop('tally:queue:v7:'+device.id)
            if multi_job:
                if queued:
                    op=json.loads(queued)['operation']
                    previous_queue='tally:queue:v6:' if op.startswith('customer_ledger_') else 'tally:queue:v5:' if op=='mcp_compile' else 'tally:queue:v4:' if op.startswith('mcp_') else 'tally:queue:v3:' if op.startswith('stock_count_') else 'tally:queue:v2:'
                    await redis.lpush(previous_queue+device.id,queued)
                queued=multi_job
        if protocol_version>=8:
            gst_job=await redis.lpop('tally:queue:v8:'+device.id)
            if gst_job:
                if queued:
                    op=json.loads(queued)['operation']
                    previous_queue='tally:queue:v7:' if op.startswith('purchase_multi_') else 'tally:queue:v6:' if op.startswith('customer_ledger_') else 'tally:queue:v5:' if op=='mcp_compile' else 'tally:queue:v4:' if op.startswith('mcp_') else 'tally:queue:v3:' if op.startswith('stock_count_') else 'tally:queue:v2:'
                    await redis.lpush(previous_queue+device.id,queued)
                queued=gst_job
        if not queued:queued = await redis.lpop('tally:queue:' + device.id)
        approved=(await db.scalars(select(TallyReadCompany).where(TallyReadCompany.device_id==device.id,TallyReadCompany.enabled.is_(True)))).all()
        descriptors=[{'identity':r.identity,'name':r.name} for r in approved]
        if not queued: return {'device_id':device.id,'job':None,'approved_companies':descriptors}
        job = json.loads(queued)
        if job.get('credential_version') != device.credential_hash: return {'device_id':device.id,'job':None}
        if not await redis.exists('tally:job:' + job['id']): return {'device_id':device.id,'job':None}
        if job['operation'] != 'discover':
            permitted = await db.scalar(select(TallyReadCompany.id).where(TallyReadCompany.organization_id == device.organization_id,
                TallyReadCompany.device_id == device.id, TallyReadCompany.identity == job.get('identity'),
                TallyReadCompany.name == job.get('company'), TallyReadCompany.enabled.is_(True)))
            if not permitted: raise HTTPException(403,'Company approval revoked')
        if job['operation'] not in ('discover','stock') and protocol_version<2:
            raise HTTPException(409,'Helper update required')
        if job['operation'].startswith('stock_count_') and protocol_version<3:
            raise HTTPException(409,'Count helper update required')
        if job['operation'].startswith('mcp_'):
            if protocol_version<4 or job['operation'] not in ('mcp_read','mcp_compile'):raise HTTPException(409,'MCP helper update required')
            if job['operation']=='mcp_compile' and protocol_version<5:raise HTTPException(409,'MCP compiler helper update required')
            from app.services.tally_mcp import validate_arguments
            try:
                contract=validate_arguments(job.get('tool'),job.get('arguments'),read_only=job['operation']=='mcp_read')
                if job['operation']=='mcp_compile':
                    from app.services.tally_mcp_write_validation import validate_write
                    validate_write(job.get('tool'),job.get('arguments'))
                    from app.models.tally import TallyAction
                    from app.models.user import User
                    action=await db.get(TallyAction,job.get('action_id'),populate_existing=True)
                    member=await db.get(OrganizationMembership,(action.user_id,device.organization_id),populate_existing=True) if action else None
                    actor=await db.get(User,action.user_id,populate_existing=True) if action else None
                    if contract['category']!='write' or not action or action.backend!='mcp' or action.status!='draft' or action.organization_id!=device.organization_id or action.company_id!=permitted or action.device_version!=device.credential_hash or action.expires_at<=datetime.now(timezone.utc) or action.payload.get('tool')!=job.get('tool') or action.payload.get('arguments')!=job.get('arguments') or not actor or not actor.is_active or not member or member.status!='active' or member.role not in ('owner','admin'):
                        raise HTTPException(403,'MCP draft authorization invalid')
            except (TallyError,ValueError):raise HTTPException(403,'MCP capability/arguments rejected')
        if job['operation'].startswith(('purchase_','stock_count_','customer_ledger_')):
            from app.models.tally import TallyAction, TallyConnection
            from app.models.organization_membership import OrganizationMembership
            from app.models.user import User
            from app.services.tally_sync import config_data
            action=await db.get(TallyAction,job.get('action_id'))
            expected_operation='purchase_gst' if job['operation'].startswith('purchase_gst_') else 'purchase_multi' if job['operation'].startswith('purchase_multi_') else 'customer_ledger_create' if job['operation'].startswith('customer_ledger_') else 'stock_count_set' if job['operation'].startswith('stock_count_') else None
            if action and (action.payload.get('operation') if action.payload.get('operation') in ('stock_count_set','customer_ledger_create','purchase_multi','purchase_gst') else None)!=expected_operation:
                raise HTTPException(403,'Action operation mismatch')
            cfg=await db.get(TallyConnection,device.organization_id)
            allowed_status={'purchase_validate':('queued',),'purchase_post':('submitting',),'purchase_reconcile':('submitting','verification_pending')}
            allowed_status.update(purchase_gst_validate=('queued',),purchase_gst_post=('submitting',),purchase_gst_reconcile=('submitting','verification_pending'))
            if job['operation'].startswith('purchase_gst_'):
                from app.services.purchase_tax_service import ensure_approved_profile,acceptance_enabled
                if protocol_version<8 or not action or action.backend!='python' or action.schema_version!=3 or action.approved_arguments!=job.get('payload') or action.target_identity!={'company':job.get('identity')}:raise HTTPException(403,'GST authorization/update required')
                if job['operation']!='purchase_gst_reconcile':
                    try:await ensure_approved_profile(db,action)
                    except TallyError:raise HTTPException(403,'GST setup changed')
                    if not acceptance_enabled():raise HTTPException(403,'GST live acceptance pending')
            allowed_status.update(purchase_multi_validate=('queued',),purchase_multi_post=('submitting',),purchase_multi_reconcile=('submitting','verification_pending'))
            if job['operation'].startswith('purchase_multi_') and (protocol_version<7 or not action or action.backend!='python' or action.schema_version!=2 or action.approved_arguments!=job.get('payload') or action.target_identity!={'company':job.get('identity')}):
                raise HTTPException(403,'Multi-item purchase authorization/update required')
            allowed_status.update(stock_count_validate=('draft','awaiting_review','preview','needs_review','queued'),stock_count_post=('submitting',),stock_count_reconcile=('submitting','verification_pending'))
            allowed_status.update(customer_ledger_validate=('queued',),customer_ledger_post=('submitting',),customer_ledger_reconcile=('submitting','verification_pending'))
            if job['operation'].startswith('customer_ledger_') and (protocol_version<6 or not action or action.approved_arguments!=job.get('payload') or action.backend!='python'):
                raise HTTPException(403,'Customer ledger authorization/update required')
            member=await db.get(OrganizationMembership,(action.user_id,device.organization_id)) if action else None
            actor=await db.get(User,action.user_id) if action else None
            if not action or action.organization_id!=device.organization_id or action.company_id!=permitted or action.device_version!=device.credential_hash or action.status not in allowed_status.get(job['operation'],()) or action.payload!=job.get('payload'):
                raise HTTPException(403,'Purchase authorization invalid')
            if not cfg or not cfg.test_company or cfg.version!=action.connection_version or config_data(cfg)!=job.get('config') or not actor or not actor.is_active or not member or member.status!='active' or member.role not in ('owner','admin'):
                raise HTTPException(403,'Purchase permission/configuration changed')
        job.pop('credential_version', None)
        return {'device_id': device.id, 'job': job, 'approved_companies': descriptors}
    finally: await redis.aclose()

@router.post('/helper/results')
async def results(request: Request, device: TallyDevice = Depends(device_auth), db: AsyncSession = Depends(get_db)):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 2_000_000: raise HTTPException(413,'Result too large')
    try: body = JobResult.model_validate_json(bytes(raw))
    except ValidationError: raise HTTPException(422,'Invalid helper result')
    if (body.data is None) == (body.error is None): raise HTTPException(422,'Exactly one of data/error required')
    await db.scalar(select(Organization).where(Organization.id == device.organization_id).with_for_update())
    original_hash = device.credential_hash
    await db.refresh(device)
    if device.revoked or device.credential_hash != original_hash: raise HTTPException(401,'Device revoked/replaced')
    redis = await get_redis_client()
    try: await consume_result(redis, device, body.id, body.model_dump(exclude={'id'},exclude_none=True))
    finally: await redis.aclose()
    return {'accepted': True}
