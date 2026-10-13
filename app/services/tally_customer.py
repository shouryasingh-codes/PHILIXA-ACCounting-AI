"""Customer master preview and verified CRM linking, using the existing outbox."""
import secrets
import uuid
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from app.models.tally import TallyAction, TallyConnection, TallyCustomerLink
from app.models.client import Client
from app.repositories.client_repository import ClientRepository
from app.services.tally_connector import TallyError, name, value
from app.services.tally_customer_codec import GROUP, ledger_fingerprint, validate_payload, ledger_xml, verify_created, verify_fields

async def preview_customer(db, principal, parsed):
    from app.services.tally_business import admin, fields_for_selection
    from app.services.tally_stock import resolve_scope
    from app.services.tally_sync import now, saved_snapshot, refresh_company, bound_device, ACTIVE
    from app.services.tally_sync_protocol import deserialize_catalog
    admin(principal)
    if parsed.unsupported_reason:return {'response':parsed.unsupported_reason}
    if not parsed.client_name or not parsed.client_name.strip():return {'response':'Naye customer ka naam bataiye.'}
    cfg=await db.get(TallyConnection,principal.organization_id)
    if not cfg or not cfg.test_company:return {'response':'Tally customer ledger ke liye approved non-GST test company configure karein.','connect_tally':True}
    scope=await resolve_scope(db,principal,parsed)
    if not parsed.company_id and len(scope)>1:
        return {'response':'Customer kis Tally company mein add karna hai?','tally_choices':[
            {'name':c.name,'command':fields_for_selection(parsed,'company_id',c.id)} for c in scope]}
    if len(scope)!=1 or scope[0].name!=cfg.company:return {'response':'Customer ledger sirf approved configured test company mein supported hai.','connect_tally':True}
    company=scope[0];customer_name=parsed.client_name.strip()
    try:
        await bound_device(db,company)
        try:await refresh_company(db,company)
        except TallyError:pass  # A complete, identity-bound snapshot permits an offline preview.
        snapshot=await saved_snapshot(db,company)
        if not snapshot:return {'response':'Customer preview ke liye Tally masters sync karein. Abhi koi customer/ledger save nahi hua.','connect_tally':True}
        catalog=deserialize_catalog(snapshot.catalog)
        if not catalog['non_gst']:return {'response':'Is milestone mein non-GST test-company customer ledger supported hai.'}
        clients=[c for c in await ClientRepository().list(db,principal) if c.name.casefold()==customer_name.casefold()]
        if len(clients)>1:return {'response':'Philixa mein same-name customers hain. Pehle duplicate customer resolve karein.'}
        client=clients[0] if clients else None
        if client and ((parsed.email and parsed.email!=client.email) or (parsed.whatsapp_phone and parsed.whatsapp_phone!=client.whatsapp_phone)):
            return {'response':'Existing customer ki contact details alag hain. Pehle customer details update karein; naya duplicate nahi banega.'}
        rows=[r for r in catalog['ledgers'] if name(r).casefold()==customer_name.casefold()]
        if len(rows)>1:return {'response':'Tally mein same-name ledger ambiguous hai. Ledger manually review karein.'}
        ledger=rows[0] if rows else None
        if ledger is not None and (value(ledger,'PARENT')!=GROUP or not value(ledger,'GUID')):
            return {'response':'Tally mein is naam ka account customer group (Sundry Debtors) mein nahi hai ya identity unavailable hai. Uska group silently change nahi karenge; ledger review karein.'}
        payload={'operation':'customer_ledger_create','company':company.name,'name':name(ledger) if ledger is not None else customer_name,
            'parent':GROUP,'guid':str(uuid.uuid4()),'mode':'link' if ledger is not None else 'create',
            'target_guid':value(ledger,'GUID') if ledger is not None else '',
            'fingerprint':ledger_fingerprint(ledger) if ledger is not None else '',
            'email':client.email if client else parsed.email,'phone':client.whatsapp_phone if client else parsed.whatsapp_phone,
            'client_id':client.id if client else None,'client_version':client.updated_at.isoformat() if client else ''}
        validate_payload(payload,{'company':cfg.company,'test_company':cfg.test_company},company.name)
        if client:
            link=await db.scalar(select(TallyCustomerLink).where(TallyCustomerLink.company_id==company.id,TallyCustomerLink.client_id==client.id))
            if link:
                if ledger is not None and link.company_identity==company.identity and link.ledger_guid==value(ledger,'GUID'):
                    return {'response':f'{client.name} Philixa mein saved aur Tally customer ledger se linked hai.','customer_id':client.id}
                return {'response':'Existing Tally customer link changed/missing hai. Manual review required; duplicate ledger nahi banega.'}
        pending=list((await db.scalars(select(TallyAction).where(TallyAction.company_id==company.id,TallyAction.status.in_(('preview',*ACTIVE,'needs_review'))))).all())
        for a in pending:
            if a.payload.get('operation')!='customer_ledger_create' or a.payload.get('name','').casefold()!=payload['name'].casefold():continue
            if a.status=='preview' and a.expires_at<=now():continue
            if a.user_id==principal.user_id and a.session_id==principal.session_id:
                from app.services.tally_sync import action_result
                result=action_result(a)
                if a.status=='preview':result.update(preview=customer_preview(a),response='Existing customer preview check karein; duplicate request nahi banayi.')
                return result
            return {'response':'Is customer ki earlier request pending hai. Pehle uska status resolve karein; duplicate ledger nahi banega.'}
        device=await bound_device(db,company);stamp=now()
        action=TallyAction(token=secrets.token_hex(16),organization_id=principal.organization_id,user_id=principal.user_id,session_id=principal.session_id,
            company_id=company.id,device_version=device.credential_hash if device else None,created_at=stamp,expires_at=stamp+timedelta(minutes=15),
            connection_version=cfg.version,payload=payload,xml_payload=ledger_xml(payload) if ledger is None else '',status='preview',attempts=0,
            backend='python',schema_version=1,target_identity={'company':company.identity},approved_arguments=None)
        db.add(action);await db.commit()
        return {'response':'Customer preview check karein. Confirm ke baad Tally ledger verify hoga, phir Philixa customer link save hoga.',
                'preview':customer_preview(action)}
    except (TallyError,ValueError) as exc:return {'response':str(exc)}

def customer_preview(action):
    p=action.payload
    return {'token':action.token,'title':'Customer + Tally ledger','can_confirm':True,'blockers':[],'send':False,
        'lines':[f'Company: {p["company"]}',f'Customer: {p["name"]}',f'Tally group: {GROUP}',
                 'Existing Tally ledger link hoga; ledger ki details/balance change nahi honge.' if p['mode']=='link' else 'Naya Tally customer ledger; opening balance 0; bill-wise tracking off.',
                 f'Email: {p["email"] or "Not supplied"}',f'Phone: {p["phone"] or "Not supplied"}',
                 'Existing Philixa customer link hoga.' if p['client_id'] else 'Tally verification ke baad Philixa customer save hoga.',
                 'Tally offline ho toh confirmed request saved rahegi; success sirf verification ke baad.' ]}

async def validate_client_precondition(db,action):
    p=action.payload
    clients=list((await db.scalars(select(Client).where(Client.organization_id==action.organization_id))).all())
    exact=[c for c in clients if c.name.casefold()==p['name'].casefold()]
    if p['client_id'] is None:return not exact
    return len(exact)==1 and exact[0].id==p['client_id'] and exact[0].updated_at.isoformat()==p['client_version'] and exact[0].is_active

async def process_customer(db,action,company,cfg):
    from app.services.tally_sync import operation,config_data,now,ACTIVE,capture_snapshot,publish_snapshot
    if not await validate_client_precondition(db,action):
        action.result={'uncertain':action.status in ('submitting','verification_pending'),'response':'Philixa customer changed; review required. Duplicate customer/ledger nahi banaya.'}
        action.status='needs_review';await db.commit();return
    p=action.payload;params={'payload':p,'config':config_data(cfg),'action_id':action.token}
    if action.status=='queued':
        reply=await operation(db,company,'customer_ledger_validate',**params)
        if reply.get('status')=='ready':
            await db.refresh(action,with_for_update=True)
            if action.status!='queued':return
            action.status='submitting';await db.commit()
            reply=await operation(db,company,'customer_ledger_post',**params)
    else:reply=await operation(db,company,'customer_ledger_reconcile',**params)
    await db.refresh(action,with_for_update=True)
    if action.status not in ACTIVE:return
    if reply.get('status')=='verified':
        if not isinstance(reply.get('ledger_guid'),str) or not 0<len(reply['ledger_guid'])<=250 or reply.get('ledger_name')!=p['name'] or reply.get('ledger_parent')!=GROUP or (p['mode']=='link' and reply['ledger_guid']!=p['target_guid']):
            raise TallyError('Customer verification response mismatch.')
        snapshot=await capture_snapshot(db,company)
        from app.services.tally_sync_protocol import deserialize_catalog
        native=[r for r in deserialize_catalog(snapshot['catalog'])['ledgers'] if name(r).casefold()==p['name'].casefold()]
        created_valid=False
        if len(native)==1 and p['mode']=='create':
            created_valid=verify_created(native[0],p) or (reply.get('verification_source')=='import_receipt'
                and isinstance(reply.get('master_id'),str) and reply['master_id'].isdigit() and int(reply['master_id'])>0
                and value(native[0],'PHILIXAMASTERID')==reply['master_id'] and verify_fields(native[0],p))
        if len(native)!=1 or value(native[0],'GUID')!=reply['ledger_guid'] or value(native[0],'PARENT')!=GROUP or (
            p['mode']=='create' and not created_valid) or (
            p['mode']=='link' and ledger_fingerprint(native[0])!=p['fingerprint']):
            action.status='needs_review';action.result={'uncertain':True,'response':'Fresh Tally snapshot does not match approved customer ledger; link not saved.'};await db.commit();return
        from app.models.organization import Organization
        # Serialize CRM creation across different Tally endpoints in one workspace.
        await db.scalar(select(Organization.id).where(Organization.id==action.organization_id).with_for_update())
        await db.refresh(action,with_for_update=True)
        # Re-check local changes during network I/O before publishing the durable link.
        if action.status not in ACTIVE or not await validate_client_precondition(db,action):
            action.status='needs_review';action.result={'uncertain':True,'response':'Customer changed during Tally verification; review required.'};await db.commit();return
        link=await db.scalar(select(TallyCustomerLink).where(TallyCustomerLink.company_id==company.id,TallyCustomerLink.ledger_guid==reply['ledger_guid']))
        if link and (p['client_id'] is None or link.client_id!=p['client_id']):
            action.status='needs_review';action.result={'uncertain':False,'response':'Tally ledger already linked to another customer.'};await db.commit();return
        client=await db.get(Client,p['client_id']) if p['client_id'] else None
        if client is None:
            from types import SimpleNamespace
            client=await ClientRepository().create(db,SimpleNamespace(organization_id=action.organization_id,user_id=action.user_id),
                {'name':p['name'],'email':p['email'],'whatsapp_phone':p['phone']})
        if not link:db.add(TallyCustomerLink(id=secrets.token_hex(16),organization_id=action.organization_id,client_id=client.id,company_id=company.id,
            company_identity=company.identity,ledger_guid=reply['ledger_guid'],ledger_name=p['name'],ledger_parent=GROUP,action_id=action.token,verified_at=now()))
        await publish_snapshot(db,company,snapshot)
        action.status='verified';action.verification_result={**reply,'client_id':client.id}
        action.result={'response':f'{p["name"]}: Tally customer ledger verified; Philixa customer saved aur linked hai.','customer_id':client.id}
    elif reply.get('status') in ('failed','needs_review'):
        action.result={'uncertain':action.status in ('submitting','verification_pending'),'response':'Customer ledger: '+reply.get('reason','Review required.')[:300]}
        action.status=reply['status']
        if action.status=='failed':action.result['uncertain']=False
    else:action.status='verification_pending';action.result=None
    await db.commit()
