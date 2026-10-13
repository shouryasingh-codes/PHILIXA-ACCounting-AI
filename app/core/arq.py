from typing import Optional
import logging

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Global ARQ Redis pool instance
arq_pool: Optional[ArqRedis] = None

async def init_arq_pool() -> None:
    """Initialize the ARQ Redis connection pool for background jobs."""
    global arq_pool
    try:
        settings = get_settings()
        redis_settings = RedisSettings.from_dsn(settings.redis_url)
        arq_pool = await create_pool(redis_settings)
        logger.info("ARQ Redis pool initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize ARQ Redis pool: {e}")
        raise

async def close_arq_pool() -> None:
    """Close the ARQ Redis connection pool gracefully."""
    global arq_pool
    if arq_pool is not None:
        await arq_pool.close()
        arq_pool = None
        logger.info("ARQ Redis pool closed safely.")

def get_arq_pool() -> Optional[ArqRedis]:
    global arq_pool
    return arq_pool
 