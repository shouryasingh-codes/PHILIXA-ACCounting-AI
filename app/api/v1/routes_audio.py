from __future__ import annotations

from datetime import date
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.arq import get_arq_pool
from app.core.config import get_settings
from app.core.dependencies import CurrentPrincipal
from app.database.session import get_db
from app.models.enums import MeetingSourceType, MeetingStatus
from app.models.meeting import Meeting
from app.repositories.meeting_repository import MeetingRepository
from app.services.minio_service import minio_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audio", tags=["Audio"])

ALLOWED_AUDIO_TYPES = ["audio/mpeg", "audio/mp4", "audio/x-m4a", "audio/wav", "audio/x-wav", "video/mp4"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB ceiling


@router.post("/upload")
async def upload_audio_meeting(
    principal: CurrentPrincipal,
    file: UploadFile = File(...),
    meeting_date: date = Form(...),
    known_client_id: int | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Upload an audio file (mp3, wav, m4a).
    Validates the file, pre-allocates a Meeting record, stores it in MinIO
    using tenant namespacing {org_id}/{user_id}/{meeting_id}/{filename},
    and enqueues an ARQ job for transcription.
    """
    # 1. Validation
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Unsupported file type: {file.content_type}. Please upload mp3, m4a, or wav.",
        )

    # Calculate file size
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File is too large. Maximum size is 10MB.",
        )

    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File is empty.",
        )

    # 2. Pre-allocate Meeting record in DB to obtain deterministic meeting.id
    try:
        new_meeting = Meeting(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            raw_notes="",
            summary="",
            meeting_date=meeting_date,
            source_type=MeetingSourceType.AUDIO_UPLOAD.value,
            status=MeetingStatus.QUEUED.value,
            client_identification_status="identified",
            client_identification_confidence=1.0,
        )
        db.add(new_meeting)
        await db.flush()
    except Exception as db_init_err:
        await db.rollback()
        logger.error(f"Database pre-allocation failed: {db_init_err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialize meeting record.",
        )

    # 3. Upload to MinIO with namespaced path
    try:
        object_name = minio_service.upload_audio_file(
            file_data=file.file,
            file_size=file_size,
            content_type=file.content_type,
            original_filename=file.filename,
            org_id=principal.organization_id,
            user_id=principal.user_id,
            meeting_id=new_meeting.id,
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"MinIO Upload failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload audio to storage.",
        )

    # 4. Commit meeting with audio object path
    try:
        new_meeting.audio_path = object_name
        await db.commit()
        await db.refresh(new_meeting)
    except Exception as e:
        await db.rollback()
        try:
            minio_service.delete_audio_file(object_name)
        except Exception:
            pass
        logger.error(f"Database insertion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save meeting record.",
        )

    # 5. Enqueue ARQ Background Job
    try:
        redis_pool = get_arq_pool()
        if not redis_pool:
            logger.warning("Redis pool not found. Job was not enqueued.")
            raise RuntimeError("Redis pool is not initialized.")

        await redis_pool.enqueue_job(
            "process_meeting_transcription",
            meeting_id=new_meeting.id,
            audio_file_path=object_name,
            known_client_id=known_client_id,
            organization_id=principal.organization_id,
            user_id=principal.user_id,
        )
        logger.info(f"Enqueued process_meeting_transcription job for meeting {new_meeting.id}")
    except Exception as e:
        logger.error(f"ARQ Enqueue failed: {e}")

        # Rollback: delete the newly created DB record
        try:
            await db.delete(new_meeting)
            await db.commit()
            logger.info(f"Rolled back database record for meeting {new_meeting.id}")
        except Exception as db_err:
            logger.error(f"Failed to rollback database record for meeting {new_meeting.id}: {db_err}")

        # Rollback: delete the MinIO uploaded file
        try:
            minio_service.delete_audio_file(object_name)
            logger.info(f"Rolled back MinIO object {object_name}")
        except Exception as minio_err:
            logger.error(f"Failed to rollback MinIO object {object_name}: {minio_err}")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue background processing.",
        )

    return {
        "message": "Audio uploaded successfully. Transcription queued.",
        "meeting_id": new_meeting.id,
        "status": new_meeting.status,
    }


@router.get("/{meeting_id}/url")
async def get_meeting_audio_url(
    meeting_id: int,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Generates a presigned MinIO audio URL scoped strictly to tenant and member ownership."""
    meeting_repo = MeetingRepository()
    meeting = await meeting_repo.get_by_id(db, principal, meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found or audio file inaccessible.",
        )

    audio_path = getattr(meeting, "audio_file_path", None) or getattr(meeting, "audio_path", None)
    if not audio_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found or audio file inaccessible.",
        )

    try:
        url = minio_service.get_presigned_url(audio_path)
    except Exception as exc:
        logger.warning(f"Could not generate presigned URL via MinIO client: {exc}")
        settings = get_settings()
        url = f"http://{settings.minio_url}/{minio_service.bucket_name}/{audio_path}"

    return {
        "url": url,
        "presigned_url": url,
        "audio_url": url,
        "meeting_id": meeting.id,
    }

