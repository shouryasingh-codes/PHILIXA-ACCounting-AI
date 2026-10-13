import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.arq import close_arq_pool, init_arq_pool
from app.core.config import get_settings, validate_production_settings
from app.database.session import async_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()

    # Production safety guardrail validation
    if settings.app_env.lower() in ("production", "prod"):
        violations = validate_production_settings(settings)
        if violations:
            logger.error(f"Production startup validation failed: {violations}")
            raise RuntimeError(f"Production startup validation failed: {'; '.join(violations)}")

    if settings.skip_startup_checks:
        logger.info("Startup checks skipped (PHILIXA_SKIP_STARTUP_CHECKS=1).")
        yield
        return

    # 1. Ping PostgreSQL
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Connected to PostgreSQL successfully.")
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
        raise

    # 2. Ping Redis
    try:
        redis_client = Redis.from_url(settings.redis_url)
        await redis_client.ping()
        await redis_client.aclose()
        logger.info("Connected to Redis successfully.")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise

    # 3. MinIO (Stub for Day 9)
    logger.info("MinIO check stubbed (will be implemented on Day 9).")

    # 4. Initialize ARQ Redis Pool
    await init_arq_pool()

    # 5. Preload Embedding Model in background to prevent first-request cold start
    from app.services.embedding_service import get_embedding_model
    asyncio.create_task(asyncio.to_thread(get_embedding_model))
    logger.info("Triggered embedding model preload in background.")

    # 6. Preload Whisper + PyAnnote (TranscriptionService) in background.
    if settings.transcription_mode == "local":
        def _preload_transcription():
            from app.services.transcription_service import transcription_service  # noqa: F401
            logger.info("TranscriptionService (Whisper + PyAnnote) preloaded into RAM.")
        asyncio.create_task(asyncio.to_thread(_preload_transcription))
        logger.info("Triggered TranscriptionService preload in background.")
    else:
        logger.info(f"Skipping TranscriptionService preload because mode is {settings.transcription_mode}. Saved ~4GB RAM!")

    logger.info("Pre-Flight Checks Passed. App is ready to serve.")

    yield

    # Shutdown Sequence
    await close_arq_pool()
    await async_engine.dispose()
    logger.info("PostgreSQL engine disposed safely.")
