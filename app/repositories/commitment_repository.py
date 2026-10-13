from __future__ import annotations

from datetime import date
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal
from app.models.commitment import Commitment
from app.services.rules_engine_service import RulesEngineService
from app.utils.text_normalization import normalize_text


class CommitmentRepository:
    async def list(
        self,
        db: AsyncSession,
        principal: Principal,
        scope: str = "team",
        status: str | None = None,
        client_id: int | None = None,
        due_before: date | None = None,
    ) -> list[Commitment]:
        stmt = select(Commitment).where(Commitment.organization_id == principal.organization_id)
        if principal.role.lower() == "member" or scope == "me":
            stmt = stmt.where(Commitment.user_id == principal.user_id)
        if status:
            stmt = stmt.where(Commitment.status == status)
        if client_id is not None:
            stmt = stmt.where(Commitment.client_id == client_id)
        if due_before is not None:
            stmt = stmt.where(Commitment.due_date.is_not(None), Commitment.due_date <= due_before)
        stmt = stmt.order_by(Commitment.created_at.desc())
        result = await db.scalars(stmt)
        return list(result.all())

    async def get_by_id(
        self,
        db: AsyncSession,
        principal: Principal,
        commitment_id: int,
    ) -> Commitment | None:
        stmt = select(Commitment).where(
            Commitment.id == commitment_id,
            Commitment.organization_id == principal.organization_id,
        )
        if principal.role.lower() == "member":
            stmt = stmt.where(Commitment.user_id == principal.user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        principal: Principal,
        data: dict[str, Any],
    ) -> Commitment:
        description = (data.get("description") or "").strip()
        normalized_description = normalize_text(description)
        due_date = data.get("due_date")
        if isinstance(due_date, str):
            try:
                due_date = date.fromisoformat(due_date)
            except ValueError:
                due_date = None

        commitment = Commitment(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            client_id=data["client_id"],
            description=description,
            normalized_description=normalized_description,
            owner=data.get("owner", "RM"),
            due_date=due_date,
            due_date_text=data.get("due_date_text"),
            due_date_confidence=float(data.get("due_date_confidence", 0.0)),
            urgency_level=data.get("urgency_level", "medium"),
            status=data.get("status", "pending"),
            extraction_confidence=float(data.get("extraction_confidence", 0.0)),
        )
        db.add(commitment)
        await db.flush()
        return commitment

    async def update_status(
        self,
        db: AsyncSession,
        principal: Principal,
        commitment_id: int,
        status: str,
    ) -> Commitment | None:
        commitment = await self.get_by_id(db, principal, commitment_id)
        if not commitment:
            return None
        commitment.status = status
        db.add(commitment)
        await db.flush()

        await RulesEngineService.sync_client_tasks_and_risks(db, commitment.client_id)
        return commitment
