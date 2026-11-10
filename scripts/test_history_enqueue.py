"""History scheduling must work outside the web-process global pool."""
import unittest
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from app.services.purchase_native_context import enqueue


class HistoryQueue(unittest.IsolatedAsyncioTestCase):
    async def test_worker_without_web_pool_enqueues_immediately_and_closes_owned_pool(self):
        pool=SimpleNamespace(enqueue_job=AsyncMock(),aclose=AsyncMock())
        row=SimpleNamespace(id='synthetic-history',attempts=0,updated_at=datetime.now(timezone.utc))
        with patch('app.core.arq.get_arq_pool',return_value=None),patch('arq.connections.create_pool',new=AsyncMock(return_value=pool)):
            await enqueue(row)
        pool.enqueue_job.assert_awaited_once()
        self.assertEqual(pool.enqueue_job.call_args.args,('refresh_purchase_history','synthetic-history'))
        pool.aclose.assert_awaited_once()

    async def test_shared_worker_pool_is_not_closed(self):
        pool=SimpleNamespace(enqueue_job=AsyncMock(),aclose=AsyncMock())
        await enqueue(SimpleNamespace(id='synthetic-history',attempts=0,updated_at=datetime.now(timezone.utc)),pool)
        pool.enqueue_job.assert_awaited_once()
        pool.aclose.assert_not_awaited()


if __name__=='__main__':unittest.main()
