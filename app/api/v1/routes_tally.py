from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import json
from app.core.dependencies import CurrentPrincipal
from app.database.session import get_db
from app.core.redis import get_redis_client
from app.models.tally import TallyConnection
from app.services.tally_connector import TallyConnector,TallyError,name,value
from app.services.tally_business import admin,safe_catalog,confirm_action

router=APIRouter(prefix='/integrations/tally',tags=['Tally pilot'])


class ConnectionRequest(BaseModel):
    company: str = Field(min_length=1,max_length=200)
    godown: str = Field(min_length=1,max_length=200)
    purchase_ledger: str = Field(min_length=1,max_length=200)
    sales_ledger: str = Field(min_length=1,max_length=200)
    test_company: bool = False


class ProbeRequest(BaseModel):
    company: str | None = Field(default=None,max_length=200)


async def configuration_catalog(db,principal,company):
    from app.services.tally_stock import resolve_scope
    from app.services.business_command_service import ParsedCommand
    from app.services.tally_sync import saved_snapshot,refresh_company
    from app.services.tally_sync_protocol import deserialize_catalog
    rows=await resolve_scope(db,principal,ParsedCommand(intent='stock_read',company_query=company))
    exact=[r for r in rows if r.name==company]
    if exact:
        if len(exact)!=1:raise TallyError('Company identity ambiguous; company access reconfirm karein.')
        snapshot=await saved_snapshot(db,exact[0])
        if not snapshot:
            try:await refresh_company(db,exact[0])
            except TallyError:pass
            snapshot=await saved_snapshot(db,exact[0])
        if not snapshot:raise TallyError('Complete saved masters available nahi. Helper/Tally available hone par sync karein.')
        return deserialize_catalog(snapshot.catalog)
    # Compatibility for the original direct-local development pilot only.
    from app.models.tally import TallyDevice
    paired=await db.scalar(select(TallyDevice.id).where(TallyDevice.organization_id==principal.organization_id,TallyDevice.revoked.is_(False)))
    if paired:raise TallyError('Company access pehle approve karein.')
    return await TallyConnector().catalog(company)


@router.get('')
async def status(principal:CurrentPrincipal, db:AsyncSession=Depends(get_db)):
    cfg=await db.get(TallyConnection,principal.organization_id)
    from app.api.v1.routes_tally_bridge import helper_status
    reads=await helper_status(principal,db)
    return {'configured':bool(cfg),'can_configure':principal.role in ('owner','admin'),
            'read_connection': {k:reads[k] for k in ('mode','device_status','read_capabilities','companies')},
            'connection':{k:getattr(cfg,k) for k in ('company','godown','purchase_ledger','sales_ledger','test_company')} if cfg else None,
            'notice':'Single-godown test-company pilot. GST calculations available; real GST Tally acceptance pending.'}


@router.post('/test')
async def test(request:ProbeRequest,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    admin(principal)
    try:
        connector=TallyConnector()
        if not request.company:
            # Direct function callers in legacy tests do not supply a session.
            if isinstance(db,AsyncSession):
                from app.services.tally_stock import resolve_scope
                from app.services.business_command_service import ParsedCommand
                permitted=await resolve_scope(db,principal,ParsedCommand(intent='stock_read'))
                if permitted:return {'companies':[c.name for c in permitted]}
            return {'companies':[name(c) for c in await connector.collection('Company')]}
        catalog=await configuration_catalog(db,principal,request.company) if isinstance(db,AsyncSession) else await connector.catalog(request.company)
        return {'gst_configuration_supported':bool(catalog.get('companies') and not catalog['non_gst']),'non_gst':catalog['non_gst'],'godowns':[name(g) for g in catalog['godowns']],
                'purchase_ledgers':[name(l) for l in catalog['ledgers'] if value(l,'PARENT')=='Purchase Accounts'],
                'sales_ledgers':[name(l) for l in catalog['ledgers'] if value(l,'PARENT')=='Sales Accounts'],
                'items':[name(i) for i in catalog['items']]}
    except TallyError as exc:
        raise HTTPException(503,str(exc))


@router.put('')
async def configure(request:ConnectionRequest,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    admin(principal)
    try:
        catalog=await configuration_catalog(db,principal,request.company)
        candidate=TallyConnection(organization_id=principal.organization_id,**request.model_dump())
        if catalog['non_gst']:safe_catalog(catalog,candidate)
        else:
            from app.services.tally_gst_purchase import validate_setup
            from app.services.tally_sync import config_data
            validate_setup(catalog,config_data(candidate))
    except TallyError as exc:
        raise HTTPException(422,str(exc))
    # Lock organization so initial configuration and updates serialize per workspace.
    from app.models.organization import Organization
    await db.scalar(select(Organization).where(Organization.id==principal.organization_id).with_for_update())
    cfg=await db.get(TallyConnection,principal.organization_id)
    if cfg:
        for key,val in request.model_dump().items():
            setattr(cfg,key,val)
        cfg.version+=1
    else:
        db.add(candidate)
    await db.commit()
    configured=cfg or candidate
    redis=await get_redis_client()
    try:
        await redis.set(f'tally:masters:{principal.organization_id}:{configured.version}',json.dumps({
            'items':[name(i) for i in catalog['items'][:100]],
            'parties':[name(l) for l in catalog['ledgers'] if value(l,'PARENT') in ('Sundry Debtors','Sundry Creditors')][:100],
            'units':[name(u) for u in catalog['units'][:100]]}),ex=3600)
    except Exception:
        pass  # Connection is durably saved; this optional model hint cache is not an execution gate.
    finally:
        await redis.aclose()
    return {'response':'Tally test-company configuration saved. Stock command se live read check karein.'}


@router.post('/actions/{token}/reconcile')
async def action_status(token:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    result=await confirm_action(db,principal,token,status_only=True)
    if result is None:
        raise HTTPException(404,'Action nahi mila.')
    return result


@router.get('/sync')
async def sync_status(principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    from app.services.tally_stock import resolve_scope
    from app.services.business_command_service import ParsedCommand
    from app.services.tally_sync import saved_snapshot
    rows=await resolve_scope(db,principal,ParsedCommand(intent='stock_read'))
    companies=[]
    for row in rows:
        try:snapshot=await saved_snapshot(db,row)
        except TallyError:snapshot=None
        companies.append({'company_id':row.id,'company':row.name,'last_synced_at':snapshot.collected_at.isoformat() if snapshot else None,
                          'as_of':snapshot.as_of if snapshot else None,'refresh_requested':row.refresh_requested})
    from app.models.tally import TallyAction
    from app.services.tally_sync import action_result
    actions=list((await db.scalars(select(TallyAction).where(TallyAction.organization_id==principal.organization_id,
        TallyAction.user_id==principal.user_id,TallyAction.session_id==principal.session_id,
        TallyAction.company_id.in_([c.id for c in rows])).order_by(TallyAction.created_at.desc()).limit(50))).all())
    return {'companies':companies,'actions':[action_result(a) for a in actions]}

@router.post('/companies/{company_id}/refresh')
async def refresh_request(company_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    from app.services.tally_stock import resolve_scope
    from app.services.business_command_service import ParsedCommand
    rows=await resolve_scope(db,principal,ParsedCommand(intent='stock_read',company_id=company_id))
    if len(rows)!=1:raise HTTPException(404,'Permitted company nahi mili.')
    rows[0].refresh_requested=True;await db.commit()
    return {'response':'Sync requested. Tally/helper available hone par saved data refresh hoga.'}

@router.post('/actions/{token}/cancel')
async def cancel_action(token:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    result=await confirm_action(db,principal,token,approve=False)
    if result is None:raise HTTPException(404,'Action nahi mila.')
    return result


@router.post('/actions/{token}/review')
async def count_review(token:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    from app.models.tally import TallyAction
    from app.services.tally_count import review
    action=await db.get(TallyAction,token)
    if action is None:raise HTTPException(404,'Count draft unavailable.')
    if action.backend=='mcp':
        from app.services.tally_mcp_service import review_write
        return await review_write(db,principal,action)
    try:return await review(db,principal,action)
    except TallyError as exc:raise HTTPException(409,str(exc))
