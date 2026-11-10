"""One-message synthetic purchase acceptance. Never approves/posts to Tally."""
import asyncio,json,os,secrets,sys
from pathlib import Path
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.jobs.task_agent_jobs import principal_for,billing_limits
from app.services import task_agent_service as tasks,purchase_draft_service as drafts

REPORT=Path('data/full-agent-review-acceptance.json')

async def main():
    if os.getenv('PHILIXA_TASK_AGENT_REVIEW_ONLY')!='1' or billing_limits()[0]!='free':
        raise RuntimeError('Confirmed free tier and review-only mode required')
    async with AsyncSessionLocal() as db:
        if '--start' in sys.argv:
            if REPORT.exists():
                previous=json.loads(REPORT.read_text())
                REPORT.with_name('full-agent-review-'+previous['task_id']+'.json').write_text(json.dumps(previous,indent=2,ensure_ascii=False))
            source=await db.get(AgentTask,'9f9dff50d793aabf288052ed645223d0')
            principal=await principal_for(db,source)
            fixture=await db.get(AgentTask,'89d42ed44957cf9dbbed2af1d79053e5')
            if fixture.organization_id!=principal.organization_id:raise RuntimeError('Fixture scope mismatch')
            old=await drafts.scoped_draft(db,principal,fixture.state['draft_id'])
            content=old.content
            reference='QA-ONE-'+secrets.token_hex(4).upper()
            message=(f'Dummy review test, post mat karna. Supplier: Philixa GST TEST Supplier Local. '
                f'Invoice number: {reference}. Purchase date: 02-10-2026. '
                'Item: Philixa GST TEST Goods18. Quantity: 1 bags. Rate before GST: 100. '
                'GST rate: 18%. HSN: '+str(content['lines'][0].get('hsn') or '')+'. '
                'Taxable amount: 100. CGST: 9. SGST: 9. Final total: 118. '
                'Supplier GSTIN: '+str(content.get('supplier_gstin') or '')+'. '
                'Place of supply state code: 06. Godown: Main Location. '
                'No discount, round off 0. Sab details ek saath use karke final review dikhao; Tally entry post mat karna.')
            result=await tasks.create(db,principal,tasks.TaskCreate(message=message,
                request_id='qa-one-'+secrets.token_hex(12),company_id=source.company_id,outcome='verified_entry'))
            REPORT.write_text(json.dumps({'task_id':result['task_id'],'reference':reference,'message':message},indent=2))
            print(json.dumps({'task_id':result['task_id'],'status':result['status'],'posting_authorized':False}))
            return
        report=json.loads(REPORT.read_text())
        task=await db.get(AgentTask,report['task_id'])
        principal=await principal_for(db,task)
        if '--resume' in sys.argv:
            result=await tasks.resume(db,principal,task.id,tasks.TaskResume(expected_revision=task.revision,
                request_id='qa-review-'+secrets.token_hex(12),message='Saved dummy ke sab supplied facts use karke final validated review dikhao. Naya draft mat banao, Tally posting mat karna.'))
            print(json.dumps({'task_id':task.id,'status':result['status'],'posting_authorized':False}))
            return
        result=await tasks.read(db,principal,task.id)
        previous_result=report.get('result') or {}
        if previous_result.get('status')=='needs_approval':
            report['reopen_check']={
                'same_draft':previous_result.get('draft_id')==result.get('draft_id'),
                'same_preview':bool(result.get('preview')) and previous_result.get('preview',{}).get('token')==result['preview'].get('token'),
                'same_action':previous_result.get('action_id')==result.get('action_id')}
        report['result']={k:result.get(k) for k in ('task_id','status','response','draft_id','action_id','issues','proposal','preview')}
        report['metrics']=await tasks.metrics(db,principal,task.id)
        if task.status=='verification_pending' and not task.state.get('draft_id'):
            from app.services.purchase_message import grounded,MessageFields
            for event in task.state.get('executions',[]):
                if event.get('tool')=='create_purchase_draft':
                    args=event.get('arguments',{})
                    try:grounded(task.state['messages'][args['message_index']],MessageFields(updates=args['updates'],unsupported_reason=None))
                    except ValueError as exc:report['grounding_error']=str(exc)
                    report['proposed_updates']=args.get('updates')
        if result.get('draft_id'):
            draft=await drafts.read_draft(db,principal,result['draft_id'])
            report['saved_content']=draft['content'];report['draft_revision']=draft['revision']
            from decimal import Decimal
            c=draft['content'];line=c['lines'][0]
            report['checks']={
                'supplier':c['party_name']=='Philixa GST TEST Supplier Local',
                'invoice_reference':c['invoice_number']==report['reference'],
                'date':c['entry_date']=='2026-10-02',
                'item':line['item_name']=='Philixa GST TEST Goods18',
                'quantity_rate_taxable':all(Decimal(str(line[k]))==Decimal(v) for k,v in {'quantity':'1','rate':'100','gst_rate':'18','taxable_amount':'100'}.items()),
                'taxes_total':all(Decimal(str(c['expected_taxes'][k]))==Decimal('9') for k in ('CGST','SGST')) and Decimal(c['invoice_total'])==Decimal('118'),
                'single_user_message':report['metrics']['user_messages']==1,
                'native_posting':False}
            report['review_pass']=result['status']=='needs_approval' and bool(result.get('preview'))
        REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False))
        print(json.dumps({k:report.get(k) for k in ('task_id','checks','review_pass','grounding_error','reopen_check')}|{
            'status':result['status'],'response':result['response'],'issues':result.get('issues'),
            'model_calls':report['metrics'].get('gateway_requests'),'report':str(REPORT)},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
