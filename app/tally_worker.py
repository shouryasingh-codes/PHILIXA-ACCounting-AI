"""Dedicated worker: no reminder cron, embeddings, transcription or model preload."""
from arq.connections import RedisSettings
from arq.cron import cron
from app.core.config import get_settings
from app.core.redis import init_redis_pool, close_redis_pool
from app.services.tally_sync import sync_tick

async def startup(ctx): await init_redis_pool()
async def shutdown(ctx):
    from app.database.session import async_engine
    await close_redis_pool()
    await async_engine.dispose()

class WorkerSettings:
    queue_name='philixa:tally:worker'
    functions=[sync_tick]
    cron_jobs=[cron(sync_tick,second={0,15,30,45},unique=True)]
    redis_settings=RedisSettings.from_dsn(get_settings().redis_url)
    on_startup=startup
    on_shutdown=shutdown
    max_jobs=1
    job_timeout=600
