"""Refresh the named saved review only; never approve or post."""
import asyncio,secrets,json
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.jobs.task_agent_jobs import principal_for
from app.services import task_agent_service as tasks
async def main():
    async with AsyncSessionLocal() as db:
        row=await db.get(AgentTask,'650548168bb7026af2d1dc051e78bde2')
        principal=await principal_for(db,row)
        result=await tasks.resume(db,principal,row.id,tasks.TaskResume(expected_revision=row.revision,request_id=secrets.token_hex(16),context_refresh=True))
        print(json.dumps({'task_id':row.id,'status':result['status'],'posting':False}))
if __name__=='__main__':asyncio.run(main())
