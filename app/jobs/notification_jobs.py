import logging
from typing import Dict, Any
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.models.client import Client
from app.models.follow_up_task import FollowUpTask
from app.models.meeting import Meeting
from app.models.notification import NotificationPreference, NotificationDelivery, DeliveryStatus
from app.services.notification_service import NotificationService
from app.core.dependencies import get_notification_adapter

logger = logging.getLogger(__name__)

async def send_client_followups(ctx: Dict[str, Any]) -> None:
    """
    Cron job to send follow-up notifications to clients.
    """
    logger.info("Starting send_client_followups job")
    
    db_session_factory = ctx.get("db_session_factory")
    if not db_session_factory:
        logger.error("db_session_factory not found in context")
        return

    adapter = get_notification_adapter()

    async with db_session_factory() as db:
        notification_service = NotificationService(db, adapter)
        
        # In a real scenario, you'd query clients/tasks that need follow-ups today
        # For demonstration, we'll find pending FollowUpTasks with a due date <= today
        # and join with their Client/NotificationPreference to send messages.
        
        # Example logic:
        # 1. Fetch pending tasks due soon
        now = datetime.now(timezone.utc)
        stmt = (
            select(FollowUpTask, Client, NotificationPreference)
            .join(Client, Client.id == FollowUpTask.client_id)
            .join(
                NotificationPreference, 
                and_(
                    NotificationPreference.organization_id == Client.organization_id,
                    NotificationPreference.user_id == Client.user_id
                    # Assuming preference represents the client somehow, or 
                    # we could map preference_id in client model.
                    # For demo purposes, let's assume we map via user_id or similar.
                ),
                isouter=True
            )
            .where(
                and_(
                    FollowUpTask.status == "pending",
                    FollowUpTask.due_date <= now + timedelta(days=1)
                )
            )
        )
        
        result = await db.execute(stmt)
        rows = result.all()
        
        for task, client, preference in rows:
            if not preference:
                continue
                
            idempotency_key = f"followup_task_{task.id}_{now.date().isoformat()}"
            message = f"Hello {client.name}, a friendly reminder regarding your pending task: {task.description}"
            
            await notification_service.dispatch_notification(
                preference_id=preference.id,
                message_content=message,
                idempotency_key=idempotency_key,
                organization_id=task.organization_id,
                user_id=task.user_id
            )
            
    logger.info("Finished send_client_followups job")

async def send_pre_interaction_briefs(ctx: Dict[str, Any]) -> None:
    """
    Cron job to send pre-interaction briefs to the RM (Relationship Manager)
    for meetings due today.
    """
    logger.info("Starting send_pre_interaction_briefs job")
    
    db_session_factory = ctx.get("db_session_factory")
    if not db_session_factory:
        logger.error("db_session_factory not found in context")
        return

    adapter = get_notification_adapter()

    async with db_session_factory() as db:
        notification_service = NotificationService(db, adapter)
        
        # Example logic: fetch meetings happening today
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        # Fetch all meetings today along with the client and their associated notification preference
        stmt_meetings = (
            select(Meeting, Client, NotificationPreference)
            .join(Client, Client.id == Meeting.client_id)
            .join(
                NotificationPreference,
                and_(
                    NotificationPreference.organization_id == Client.organization_id,
                    NotificationPreference.user_id == Client.user_id
                ),
                isouter=True
            )
            .where(Meeting.meeting_date <= now.date())
        )
        result_meetings = await db.execute(stmt_meetings)
        meetings_rows = result_meetings.all()
        
        for meeting, client, preference in meetings_rows:
            if not preference:
                continue
                
            idempotency_key = f"pre_meeting_brief_{meeting.id}"
            message = f"RM Brief: You have a meeting with {client.name} today. Please review their profile and prepare."
            
            await notification_service.dispatch_notification(
                preference_id=preference.id,
                message_content=message,
                idempotency_key=idempotency_key,
                organization_id=client.organization_id,
                user_id=client.user_id
            )
            
    logger.info("Finished send_pre_interaction_briefs job")

async def retry_failed_notifications(ctx: Dict[str, Any]) -> None:
    """
    Cron job to retry failed or stuck notifications.
    """
    logger.info("Starting retry_failed_notifications job")
    
    db_session_factory = ctx.get("db_session_factory")
    if not db_session_factory:
        logger.error("db_session_factory not found in context")
        return

    adapter = get_notification_adapter()

    async with db_session_factory() as db:
        notification_service = NotificationService(db, adapter)
        now = datetime.now(timezone.utc)
        stuck_threshold = now - timedelta(minutes=15)

        stmt = select(NotificationDelivery).where(
            or_(
                NotificationDelivery.status == DeliveryStatus.FAILED,
                and_(
                    NotificationDelivery.status == DeliveryStatus.PENDING,
                    NotificationDelivery.updated_at <= stuck_threshold
                )
            )
        )
        
        result = await db.execute(stmt)
        deliveries = result.scalars().all()
        
        for delivery in deliveries:
            idempotency_key = delivery.metadata_payload.get("idempotency_key") if delivery.metadata_payload else None
            if not idempotency_key:
                logger.warning(f"Delivery {delivery.id} has no idempotency_key, skipping retry.")
                continue
                
            logger.info(f"Retrying delivery {delivery.id} with status {delivery.status}")
            
            await notification_service.dispatch_notification(
                preference_id=delivery.preference_id,
                message_content=delivery.message_content,
                idempotency_key=idempotency_key,
                organization_id=delivery.organization_id,
                user_id=delivery.user_id
            )
            
    logger.info("Finished retry_failed_notifications job")
