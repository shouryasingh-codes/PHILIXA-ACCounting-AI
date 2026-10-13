import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Any
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, cast
from sqlalchemy.dialects.postgresql import JSONB

from app.models.notification import NotificationPreference, NotificationDelivery, DeliveryStatus
from app.services.notifications.base import NotificationAdapter

logger = logging.getLogger(__name__)

def is_within_quiet_hours(current_time: datetime, start: str, end: str) -> bool:
    """
    Checks if current_time is within the quiet hours [start, end].
    start and end are strings in HH:MM format (e.g. "22:00", "08:00").
    Assumes current_time is localized to the user's timezone or compares in UTC (depending on context).
    For simplicity, we'll compare HH:MM string representations.
    """
    if not start or not end:
        return False
        
    current_hhmm = current_time.strftime("%H:%M")
    if start <= end:
        return start <= current_hhmm <= end
    else:
        # Crosses midnight
        return current_hhmm >= start or current_hhmm <= end

class NotificationService:
    def __init__(self, db: AsyncSession, adapter: NotificationAdapter):
        self.db = db
        self.adapter = adapter

    async def dispatch_notification(
        self,
        preference_id: str,
        message_content: str,
        idempotency_key: str,
        organization_id: str,
        user_id: str
    ) -> Optional[NotificationDelivery]:
        # 1. Fetch Preference
        stmt = select(NotificationPreference).where(
            and_(
                NotificationPreference.id == preference_id,
                NotificationPreference.organization_id == organization_id,
                NotificationPreference.user_id == user_id
            )
        )
        result = await self.db.execute(stmt)
        preference = result.scalar_one_or_none()

        if not preference:
            logger.error(f"Preference not found: {preference_id}")
            return None

        if not preference.is_opted_in or not preference.whatsapp_number:
            logger.info(f"User opted out or no number for preference {preference_id}")
            return None

        # 2. Check Quiet Hours
        now = datetime.now(timezone.utc)
        if preference.quiet_hours_start and preference.quiet_hours_end:
            if is_within_quiet_hours(now, preference.quiet_hours_start, preference.quiet_hours_end):
                logger.info(f"Suppressed notification due to quiet hours: {preference_id}")
                return None

        # 3. Idempotency Check
        # Checking if a delivery with this idempotency key already exists for this preference
        idempotency_stmt = select(NotificationDelivery).where(
            and_(
                NotificationDelivery.preference_id == preference_id,
                NotificationDelivery.metadata_payload.op("->>")("idempotency_key") == idempotency_key
            )
        )
        idemp_result = await self.db.execute(idempotency_stmt)
        existing_delivery = idemp_result.scalar_one_or_none()
        
        delivery = None
        if existing_delivery:
            if existing_delivery.status in (DeliveryStatus.SENT, DeliveryStatus.DELIVERED, DeliveryStatus.READ):
                logger.info(f"Notification already sent (Idempotency Hit): {idempotency_key}")
                return existing_delivery
            else:
                logger.info(f"Retrying failed/pending notification for idempotency key: {idempotency_key}")
                delivery = existing_delivery
                # Reset status and error message before retry
                delivery.status = DeliveryStatus.PENDING
                delivery.error_message = None

        if not delivery:
            # 4. Create Delivery Record (PENDING)
            delivery_id = str(uuid.uuid4())
            metadata = {"idempotency_key": idempotency_key}
            
            delivery = NotificationDelivery(
                id=delivery_id,
                preference_id=preference_id,
                organization_id=organization_id,
                user_id=user_id,
                channel="whatsapp",
                message_content=message_content,
                status=DeliveryStatus.PENDING,
                metadata_payload=metadata
            )
            self.db.add(delivery)
            
        await self.db.commit()
        await self.db.refresh(delivery)

        # 5. Dispatch via Adapter
        try:
            adapter_res = await self.adapter.send_message(
                to_destination=preference.whatsapp_number,
                message_content=message_content
            )
            
            delivery.provider_message_id = adapter_res.get("provider_message_id")
            delivery.status = DeliveryStatus.SENT
            
            # Merge provider metadata
            if adapter_res.get("metadata_payload"):
                current_meta = dict(delivery.metadata_payload or {})
                current_meta.update(adapter_res["metadata_payload"])
                delivery.metadata_payload = current_meta
                
        except Exception as e:
            logger.exception(f"Failed to send message for {delivery_id}")
            delivery.status = DeliveryStatus.FAILED
            delivery.error_message = str(e)
            
        await self.db.commit()
        await self.db.refresh(delivery)
        
        return delivery
