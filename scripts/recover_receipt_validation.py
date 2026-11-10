"""Recover only a pre-preview inclusive-rate rejection; never submit/replay."""
import asyncio,copy,secrets,sys
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask,AgentRun
from app.jobs.task_agent_jobs import principal_for
from app.services import purchase_draft_service as drafts,purchase_situation as situation
from app.services.task_agent_service import now

async def main():
    async with AsyncSessionLocal() as db:
        task=await db.get(AgentTask,sys.argv[1]);principal=await principal_for(db,task)
        draft=await drafts.scoped_draft(db,principal,task.state['draft_id'],lock=True)
        pending=[e for e in task.state.get('executions',[]) if e.get('status')=='pending']
        if task.status!='verification_pending' or draft.action_id or task.state.get('action_id') or not pending or any(e['tool']!='receipt_preview' for e in pending):
            raise RuntimeError('Recovery guard failed; no changes')
        if (draft.extraction_metadata or {}).get('goods_receipt',{}).get('rate_basis')!='tax_inclusive':raise RuntimeError('Unexpected reason')
        result=await situation.state(db,principal,draft.id)
        db.add(AgentRun(id=secrets.token_hex(16),task_id=task.id,revision=task.revision,state=copy.deepcopy(task.state),created_at=now()))
        state=copy.deepcopy(task.state)
        for event in state['executions']:
            if event['status']=='pending':event['status']='validation_rejected_before_preview'
        state.update(observations=[{'status':'needs_input','data':result,'verified':False}],summary=result['response'],issues=[])
        task.state=state;task.status='needs_input';task.revision+=1;task.updated_at=now()
        await db.commit();print('Recovered saved task to actionable review; no action created or posted.')
if __name__=='__main__':asyncio.run(main())
