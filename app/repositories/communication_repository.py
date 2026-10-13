from __future__ import annotations

from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal
from app.models.communication_log import CommunicationLog

class CommunicationRepository:
    async def list_by_client_id(self, db: AsyncSession, principal: Principal, client_id: int) -> list[CommunicationLog]:
        stmt = select(CommunicationLog).where(
            CommunicationLog.client_id == client_id,
            CommunicationLog.organization_id == principal.organization_id,
        )
        if principal.role.lower() == "member":
            stmt = stmt.where(CommunicationLog.user_id == principal.user_id)
        stmt = stmt.order_by(CommunicationLog.created_at.desc())
        result = await db.scalars(stmt)
        return list(result.all())

    async def create(self, db: AsyncSession, data: dict[str, Any]) -> CommunicationLog:
        log = CommunicationLog(**data)
        db.add(log)
        return log

    async def update_status_by_provider_id(
        self,
        db: AsyncSession,
        provider_message_id: str,
        status: str,
        error_message: str | None = None
    ) -> CommunicationLog | None:
        from app.models.notification import DeliveryStatus
        stmt = select(CommunicationLog).where(CommunicationLog.provider_message_id == provider_message_id)
        result = await db.execute(stmt)
        log = result.scalar_one_or_none()
        
        if log:
            log.status = DeliveryStatus(status.lower())
            if error_message is not None:
                log.error_message = error_message
        return log
