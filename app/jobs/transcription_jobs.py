from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from arq import Retry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_notification_adapter
from app.models.client import Client
from app.models.enums import MeetingStatus
from app.models.meeting import Meeting
from app.models.notification import NotificationPreference
from app.services.minio_service import minio_service
from app.services.notification_service import NotificationService
from app.services.transcription_service import transcription_service

logger = logging.getLogger(__name__)


async def _notify_meeting_processed(
    db: AsyncSession,
    meeting_id: int,
    client_name: str | None,
    success: bool,
    organization_id: str = "default",
    user_id: str | None = None,
) -> None:
    """
    Sends email/WhatsApp notification to user after meeting is processed.
    Handles both success and failure cases.
    """
    try:
        stmt = select(NotificationPreference).where(
            NotificationPreference.organization_id == organization_id,
        )
        if user_id:
            stmt = stmt.where(NotificationPreference.user_id == user_id)
        pref = await db.scalar(stmt)
        if not pref or not pref.is_opted_in or not pref.whatsapp_number:
            logger.info(
                "No notification preference found or opted-out — skipping meeting processed notification."
            )
            return

        if success:
            client_part = f" Client: {client_name}." if client_name else ""
            message = (
                f"✅ Philixa: Aapki audio meeting (ID #{meeting_id}) successfully process ho gayi!{client_part} "
                f"Summary, commitments aur follow-up tasks ready hain. Dashboard pe check karein."
            )
        else:
            message = (
                f"⚠️ Philixa: Meeting (ID #{meeting_id}) process nahi ho saki — manual review required hai. "
                f"Audio mein koi issue ho sakta hai ya AI extraction fail hua. Dashboard pe dekhe."
            )

        idempotency_key = f"meeting_processed_{meeting_id}_{'ok' if success else 'fail'}"
        adapter = get_notification_adapter()
        svc = NotificationService(db, adapter)
        await svc.dispatch_notification(
            preference_id=pref.id,
            message_content=message,
            idempotency_key=idempotency_key,
            organization_id=organization_id,
            user_id=user_id,
        )
        logger.info(f"Meeting processed notification sent for meeting {meeting_id}.")
    except Exception as e:
        logger.warning(f"Failed to send meeting processed notification: {e}")


async def process_meeting_transcription(
    ctx: dict,
    meeting_id: int,
    audio_file_path: str,
    known_client_id: int | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> bool:
    """
    ARQ Background job to transcribe audio for a meeting.
    Runs Whisper/WhisperX on the provided audio_file_path.
    """
    job_try = ctx.get("job_try", 1)
    max_tries = ctx.get("max_tries", 3)

    logger.info(f"Starting transcription for meeting {meeting_id}, file: {audio_file_path}, try {job_try}/{max_tries}")

    SessionLocal = ctx.get("db_session_factory")
    if not SessionLocal:
        logger.error("db_session_factory not found in context")
        return False

    async with SessionLocal() as db:
        stmt = select(Meeting).where(Meeting.id == meeting_id)
        if organization_id:
            stmt = stmt.where(Meeting.organization_id == organization_id)
        result = await db.execute(stmt)
        meeting = result.scalar_one_or_none()

        if not meeting:
            logger.error(f"Meeting {meeting_id} not found")
            return False

        effective_org_id = organization_id or meeting.organization_id
        effective_user_id = user_id or meeting.user_id

        # --- Step A: Transient (DB + MinIO) ---
        try:
            meeting.status = MeetingStatus.TRANSCRIBING.value
            await db.commit()

            logger.info(f"Downloading audio from MinIO: {audio_file_path}")

            suffix = os.path.splitext(audio_file_path)[1]
            if not suffix:
                suffix = ".mp3"

            # Removed lazy import

            # Fetch known client names scoped to this org to avoid hallucinations
            client_stmt = select(Client.name)
            if effective_org_id:
                client_stmt = client_stmt.where(Client.organization_id == effective_org_id)
            _names_result = await db.scalars(client_stmt)
            client_names = [n for n in _names_result.all() if n]

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_audio_file:
                temp_file_path = temp_audio_file.name
                response = minio_service.get_audio_file_stream(audio_file_path)
                try:
                    for d in response.stream(32 * 1024):
                        temp_audio_file.write(d)
                finally:
                    response.close()
                    response.release_conn()

        except Exception as net_err:
            logger.error(f"Transient error for meeting {meeting_id}: {str(net_err)}")
            await db.rollback()
            if job_try < max_tries:
                raise Retry(defer=60)

            stmt = select(Meeting).where(Meeting.id == meeting_id)
            result = await db.execute(stmt)
            meeting = result.scalar_one_or_none()
            if meeting:
                meeting.status = MeetingStatus.MANUAL_REVIEW_REQUIRED.value
                meeting.raw_notes = (meeting.raw_notes or "") + f"\n[Transient Error]: {str(net_err)}"
                await db.commit()
            return False

        # --- Step B: ML Permanent (Transcribe + Process) ---
        try:
            try:
                logger.info(f"Passing {temp_file_path} to TranscriptionService")
                transcript_text = await asyncio.to_thread(
                    transcription_service.transcribe_audio,
                    temp_file_path,
                    client_names,
                )
            finally:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                    logger.info(f"Deleted temp file {temp_file_path}")

            if not transcript_text:
                logger.warning("Transcription resulted in empty text.")
                meeting.raw_notes = "[No audible speech detected]"
                meeting.status = MeetingStatus.MANUAL_REVIEW_REQUIRED.value
                meeting.client_identification_status = "unknown"
                meeting.client_identification_confidence = 0.0
                await db.commit()
                logger.warning("Meeting %d needs review because no usable speech was transcribed.", meeting_id)
                if effective_org_id and effective_user_id:
                    await _notify_meeting_processed(
                        db, meeting_id, client_name=None, success=False, organization_id=effective_org_id, user_id=effective_user_id
                    )
                return False

            meeting.raw_notes = transcript_text
            await db.commit()

            logger.info(f"Triggering pipeline for {meeting_id}. raw_notes: {meeting.raw_notes}")

            from app.services.meeting_processing_service import MeetingProcessingService
            svc = MeetingProcessingService()
            result = await svc.process_existing_meeting(db, meeting, known_client_id=known_client_id)

            client_name = None
            if result and result.get("client_id"):
                client_obj = await db.get(Client, result["client_id"])
                client_name = client_obj.name if client_obj else None

            if effective_org_id and effective_user_id:
                await _notify_meeting_processed(
                    db, meeting_id, client_name=client_name, success=True, organization_id=effective_org_id, user_id=effective_user_id
                )

            logger.info(f"Successfully transcribed and processed meeting {meeting_id}")
            return True

        except Exception as ml_err:
            logger.error(f"ML / Processing error for meeting {meeting_id}: {str(ml_err)}")
            await db.rollback()
            stmt = select(Meeting).where(Meeting.id == meeting_id)
            result = await db.execute(stmt)
            meeting = result.scalar_one_or_none()
            if meeting:
                meeting.status = MeetingStatus.MANUAL_REVIEW_REQUIRED.value
                meeting.raw_notes = (meeting.raw_notes or "") + f"\n[ML/Processing Error]: {str(ml_err)}"
                await db.commit()

            await _notify_meeting_processed(
                db, meeting_id, client_name=None, success=False, organization_id=effective_org_id or "default", user_id=effective_user_id
            )
            return False

        finally:
            from app.core.config import get_settings
            settings = get_settings()
            if not settings.retain_audio_files and audio_file_path:
                logger.info(f"Audio retention disabled. Cleaning up MinIO file {audio_file_path}.")
                try:
                    minio_service.delete_audio_file(audio_file_path)

                    stmt = select(Meeting).where(Meeting.id == meeting_id)
                    result = await db.execute(stmt)
                    m = result.scalar_one_or_none()
                    if m and m.audio_path:
                        m.audio_path = None
                        await db.commit()
                except Exception as e:
                    logger.error(f"Failed to cleanup audio file {audio_file_path}: {e}")
