from sqlalchemy.ext.asyncio import AsyncSession
import logging
from typing import Any, Dict

from arq.connections import RedisSettings
from arq.worker import Worker

from app.core.config import get_settings
from app.core.redis import init_redis_pool, close_redis_pool
from app.database.session import AsyncSessionLocal, async_engine

logger = logging.getLogger(__name__)

async def startup(ctx: Dict[str, Any]) -> None:
    logger.info("Initializing worker startup hooks...")
    # Initialize Redis connection pool for app usage
    await init_redis_pool()
    
    # Store DB session factory in context for tasks to use
    ctx["db_session_factory"] = AsyncSessionLocal
    
    settings = get_settings()
    # Preload Whisper based on the feature flag.
    # If AUDIO UPLOADS are disabled, we don't need Whisper in the worker, saving ~2GB RAM.
    if settings.enable_audio_upload:
        logger.info("Preloading Whisper + PyAnnote model into worker RAM...")
        from app.services.transcription_service import transcription_service  # noqa: F401
        logger.info("Whisper model ready. Audio file uploads will be served instantly.")
    else:
        logger.info("Audio Upload disabled. Skipping Whisper preload (Saved ~2GB RAM!).")
    
    logger.info("Worker startup complete.")

async def shutdown(ctx: Dict[str, Any]) -> None:
    logger.info("Running worker shutdown hooks...")
    # Clean up Redis pool
    await close_redis_pool()
    
    # Dispose of the database engine
    await async_engine.dispose()
    logger.info("Worker shutdown complete.")

def get_redis_settings() -> RedisSettings:
    settings = get_settings()
    return RedisSettings.from_dsn(settings.redis_url)

from arq.cron import cron
from app.jobs.notification_jobs import send_client_followups, send_pre_interaction_briefs, retry_failed_notifications
from scripts.cleanup_demo_accounts import cleanup_demo_accounts

from app.jobs.embedding_jobs import generate_meeting_embeddings
from app.jobs.transcription_jobs import process_meeting_transcription

class WorkerSettings:
    """
    ARQ Worker settings.
    Run the worker using: `arq app.worker.WorkerSettings`
    """
    functions = [generate_meeting_embeddings, process_meeting_transcription]  # Register background task functions here
    cron_jobs = [
        # Hourly disk cleanup: delete expired demo guest accounts at minute 0 of every hour
        cron(cleanup_demo_accounts, hour=None, minute=0),
        # Example: run every day at 08:00 UTC
        cron(send_client_followups, hour=8, minute=0),
        cron(send_pre_interaction_briefs, hour=7, minute=0),
        # Run every 15 minutes to retry failed/stuck notifications
        cron(retry_failed_notifications, minute={0, 15, 30, 45})
    ]
    redis_settings = get_redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    allow_abort_jobs = True
    max_jobs = 10
