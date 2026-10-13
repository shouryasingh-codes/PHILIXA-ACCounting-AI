from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.client import Client
from app.utils.text_normalization import normalize_text, similarity


class ClientIdentificationService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def resolve_client(
        self,
        db: AsyncSession,
        suggested_name: str | None,
        confidence: float,
        known_client_id: int | None = None,
        organization_id: str | None = None,
    ) -> tuple[Client | None, str, list[str]]:
        warnings: list[str] = []
        if known_client_id:
            stmt = select(Client).where(Client.id == known_client_id)
            if organization_id:
                stmt = stmt.where(Client.organization_id == organization_id)
            client = (await db.execute(stmt)).scalar_one_or_none()
            if not client:
                warnings.append("Known client id was not found.")
                return None, "client_identification_required", warnings
            return client, "identified", warnings

        if not suggested_name:
            warnings.append("Client identification required.")
            return None, "client_identification_required", warnings

        normalized = normalize_text(suggested_name)
        stmt = select(Client)
        if organization_id:
            stmt = stmt.where(Client.organization_id == organization_id)
        clients = list((await db.scalars(stmt)).all())
        exact = [client for client in clients if client.normalized_name == normalized]
        if exact and confidence >= self.settings.client_auto_match_threshold:
            return exact[0], "identified", warnings

        close_matches = [
            client
            for client in clients
            if similarity(client.normalized_name, normalized) >= self.settings.client_auto_match_threshold
        ]
        if len(close_matches) == 1 and confidence >= self.settings.client_auto_match_threshold:
            return close_matches[0], "identified", warnings
        if len(close_matches) > 1:
            warnings.append("Multiple similar clients found; confirmation required.")
            return None, "client_identification_required", warnings

        # We intentionally do not auto-create clients anymore so that the user 
        # is always prompted with the confirmation popup (where the suggested name 
        # is auto-filled) to manually confirm the creation of a new client.
        warnings.append("New client identified; confirmation required.")
        return None, "client_identification_required", warnings
