from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import AIExtractionError
from app.core.arq import get_arq_pool
from app.core.dependencies import CurrentPrincipal
from app.core.rate_limit import limiter
from app.database.session import get_db
from app.models.commitment import Commitment, CommitmentMeetingLink
from app.models.enums import MeetingStatus
from app.models.meeting import Meeting
from app.repositories.meeting_repository import MeetingRepository
from app.schemas.meeting_note import (
    ClientConfirmationRequest,
    ClientConfirmationResponse,
    MeetingNoteProcessRequest,
    MeetingNoteProcessResponse,
)
from app.services.json_utils import from_json
from app.services.meeting_processing_service import MeetingProcessingService


class TranscriptUpdate(BaseModel):
    raw_notes: str = Field(..., description="The corrected meeting transcript")


router = APIRouter(
    prefix="/meeting-notes",
    tags=["meeting notes"],
)


@router.post("/process", response_model=MeetingNoteProcessResponse)
@limiter.limit("10/minute")
async def process_meeting_note(
    request: Request,
    body: Annotated[
        MeetingNoteProcessRequest,
        Body(
            openapi_examples={
                "clear_client": {
                    "summary": "Clear client with due dates",
                    "value": {
                        "raw_notes": "Met Rajesh Sharma today. Interested in business loan. Concerned about processing time. Promised documents by Friday. Asked for approval status update in 3 days.",
                        "meeting_date": "2026-06-19",
                    },
                },
                "ambiguous_client": {
                    "summary": "Ambiguous client requiring confirmation",
                    "value": {
                        "raw_notes": "Customer interested in home loan. Wants callback Friday.",
                        "meeting_date": "2026-06-19",
                    },
                },
            }
        ),
    ],
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if principal.user.email.startswith("demo_guest_"):
        meeting_count = await db.scalar(select(func.count(Meeting.id)).where(Meeting.user_id == principal.user_id))
        if meeting_count >= 2:
            raise HTTPException(
                status_code=403,
                detail="Demo limit reached (Max 2 meetings). Please create a free Philixa account to continue!"
            )
            
    try:
        return await MeetingProcessingService().process_notes(db, body, principal=principal)
    except AIExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post("/{meeting_id}/confirm-client", response_model=ClientConfirmationResponse)
async def confirm_client(
    meeting_id: int,
    request: Annotated[
        ClientConfirmationRequest,
        Body(
            openapi_examples={
                "select_existing_client": {
                    "summary": "Attach to an existing client",
                    "value": {"client_id": 1},
                },
                "create_new_client": {
                    "summary": "Create a new client from unresolved meeting",
                    "value": {"new_client_name": "Amit Verma"},
                },
            }
        ),
    ],
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await MeetingProcessingService().confirm_client(
            db,
            meeting_id=meeting_id,
            client_id=request.client_id,
            new_client_name=request.new_client_name,
            new_client_email=request.new_client_email,
            new_client_whatsapp_phone=request.new_client_whatsapp_phone,
            principal=principal,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found.")
    return result


@router.patch("/{meeting_id}/transcript", response_model=dict)
async def update_transcript(
    meeting_id: int,
    request: TranscriptUpdate,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> dict:
    meeting = await MeetingRepository().get_by_id(db, principal, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found.")

    meeting.raw_notes = request.raw_notes
    meeting.status = MeetingStatus.PROCESSING.value
    await db.commit()

    pool = get_arq_pool()
    if pool:
        await pool.enqueue_job(
            "generate_meeting_embeddings",
            meeting.id,
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            _job_id=f"generate_meeting_embeddings_{meeting.id}",
        )

    return {"message": "Transcript updated successfully. Reprocessing queued.", "meeting_id": meeting.id}


@router.get("/{meeting_id}", response_model=dict)
async def get_meeting(
    meeting_id: int,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> dict:
    meeting = await MeetingRepository().get_by_id(db, principal, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found.")

    commitments_result = await db.execute(
        select(Commitment)
        .join(
            CommitmentMeetingLink,
            CommitmentMeetingLink.commitment_id == Commitment.id,
        )
        .where(CommitmentMeetingLink.meeting_id == meeting.id)
    )
    commitments = commitments_result.scalars().all()

    return {
        "id": meeting.id,
        "status": meeting.status,
        "client_id": meeting.client_id,
        "client_identification_status": meeting.client_identification_status,
        "suggested_name": getattr(meeting, "suggested_client_name", "") or "",
        "suggested_email": getattr(meeting, "suggested_client_email", "") or "",
        "suggested_whatsapp_phone": getattr(meeting, "suggested_client_whatsapp_phone", "") or "",
        "summary": meeting.summary,
        "key_discussion_points": from_json(meeting.key_discussion_points_json, []),
        "concerns": from_json(meeting.concerns_json, []),
        "commitments": [
            {
                "id": commitment.id,
                "description": commitment.description,
                "owner": commitment.owner,
                "due_date": commitment.due_date.isoformat() if commitment.due_date else None,
                "due_date_text": commitment.due_date_text,
                "urgency_level": commitment.urgency_level,
                "status": commitment.status,
                "extraction_confidence": commitment.extraction_confidence,
            }
            for commitment in commitments
        ],
    }
