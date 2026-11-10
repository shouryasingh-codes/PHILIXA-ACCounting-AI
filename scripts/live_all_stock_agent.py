"""Review-only stock question; cannot approve/post accounting actions."""
import asyncio,json,secrets,sys
from pathlib import Path
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.jobs.task_agent_jobs import principal_for
from app.services import task_agent_service as tasks
FILE=Path('data/live-all-stock-agent.json')
async def main():
    async with AsyncSessionLocal() as db:
        if '--start' in sys.argv:
            source=await db.scalar(select(AgentTask).where(AgentTask.company_id.is_not(None)).order_by(AgentTask.updated_at.desc()).limit(1))
            principal=await principal_for(db,source)
            result=await tasks.create(db,principal,tasks.TaskCreate(message='stock kitna hai',company_id=source.company_id,request_id=secrets.token_hex(16)))
            FILE.write_text(json.dumps({'task_id':result['task_id']}))
        else:
            row=await db.get(AgentTask,json.loads(FILE.read_text())['task_id']);principal=await principal_for(db,row)
            result=await tasks.read(db,principal,row.id)
            print(json.dumps({'outcome':row.state.get('outcome'),'executions':row.state.get('executions'),'issues':row.state.get('issues')},default=str))
        print(json.dumps({k:result.get(k) for k in ('task_id','status','response','stock_results','coverage')},ensure_ascii=False))
if __name__=='__main__':asyncio.run(main())
