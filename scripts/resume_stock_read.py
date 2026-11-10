"""Resume the paused exact stock read; no approval or posting."""
import asyncio,secrets,json
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.jobs.task_agent_jobs import principal_for
from app.services import task_agent_service as tasks
async def main():
    async with AsyncSessionLocal() as db:
        row=await db.get(AgentTask,'ca259a8b12631665fc7fded117946859');principal=await principal_for(db,row)
        if row.state.get('executions') or row.state.get('outcome')!='answer':raise RuntimeError('Unexpected state; no replay')
        result=await tasks.resume(db,principal,row.id,tasks.TaskResume(expected_revision=row.revision,request_id=secrets.token_hex(16)))
        print(json.dumps({'task_id':row.id,'status':result['status'],'posting':False}))
if __name__=='__main__':asyncio.run(main())
