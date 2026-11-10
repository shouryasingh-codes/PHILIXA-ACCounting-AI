"""Bounded offline evaluator driver; never occupies a production worker.

Resumes distinct held-out cases, follows unsent quota admission reset, stops on
daily/local limits. It never retries a recorded transmitted failure.
"""
import json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path

deadline=time.monotonic()+900
for invocation in range(24):
    result=subprocess.run([sys.executable,'-m','scripts.evaluate_intent_routing','--live','--resume','--max-calls','50'],check=False)
    if result.returncode:raise SystemExit(result.returncode)
    path=Path('data/intent-router-golden-v4-live-heldout.json')
    if not path.exists():break
    report=json.loads(path.read_text(encoding='utf-8'))
    if report.get('summary',{}).get('heldout_complete'):break
    summary=report.get('summary',{})
    failures=sum(not row.get('correct_route',False) for row in report.get('rows',[]))
    if failures>int(summary.get('expected_cases',60)*0.05):
        print(json.dumps({'stopped':'95_percent_gate_unreachable','recorded_failures':failures}),flush=True)
        break
    block=report.get('blocked_case') or {}
    if report.get('setup_failure') or block.get('reason') in ('local_cap','daily_quota'):break
    if time.monotonic()>=deadline:break
    if block.get('reason')=='minute_quota' and block.get('retry_at'):
        delay=max(1,(datetime.fromisoformat(block['retry_at'])-datetime.now(timezone.utc)).total_seconds()+1)
        if delay>65:break
        print(json.dumps({'waiting_for_unsent_quota_reset_seconds':round(delay),'completed_cases':len(report['rows'])}),flush=True)
        time.sleep(min(delay,60))
    elif block.get('failure') in ('RoutingOutputError','ValueError'):
        # This case is already recorded failed. Continue other cases, no repair.
        continue
    else:break
