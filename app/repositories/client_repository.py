from __future__ import annotations

from typing import Any
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal
from app.models.ai_extraction_log import AIExtractionLog
from app.models.client import Client
from app.models.commitment import Commitment, CommitmentMeetingLink
from app.models.follow_up_task import FollowUpTask
from app.models.meeting import Meeting
from app.models.meeting_evidence import MeetingEvidence
from app.models.risk_signal import RiskSignal
from app.services.json_utils import to_json
from app.utils.text_normalization import normalize_text


class ClientRepository:
    async def list(self, db: AsyncSession, principal: Principal, scope: str = "team") -> list[Client]:
        from sqlalchemy.orm import joinedload
        stmt = select(Client).options(joinedload(Client.user)).where(Client.organization_id == principal.organization_id)
        if principal.role.lower() == "member" or scope == "me":
            stmt = stmt.where(Client.user_id == principal.user_id)
        stmt = stmt.order_by(Client.updated_at.desc())
        result = await db.scalars(stmt)
        return list(result.all())

    async def get_by_id(self, db: AsyncSession, principal: Principal, client_id: int) -> Client | None:
        stmt = select(Client).where(
            Client.id == client_id,
            Client.organization_id == principal.organization_id,
        )
        if principal.role.lower() == "member":
            stmt = stmt.where(Client.user_id == principal.user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, db: AsyncSession, principal: Principal, data: dict[str, Any]) -> Client:
        name = (data.get("name") or "").strip()
        normalized_name = normalize_text(name)

        products_owned = data.get("products_owned", [])
        if isinstance(products_owned, list):
            products_owned_json = to_json(products_owned)
        else:
            products_owned_json = str(products_owned or "[]")

        products_interested = data.get("products_interested", [])
        if isinstance(products_interested, list):
            products_interested_json = to_json(products_interested)
        else:
            products_interested_json = str(products_interested or "[]")

        client = Client(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            name=name,
            normalized_name=normalized_name,
            products_owned_json=products_owned_json,
            products_interested_json=products_interested_json,
            rolling_summary=data.get("rolling_summary", ""),
            relationship_notes=data.get("relationship_notes", ""),
            email=data.get("email"),
            whatsapp_phone=data.get("whatsapp_phone"),
            is_active=data.get("is_active", True),
        )
        db.add(client)
        await db.flush()
        return client

    async def update(self, db: AsyncSession, principal: Principal, client_id: int, data: dict[str, Any]) -> Client | None:
        client = await self.get_by_id(db, principal, client_id)
        if not client:
            return None
        if "name" in data and data["name"] is not None:
            client.name = data["name"].strip()
            client.normalized_name = normalize_text(client.name)
        if "products_owned" in data:
            client.products_owned_json = to_json(data["products_owned"])
        if "products_owned_json" in data:
            client.products_owned_json = data["products_owned_json"]
        if "products_interested" in data:
            client.products_interested_json = to_json(data["products_interested"])
        if "products_interested_json" in data:
            client.products_interested_json = data["products_interested_json"]
        if "rolling_summary" in data:
            client.rolling_summary = data["rolling_summary"]
        if "relationship_notes" in data:
            client.relationship_notes = data["relationship_notes"]
        if "email" in data:
            client.email = data["email"]
        if "whatsapp_phone" in data:
            client.whatsapp_phone = data["whatsapp_phone"]
        if "is_active" in data:
            client.is_active = data["is_active"]
        db.add(client)
        await db.flush()
        return client

    async def delete(self, db: AsyncSession, principal: Principal, client_id: int) -> dict[str, Any] | None:
        client = await self.get_by_id(db, principal, client_id)
        if not client:
            return None

        meeting_ids = list(
            (await db.scalars(
                select(Meeting.id).where(
                    Meeting.client_id == client_id,
                    Meeting.organization_id == principal.organization_id,
                )
            )).all()
        )
        commitment_ids = list(
            (await db.scalars(
                select(Commitment.id).where(
                    Commitment.client_id == client_id,
                    Commitment.organization_id == principal.organization_id,
                )
            )).all()
        )

        if commitment_ids:
            await db.execute(
                delete(CommitmentMeetingLink).where(
                    CommitmentMeetingLink.commitment_id.in_(commitment_ids)
                )
            )
        if meeting_ids:
            await db.execute(
                delete(CommitmentMeetingLink).where(
                    CommitmentMeetingLink.meeting_id.in_(meeting_ids)
                )
            )
            await db.execute(
                delete(MeetingEvidence).where(
                    MeetingEvidence.meeting_id.in_(meeting_ids)
                )
            )
            await db.execute(
                delete(AIExtractionLog).where(
                    AIExtractionLog.meeting_id.in_(meeting_ids)
                )
            )

        await db.execute(
            delete(RiskSignal).where(
                RiskSignal.client_id == client_id,
                RiskSignal.organization_id == principal.organization_id,
            )
        )
        await db.execute(
            delete(FollowUpTask).where(
                FollowUpTask.client_id == client_id,
                FollowUpTask.organization_id == principal.organization_id,
            )
        )

        if meeting_ids:
            await db.execute(
                delete(Meeting).where(
                    Meeting.id.in_(meeting_ids),
                    Meeting.organization_id == principal.organization_id,
                )
            )
        if commitment_ids:
            await db.execute(
                delete(Commitment).where(
                    Commitment.id.in_(commitment_ids),
                    Commitment.organization_id == principal.organization_id,
                )
            )

        await db.delete(client)
        await db.flush()
        return {
            "status": "deleted",
            "client_id": client_id,
            "meetings_deleted": len(meeting_ids),
            "commitments_deleted": len(commitment_ids),
        }
