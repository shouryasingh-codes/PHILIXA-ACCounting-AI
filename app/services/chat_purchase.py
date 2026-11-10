"""Chat-to-GST working copy handoff. No tax guessing or write authorization."""
import hashlib
import json
from datetime import datetime,timezone
from sqlalchemy import select
from app.models.purchase_draft import PurchaseDraft
from app.services import purchase_draft_service as drafts


async def gst_working_copy(db,principal,company,parsed,item_name,godown,gst=True):
    content=drafts.DraftContent(party_name=parsed.party_name,entry_date=parsed.entry_date,
        godown=parsed.godown or godown,invoice_number=parsed.invoice_number,tax_treatment='regular_domestic_goods' if gst else None,
        lines=[drafts.DraftLine.model_validate(v) for v in parsed.purchase_lines] if parsed.purchase_lines else [drafts.DraftLine(item_name=item_name,quantity=parsed.quantity,unit=parsed.unit,rate=parsed.rate)])
    if parsed.purchase_mentions:
        from app.services.purchase_agent import apply_updates
        content=drafts.DraftContent.model_validate(apply_updates(content.model_dump(mode='json'),parsed.purchase_mentions))
    seed=hashlib.sha256(json.dumps({'session':principal.session_id,'company':company.id,
        'conversation':parsed.purchase_context,
        'content':content.model_dump(mode='json')},sort_keys=True).encode()).hexdigest()
    # Serialize repeated requests for this user's same command. Never reset edits.
    from sqlalchemy import text
    await db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':int(seed[:15],16)})
    row=await db.scalar(select(PurchaseDraft).where(PurchaseDraft.organization_id==principal.organization_id,
        PurchaseDraft.user_id==principal.user_id,PurchaseDraft.company_id==company.id,
        PurchaseDraft.action_id.is_(None),drafts.active_source_filter(),
        PurchaseDraft.extraction_metadata['chat_gst_seed'].as_string()==seed)
        .order_by(PurchaseDraft.created_at.desc()).limit(1))
    if row is None:
        import secrets
        stamp=datetime.now(timezone.utc)
        row=PurchaseDraft(id=secrets.token_hex(16),organization_id=principal.organization_id,
            user_id=principal.user_id,company_id=company.id,content=content.model_dump(mode='json'),
            extraction_metadata={'source':'chat','chat_gst_seed':seed,
                'agent_provenance':{m['path']:dict(value=m['value'],quote=m['quote'],status='explicit',source_type='user_message',
                    observed_at=stamp.isoformat(),draft_revision=0) for m in parsed.purchase_mentions or []},
                'warnings':['Chat working copy: original invoice reference/date, GST and totals require review.']},
            revision=0,created_at=stamp,updated_at=stamp)
        db.add(row);await db.flush();drafts.record_event(db,row,principal.user_id,'created')
    draft_id=row.id
    await db.commit()
    from app.services.purchase_conversation import state
    return await state(db,principal,draft_id,prefix=company.name+' · Purchase draft (abhi entry nahi hui)')
