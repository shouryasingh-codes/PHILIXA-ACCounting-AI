from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentPrincipal
from app.database.session import get_db
from app.repositories.commitment_repository import CommitmentRepository
from app.schemas.commitment import (
    CommitmentListResponse,
    CommitmentStatusUpdateRequest,
    CommitmentStatusUpdateResponse,
)

router = APIRouter(
    prefix="/commitments",
    tags=["commitments"],
)


@router.get("", response_model=CommitmentListResponse)
async def list_commitments(
    principal: CurrentPrincipal,
    scope: str = "team",
    status_filter: str | None = Query(default=None, alias="status"),
    client_id: int | None = None,
    due_before: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    commitments = await CommitmentRepository().list(
        db,
        principal,
        scope=scope,
        status=status_filter,
        client_id=client_id,
        due_before=due_before,
    )
    return {"commitments": commitments}


@router.patch("/{commitment_id}/status", response_model=CommitmentStatusUpdateResponse)
async def update_commitment_status(
    commitment_id: int,
    request: CommitmentStatusUpdateRequest,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> dict:
    commitment = await CommitmentRepository().update_status(
        db,
        principal,
        commitment_id,
        request.status,
    )
    if not commitment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commitment not found.",
        )
    await db.commit()
    return {"commitment": commitment}
