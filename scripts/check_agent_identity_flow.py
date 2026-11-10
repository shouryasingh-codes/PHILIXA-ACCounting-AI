"""Idempotent synthetic identity-first acceptance; review only, no posting."""
import asyncio,json,os
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.jobs.task_agent_jobs import principal_for
from app.services import task_agent_service as service

async def main():
    if os.getenv('PHILIXA_TASK_AGENT_REVIEW_ONLY')!='1':raise RuntimeError('Review-only required')
    async with AsyncSessionLocal() as db:
        source=await db.get(AgentTask,'89d42ed44957cf9dbbed2af1d79053e5')
        principal=await principal_for(db,source)
        result=await service.create(db,principal,service.TaskCreate(
            company_id=source.company_id,outcome='draft',request_id='identity-regression-20261102-01',
            message='5 bag of Cement kharide. Ye dummy review test hai; Tally mein post mat karna.'))
        print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
