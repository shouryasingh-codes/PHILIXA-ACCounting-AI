"""Read-only diagnosis of latest task, linked action and helper capability."""
import asyncio,json
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.models.tally import TallyAction
from app.models.purchase_automation import PurchaseAutomationPolicy
from app.jobs.task_agent_jobs import principal_for
from app.services import purchase_draft_service as drafts
from app.api.v1.routes_tally_bridge import helper_status

async def main():
    async with AsyncSessionLocal() as db:
        task=await db.scalar(select(AgentTask).order_by(AgentTask.updated_at.desc()).limit(1))
        principal=await principal_for(db,task)
        draft=await drafts.scoped_draft(db,principal,task.state['draft_id'])
        status=await helper_status(principal,db)
        action=await db.get(TallyAction,draft.action_id) if draft.action_id else None
        pending=(await db.scalars(select(TallyAction).where(TallyAction.status.in_(['queued','submitting','verification_pending','draft','awaiting_review','needs_review'])))).all()
        policies=(await db.scalars(select(PurchaseAutomationPolicy))).all()
        print(json.dumps({'automation_modes':[p.data.get('mode') for p in policies]}))
        print(json.dumps({'pending_actions':[{'token':a.token,'status':a.status,'operation':a.payload.get('operation'),'attempts':a.attempts} for a in pending]}))
        from app.services.tally_sync import uncertain
        print(json.dumps({'company_dispatch_blockers':[{'token':a.token,'operation':a.payload.get('operation'),'result':a.result} for a in pending if a.company_id==task.company_id and a.status=='needs_review' and uncertain(a)]},default=str))
        print(json.dumps({'task':task.id,'task_status':task.status,'helper':{k:v for k,v in status.items() if k in ('online','protocol_version','goods_receipt_capable','connection_state','startup_configured','helper_version','minimum_version','version','last_seen','update_required')},'action':{k:getattr(action,k,None) for k in ('token','status','attempts','last_error','error','result','schema_version','updated_at','created_at')} if action else None,'receipt':(draft.extraction_metadata or {}).get('goods_receipt')},default=str,ensure_ascii=False))
if __name__=='__main__':asyncio.run(main())
