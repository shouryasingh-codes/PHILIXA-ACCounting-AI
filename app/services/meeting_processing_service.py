from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import AIExtractionError, AIProvider, get_ai_provider
from app.core.arq import get_arq_pool
from app.core.auth import Principal
from app.core.config import Settings, get_settings
from app.models.ai_extraction_log import AIExtractionLog
from app.models.client import Client
from app.models.enums import MeetingSourceType, MeetingStatus
from app.models.meeting import Meeting
from app.schemas.meeting_note import MeetingNoteProcessRequest
from app.services.ai_routing_service import AIRoutingService
from app.services.client_identification_service import ClientIdentificationService
from app.services.commitment_service import CommitmentService
from app.services.json_utils import from_json, to_json
from app.services.memory_service import MemoryService

logger = logging.getLogger(__name__)


class MeetingProcessingService:
    def __init__(
        self,
        settings: Settings | None = None,
        ai_provider: AIProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.ai_provider = ai_provider or get_ai_provider(settings=self.settings)
        self.client_identifier = ClientIdentificationService(self.settings)
        self.commitments = CommitmentService()
        self.memory = MemoryService()

    async def process_notes(
        self,
        db: AsyncSession,
        request: MeetingNoteProcessRequest,
        principal: Principal | None = None,
        organization_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        meeting_date = request.meeting_date or date.today()

        if principal is not None:
            organization_id = principal.organization_id
            user_id = principal.user_id

        # Step 1: Persist the raw meeting immediately so that even a total
        # AI failure is tracked in the database as manual_review_required.
        meeting = Meeting(
            organization_id=organization_id,
            user_id=user_id,
            client_id=None,
            raw_notes=request.raw_notes,
            meeting_date=meeting_date,
            source_type=request.source_type.value,
            summary="",
            key_discussion_points_json="[]",
            concerns_json="[]",
            status=MeetingStatus.MANUAL_REVIEW_REQUIRED.value,
            client_identification_status="unknown",
            client_identification_confidence=0.0,
        )
        db.add(meeting)
        await db.flush()  # obtain meeting.id for the audit log

        return await self._process_extracted_meeting(db, meeting, request.known_client_id, raise_on_error=True)

    async def process_existing_meeting(
        self, db: AsyncSession, meeting: Meeting, known_client_id: int | None = None
    ) -> dict[str, Any]:
        """Process an already created meeting, like one created from an audio upload."""
        return await self._process_extracted_meeting(db, meeting, known_client_id, raise_on_error=False)

    async def _process_extracted_meeting(
        self, db: AsyncSession, meeting: Meeting, known_client_id: int | None, raise_on_error: bool = False
    ) -> dict[str, Any]:
        meeting_date = meeting.meeting_date or date.today()
        # Both failure paths are audit-logged inside the routing service.
        try:
            routing = AIRoutingService(db, self.settings)
            extraction = await routing.route_and_extract(
                meeting.raw_notes, meeting_date, meeting.id
            )
        except AIExtractionError as exc:
            if raise_on_error:
                raise exc
            # Both models failed — keep the meeting as manual_review_required
            # and commit so the record is visible for human triage.
            logger.error(
                "All AI models failed for meeting %d — saved as manual_review_required.",
                meeting.id,
            )
            await db.commit()
            return self._manual_review_payload(meeting)

        # Step 3: Client identification.
        client_info = extraction.get("client_identification", {})
        client, client_status, warnings = await self.client_identifier.resolve_client(
            db,
            suggested_name=client_info.get("suggested_client_name"),
            confidence=float(client_info.get("confidence") or 0.0),
            known_client_id=known_client_id,
            organization_id=meeting.organization_id,
        )
        warnings.extend(extraction.get("warnings") or [])

        # Step 4: Update the meeting row with extracted data and final status.
        meeting.client_id = client.id if client else None
        meeting.summary = extraction.get("meeting_summary") or ""
        meeting.key_discussion_points_json = to_json(
            extraction.get("key_discussion_points") or []
        )
        meeting.concerns_json = to_json(extraction.get("concerns") or [])
        meeting.status = (
            "processed" if client else "client_identification_required"
        )
        meeting.client_identification_status = client_status
        meeting.suggested_client_name = client_info.get("suggested_client_name")
        meeting.suggested_client_email = client_info.get("suggested_client_email")
        meeting.suggested_client_whatsapp_phone = client_info.get("suggested_client_whatsapp_phone")
        meeting.client_identification_confidence = float(
            client_info.get("confidence") or 0.0
        )
        db.add(meeting)
        # Temporarily store the email for the confirmation popup
        if not client:
            extracted_email = client_info.get("suggested_client_email")
            if extracted_email:
                meeting.suggested_client_email = extracted_email
            extracted_phone = client_info.get("suggested_client_whatsapp_phone")
            if extracted_phone:
                meeting.suggested_client_whatsapp_phone = extracted_phone

        # Step 5: Upsert commitments and refresh client memory.
        created: list = []
        updated: list = []
        if client:
            client.products_owned_json = self._merge_string_list_field(
                client.products_owned_json, extraction.get("products_owned") or []
            )
            client.products_interested_json = self._merge_string_list_field(
                client.products_interested_json, extraction.get("products_interested") or []
            )
            # Save extracted email to existing client (only if not already set)
            extracted_email = client_info.get("suggested_client_email")
            if extracted_email and not client.email:
                client.email = extracted_email
            extracted_phone = client_info.get("suggested_client_whatsapp_phone")
            if extracted_phone and not client.whatsapp_phone:
                client.whatsapp_phone = extracted_phone
            created, updated = await self.commitments.upsert_commitments(
                db,
                client_id=client.id,
                meeting_id=meeting.id,
                extracted_commitments=extraction.get("commitments") or [],
                organization_id=meeting.organization_id,
                user_id=meeting.user_id,
            )
            await self.memory.update_client_memory(db, client.id)

            from app.services.rules_engine_service import RulesEngineService
            await RulesEngineService.sync_client_tasks_and_risks(db, client.id)

        await db.commit()

        # TRIGGER ARQ BACKGROUND JOB
        pool = get_arq_pool()
        if client and pool and meeting.organization_id and meeting.user_id:
            await pool.enqueue_job(
                "generate_meeting_embeddings",
                meeting.id,
                organization_id=meeting.organization_id,
                user_id=meeting.user_id,
                _job_id=f"generate_meeting_embeddings_{meeting.id}",
            )

        return await self._response_payload(
            db,
            meeting=meeting,
            client=client,
            client_status=client_status,
            extraction=extraction,
            created=created,
            updated=updated,
            warnings=warnings,
        )

    async def confirm_client(
        self,
        db: AsyncSession,
        *,
        meeting_id: int,
        client_id: int | None = None,
        new_client_name: str | None = None,
        new_client_email: str | None = None,
        new_client_whatsapp_phone: str | None = None,
        principal: Principal | None = None,
    ) -> dict[str, Any] | None:
        if principal is not None:
            from app.repositories.meeting_repository import MeetingRepository
            meeting = await MeetingRepository().get_by_id(db, principal, meeting_id)
        else:
            meeting = await db.get(Meeting, meeting_id)

        if not meeting:
            return None

        if client_id and new_client_name:
            raise ValueError("Provide either client_id or new_client_name, not both.")

        if client_id:
            if principal is not None:
                from app.repositories.client_repository import ClientRepository
                client = await ClientRepository().get_by_id(db, principal, client_id)
            else:
                client = await db.get(Client, client_id)

            if not client:
                raise ValueError("Client not found.")
            if new_client_email:
                client.email = new_client_email
            if new_client_whatsapp_phone:
                client.whatsapp_phone = new_client_whatsapp_phone
            client_status = "identified"
        elif new_client_name:
            client = Client(
                organization_id=meeting.organization_id,
                user_id=meeting.user_id,
                name=new_client_name,
                normalized_name=self._normalize_client_name(new_client_name),
                email=new_client_email or meeting.suggested_client_email,
                whatsapp_phone=(
                    new_client_whatsapp_phone or meeting.suggested_client_whatsapp_phone
                ),
            )
            db.add(client)
            await db.flush()
            client_status = "created"
        else:
            raise ValueError("Either client_id or new_client_name is required.")

        latest_log = await db.scalar(
            select(AIExtractionLog)
            .where(AIExtractionLog.meeting_id == meeting_id, AIExtractionLog.success.is_(True))
            .order_by(AIExtractionLog.created_at.desc())
        )
        extraction = from_json(latest_log.parsed_response_json if latest_log else "{}", {})
        meeting.client_id = client.id
        meeting.status = "processed"
        meeting.client_identification_status = client_status
        db.add(meeting)
        client.products_owned_json = self._merge_string_list_field(
            client.products_owned_json, extraction.get("products_owned") or []
        )
        client.products_interested_json = self._merge_string_list_field(
            client.products_interested_json, extraction.get("products_interested") or []
        )
        created, updated = await self.commitments.upsert_commitments(
            db,
            client_id=client.id,
            meeting_id=meeting.id,
            extracted_commitments=extraction.get("commitments") or [],
            organization_id=meeting.organization_id,
            user_id=meeting.user_id,
        )
        await self.memory.update_client_memory(db, client.id)

        from app.services.rules_engine_service import RulesEngineService
        await RulesEngineService.sync_client_tasks_and_risks(db, client.id)

        await db.commit()

        # TRIGGER ARQ BACKGROUND JOB
        pool = get_arq_pool()
        if pool and meeting.organization_id and meeting.user_id:
            await pool.enqueue_job(
                "generate_meeting_embeddings",
                meeting.id,
                organization_id=meeting.organization_id,
                user_id=meeting.user_id,
                _job_id=f"generate_meeting_embeddings_{meeting.id}",
            )

        return await self._response_payload(
            db,
            meeting=meeting,
            client=client,
            client_status=client_status,
            extraction=extraction,
            created=created,
            updated=updated,
            warnings=[],
        )

    @staticmethod
    def _manual_review_payload(meeting: Meeting) -> dict[str, Any]:
        warning_msg = (
            "AI extraction failed after all model attempts. "
            "This meeting has been saved and requires manual review."
        )
        return {
            "meeting_id": meeting.id,
            "client_status": "unknown",
            "client_id": None,
            "requires_client_confirmation": False,
            "meeting_summary": "",
            "meeting": meeting_to_dict(meeting),
            "extraction": {
                "client_identification": {
                    "status": "unknown",
                    "matched_client_id": None,
                    "suggested_client_name": None,
                    "suggested_client_email": None,
                    "suggested_client_whatsapp_phone": None,
                    "confidence": 0.0,
                    "requires_confirmation": False,
                },
                "meeting_summary": "",
                "key_discussion_points": [],
                "products_owned": [],
                "products_interested": [],
                "concerns": [],
                "commitments": [],
                "action_items": [],
                "warnings": [warning_msg],
            },
            "commitments_created": [],
            "commitments_updated": [],
            "pending_commitments": [],
            "warnings": [warning_msg],
        }

    async def _response_payload(
        self,
        db: AsyncSession,
        *,
        meeting: Meeting,
        client: Client | None,
        client_status: str,
        extraction: dict[str, Any],
        created: list,
        updated: list,
        warnings: list[str],
    ) -> dict[str, Any]:
        unique_warnings = list(dict.fromkeys(warnings))
        pending = await self.commitments.pending_for_client(db, client.id) if client else []
        return {
            "meeting_id": meeting.id,
            "client_status": client_status,
            "client_id": client.id if client else None,
            "requires_client_confirmation": client is None,
            "meeting_summary": meeting.summary,
            "meeting": meeting_to_dict(meeting),
            "extraction": self._extraction_payload(
                extraction=extraction,
                client=client,
                client_status=client_status,
                warnings=unique_warnings,
            ),
            "commitments_created": created,
            "commitments_updated": updated,
            "pending_commitments": pending,
            "warnings": unique_warnings,
        }

    @staticmethod
    def _normalize_client_name(name: str) -> str:
        from app.utils.text_normalization import normalize_text

        return normalize_text(name)

    def _extraction_payload(
        self,
        *,
        extraction: dict[str, Any],
        client: Client | None,
        client_status: str,
        warnings: list[str],
    ) -> dict[str, Any]:
        client_identification = extraction.get("client_identification", {})
        extracted_commitments = [
            self._sanitize_extracted_commitment(item)
            for item in extraction.get("commitments") or []
            if item.get("description")
        ]
        return {
            "client_identification": {
                "status": client_status,
                "matched_client_id": client.id if client else client_identification.get("matched_client_id"),
                "suggested_client_name": (
                    client.name
                    if client
                    else client_identification.get("suggested_client_name")
                ),
                "suggested_client_email": client_identification.get("suggested_client_email"),
                "suggested_client_whatsapp_phone": client_identification.get("suggested_client_whatsapp_phone"),
                "confidence": float(client_identification.get("confidence") or 0.0),
                "requires_confirmation": client is None,
            },
            "meeting_summary": extraction.get("meeting_summary") or "",
            "key_discussion_points": extraction.get("key_discussion_points") or [],
            "products_owned": extraction.get("products_owned") or [],
            "products_interested": extraction.get("products_interested") or [],
            "concerns": extraction.get("concerns") or [],
            "commitments": extracted_commitments,
            "action_items": extraction.get("action_items")
            or [item["description"] for item in extracted_commitments],
            "warnings": warnings,
        }

    def _sanitize_extracted_commitment(self, item: dict[str, Any]) -> dict[str, Any]:
        due_date_confidence = float(item.get("due_date_confidence") or 0.0)
        due_date = item.get("due_date")
        if due_date_confidence < self.settings.due_date_threshold:
            due_date = None
        return {
            "description": item.get("description") or "",
            "owner": item.get("owner") or "RM",
            "due_date": due_date,
            "due_date_text": item.get("due_date_text"),
            "due_date_confidence": due_date_confidence,
            "urgency_level": item.get("urgency_level") or "medium",
            "status": item.get("status") or "pending",
            "confidence": float(item.get("confidence") or item.get("extraction_confidence") or 0.0),
        }

    def _merge_string_list_field(self, current_json: str, new_items: list[str]) -> str:
        if not new_items:
            return current_json
        existing = from_json(current_json, [])
        merged: list[str] = []
        seen: set[str] = set()
        for value in [*existing, *new_items]:
            val_str = str(value or "").strip()
            if not val_str:
                continue
            key = val_str.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(val_str)
        return to_json(merged)


def meeting_to_dict(meeting: Meeting) -> dict[str, Any]:
    return {
        "id": meeting.id,
        "client_id": meeting.client_id,
        "raw_notes": meeting.raw_notes,
        "meeting_date": meeting.meeting_date.isoformat(),
        "summary": meeting.summary,
        "key_discussion_points": from_json(meeting.key_discussion_points_json, []),
        "concerns": from_json(meeting.concerns_json, []),
        "status": meeting.status,
        "source_type": meeting.source_type,
        "client_identification_status": meeting.client_identification_status,
        "client_identification_confidence": meeting.client_identification_confidence,
    }
