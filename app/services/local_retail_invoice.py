"""Conservative retail GST layout reader; printed tax summary is required.

Amounts in the item table include tax. They must never become taxable amounts.
Repeated HSNs, missing cells and inconsistent arithmetic require source review.
"""
import re
from decimal import Decimal, ROUND_HALF_UP


def parse_retail(tokens, width, height):
    from app.services.invoice_extraction import _to_decimal, parse_date
    norm = lambda s: re.sub('[^a-z0-9]', '', s.lower())
    cx = lambda t: (t['box'][0] + t['box'][2]) / 2
    cy = lambda t: (t['box'][1] + t['box'][3]) / 2
    def fail(reason):
        raise ValueError('Retail invoice: ' + reason + '; source review required.')
    def one(values, reason):
        if len(values) != 1: fail(reason)
        return values[0]
    def evidence(t):
        return dict(raw=t['text'], confidence=t['confidence'], bbox=t['box'],
                    image_width=width, image_height=height, page=1)
    def money(t):
        v = _to_decimal(t['text'])
        if v is None: fail('unreadable amount')
        return v
    def close(a, b):
        return abs(a-b) <= Decimal('.01')
    def right(label):
        # Restrict to the label baseline so due date / adjacent rows cannot win.
        candidates = [t for t in tokens if t['box'][0] >= label['box'][2]
                      and abs(cy(t)-cy(label)) < (label['box'][3]-label['box'][1])*.3]
        return one(candidates, 'missing or ambiguous label value')
    def label(names, start=0, stop=None):
        return one([t for t in tokens if norm(t['text']) in names
                    and t['box'][1] >= start and (stop is None or t['box'][1] < stop)], 'missing or ambiguous label')
    def columns(mapping, below=0):
        for t in tokens:
            if norm(t['text']) not in mapping or t['box'][1] < below: continue
            band = [x for x in tokens if abs(cy(x)-cy(t)) < 10 and norm(x['text']) in mapping]
            keys = [mapping[norm(x['text'])] for x in band]
            if len(keys) == len(set(mapping.values())) and len(set(keys)) == len(keys):
                return dict(zip(keys, band))
        fail('table columns not identified')
    heads = columns({'item':'item_name', 'hsn':'hsn', 'qty':'quantity', 'rate':'rate', 'gst':'gst', 'amount':'inclusive'})
    header_end = max(cy(t) for t in heads.values())
    totals = [t for t in tokens if norm(t['text'])=='total' and cy(t)>header_end]
    if not totals: fail('missing item-table footer')
    body_end = min(cy(t) for t in totals)
    return _finish(tokens, width, height, heads, header_end, body_end, norm, cx, cy,
                   fail, one, evidence, money, close, right, label, columns, parse_date)


def _finish(tokens, width, height, heads, header_end, body_end, norm, cx, cy,
            fail, one, evidence, money, close, right, label, columns, parse_date):
    from app.services.invoice_extraction import _to_decimal
    def cell_key(t, columns=heads):
        # Item descriptions can be much wider than their short header.
        if t['box'][0] < columns['hsn']['box'][0]-20: return 'item_name'
        return min(columns, key=lambda k: abs(cx(columns[k])-cx(t)))
    body = [t for t in tokens if header_end < cy(t) < body_end]
    names = sorted([t for t in body if cell_key(t)=='item_name'
                    and re.search('[A-Za-z]', t['text'])], key=cy)
    if not names or len(names)>100: fail('missing item descriptions')
    summary_title = label({'taxsummary'}, start=int(body_end))
    summary = columns({'hsnsac':'hsn', 'taxable':'taxable', 'rate':'gst_rate',
                       'cgst':'CGST', 'sgst':'SGST', 'totaltax':'tax'}, below=summary_title['box'][1])
    summary_end = max(cy(t) for t in summary.values())
    summaries = {}
    hsn_tokens = [t for t in tokens if cy(t)>summary_end and re.fullmatch(r'\d{4,8}', t['text'])
                  and abs(cx(t)-cx(summary['hsn']))<45]
    for anchor in hsn_tokens:
        hsn = anchor['text']
        if hsn in summaries: fail('repeated HSN requires explicit line allocation')
        cells = {}
        for t in tokens:
            if abs(cy(t)-cy(anchor))<8:
                key = min(summary, key=lambda k: abs(cx(summary[k])-cx(t)))
                cells.setdefault(key, []).append(t)
        summaries[hsn] = {k: one(cells.get(k, []), 'incomplete tax summary') for k in summary}
    lines=[]; used=set(); tax_sum=Decimal(0); taxable_sum=Decimal(0)
    for i, name in enumerate(names):
        upper = cy(names[i+1])-15 if i+1<len(names) else body_end-1
        row = [t for t in body if cy(name)-10 <= cy(t)<upper]
        cells = {}
        for t in row:
            key=cell_key(t)
            if key=='item_name' and t is not name: continue  # serial number is not description
            cells.setdefault(key, []).append(t)
        hsn_t=one(cells.get('hsn', []), 'missing HSN')
        hsn=hsn_t['text']
        if hsn in used or hsn not in summaries: fail('missing or ambiguous HSN summary')
        used.add(hsn); s=summaries[hsn]
        qty_t=one(cells.get('quantity', []), 'missing quantity/unit')
        qty=re.fullmatch(r'([0-9,]+(?:\.[0-9]+)?)\s*([A-Za-z][A-Za-z ./-]*)', qty_t['text'])
        if not qty: fail('quantity/unit unreadable')
        quantity=_to_decimal(qty[1]); rate_t=one(cells.get('rate', []), 'missing rate')
        rate=money(rate_t); taxable=money(s['taxable'])
        gst_cells=cells.get('gst', [])
        percent_t=one([t for t in gst_cells if re.fullmatch(r'\(?[0-9.]+%\)?', t['text'])], 'missing GST percentage')
        tax_t=one([t for t in gst_cells if t is not percent_t], 'missing line tax')
        gst=_to_decimal(percent_t['text'].strip('()%')); summary_gst=_to_decimal(s['gst_rate']['text'].strip('%'))
        if quantity is None or quantity<=0 or rate<=0 or gst is None or gst!=summary_gst: fail('invalid quantity/rate/GST')
        tax=money(tax_t); inc_t=one(cells.get('inclusive', []), 'missing inclusive amount')
        cgst=money(s['CGST']); sgst=money(s['SGST'])
        expected_half=(taxable*gst/200).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        if not all([close(quantity*rate, taxable), close(tax, money(s['tax'])),
                    close(tax, cgst+sgst), close(cgst, expected_half), close(sgst, expected_half),
                    close(taxable+tax, money(inc_t))]): fail('line or tax-summary arithmetic mismatch')
        ev={k:evidence(t) for k,t in dict(item_name=name, quantity=qty_t, unit=qty_t, rate=rate_t,
             hsn=hsn_t, gst_rate=percent_t, taxable_amount=s['taxable'], tax_amount=tax_t, inclusive_amount=inc_t).items()}
        lines.append(dict(page_number=1,item_name=name['text'],quantity=str(quantity),unit=qty[2].strip(),
                          rate=str(rate),hsn=hsn,gst_rate=str(gst),taxable_amount=str(taxable),amount=str(taxable),
                          confidence=min(e['confidence'] for e in ev.values()),source_evidence=ev))
        tax_sum+=tax; taxable_sum+=taxable
    if used!=set(summaries): fail('unmatched tax-summary rows')
    round_t=label({'roundoff'}, start=int(body_end), stop=summary_title['box'][1]); rounding=money(right(round_t))
    total_t=label({'total'}, start=int(cy(round_t)), stop=summary_title['box'][1]); total=money(right(total_t))
    taxes={head:str(money(right(label({head.lower()},start=int(body_end),stop=round_t['box'][1])))) for head in ('CGST','SGST')}
    if not close(sum(map(Decimal,taxes.values())),tax_sum) or not close(taxable_sum+tax_sum+rounding,total): fail('invoice totals mismatch')
    printed_taxable=money(right(label({'taxableamount'},start=int(body_end),stop=round_t['box'][1])))
    if not close(printed_taxable,taxable_sum): fail('taxable total mismatch')
    inv_t=right(label({'saleno','invoiceno','invoicenumber'},stop=int(header_end)))
    date_t=right(label({'date','invoicedate'},stop=int(header_end))); date=parse_date(date_t['text'])
    if not date: fail('invoice date unreadable')
    bill=label({'billto'},stop=int(header_end))
    buyer=one([t for t in tokens if t['box'][1]>=bill['box'][3]-6 and t['box'][1]<bill['box'][3]+10
               and abs(t['box'][0]-bill['box'][0])<15], 'buyer not identified')
    title=label({'taxinvoice'},stop=bill['box'][1])
    supplier=one([t for t in tokens if abs(cy(t)-cy(title))<15 and t['box'][2]<title['box'][0]
                  and len(t['text'])>5 and re.search('[A-Za-z]',t['text'])], 'supplier not identified')
    gst_t=one([t for t in tokens if re.fullmatch(r'GSTIN\s*:\s*[0-9A-Z]{15}',t['text'],re.I)
               and t['box'][1]<bill['box'][1]], 'supplier GSTIN missing')
    gstin=gst_t['text'].split(':',1)[1].strip().upper(); warnings=['Local photo extraction requires source review.']
    from app.services.tally_gst_purchase import gstin_state
    try: gstin_state(gstin)
    except Exception: warnings.append('Supplier GSTIN invalid; verify original.')
    pos=right(label({'placeofsupply'},stop=int(header_end)))['text']
    pos_match=re.fullmatch(r'(\d{2})\s*-\s*[A-Za-z ]+',pos)
    if not pos_match: fail('place of supply unreadable')
    from app.services.invoice_source_quality import pagination_issues
    page_issues=pagination_issues(['\n'.join(t['text'] for t in sorted(tokens,key=lambda t:(cy(t),cx(t))))])
    warnings.extend(page_issues)
    return dict(invoice_number=inv_t['text'],invoice_date=str(date),supplier_name=supplier['text'],buyer_name=buyer['text'],
                lines=lines,total_amount=str(total),invoice_total=str(total),round_off=str(rounding),
                expected_taxes=taxes,tax_treatment='regular_domestic_goods',supplier_gstin=gstin,place_of_supply=pos_match[1],
                warnings=warnings,confidence={k:t['confidence'] for k,t in dict(supplier_name=supplier,invoice_number=inv_t,invoice_date=date_t).items()},
                multiple_invoices_detected=False,detected_invoices=[],extraction_method='local_ocr',extraction_provider='rapidocr',
                source_tokens=tokens,source_page_issues=page_issues,source_layout='retail_gst_summary')
