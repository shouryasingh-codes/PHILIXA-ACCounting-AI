from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.database.session import AsyncSessionLocal

from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str
    app_version: str
    database: str
    enable_audio_upload: bool

router = APIRouter(tags=["health"])

@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    database_status = "ok"
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        database_status = "error"
    return HealthResponse(
        status="ok" if database_status == "ok" else "degraded",
        app_version=settings.app_version,
        database=database_status,
        enable_audio_upload=settings.enable_audio_upload,
    )
