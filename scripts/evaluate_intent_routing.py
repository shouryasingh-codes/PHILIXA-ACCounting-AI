"""No domain tools execute. Offline coverage is NOT semantic model accuracy."""
import argparse,asyncio,hashlib,json,secrets,time
from pathlib import Path
from app.services.intent_router import VERSION,fast_route,validate_evidence

DATA=Path(__file__).parent/'fixtures'/'intent_routing'/'golden-v4.json'


def score(case,decision):
    expected=case['expected'];actual=decision.model_dump(mode='json')
    correct=all(actual[k]==expected[k] for k in ('intent','handler','relation'))
    for key in ('target_task_id','target_draft_id'):
        if key in expected:correct=correct and actual.get(key)==expected[key]
    if decision.handler=='domain_continuation':correct=correct and decision.target_task_id==case['context'].get('task_id')
    update=case.get('required_update')
    grounded_update=not update or any(u.path==update['path'] and u.value==update['value'] for u in decision.explicit_fields)
    return {'correct_route':correct,'intent_label_exact':actual['intent']==expected['intent'],
            'required_field_correct':grounded_update,'decision':actual}


def fingerprint_for(dataset=DATA):
    import inspect
    import app.services.intent_router_model as model
    return hashlib.sha256(Path(dataset).read_bytes()+model.SYSTEM.encode()+VERSION.encode()
        +json.dumps(model.WireRoute.model_json_schema(),sort_keys=True).encode()+inspect.getsource(model.resolve).encode()).hexdigest()


async def main(args):
    import app.services.intent_router_model as model
    dataset=Path(args.dataset) if args.dataset else DATA
    fingerprint=fingerprint_for(dataset)
    output=Path('data')/('intent-router-'+dataset.stem+'-'+('live-'+args.split if args.live else 'offline')+'.json')
    if args.case_id:output=output.with_name(output.stem+'-'+args.case_id+output.suffix)
    report={'version':VERSION,'fingerprint':fingerprint,'mode':'live_classifier_only' if args.live else 'offline_fast_path_coverage',
        'domain_tools_executed':False,'real_world_accuracy_verified':False,'rows':[]}
    if not args.resume and output.exists():
        old=json.loads(output.read_text(encoding='utf-8'))
        if old.get('rows'):
            archive=output.with_name(output.stem+'-'+old.get('fingerprint','unknown')[:12]+'-'+str(time.time_ns())+'.json')
            archive.write_bytes(output.read_bytes())
    if args.resume and output.exists():
        report=json.loads(output.read_text(encoding='utf-8'))
        if report['fingerprint']!=fingerprint:raise SystemExit('Dataset/prompt changed: previous report cannot be resumed.')
    if args.live:
        warm_started=time.monotonic()
        try:await model.warm()
        except Exception as exc:
            report['setup_failure']=type(exc).__name__
            output.parent.mkdir(exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps({'setup_failure':type(exc).__name__,'inference_calls':0}));return
        report['last_setup_ms']=round((time.monotonic()-warm_started)*1000)
    rows=report['rows'];done={r['id'] for r in rows};calls=0
    cases={c['id']:c for c in json.loads(dataset.read_text(encoding='utf-8'))['cases']}
    # Gate specified in the plan is handler + task relation. Preserve exact
    # intent-label accuracy separately; supplier reply/correction may overlap.
    for recorded in rows:
        if recorded.get('decision'):
            from app.services.intent_router import RouteDecision
            recorded.update(score(cases[recorded['id']],RouteDecision.model_validate(recorded['decision'])))
    for case in json.loads(dataset.read_text(encoding='utf-8'))['cases']:
        if args.live and case['split']!=args.split:continue
        if args.case_id and case['id']!=args.case_id:continue
        if case['id'] in done:continue
        decision=fast_route(case['message'],case['context']);started=time.monotonic()
        if decision is None and not args.live:
            rows.append({'id':case['id'],'category':case['category'],'split':case['split'],'path':'semantic_required'})
            continue
        if decision is None:
            if calls>=args.max_calls:break
            from app.database.session import AsyncSessionLocal
            from app.models.business_route import BusinessRoute
            from app.services.business_router import reserve_model
            from app.services.task_agent_service import now
            ident=secrets.token_hex(16);stamp=now()
            async with AsyncSessionLocal() as db:
                row=BusinessRoute(id=ident,organization_id='routing-synthetic-evaluation',user_id='synthetic',
                    request_id=ident,input_hash=fingerprint,status='routing',version=VERSION,context_data={},
                    decision={},result={},telemetry={},created_at=stamp,updated_at=stamp)
                db.add(row);await db.commit()
                try:
                    await reserve_model(db,row)
                    calls+=1
                    decision,usage=await model.classify(case['message'],case['context'],ident)
                    row.status='completed';row.decision=decision.model_dump(mode='json');row.telemetry={**row.telemetry,'usage':usage}
                    rows.append({'id':case['id'],'category':case['category'],'split':case['split'],
                        'path':'model',**score(case,decision),'usage':usage,'latency_ms':round((time.monotonic()-started)*1000)})
                except Exception as exc:
                    from app.ai.groq_gateway import QuotaDeferred
                    from app.services.intent_router_model import RoutingNotSent
                    if (isinstance(exc,QuotaDeferred) and not exc.sent) or isinstance(exc,RoutingNotSent):
                        row.telemetry={**row.telemetry,'reserved_usd':'0','free_call':False,'model_attempts':0}
                        calls=max(0,calls-1)
                    row.status='failed';row.result={'failure':type(exc).__name__,'reason':getattr(exc,'reason',None),
                        'diagnostic':getattr(exc,'diagnostic',None)}
                    report['blocked_case']={'id':case['id'],**row.result,
                        'retry_at':exc.retry_at.isoformat() if isinstance(exc,QuotaDeferred) and exc.retry_at else None}
                    if not isinstance(exc,QuotaDeferred):
                        rows.append({'id':case['id'],'category':case['category'],'split':case['split'],
                                     'path':'model','correct_route':False,'failure':type(exc).__name__})
                    await db.commit()
                    break
                await db.commit()
        else:
            validate_evidence(decision,case['message'],case['context'])
            rows.append({'id':case['id'],'category':case['category'],'split':case['split'],
                         'path':'deterministic',**score(case,decision),'latency_ms':round((time.monotonic()-started)*1000,3)})
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    expected_count=sum(c['split']==args.split for c in cases.values())
    graded=[r for r in rows if 'correct_route' in r]
    report['summary']={'cases_recorded':len(rows),'graded':len(graded),'correct_routes':sum(r['correct_route'] for r in graded),
        'semantic_required_unmeasured':sum(r['path']=='semantic_required' for r in rows),
        'live_calls_this_invocation':calls,'evaluated_split':args.split,'expected_cases':expected_count,'heldout_complete':args.live and args.split=='heldout' and len(rows)==expected_count,
        'intent_labels_exact':sum(r.get('intent_label_exact',False) for r in graded),
        'classification_gate_only':True,'gate_passed':args.live and not args.case_id and args.split=='heldout' and len(rows)==expected_count and sum(r.get('correct_route',False) for r in rows)/max(1,expected_count)>=0.95
            and all(r.get('required_field_correct',True) for r in rows)}
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(output),**report['summary'],'blocked':report.get('blocked_case')},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--resume',action='store_true')
    parser.add_argument('--case-id');parser.add_argument('--dataset');parser.add_argument('--split',choices=['development','heldout'],default='heldout')
    parser.add_argument('--max-calls',type=int,default=12)
    args=parser.parse_args()
    if not 1<=args.max_calls<=50:raise SystemExit('Bounded free-tier pilot: 1..50 calls per invocation.')
    asyncio.run(main(args))
