import logging
import uuid
import httpx
from typing import Dict, Any

from app.core.config import get_settings
from app.services.notifications.base import NotificationAdapter
from app.models.notification import DeliveryStatus

logger = logging.getLogger(__name__)

class WhatsAppAdapter(NotificationAdapter):
    """
    Adapter for sending messages via Meta's WhatsApp Cloud API.
    """
    def __init__(self):
        self.settings = get_settings()
        self.base_url = "https://graph.facebook.com/v25.0"
        self.phone_number_id = self.settings.whatsapp_phone_number_id
        self.access_token = self.settings.whatsapp_access_token

    async def send_message(self, to_destination: str, message_content: str) -> Dict[str, Any]:
        if not self.phone_number_id or not self.access_token:
            logger.error("WhatsApp credentials missing from configuration.")
            return {
                "provider_message_id": f"err_{uuid.uuid4().hex}",
                "status": DeliveryStatus.FAILED,
                "error_message": "Missing credentials"
            }

        url = f"{self.base_url}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        # Meta expects the number without the leading +
        clean_destination = to_destination.replace("+", "").replace("-", "").replace(" ", "")

        payload = {
            "messaging_product": "whatsapp",
            "to": clean_destination,
            "type": "text",
            "text": {
                "body": message_content
            }
        }
        
        logger.info(f"Attempting to send WhatsApp message to {clean_destination}. Message length: {len(message_content)}")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                
            response_data = response.json()
            
            if response.status_code in (200, 201):
                # Meta returns a list of messages. We grab the ID of the first one.
                messages = response_data.get("messages", [])
                message_id = messages[0].get("id") if messages else f"sent_{uuid.uuid4().hex}"
                
                logger.info(f"WhatsApp message sent to {clean_destination}. ID: {message_id}")
                return {
                    "provider_message_id": message_id,
                    "status": DeliveryStatus.SENT,
                    "metadata_payload": response_data
                }
            else:
                error_obj = response_data.get("error", {})
                error_code = error_obj.get("code", "")
                error_title = error_obj.get("message", "Unknown error")
                error_details = error_obj.get("error_data", {}).get("details", "")
                
                # Format: "Message (Code) - Details"
                error_msg = error_title
                if error_code:
                    error_msg += f" (Code: {error_code})"
                if error_details:
                    error_msg += f" - {error_details}"
                    
                logger.error(f"Failed to send WhatsApp message. Code: {response.status_code}, Error: {error_msg}")
                return {
                    "provider_message_id": f"err_{uuid.uuid4().hex}",
                    "status": DeliveryStatus.FAILED,
                    "error_message": error_msg,
                    "metadata_payload": response_data
                }
                
        except Exception as e:
            logger.exception("Exception while sending WhatsApp message")
            return {
                "provider_message_id": f"err_{uuid.uuid4().hex}",
                "status": DeliveryStatus.FAILED,
                "error_message": str(e)
            }

    async def get_message_status(self, provider_message_id: str) -> str:
        return DeliveryStatus.UNKNOWN
