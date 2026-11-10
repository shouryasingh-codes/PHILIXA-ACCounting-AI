"""Review-only synthetic situation routing; never approves/submits."""
import asyncio,json,os,secrets,sys
from pathlib import Path
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.jobs.task_agent_jobs import principal_for,billing_limits
from app.services import task_agent_service as tasks,purchase_draft_service as drafts

FILE=Path('data/live-situation-acceptance.json')

async def main():
    if os.getenv('PHILIXA_TASK_AGENT_REVIEW_ONLY')!='1' or billing_limits()[0]!='free':raise RuntimeError('Free review-only mode required')
    async with AsyncSessionLocal() as db:
        if '--start' in sys.argv:
            source=await db.get(AgentTask,'9f9dff50d793aabf288052ed645223d0');principal=await principal_for(db,source)
            message=('Dummy review only, post mat karna. Supplier: Philixa GST TEST Supplier Local. '
                'Item: Philixa GST TEST Goods18. Quantity: 1 bags. Rate before GST: 100. '
                'Maal aa gaya, bill baad mein. Received date: 02-10-2026. GST alag lagega. '
                'Receipt Note ka final review dikhao, Tally mein post mat karna.')
            result=await tasks.create(db,principal,tasks.TaskCreate(message=message,company_id=source.company_id,
                request_id='qa-situation-'+secrets.token_hex(10),outcome='verified_entry'))
            FILE.write_text(json.dumps({'task_id':result['task_id'],'message':message},indent=2))
            print(json.dumps({'task_id':result['task_id'],'status':result['status']}));return
        report=json.loads(FILE.read_text());row=await db.get(AgentTask,report['task_id']);principal=await principal_for(db,row)
        result=await tasks.read(db,principal,row.id)
        report['result']={k:result.get(k) for k in ('status','response','draft_id','goods_receipt','receipt_ready','issues','preview')}
        report['trajectory']=[{'tool':e.get('tool'),'status':e.get('status')} for e in row.state.get('executions',[])]
        report['metrics']=await tasks.metrics(db,principal,row.id)
        if result.get('draft_id'):
            draft=await drafts.scoped_draft(db,principal,result['draft_id'])
            receipt=(draft.extraction_metadata or {}).get('goods_receipt',{})
            report['checks']={'no_invoice_invented':not draft.content.get('invoice_number'),
                'bill_pending':receipt.get('status')=='bill_pending',
                'received_date':receipt.get('received_on')=='2026-10-02',
                'rate_basis':receipt.get('rate_basis')=='tax_exclusive',
                'correct_tool_route':any(e['tool']=='receipt_preview' for e in report['trajectory']) and not any(e['tool']=='purchase_preview' for e in report['trajectory'])}
        FILE.write_text(json.dumps(report,indent=2,ensure_ascii=False))
        print(json.dumps({'task_id':row.id,**report['result'],'checks':report.get('checks'),'trajectory':report['trajectory'],'model_calls':report['metrics'].get('gateway_requests'),'tally_posting':False},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
