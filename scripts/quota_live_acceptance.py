"""Inspect only the explicitly named UI dummy, without any API/provider writes."""
import asyncio,json
from pathlib import Path
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.jobs.task_agent_jobs import principal_for
from app.services import task_agent_service as tasks,purchase_draft_service as drafts

MESSAGE='5 Cement bags kharide. Ye quota acceptance ka dummy review test hai; Tally mein post mat karna.'
async def main():
    async with AsyncSessionLocal() as db:
        source=await db.get(AgentTask,'89d42ed44957cf9dbbed2af1d79053e5')
        principal=await principal_for(db,source)
        rows=(await db.scalars(select(AgentTask).where(AgentTask.organization_id==principal.organization_id,
            AgentTask.user_id==principal.user_id).order_by(AgentTask.created_at.desc()).limit(30))).all()
        task=next((r for r in rows if r.state.get('messages',[''])[0]==MESSAGE),None)
        if not task:print(json.dumps({'found':False}));return
        result=await tasks.read(db,principal,task.id)
        report={k:result.get(k) for k in ('task_id','task_revision','status','response','draft_id','action_id','wait_reason','retry_at','auto_resume_until','selections')}
        report['metrics']=await tasks.metrics(db,principal,task.id)
        if result.get('draft_id'):
            draft=await drafts.read_draft(db,principal,result['draft_id'])
            report['dummy_content']=draft['content'];report['draft_revision']=draft['revision']
        output=Path('data/quota-ui-acceptance.json')
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
