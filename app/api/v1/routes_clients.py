from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentPrincipal, Principal
from app.database.session import get_db
from app.models.client import Client
from app.models.commitment import Commitment
from app.models.meeting import Meeting
from app.repositories.client_repository import ClientRepository
from app.repositories.meeting_repository import MeetingRepository
from app.schemas.ask_client import AskClientRequest, AskClientResponse
from app.schemas.client import ClientCreateRequest, ClientListItem, ClientMemoryResponse, ClientResponse, MeetingRead, CommunicationLogRead
from app.services.ask_client_service import AskClientService
from app.services.json_utils import from_json
from app.services.meeting_processing_service import meeting_to_dict
from app.services.memory_service import MemoryService

router = APIRouter(
    prefix="/clients",
    tags=["clients"],
)


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: dict[str, Any],
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> dict:
    client_repo = ClientRepository()
    client = await client_repo.create(db, principal, payload)
    await db.commit()
    await db.refresh(client)
    return {
        "id": client.id,
        "name": client.name,
        "organization_id": client.organization_id,
        "user_id": client.user_id,
        "products_owned": from_json(client.products_owned_json, []),
        "products_interested": from_json(client.products_interested_json, []),
        "rolling_summary": client.rolling_summary,
        "relationship_notes": client.relationship_notes,
        "email": client.email,
        "whatsapp_phone": client.whatsapp_phone,
        "is_active": client.is_active,
        "created_at": client.created_at,
        "updated_at": client.updated_at,
    }


@router.get("", response_model=list[ClientListItem])
async def list_clients(
    principal: CurrentPrincipal,
    scope: str = "team",
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    client_repo = ClientRepository()
    clients = await client_repo.list(db, principal, scope=scope)
    rows = []
    for client in clients:
        pending_stmt = select(func.count(Commitment.id)).where(
            Commitment.client_id == client.id,
            Commitment.organization_id == principal.organization_id,
            Commitment.status == "pending",
        )
        if principal.role.lower() == "member":
            pending_stmt = pending_stmt.where(Commitment.user_id == principal.user_id)
        pending_count = await db.scalar(pending_stmt)

        meeting_stmt = (
            select(Meeting)
            .where(
                Meeting.client_id == client.id,
                Meeting.organization_id == principal.organization_id,
            )
        )
        if principal.role.lower() == "member":
            meeting_stmt = meeting_stmt.where(Meeting.user_id == principal.user_id)
        meeting_stmt = meeting_stmt.order_by(Meeting.meeting_date.desc(), Meeting.created_at.desc()).limit(1)
        last_meeting = await db.scalar(meeting_stmt)

        rows.append(
            {
                "id": client.id,
                "name": client.name,
                "products_owned": from_json(client.products_owned_json, []),
                "products_interested": from_json(client.products_interested_json, []),
                "rolling_summary": client.rolling_summary,
                "pending_commitments_count": int(pending_count or 0),
                "last_meeting_summary": last_meeting.summary if last_meeting else None,
                "created_at": client.created_at,
                "updated_at": client.updated_at,
                "owner_email": client.user.email if client.user else None,
            }
        )
    return rows


@router.get("/{client_id}")
async def get_client(
    client_id: int,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> dict:
    client_repo = ClientRepository()
    client = await client_repo.get_by_id(db, principal, client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")
    return {
        "id": client.id,
        "name": client.name,
        "organization_id": client.organization_id,
        "user_id": client.user_id,
        "products_owned": from_json(client.products_owned_json, []),
        "products_interested": from_json(client.products_interested_json, []),
        "rolling_summary": client.rolling_summary,
        "relationship_notes": client.relationship_notes,
        "email": client.email,
        "whatsapp_phone": client.whatsapp_phone,
        "is_active": client.is_active,
        "created_at": client.created_at,
        "updated_at": client.updated_at,
    }


@router.put("/{client_id}")
async def update_client(
    client_id: int,
    payload: dict[str, Any],
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> dict:
    client_repo = ClientRepository()
    client = await client_repo.update(db, principal, client_id, payload)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")
    await db.commit()
    await db.refresh(client)
    return {
        "id": client.id,
        "name": client.name,
        "organization_id": client.organization_id,
        "user_id": client.user_id,
        "products_owned": from_json(client.products_owned_json, []),
        "products_interested": from_json(client.products_interested_json, []),
        "rolling_summary": client.rolling_summary,
        "relationship_notes": client.relationship_notes,
        "email": client.email,
        "whatsapp_phone": client.whatsapp_phone,
        "is_active": client.is_active,
        "created_at": client.created_at,
        "updated_at": client.updated_at,
    }


@router.get("/{client_id}/memory", response_model=ClientMemoryResponse)
async def get_client_memory(
    client_id: int,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await MemoryService().get_client_memory(db, client_id, principal=principal)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{client_id}/ask", response_model=AskClientResponse)
async def ask_client(
    client_id: int,
    request: AskClientRequest,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await AskClientService().ask(db, client_id, request.query, principal=principal)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{client_id}/meetings", response_model=list[MeetingRead])
async def get_client_meetings(
    client_id: int,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    client = await ClientRepository().get_by_id(db, principal, client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")
    meetings = await MeetingRepository().list(db, principal, client_id=client_id)
    return [meeting_to_dict(meeting) for meeting in meetings]


@router.get("/{client_id}/communications", response_model=list[CommunicationLogRead])
async def get_client_communications(
    client_id: int,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    client = await ClientRepository().get_by_id(db, principal, client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")
    
    from app.repositories.communication_repository import CommunicationRepository
    logs = await CommunicationRepository().list_by_client_id(db, principal, client_id)
    return [
        {
            "id": log.id,
            "client_id": log.client_id,
            "channel": log.channel.value,
            "message_content": log.message_content,
            "status": log.status.value,
            "error_message": log.error_message,
            "created_at": log.created_at,
        }
        for log in logs
    ]

@router.delete("/{client_id}")
async def delete_client(
    client_id: int,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> dict:
    deleted = await ClientRepository().delete(db, principal, client_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")
    await db.commit()
    return deleted if isinstance(deleted, dict) else {"status": "deleted", "client_id": client_id}
