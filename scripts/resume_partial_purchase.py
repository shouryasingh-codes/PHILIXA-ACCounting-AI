"""Resume the saved failed partial-draft task; no facts, approval or posting."""
import asyncio,json,secrets
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.jobs.task_agent_jobs import principal_for
from app.services import task_agent_service as tasks
async def main():
    async with AsyncSessionLocal() as db:
        row=await db.get(AgentTask,'936f607587fae1eed52e0d69b40da47e')
        principal=await principal_for(db,row)
        if row.state.get('draft_id'):raise RuntimeError('Already has a draft; no replay')
        result=await tasks.resume(db,principal,row.id,tasks.TaskResume(expected_revision=row.revision,request_id=secrets.token_hex(16)))
        print(json.dumps({'task_id':row.id,'status':result['status'],'posting':False}))
if __name__=='__main__':asyncio.run(main())
