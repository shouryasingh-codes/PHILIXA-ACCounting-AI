from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from fastapi import BackgroundTasks
from datetime import date
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import get_ai_provider
from app.core.auth import Principal
from app.core.config import Settings
from app.models.client import Client
from app.models.meeting import Meeting
from app.core.redis import get_redis_client
from app.database.session import AsyncSessionLocal
from app.services.meeting_processing_service import MeetingProcessingService
from app.services.portfolio_copilot_service import process_copilot_query
from app.services.reminder_service import ReminderService
from app.schemas.meeting_note import MeetingNoteProcessRequest

logger = logging.getLogger(__name__)


class VoiceAssistantService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

        self.economy_provider = get_ai_provider(self.settings.ai_economy_provider, self.settings)
        self.economy_model = self.settings.ai_economy_model

        self.review_provider = get_ai_provider(self.settings.ai_review_provider, self.settings)
        self.review_model = self.settings.ai_review_model

    def _looks_like_reminder_command(self, text: str) -> bool:
        normalized = text.lower()
        return ("reminder" in normalized or "email" in normalized or "message" in normalized or "whatsapp" in normalized) and ("send" in normalized or "bhej" in normalized)

    def _reminder_client_name_from_text(self, text: str) -> str | None:
        match = re.search(r"(?:remind|email|message)\s+([a-z][a-z .'-]{0,117}?)\s+(?:that|about|to)\b", text, flags=re.I)
        if match:
            return match.group(1).strip(" .'-")

        match = re.search(r"^\s*([a-z][a-z .'-]{0,117}?)\s+ko\b", text, flags=re.I)
        return match.group(1).strip(" .'-") if match else None

    async def chat(
        self,
        user_text: str,
        conversation_history: List[Dict[str, str]] | None = None,
        principal: Principal | None = None,
        background_tasks: BackgroundTasks | None = None,
    ) -> Tuple[str, Optional[int]]:
        """
        Process user's voice transcript and return a conversational response.
        """
        if conversation_history is None:
            conversation_history = []

        logger.info(f"Voice Assistant received: '{user_text}'")

        # Step 1: Extract Entities and Intent
        intent_schema = {
            "intent": "string ('QUERY', 'SAVE_MEETING', 'GENERAL_CHAT', 'SEND_REMINDER', 'CONFIRM_ACTION', or 'REJECT_ACTION')",
            "client_name": "string (extracted client name, or null if none)",
            "reminder_channel": "string (only for SEND_REMINDER: 'email', 'whatsapp', or 'both'; use 'both' if unspecified)",
            "meeting_notes": "string (the notes to save, if intent is SAVE_MEETING, else null)",
        }

        transcript = user_text

        try:
            intent_json_str = await asyncio.to_thread(
                self.economy_provider.generate_json,
                self.economy_model,
                f"User just said: '{transcript}'.\nAnalyze the user's voice input (which might be in Hindi/Hinglish) and extract intent. If they are talking about a client meeting to save, return SAVE_MEETING and extract the client's name. If they are asking a question about a specific person, client, past discussion, or ANY portfolio metrics/data (like 'how many meetings', 'who asked for discount'), return QUERY and extract the person's name if applicable. If they want to send an email, message, or reminder to a client, return SEND_REMINDER and extract the client's name. If they say 'yes', 'send it', 'haan bhej do', 'correct' and are confirming a previous action, return CONFIRM_ACTION. If they say 'no', 'cancel', 'stop', 'mat bhej', return REJECT_ACTION. Otherwise, return GENERAL_CHAT. (TRANSLATE AND SPELL HINDI NAMES IN ENGLISH, e.g. 'मनोज' -> 'Manoj').",
                json.loads(json.dumps(intent_schema)),
            )
            intent_data = json.loads(intent_json_str)
        except Exception as e_econ:
            logger.warning(f"Economy intent extraction failed: {e_econ}. Falling back to Review model.")
            try:
                intent_json_str = await asyncio.to_thread(
                    self.review_provider.generate_json,
                    self.review_model,
                    f"User just said: '{transcript}'.\nAnalyze the user's voice input (which might be in Hindi/Hinglish) and extract intent. If they are talking about a client meeting to save, return SAVE_MEETING and extract the client's name. If they are asking a question about a specific person, client, past discussion, or ANY portfolio metrics/data (like 'how many meetings', 'who asked for discount'), return QUERY and extract the person's name if applicable. If they want to send an email, message, or reminder to a client, return SEND_REMINDER and extract the client's name. If they say 'yes', 'send it', 'haan bhej do', 'correct' and are confirming a previous action, return CONFIRM_ACTION. If they say 'no', 'cancel', 'stop', 'mat bhej', return REJECT_ACTION. Otherwise, return GENERAL_CHAT. (TRANSLATE AND SPELL HINDI NAMES IN ENGLISH, e.g. 'मनोज' -> 'Manoj').",
                    json.loads(json.dumps(intent_schema)),
                )
                intent_data = json.loads(intent_json_str)
            except Exception as e_rev:
                logger.error(f"Review intent extraction also failed: {e_rev}")
                intent_data = {"intent": "GENERAL_CHAT", "client_name": None}

        intent = intent_data.get("intent", "GENERAL_CHAT")
        client_name = intent_data.get("client_name")
        reminder_channel = intent_data.get("reminder_channel")

        # Reminder commands trigger real delivery, not a conversational guess from the LLM.
        if principal and self._looks_like_reminder_command(user_text) and intent != "CONFIRM_ACTION":
            intent = "SEND_REMINDER"
            client_name = client_name or self._reminder_client_name_from_text(user_text)

        logger.info(f"Voice Assistant Intent: {intent}, Client: {client_name}")

        # Step 2: Context Retrieval (Memory)
        memory_context = ""
        client = None

        if intent == "QUERY" and principal:
            try:
                copilot_result = await process_copilot_query(
                    query=user_text,
                    organization_id=principal.organization_id,
                    user_id=principal.user_id,
                    role=principal.role,
                    db=self.db,
                    client_name=client_name
                )
                memory_context = f"The database search returned this precise answer: {copilot_result['answer']}"
            except Exception as e:
                logger.warning(f"Portfolio Copilot query failed for voice assistant: {e}")
                memory_context = "Could not retrieve portfolio data due to an error."
        elif intent == "SEND_REMINDER" and principal:
            try:
                result = await ReminderService().draft_client_reminder(
                    db=self.db,
                    organization_id=principal.organization_id,
                    user_id=principal.user_id,
                    role=principal.role,
                    client_name=client_name,
                    instruction=user_text,
                    channel=reminder_channel,
                )
                if result.get("status") == "success" and "draft_data" in result:
                    redis = await get_redis_client()
                    await redis.setex(
                        f"pending_reminder:{principal.user_id}",
                        300,
                        json.dumps(result["draft_data"])
                    )
                return result["message"], None
            except Exception as e:
                logger.error(f"Reminder Service drafting error: {e}")
                memory_context = "Could not draft the reminder due to an error."
                
        elif intent == "CONFIRM_ACTION" and principal:
            redis = await get_redis_client()
            redis_key = f"pending_reminder:{principal.user.id}"
            pending_data_str = await redis.get(redis_key)
            if pending_data_str:
                try:
                    pending_data = json.loads(pending_data_str)
                    result = await ReminderService().dispatch_client_reminder(
                        pending_data, 
                        db=self.db, 
                        user_id=principal.user.id, 
                        organization_id=principal.organization.id
                    )
                    await redis.delete(redis_key)
                    return result["message"], None
                except Exception as e:
                    logger.error(f"Failed to dispatch pending reminder: {e}")
                    return "There was an error sending the message.", None
            else:
                return "I don't have any pending messages to send right now.", None
                
        elif intent == "REJECT_ACTION" and principal:
            redis = await get_redis_client()
            redis_key = f"pending_reminder:{principal.user_id}"
            if await redis.exists(redis_key):
                await redis.delete(redis_key)
                return "Okay, I have cancelled the message.", None
            else:
                return "Okay.", None

        elif client_name and intent == "SAVE_MEETING":
            try:
                client_stmt = select(Client).where(Client.name.ilike(f"%{client_name}%"))
                if principal is not None:
                    client_stmt = client_stmt.where(Client.organization_id == principal.organization_id)
                    if principal.role.lower() == "member":
                        client_stmt = client_stmt.where(Client.user_id == principal.user_id)
                client_stmt = client_stmt.limit(1)

                client_res = await self.db.execute(client_stmt)
                client = client_res.scalar_one_or_none()

                if client:
                    meeting_stmt = select(Meeting).where(
                        Meeting.client_id == client.id,
                        Meeting.organization_id == client.organization_id,
                    )
                    if principal is not None and principal.role.lower() == "member":
                        meeting_stmt = meeting_stmt.where(Meeting.user_id == principal.user_id)
                    meeting_stmt = meeting_stmt.order_by(Meeting.meeting_date.desc()).limit(3)

                    meeting_res = await self.db.execute(meeting_stmt)
                    meetings = meeting_res.scalars().all()

                    if meetings:
                        memory_context = f"Here is the context from the database regarding PAST meetings for {client.name} (These meetings have ALREADY happened):\n"
                        for m in meetings:
                            memory_context += f"- Past meeting that occurred on {m.meeting_date}: {m.summary}\n"
                    else:
                        memory_context = f"Found client {client.name} but no previous meetings recorded."
                else:
                    memory_context = f"No previous records found for {client_name}."
            except Exception as e:
                logger.warning(f"Semantic search failed for voice assistant: {e}")
                memory_context = "Could not retrieve past records due to an error."

        # Trigger Background Save for Meetings
        meeting_id = None
        if intent == "SAVE_MEETING" and intent_data.get("meeting_notes") and principal:
            notes_to_save = intent_data.get("meeting_notes")
            resolved_client_id = client.id if client else None
            
            # Synchronously create the Meeting row to get the ID
            meeting = Meeting(
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                client_id=None,
                raw_notes=notes_to_save,
                meeting_date=date.today(),
                source_type="voice",
                summary="",
                key_discussion_points_json="[]",
                concerns_json="[]",
                status="manual_review_required",
                client_identification_status="unknown",
                client_identification_confidence=0.0,
            )
            self.db.add(meeting)
            await self.db.flush()
            meeting_id = meeting.id
            await self.db.commit() # Important: Commit so the background task can query it
            
            async def background_save(m_id):
                async with AsyncSessionLocal() as bg_db:
                    try:
                        # Fetch the meeting we just created
                        m_res = await bg_db.execute(select(Meeting).where(Meeting.id == m_id))
                        m = m_res.scalar_one_or_none()
                        if m:
                            svc = MeetingProcessingService(self.settings, self.economy_provider)
                            await svc.process_existing_meeting(bg_db, m, resolved_client_id)
                    except Exception as e:
                        logger.error(f"Voice background save failed for meeting {m_id}: {e}")

            if background_tasks:
                background_tasks.add_task(background_save, meeting_id)
            else:
                asyncio.create_task(background_save(meeting_id))
            
            memory_context += "\n\nSYSTEM INSTRUCTION: You have successfully started saving the meeting notes in the background. Tell the user exactly this: 'Okay, I am saving this meeting for you now.'"

        # Step 3: Generate Conversational Response
        system_prompt = (
            "You are Philixa, an energetic and smart AI voice assistant for insurance agents. "
            "You have a confident, conversational, and direct personality. "
            "IMPORTANT: Keep your answers VERY short (1-2 sentences). You are speaking aloud, so don't use bullet points, markdown, or complex words. "
            "CRITICAL RULE: If the user is asking a question (QUERY) about a specific person or topic and you DO NOT see their details in the 'Context from database', you MUST reply saying you don't have information about them. DO NOT make up details. "
            "HOWEVER, if the Context contains a 'SYSTEM INSTRUCTION', you MUST follow that instruction as your absolute highest priority. "
            "NOTE: You may reply in Hinglish (a natural mix of Hindi and English) if the user speaks in Hinglish. "
            f"Context from database: {memory_context}"
        )

        if memory_context:
            system_prompt += f"\n\nDATABASE CONTEXT:\n{memory_context}"

        history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in conversation_history[-4:]])

        final_user_prompt = ""
        if history_text:
            final_user_prompt += f"Recent Conversation:\n{history_text}\n\n"
        final_user_prompt += f"Manager: {user_text}"

        try:
            response_text = await asyncio.to_thread(
                self.economy_provider.generate_text,
                self.economy_model,
                system_prompt,
                final_user_prompt,
            )
        except Exception as e_econ:
            logger.warning(f"Economy voice generation failed: {e_econ}. Falling back to Review model.")
            try:
                response_text = await asyncio.to_thread(
                    self.review_provider.generate_text,
                    self.review_model,
                    system_prompt,
                    final_user_prompt,
                )
            except Exception as e:
                logger.error(f"LLM Generation error: {e}")
                return "I'm having trouble processing that right now.", meeting_id

        return response_text, meeting_id
