"""Revisioned, one-question-at-a-time purchase review; never posts a voucher."""
import copy
import re
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from fastapi import HTTPException
from pydantic import BaseModel,Field,ConfigDict,ValidationError
from app.services import purchase_draft_service as drafts
from app.services.purchase_memory_service import catalog_for
from app.services import tally_gst_purchase as gst
from app.services.tally_connector import name,value,TallyError
from app.models.tally import TallyConnection


class Reply(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int|None=Field(default=None,ge=0)
    field:str|None=Field(default=None,max_length=100)
    answer:str|None=Field(default=None,max_length=500)
    resume:bool=False
    message:str|None=Field(default=None,max_length=4000)
    expected_revision:int|None=Field(default=None,ge=0)
    request_id:str|None=Field(default=None,pattern=r'^[a-f0-9-]{16,64}$')
    evidence_version:str|None=Field(default=None,max_length=64)
    accept_suggestions:bool=False
    prepare_preview:bool=False


def exact(rows,label):
    matches=[r for r in rows if name(r)==label]
    return matches[0] if len(matches)==1 else None


def frozen(principal):
    return SimpleNamespace(organization_id=principal.organization_id,user_id=principal.user_id,
                           role=principal.role,session_id=principal.session_id)


def adjustment_signature(content):
    import hashlib,json
    fields=[content.get('invoice_discount'),content.get('round_off'),
            [(l.get('discount_amount'),l.get('discount_percent')) for l in content['lines']]]
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()


def adjustments_known(content):
    return any(Decimal(str(v or 0))!=0 for v in [content.get('invoice_discount'),content.get('round_off'),
               *[l.get(k) for l in content['lines'] for k in ('discount_amount','discount_percent')]])


async def prepare(db,principal,row):
    company=await drafts.company_for(db,principal,row.company_id)
    catalog=await catalog_for(db,company)
    content=copy.deepcopy(row.content);lines=content.get('lines') or []
    if not lines:raise HTTPException(409,'Is purchase ko Bills review mein kholein.')
    suggestions=[]
    for index,line in enumerate(lines):
        item=exact(catalog['items'],line.get('item_name'))
        if item is not None and not line.get('unit'):
            unit=value(item,'BASEUNITS')
            if unit:line['unit']=unit;suggestions.append(f'Item {index+1} unit: {unit} (Tally master)')
        elif item is not None and line.get('unit')!=value(item,'BASEUNITS'):
            from app.services.purchase_native_context import history_unit_matches
            unit=value(item,'BASEUNITS')
            if history_unit_matches(line.get('unit'),unit,unit):
                from app.services.tally_validation import validate_item
                try:validate_item(catalog,item,unit)
                except TallyError:pass
                else:
                    line['unit']=unit
                    suggestions.append(f'Item {index+1}: bag/bags spelling ko exact Tally unit {unit} se resolve kiya; quantity unchanged.')
    cfg=await db.get(TallyConnection,principal.organization_id)
    if content.get('tax_treatment') and content.get('entry_date') and cfg and cfg.company==company.name:
        stamp=content['entry_date']
        party=exact(catalog['ledgers'],content.get('party_name'))
        if party is not None:
            try:
                detail=gst.effective(party.findall('LEDGSTREGDETAILS.LIST'),stamp)
                source=detail if detail is not None else party
                number=value(source,'GSTIN') or value(party,'PARTYGSTIN')
                gst.gstin_state(number)
            except TallyError:
                # Optional enrichment must not abort a saved conversation. Do not
                # fall back to today's GSTIN when historical master dates are invalid.
                suggestions.append('Supplier GST details Tally se verify nahi hui. Bill se check karna hoga; posting se pehle validation zaroori hai.')
            else:
                if not content.get('supplier_gstin'):content['supplier_gstin']=number;suggestions.append('Supplier GSTIN: '+number+' (Tally master)')
        purchase=exact(catalog['ledgers'],cfg.purchase_ledger)
        native=exact(catalog.get('companies',[]),company.name)
        if purchase is not None and native is not None:
            for index,line in enumerate(lines):
                item=exact(catalog['items'],line.get('item_name'))
                if item is None:continue
                try:rate,hsn,_,_=gst.master_rate(catalog,item,purchase,native,stamp)
                except (TallyError,ValueError,TypeError):continue
                for key,val in [('gst_rate',str(rate)),('hsn',hsn)]:
                    if line.get(key) is None:line[key]=val;suggestions.append(f'Item {index+1} {key}: {val} (Tally master; bill se check karein)')
    if content!=row.content:
        previous=await drafts.editable_action(db,row,row.revision)
        if previous and previous.status=='preview':previous.status='expired'
        row.content=drafts.DraftContent.model_validate(content).model_dump(mode='json')
        row.action_id=None;row.revision+=1;row.updated_at=datetime.now(ZoneInfo('UTC'))
        drafts.record_event(db,row,'system:masters','master_suggested',{'suggestions':suggestions})
        await db.commit()
        row=await drafts.scoped_draft(db,principal,row.id,lock=True)
    return row,catalog,suggestions


def question(content,catalog):
    suppliers=[r for r in catalog['ledgers'] if value(r,'PARENT')=='Sundry Creditors']
    if exact(suppliers,content.get('party_name')) is None:
        hint=(content.get('party_name') or '').casefold()
        candidates=[r for r in suppliers if hint and hint in name(r).casefold()] or suppliers
        return 'party_name','Kis supplier se kharida? Tally wala exact naam select karein.',[name(r) for r in candidates[:6]]
    for i,line in enumerate(content['lines']):
        if exact(catalog['items'],line.get('item_name')) is None:return f'{i}:item_name',f'Item {i+1}: Tally ka exact item naam?', [name(r) for r in catalog['items'][:12]]
        for key,prompt in [('quantity','Kitni quantity kharidi?'),('unit','Kaunsi unit?'),('rate','Ek unit ka rate kitna tha? GST se pehle wala rate bataiye.')]:
            if not line.get(key):return f'{i}:{key}',f'{line["item_name"]}: '+prompt,[]
    for key,prompt in [('invoice_number','Supplier ke bill ka invoice number kya hai?'),('entry_date','Bill par kaunsi date hai? Jaise 02-10-2026. Date khud se nahi badlegi.')]:
        if not content.get(key):return key,prompt,['Bill nahi mila'] if key=='invoice_number' else []
    if content.get('tax_treatment'):
        for key,prompt in [('supplier_gstin','Bill par supplier ka GSTIN kya hai?'),('place_of_supply','Bill ka place of supply state code kya hai? Jaise Rajasthan 08, Haryana 06.')]:
            if not content.get(key):return key,prompt,[]
        for i,line in enumerate(content['lines']):
            for key,prompt in [('gst_rate','Bill par GST rate kitna hai?'),('hsn','Bill par HSN kya hai?'),('taxable_amount','Is line ka bill par taxable amount kitna hai? Discount ke baad, GST se pehle.')]:
                if line.get(key) is None:return f'{i}:{key}',f'{line["item_name"]}: '+prompt,[]
        if not isinstance(content.get('expected_taxes'),dict) or not content['expected_taxes']:
            return 'taxes','Bill ka tax breakup bataiye: jaise CGST 90 SGST 90, ya IGST 180. Bill par jo likha hai wahi.',[]
    if content.get('invoice_total') is None:return 'invoice_total','Bill ka final total kitna hai? GST aur round-off ke baad wala amount.',[]
    return 'review','Details check karke “Details sahi hain” dabayein. Isse sirf validated preview banega, entry post nahi hogi.',['Details sahi hain']


async def state(db,principal,draft_id,prefix=''):
    from app.services import goods_receipt_service as receipts
    saved=await drafts.scoped_draft(db,principal,draft_id,lock=True)
    if receipts.receipt(saved):
        await drafts.editable_action(db,saved,saved.revision)
        return await receipts.state(db,principal,saved,prefix)
    from app.services.purchase_native_context import enabled
    if enabled():
        from app.services.purchase_agent import state as agent_state
        return await agent_state(db,principal,draft_id,prefix)
    principal=frozen(principal)
    row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
    await drafts.editable_action(db,row,row.revision)
    row,catalog,suggestions=await prepare(db,principal,row)
    technical_details=list(suggestions)
    suggestions=[]
    field,prompt,choices=question(row.content,catalog)
    native_history={}
    if field=='party_name' or field.endswith(':rate'):
        from app.services.purchase_native_context import conversation_history
        try:
            native_history=await conversation_history(db,principal,row,catalog)
        except (TallyError,ValueError,TypeError):
            native_history={'status':'unavailable','suggestions':[]}
        supplier_hint=native_history.get('supplier_suggestion')
        if field=='party_name' and supplier_hint:
            rates=supplier_hint['rates']
            detail=', '.join(f"{row.content['lines'][int(v['field'].split(':')[0])]['item_name']} ₹{v['value']}/{row.content['lines'][int(v['field'].split(':')[0])].get('unit') or 'unit'} ({v['entry_date']})" for v in rates)
            prompt=f"Pichhli matching Tally purchase: {supplier_hint['supplier']}, {detail}. Is baar bhi supplier aur rate wahi hain?"
            # Existing supplier-choice handler explicitly confirms the identity.
            choices=['Haan, supplier aur rates wahi hain',supplier_hint['supplier'],*[v for v in choices if v!=supplier_hint['supplier']]]
    from app.services import purchase_context
    evidence=await purchase_context.collect(db,principal,row,datetime.now(ZoneInfo('Asia/Kolkata')).date())
    rate_hint=next((v for v in native_history.get('suggestions',[]) if v['field']==field),None)
    rate_hint=rate_hint or next((v for v in evidence if v['field']==field),None)
    if rate_hint:
        suggestions.append(f"Suggested rate ₹{rate_hint['value']} — verified purchase ({rate_hint['entry_date']}); nayi purchase ka rate confirm karein.")
        prompt='Is baar bhi yahi rate hai? Suggested rate select karein ya naya rate likhein.'
        choices=[rate_hint['value']]
    if field=='review' and (row.extraction_metadata or {}).get('chat_adjustments_checked')!=adjustment_signature(row.content):
        if adjustments_known(row.content):
            field,prompt,choices='adjustments',f'Saved bill discount ₹{row.content.get("invoice_discount") or 0}, round-off ₹{row.content.get("round_off") or 0}; line discounts bhi retained hain. Original se check karein.',['Adjustments bill se match hain']
        else:field,prompt,choices='adjustments','Bill par discount/round-off ki extra adjustment hai? Nahi hai toh “Koi adjustment nahi”. Hai toh detailed review kholein.',['Koi adjustment nahi']
    summary=[]
    if field!='review':
        c=row.content
        summary=[]
        for line in c['lines']:
            parts=[line['item_name']] if line.get('item_name') else []
            if line.get('quantity'):parts.append(f"{line['quantity']} {line.get('unit') or ''}".strip())
            if line.get('rate'):parts.append(f"₹{line['rate']} per {line.get('unit') or 'unit'}")
            if parts:summary.append(' · '.join(parts))
        if c.get('party_name') and field!='party_name':summary.append('Supplier: '+c['party_name'])
        technical_details += ['Pending: '+', '.join(purchase_context.pending_labels(c))]
    if field=='review':
        c=row.content
        summary=['Company: '+(await drafts.company_for(db,principal,row.company_id)).name]
        summary += [f'Supplier: {c["party_name"]}',f'Invoice: {c["invoice_number"]} · {c["entry_date"]}']
        for line in c['lines']:
            summary.append(f'{line["item_name"]}: {line["quantity"]} {line["unit"]} × ₹{line["rate"]}'+(f' · discount ₹{line.get("discount_amount") or 0} / {line.get("discount_percent") or 0}% · GST {line.get("gst_rate")} · HSN {line.get("hsn")} · taxable ₹{line.get("taxable_amount")}' if c.get('tax_treatment') else ''))
        if c.get('tax_treatment'):
            summary += [f'Supplier GSTIN: {c.get("supplier_gstin")} · Place: {c.get("place_of_supply")}',f'Tax breakup: {c.get("expected_taxes")} · Discount: {c.get("invoice_discount")} · Round-off: {c.get("round_off")}']
            summary.append('Tally se liye GSTIN/HSN/rates bhi original bill se verify karein; master suggestion invoice evidence ki jagah nahi leta.')
        summary.append(f'Total: ₹{c.get("invoice_total")}')
        summary.extend('Source warning: '+str(w) for w in (row.extraction_metadata or {}).get('warnings',[])[:5])
    result={'response':'\n'.join([x for x in [prefix,*suggestions,*summary,prompt] if x]),
        'purchase_assistant':{'draft_id':row.id,'revision':row.revision,'field':field,'choices':choices},
        'purchase_details':technical_details,
        'gst_purchase_draft':{'id':row.id},'draft_id':row.id,
        'purchase_context':{'suggestions':native_history.get('suggestions',[]) or evidence,'native_history_status':native_history.get('status'), 'native_history_reason':native_history.get('reason'), 'supplier_suggestion':native_history.get('supplier_suggestion'), 'missing_fields':purchase_context.pending_fields(row.content),
                            'history_scope':'same company, exact native supplier/item/unit; fresh complete native history' if native_history.get('status')=='ready' else 'same company, exact supplier/item/unit; verified Philixa purchases fallback',
                            'history_limit':5000 if native_history.get('status')=='ready' else 100,'history_max_age_days':180}}
    if native_history.get('supplier_suggestion'):
        from app.services.purchase_native_context import suggestion_version
        result['purchase_assistant']['evidence_version']=suggestion_version(native_history['supplier_suggestion'])
    await db.commit()
    return result


async def answer(db,principal,draft_id,request):
    from app.services import goods_receipt_service as receipts
    saved=await drafts.scoped_draft(db,principal,draft_id,lock=True)
    if receipts.receipt(saved) or (request.field=='invoice_number' and receipts.no_bill(request.answer or '')):
        await drafts.editable_action(db,saved,saved.revision if request.resume else request.revision)
        if not receipts.receipt(saved):
            await receipts.begin(db,principal,saved)
            return await receipts.state(db,principal,saved)
        if request.resume:return await receipts.state(db,principal,saved)
        catalog=await catalog_for(db,await drafts.company_for(db,principal,saved.company_id))
        return await receipts.answer(db,principal,saved,request,catalog)
    from app.services.purchase_native_context import enabled
    if enabled() and (request.request_id or request.resume):
        from app.services.purchase_agent import answer as agent_answer
        return await agent_answer(db,principal,draft_id,request)
    principal=frozen(principal)
    if request.resume:return await state(db,principal,draft_id)
    row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
    await drafts.editable_action(db,row,request.revision)
    catalog=await catalog_for(db,await drafts.company_for(db,principal,row.company_id))
    field,_,_=question(row.content,catalog)
    if field=='review' and (row.extraction_metadata or {}).get('chat_adjustments_checked')!=adjustment_signature(row.content):field='adjustments'
    if request.field!=field:raise HTTPException(409,'Purchase details badal gayi. Current question dobara kholein.')
    text=(request.answer or '').strip()
    if text.casefold() in ('pause','stop','ruk ja','baad mein'):
        await db.commit();return {'response':'Purchase saved hai. Baad mein Resume purchase se continue karein. Koi entry post nahi hui.','gst_purchase_draft':{'id':row.id},'purchase_resume':row.id}
    content=copy.deepcopy(row.content)
    try:
        if field=='party_name' and text=='Haan, supplier aur rates wahi hain':
            from app.services.purchase_native_context import conversation_history,suggestion_version
            current=await conversation_history(db,principal,row,catalog)
            hint=current.get('supplier_suggestion')
            if not hint or request.evidence_version!=suggestion_version(hint):
                raise HTTPException(409,'History suggestion changed/stale. Current purchase dobara kholein.')
            text=hint['supplier']
            for evidence in hint['rates']:
                index,key=evidence['field'].split(':')
                if key!='rate' or content['lines'][int(index)].get('rate') is not None:
                    raise HTTPException(409,'Rate already changed; current purchase review karein.')
                content['lines'][int(index)]['rate']=evidence['value']
        if field=='review':
            if text.casefold() not in ('details sahi hain','details sahi hai'):raise ValueError('Summary check karke “Details sahi hain” select karein. Changes ke liye detailed review kholein.')
            # The existing compiler, duplicate check and human approval remain final gates.
            return await drafts.preview_draft(db,principal,row.id,drafts.DraftPreview(revision=row.revision))
        if field=='adjustments':
            if adjustments_known(content):
                if text.casefold()!='adjustments bill se match hain':raise ValueError('Saved adjustments original se check karein. Changes detailed review mein karein.')
            else:
                if text.casefold() not in ('koi adjustment nahi','nahi','no','none'):raise ValueError('Discount/round-off ko detailed review mein exact bill se bharein; guess nahi karunga.')
                content['invoice_discount']='0';content['round_off']='0'
        elif field=='taxes':
            pairs=re.findall(r'\b(CGST|SGST|IGST|UTGST)\s*[:=]?\s*(\d+(?:\.\d{1,2})?)\b',text,re.I)
            remainder=re.sub(r'\b(CGST|SGST|IGST|UTGST)\s*[:=]?\s*\d+(?:\.\d{1,2})?\b','',text,flags=re.I).strip(' ,;')
            if not pairs or remainder or len({h.upper() for h,v in pairs})!=len(pairs):raise ValueError('Is format mein bataiye: CGST 90 SGST 90, ya IGST 180.')
            content['expected_taxes']={h.upper():v for h,v in pairs}
        elif ':' in field:
            index,key=field.split(':');line=content['lines'][int(index)]
            if key in ('quantity','rate','gst_rate','taxable_amount'):
                text=re.sub(r'\s+(hai|hain|है)\s*$','',text,flags=re.I)
                text=re.sub(r'^(?:rate|quantity|qty)\s*[:=]?\s*','',text,flags=re.I)
                match=re.fullmatch(r'(?:₹\s*|Rs\.?\s*)?([0-9,]+(?:\.\d+)?)\s*%?',text,re.I)
                if key=='quantity' and not match:
                    unit_answer=re.fullmatch(r'([0-9,]+(?:\.\d+)?)\s*([A-Za-z]+)',text)
                    if unit_answer and unit_answer[2].casefold()==str(line.get('unit') or '').casefold():match=unit_answer
                if not match:raise ValueError('Sirf amount/number bataiye, jaise 350.00. Mixed details ke liye detailed review use karein.')
                line[key]=match[1].replace(',','')
            else:line[key]=text
        elif field=='entry_date':
            from app.services.invoice_extraction import parse_date
            if text.casefold() not in ('aaj','today') and not re.fullmatch(r'(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}[ -][A-Za-z]+[ -]\d{4})',text):raise ValueError('Sirf bill ki date bataiye, jaise 02-10-2026.')
            date=datetime.now(ZoneInfo('Asia/Kolkata')).date() if text.casefold() in ('aaj','today') else parse_date(text)
            if date is None:raise ValueError('Bill ki exact date bataiye, jaise 02-10-2026.')
            content[field]=str(date)
        elif field=='invoice_number':
            text=re.sub(r'^(?:invoice|bill)\s+(?:(?:number|no\.?)\s*)?[:=]?\s*','',text,flags=re.I)
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9./_-]{0,99}',text):raise ValueError('Sirf invoice reference bataiye, jaise INV/2026/123. Naye task ko invoice number nahi banaunga.')
            content[field]=text
        else:content[field]=text
        validated=drafts.DraftContent.model_validate(content)
        if field=='party_name' and exact([r for r in catalog['ledgers'] if value(r,'PARENT')=='Sundry Creditors'],text) is None:raise ValueError('Supplier exact match nahi hua. Listed Tally supplier select karein.')
        if field.endswith(':item_name') and exact(catalog['items'],text) is None:raise ValueError('Exact Tally item select karein.')
        saved=await drafts.save_draft(db,principal,row.id,drafts.DraftSave(revision=row.revision,content=validated))
        if field=='adjustments':
            row=await drafts.scoped_draft(db,principal,row.id,lock=True)
            row.extraction_metadata={**(row.extraction_metadata or {}),'chat_adjustments_checked':adjustment_signature(row.content)}
            await db.commit()
    except ValidationError as exc:
        await db.rollback()
        return await state(db,principal,draft_id,prefix='Jawab save nahi hua: '+exc.errors()[0]['msg'])
    except (ValueError,TypeError) as exc:
        await db.rollback()
        return await state(db,principal,draft_id,prefix='Jawab save nahi hua: '+str(exc).split('\n')[0])
    return await state(db,principal,draft_id)
