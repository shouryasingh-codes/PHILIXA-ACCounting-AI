"""Frozen-source offline QA. No cloud calls, native imports or user-workspace edits."""
import asyncio,copy,hashlib,json,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch,AsyncMock
from fastapi import HTTPException
from app.services import invoice_extraction as e,purchase_draft_service as drafts,tally_gst_purchase as gst,purchase_identity as identity
from app.services.tally_connector import TallyError
from scripts.evaluate_day9 import score
from scripts import test_gst_purchase as masters

ROOT=Path('scripts/fixtures/accountant-v1');OUT=Path('data/accountant-pack')
def catalog(bill):
 cat=masters.catalog('IGST' in bill['expected_taxes'])
 cat['companies'][0].set('NAME','Philixa Test')
 cat['ledgers'][0].set('NAME',bill['supplier_name'])
 for item,label in zip(cat['items'],['Philixa GST TEST Goods18','Philixa GST TEST Goods5']):item.set('NAME',label)
 return cat
def content(raw):
 return dict(party_name=raw.get('supplier_name'),entry_date=e.parse_date(raw.get('invoice_date')).isoformat() if e.parse_date(raw.get('invoice_date')) else None,
  **{k:copy.deepcopy(raw.get(k)) for k in ('invoice_number','supplier_gstin','place_of_supply','tax_treatment','invoice_discount','round_off','invoice_total','expected_taxes')},
  lines=[{k:l.get(k) for k in ('item_name','quantity','unit','rate','discount_percent','gst_rate','hsn','taxable_amount')} for l in raw.get('lines',[])])
def compile_read(raw,bill):
 cfg=masters.config();cfg['company']='Philixa Test'
 return gst.compile_purchase(catalog(bill),content(raw),masters.profile(),cfg,str(uuid.uuid4()))

async def main():
 manifest_bytes=(ROOT/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes);hashes=json.loads((ROOT/'hashes.json').read_text())
 for filename,digest in hashes.items():assert hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()==digest,'Frozen input changed: '+filename
 OUT.mkdir(parents=True,exist_ok=True)
 stamp=datetime.now(timezone.utc).isoformat();rows=[];raws={}
 settings=type('S',(),{'gemini_api_key':'','ai_api_key':''})()
 with patch.dict('os.environ',{'PHILIXA_LOCAL_OCR_ENABLED':'1'}),patch.object(e,'get_settings',return_value=settings),patch.object(e,'_post_invoice_json',AsyncMock(side_effect=AssertionError('Paid calls forbidden'))) as paid:
  for c in manifest['cases']:
   start=time.perf_counter();row=dict(id=c['id'],title=c['title'],format=c['format'],expected_outcome=c['expected_outcome'],input_sha256=hashes[c['filename']])
   try:
    media={'pdf':'application/pdf','png':'image/png','jpg':'image/jpeg'}[c['format']]
    raw=await e.extract_invoice_data((ROOT/c['filename']).read_bytes(),media);raws[c['id']]=raw
    row['extraction']=score(c['expected'],raw);row['method']=raw.get('extraction_method');row['warnings']=raw.get('warnings',[])
    kind=c['expected_outcome'];passed=False
    if kind=='review':
     drafts.validate_document_company(raw,'Philixa Test')
     p=compile_read(raw,c['expected']);passed=p['total']==c['expected']['invoice_total'];row['compiled_total']=p['total'];row['guard']='reviewed supported purchase compiles; no dispatch'
    elif kind=='block_total':
     checked=e.verify_and_match(raw,{'suppliers':[c['expected']['supplier_name']],'items':[{'name':'Philixa GST TEST Goods18','unit':'bags'}]})
     row['total_warning']=any('Invoice total mismatch' in w for w in checked['warnings'])
     try:compile_read(raw,c['expected'])
     except (TallyError,HTTPException,ValueError) as err:
      row['guard_reason']=str(getattr(err,'detail',err));passed=row['total_warning'] and 'total' in row['guard_reason'].lower()
     row['guard']='original bad total preserved; arithmetic must reject'
    elif kind in ('block_company','block_pages'):
     try:drafts.validate_document_company(raw,'Philixa Test')
     except HTTPException as err:
      reason=err.detail;passed=('mismatch' in reason.lower()) if kind=='block_company' else ('pages' in reason.lower());row['guard_reason']=reason
     row['guard']='production immutable-source company/page validation'
    elif kind=='duplicate':
     first=manifest['cases'][0];cat=catalog(c['expected'])
     a=identity.invoice_guard('qa-company:identity',cat,content(raw));b=identity.invoice_guard('qa-company:identity',cat,content(raws['C01']))
     passed=hashes[c['filename']]==hashes[first['filename']] and a==b;row['guard']='same source hash and company/supplier/reference/FY identity; persisted duplicate regression run separately'
    row['behavior_passed']=passed;row['passed']=row['extraction']['exact_bill'] and passed
    (OUT/(c['id']+'-extracted.json')).write_text(json.dumps(raw,indent=2))
   except Exception as err:
    row.update(passed=False,behavior_passed=False,error=str(getattr(err,'detail',err))[:500])
    row.setdefault('extraction',score(c['expected'],{}))
   row['latency_ms']=round((time.perf_counter()-start)*1000)
   rows.append(row);print(c['id'], 'PASS' if row['passed'] else 'FAIL',row.get('error') or row.get('extraction',{}).get('differences'),flush=True)
  paid.assert_not_awaited()
 for filename,digest in hashes.items():assert hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()==digest,'Input changed during run'
 report=dict(version=manifest['version'],run_at=stamp,scope='synthetic_only; first results and failures retained',manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),source_hashes={f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in ['app/services/invoice_extraction.py','app/services/local_invoice_ocr.py',__file__]},cases=rows,
  passed=sum(r['passed'] for r in rows),total=len(rows),unique_invoice_count=9,cloud_calls=0,native_posting=False,real_world_accuracy='unverified',accountant_time_savings=None)
 (OUT/'report.json').write_text(json.dumps(report,indent=2));run=OUT/'runs'/stamp.replace(':','').replace('+','_');run.mkdir(parents=True,exist_ok=True);(run/'report.json').write_text(json.dumps(report,indent=2))
 for c in manifest['cases']:
  p=OUT/(c['id']+'-extracted.json')
  if p.exists():(run/p.name).write_bytes(p.read_bytes())
 print(json.dumps({'passed':report['passed'],'total':report['total'],'real_world_accuracy':report['real_world_accuracy']}),flush=True)
if __name__=='__main__':asyncio.run(main())
