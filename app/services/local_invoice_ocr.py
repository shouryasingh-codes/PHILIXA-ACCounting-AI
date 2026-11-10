"""Isolated local photo OCR with geometry-preserving, conservative invoice parsing."""
import asyncio,io,json,os,re,sys
from decimal import Decimal
from fastapi import HTTPException

def parse_tokens(tokens,width,height):
    from app.services.invoice_extraction import parse_date,_to_decimal
    def center(t):return ((t['box'][0]+t['box'][2])/2,(t['box'][1]+t['box'][3])/2)
    def normalize(text):return re.sub('[^a-z0-9]','',text.lower())
    # A separate evidenced layout handles tax-inclusive Amount columns. Do not
    # reinterpret them as the pre-tax amounts expected by the legacy reader.
    if any(normalize(t['text'])=='item' for t in tokens) and any(normalize(t['text'])=='taxsummary' for t in tokens):
        from app.services.local_retail_invoice import parse_retail
        return parse_retail(tokens,width,height)
    aliases={'description':'item_name','descriptionofgoods':'item_name','itemname':'item_name','hsn':'hsn','hsncode':'hsn','unit':'unit','uom':'unit','qty':'quantity','quantity':'quantity','rate':'rate','rateinr':'rate','disc':'discount_percent','discount':'discount_percent','discpercent':'discount_percent','taxableamt':'taxable_amount','taxableamount':'taxable_amount','gst':'gst_rate','gstpercent':'gst_rate','gstamt':'_tax','total':'_total','':'_serial'}
    aliases.update(qtyunit='quantity',quantityunit='quantity',raters='rate',taxablers='taxable_amount',taxablevalue='taxable_amount',no='_serial',sno='_serial',srno='_serial')
    # Punctuation-only tokens are never serial columns (a wrapped GST '%' is common).
    aliases.pop('',None)
    original_tokens=tokens
    headers=[t for t in tokens if normalize(t['text']) in aliases]
    descriptions=[t for t in headers if aliases[normalize(t['text'])]=='item_name']
    quantities=[t for t in headers if aliases[normalize(t['text'])]=='quantity']
    if descriptions and quantities:
        left=descriptions[0];right=min(quantities,key=lambda t:abs(center(t)[1]-center(left)[1]))
        dx=center(right)[0]-center(left)[0]
        slope=(center(right)[1]-center(left)[1])/dx if dx else 0
        if .01<abs(slope)<.12:
            # Align rows for parsing only; all evidence/crops retain original coordinates.
            tokens=[{**t,'_source_box':t['box'],'box':[t['box'][0],t['box'][1]-slope*center(t)[0],t['box'][2],t['box'][3]-slope*center(t)[0]]} for t in tokens]
            headers=[t for t in tokens if normalize(t['text']) in aliases]
    found=None
    for head in headers:
        band=[t for t in headers if abs(center(t)[1]-center(head)[1])<max(12,(head['box'][3]-head['box'][1]))]
        fields={aliases[normalize(t['text'])]:t for t in band}
        combined='quantity' in fields and normalize(fields['quantity']['text']) in ('qtyunit','quantityunit')
        if all(k in fields for k in ['item_name','quantity','rate','taxable_amount']) and ('unit' in fields or combined):found=fields;break
    if not found:raise ValueError('Local OCR could not identify invoice table columns; manual review required.')
    header_bottom=max(t['box'][3] for t in found.values())
    header_height=max(t['box'][3]-t['box'][1] for t in found.values())
    fragments=[]
    if 'gst_rate' in found:
        gst_head=found['gst_rate']
        fragments.extend(t for t in tokens if t['text'].strip()=='%' and abs(center(t)[0]-center(gst_head)[0])<header_height and gst_head['box'][1]<=t['box'][1]<=header_bottom+header_height)
    # Recognise only the spatially adjacent N + o./0. split of an explicit No. header.
    for first in tokens:
        if first['text'].strip()!='N' or abs(center(first)[1]-center(found['item_name'])[1])>header_height or first['box'][2]>=found['item_name']['box'][0]:continue
        tails=[t for t in tokens if t['text'].strip().lower() in ('o','o.','0','0.') and abs(center(t)[0]-center(first)[0])<header_height/2 and first['box'][3]-5<=t['box'][1]<=first['box'][3]+header_height]
        if len(tails)==1:
            found['_serial']=first;fragments.extend([first,tails[0]])
    if 'gst_rate' in found and 'hsn' not in found:raise ValueError('GST table HSN column unreadable; manual review required.')
    ordered=sorted(found.items(),key=lambda kv:center(kv[1])[0]);xs=[center(t)[0] for _,t in ordered]
    header_y=max(t['box'][3] for t in [*found.values(),*fragments]);end=height
    for t in tokens:
        if (t['text'].strip().upper() in ('CGST','SGST','IGST','ROUND OFF','TOTAL','HSN / TAX SUMMARY') or normalize(t['text']).startswith('gsttaxsummary')) and t['box'][1]>header_y:end=min(end,t['box'][1])
    body=[t for t in tokens if t['box'][1]>header_y and t['box'][3]<end]
    rows=[]
    for t in sorted(body,key=lambda t:center(t)[1]):
        cy=center(t)[1]
        row=next((r for r in rows if abs(r['y']-cy)<max(10,(t['box'][3]-t['box'][1])*.6)),None)
        if row is None:row={'y':cy,'tokens':[]};rows.append(row)
        row['tokens'].append(t)
    lines=[]
    for row in rows:
        cells={}
        for t in row['tokens']:
            idx=min(range(len(xs)),key=lambda i:abs(xs[i]-center(t)[0]));key=ordered[idx][0]
            cells.setdefault(key,[]).append(t)
        line={'page_number':1};evidence={}
        for k,ts in cells.items():
            text=' '.join(t['text'] for t in sorted(ts,key=lambda t:t['box'][0]));confidence=min(t['confidence'] for t in ts)
            bbox=[min(t.get('_source_box',t['box'])[0] for t in ts),min(t.get('_source_box',t['box'])[1] for t in ts),max(t.get('_source_box',t['box'])[2] for t in ts),max(t.get('_source_box',t['box'])[3] for t in ts)]
            evidence[k]={'raw':text,'confidence':confidence,'bbox':bbox,'image_width':width,'image_height':height,'page':1,'reread':ts[0].get('reread')}
            if k=='unit' and len(ts)==1:
                reads=ts[0].get('unit_rereads') or []
                candidates=[r.get('text','').strip() for r in reads]
                if len(reads)==2 and candidates[0]==candidates[1] and re.fullmatch(r'[A-Za-z]{1,20}',candidates[0]) and all(r.get('confidence',0)>=.98 for r in reads) and confidence<.8:
                    text=candidates[0]
                    evidence[k].update(value=text,corrected_from=ts[0]['text'],reread_consensus=reads)
                    # Keep initial confidence: photo still requires source review.
            if k.startswith('_'):continue
            if k=='quantity' and combined:
                pair=re.fullmatch(r'([0-9,]+(?:\.[0-9]+)?)\s*([A-Za-z][A-Za-z ./-]*)',text.strip())
                if not pair:raise ValueError('Combined quantity/unit unreadable; review original.')
                line['quantity']=str(_to_decimal(pair[1]));line['unit']=pair[2].strip()
                evidence['unit']={**evidence[k]}
                continue
            line[k]=text if k in ('item_name','unit','hsn') else str(_to_decimal(text.replace('%',''))) if _to_decimal(text.replace('%','')) is not None else None
        if not line.get('item_name') or not line.get('quantity') or not line.get('rate'):raise ValueError('Local OCR found an incomplete table row; no incomplete draft created.')
        line['amount']=line.get('taxable_amount');line['confidence']=min(e['confidence'] for e in evidence.values());line['source_evidence']=evidence;lines.append(line)
    if not lines or len(lines)>100:raise ValueError('Local OCR found no supported invoice rows.')
    text='\n'.join(t['text'] for t in sorted(tokens,key=lambda t:(center(t)[1],center(t)[0])))
    def labelled(pattern,prefer_below=False,only_label=None):
        for label in ([only_label] if only_label is not None else tokens):
            match=re.match(pattern,label['text'],re.I)
            if not match:continue
            inline=label['text'][match.end():].strip()
            if inline:return inline
            lx,ly=center(label);h=label['box'][3]-label['box'][1]
            right=[t for t in tokens if t is not label and abs(center(t)[1]-ly)<max(8,h*.8) and t['box'][0]>=label['box'][2]-5 and not t['text'].endswith(':')]
            below=[t for t in tokens if t['box'][1]>=label['box'][3]-3 and t['box'][1]<label['box'][3]+max(80,h*4) and abs(t['box'][0]-label['box'][0])<max(20,h*2) and not t['text'].endswith(':')]
            if prefer_below and below:return min(below,key=lambda t:t['box'][1])['text']
            if right:return min(right,key=lambda t:t['box'][0])['text']
            if below:return min(below,key=lambda t:t['box'][1])['text']
        return None
    inv_value=labelled(r'Invoice\s*No\.?\s*:\s*');date_value=labelled(r'Invoice\s*Date\s*:\s*')
    buyer_value=labelled(r'Bill To[^:]*$',prefer_below=True)
    titles=[t for t in tokens if normalize(t['text'])=='taxinvoice']
    supplier_value=None
    if titles:
        title=max(titles,key=lambda t:center(t)[1]);below=[t for t in tokens if t['box'][1]>title['box'][3] and t['box'][0]<width*.6 and t['box'][1]<title['box'][3]+120 and not t['text'].endswith(':')]
        if below:supplier_value=min(below,key=lambda t:t['box'][1])['text']
    total_value=labelled(r'Grand Total\s*:?\s*')
    gst=re.search(r'GSTIN\s*:\s*([0-9A-Z]{15})',text,re.I)
    taxes={}
    for head in ['CGST','SGST','IGST','UTGST']:
        value=labelled('^'+head+r'\s*$')
        if value and _to_decimal(value) is not None:taxes[head]=str(_to_decimal(value))
    warnings=[]
    if gst:
        from app.services.tally_gst_purchase import gstin_state as validate_gstin
        try:validate_gstin(gst.group(1).upper())
        except Exception:warnings.append('Supplier GSTIN invalid; verify original.')
    for i,line in enumerate(lines):
        for k,ev in line['source_evidence'].items():
            if ev['confidence']<.8:warnings.append(f'Line {i+1}: {k} needs review; original field evidence preserved.')
    date=parse_date(date_value)
    total_decimal=_to_decimal(total_value)
    if not inv_value or not supplier_value or re.match(r'GSTIN|Invoice|Phone|Email|Shop|Address',supplier_value,re.I) or not buyer_value or not date or total_decimal is None:raise ValueError('Local OCR header layout unsupported or incomplete; manual review required.')
    confidence={key:min([t['confidence'] for t in tokens if value and value.lower() in t['text'].lower()] or [0]) for key,value in [('supplier_name',supplier_value.strip()),('invoice_number',inv_value.strip()),('invoice_date',date_value.strip())]}
    if 'gst_rate' in found and (not taxes or not gst or any(not l.get('hsn') or l.get('gst_rate') is None for l in lines)):raise ValueError('GST fields incomplete; original review required.')
    raw={'invoice_number':inv_value.strip(),'invoice_date':str(date),'supplier_name':supplier_value.strip(),'buyer_name':buyer_value.strip(),'lines':lines,'total_amount':str(total_decimal),'invoice_total':str(total_decimal),'warnings':warnings,'confidence':confidence,'multiple_invoices_detected':False,'detected_invoices':[],'extraction_method':'local_ocr','extraction_provider':'rapidocr','source_tokens':original_tokens}
    from app.services.invoice_source_quality import pagination_issues
    raw['source_page_issues']=pagination_issues([text])
    warnings.extend(raw['source_page_issues'])
    if taxes and gst and all(l.get('hsn') and l.get('gst_rate') is not None for l in lines):
        raw.update(tax_treatment='regular_domestic_goods',supplier_gstin=gst.group(1).upper(),expected_taxes=taxes)
        pos=re.search(r'\(([0-9]{2})\)',labelled(r'Place of Supply\s*:\s*') or '');raw['place_of_supply']=pos.group(1) if pos else None
    rounding=re.search(r'Round Off\s*\n([+-]?[0-9,.]+)',text,re.I)
    if rounding:raw['round_off']=rounding.group(1)
    from app.services.invoice_extraction import invoice_discount_from_text
    discount_value=invoice_discount_from_text(text)
    if discount_value is None:
        pattern=r'^(?:Invoice|Bill|Overall) Discount\s*:?[ \t]*$'
        labels=[t for t in tokens if re.fullmatch(pattern,t['text'],re.I)]
        amounts={_to_decimal(labelled(pattern,only_label=t)) for t in labels}
        if len(amounts)==1:
            amount=amounts.pop()
            if amount is not None and amount>=0:discount_value=str(amount)
    if discount_value is not None:raw['invoice_discount']=discount_value
    return raw

async def extract_local_photo(data):
    layout=os.getenv('PHILIXA_LAYOUT_REVIEW_ENABLED','0')=='1'
    semantic=os.getenv('PHILIXA_OCR_SEMANTIC_REVIEW_ENABLED','0')=='1' or layout
    result=await _local_process(data,tokens_only=semantic)
    if not semantic:return result
    try:return parse_tokens(result['tokens'],result['width'],result['height'])
    except ValueError:
        if layout:
            from app.services.invoice_layout_review import extract_layout_review
            return await extract_layout_review(data)
        from app.services.ocr_semantic_invoice import extract_review
        from app.ai.provider import AIExtractionError
        try:raw,telemetry=await extract_review(result)
        except AIExtractionError as exc:
            detail='AI declined this document extraction; original saved for review.' if getattr(exc,'provider_code',None)=='model_refusal' else 'Invoice AI request unavailable; original saved. Retry later.'
            raise HTTPException(422 if getattr(exc,'provider_code',None)=='model_refusal' else 503,detail) from None
        except ValueError:raise HTTPException(422,'Invoice AI evidence/layout could not be validated. Original saved; no values guessed.') from None
        if not raw.get('row_coverage_verified') or not raw.get('lines'):
            raise HTTPException(422,'Invoice item coverage is incomplete. Original saved; review required.')
        problems=raw.get('validation_issues',[])
        if any('mismatch' in p or 'numeric source ambiguous' in p or 'incomplete source row' in p for p in problems):
            raise HTTPException(422,'Invoice source values do not reconcile or remain unreadable. Original saved; review required.')
        if any(l.get('taxable_amount') is None for l in raw['lines']):
            raw['unsupported_treatments']=['semantic_amount_basis_requires_review']
        raw['semantic_telemetry']=telemetry
        return raw


async def _local_process(data, *, tokens_only=False):
    executable=os.getenv('PHILIXA_LOCAL_OCR_PYTHON','/app/data/local-ocr-venv/bin/python')
    if not os.path.isfile(executable):raise HTTPException(503,'Local OCR runtime unavailable; install the isolated OCR environment.')
    proc=await asyncio.create_subprocess_exec(executable,'-m','app.services.local_invoice_ocr',*(['tokens'] if tokens_only else []),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:out,_=await asyncio.wait_for(proc.communicate(data),timeout=60)
    except (TimeoutError,asyncio.CancelledError):proc.kill();await proc.wait();raise HTTPException(503,'Local OCR timed out; retry or review original.')
    if proc.returncode:raise HTTPException(422,'Local OCR layout unsupported or unreadable. Review the original; no values guessed.')
    return json.loads(out)

def read_tokens(data):
    import contextlib
    import numpy as np
    from PIL import Image,ImageOps
    from rapidocr import RapidOCR
    from app.services.document_validation import inspect
    inspect(data)
    image=ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert('RGB');width,height=image.size
    with contextlib.redirect_stdout(sys.stderr):
        engine=RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads':2,'EngineConfig.onnxruntime.inter_op_num_threads':2})
        result=engine(np.array(image));tokens=[]
        for box,text,score in zip(result.boxes,result.txts,result.scores):
            b=[int(min(p[0] for p in box)),int(min(p[1] for p in box)),int(max(p[0] for p in box)),int(max(p[1] for p in box))]
            token={'text':text,'confidence':float(score),'box':b}
            if score<.8:
                crop=image.crop((max(0,b[0]-4),max(0,b[1]-4),min(width,b[2]+4),min(height,b[3]+4)))
                scale=min(3,2000/max(crop.size),(4000000/(crop.width*crop.height))**.5)
                crop=crop.resize((max(1,int(crop.width*scale)),max(1,int(crop.height*scale))))
                reread=engine(np.array(crop),use_det=False,use_cls=False)
                token['reread']={'text':' '.join(reread.txts or []),'confidence':min([float(s) for s in reread.scores] or [0])}
                # Two independently resized crops must agree before a unit cell
                # can use the reread. No Tally master or word substitution used.
                second=image.crop((max(0,b[0]-4),max(0,b[1]-4),min(width,b[2]+4),min(height,b[3]+4)))
                second_scale=min(2,scale*.67)
                second=second.resize((max(1,int(second.width*second_scale)),max(1,int(second.height*second_scale))))
                confirm=engine(np.array(second),use_det=False,use_cls=False)
                token['unit_rereads']=[token['reread'],{'text':' '.join(confirm.txts or []),'confidence':min([float(s) for s in confirm.scores] or [0])}]
            tokens.append(token)
    return {'tokens':tokens,'width':width,'height':height}

def run(data):
    source=read_tokens(data)
    return parse_tokens(source['tokens'],source['width'],source['height'])

if __name__=='__main__':
    try:
        data=sys.stdin.buffer.read(10*1024*1024+1)
        sys.stdout.write(json.dumps(read_tokens(data) if sys.argv[1:]==['tokens'] else run(data)))
    except Exception:sys.stderr.write('local_ocr_failed');sys.exit(2)
