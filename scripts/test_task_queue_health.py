import unittest
from unittest.mock import patch,AsyncMock
from types import SimpleNamespace
from app.services.task_queue_health import annotate


class QueueHealth(unittest.IsolatedAsyncioTestCase):
    async def test_missing_heartbeat_does_not_claim_running(self):
        with patch('app.core.redis.get_redis_client',new=AsyncMock(return_value=SimpleNamespace(exists=AsyncMock(return_value=0)))):
            result=await annotate({'task_id':'a'*32,'status':'queued','response':'Task queued.'})
        self.assertEqual(result['worker_state'],'unavailable');self.assertFalse(result['progress_active'])
        self.assertEqual(result['status'],'queued')

    async def test_redis_error_is_unknown_not_live(self):
        with patch('app.core.redis.get_redis_client',new=AsyncMock(side_effect=TimeoutError)):
            result=await annotate({'status':'running'})
        self.assertEqual(result['worker_state'],'unknown');self.assertFalse(result['progress_active'])

    async def test_live_worker_is_not_proof_this_queued_job_is_thinking(self):
        redis=SimpleNamespace(exists=AsyncMock(return_value=1))
        with patch('app.core.redis.get_redis_client',new=AsyncMock(return_value=redis)):
            queued=await annotate({'status':'queued','response':'Task queued.'})
            running=await annotate({'status':'running','execution_stage':'running','response':'Reading context'})
        self.assertFalse(queued['progress_active'])
        self.assertEqual(queued['execution_stage'],'waiting_worker')
        self.assertTrue(running['progress_active'])

    async def test_completed_result_needs_no_redis(self):
        with patch('app.core.redis.get_redis_client',new=AsyncMock(side_effect=AssertionError('No Redis'))):
            self.assertEqual((await annotate({'status':'completed','response':'done'}))['response'],'done')

    async def test_native_outbox_action_is_not_mislabelled_by_document_worker_health(self):
        with patch('app.core.redis.get_redis_client',new=AsyncMock(side_effect=AssertionError('Separate native worker'))):
            result=await annotate({'status':'queued','action_id':'a'*32,'response':'Tally sync pending'})
        self.assertEqual(result['response'],'Tally sync pending');self.assertNotIn('worker_state',result)


if __name__=='__main__':unittest.main()
