from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.client import Client
from app.models.commitment import Commitment, CommitmentMeetingLink
from app.utils.text_normalization import normalize_text, similarity


class CommitmentService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def upsert_commitments(
        self,
        db: AsyncSession,
        *,
        client_id: int,
        meeting_id: int,
        extracted_commitments: list[dict[str, Any]],
        organization_id: str | None = None,
        user_id: str | None = None,
    ) -> tuple[list[Commitment], list[Commitment]]:
        if not organization_id or not user_id:
            client = await db.get(Client, client_id)
            if client:
                organization_id = organization_id or client.organization_id
                user_id = user_id or client.user_id

        created: list[Commitment] = []
        updated: list[Commitment] = []
        for item in extracted_commitments:
            description = (item.get("description") or "").strip()
            if not description:
                continue
            normalized = normalize_text(description)
            existing = await self._find_duplicate(db, client_id, normalized)
            due_date_confidence = float(item.get("due_date_confidence") or 0.0)
            due_date = self._parse_due_date(item.get("due_date"))
            if due_date_confidence < self.settings.due_date_threshold:
                due_date = None
            if existing:
                existing.description = description
                existing.normalized_description = normalized
                existing.owner = item.get("owner") or existing.owner or "RM"
                existing.urgency_level = item.get("urgency_level") or existing.urgency_level or "medium"
                if due_date:
                    existing.due_date = due_date
                    existing.due_date_text = item.get("due_date_text")
                    existing.due_date_confidence = due_date_confidence
                elif due_date_confidence < self.settings.due_date_threshold:
                    existing.due_date = None
                    existing.due_date_text = item.get("due_date_text")
                    existing.due_date_confidence = due_date_confidence
                existing.extraction_confidence = max(
                    existing.extraction_confidence,
                    float(item.get("confidence") or item.get("extraction_confidence") or 0.0),
                )
                await self._link_meeting(db, existing.id, meeting_id)
                updated.append(existing)
                continue

            commitment = Commitment(
                organization_id=organization_id,
                user_id=user_id,
                client_id=client_id,
                description=description,
                normalized_description=normalized,
                owner=item.get("owner") or "RM",
                due_date=due_date,
                due_date_text=item.get("due_date_text"),
                due_date_confidence=due_date_confidence,
                urgency_level=item.get("urgency_level") or "medium",
                status=item.get("status") or "pending",
                extraction_confidence=float(
                    item.get("confidence") or item.get("extraction_confidence") or 0.0
                ),
            )
            db.add(commitment)
            await db.flush()
            await self._link_meeting(db, commitment.id, meeting_id)
            created.append(commitment)
        return created, updated

    async def list_commitments(
        self,
        db: AsyncSession,
        *,
        status: str | None = None,
        client_id: int | None = None,
        due_before: date | None = None,
    ) -> list[Commitment]:
        query = select(Commitment).order_by(Commitment.created_at.desc())
        if status:
            query = query.where(Commitment.status == status)
        if client_id:
            query = query.where(Commitment.client_id == client_id)
        if due_before:
            query = query.where(Commitment.due_date.is_not(None), Commitment.due_date <= due_before)
        return list((await db.scalars(query)).all())

    async def update_status(self, db: AsyncSession, commitment_id: int, status: str) -> Commitment | None:
        commitment = await db.get(Commitment, commitment_id)
        if not commitment:
            return None
        commitment.status = status
        db.add(commitment)
        await db.flush()

        from app.services.rules_engine_service import RulesEngineService
        await RulesEngineService.sync_client_tasks_and_risks(db, commitment.client_id)

        return commitment

    async def pending_for_client(self, db: AsyncSession, client_id: int) -> list[Commitment]:
        return list(
            (await db.scalars(
                select(Commitment)
                .where(Commitment.client_id == client_id, Commitment.status == "pending")
                .order_by(Commitment.due_date.is_(None), Commitment.due_date, Commitment.created_at)
            )).all()
        )

    async def _find_duplicate(
        self, db: AsyncSession, client_id: int, normalized_description: str
    ) -> Commitment | None:
        candidates = list(
            (await db.scalars(
                select(Commitment).where(
                    Commitment.client_id == client_id,
                    Commitment.status == "pending",
                )
            )).all()
        )
        for candidate in candidates:
            score = similarity(candidate.normalized_description, normalized_description)
            if score >= 0.72:
                return candidate
        return None

    async def _link_meeting(self, db: AsyncSession, commitment_id: int, meeting_id: int) -> None:
        existing = await db.scalar(
            select(CommitmentMeetingLink).where(
                CommitmentMeetingLink.commitment_id == commitment_id,
                CommitmentMeetingLink.meeting_id == meeting_id,
            )
        )
        if existing:
            return
        db.add(CommitmentMeetingLink(commitment_id=commitment_id, meeting_id=meeting_id))
        await db.flush()

    @staticmethod
    def _parse_due_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
