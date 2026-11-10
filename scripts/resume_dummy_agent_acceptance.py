"""Resume only the named review-only dummy using current session/permission guards."""
import asyncio, json, os, secrets
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.jobs.task_agent_jobs import principal_for
from app.services.task_agent_service import resume, read, TaskResume

async def main():
    if os.getenv('PHILIXA_TASK_AGENT_REVIEW_ONLY')!='1':
        raise RuntimeError('Review-only acceptance required')
    async with AsyncSessionLocal() as db:
        row=await db.get(AgentTask,'89d42ed44957cf9dbbed2af1d79053e5')
        if not row or not row.state.get('messages',[''])[0].startswith('Naya dummy purchase draft taiyar karo.'):
            raise RuntimeError('Named dummy unavailable')
        if row.state.get('action_id'):
            raise RuntimeError('Dummy already has action; inspect instead')
        principal=await principal_for(db,row)
        await read(db,principal,row.id)
        result=await resume(db,principal,row.id,TaskResume(expected_revision=row.revision,
            request_id='dummy-review-'+secrets.token_hex(12),message=(
            'Supplier: Philixa GST TEST Supplier Local. Invoice number: TA-AGENT-20261102-01. '
            'Date: 02-10-2026. Item: Philixa GST TEST Goods18. Quantity: 1 bags. Rate: 100. '
            'GST: 18%. Taxable amount: 100. CGST: 9. SGST: 9. Final total: 118. '
            'Dummy fixture place_of_supply state code: 06. '
            'Isi saved draft ko update karke review dikhao; post mat karna.')))
        print(json.dumps({k:result.get(k) for k in ('task_id','status','revision','draft_id')},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
