"""Existing principal/company grants gate MCP reads; rollout is opt-in."""
import os
from fastapi import HTTPException
from app.models.tally import TallyDevice
from app.services.tally_stock import resolve_scope
from app.services.tally_bridge import request_job
from app.services.tally_connector import TallyError
from app.services.tally_mcp import validate_arguments, PIN
from app.services.tally_mcp_reports import report_catalog, dates, display, LABELS

async def read_report(db, principal, parsed):
    if parsed.unsupported_reason:
        return {'response':parsed.unsupported_reason,'capability':'blocked'}
    full_reports=os.getenv('PHILIXA_MCP_READ_ENABLED')=='1'
    purchase_only=os.getenv('PHILIXA_PURCHASE_REPORT_ENABLED')=='1'
    if not full_reports and not purchase_only:
        return {'response':'MCP reports rollout disabled; existing stock/purchase available.', 'capability':'disabled'}
    if not parsed.mcp_tool:
        return {'response':'Kaunsi Tally report chahiye? Report select karein.',
                'mcp_catalog':[r for r in report_catalog() if full_reports or r['tool']=='get_purchase_register'], 'capability':'report_selection'}
    if not full_reports and parsed.mcp_tool!='get_purchase_register':
        return {'response':'Abhi sirf Purchase Register enabled hai.','capability':'disabled'}
    from app.services.tally_mcp import CONTRACTS
    contract=CONTRACTS.get(parsed.mcp_tool)
    if not contract or contract['category']!='read':
        return {'response':'Report tool/fields unavailable or invalid.', 'capability':'blocked'}
    # Missing fields produce a report form, not invented dates or an invalid job.
    missing=set(contract['inputSchema'].get('required',[]))-set(parsed.mcp_arguments)
    if missing:
        return {'response':'Report ki date/details select karein.', 'capability':'report_fields_required',
                'mcp_form':{'tool':parsed.mcp_tool,'label':LABELS[parsed.mcp_tool],
                    'schema':contract['inputSchema'],'fields':parsed.model_dump(mode='json',exclude={'intent'})}}
    try:
        arguments=dates(parsed.mcp_arguments)
        validate_arguments(parsed.mcp_tool, arguments)
    except (TallyError,ValueError):
        return {'response':'Report tool/fields unavailable or invalid.', 'capability':'blocked'}
    rows=await resolve_scope(db,principal,parsed)
    if len(rows)!=1:
        return {'response':'Ek approved company select karein.' if rows else 'Approved Tally company nahi mili. Connection setup karein.',
                'capability':'company_selection_required', 'connect_tally':not rows,
                'tally_choices':[{'name':c.name,'command':{'intent':'mcp_read','fields':{
                    **parsed.model_dump(mode='json',exclude={'intent'}),'company_id':c.id}}} for c in rows]}
    company=rows[0]
    device=await db.get(TallyDevice,company.device_id) if company.device_id else None
    if not device or device.revoked or device.organization_id!=principal.organization_id:
        return {'response':'Updated paired Tally Connector required.', 'capability':'update_required'}
    original=device.credential_hash
    try:
        data=await request_job(device,'mcp_read',company=company.name,identity=company.identity,
                               tool=parsed.mcp_tool,arguments=arguments)
    except TallyError:
        return {'response':'MCP report unavailable; no live result verified.', 'capability':'unavailable'}
    await db.refresh(device);await db.refresh(company)
    from app.models.organization_membership import OrganizationMembership
    from app.models.organization import Organization
    from app.models.user import User
    membership=await db.get(OrganizationMembership,(principal.user_id,principal.organization_id),populate_existing=True)
    actor=await db.get(User,principal.user_id,populate_existing=True)
    organization=await db.get(Organization,principal.organization_id,populate_existing=True)
    if not membership or membership.status!='active' or membership.role!=principal.role or not actor or not actor.is_active or not organization or not organization.is_active:
        raise HTTPException(403,'Workspace membership changed')
    permitted=await resolve_scope(db,principal,parsed)
    if device.revoked or device.credential_hash!=original or company.id not in {c.id for c in permitted}:
        raise HTTPException(403,'Company/device permission changed')
    if not isinstance(data,dict) or any(data.get(k)!=v for k,v in
        {'company':company.name,'identity':company.identity,'tool':parsed.mcp_tool,'commit':PIN,'backend':'mcp'}.items()):
        raise HTTPException(502,'MCP scope/version mismatch')
    try: view=display(data.get('result'),parsed.mcp_tool)
    except TallyError:
        return {'response':'Tally report format/reply verify nahi hui. Is result ko financial report na maanein.', 'capability':'unverified_result'}
    from datetime import datetime, timezone
    view.update(company=company.name,arguments=arguments,read_at=datetime.now(timezone.utc).isoformat())
    return {'response':f'{view["title"]} — {company.name}. Tally se live read.',
            'mcp_report':view, 'capability':'read_result'}

async def prepare_write(db,principal,parsed,action=None):
    """Persist typed requests without pretending unverified builders are executable."""
    import hashlib,json,secrets
    from datetime import timedelta
    from app.models.tally import TallyAction
    from app.services.tally_business import admin
    from app.services.tally_sync import now,action_result
    from app.services.tally_mcp import CONTRACTS
    admin(principal)
    if os.getenv('PHILIXA_MCP_READ_ENABLED')!='1':
        return {'response':'Tally MCP rollout abhi enabled nahi hai. Existing purchase/stock available hain.','capability':'disabled'}
    if not parsed.mcp_tool:
        return {'response':'Naye operations ke drafts available hain; live posting acceptance abhi pending hai.',
            'mcp_write_catalog':[{'tool':k,'label':k.replace('_',' ').title(),'schema':c['inputSchema']}
                for k,c in CONTRACTS.items() if c['category']=='write'], 'capability':'draft_selection'}
    contract=CONTRACTS.get(parsed.mcp_tool)
    if not contract or contract['category']!='write' or not contract['builderAvailable']:
        return {'response':'Ye operation pinned adapter mein available nahi hai.','capability':'blocked'}
    fields=parsed.model_dump(mode='json',exclude={'intent'})
    if not parsed.mcp_arguments or set(contract['inputSchema'].get('required',[]))-set(parsed.mcp_arguments):
        return {'response':'Operation ki details dein. Ye draft banega; Tally mein abhi post nahi hoga.',
                'mcp_write_form':{'tool':parsed.mcp_tool,'label':parsed.mcp_tool.replace('_',' ').title(),
                    'schema':contract['inputSchema'],'fields':fields}}
    from app.services.tally_mcp_write_validation import validate_write
    try:validate_write(parsed.mcp_tool,parsed.mcp_arguments)
    except TallyError as exc:return {'response':str(exc),'capability':'blocked'}
    companies=await resolve_scope(db,principal,parsed)
    # Writes always require explicit company selection, including a sole approved company.
    if not parsed.company_id or len(companies)!=1:
        return {'response':'Is draft ke liye company explicitly select karein.', 'connect_tally':not companies,
                'tally_choices':[{'name':c.name,'command':{'intent':'mcp_write','fields':{**fields,'company_id':c.id}}} for c in companies]}
    company=companies[0]
    device=await db.get(TallyDevice,company.device_id,populate_existing=True) if company.device_id else None
    if not device or device.revoked or device.organization_id!=principal.organization_id:
        return {'response':'Paired updated Tally Connector required.','capability':'update_required'}
    if parsed.draft_id and action is None:action=await db.get(TallyAction,parsed.draft_id,populate_existing=True)
    if parsed.draft_id and action is None:raise HTTPException(410,'Operation draft unavailable.')
    if action is not None:
        if (action.organization_id,action.user_id,action.session_id)!=(principal.organization_id,principal.user_id,principal.session_id):raise HTTPException(410,'Operation draft unavailable.')
        if action.backend!='mcp' or action.status!='draft' or action.company_id!=company.id or action.expires_at<=now():raise HTTPException(409,'Draft unavailable/expired; create a fresh request.')
        if action.payload.get('tool')!=parsed.mcp_tool or action.payload.get('arguments')!=parsed.mcp_arguments:raise HTTPException(409,'Draft details changed. Create a fresh request.')
    else:
        action=TallyAction(token=secrets.token_hex(16),organization_id=principal.organization_id,user_id=principal.user_id,
            session_id=principal.session_id,company_id=company.id,device_version=device.credential_hash,
            created_at=now(),expires_at=now()+timedelta(days=30),connection_version=0,backend='mcp',schema_version=1,
            payload={'operation':'mcp_write','tool':parsed.mcp_tool,'arguments':parsed.mcp_arguments,'company':company.name,'identity':company.identity,'commit':PIN},
            xml_payload='',status='draft',attempts=0)
        db.add(action);await db.commit()
    try:
        result=await request_job(device,'mcp_compile',company=company.name,identity=company.identity,
            tool=parsed.mcp_tool,arguments=parsed.mcp_arguments,action_id=action.token)
        await db.refresh(action,with_for_update=True);await db.refresh(device);await db.refresh(company)
        current=await resolve_scope(db,principal,parsed)
        if action.status!='draft':return action_result(action)
        if device.revoked or device.credential_hash!=action.device_version or company.id not in {c.id for c in current}:raise HTTPException(403,'Draft company/device permission changed.')
        from app.models.organization_membership import OrganizationMembership
        from app.models.organization import Organization
        from app.models.user import User
        membership=await db.get(OrganizationMembership,(principal.user_id,principal.organization_id),populate_existing=True)
        actor=await db.get(User,principal.user_id,populate_existing=True)
        organization=await db.get(Organization,principal.organization_id,populate_existing=True)
        if not membership or membership.status!='active' or membership.role not in ('owner','admin') or not actor or not actor.is_active or not organization or not organization.is_active:
            raise HTTPException(403,'Draft workspace authorization changed.')
        scope={'backend':'mcp','commit':PIN,'tool':parsed.mcp_tool,'company':company.name,'identity':company.identity,'posting_enabled':False}
        if not isinstance(result,dict) or any(result.get(k)!=v for k,v in scope.items()):raise TallyError('Compiler scope mismatch.')
        xml=result.get('xml')
        if not isinstance(xml,str) or len(xml)>1_500_000 or hashlib.sha256(xml.encode()).hexdigest()!=result.get('xml_sha256'):raise TallyError('Compiler fingerprint mismatch.')
        action.xml_payload=xml
        action.preconditions={'commit':PIN,'compiler_digest':result['xml_sha256'],'company_identity':company.identity,
            'operation_acceptance':'pending','durable_dispatch':'pending'}
        action.result={'response':'Operation draft saved; XML builder checked. Posting/verification acceptance pending — Tally mein kuch post nahi hua.'}
    except TallyError:
        action.result={'response':'Operation draft saved. Connector live hone par draft review karein; Tally mein kuch post nahi hua.'}
    await db.commit()
    result=action_result(action)
    result['preview']={'token':action.token,'title':parsed.mcp_tool.replace('_',' ').title(), 'can_confirm':False,
        'send':False,'blockers':['Is operation ka durable dispatch aur actual Tally acceptance abhi complete nahi hai.'],
        'lines':['Company: '+company.name,*[key+': '+json.dumps(value,ensure_ascii=False) for key,value in parsed.mcp_arguments.items()]]}
    return result

async def review_write(db,principal,action):
    from app.services.business_command_service import ParsedCommand
    if action.backend!='mcp':raise HTTPException(409,'Not an MCP draft.')
    parsed=ParsedCommand(intent='mcp_write',company_id=action.company_id,draft_id=action.token,
        mcp_tool=action.payload.get('tool'),mcp_arguments=action.payload.get('arguments',{}))
    return await prepare_write(db,principal,parsed,action)
