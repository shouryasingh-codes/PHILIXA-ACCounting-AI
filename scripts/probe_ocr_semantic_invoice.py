"""Local review-only probe. Explicit --live enables one Groq call per input.

No result is inserted into a production draft and no Tally operation exists here.
Input must be a saved RapidOCR token result with width/height; no expected answers
are sent to the model. Outputs are local diagnostic artifacts, not API responses.
"""
import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from app.services.ocr_semantic_invoice import request_payload, extract_review, Interpretation
from app.ai.groq_gateway import estimate, QuotaDeferred


async def main():
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('--output',required=True);p.add_argument('--live',action='store_true');p.add_argument('--json-mode',action='store_true');p.add_argument('--text-mode',action='store_true');a=p.parse_args()
    constrained=not (a.json_mode or a.text_mode)
    source=json.loads(Path(a.source).read_text());payload=request_payload(source,constrained=constrained)
    if a.text_mode:payload.pop('response_format')
    report={'input':Path(a.source).name,'posting_allowed':False,'estimated_reserved_tokens':estimate(payload), 'live':a.live,'constrained':constrained,'text_mode':a.text_mode,
        'started_at':datetime.now(timezone.utc).isoformat(),
        'request_sha256':hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    if a.live:
        try:
            def audit(wire):
                path=Path(a.output).with_suffix('.selection.json');path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(wire,indent=2),encoding='utf8')
            result,usage=await extract_review(source,constrained=constrained,text_mode=a.text_mode,audit_selection=audit);report.update(result=result,telemetry=usage,status='review_only')
        except QuotaDeferred as e:report.update(status='deferred',reason=e.reason,sent=e.sent)
        except Exception as e:
            report.update(status='failed',reason=type(e).__name__,
                http_status=getattr(e.__cause__,'code',None),provider_code=getattr(e,'provider_code',None))
            if hasattr(e,'errors'):
                report['schema_errors']=[{'path':list(x['loc']),'type':x['type']}
                    for x in e.errors(include_input=False,include_url=False)]
            if type(e) is ValueError and str(e).startswith(('Invalid or repeated source reference','Quantity evidence reused','Unknown extraction target','Unknown line assignment','Duplicate field assignment','Duplicate tax head','Too many invoice rows')):
                report['validation_reason']=str(e)
    else:report['status']='dry_run_no_provider_call'
    Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='result'}))
    if report.get('result'):print('rows',len(report['result']['lines']),'issues',report['result']['validation_issues'])


if __name__=='__main__':asyncio.run(main())
