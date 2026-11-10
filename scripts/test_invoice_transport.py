import unittest
from unittest.mock import patch,AsyncMock
import httpx
from app.services.invoice_extraction import _post_invoice_json
from app.services.invoice_ai_budget import TransientExtraction
class Transport(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.admission=patch('app.services.invoice_ai_budget.reserve_paid_call',AsyncMock())
  self.admission.start();self.addCleanup(self.admission.stop)
 async def test_retry_backoff_and_bound(self):
  response=type('R',(),{'status_code':503})()
  with patch('httpx.AsyncClient.post',AsyncMock(return_value=response)) as post,patch('asyncio.sleep',AsyncMock()) as sleep:
   with self.assertRaises(TransientExtraction):await _post_invoice_json('https://example.invalid',{}, {})
   self.assertEqual(post.await_count,1);sleep.assert_not_awaited()
 async def test_auth_model_fail_without_retry(self):
  for status in (401,403,404):
   response=type('R',(),{'status_code':status})()
   with patch('httpx.AsyncClient.post',AsyncMock(return_value=response)) as post:
    with self.assertRaisesRegex(RuntimeError,str(status)):await _post_invoice_json('https://example.invalid',{}, {})
    self.assertEqual(post.await_count,1)
 async def test_timeout_no_hidden_retries(self):
  with patch('httpx.AsyncClient.post',AsyncMock(side_effect=httpx.ReadTimeout('timeout'))) as post:
   with self.assertRaises(TransientExtraction):await _post_invoice_json('https://example.invalid',{}, {})
   self.assertEqual(post.await_count,1)

 async def test_quota_is_bounded_and_message_safe(self):
  response=type('R',(),{'status_code':429})()
  from app.services import invoice_extraction as e
  with patch('httpx.AsyncClient.post',AsyncMock(return_value=response)) as post,patch('asyncio.sleep',AsyncMock()):
   from fastapi import HTTPException
   with self.assertRaises(HTTPException) as error:await e.call_gemini_multimodal_extraction([b'fake'])
   self.assertIn('quota',error.exception.detail)
   self.assertNotIn('http',error.exception.detail)
   self.assertEqual(post.await_count,1)
