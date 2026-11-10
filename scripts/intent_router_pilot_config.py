"""Reversible local review pilot; acceptance never enables real-company writes."""
import argparse,hashlib,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCES=('app/services/business_router.py','app/services/intent_router.py','app/services/intent_router_model.py',
         'app/services/business_command_service.py','app/api/v1/routes_business.py','app/web/business-chat.js',
         'app/services/task_agent_runtime.py','app/services/task_agent_model.py')

def implementation_hash():
    digest=hashlib.sha256()
    for name in SOURCES:
        digest.update(name.encode());digest.update(b'\0');digest.update((ROOT/name).read_bytes())
    return digest.hexdigest()

def eligible(report,acceptance,fingerprint,source_hash,*,browser_required=True):
    base=(report.get('summary',{}).get('gate_passed') is True
        and report.get('fingerprint')==fingerprint==acceptance.get('evaluation_fingerprint')
        and acceptance.get('implementation_sha256')==source_hash
        and acceptance.get('regressions_passed') is True)
    return bool(base and (not browser_required or (acceptance.get('browser_passed') is True
        and acceptance.get('zero_critical_errors') is True)))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['acceptance','enable','restore'])
    args=parser.parse_args()
    env=ROOT/'.env';backup=ROOT/'data'/'intent-router-pilot-flags.json'
    changes={'PHILIXA_INTENT_ROUTER_ENABLED':'1','PHILIXA_TASK_AGENT_REVIEW_ONLY':'1'}
    if args.action!='restore':
        from scripts.evaluate_intent_routing import fingerprint_for
        rp=ROOT/'data'/'intent-router-golden-v4-live-heldout.json'
        ap=ROOT/'data'/'intent-router-v3-acceptance.json'
        report=json.loads(rp.read_text(encoding='utf-8')) if rp.exists() else {}
        acceptance=json.loads(ap.read_text(encoding='utf-8')) if ap.exists() else {}
        if not eligible(report,acceptance,fingerprint_for(),implementation_hash(),browser_required=args.action=='enable'):
            raise SystemExit('Pilot stays OFF: matching current classifier gate and regression evidence required; enable also requires browser/critical-error acceptance.')
        if backup.exists():raise SystemExit('Restore the existing pilot backup before starting another pilot.')
    elif not backup.exists():raise SystemExit('No pilot backup exists; nothing changed.')
    content=env.read_text(encoding='utf-8-sig')
    if args.action!='restore':
        original={key:(m.group(1) if (m:=re.search(r'^'+key+r'=(.*)$',content,re.M)) else None) for key in changes}
        backup.parent.mkdir(exist_ok=True);backup.write_text(json.dumps(original),encoding='utf-8')
    else:changes=json.loads(backup.read_text(encoding='utf-8'))
    for key,value in changes.items():
        content=re.sub(r'^'+key+r'=.*\n?','',content,flags=re.M)
        if value is not None:content=content.rstrip()+'\n'+key+'='+value+'\n'
    env.write_text(content,encoding='utf-8')
    if args.action=='restore':backup.unlink()
    print('Previous flags restored.' if args.action=='restore' else 'Local review-only pilot configured. Restart app to apply; restore after acceptance.')

if __name__=='__main__':main()
