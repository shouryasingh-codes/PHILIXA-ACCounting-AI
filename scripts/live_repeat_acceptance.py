"""Synthetic repeat-purchase selection acceptance. No posting or approvals."""
import asyncio,json,secrets,sys,os
from pathlib import Path
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.jobs.task_agent_jobs import principal_for,billing_limits
from app.services import task_agent_service as tasks,purchase_draft_service as drafts

FILE=Path('data/live-repeat-acceptance.json')

async def main():
    if os.getenv('PHILIXA_TASK_AGENT_REVIEW_ONLY')!='1' or billing_limits()[0]!='free':raise RuntimeError('Free review mode required')
    async with AsyncSessionLocal() as db:
        if '--start' in sys.argv:
            source=await db.get(AgentTask,'9f9dff50d793aabf288052ed645223d0');principal=await principal_for(db,source)
            message='Repeat purchase dummy review test: Cement ke 5 bags kharide. Tally mein post mat karna; supplier/rate history ka suggestion dikhao.'
            result=await tasks.create(db,principal,tasks.TaskCreate(message=message,company_id=source.company_id,
                request_id='qa-repeat-'+secrets.token_hex(10),outcome='verified_entry'))
            FILE.write_text(json.dumps({'task_id':result['task_id'],'message':message},indent=2))
            print(json.dumps({'task_id':result['task_id'],'status':result['status']}));return
        report=json.loads(FILE.read_text());row=await db.get(AgentTask,report['task_id']);principal=await principal_for(db,row)
        current=await tasks.read(db,principal,row.id)
        if '--refresh' in sys.argv:
            result=await tasks.resume(db,principal,row.id,tasks.TaskResume(expected_revision=row.revision,
                request_id='qa-repeat-refresh-'+secrets.token_hex(8),context_refresh=True))
            print(json.dumps({'status':result['status'],'task_id':row.id}));return
        if '--accept' in sys.argv:
            if not current.get('repeat_purchase') or current['status']!='needs_input':raise RuntimeError('No ready repeat suggestion; no selection attempted')
            report['before_selection_metrics']=await tasks.metrics(db,principal,row.id)
            result=await tasks.resume(db,principal,row.id,tasks.TaskResume(expected_revision=row.revision,
                request_id='qa-repeat-done-'+secrets.token_hex(8),message='done'))
            FILE.write_text(json.dumps(report,indent=2,ensure_ascii=False));print(json.dumps({'status':result['status'],'task_id':row.id}));return
        report['result']={k:current.get(k) for k in ('status','response','draft_id','action_id','repeat_purchase','situation_choices')}
        report['metrics']=await tasks.metrics(db,principal,row.id)
        if current.get('draft_id'):
            draft=await drafts.read_draft(db,principal,current['draft_id'])
            report['saved_content']=draft['content']
        if report.get('before_selection_metrics'):
            report['zero_call_selection']=report['before_selection_metrics']['gateway_requests']==report['metrics']['gateway_requests']
        FILE.write_text(json.dumps(report,indent=2,ensure_ascii=False))
        print(json.dumps({'task_id':row.id,**report['result'],'model_calls':report['metrics']['gateway_requests'],
            'zero_call_selection':report.get('zero_call_selection'),'saved_content':report.get('saved_content'),'posting':False},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
