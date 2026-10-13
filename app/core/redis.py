from typing import AsyncGenerator
from redis.asyncio import Redis, ConnectionPool
from app.core.config import get_settings

pool: ConnectionPool | None = None

async def init_redis_pool():
    global pool
    settings = get_settings()
    pool = ConnectionPool.from_url(
        settings.redis_url,
        decode_responses=True
    )

async def close_redis_pool():
    global pool
    if pool is not None:
        await pool.disconnect()
        pool = None

async def get_redis_client() -> Redis:
    global pool
    if pool is None:
        await init_redis_pool()
    return Redis(connection_pool=pool)


async def get_redis() -> AsyncGenerator[Redis, None]:
    global pool
    if pool is None:
        await init_redis_pool()
    
    redis_client = Redis(connection_pool=pool)
    try:
        yield redis_client
    finally:
        await redis_client.close()
