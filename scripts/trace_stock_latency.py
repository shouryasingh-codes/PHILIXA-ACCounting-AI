"""Read-only transport/schema timing. Never calls a model or posts a voucher."""
import asyncio,json,sys,time
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask,AgentExecution,AgentRun
from app.models.tally import TallyDevice
from app.jobs.task_agent_jobs import principal_for
from app.services import tally_stock as stock,purchase_draft_service as drafts
from app.services.tally_bridge import request_job
from sqlalchemy import select


async def main():
    ident=sys.argv[1]
    async with AsyncSessionLocal() as db:
        row=await db.get(AgentTask,ident);principal=await principal_for(db,row)
        company=await drafts.company_for(db,principal,row.company_id)
        device=await db.get(TallyDevice,company.device_id)
        executions=(await db.scalars(select(AgentExecution).where(AgentExecution.task_id==ident))).all()
        runs=(await db.scalars(select(AgentRun).where(AgentRun.task_id==ident))).all()
        print(json.dumps({'task':ident,'created':str(row.created_at),'updated':str(row.updated_at),
            'model_rounds':row.state.get('model_rounds'),'executions':[(e.data.get('tool'),str(e.created_at)) for e in executions],
            'model_requests':sum(bool(r.state.get('free_call')) for r in runs)},ensure_ascii=False),flush=True)
        from app.services.business_command_service import today
        as_of=str(today());started=time.monotonic()
        try:
            if '--legacy' in sys.argv:
                result=await request_job(device,'stock',company=company.name,identity=company.identity,as_of=as_of,item_query=None)
            else:
                result=await stock.read_complete_stock(company)
            record={'transport_ms':round((time.monotonic()-started)*1000),
                'company_match':result.get('company')==company.name,'identity_match':result.get('identity')==company.identity,
                'date_match':result.get('as_of')==as_of,'items':len(result.get('items',[]))}
            try:stock.validate_stock_data(result);record['schema']='valid'
            except Exception as exc:record.update(schema='invalid',error_type=type(exc).__name__,error=str(exc)[:160])
            print(json.dumps(record),flush=True)
        except Exception as exc:
            print(json.dumps({'transport_ms':round((time.monotonic()-started)*1000),'error_type':type(exc).__name__,'error':str(exc)[:160]}),flush=True)


if __name__=='__main__':asyncio.run(main())
