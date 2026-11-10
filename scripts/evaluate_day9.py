"""Reproducible offline benchmark. Never calls a cloud provider or real Tally.

Run: docker compose exec -T app python -m scripts.evaluate_day9
Golden fields are immutable inputs. Each stage has its own denominator; compiler
and posting use golden data so OCR failures cannot be hidden by downstream stages.
"""
import argparse,asyncio,copy,hashlib,io,json,platform,statistics,tempfile,time,uuid
import os
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import pymupdf
from PIL import Image
from app.services import invoice_extraction as extraction,tally_gst_purchase as gst
from app.services.bill_evaluation_service import flatten,equivalent
from app.services.local_invoice_ocr import extract_local_photo,parse_tokens
from app.services.tally_connector import tag,parse_xml,TallyError
import scripts.test_gst_purchase as masters

SOURCE=Path('scripts/fixtures/day9/golden.json');OUT=Path('data/day9')

def canonical(raw):
    raw=copy.deepcopy(raw)
    if raw.get('invoice_date'):
        date=extraction.parse_date(raw['invoice_date']);raw['invoice_date']=date.isoformat() if date else raw['invoice_date']
    return raw

def score(expected,actual):
    a=flatten(canonical(actual));e=flatten(expected)
    rows=[dict(field=k,expected=v,actual=a.get(k),correct=equivalent(k,v,a.get(k))) for k,v in e.items()]
    # Extra rows/tax heads are false positives, not free hallucinations.
    for k,v in a.items():
        extra_line=k.startswith('lines.') and int(k.split('.')[1])>=len(expected.get('lines',[])) and k.split('.')[-1] in ('item_name','quantity','unit','rate','discount_percent','gst_rate','hsn','taxable_amount')
        extra_tax=k.startswith('expected_taxes.') and k not in e
        if extra_line or extra_tax:rows.append(dict(field=k,expected=None,actual=v,correct=False))
    return dict(correct=sum(r['correct'] for r in rows),total=len(rows),exact_bill=all(r['correct'] for r in rows),
        correction_count=sum(not r['correct'] for r in rows),differences=[r for r in rows if not r['correct']])

def expected_fields(bill):return {k:copy.deepcopy(v) for k,v in bill.items() if k not in ('id','inter','taxable_total')}

def content(bill):
    result={k:copy.deepcopy(v) for k,v in bill.items() if k in ('supplier_gstin','place_of_supply','tax_treatment','invoice_number','invoice_discount','round_off','invoice_total','expected_taxes','lines')}
    result.update(party_name=bill['supplier_name'],entry_date=bill['invoice_date']);return result

def make_pdf(bill,alternate=False):
    doc=pymupdf.open();p=doc.new_page(width=842,height=595)
    def text(y,s):p.insert_text((30,y),s,fontsize=11)
    for y,s in [(30,'SYNTHETIC GOLDEN BILL - NOT A REAL INVOICE'),(55,'TAX INVOICE'),(75,bill['supplier_name']),(95,'GSTIN: '+bill['supplier_gstin']),(115,'Invoice No: '+bill['invoice_number']),(135,'Invoice Date: 02-Oct-2026'),(155,'Place of Supply: Haryana (06)'),(175,'Bill To / Buyer Details'),(195,bill['buyer_name']),(215,'GSTIN: 06ABCPE1234F1ZF')]:text(y,s)
    xs=[30,280,350,400,450,515,570,650,760];ys=[240,265,290,315]
    if alternate:xs=[30,240,310,380,430,500,565,650,760]
    for x in xs:p.draw_line((x,ys[0]),(x,ys[-1]))
    for y in ys:p.draw_line((xs[0],y),(xs[-1],y))
    rows=[['Description','HSN','Unit','Qty','Rate','Disc %','Taxable Amt','GST %']]
    rows += [[l['item_name'],l['hsn'],l['unit'],l['quantity'],l['rate'],l['discount_percent']+'%',l['taxable_amount'],l['gst_rate']+'%'] for l in bill['lines']]
    for i,row in enumerate(rows):
        for j,v in enumerate(row):p.insert_text((xs[j]+4,ys[i]+16),v,fontsize=9)
    y=340
    for head,amount in bill['expected_taxes'].items():text(y,head);text(y+17,amount);y+=40
    text(y,'Round Off');text(y+17,bill['round_off']);text(y+42,'Invoice Discount: '+bill['invoice_discount']);text(y+64,'Grand Total: '+bill['invoice_total'])
    result=doc.tobytes(garbage=4,deflate=True);doc.close();return result

def fingerprint_sources():
    files=[SOURCE,Path(__file__),Path('scripts/test_gst_purchase.py'),*[Path('app/services')/name for name in ('invoice_extraction.py','invoice_source_quality.py','local_invoice_ocr.py','purchase_draft_service.py','tally_gst_purchase.py','purchase_identity.py','bill_evaluation_service.py')]]
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

async def ocr_runtime():
    executable=os.getenv('PHILIXA_LOCAL_OCR_PYTHON','/app/data/local-ocr-venv/bin/python')
    code="""import json,hashlib
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path
root=Path(find_spec('rapidocr').origin).parent
print(json.dumps({'packages':{p:version(p) for p in ['rapidocr','onnxruntime','numpy','Pillow']},'bundled_models':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*.onnx')}}))
"""
    process=None
    try:
        process=await asyncio.create_subprocess_exec(executable,'-c',code,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        out,_=await asyncio.wait_for(process.communicate(),timeout=15)
        return json.loads(out) if process.returncode==0 else {'runtime':'unavailable'}
    except (OSError,TimeoutError):
        if process and process.returncode is None:
            process.kill();await process.communicate()
        return {'runtime':'unavailable'}

async def extraction_cases(bills,photos):
    rows=[]
    for index,bill in enumerate(bills):
        pdf=make_pdf(bill,alternate=index%2==1);path=OUT/(bill['id']+'.pdf');path.write_bytes(pdf)
        started=time.perf_counter();raw=extraction.extract_from_pdf_text_local(pdf)
        rows.append(dict(id=bill['id']+'-pdf',format='digital_pdf',method='embedded_text_actual_pdf',source_sha256=hashlib.sha256(pdf).hexdigest(),
            latency_ms=round((time.perf_counter()-started)*1000,2),provider_cost_usd='0',active_review_ms=None,manual_tally_baseline_ms=None,
            **score(expected_fields(bill),raw)))
    if photos:
        bill=bills[0];doc=pymupdf.open(stream=make_pdf(bill),filetype='pdf');png=doc[0].get_pixmap(matrix=pymupdf.Matrix(2,2)).tobytes('png');doc.close()
        for kind in ('png','jpeg'):
            buffer=io.BytesIO();image=Image.open(io.BytesIO(png));image.save(buffer,format='PNG' if kind=='png' else 'JPEG',quality=92)
            data=buffer.getvalue();OUT.joinpath('intra-mixed.'+kind).write_bytes(data);started=time.perf_counter()
            try:raw=await extract_local_photo(data);result=score(expected_fields(bill),raw)
            except Exception as exc:result={**score(expected_fields(bill),{}),'error':str(getattr(exc,'detail',exc))[:300]}
            rows.append(dict(id='intra-mixed-'+kind,format=kind,method='actual_local_ocr_image_bytes',source_sha256=hashlib.sha256(data).hexdigest(),latency_ms=round((time.perf_counter()-started)*1000,2),provider_cost_usd='0',active_review_ms=None,manual_tally_baseline_ms=None,**result))
    return rows

def mapping_cases():
    raw=dict(supplier_name='Supplier',invoice_number='MAP',invoice_date='2026-10-02',lines=[dict(item_name='Cement',quantity='1',unit='bags',rate='100')],total_amount='100',confidence={})
    rows=[]
    scenarios=[('exact','Supplier','Cement',['Supplier'],[dict(name='Cement',unit='bags')],True),
        ('fuzzy-supplier','Supplie','Cement',['Supplier'],[dict(name='Cement',unit='bags')],False),
        ('fuzzy-item','Supplier','Cemen',['Supplier'],[dict(name='Cement',unit='bags')],False),
        ('ambiguous-item','Supplier','Cement',['Supplier'],[dict(name='Cement',unit='bags'),dict(name='cement',unit='bags')],False),
        ('unknown-supplier','Unknown seller','Cement',['Supplier'],[dict(name='Cement',unit='bags')],False)]
    for label,supplier,item,suppliers,items,expected in scenarios:
        sample=copy.deepcopy(raw);sample['supplier_name']=supplier;sample['lines'][0]['item_name']=item
        result=extraction.verify_and_match(sample,dict(suppliers=suppliers,items=items))
        matched=bool(result['field_evidence']['party_name']['matched'] and result['line_evidence'][0]['item_name']['matched'])
        rows.append(dict(id=label,expected_automatic_identity=expected,actual_automatic_identity=matched,passed=matched==expected))
    alias_raw=copy.deepcopy(raw);alias_raw['supplier_name']='Approved seller alias';alias_raw['lines'][0]['item_name']='Approved cement alias'
    resolved=extraction.verify_and_match(alias_raw,dict(suppliers=['Supplier'],items=[dict(name='Cement',unit='bags')],approved_aliases={
        'supplier:approved seller alias':{'target':'Supplier'},'item:approved cement alias':{'target':'Cement'}}))
    alias_ok=resolved['party_name']=='Supplier' and resolved['lines'][0]['item_name']=='Cement' and len(resolved['approved_aliases'])==2
    rows.append(dict(id='explicit-approved-alias',expected_automatic_identity=True,actual_automatic_identity=alias_ok,passed=alias_ok))
    from app.services.purchase_memory_service import binding_valid
    from app.services.purchase_identity import master_identity,master_fingerprint
    catalog=masters.catalog();item=catalog['items'][0]
    approved=SimpleNamespace(kind='item',target='Cement',master_identity=master_identity(item),fingerprint=master_fingerprint(item))
    item.find('BASEUNITS').text='pcs';valid=binding_valid(approved,catalog)
    rows.append(dict(id='changed-master-invalidates-alias',expected_automatic_identity=False,actual_automatic_identity=valid,passed=not valid))
    return rows

async def accounting_posting(bills):
    accounting=[];posting=[]
    for bill in bills:
        cat=masters.catalog(bill['inter']);started=time.perf_counter()
        try:
            payload=gst.compile_purchase(cat,content(bill),masters.profile(),masters.config(),str(uuid.uuid4()))
            actual_taxes={r['head']:r['amount'] for r in payload['tax_ledgers']}
            passed=Decimal(payload['total'])==Decimal(bill['invoice_total']) and Decimal(payload['taxable_total'])==Decimal(bill['taxable_total']) and all(Decimal(actual_taxes.get(h,'0'))==Decimal(a) for h,a in bill['expected_taxes'].items()) and set(actual_taxes)==set(bill['expected_taxes'])
            accounting.append(dict(id=bill['id'],passed=passed,expected_total=bill['invoice_total'],actual_total=payload['total'],tax_ledgers=actual_taxes,latency_ms=round((time.perf_counter()-started)*1000,2)))
        except Exception as exc:
            accounting.append(dict(id=bill['id'],passed=False,error=str(exc)[:300]));posting.append(dict(id=bill['id'],passed=False,skipped='Accounting could not compile; not excluded from denominator'));continue
        vouchers=[];writes=[]
        async def post(xml):
            writes.append(xml);voucher=parse_xml(xml.encode()).find('.//VOUCHER');tag(voucher,'VOUCHERNUMBER','SYNTHETIC');vouchers.append(voucher)
        connector=SimpleNamespace(catalog=AsyncMock(return_value=cat),collection=AsyncMock(side_effect=lambda *args:vouchers),post=post)
        started=time.perf_counter()
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED':'1'}):
            first=await gst.execute('purchase_gst_post',connector,'Pilot Test','identity',payload,masters.config(),tmp+'/journal')
            again=await gst.execute('purchase_gst_post',connector,'Pilot Test','identity',payload,masters.config(),tmp+'/journal')
        tamper=[]
        for path in ('REFERENCE','ALLINVENTORYENTRIES.LIST/ACTUALQTY','LEDGERENTRIES.LIST[2]/AMOUNT'):
            altered=copy.deepcopy(vouchers[0]);element=altered.find(path)
            if element is None:tamper.append(False);continue
            element.text='incorrect';tamper.append(not gst.verify(altered,payload))
        posting.append(dict(id=bill['id'],passed=first['status']=='verified' and again['status']=='verified' and len(writes)==1 and all(tamper),
            status=first['status'],duplicate_delivery_writes=len(writes),tamper_cases=len(tamper),tamper_rejected=sum(tamper),transport='in_memory_simulated_Tally',latency_ms=round((time.perf_counter()-started)*1000,2)))
    for label in ('wrong-total','wrong-tax-rate','missing-tax-ledger','missing-item'):
        bill=bills[0];data=content(bill);catalog=masters.catalog();profile=masters.profile()
        if label=='wrong-total':data['invoice_total']='999'
        elif label=='wrong-tax-rate':data['lines'][0]['gst_rate']='5'
        elif label=='missing-tax-ledger':profile['ledgers'].pop('CGST')
        elif label=='missing-item':catalog['items']=[]
        try:gst.compile_purchase(catalog,data,profile,masters.config(),str(uuid.uuid4()));blocked=False
        except TallyError:blocked=True
        accounting.append(dict(id=label,expected='reject',passed=blocked))
    return accounting,posting

def summary(rows,key='passed'):return dict(passed=sum(bool(r.get(key)) for r in rows),total=len(rows))
async def main(args):
    OUT.mkdir(parents=True,exist_ok=True);manifest=json.loads(SOURCE.read_text());bills=manifest['bills']
    report=dict(schema_version=1,fixture_version=manifest['version'],run_at=datetime.now(timezone.utc).isoformat(),source_hashes=fingerprint_sources(),
        environment=dict(python=platform.python_version(),platform=platform.platform(),pymupdf=pymupdf.VersionBind),
        scope='synthetic_only',real_world_accuracy='unverified',accountant_evaluation='not_performed',manual_workflow_savings_percent=None,
        methodology='Extraction uses actual generated PDFs/images. Mapping, accounting and simulated posting are independently scored with golden inputs, not an end-to-end production accuracy claim. Failures remain in denominators. PDF latency measures parser execution; image latency includes isolated OCR process startup. Single observations only; no confidence intervals or population inference. Explicit zero discount evidence is scored strictly; missing zero differs from extracted zero even though accounting may default it to zero.',
        provider_cost_basis='Offline/local run: external provider API cost USD 0; hardware/electricity/model hosting costs not measured.',
        raw_ocr_replay_not_in_accuracy_denominator=True)
    report['extraction']=await extraction_cases(bills,not args.skip_photos)
    report['environment']['local_ocr']=await ocr_runtime() if not args.skip_photos else {'runtime':'not_exercised'}
    report['mappings']=mapping_cases();report['accounting'],report['posting']=await accounting_posting(bills)
    report['summary']=dict(extraction=summary(report['extraction'],'exact_bill'),mappings=summary(report['mappings']),accounting=summary(report['accounting']),posting=summary(report['posting']))
    report['field_accuracy']=dict(correct=sum(r['correct'] for r in report['extraction']),total=sum(r['total'] for r in report['extraction']))
    report['synthetic_evaluation']='complete' if not args.skip_photos else 'partial_pdf_only'
    report['quality_gate_passed']=all(v['passed']==v['total'] for v in report['summary'].values())
    OUT.joinpath('report.json').write_text(json.dumps(report,indent=2))
    lines=['# Day 9 synthetic accuracy evaluation','',f"Run: {report['run_at']}",'','**Real-world accuracy unverified. No accountant timing study or real anonymised bills were used.**','',report['methodology'],'']
    for stage,result in report['summary'].items():lines.append(f"- {stage}: {result['passed']}/{result['total']} complete cases correct.")
    lines+=['',f"Extraction fields correct: {report['field_accuracy']['correct']}/{report['field_accuracy']['total']}.",'','## Per-bill observations','']
    for row in report['extraction']:lines.append(f"- {row['id']}: {row['correct']}/{row['total']} fields; {row['correction_count']} golden field discrepancies (not observed human edits); {row['latency_ms']} ms; external API cost $0; human active review and manual Tally baseline unmeasured.")
    lines+=['','## Accuracy gaps','']
    for row in report['extraction']:
        if row.get('error'):lines.append(f"- {row['id']}: {row['error']}")
        for diff in row['differences']:lines.append(f"- {row['id']} / {diff['field']}: expected {diff['expected']!r}, observed {diff['actual']!r}.")
    lines+=['','## Reproduce','', '`docker compose exec -T app python -m scripts.evaluate_day9`','', 'Golden inputs: `scripts/fixtures/day9/golden.json`. Source hashes, raw counts, image/PDF hashes, runtime versions and every mismatch are retained in `data/day9/report.json`. Generated inputs are synthetic. Posting uses an isolated in-memory transport and SQLite journal; no real voucher is posted.','', 'Unknown timings/costs remain null. Golden correction count measures field discrepancies, not required/observed accountant edits (optional missing zeros may need no edit). A real savings study must compare the same bills with an accountant, including active review/correction, setup and exception-handling time; do not infer savings from parser latency.']
    OUT.joinpath('report.md').write_text('\n'.join(lines)+'\n')
    import shutil
    run_dir=OUT/'runs'/report['run_at'].replace(':','').replace('+','_')
    run_dir.mkdir(parents=True,exist_ok=True)
    for path in OUT.iterdir():
        if path.is_file() and path.suffix in ('.json','.md','.pdf','.png','.jpeg'):shutil.copy2(path,run_dir/path.name)
    print(json.dumps({'summary':report['summary'],'field_accuracy':report['field_accuracy'],'synthetic_evaluation':report['synthetic_evaluation'],'quality_gate_passed':report['quality_gate_passed'],'real_world_accuracy':'unverified'}))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--skip-photos',action='store_true',help='Partial fast check only; never marks full synthetic evaluation complete.');asyncio.run(main(parser.parse_args()))
