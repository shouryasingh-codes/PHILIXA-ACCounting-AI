"""Header-anchored embedded-text tables. No vendor names, source IDs or amounts.

Supports the gross/discount/taxable/tax/total presentation. Missing base rate
and unit remain unknown; tax-inclusive gross is never a pre-tax purchase rate.
"""
import re
from decimal import Decimal


def number(value):
    value=value.replace(',','').strip()
    return Decimal(value) if re.fullmatch(r'\d+(?:\.\d{1,2})?',value) else None


def rows(words,tolerance=3):
    result=[]
    for word in sorted(words,key=lambda w:(w[1],w[0])):
        if not result or abs(result[-1][0][1]-word[1])>tolerance:result.append([word])
        else:result[-1].append(word)
    return [sorted(row,key=lambda w:w[0]) for row in result]


def right_value(page,label,same_row_of=None):
    rects=page.search_for(label)
    if same_row_of:
        anchors=page.search_for(same_row_of)
        if len(anchors)!=1:return None
        rects=[rect for rect in rects if abs(rect.y0-anchors[0].y0)<6]
    if len(rects)!=1:return None
    rect=rects[0];words=sorted([w for w in page.get_text('words') if
        abs((w[1]+w[3])/2-(rect.y0+rect.y1)/2)<5 and w[0]>=rect.x1-1],key=lambda w:w[0])
    found=[];end=rect.x1
    for word in words:
        if found and word[0]-end>35:break
        found.append(word[4]);end=word[2]
    return ' '.join(found).strip() or None


def below_value(page,labels):
    for label in labels:
        rects=page.search_for(label)
        if len(rects)!=1:continue
        rect=rects[0]
        candidates=[w for w in page.get_text('words') if rect.y1-1<w[1]<rect.y1+35 and rect.x0-2<=w[0]<rect.x0+250]
        grouped=rows(candidates)
        if grouped:return ' '.join(w[4] for w in grouped[0])
    return None


def page_invoice(page,page_number):
    words=page.get_text('words');qty=[w for w in words if w[4].casefold() in ('qty','quantity')]
    if len(qty)!=1:return None
    header_y=qty[0][1]
    labels={'qty':('qty','quantity'),'gross':('gross',),'discount':('discount',),'other':('other',),
            'taxable':('taxable',),'CGST':('cgst',),'SGST':('sgst/','sgst'),'IGST':('igst',),
            'cess':('cess',),'total':('total',)}
    anchors={}
    for key,aliases in labels.items():
        matches=[w for w in words if abs(w[1]-header_y)<14 and w[4].casefold() in aliases]
        if len(matches)!=1:return None
        anchors[key]=(matches[0][0]+matches[0][2])/2
    if list(anchors.values())!=sorted(anchors.values()):return None
    totals=[w for w in words if w[4].casefold()=='total' and w[1]>header_y+15]
    if len(totals)!=1:return None
    total_y=totals[0][1]
    table_rows=rows([w for w in words if header_y+16<w[1]<total_y+5])
    extracted=[];totals_cells=None;description=[];last_y=header_y+15
    for row in table_rows:
        cells={};is_total=any(w[4].casefold()=='total' for w in row)
        for word in row:
            value=number(word[4])
            if value is None:continue
            center=(word[0]+word[2])/2
            nearest=min(anchors,key=lambda key:abs(anchors[key]-center))
            if nearest in cells:return None
            cells[nearest]=value
        required={'gross','discount','other','taxable','total'}
        if not required<=cells.keys():continue
        if is_total:totals_cells=cells;break
        if cells.get('qty',Decimal(0))<=0:return None
        if abs(cells['gross']-cells['discount']+cells['other']-cells['total'])>Decimal('.01'):return None
        taxes={key:cells[key] for key in ('CGST','SGST','IGST') if key in cells}
        if abs(cells['taxable']+sum(taxes.values(),Decimal(0))+cells.get('cess',Decimal(0))-cells['total'])>Decimal('.01'):return None
        band=rows([w for w in words if last_y<w[1]<row[0][1]-3])
        text_lines=[' '.join(w[4] for w in group) for group in band]
        hsn_lines=[text for text in text_lines if re.search(r'\bHSN\s*:',text,re.I)]
        if len(hsn_lines)!=1:return None
        hsn=re.search(r'HSN\s*:\s*(\d{4,8})\b',hsn_lines[0],re.I)
        rates=re.findall(r'(\d+(?:\.\d+)?)%\s*(CGST|SGST(?:/UGST)?|IGST)',hsn_lines[0],re.I)
        description=' '.join(text for text in text_lines if text not in hsn_lines).strip()
        if not hsn or not rates or not description or len(description)>200:return None
        extracted.append({'item_name':description,'quantity':str(cells['qty']),'rate':None,'unit':None,
            'amount':str(cells['taxable']),'taxable_amount':str(cells['taxable']),
            'hsn':hsn[1],'gst_rate':str(sum((Decimal(rate) for rate,_ in rates),Decimal(0))),
            'page_number':page_number,'confidence':0.0,
            'source_evidence':{key:{'value':str(value),'page':page_number,'confidence':0.0,
                'basis':'embedded table column; gross and discount may include tax'} for key,value in cells.items()}})
        last_y=max(w[3] for w in row)
    if not extracted or totals_cells is None:return None
    for key in ('gross','discount','other','taxable','CGST','SGST','IGST','cess','total'):
        values=[Decimal(line['source_evidence'][key]['value']) for line in extracted if key in line['source_evidence']]
        if values and (key not in totals_cells or abs(sum(values)-totals_cells[key])>Decimal('.01')):return None
    invoice=right_value(page,'Invoice Number:')
    date=right_value(page,'Invoice Date:') or right_value(page,'Date:',same_row_of='Invoice Number:')
    supplier=below_value(page,('Bill From:','Seller Details','Supplier:'))
    buyer=below_value(page,('Bill to / Ship to:','Bill To:','Buyer Details'))
    if not invoice or not re.fullmatch(r'[A-Za-z0-9/-]{1,100}',invoice) or not date or not supplier:return None
    gstins=set(re.findall(r'\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b',page.get_text()))
    nature=right_value(page,'Nature of Supply:')
    unsupported=['tax_inclusive_gross_requires_rate_review']
    if nature and 'service' in nature.casefold():unsupported.append('services')
    info={'invoice_number':invoice,'invoice_date':date,'supplier_name':supplier,'buyer_name':buyer,
        'page_numbers':[page_number],'invoice_total':str(totals_cells['total']),
        'supplier_gstin':next(iter(gstins)) if len(gstins)==1 else None,
        'expected_taxes':{key:str(totals_cells[key]) for key in ('CGST','SGST','IGST') if key in totals_cells},
        'unsupported_treatments':unsupported}
    return info,extracted


def extract_document(pdf):
    invoices=[];lines=[]
    for index,page in enumerate(pdf):
        parsed=page_invoice(page,index+1)
        if parsed is None:return None  # Never drop an unsupported/continuation page.
        invoice,items=parsed;invoices.append(invoice);lines.extend(items)
    if not invoices or len({invoice['invoice_number'] for invoice in invoices})!=len(invoices):return None
    single=len(invoices)==1;first=invoices[0]
    buyers={re.sub(r'\W','',str(invoice.get('buyer_name') or '')).casefold() for invoice in invoices}
    buyer=first.get('buyer_name') if len(buyers)==1 and '' not in buyers else None
    return {**first,'buyer_name':buyer,'invoice_total':first['invoice_total'] if single else None,
        'total_amount':first['invoice_total'] if single else None,'lines':lines,
        'multiple_invoices_detected':not single,'detected_invoices':invoices,
        'extraction_method':'embedded_layout','extraction_provider':'pymupdf',
        'confidence':{},'warnings':['Header-aligned embedded table extraction; review original. Base units and pre-tax rates were not inferred from tax-inclusive gross amounts.'],
        'source_page_issues':[]}
