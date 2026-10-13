import logging
import uuid
import aiosmtplib
from email.message import EmailMessage
from email.utils import formataddr
from typing import Dict, Any

from app.services.notifications.base import NotificationAdapter
from app.models.notification import DeliveryStatus

logger = logging.getLogger(__name__)

class EmailAdapter(NotificationAdapter):
    """
    An email adapter using aiosmtplib.
    """
    def __init__(self, hostname: str, port: int, username: str, password: str, use_tls: bool, from_address: str):
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.from_address = from_address

    async def send_message(self, to_destination: str, message_content: str, subject: str | None = None) -> Dict[str, Any]:
        logger.info(f"[EmailAdapter] Sending email to {to_destination}")
        
        message = EmailMessage()
        message["From"] = formataddr(("Philixa AI", self.from_address))
        message["To"] = to_destination
        message["Subject"] = subject or "Notification from Philixa AI"
        message.set_content(message_content)

        provider_message_id = f"email_{uuid.uuid4().hex}"

        try:
            await aiosmtplib.send(
                message,
                hostname=self.hostname,
                port=self.port,
                username=self.username,
                password=self.password,
                use_tls=self.use_tls,
                start_tls=not self.use_tls
            )
            logger.info(f"[EmailAdapter] Email sent successfully. ID: {provider_message_id}")
            return {
                "provider_message_id": provider_message_id,
                "status": DeliveryStatus.SENT,
                "metadata_payload": {
                    "provider": "email",
                    "to": to_destination
                }
            }
        except Exception as e:
            logger.error(f"[EmailAdapter] Failed to send email to {to_destination}: {e}")
            return {
                "provider_message_id": provider_message_id,
                "status": DeliveryStatus.FAILED,
                "error_message": str(e),
                "metadata_payload": {
                    "provider": "email",
                    "to": to_destination
                }
            }

    async def send_notification(self, to_destination: str, message_content: str, subject: str | None = None) -> Dict[str, Any]:
        return await self.send_message(to_destination, message_content, subject=subject)

    async def get_message_status(self, provider_message_id: str) -> str:
        # Email status is inherently difficult to track once handed off to SMTP,
        # so we just return SENT unless it failed initially.
        return DeliveryStatus.SENT
