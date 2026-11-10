"""Development probe: cached actual reader, one fresh model call, no draft/write."""
import asyncio,io,json
from pathlib import Path
from PIL import Image
from app.services.document_validation import preview
from app.services.invoice_layout import normalize
from app.services.invoice_layout_review import interpret_layout,source_and_rows
async def main():
 p=Path('/app/data/public-invoice-preparation');image=preview((p/'timenet-philixa-test.pdf').read_bytes(),1);w,h=Image.open(io.BytesIO(image)).size
 v=json.loads((p/'layout-fixed-fresh3.json.reader.json').read_text());layout=normalize(v['result'],image,w,h,v['manifest']);r={'cached_reader':True,'fresh_model':True,'posting_allowed':False}
 try:
  raw,usage=await interpret_layout(layout,audit_wire=lambda v:r.update(wire=v));r.update(status='review_result',result=raw,usage=usage)
 except Exception as e:
  r.update(status='failed',error=type(e).__name__,status_code=getattr(e,'status_code',None),provider_code=getattr(e,'provider_code',None),structure=getattr(e,'output_structure',None),wait_reason=getattr(e,'reason',None))
  if isinstance(e,ValueError):r['reason']=str(e)[:150]
 (p/'layout-wire-diagnostic.json').write_text(json.dumps(r,default=str,indent=2))
 print(json.dumps({k:v for k,v in r.items() if k not in ('wire','result')},default=str))
 if 'wire' in r:
  print(json.dumps(r['wire']));_,rows=source_and_rows(layout)
  print('source_row_count',len(rows))
if __name__=='__main__':asyncio.run(main())
