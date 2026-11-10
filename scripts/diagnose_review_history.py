"""Read-only native manifest diagnostic for the named synthetic review task."""
import asyncio,json
from pathlib import Path
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.models.purchase_agent import PurchaseHistoryCache
from app.jobs.task_agent_jobs import principal_for
from app.services import purchase_draft_service as drafts,purchase_native_context as native,tally_sync as sync

async def main():
    report=json.loads(Path('data/full-agent-review-acceptance.json').read_text())
    async with AsyncSessionLocal() as db:
        task=await db.get(AgentTask,report['task_id']);principal=await principal_for(db,task)
        draft=await drafts.scoped_draft(db,principal,task.state['draft_id'])
        context=await native.context(db,principal,draft)
        cache=await db.get(PurchaseHistoryCache,context['cache_id'])
        company=await native.permitted_job(db,cache)
        manifest=await sync.operation(db,company,'purchase_history_read',payload=cache.query)
        print(json.dumps({k:manifest.get(k) for k in ('complete','issues','count')},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
