"""Read only the explicitly named dummy acceptance task; never print credentials."""
import asyncio,json
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask,AgentRun

async def main():
    async with AsyncSessionLocal() as db:
        rows=(await db.scalars(select(AgentTask).where(AgentTask.organization_id=='org_01e2721e023d75c9fd11a4a7').order_by(AgentTask.created_at.desc()).limit(20))).all()
        for row in rows:
            messages=row.state.get('messages',[])
            if not messages or not messages[0].startswith('Naya dummy purchase draft taiyar karo.'):continue
            print(json.dumps({'id':row.id,'status':row.status,'revision':row.revision,'draft_id':row.state.get('draft_id'),
                'issues':row.state.get('issues'), 'executions':row.state.get('executions'),
                'summary':row.state.get('summary')},ensure_ascii=False))
            from app.models.purchase_draft import PurchaseDraft
            draft=await db.get(PurchaseDraft,row.state.get('draft_id'))
            if draft:print(json.dumps({'dummy_draft_revision':draft.revision,'content':draft.content,'action_id':draft.action_id},ensure_ascii=False))
            usage=(await db.scalars(select(AgentRun).where(AgentRun.task_id==row.id).order_by(AgentRun.created_at.desc()).limit(20))).all()
            print(json.dumps({'recent_model_usage':[r.state['usage'] for r in usage if 'usage' in r.state]}))

if __name__=='__main__':asyncio.run(main())
