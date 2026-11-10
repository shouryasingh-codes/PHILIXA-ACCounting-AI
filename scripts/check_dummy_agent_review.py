"""Verify named dummy persistence and preview only; never approve or submit."""
import asyncio,json,os
from fastapi import HTTPException
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.jobs.task_agent_jobs import principal_for
from app.services import purchase_draft_service as drafts

async def main():
    if os.getenv('PHILIXA_TASK_AGENT_REVIEW_ONLY')!='1':raise RuntimeError('Review-only required')
    async with AsyncSessionLocal() as db:
        task=await db.get(AgentTask,'89d42ed44957cf9dbbed2af1d79053e5')
        principal=await principal_for(db,task)
        draft=await drafts.scoped_draft(db,principal,task.state['draft_id'])
        content=draft.content
        assert content['party_name']=='Philixa GST TEST Supplier Local'
        assert content['invoice_number']=='TA-AGENT-20261102-01'
        assert content['entry_date']=='2026-10-02'
        from decimal import Decimal
        line=content['lines'][0]
        assert all(Decimal(str(line[k]))==Decimal(v) for k,v in {'quantity':'1','rate':'100','gst_rate':'18','taxable_amount':'100'}.items())
        assert Decimal(content['invoice_total'])==Decimal('118')
        assert all(Decimal(content['expected_taxes'][k])==Decimal('9') for k in ('CGST','SGST'))
        print(json.dumps({'persisted_facts_pass':True,'task_id':task.id,'draft_id':draft.id,'revision':draft.revision}))
        try:
            result=await drafts.preview_draft(db,principal,draft.id,drafts.DraftPreview(revision=draft.revision))
            print(json.dumps({'preview_pass':True,'preview_available':bool(result.get('preview')),'tally_submission':False}))
        except HTTPException as exc:
            print(json.dumps({'preview_pass':False,'http_status':exc.status_code,'reason':str(exc.detail),'tally_submission':False}))

if __name__=='__main__':asyncio.run(main())
