"""Isolated real-file probe; never inserts a draft or posts to Tally.

Run inside app container with --url http://layout-reader:8097 when enabled.
Ground-truth answers are deliberately not accepted as extraction input.
"""
import argparse
import asyncio
import hashlib
import io
import json
import os
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path
import httpx
from PIL import Image
from app.services.invoice_layout import normalize


async def main():
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('--output',required=True)
    p.add_argument('--url',default='http://layout-reader:8097');p.add_argument('--live-model',action='store_true')
    args=p.parse_args();data=Path(args.source).read_bytes();original_hash=hashlib.sha256(data).hexdigest()
    if data.startswith(b'%PDF-'):
        from app.services.document_validation import inspect,preview
        if inspect(data)['page_count']!=1:raise ValueError('Single-page candidate only')
        data=preview(data,1)
    with Image.open(io.BytesIO(data)) as im:width,height=im.size
    started=time.monotonic();report={'run_id':uuid.uuid4().hex,'started_at':datetime.now(timezone.utc).isoformat(),'source_sha256':original_hash,'image_sha256':hashlib.sha256(data).hexdigest(),
        'posting_allowed':False,'live_model':args.live_model}
    try:
        async with httpx.AsyncClient(timeout=100,trust_env=False) as c:
            r=await c.post(args.url+'/read',content=data);r.raise_for_status();value=r.json()
        Path(args.output+'.reader.json').write_text(json.dumps(value,ensure_ascii=False))
        if value.get('status')!='ok':raise ValueError(value.get('reason','layout_failed'))
        layout=normalize(value['result'],data,width,height,value['manifest'])
        report.update(status='layout_ready',layout=layout.model_dump(mode='json'),telemetry=value.get('telemetry',{}))
        if args.live_model:
            from app.services.invoice_layout_review import interpret_layout
            def audit(value):report['selection']=value
            raw,telemetry=await interpret_layout(layout,audit,audit_wire=lambda value:report.update(wire=value))
            report.update(status='review_result',result=raw,usage=telemetry['usage'],model_calls=telemetry['model_calls'])
    except Exception as exc:
        report.update(status='failed',exception_type=type(exc).__name__,http_status=getattr(exc,'status_code',getattr(getattr(exc,'response',None),'status_code',getattr(exc.__cause__,'code',None))),provider_code=getattr(exc,'provider_code',None),structure=getattr(exc,'output_structure',None))
        from app.ai.groq_gateway import QuotaDeferred
        if isinstance(exc,QuotaDeferred):report.update(wait_reason=exc.reason,retry_at=str(exc.retry_at))
        # Do not serialize provider errors, credentials or unconstrained generated prose.
        if isinstance(exc,ValueError) and len(str(exc))<100:report['reason']=str(exc)
    report['latency_ms']=round((time.monotonic()-started)*1000)
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('layout','result','selection','wire')}))


if __name__=='__main__':asyncio.run(main())
