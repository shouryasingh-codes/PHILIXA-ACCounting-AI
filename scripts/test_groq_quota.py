"""Real PostgreSQL ledger tests; HTTP is synthetic and never contacts Groq."""
import io,json,secrets,unittest,urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from sqlalchemy import delete,select
from sqlalchemy.orm import Session
from app.ai import groq_gateway as g
from app.jobs.task_agent_jobs import quota_wait

class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict('os.environ',{'PHILIXA_GROQ_ACCOUNT_SCOPE':'test-'+secrets.token_hex(8),
            'PHILIXA_GROQ_RPM':'30','PHILIXA_GROQ_TPM':'8000','PHILIXA_GROQ_RPD':'1000','PHILIXA_GROQ_TPD':'200000'})
        self.env.start();self.bucket=g.bucket_for('dummy-key','openai/gpt-oss-20b')
    def tearDown(self):
        with Session(g.engine()) as db,db.begin():
            db.execute(delete(g.Request).where(g.Request.bucket==self.bucket));db.execute(delete(g.Cooldown).where(g.Cooldown.bucket==self.bucket))
        self.env.stop()
    def test_atomic_parallel_admission(self):
        def reserve(_):
            try:g.admit(self.bucket,4000);return True
            except g.QuotaDeferred:return False
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(reserve,range(4)))
        self.assertEqual(sum(results),1)
    def test_oversize_never_creates_reservation(self):
        with self.assertRaises(g.QuotaDeferred) as caught:g.admit(self.bucket,7201)
        self.assertEqual(caught.exception.reason,'request_too_large')
        with Session(g.engine()) as db:self.assertEqual(list(db.scalars(select(g.Request).where(g.Request.bucket==self.bucket))),[])
    def test_observed_lower_limit_and_cache_reconciliation(self):
        ident=g.admit(self.bucket,1000)
        g.settle(ident,self.bucket,{'total_tokens':900,'prompt_tokens_details':{'cached_tokens':300}},
            {'x-ratelimit-limit-tokens':'1000'},200,.01)
        with Session(g.engine()) as db:self.assertEqual(db.get(g.Request,ident).charged_tokens,600)
        with self.assertRaises(g.QuotaDeferred):g.admit(self.bucket,400)
    def test_external_remaining_capacity_is_honoured(self):
        ident=g.admit(self.bucket,1000)
        g.settle(ident,self.bucket,{'total_tokens':100}, {'x-ratelimit-remaining-tokens':'20','x-ratelimit-reset-tokens':'12s'},200,.01)
        with self.assertRaises(g.QuotaDeferred) as caught:g.admit(self.bucket,50)
        self.assertEqual(caught.exception.reason,'minute_quota')
    def test_provider_snapshot_avoids_second_rolling_token_block(self):
        ident=g.admit(self.bucket,7000)
        g.settle(ident,self.bucket,{'total_tokens':6500},
            {'x-ratelimit-remaining-tokens':'6000','x-ratelimit-reset-tokens':'15s'},200,.01)
        # Provider has refilled capacity: old rolling sum would reject this.
        g.admit(self.bucket,3000)
        with self.assertRaises(g.QuotaDeferred):g.admit(self.bucket,2500)

    def test_missing_or_expired_headers_keep_rolling_fallback(self):
        ident=g.admit(self.bucket,6500)
        g.settle(ident,self.bucket,{'total_tokens':6500},
            {'x-ratelimit-remaining-tokens':'7000','x-ratelimit-reset-tokens':'0s'},200,.01)
        with self.assertRaises(g.QuotaDeferred):g.admit(self.bucket,1000)

    def test_optional_local_cap_and_legacy_fallback(self):
        with patch.dict('os.environ',{'PHILIXA_GROQ_QUOTA_ENABLED':'1'}):
            self.assertIsNone(g.free_call_limit())
            with patch.dict('os.environ',{'PHILIXA_GROQ_LOCAL_DAILY_CALLS':'25'}):
                self.assertEqual(g.free_call_limit(),25)
        with patch.dict('os.environ',{'PHILIXA_GROQ_QUOTA_ENABLED':'0'}):
            self.assertEqual(g.free_call_limit(),50)

    def test_daily_limit_is_not_minute_retry(self):
        with patch.dict('os.environ',{'PHILIXA_GROQ_RPD':'1'}):
            g.admit(self.bucket,100)
            with self.assertRaises(g.QuotaDeferred) as caught:g.admit(self.bucket,100)
            self.assertEqual(caught.exception.reason,'daily_quota')
    def test_429_single_attempt_and_server_delay(self):
        error=urllib.error.HTTPError('https://api.groq.com',429,'busy',{'retry-after':'90'},io.BytesIO(b'{"error":{"message":"tokens per minute"}}'))
        with patch.object(g.urllib.request,'urlopen',side_effect=error) as post:
            with self.assertRaises(g.QuotaDeferred) as caught:g.request('https://api.groq.com/openai/v1/chat/completions',
                {'model':'openai/gpt-oss-20b','messages':[{'role':'user','content':'dummy'}],'max_completion_tokens':100},{'Authorization':'Bearer dummy-key'},5)
            self.assertTrue(caught.exception.sent);self.assertGreater((caught.exception.retry_at-g.now()).total_seconds(),85)
            post.assert_called_once()
            self.assertIn('PhilixaAI',post.call_args.args[0].get_header('User-agent'))
    def test_explicit_pre_generation_rejection_does_not_spend_tokens(self):
        ident=g.admit(self.bucket,3000)
        g.settle(ident,self.bucket,{}, {},403,.01)
        with Session(g.engine()) as db:
            row=db.get(g.Request,ident)
            self.assertEqual(row.charged_tokens,0)
            self.assertEqual(row.status,'rejected')
        g.admit(self.bucket,6000)

    def test_timeout_preserves_reservation_and_no_retry(self):
        with patch.object(g.urllib.request,'urlopen',side_effect=TimeoutError) as post:
            with self.assertRaises(g.QuotaDeferred) as caught:g.request('https://api.groq.com',
                {'model':'openai/gpt-oss-20b','messages':[],'max_completion_tokens':100},{'Authorization':'Bearer dummy-key'},5)
            self.assertEqual(caught.exception.reason,'provider_uncertain');post.assert_called_once()
        with Session(g.engine()) as db:
            row=db.scalar(select(g.Request).where(g.Request.bucket==self.bucket))
            self.assertEqual(row.charged_tokens,row.reserved_tokens);self.assertEqual(row.status,'uncertain')

    def test_long_provider_error_keeps_code_without_document_leak(self):
        from app.ai.provider import AIExtractionError
        private='private invoice content '*300
        error=urllib.error.HTTPError('https://api.groq.com',400,'bad',{},io.BytesIO(json.dumps(
            {'error':{'failed_generation':private,'code':'json_validate_failed'}}).encode()))
        with patch.object(g.urllib.request,'urlopen',side_effect=error) as post:
            with self.assertRaises(AIExtractionError) as caught:g.request('https://api.groq.com',
                {'model':'openai/gpt-oss-20b','messages':[],'max_completion_tokens':100},{'Authorization':'Bearer dummy-key'},5)
            self.assertEqual(caught.exception.status_code,400)
            self.assertEqual(caught.exception.provider_code,'json_validate_failed')
            self.assertNotIn('private invoice',str(caught.exception));post.assert_called_once()
    def test_unavailable_ledger_fails_closed(self):
        with patch.object(g,'admit',side_effect=RuntimeError),patch.object(g.urllib.request,'urlopen') as post:
            with self.assertRaises(g.QuotaDeferred) as caught:g.request('https://api.groq.com',{'model':'openai/gpt-oss-20b','messages':[]},{},5)
            self.assertFalse(caught.exception.sent);post.assert_not_called()
    def test_duration_parser(self):
        self.assertEqual(g.duration('1m26.4s'),86.4)
        self.assertEqual(g.duration('105ms'),.105)
        for value in ('NaN','-1','Infinity','bad','1s junk'):self.assertIsNone(g.duration(value))
    def test_wait_deadline_survives_restart_and_stops_daily(self):
        stamp=g.now();exc=g.QuotaDeferred('minute_quota',stamp+timedelta(seconds=60))
        first=quota_wait({},exc,stamp)
        second=quota_wait(first,g.QuotaDeferred('minute_quota',stamp+timedelta(seconds=130)),stamp+timedelta(seconds=61))
        self.assertEqual(first['auto_resume_until'],second['auto_resume_until'])
        self.assertEqual(second['status'],'needs_input')
        self.assertEqual(quota_wait({},g.QuotaDeferred('daily_quota',stamp+timedelta(days=1)),stamp)['status'],'needs_input')
        state=quota_wait({},g.QuotaDeferred('minute_quota',stamp+timedelta(seconds=1),sent=True),stamp)
        self.assertEqual(quota_wait(state,g.QuotaDeferred('minute_quota',stamp+timedelta(seconds=2),sent=True),stamp)['status'],'needs_input')

if __name__=='__main__':unittest.main()
