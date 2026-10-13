"""Server-side staging only; posting is performed by the existing durable worker."""
import secrets
import uuid
from datetime import timedelta
from decimal import Decimal
from sqlalchemy import select
from app.models.tally import TallyAction,TallyConnection
from app.services import tally_sync as sync
from app.services.tally_connector import TallyError,name,decimal
from app.services.tally_validation import match
from app.services.tally_sync_protocol import deserialize_catalog
from app.services.tally_multi_purchase import fingerprint_multi,validate_multi,multi_xml


def action_lines(payload):
    if payload.get('operation') in ('purchase_multi','purchase_gst'):return payload['items']
    return [payload] if 'item' in payload else []


async def preview_multi_purchase(db,principal,draft,content):
    from app.services.purchase_draft_service import company_for,attach_preview
    expected_revision=draft.revision
    company=await company_for(db,principal,draft.company_id)
    cfg=await db.get(TallyConnection,principal.organization_id)
    if not cfg or not cfg.test_company or cfg.company!=company.name:
        return {'response':'Multi-item purchase ke liye configured non-GST test company select karein.'}
    try:
        try:await sync.refresh_company(db,company)
        except TallyError:pass
        snapshot=await sync.saved_snapshot(db,company)
        if not snapshot:raise TallyError('Complete saved masters unavailable; sync company first.')
        catalog=deserialize_catalog(snapshot.catalog)
        if content.godown and content.godown!=cfg.godown:raise TallyError('Configured godown use karein.')
        parties=match(catalog['ledgers'],content.party_name)
        if len(parties)!=1:raise TallyError('Supplier missing/ambiguous; exact Tally supplier select karein.')
        lines=[]
        for index,line in enumerate(content.lines):
            items=match(catalog['items'],line.item_name)
            if len(items)!=1:raise TallyError(f'Line {index+1}: item missing/ambiguous; exact item name use karein.')
            item=name(items[0]);qty=decimal(line.quantity);rate=decimal(line.rate)
            stock=next((r for r in snapshot.items if r['item']==item),None)
            if stock is None:raise TallyError(f'Line {index+1}: saved stock master missing.')
            lines.append({'item':item,'quantity':str(qty),'unit':line.unit,'rate':str(rate),
                'total':str((qty*rate).quantize(Decimal('.01'))),'stock_before':stock['quantity'] or ''})
        prior=await db.scalars(select(TallyAction).where(TallyAction.company_id==company.id,
            TallyAction.status.in_(('submitting','verification_pending','needs_review'))))
        affected={l['item'] for l in lines}
        if any(sync.uncertain(a) and (a.backend=='mcp' or any(l.get('item') in affected for l in action_lines(a.payload))) for a in prior):
            raise TallyError('Earlier item entry verification pending; resolve it before another purchase.')
        p={'operation':'purchase_multi','company':company.name,'godown':cfg.godown,'party':name(parties[0]),
            'voucher_type':'Purchase','ledger':cfg.purchase_ledger,'date':content.entry_date.isoformat(),
            'guid':str(uuid.uuid4()),'items':lines,'total':str(sum((decimal(l['total']) for l in lines),Decimal('0.00'))),
            'master_fingerprint':''}
        p['master_fingerprint']=fingerprint_multi(catalog,p);validate_multi(catalog,p,sync.config_data(cfg))
        # Snapshot refresh commits internally; reacquire the draft lock and reject
        # a concurrent edit instead of previewing the stale captured content.
        await db.refresh(draft,with_for_update=True)
        if draft.revision!=expected_revision:raise TallyError('Draft changed during master refresh. Reopen it and retry preview.')
        device=await sync.bound_device(db,company);stamp=sync.now()
        action=TallyAction(token=secrets.token_hex(16),organization_id=principal.organization_id,
            user_id=principal.user_id,session_id=principal.session_id,company_id=company.id,
            device_version=device.credential_hash if device else None,created_at=stamp,expires_at=stamp+timedelta(minutes=15),
            connection_version=cfg.version,payload=p,xml_payload=multi_xml(p),status='preview',attempts=0,
            schema_version=2,target_identity={'company':company.identity})
        db.add(action);await attach_preview(db,principal,action,draft);await db.commit()
        return {'draft_id':draft.id,'response':'Multi-item preview check karein. Confirm se ek purchase voucher save hoga.',
            'preview':{'token':action.token,'title':'Purchase — multi-item test company','can_confirm':True,'send':False,'blockers':[],
            'lines':[f'Company: {company.name}',f'Supplier: {p["party"]}',f'Date: {p["date"]}',f'Godown: {p["godown"]}']+
                [f'{i+1}. {l["item"]}: {l["quantity"]} {l["unit"]} × ₹{l["rate"]} = ₹{l["total"]}' for i,l in enumerate(lines)]+
                [f'Total: ₹{p["total"]} (non-GST)',f'{len(lines)} item lines · one purchase voucher']}}
    except (TallyError,ValueError) as exc:return {'response':str(exc)}
