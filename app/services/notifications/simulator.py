import logging
import uuid
import asyncio
from typing import Dict, Any

from app.services.notifications.base import NotificationAdapter
from app.models.notification import DeliveryStatus

logger = logging.getLogger(__name__)

class SimulatedNotificationAdapter(NotificationAdapter):
    """
    A simulated notification adapter for development and testing.
    It pretends to send messages without connecting to an actual provider.
    """
    def __init__(self):
        self._sent_messages: Dict[str, str] = {}

    async def send_message(self, to_destination: str, message_content: str) -> Dict[str, Any]:
        logger.info(f"[SimulatedNotification] Sending message to {to_destination}: {message_content}")
        
        # Simulate network delay
        await asyncio.sleep(0.5)
        
        provider_message_id = f"sim_{uuid.uuid4().hex}"
        self._sent_messages[provider_message_id] = DeliveryStatus.SENT
        
        logger.info(f"[SimulatedNotification] Message sent successfully. ID: {provider_message_id}")
        
        return {
            "provider_message_id": provider_message_id,
            "status": DeliveryStatus.SENT,
            "metadata_payload": {
                "simulated": True,
                "to": to_destination
            }
        }

    async def get_message_status(self, provider_message_id: str) -> str:
        # Simulate retrieving the status
        status = self._sent_messages.get(provider_message_id, DeliveryStatus.FAILED)
        
        # For simulation purposes, automatically transition SENT to DELIVERED
        if status == DeliveryStatus.SENT:
            self._sent_messages[provider_message_id] = DeliveryStatus.DELIVERED
            status = DeliveryStatus.DELIVERED
            
        return status
