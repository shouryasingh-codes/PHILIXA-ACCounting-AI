"""Offline contract replay or opt-in paired live decisions. Never executes domain tools.

Offline replay checks the evaluator/contracts, not model accuracy. Live runs stop
on quota/provider failures, preserve partial evidence and never retry automatically.
"""
import argparse,asyncio,hashlib,json,secrets,time
import statistics
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from app.services.task_agent_model import choose,request_payload
from app.services.task_agent_prompts import metadata
from app.services.task_agent_tools import registry
from app.services.task_agent_runtime import available_tools,Decision
from app.services.purchase_message import MessageFields,grounded
from app.ai.groq_gateway import estimate,QuotaDeferred

FIXTURES=Path('scripts/fixtures/agent_prompts/heldout.json')
REPORT=Path('data/agent-prompt-evaluation.json')

def summarize(report):
    rows=report['rows'];comparison={}
    for version in ('baseline','v2'):
        subset=[r for r in rows if r['version']==version];evaluated=[r for r in subset if 'decision' in r]
        usage=[r['usage'] for r in subset if r.get('usage')]
        latency=[r['latency_ms'] for r in subset if r.get('latency_ms') is not None]
        comparison[version]={
            'evaluated_decisions':len(evaluated),'passed':sum(r['passed'] for r in evaluated),
            'model_calls':sum(r['model_calls'] for r in subset),
            'estimated_reserved_tokens':sum(r['estimated_reserved_tokens'] for r in evaluated),
            'actual_prompt_tokens':sum(u.get('prompt_tokens',0) for u in usage) if usage else None,
            'actual_completion_tokens':sum(u.get('completion_tokens',0) for u in usage) if usage else None,
            'cached_tokens':sum((u.get('prompt_tokens_details') or {}).get('cached_tokens',0) for u in usage) if usage else None,
            'median_latency_ms':statistics.median(latency) if latency else None,
            'clarification_decisions':sum(r['decision']['kind']=='needs_input' for r in evaluated),
            'field_failures':sum(any(e.startswith(('missing_or_changed_fact:','unexpected_fact:','ungrounded_fields')) for e in r.get('errors',[])) for r in evaluated),
            'repeated_question_rate':None,'active_review_time_ms':None,'actual_billed_cost_usd':None}
    paired=set.intersection(*[{r['case_id'] for r in rows if r['version']==version and 'decision' in r} for version in ('baseline','v2')])
    report['comparison']=comparison;report['paired_cases']=len(paired)
    report['cost_note']='Actual billing unavailable. Confirmed free-tier calls; token totals are usage, not an invoice.'
    return report

def tools_for(state):
    tools=available_tools(state,registry(None,SimpleNamespace(),state.get('company_id'),state))
    schemas=[dict(name=t.name,description=t.description,effect=t.effect,schema=t.arguments.model_json_schema()) for t in tools]
    return {t.name:t for t in tools},schemas

def equal(a,b):
    try:return Decimal(str(a))==Decimal(str(b))
    except (InvalidOperation,ValueError,TypeError):return a==b

def grade(case,decision,tools):
    expected=case['expected'];errors=[]
    if decision.kind not in expected['kinds']:errors.append('wrong_decision_kind')
    if decision.kind=='tool':
        if decision.tool not in expected['tools']:errors.append('wrong_next_tool')
        if decision.tool not in tools:return errors+['unavailable_tool']
        try:args=tools[decision.tool].arguments.model_validate(decision.arguments).model_dump()
        except Exception:return errors+['invalid_tool_schema']
        for key,value in expected.get('arguments',{}).items():
            if args.get(key)!=value:errors.append('wrong_argument:'+key)
        if decision.tool in ('create_purchase_draft','apply_user_message'):
            try:
                message=case['state']['messages'][args['message_index']]
                updates=grounded(message,MessageFields(updates=args['updates'],unsupported_reason=None))
            except Exception:return errors+['ungrounded_fields']
            actual={u['path']:u['value'] for u in updates}
            for key,value in expected.get('updates',{}).items():
                if not equal(actual.get(key),value):errors.append('missing_or_changed_fact:'+key)
            for key in actual.keys()-expected.get('updates',{}).keys():errors.append('unexpected_fact:'+key)
    for phrase in expected.get('required_summary',[]):
        if phrase.casefold() not in decision.summary.casefold():errors.append('missing_disclosure:'+phrase)
    for phrase in expected.get('forbidden_summary',[]):
        if phrase.casefold() in decision.summary.casefold():errors.append('forbidden_claim:'+phrase)
    return errors

async def reserve_free_call(case_id,version):
    from sqlalchemy import select,text
    from app.database.session import AsyncSessionLocal
    from app.models.agent_task import AgentRun
    from app.jobs.task_agent_jobs import billing_limits
    from zoneinfo import ZoneInfo
    import os
    if billing_limits()[0]!='free' or os.getenv('PHILIXA_GROQ_QUOTA_ENABLED')!='1':
        raise RuntimeError('Confirmed free tier and shared quota gateway required')
    async with AsyncSessionLocal() as db:
        await db.execute(text('SELECT pg_advisory_xact_lock(73925,1)'))
        start=datetime.now(ZoneInfo('Asia/Kolkata')).replace(hour=0,minute=0,second=0,microsecond=0)
        runs=(await db.scalars(select(AgentRun).where(AgentRun.created_at>=start))).all()
        if sum(bool(r.state.get('free_call')) for r in runs)>=50:raise QuotaDeferred('local_cap')
        ident=secrets.token_hex(16)
        db.add(AgentRun(id=ident,task_id=hashlib.sha256(('prompt-eval:'+case_id).encode()).hexdigest()[:32],revision=0,
            state={'free_call':True,'reserved_usd':'0','evaluation':case_id,'prompt_version':version},created_at=datetime.now(timezone.utc)))
        await db.commit();return ident

async def release_unsent(ident):
    from app.database.session import AsyncSessionLocal
    from app.models.agent_task import AgentRun
    async with AsyncSessionLocal() as db:
        row=await db.get(AgentRun,ident)
        row.state={**row.state,'free_call':False,'not_sent':True};await db.commit()

async def evaluate(args):
    global REPORT
    REPORT=Path('data/agent-prompt-evaluation-live.json' if args.live else 'data/agent-prompt-evaluation.json')
    cases=json.loads(FIXTURES.read_text(encoding='utf-8'));rows=[]
    if args.cases:cases=[c for c in cases if c['id'] in args.cases.split(',')]
    if not cases:raise ValueError('No selected cases')
    report={'mode':'live_decisions' if args.live else 'offline_contract_replay',
        'dataset_sha256':hashlib.sha256(FIXTURES.read_bytes()).hexdigest(),
        'scope':'Single next-decision evaluation; no domain tools, native writes, review-time study or accounting accuracy benchmark.',
        'model_accuracy_verified':False,'domain_tools_executed':0,'tally_writes':0,'rows':rows}
    if args.resume:
        previous=json.loads(REPORT.read_text(encoding='utf-8'))
        if previous['dataset_sha256']!=report['dataset_sha256'] or previous['mode']!=report['mode']:
            raise ValueError('Evaluation dataset/mode changed; cannot resume')
        report=previous;rows=report['rows']
        report.setdefault('wait_events',[]).extend({k:r.get(k) for k in ('case_id','version','reason','retry_at')} for r in rows if r.get('model_calls')==0 and r.get('error_type'))
        rows[:]=[r for r in rows if not (r.get('model_calls')==0 and r.get('error_type'))]
        report.pop('stopped',None);report.pop('remaining_cases_unverified',None)
    completed={(r['case_id'],r['version']) for r in rows}
    by_id={c['id']:c for c in cases}
    for previous_row in rows:
        case=by_id.get(previous_row['case_id'])
        if case is None:raise ValueError('Resume selection must include all previous cases')
        _,schemas=tools_for(case['state'])
        if metadata(case['state'],schemas,previous_row['version'])!=previous_row['prompt']:
            raise ValueError('Prompt/config changed during held-out evaluation; freeze a new report instead')
    REPORT.parent.mkdir(exist_ok=True)
    for index,case in enumerate(cases):
        tools,schemas=tools_for(case['state'])
        for version in (('baseline','v2') if index%2==0 else ('v2','baseline')):
            if (case['id'],version) in completed:continue
            row={'case_id':case['id'],'prompt':metadata(case['state'],schemas,version),
                 'version':version,'estimated_reserved_tokens':estimate(request_payload(case['state'],schemas,prompt_version=version)),
                 'model_calls':0,'latency_ms':None,'usage':None,'active_review_time_ms':None}
            reservation=None;started=time.monotonic()
            try:
                if args.live:
                    reservation=await reserve_free_call(case['id'],version)
                    row['model_calls']=1
                    decision,usage=await choose(case['state'],schemas,prompt_version=version)
                    row.update(usage=usage,latency_ms=round((time.monotonic()-started)*1000))
                else:decision=Decision.model_validate(case['replay'])
                errors=grade(case,decision,tools)
                row.update(decision=decision.model_dump(),errors=errors,passed=not errors)
            except Exception as exc:
                if isinstance(exc,QuotaDeferred) and not exc.sent:
                    row['model_calls']=0
                    if reservation:await release_unsent(reservation)
                row.update(passed=False,error_type=type(exc).__name__,reason=getattr(exc,'reason',getattr(exc,'code','evaluation_error')),
                    retry_at=getattr(exc,'retry_at',None).isoformat() if getattr(exc,'retry_at',None) else None)
                rows.append(row);report['stopped']=True;report['remaining_cases_unverified']=True
                REPORT.write_text(json.dumps(summarize(report),ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'report':str(REPORT),'mode':report['mode'],'stopped':True,'reason':row['reason']}));return
            rows.append(row)
            REPORT.write_text(json.dumps(summarize(report),ensure_ascii=False,indent=2),encoding='utf-8')
    report.update(completed=True,live_model_evaluated=bool(args.live),
        comparison={v:{'cases':sum(r['version']==v for r in rows),'passed':sum(r['version']==v and r.get('passed',False) for r in rows),
            'estimated_reserved_tokens':sum(r['estimated_reserved_tokens'] for r in rows if r['version']==v)} for v in ('baseline','v2')})
    REPORT.write_text(json.dumps(summarize(report),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(REPORT),'mode':report['mode'],'comparison':report['comparison'],'model_accuracy_verified':report['model_accuracy_verified']}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--cases');parser.add_argument('--resume',action='store_true')
    asyncio.run(evaluate(parser.parse_args()))
