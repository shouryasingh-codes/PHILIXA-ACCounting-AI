"""Read-only scoped context diagnostic for an explicitly selected task."""
import asyncio,json,sys
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.jobs.task_agent_jobs import principal_for
from app.services.task_agent_service import read

async def main():
    async with AsyncSessionLocal() as db:
        row=await db.get(AgentTask,sys.argv[1])
        principal=await principal_for(db,row)
        result=await read(db,principal,row.id)
        print(json.dumps({k:result.get(k) for k in ('task_id','status','response','draft_id','task_revision','purchase_context','selections')},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
