from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import get_ai_provider
from app.core.auth import Principal
from app.core.config import get_settings
from app.models.client import Client
from app.models.notification import DeliveryStatus
from app.services.notifications.email_adapter import EmailAdapter
from app.services.notifications.whatsapp_adapter import WhatsAppAdapter

logger = logging.getLogger(__name__)

ReminderChannel = Literal["email", "whatsapp", "both"]


class ReminderService:
    """Draft and send client reminders without coupling email and WhatsApp delivery."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.economy_provider = get_ai_provider(self.settings.ai_economy_provider, self.settings)
        self.economy_model = self.settings.ai_economy_model
        self.email_adapter = EmailAdapter(
            hostname=self.settings.smtp_hostname,
            port=self.settings.smtp_port,
            username=self.settings.smtp_username,
            password=self.settings.smtp_password,
            use_tls=self.settings.smtp_use_tls,
            from_address=self.settings.smtp_from_address,
        )
        self.whatsapp_adapter = WhatsAppAdapter()

    @staticmethod
    def _resolve_channel(instruction: str | None, requested_channel: str | None = None) -> ReminderChannel:
        text = instruction.casefold() if instruction else ""
        mentions_whatsapp = "whatsapp" in text or "what's app" in text
        mentions_email = "email" in text or "e-mail" in text
        if mentions_whatsapp and not mentions_email:
            return "whatsapp"
        if mentions_email and not mentions_whatsapp:
            return "email"
        if mentions_whatsapp and mentions_email:
            return "both"

        requested = (requested_channel or "").strip().casefold()
        if requested in {"email", "whatsapp", "both"}:
            return requested  # type: ignore[return-value]
        return "both"

    async def _draft_messages(self, client_name: str, instruction: str) -> dict[str, str]:
        prompt = f"""
Draft a concise, professional reminder for a client named {client_name}.
The user's instruction is: {instruction!r}

Return ONLY JSON in this exact shape:
{{
  "email_subject": "short subject",
  "email_body": "polite complete email, ending with Best regards, [Your Name]",
  "whatsapp_body": "short WhatsApp message, no markdown, no subject, under 700 characters"
}}
"""
        fallback = {
            "email_subject": "Important Reminder",
            "email_body": (
                f"Dear {client_name},\n\nThis is a quick reminder regarding: {instruction}\n\n"
                "Please let us know if you need any assistance.\n\nBest regards,\nYour Agent"
            ),
            "whatsapp_body": (
                f"Hello {client_name}, this is a quick reminder regarding: {instruction}. "
                "Please let us know if you need any assistance."
            ),
        }
        try:
            raw = await asyncio.to_thread(
                self.economy_provider.generate_json,
                self.economy_model,
                prompt,
                {"email_subject": "string", "email_body": "string", "whatsapp_body": "string"},
            )
            drafted = json.loads(raw)
            if not all(isinstance(drafted.get(key), str) and drafted[key].strip() for key in fallback):
                raise ValueError("AI reminder draft was incomplete.")
            return {key: drafted[key].strip() for key in fallback}
        except Exception:
            logger.exception("Reminder drafting failed; using the safe fallback draft.")
            return fallback

    @staticmethod
    def _delivery_succeeded(result: dict[str, Any]) -> bool:
        return result.get("status") in {DeliveryStatus.SENT, DeliveryStatus.DELIVERED}

    async def draft_client_reminder(
        self,
        db: AsyncSession,
        organization_id: str,
        user_id: str,
        role: str,
        client_name: str | None,
        instruction: str,
        channel: str | None = None,
        client_id: int | None = None,
    ) -> dict[str, Any]:
        """Draft an email, WhatsApp message, or both without sending them."""
        if not client_name:
            return {"status": "error", "message": "I didn't catch the client's name. Who should I send the reminder to?"}

        client_stmt = select(Client).where(
            Client.id == client_id if client_id is not None else Client.name.ilike(f"%{client_name}%"),
            Client.organization_id == organization_id,
        )
        if role.lower() == "member":
            client_stmt = client_stmt.where(Client.user_id == user_id)

        clients = (await db.execute(client_stmt)).scalars().all()
        if not clients:
            return {"status": "error", "message": f"I couldn't find a client named {client_name} in your portfolio."}
        if len(clients) > 1:
            return {"status": "error", "message": f"I found multiple clients named {client_name}. Please be more specific."}

        client = clients[0]
        delivery_channel = self._resolve_channel(instruction, channel)
        wants_email = delivery_channel in {"email", "both"}
        wants_whatsapp = delivery_channel in {"whatsapp", "both"}

        if wants_email and not client.email and wants_whatsapp and not client.whatsapp_phone:
             return {"status": "error", "message": f"Neither email nor WhatsApp is saved for {client.name}."}
        elif wants_email and not client.email and delivery_channel == "email":
             return {"status": "error", "message": f"No email address saved for {client.name}."}
        elif wants_whatsapp and not client.whatsapp_phone and delivery_channel == "whatsapp":
             return {"status": "error", "message": f"No WhatsApp number saved for {client.name}."}

        draft = await self._draft_messages(client.name, instruction)
        
        # Prepare the response message to read aloud
        preview_texts = []
        if wants_whatsapp and client.whatsapp_phone:
            preview_texts.append(f"WhatsApp: '{draft['whatsapp_body']}'")
        if wants_email and client.email:
            preview_texts.append(f"Email subject '{draft['email_subject']}'")
            
        joiner = " and "
        msg = f"I drafted this for {client.name}. {joiner.join(preview_texts)}. Should I send it?"

        return {
            "status": "success",
            "message": msg,
            "draft_data": {
                "client_id": client.id,
                "client_name": client.name,
                "delivery_channel": delivery_channel,
                "wants_email": wants_email,
                "wants_whatsapp": wants_whatsapp,
                "email_destination": client.email,
                "whatsapp_destination": client.whatsapp_phone,
                "draft": draft,
            }
        }

    async def dispatch_client_reminder(
        self, 
        draft_data: dict[str, Any],
        db: AsyncSession | None = None,
        user_id: str | None = None,
        organization_id: str | None = None
    ) -> dict[str, Any]:
        """Actually dispatch the approved draft and log communications."""
        wants_email = draft_data.get("wants_email", False)
        wants_whatsapp = draft_data.get("wants_whatsapp", False)
        draft = draft_data.get("draft", {})
        client_name = draft_data.get("client_name", "the client")
        client_id = draft_data.get("client_id")
        email_dest = draft_data.get("email_destination")
        wa_dest = draft_data.get("whatsapp_destination")

        deliveries: dict[str, dict[str, Any]] = {}
        send_jobs: dict[str, Any] = {}

        if wants_email and email_dest:
            send_jobs["email"] = self.email_adapter.send_message(
                to_destination=email_dest,
                message_content=draft.get("email_body", ""),
                subject=draft.get("email_subject", ""),
            )
        elif wants_email:
            deliveries["email"] = {"status": "skipped", "reason": "No email address saved."}

        if wants_whatsapp and wa_dest:
            send_jobs["whatsapp"] = self.whatsapp_adapter.send_message(
                to_destination=wa_dest,
                message_content=draft.get("whatsapp_body", ""),
            )
        elif wants_whatsapp:
            deliveries["whatsapp"] = {"status": "skipped", "reason": "No WhatsApp number saved."}

        results = await asyncio.gather(*send_jobs.values(), return_exceptions=True)
        for name, result in zip(send_jobs, results, strict=False):
            if isinstance(result, Exception):
                logger.exception("%s reminder delivery raised an exception", name, exc_info=result)
                deliveries[name] = {"status": "failed", "error_message": str(result)}
            else:
                deliveries[name] = result

        sent_channels = [name for name, result in deliveries.items() if self._delivery_succeeded(result)]
        failed_channels = [name for name, result in deliveries.items() if result.get("status") in {DeliveryStatus.FAILED, "failed"}]
        skipped_channels = [name for name, result in deliveries.items() if result.get("status") == "skipped"]

        details: list[str] = []
        if sent_channels:
            details.append(f"sent via {' and '.join(sent_channels)}")
        if failed_channels:
            details.append(f"failed on {' and '.join(failed_channels)}")
        if skipped_channels:
            details.append(f"skipped {' and '.join(skipped_channels)} (contact not saved)")
            
        status = "success" if sent_channels and not failed_channels else "partial" if sent_channels else "error"
        message = f"Reminder for {client_name}: {', '.join(details)}." if details else f"Reminder for {client_name} could not be sent."
        
        # Save to database if db and principal are provided
        if db and user_id and organization_id and client_id:
            from app.models.communication_log import CommunicationLog, CommunicationChannel
            for channel_name, result in deliveries.items():
                if result.get("status") == "skipped":
                    continue
                
                log_status = DeliveryStatus.SENT if result.get("status") not in {"failed", DeliveryStatus.FAILED} else DeliveryStatus.FAILED
                chan_enum = CommunicationChannel.WHATSAPP if channel_name == "whatsapp" else CommunicationChannel.EMAIL
                
                log = CommunicationLog(
                    client_id=client_id,
                    organization_id=organization_id,
                    user_id=user_id,
                    channel=chan_enum,
                    message_content=draft.get(f"{channel_name}_body", ""),
                    status=log_status,
                    error_message=result.get("error_message"),
                    provider_message_id=result.get("provider_message_id")
                )
                db.add(log)
            await db.commit()

        return {"status": status, "message": message, "deliveries": deliveries}
