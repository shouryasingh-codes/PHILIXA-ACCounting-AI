import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.session import get_db
from app.models.notification import NotificationDelivery, DeliveryStatus
from app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

@router.get("/whatsapp")
async def verify_whatsapp_webhook(request: Request):
    """
    Handles WhatsApp Webhook Verification (Meta's GET request).
    """
    settings = get_settings()
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == settings.whatsapp_verify_token:
            logger.info("WhatsApp webhook verified successfully!")
            return Response(content=challenge, status_code=200)
        else:
            raise HTTPException(status_code=403, detail="Verification token mismatch")
    
    raise HTTPException(status_code=400, detail="Missing hub parameters")

@router.post("/whatsapp")
async def whatsapp_webhook(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Webhook endpoint to receive WhatsApp delivery receipts.
    Meta's payload format is nested under entry -> changes -> value -> statuses.
    """
    try:
        if "entry" in payload:
            for entry in payload["entry"]:
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    # Handle statuses
                    for status_obj in value.get("statuses", []):
                        provider_message_id = status_obj.get("id")
                        new_status = status_obj.get("status")
                        
                        if not provider_message_id or not new_status:
                            continue
                            
                        status_map = {
                            "sent": DeliveryStatus.SENT,
                            "delivered": DeliveryStatus.DELIVERED,
                            "read": DeliveryStatus.DELIVERED,
                            "failed": DeliveryStatus.FAILED
                        }
                        
                        status_enum = status_map.get(new_status, DeliveryStatus.UNKNOWN)
                        
                        # Extract detailed error message if failed
                        error_msg = None
                        if new_status == "failed":
                            errors = status_obj.get("errors", [])
                            if errors:
                                err = errors[0]
                                code = err.get("code", "")
                                title = err.get("title", "Unknown WhatsApp error")
                                details = err.get("error_data", {}).get("details", "")
                                
                                error_msg = title
                                if code:
                                    error_msg += f" (Code: {code})"
                                if details:
                                    error_msg += f" - {details}"
                        
                        # 1. Check NotificationDelivery
                        stmt = select(NotificationDelivery).where(
                            NotificationDelivery.provider_message_id == provider_message_id
                        )
                        result = await db.execute(stmt)
                        delivery = result.scalar_one_or_none()
                        
                        if delivery:
                            delivery.status = status_enum
                            if error_msg:
                                delivery.error_message = error_msg
                            logger.info(f"Updated NotificationDelivery {delivery.id} to {status_enum}")
                            
                        # 2. Check CommunicationLog using Repository
                        from app.repositories.communication_repository import CommunicationRepository
                        comm_log = await CommunicationRepository().update_status_by_provider_id(
                            db=db,
                            provider_message_id=provider_message_id,
                            status=new_status,
                            error_message=error_msg
                        )
                        if comm_log:
                            logger.info(f"Updated CommunicationLog {comm_log.id} to {status_enum}")
            
            await db.commit()
            return {"status": "success"}
            
        else:
            # Fallback for old simulator payloads
            provider_message_id = payload.get("provider_message_id")
            if provider_message_id:
                stmt = select(NotificationDelivery).where(
                    NotificationDelivery.provider_message_id == provider_message_id
                )
                result = await db.execute(stmt)
                delivery = result.scalar_one_or_none()
                if delivery:
                    try:
                        delivery.status = DeliveryStatus(payload.get("status", "unknown").lower())
                    except:
                        pass
                    await db.commit()
            return {"status": "success"}
                
    except Exception as e:
        logger.exception("Error processing WhatsApp webhook")
        # Return 200 so Meta doesn't block the webhook
        return {"status": "success"}

    return {"status": "success"}
