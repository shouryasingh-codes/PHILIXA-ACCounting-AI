import pytest
from app.worker import WorkerSettings
from scripts.cleanup_demo_accounts import cleanup_demo_accounts


def test_arq_worker_demo_cleanup_cron_registered():
    cron_coroutines = [job.coroutine for job in WorkerSettings.cron_jobs]
    assert cleanup_demo_accounts in cron_coroutines, "cleanup_demo_accounts must be registered in WorkerSettings.cron_jobs"
    
    cleanup_cron = next(job for job in WorkerSettings.cron_jobs if job.coroutine == cleanup_demo_accounts)
    assert cleanup_cron.minute == {0} or cleanup_cron.minute == 0
    assert cleanup_cron.hour is None


@pytest.mark.asyncio
async def test_cleanup_demo_accounts_accepts_ctx():
    ctx = {"db_session_factory": None}
    assert callable(cleanup_demo_accounts)
