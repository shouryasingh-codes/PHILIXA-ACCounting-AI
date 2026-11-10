"""Score labelled probe results. Missing held-out labels/results never become passes.

Manifest entries: {split, layout_id, source_sha256, result, expected:{header,lines}}
Numbers remain strings; line order and every critical value must match.
"""
import argparse
import hashlib
import json
from pathlib import Path
from decimal import Decimal, InvalidOperation

CRITICAL=('quantity','unit','rate','amount','hsn','gst_rate')


def equal(a,b,key):
    if a is None or b is None:return a is b
    if key in ('quantity','rate','amount','gst_rate','invoice_total','subtotal'):
        try:return Decimal(str(a).replace(',',''))==Decimal(str(b).replace(',',''))
        except InvalidOperation:return False
    return ' '.join(str(a).casefold().split())==' '.join(str(b).casefold().split())


def score(entry):
    path=Path(entry['result'])
    if not entry.get('expected') or not path.is_file():return {'status':'pending','layout_id':entry['layout_id']}
    value=json.loads(path.read_text());failures=[]
    if value.get('source_sha256')!=entry['source_sha256']:return {'status':'invalid_source','layout_id':entry['layout_id']}
    if value.get('status')!='review_result':return {'status':'blocked','layout_id':entry['layout_id'],'reason':value.get('reason',value.get('exception_type'))}
    raw=value['result'];expected=entry['expected'];checks=0;passed=0
    for key,want in expected['header'].items():
        checks+=1;match=equal(raw.get(key),want,key);passed+=int(match)
        if not match:failures.append('header.'+key)
    got=raw.get('lines',[]);want=expected['lines'];checks+=1
    if len(got)==len(want):passed+=1
    else:failures.append('line_count')
    for i,line in enumerate(want):
        for key,wanted in line.items():
            checks+=1;match=i<len(got) and equal(got[i].get(key),wanted,key);passed+=int(match)
            if not match:failures.append(f'lines.{i}.{key}')
    return {'status':'pass' if not failures else 'fail','layout_id':entry['layout_id'],
            'checks':checks,'passed':passed,'failures':failures,'latency_ms':value.get('latency_ms'),'usage':value.get('usage')}


def report(entries, acceptance=None):
    rows=[dict(score(e),split=e['split']) for e in entries]
    held=[r for r in rows if r['split']=='held_out'];checks=sum(r.get('checks',0) for r in held)
    accuracy=sum(r.get('passed',0) for r in held)/checks if checks else None
    complete=len({r['layout_id'] for r in held})>=10 and all(r['status'] in ('pass','fail') for r in held)
    accuracy_gate=bool(complete and accuracy>=.95 and all(r['status']=='pass' for r in rows))
    required=('three_fresh_repetitions','resource_budgets','normal_worker_browser','source_crops','regressions')
    acceptance=acceptance or {}
    return {'rows':rows,'held_out_field_exact_match':accuracy,'held_out_complete':complete,
            'accuracy_gate_passed':accuracy_gate,'pending_acceptance':[k for k in required if acceptance.get(k) is not True],
            'pilot_gate_passed':accuracy_gate and all(acceptance.get(k) is True for k in required),
            'real_world_accuracy_verified':False,'posting_allowed':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('manifest');p.add_argument('--output',required=True);a=p.parse_args()
    Path(a.output).write_text(json.dumps(report(json.loads(Path(a.manifest).read_text())),indent=2))
