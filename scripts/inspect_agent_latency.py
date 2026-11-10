"""Read-only queue/provider timings. Never logs document bodies or credentials."""
import asyncio,json,os
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask,AgentRun
from app.models.groq_quota import GroqQuotaRequest

async def main():
    print(json.dumps({'router_enabled':os.getenv('PHILIXA_INTENT_ROUTER_ENABLED','0')}))
    async with AsyncSessionLocal() as db:
        rows=(await db.scalars(select(AgentTask).order_by(AgentTask.updated_at.desc()).limit(2))).all()
        for row in rows:
            calls=(await db.scalars(select(GroqQuotaRequest).where(GroqQuotaRequest.task_id==row.id))).all()
            runs=(await db.scalars(select(AgentRun).where(AgentRun.task_id==row.id))).all()
            print(json.dumps({'task_id':row.id,'status':row.status,'revision':row.revision,
                'created':str(row.created_at),'updated':str(row.updated_at),'lease_until':str(row.lease_until),
                'model_rounds':row.state.get('model_rounds',0),'execution_count':len(row.state.get('executions',[])),
                'reservation_count':len(runs),'call_count':len(calls),
                'calls':[{'status':q.status,'created':str(q.created_at),'updated':str(q.updated_at),
                    'http_status':q.metadata_json.get('http_status'),'latency_ms':q.metadata_json.get('latency_ms')} for q in calls]},default=str))

if __name__=='__main__':asyncio.run(main())
