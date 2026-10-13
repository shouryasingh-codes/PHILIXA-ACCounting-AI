from __future__ import annotations

from datetime import date
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal
from app.models.enums import MeetingSourceType, MeetingStatus
from app.models.meeting import Meeting
from app.services.json_utils import to_json


class MeetingRepository:
    async def list(
        self,
        db: AsyncSession,
        principal: Principal,
        client_id: int | None = None,
    ) -> list[Meeting]:
        stmt = select(Meeting).where(Meeting.organization_id == principal.organization_id)
        if principal.role.lower() == "member":
            stmt = stmt.where(Meeting.user_id == principal.user_id)
        if client_id is not None:
            stmt = stmt.where(Meeting.client_id == client_id)
        stmt = stmt.order_by(Meeting.meeting_date.desc(), Meeting.created_at.desc())
        result = await db.scalars(stmt)
        return list(result.all())

    async def get_by_id(
        self,
        db: AsyncSession,
        principal: Principal,
        meeting_id: int,
    ) -> Meeting | None:
        stmt = select(Meeting).where(
            Meeting.id == meeting_id,
            Meeting.organization_id == principal.organization_id,
        )
        if principal.role.lower() == "member":
            stmt = stmt.where(Meeting.user_id == principal.user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        principal: Principal,
        data: dict[str, Any],
    ) -> Meeting:
        meeting_date = data.get("meeting_date")
        if isinstance(meeting_date, str):
            meeting_date = date.fromisoformat(meeting_date)
        elif meeting_date is None:
            meeting_date = date.today()

        key_points = data.get("key_discussion_points", [])
        key_points_json = (
            to_json(key_points)
            if isinstance(key_points, list)
            else data.get("key_discussion_points_json", "[]")
        )
        concerns = data.get("concerns", [])
        concerns_json = (
            to_json(concerns)
            if isinstance(concerns, list)
            else data.get("concerns_json", "[]")
        )

        source_type_val = data.get("source_type", MeetingSourceType.PASTED_NOTE.value)
        if hasattr(source_type_val, "value"):
            source_type_val = source_type_val.value

        status_val = data.get("status", MeetingStatus.PROCESSED.value)
        if hasattr(status_val, "value"):
            status_val = status_val.value

        meeting = Meeting(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            client_id=data.get("client_id"),
            raw_notes=data.get("raw_notes", ""),
            meeting_date=meeting_date,
            summary=data.get("summary", ""),
            key_discussion_points_json=key_points_json,
            concerns_json=concerns_json,
            audio_path=data.get("audio_path") or data.get("audio_file_path"),
            audio_duration_seconds=data.get("audio_duration_seconds", 0),
            suggested_client_name=data.get("suggested_client_name"),
            source_type=source_type_val,
            status=status_val,
            client_identification_status=data.get("client_identification_status", "identified"),
            client_identification_confidence=float(data.get("client_identification_confidence", 0.0)),
        )
        db.add(meeting)
        await db.flush()
        return meeting

    async def update(
        self,
        db: AsyncSession,
        principal: Principal,
        meeting_id: int,
        data: dict[str, Any],
    ) -> Meeting | None:
        meeting = await self.get_by_id(db, principal, meeting_id)
        if not meeting:
            return None

        updatable_fields = [
            "client_id", "raw_notes", "meeting_date", "summary",
            "audio_path", "audio_duration_seconds", "suggested_client_name",
            "source_type", "status", "client_identification_status",
            "client_identification_confidence",
        ]
        for field in updatable_fields:
            if field in data and data[field] is not None:
                val = data[field]
                if field == "meeting_date" and isinstance(val, str):
                    val = date.fromisoformat(val)
                elif hasattr(val, "value"):
                    val = val.value
                setattr(meeting, field, val)

        if "key_discussion_points" in data and isinstance(data["key_discussion_points"], list):
            meeting.key_discussion_points_json = to_json(data["key_discussion_points"])
        elif "key_discussion_points_json" in data:
            meeting.key_discussion_points_json = data["key_discussion_points_json"]

        if "concerns" in data and isinstance(data["concerns"], list):
            meeting.concerns_json = to_json(data["concerns"])
        elif "concerns_json" in data:
            meeting.concerns_json = data["concerns_json"]

        db.add(meeting)
        await db.flush()
        return meeting
