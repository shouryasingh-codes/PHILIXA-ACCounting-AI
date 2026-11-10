"""Pure routing contracts/fast paths. No domain execution or permissions here."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.services.purchase_message import Mention, MessageFields, grounded

VERSION = 'intent-router-v3.4'


class ReportDate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    field: Literal['from_date','to_date','as_of']
    value: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    quote: str = Field(min_length=1,max_length=100)


class RouteDecision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    intent: Literal['help','greeting','smalltalk','stock_read','report_read','existing_read','purchase','bill_processing','document_question',
                    'task_reply','correction','unsupported','clarification','compound']
    relation: Literal['standalone','continue_current','switch_topic','unclear']
    handler: Literal['direct_reply','domain_read','domain_continuation','domain_document','agent','clarify']
    reported_context_relation: Literal['standalone','continue_current','switch_topic','unclear'] | None = None
    target_task_id: str | None = Field(default=None,pattern=r'^[a-f0-9]{32}$')
    target_draft_id: str | None = Field(default=None,pattern=r'^[a-f0-9]{32}$')
    document_fields: list[Literal['party_name','invoice_number','entry_date','invoice_total','lines','expected_taxes']] = Field(default_factory=list,max_length=6)
    item_name: str | None = Field(default=None,max_length=200)
    report: Literal['get_purchase_register','get_sales_register','get_bills_receivable',
                    'get_bills_payable','get_receipts_and_payments','get_cash_flow'] | None = None
    explicit_fields: list[Mention] = Field(default_factory=list,max_length=100)
    report_dates: list[ReportDate] = Field(default_factory=list,max_length=3)
    clarification: str | None = Field(default=None,max_length=250)
    conversational_reply: str | None = Field(default=None, min_length=1, max_length=600)
    reason: str = Field(max_length=100)

    @model_validator(mode='after')
    def valid_route(self):
        if self.conversational_reply is not None:
            if self.intent not in ('greeting','smalltalk','help','unsupported') or not self.conversational_reply.strip():
                raise ValueError('Unexpected conversational reply')
        if self.intent in ('smalltalk','help') and not self.conversational_reply:
            raise ValueError('Conversational reply required')
        legal={'help':{'direct_reply'},'greeting':{'direct_reply'},'smalltalk':{'direct_reply'},
               'stock_read':{'domain_read','clarify'},'report_read':{'domain_read','clarify'},
               'existing_read':{'domain_read'},
               'purchase':{'agent','clarify'},'bill_processing':{'agent','domain_continuation','clarify'},'document_question':{'domain_document','clarify'},
               'task_reply':{'domain_continuation','clarify'},'correction':{'domain_continuation','clarify'},
               'unsupported':{'clarify'},'clarification':{'clarify'},'compound':{'agent','clarify'}}
        if self.handler not in legal[self.intent]:raise ValueError('Illegal route combination')
        if self.target_draft_id and self.handler!='domain_document' and not (self.intent=='bill_processing' and self.handler=='domain_continuation'):raise ValueError('Unexpected document target')
        if self.document_fields and self.intent!='document_question':raise ValueError('Unexpected document fields')
        if self.handler=='domain_document' and not self.document_fields:raise ValueError('Document fields required')
        continuation=self.handler=='domain_continuation'
        if continuation != (self.relation=='continue_current'):
            raise ValueError('Continuation relation mismatch')
        if continuation and not self.target_task_id:raise ValueError('Missing continuation task')
        if not continuation and self.target_task_id:raise ValueError('Unexpected task target')
        if self.handler=='domain_read' and self.intent=='report_read' and not self.report:
            raise ValueError('Missing report')
        if self.explicit_fields and self.intent not in ('purchase','correction','task_reply'):
            raise ValueError('Unexpected accounting fields')
        if self.report_dates and self.intent!='report_read':raise ValueError('Unexpected report dates')
        if len({d.field for d in self.report_dates})!=len(self.report_dates):raise ValueError('Duplicate report date')
        return self


def validate_evidence(decision, message, context):
    if decision.handler=='domain_document' or decision.intent=='bill_processing' and decision.target_draft_id:
        candidates=[d for source in context.get('attachment_index',[]) for d in source.get('drafts',[])]
        if context.get('draft_id'):candidates.append({'id':context['draft_id']})
        if decision.target_draft_id and decision.target_draft_id not in {d['id'] for d in candidates}:
            raise ValueError('Unlisted document draft')
    if decision.target_task_id and decision.target_task_id != context.get('task_id'):
        raise ValueError('Unlisted task target')
    if decision.handler=='domain_continuation' and not context.get('can_continue'):
        raise ValueError('Current task cannot accept answers')
    if decision.intent=='correction' and not context.get('draft_id'):
        raise ValueError('Correction needs current draft')
    if decision.item_name and decision.item_name!='*' and decision.item_name.casefold() not in message.casefold():
        raise ValueError('Item query lacks message evidence')
    if decision.explicit_fields:
        grounded(message,MessageFields(updates=decision.explicit_fields,unsupported_reason=None))
    for date in decision.report_dates:
        grounded(message,MessageFields(updates=[Mention(path='entry_date',value=date.value,quote=date.quote)],unsupported_reason=None))
    dates={d.field:d.value for d in decision.report_dates}
    if dates.get('from_date','')>dates.get('to_date','9999'):raise ValueError('Invalid report range')
    if decision.intent=='report_read' and decision.handler=='domain_read':
        temporal=re.search(r'\b(?:today|yesterday|month|year|week|between|from|since|aaj|kal|mahine|saal|pichhle|pichle|january|february|march|april|may|june|july|august|september|october|november|december)\b|\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|आज|कल|महीन|साल',message,re.I)
        if temporal and not dates:raise ValueError('Requested report period unresolved')
    return decision


def normalize_command(text: str) -> str:
    """Normalize informal Hinglish, phonetic typos, attached postpositions/particles and repeated characters."""
    t = text.lower().strip()
    t = re.sub(r'[\?!.,।/\\_~@#\$%\^&\*\(\)\[\]\{\}]+', ' ', t)
    t = re.sub(r'(.)\1{2,}', r'\1', t)
    t = re.sub(r'([^elos\s])\1+', r'\1', t)
    t = re.sub(r'\b([a-z]{2,})(ki|ka|ke|ko|se|mai|mein|mey|pe|par)\b', r'\1 \2', t)
    t = re.sub(r'\b(daal|dal|chadha|chada|charha|bana|kar|kr|punch|post|maar|mar)(de|do|krde|krdo|dena|karo|kro)\b', r'\1 \2', t)
    t = re.sub(r'\b(bil|invoic|invoce)\b', 'bill', t)
    t = re.sub(r'\b(enery|entri|antri|entree)\b', 'entry', t)
    t = re.sub(r'\b(taly|talley|talli|tali)\b', 'tally', t)
    t = re.sub(r'\b(mai|mein|mey)\b', 'me', t)
    t = re.sub(r'\b(kro|karo)\b', 'kar do', t)
    t = re.sub(r'\b(krde|karde)\b', 'kar de', t)
    t = re.sub(r'\b(chada|charha)\b', 'chadha', t)
    t = re.sub(r'\bdal\b', 'daal', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def is_bill_entry_intent(message: str) -> bool:
    norm = normalize_command(message)
    if re.search(r'\b(?:what|kya|kiya|kitna|kitne|kaun|kaunsa|who|batao?|dikhao?|show|check|help|sukriya|thanks?|bye)\b', norm):
        return False
    if re.search(r'\b(?:aur|and|or)\b', norm):
        return False
    if re.search(r'\bprepare\b', norm):
        return False
    if re.search(r'\d+\s*(?:bags?|pcs?|nos?|kg|ton|box|boxes|rate|\/)', norm) or re.search(r'\brate\s*\d+', norm):
        return False
    has_entry_action = bool(re.search(r'\b(?:entry|enter|record|chadha(?:do|de|na)?|daal(?:do|de|na)?|punch(?:ing)?|post(?:ing)?|process(?:ing)?|maar(?:do|de|o)?|mar(?:do|de|o)?)\b', norm))
    has_make_voucher = bool(re.search(r'\b(?:bana(?:do|de|na|o)?)\b', norm) and re.search(r'\b(?:bill|voucher|entry)\b', norm))
    if not (has_entry_action or has_make_voucher):
        return False
    has_tally = bool(re.search(r'\btally\b', norm))
    has_bill = bool(re.search(r'\b(?:bill|invoice|voucher|parcha|challan|document|file|pdf)\b', norm))
    has_ref = bool(re.search(r'\b(?:is|isi|ye|yeh|yo|yahi|same|current|saved|uploaded|attached)\b', norm))
    has_verb = bool(re.search(r'\b(?:kar|kr|karo|kro|karna|krna|de|do|dena|kariye|kijiye|maar|maaro|mar|maro)\b', norm))
    return has_tally or has_bill or has_ref or (has_entry_action and has_verb)


def fast_route(message,context,*,selection=False,refresh=False):
    if selection or refresh:
        if not context.get('task_id') or not context.get('can_continue'):return None
        return RouteDecision(intent='task_reply',relation='continue_current',handler='domain_continuation',
                             target_task_id=context['task_id'],reason='typed_control')
    text=message.strip().casefold().rstrip('?!.।').strip()
    if text in {'hi','hii','hello','hey','hyy','namaste','नमस्ते'}:
        return RouteDecision(intent='greeting',relation='switch_topic' if context.get('task_id') else 'standalone',handler='direct_reply',reason='greeting')
    if re.fullmatch(r'(?:stock\s+(?:kitn[ae]\s+hai|batao?|dikhao)|(?:saare|sare|saara|sara|all)\s+(?:items?\s+ka\s+)?stock\s+(?:batao?|dikhao)|(?:show|check)\s+(?:all\s+)?(?:stock|inventory)|सभी सामान का स्टॉक बताओ)',text):
        return RouteDecision(intent='stock_read',relation='switch_topic' if context.get('task_id') else 'standalone',
                             handler='domain_read',item_name='*',reason='clear_stock_read')
    if context.get('can_continue') and context.get('focused'):
        choices=context.get('choices',[])
        matches=[v for v in choices if text==v.casefold()]
        if len(matches)==1:
            return RouteDecision(intent='task_reply',relation='continue_current',handler='domain_continuation',
                                 target_task_id=context['task_id'],reason='exact_current_offer')
        pending=re.fullmatch(r'(\d{1,2}):(rate|quantity)',context.get('pending_field') or '')
        if pending and context.get('draft_id') and re.fullmatch(r'\d+(?:\.\d+)?',text):
            return RouteDecision(intent='task_reply',relation='continue_current',handler='domain_continuation',
                target_task_id=context['task_id'],reason='typed_numeric_answer',explicit_fields=[Mention(
                    path=f'lines.{pending[1]}.{pending[2]}',value=text,quote=message.strip())])
    if text in {'haan','han','yes','done','ok','okay','जी','हाँ'}:
        return RouteDecision(intent='clarification',relation='standalone',handler='clarify',
            clarification='Kis saved task ya detail ke liye keh rahe hain? Current review se option chunein.',reason='ambiguous_acknowledgement')
    if is_bill_entry_intent(message):
        targets=[d['id'] for source in context.get('attachment_index',[]) for d in source.get('drafts',[])]
        target_draft=context.get('draft_id') or (targets[0] if len(targets)==1 else None)
        if not target_draft and len(targets)>1:
            return RouteDecision(intent='clarification',relation='unclear',handler='clarify',
                clarification='Kaunsa saved bill prepare karna hai? Current bill review se chunein.',reason='bill_action_target_unclear')
        if target_draft or targets:
            selected=target_draft or (targets[0] if targets else None)
            if context.get('can_continue') and context.get('task_id'):
                return RouteDecision(intent='bill_processing',relation='continue_current',handler='domain_continuation',
                    target_task_id=context['task_id'],target_draft_id=selected,reason='fast_bill_processing')
            return RouteDecision(intent='bill_processing',relation='switch_topic' if context.get('task_id') else 'standalone',
                handler='agent',target_draft_id=None,reason='fast_bill_processing')
        return RouteDecision(intent='purchase',relation='switch_topic' if context.get('task_id') else 'standalone',
            handler='agent',reason='fast_purchase')
    return None


def first_step(decision,context):
    """Only grounded draft operations; model cannot seed arbitrary tools/writes."""
    target_draft=decision.target_draft_id or context.get('draft_id')
    if decision.intent=='bill_processing' and (decision.handler=='domain_continuation' or decision.handler=='agent') and target_draft:
        return {'kind':'tool','tool':'purchase_context','arguments':{'draft_id':target_draft},'summary':'Saved bill ki purchase validation check kar rahi hoon.'}
    if not decision.explicit_fields:return None
    if decision.intent=='purchase' and context.get('company_id'):
        return {'kind':'tool','tool':'create_purchase_draft','arguments':{'message_index':0,
                'updates':[u.model_dump() for u in decision.explicit_fields]},'summary':'Purchase details se draft bana rahi hoon.'}
    if decision.handler=='domain_continuation' and context.get('draft_id'):
        return {'kind':'tool','tool':'apply_user_message','arguments':{'draft_id':context['draft_id'],
            'revision':context['draft_revision'],'message_index':context['message_count'],
            'updates':[u.model_dump() for u in decision.explicit_fields]},'summary':'Correction save kar rahi hoon.'}
    return None
