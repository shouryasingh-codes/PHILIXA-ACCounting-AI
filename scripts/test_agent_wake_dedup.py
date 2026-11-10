"""Atomic wake deduplication in an isolated Redis test queue. No jobs execute."""
import asyncio,secrets,unittest
from arq.connections import create_pool,RedisSettings
from arq.constants import job_key_prefix
from app.core.config import get_settings
from app.services.task_agent_service import wake_job_id

class WakeDedup(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_wakes_one_job_per_revision(self):
        redis=await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        ident=secrets.token_hex(16);queue='philixa:test:agent-wake:'+ident
        keys=[job_key_prefix+wake_job_id(ident,rev) for rev in (0,1)]
        try:
            async def wake(rev):
                return await redis.enqueue_job('execute_agent_task',ident,rev,_queue_name=queue,
                    _job_id=wake_job_id(ident,rev),_expires=30)
            results=await asyncio.gather(*(wake(0) for _ in range(10)))
            self.assertEqual(sum(job is not None for job in results),1)
            self.assertIsNotNone(await wake(1))
            self.assertEqual(await redis.zcard(queue),2)
        finally:
            await redis.delete(queue,*keys)
            await redis.aclose()

if __name__=='__main__':unittest.main()
