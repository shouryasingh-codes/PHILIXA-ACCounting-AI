"""Append-only action authorization evidence, committed before external posting."""
import hashlib
import json
from types import SimpleNamespace
from sqlalchemy import select
from fastapi import HTTPException
from app.services.tally_connector import TallyError


async def record_authorization(db,action,principal):
    from app.models.purchase_draft import PurchaseDraft
    from app.models.purchase_automation import PurchaseAutomationDecision, PurchaseAutomationReservation
    from app.services.bill_evaluation_service import record
    if (action.organization_id,action.user_id,action.session_id)!=(principal.organization_id,principal.user_id,principal.session_id):
        raise HTTPException(410,'Action authorization scope changed.')
    data={'action_id':action.token,'authorization_type':'human_approval','actor_id':principal.user_id,
          'session_id':principal.session_id,'company_id':action.company_id,
          'target_identity':action.target_identity or {'company':action.payload.get('company')},
          'operation':action.payload.get('operation') or action.payload.get('voucher_type'),
          'action_guid':action.payload.get('guid'),
          'approved_payload_sha256':hashlib.sha256(json.dumps(action.payload,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()}
    if not data['action_guid']:raise TallyError('Action-specific posting identity missing.')
    auto=(action.preconditions or {}).get('automation')
    if auto:
        reservation=await db.get(PurchaseAutomationReservation,action.token)
        decision=await db.scalar(select(PurchaseAutomationDecision).where(
            PurchaseAutomationDecision.action_id==action.token,
            PurchaseAutomationDecision.company_id==action.company_id,
            PurchaseAutomationDecision.policy_revision==auto['policy_revision'],
            PurchaseAutomationDecision.decision=='auto_post'))
        if not reservation or not decision or reservation.policy_revision!=auto['policy_revision'] or auto['actor_id']!=principal.user_id:
            raise TallyError('Durable policy authorization evidence missing.')
        data.update(authorization_type='policy',policy_revision=auto['policy_revision'],decision_id=decision.id,
                    reservation_action_id=reservation.action_id,source_sha256=auto.get('source_sha256'))
    row=await db.scalar(select(PurchaseDraft).where(PurchaseDraft.action_id==action.token))
    record(db,SimpleNamespace(organization_id=action.organization_id,user_id=action.user_id),'posting_authorized',data,
           draft_id=row.id if row else None,document_id=row.document_id if row else None)
