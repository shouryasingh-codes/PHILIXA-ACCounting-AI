"""Evidence-backed workflow selection; never invent bill/receipt facts."""
import copy,re
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app.services import purchase_draft_service as drafts,goods_receipt_service as receipts


def extract(text):
    s=text.casefold();facts={}
    if re.search(r'\b(?:agar|if|suppose|maan\s+lo)\b',s):return facts
    def capture(field,value,pattern):
        found=re.search(pattern,s)
        if found:
            if field in facts and facts[field]['value']!=value:raise HTTPException(422,'Conflicting purchase situation; current facts clear karein.')
            facts[field]={'value':value,'quote':text[found.start():found.end()]}
    capture('bill_status','pending',r'\b(?:bill|invoice)\s+(?:baad\s*(?:mein|me)|pending|abhi\s+nahi\s+mila|nahi\s+mila|nhi\s+mila|nahi\s+hai|nhi\s+hai|not\s+(?:yet\s+)?received)\b|\bno\s+(?:bill|invoice)\s+yet\b|बिल बाद में')
    capture('bill_status','available',r'\b(?:bill|invoice)\s+(?:mil\s+gaya|mila\s+hai|received|available|hai)\b|बिल मिल गया')
    capture('goods_status','received',r'\b(?:maal|goods|stock)\s+(?:aa\s*gaya|aaya\s+hai|mil\s+gaya|received)\b|\bgoods\s+(?:have\s+)?arrived\b|\b(?:bags?|bori)\s+(?:aa\s*gaye|aaye)\b|माल आ गया')
    capture('goods_status','not_received',r'\b(?:maal|goods|stock)\s+(?:abhi\s+)?(?:nahi|nhi|not)\s+(?:aaya|mila|received)\b')
    capture('rate_basis','tax_exclusive',r'\bgst\s+(?:se\s+pehle|alag(?:\s+lagega)?)\b|\brate\s+before\s+gst\b|\btax[- ]exclusive\b')
    capture('rate_basis','tax_inclusive',r'\bgst\s+(?:included|mila\s+kar)\b|\btax[- ]inclusive\b')
    capture('rate_basis','no_gst_charged',r'\b(?:supplier\s+)?gst\s+charge\s+(?:nahi|nhi)\b|\bno\s+gst\s+charged\b')
    today=re.search(r'\baaj\s+(?:maal\s+)?mila\b|\breceived\s+today\b',s)
    if today and not re.search(r'\b(?:not|never)\s+received\s+today\b',s):
        facts['goods_status']={'value':'received','quote':text[today.start():today.end()]}
        facts['received_on']={'value':datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat(),'quote':text[today.start():today.end()]}
    date=re.search(r'(?:received\s+(?:on|date)|maal\s+milne\s+ki\s+date)\s*[:=]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4})',s)
    if date:
        from app.services.invoice_extraction import parse_date
        value=parse_date(date[1])
        if value and value<=datetime.now(ZoneInfo('Asia/Kolkata')).date():facts['received_on']={'value':value.isoformat(),'quote':text[date.start():date.end()]}
    return facts


async def capture(db,principal,row,text):
    facts=extract(text)
    if not facts:return
    previous=copy.deepcopy((row.extraction_metadata or {}).get('purchase_situation',{}))
    for key,proof in facts.items():
        old=previous.get(key)
        if old and old['value']!=proof['value']:
            raise HTTPException(409,'Purchase situation changed. Review existing draft before switching bill/receipt workflow.')
    if facts.get('bill_status',{}).get('value')=='pending' and (row.content.get('invoice_number') or row.document_id):
        raise HTTPException(409,'Invoice/source already saved; review it before choosing bill-pending receipt.')
    previous.update(facts)
    if previous==(row.extraction_metadata or {}).get('purchase_situation'):return
    await drafts.editable_action(db,row,row.revision)
    if row.action_id:
        from app.models.tally import TallyAction
        action=await db.get(TallyAction,row.action_id)
        if action and action.status=='preview':action.status='expired'
    row.action_id=None;row.revision+=1
    row.extraction_metadata={**(row.extraction_metadata or {}),'purchase_situation':previous}
    drafts.record_event(db,row,principal.user_id,'situation_updated',{'evidence':facts})
    await db.commit()


async def state(db,principal,draft_id):
    row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
    situation=(row.extraction_metadata or {}).get('purchase_situation',{})
    bill=situation.get('bill_status',{}).get('value')
    goods=situation.get('goods_status',{}).get('value')
    if receipts.receipt(row):
        return await receipt_state(db,principal,row,situation)
    from app.services.purchase_agent import state as invoice_state
    result=await invoice_state(db,principal,draft_id)
    if goods=='not_received':
        result['response']='Maal abhi receive nahi hua. Working draft saved hai; stock badhane wali purchase/receipt entry abhi nahi banegi.'
        result['issues']=[*result.get('issues',[]),{'field':'goods_status','kind':'blocked','message':'Goods not received; supported received-goods workflow unavailable.'}]
        if result.get('proposal'):result['proposal']['can_prepare_preview']=False
        result['purchase_situation']=situation
        return result
    if bill=='pending':
        if goods!='received':
            result['response']='Bill pending hai. Maal mil chuka hai ya abhi aana hai? Abhi entry nahi hui.'
            result['situation_choices']=['Maal aa gaya','Maal abhi nahi aaya']
        else:
            core=[i for i in result.get('issues',[]) if i.get('kind')=='identity' or i.get('field','').endswith((':quantity',':unit',':rate'))]
            if not core:
                row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
                await receipts.begin(db,principal,row)
                return await receipt_state(db,principal,row,situation)
            result['issues']=core
            if not any(i.get('kind')=='identity' for i in core):result['response']='Maal received hai, bill pending hai. Receipt ke liye actual quantity/rate confirm karein; invoice/GST bill details abhi nahi chahiye.'
        result['purchase_situation']=situation
    elif not bill and not result.get('repeat_purchase') and not result.get('suggestions') and not row.content.get('invoice_number') and not getattr(row,'document_id',None):
        # Resolve identity/rate first. Ask the transaction situation together,
        # instead of sending every purchase through a full invoice form.
        if not any(i.get('kind')=='identity' for i in result.get('issues',[])):
            questions=['Bill mil gaya hai ya baad mein aayega?']
            if goods!='received':questions.append('Maal mil chuka hai toh kis date ko?')
            elif not situation.get('received_on'):questions.append('Maal kis date ko mila?')
            if any(line.get('rate') is None for line in row.content.get('lines',[])):questions.append('Actual rate bhi ek saath bata sakte hain.')
            result['response']=' '.join(questions)
            result['situation_choices']=['Bill mil gaya','Bill baad mein']
    return result


async def receipt_state(db,principal,row,situation):
    data=copy.deepcopy(receipts.receipt(row));changed=False
    for key in ('received_on','rate_basis'):
        if situation.get(key) and data.get(key)!=situation[key]['value']:
            data[key]=situation[key]['value'];changed=True
    if changed:await receipts.persist(db,principal,row,data,'receipt_situation_applied')
    result=await receipts.state(db,principal,row)
    missing=[]
    if not data.get('received_on'):missing.append('maal milne ki date')
    if not data.get('rate_basis'):missing.append('rate GST se pehle hai ya included')
    inclusive=data.get('rate_basis')=='tax_inclusive'
    if inclusive:missing.append('GST se pehle ki confirmed stock valuation; GST-included amount ko seedha stock cost nahi maan sakte')
    result['response']=('Maal received, bill pending. Bas '+', aur '.join(missing)+' bata dein; ek message kaafi hai.') if missing else 'Maal received, bill pending. Receipt Note ka final review taiyar kar sakte hain; purchase invoice/GST credit abhi nahi banega.'
    company=await drafts.company_for(db,principal,row.company_id)
    result['proposal']={'company':company.name,'content':row.content,'revision':row.revision,
        'totals':drafts.draft_totals(row.content),'provenance':{},'can_prepare_preview':False}
    result['purchase_assistant']['choices']=[]
    result['receipt_ready']=not missing
    result['issues']=[{'field':'receipt','kind':'missing','message':label} for label in missing]
    result['purchase_situation']=situation
    return result
