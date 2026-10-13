"""
Day 12 (Accuracy Fix) + Day 13 (Robustness) + Milestone 4: Multi-Tenant WebSocket Live Route
Secured with short-lived (60s) single-use signed tickets and Redis replay protection.
Tenant-scoped client name prompt injection via ClientRepository.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import time
from typing import Any, List, Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal
from app.core.config import get_settings
from app.core.redis import get_redis_client
from app.core.security import decode_jwt_token, hash_token
from app.database.session import AsyncSessionLocal
from app.models.enums import MembershipStatus
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.models.user_session import UserSession
from app.repositories.client_repository import ClientRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/live", tags=["Live Transcription"])

SAMPLE_RATE = 16000
# Idle timeout: if no audio bytes received within this window, auto-stop.
IDLE_TIMEOUT_SECONDS = 120  # 2 minutes


async def _resolve_redis_client() -> Any:
    """Helper to safely obtain an active Redis client across runtime and test environments."""
    try:
        redis_obj = get_redis_client()
        if asyncio.iscoroutine(redis_obj):
            return await redis_obj
        return redis_obj
    except Exception as exc:
        logger.warning(f"Could not initialize Redis client for WS ticket check: {exc}")
        return None


async def _authenticate_ws_ticket(
    websocket: WebSocket,
    raw_ticket: Optional[str],
) -> Optional[tuple[dict[str, Any], Principal]]:
    """
    Validates the WebSocket ticket:
    1. Signature and expiration verification via decode_jwt_token
    2. Claim structure validation (sub, org_id, type)
    3. Redis single-use replay defense
    4. Database validation of User, Org, Membership, and Session status
    """
    if not raw_ticket:
        logger.warning("WebSocket connection rejected: missing ticket parameter.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing authentication ticket")
        return None

    # 1. Decode HS256 JWT
    try:
        payload = decode_jwt_token(raw_ticket)
    except JWTError as exc:
        logger.warning(f"WebSocket auth failed: Invalid or expired JWT - {exc}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired ticket")
        return None
    except Exception as exc:
        logger.error(f"WebSocket auth failed: Unexpected decode error - {exc}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication failed")
        return None

    # 2. Verify claims
    token_type = payload.get("type", "access")
    if token_type not in ("ws_ticket", "access"):
        logger.warning(f"WebSocket auth failed: Invalid token type '{token_type}'")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token type for WebSocket")
        return None

    user_id: Optional[str] = payload.get("sub")
    org_id: Optional[str] = payload.get("org_id")
    session_id: str = payload.get("sid", "")
    role: str = payload.get("role", "member")
    jti: str = payload.get("jti") or hash_token(raw_ticket)

    if not user_id or not org_id:
        logger.warning("WebSocket auth failed: Missing sub or org_id claims")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Incomplete ticket claims")
        return None

    # 3. Redis Replay Defense
    redis_client = await _resolve_redis_client()
    if redis_client:
        try:
            used_key = f"philixa:ws_ticket_used:{jti}"
            if await redis_client.exists(used_key):
                logger.warning(f"WebSocket replay attack detected for ticket jti={jti}")
                await websocket.close(
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="Ticket has already been redeemed (replay detected)",
                )
                return None

            # Mark ticket as used for 60s
            await redis_client.set(used_key, "1", ex=60)
            # Delete any pre-stored ticket keys
            await redis_client.delete(f"ws_ticket:{jti}", f"ticket_{jti}", raw_ticket)
        except Exception as redis_exc:
            logger.warning(f"Redis replay check error: {redis_exc}")

    # 4. Multi-Tenant Database Identity & Membership Validation
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if not user or not user.is_active:
            logger.warning(f"WebSocket rejected: user {user_id} inactive or not found")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="User is inactive")
            return None

        org = await db.get(Organization, org_id)
        if not org or not org.is_active:
            logger.warning(f"WebSocket rejected: org {org_id} inactive or not found")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Organization is inactive")
            return None

        membership_stmt = select(OrganizationMembership).where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == org_id,
        )
        membership = (await db.execute(membership_stmt)).scalar_one_or_none()
        if not membership or membership.status != MembershipStatus.ACTIVE.value:
            logger.warning(f"WebSocket rejected: user {user_id} has no active membership in org {org_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Inactive workspace membership")
            return None

        # Check session revocation if session_id is provided
        if session_id:
            user_session = await db.get(UserSession, session_id)
            if user_session and user_session.revoked_at is not None:
                logger.warning(f"WebSocket rejected: session {session_id} has been revoked")
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Session has been revoked")
                return None

        principal = Principal(
            user=user,
            organization=org,
            role=membership.role,
            session_id=session_id,
        )

    return payload, principal


@router.websocket("/transcribe")
async def live_transcribe(
    websocket: WebSocket,
    ticket: Optional[str] = Query(default=None),
    token: Optional[str] = Query(default=None),
    api_key: Optional[str] = Query(default=None),
    sample_rate: int = Query(default=16000),
    diarize: bool = Query(default=False),
) -> None:
    """
    Live audio collection WebSocket endpoint.
    Authenticated via short-lived (60s) single-use WebSocket ticket.
    Browser sends raw Int16 PCM chunks -> buffer silently collects audio.
    On 'stop' action: audio -> WAV -> Whisper / Deepgram -> transcript.
    """
    raw_ticket = ticket or token or api_key
    auth_result = await _authenticate_ws_ticket(websocket, raw_ticket)
    if auth_result is None:
        return

    payload, principal = auth_result
    settings = get_settings()

    await websocket.accept()
    logger.info(
        f"Live WebSocket authenticated and connected for user={principal.user_id}, "
        f"org={principal.organization_id}, role={principal.role}. Sample rate: {sample_rate}Hz"
    )

    try:

        # Fetch tenant-scoped client names for Whisper prompt injection
        client_names: List[str] = []
        async with AsyncSessionLocal() as db:
            client_repo = ClientRepository()
            clients = await client_repo.list(db, principal)
            client_names = [c.name for c in clients if c.name]
        logger.info(f"Loaded {len(client_names)} tenant-scoped client names for prompt injection (org={principal.organization_id}).")

    except Exception as setup_exc:
        logger.error(f"[VOICE SETUP ERROR] user={principal.user_id}: {setup_exc!r}", exc_info=True)
        try:
            await websocket.send_json({"action": "error", "error": f"Setup failed: {setup_exc}"})
        except Exception:
            pass
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    # Initialize Strategy based on configuration
    from app.services.live_strategies import LocalTranscriptionSession, DeepgramTranscriptionSession

    session = None
    try:
        if settings.transcription_mode == "cloud" and settings.deepgram_api_key:
            logger.info("Using Deepgram Cloud Transcription Strategy")
            session = DeepgramTranscriptionSession(
                api_key=settings.deepgram_api_key,
                sample_rate=sample_rate,
                diarize=diarize,
            )
            await session.initialize()
        else:
            logger.info("Using Local Whisper Transcription Strategy")
            session = LocalTranscriptionSession(
                client_names=client_names,
                sample_rate=sample_rate,
                diarize=diarize,
            )
            await session.initialize()
    except Exception as init_exc:
        logger.error(f"Transcription session init FAILED for user={principal.user_id}: {init_exc!r}", exc_info=True)
        try:
            await websocket.send_json({
                "action": "error",
                "error": f"Voice service unavailable: {str(init_exc)}. Please try again.",
            })
        except Exception:
            pass
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    total_bytes_received = 0
    finalized = False
    last_audio_time = time.monotonic()  # Track last audio activity for idle timeout

    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive(),
                    timeout=IDLE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Live WebSocket idle timeout ({IDLE_TIMEOUT_SECONDS}s) for user={principal.user_id}. "
                    "Auto-stopping session."
                )
                if not finalized:
                    finalized = True
                    await websocket.send_json({
                        "action": "timeout",
                        "error": f"No audio detected for {IDLE_TIMEOUT_SECONDS // 60} minute(s). Recording auto-stopped.",
                        "is_final": True,
                    })
                break

            if "bytes" in message:
                chunk = message["bytes"]
                total_bytes_received += len(chunk)
                last_audio_time = time.monotonic()  # Reset idle timer on each audio chunk
                await session.add_chunk(chunk)

            elif "text" in message:
                text_data = json.loads(message["text"])

                if text_data.get("action") == "stop" and not finalized:
                    finalized = True
                    logger.info("Stop signal received. Starting full-audio transcription...")

                    min_duration_seconds = 1.0
                    actual_duration = (total_bytes_received / 2) / sample_rate
                    if actual_duration < min_duration_seconds:
                        logger.warning(f"Audio too short ({actual_duration:.1f}s) — skipping transcription.")
                        await websocket.send_json({
                            "action": "stopped",
                            "confirmed": "",
                            "is_final": True,
                            "error": f"Recording too short ({actual_duration:.1f}s). Minimum 1 second required.",
                        })
                        break

                    await websocket.send_json({"action": "processing"})

                    try:
                        transcript = await session.finish()
                        logger.info(f"Transcription complete: {len(transcript)} chars")
                    except Exception as exc:
                        logger.error(f"Transcription error: {exc}")
                        transcript = ""

                    await websocket.send_json({
                        "action": "stopped",
                        "confirmed": transcript.strip(),
                        "is_final": True,
                    })
                    break

    except WebSocketDisconnect:
        logger.info(f"Live WebSocket disconnected cleanly for user={principal.user_id}.")
    except Exception as exc:
        logger.error(f"WebSocket unexpected error: {exc}")
    finally:
        try:
            await session.close()
        except Exception:
            logger.warning("Transcription session cleanup failed")
        duration = (total_bytes_received / 2) / sample_rate if total_bytes_received else 0
        logger.info(f"Live session ended for user={principal.user_id}. Total audio collected: {duration:.1f}s")
