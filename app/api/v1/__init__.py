"""Version 1 API routes."""
from __future__ import annotations

from app.api.v1.routes_audio import router as audio_router
from app.api.v1.routes_auth import router as auth_router, ws_ticket_router
from app.api.v1.routes_clients import router as clients_router
from app.api.v1.routes_commitments import router as commitments_router
from app.api.v1.routes_dashboard import router as dashboard_router
from app.api.v1.routes_health import router as health_router
from app.api.v1.routes_jobs import router as jobs_router
from app.api.v1.routes_live import router as live_router
from app.api.v1.routes_meeting_notes import router as meeting_notes_router
from app.api.v1.routes_preferences import router as preferences_router
from app.api.v1.routes_vapi import router as vapi_router
from app.api.v1.routes_voice import router as voice_router
from app.api.v1.routes_webhooks import router as webhooks_router
from app.api.v1.routes_workspace import router as workspace_router

__all__ = [
    "audio_router",
    "auth_router",
    "clients_router",
    "commitments_router",
    "dashboard_router",
    "health_router",
    "jobs_router",
    "live_router",
    "meeting_notes_router",
    "preferences_router",
    "vapi_router",
    "voice_router",
    "webhooks_router",
    "workspace_router",
    "ws_ticket_router",
]
