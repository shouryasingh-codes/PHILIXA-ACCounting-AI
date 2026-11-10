"""Bounded, model-directed orchestration. Domain adapters own all authority.

This module deliberately has no SQL, XML, credential or posting implementation.
Persist callbacks must commit before returning; a pending write is reconciled,
never automatically executed again after an interrupted call.
"""
import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field


class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['tool', 'needs_input', 'needs_approval', 'finish']
    tool: str | None
    arguments: dict
    summary: str = Field(max_length=1000, description='Internal next-step rationale; never shown directly to the user.')
    user_response: str = Field(default='', max_length=1000, description='Direct user-facing question or answer in the user language. No third-person planning or instructions to another assistant.')


class ToolResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['ok', 'waiting_context', 'needs_input', 'needs_approval',
                    'queued', 'verification_pending', 'failed']
    data: dict = Field(default_factory=dict)
    verified: bool = False


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    arguments: type[BaseModel]
    effect: Literal['read', 'draft', 'write']
    authorize: Callable[[dict], Awaitable[None]]
    execute: Callable[[dict], Awaitable[ToolResult]]


class TransientReadError(Exception):
    """Adapter-classified temporary failure; other errors must not retry."""


class ExecutionNotStarted(Exception):
    """The adapter guarantees that no domain operation was invoked."""

def settled_stock_answer(state):
    """A server-rendered stock result needs no model narration/second call."""
    if state.get('outcome')!='answer':return None
    events=state.get('executions',[])
    if not events or events[-1].get('tool')!='read_stock' or any(e.get('effect')!='read' or e.get('status')!='settled' for e in events):return None
    latest=(state.get('observations') or [{}])[-1]
    data=latest.get('data',{})
    if not data.get('stock_results') or not data.get('response'):return None
    return latest

def direct_stock_question(state):
    if state.get('outcome')!='answer' or not state.get('company_id'):return False
    text=(state.get('messages') or [''])[-1].strip().casefold()
    return bool(re.fullmatch(r'(?:stock\s+kitn[ae]\s+hai|(?:saara|sara|all)\s+stock\s+(?:dikhao|batao)|(?:show|check)\s+(?:all\s+)?(?:stock|inventory)|inventory\s+dikhao|सभी सामान का स्टॉक बताओ)[?!.।\s]*',text))

def format_tally_blockers(state: dict, data: dict) -> str | None:
    """Articulate Tally blockers directly in conversational Hinglish:
    - Mention supplier name and total amount.
    - State clearly which masters are missing in Tally (e.g. TimeNet Solutions is not in Sundry Creditors; 6 stock items missing).
    - Ask clearly: 'Kya main Tally me [Supplier] ka Sundry Creditor ledger bana doon ya kisi existing ledger se map karna hai?'
    """
    issues = data.get('issues') or []
    proposal = data.get('proposal') or {}
    content = proposal.get('content') or {}

    supplier_missing = any(v.get('kind') == 'identity' and v.get('field') == 'party_name' for v in issues)
    missing_items = [v for v in issues if v.get('kind') == 'identity' and str(v.get('field', '')).endswith(':item_name')]

    if not supplier_missing and not missing_items:
        return None

    # 1. Supplier Name
    supplier = (content.get('party_name') or '').strip()
    if not supplier:
        for source in state.get('attachment_sources', []):
            for d in source.get('drafts', []):
                p = (d.get('content', {}).get('party_name') or '').strip()
                if not p:
                    p = ((d.get('extraction_metadata') or {}).get('source_evidence', {}).get('supplier_name', {}).get('raw') or '').strip()
                if p:
                    supplier = p
                    break
            if supplier:
                break
    if not supplier:
        supplier = 'Supplier'

    # 2. Total Amount
    total = content.get('invoice_total') or (proposal.get('totals') or {}).get('invoice_total') or (proposal.get('totals') or {}).get('total')
    if not total:
        for source in state.get('attachment_sources', []):
            for d in source.get('drafts', []):
                t = d.get('content', {}).get('invoice_total')
                if t:
                    total = t
                    break
            if total:
                break

    lines = []

    # Line 1: Mention supplier name and total amount
    if total:
        tot_str = str(total).strip()
        if not tot_str.startswith(('₹', 'Rs')):
            tot_str = f"₹{tot_str}"
        lines.append(f"{supplier} ka bill mila hai total amount {tot_str} ka.")
    else:
        lines.append(f"{supplier} ka bill mila hai.")

    # Line 2: State clearly which masters are missing in Tally
    missing_desc = []
    if supplier_missing:
        missing_desc.append(f"{supplier} Sundry Creditors me nahi hai")
    if missing_items:
        missing_desc.append(f"{len(missing_items)} stock items missing hain")

    lines.append(f"Tally me {'; '.join(missing_desc)}.")

    # Line 3: Ask clearly
    if supplier_missing:
        lines.append(f"Kya main Tally me {supplier} ka Sundry Creditor ledger bana doon ya kisi existing ledger se map karna hai?")
    elif missing_items:
        lines.append(f"Kya main Tally me missing stock items bana doon ya kisi existing item se map karna hai?")

    return "\n".join(lines)

def available_tools(state,tools):
    groups={'purchase':{'company_masters','read_purchase_draft','purchase_context','record_purchase_situation','apply_user_message','create_purchase_draft','check_purchase_tax','purchase_preview','evaluate_automation'},
        'reads':{'company_masters','read_stock','read_report'},'documents':{'list_documents','document_status','extract_document','read_bill_fields'},
        'receipts':{'record_purchase_situation','receipt_preview','link_receipt','read_purchase_draft'}}
    active=state.get('tool_groups') or ['reads' if state.get('outcome')=='answer' else 'purchase']
    latest=(state.get('observations') or [{}])[-1].get('data',{})
    if latest.get('goods_receipt') or latest.get('purchase_situation'):
        active=list(dict.fromkeys([*active,'receipts']))
    known=set().union(*groups.values());allowed=set().union(*(groups.get(g,set()) for g in active))
    return [t for t in tools if t.name not in known or t.name in allowed]


async def run(state: dict, tools: list[Tool], choose, persist, budget, completion=None):
    """Run one bounded segment. Callbacks inject scoped persistence and model.

    `budget` reserves/authorises a model request before it starts. `choose`
    returns a Decision; it must not execute any tool. Evidence is untrusted
    input to the model. The controller alone routes registered operations.
    """
    registry = {t.name: t for t in tools}
    if len(registry) != len(tools):
        raise ValueError('Duplicate tool name')
    state = json.loads(json.dumps(state))
    state.setdefault('executions', [])
    state.setdefault('observations', [])
    state.setdefault('model_rounds',0)
    from app.services.business_help import help_answer
    answer=help_answer((state.get('messages') or [''])[-1])
    if answer and not state['executions'] and not state.get('draft_id') and not state.get('action_id'):
        state.update(status='completed',outcome='answer',summary=answer,issues=[])
        for key in ('wait_reason','provider_retry_at','auto_resume_until'):state.pop(key,None)
        await persist(state)
        return state
    if any(e['status'] == 'pending' and e.get('effect') != 'read' for e in state['executions']):
        state.update(status='verification_pending', summary='Interrupted operation requires reconciliation.')
        await persist(state)
        return state
    for event in state['executions']:
        if event['status']=='pending':
            event['status']='interrupted_read'
    state['status']='running'
    for _ in range(6):
        if len(state['executions']) >= 12 or state['model_rounds'] >= 6:
            break
        permitted=available_tools(state,tools)
        seed=state.get('routing_first_step')
        from app.services.intent_router import is_bill_entry_intent
        has_entry = state.get('outcome') == 'verified_entry' or any(is_bill_entry_intent(m) for m in state.get('messages', []))
        if not seed and not state['executions'] and state.get('draft_id') and has_entry and state.get('attachment_document_ids') and any(t.name=='purchase_context' and t.effect=='draft' for t in permitted):
            seed = {'kind': 'tool', 'tool': 'purchase_context', 'arguments': {'draft_id': state['draft_id']}, 'summary': 'Saved bill ki purchase validation check kar rahi hoon.'}
        if seed and not state['executions'] and state['model_rounds']==0:
            decision=Decision.model_validate(seed)
            if decision.tool not in {'create_purchase_draft','apply_user_message','purchase_context'} or not any(t.name==decision.tool and t.effect=='draft' for t in permitted):
                raise ValueError('Invalid server routing seed')
            if decision.tool=='purchase_context' and (not state.get('attachment_document_ids') or decision.arguments.get('draft_id')!=state.get('draft_id')):
                raise ValueError('Invalid saved bill routing seed')
            state.pop('routing_first_step',None)
        elif direct_stock_question(state) and not state['executions'] and any(t.name=='read_stock' and t.effect=='read' for t in permitted):
            decision=Decision(kind='tool',tool='read_stock',arguments={'item_name':'*'},summary='Tally ka stock check kar raha hoon.')
        else:
            await budget()
            state['model_rounds']+=1
            await persist(state)
            decision = Decision.model_validate(await choose(state, [
                dict(name=t.name, description=t.description, effect=t.effect,
                     schema=t.arguments.model_json_schema()) for t in permitted]))
        if decision.kind != 'tool':
            # A purchase planner must inspect context/try the partial-draft
            # capability before claiming that transaction facts are missing.
            # This is bounded feedback, not permission to invent fields.
            if (decision.kind=='needs_input' and state.get('outcome')!='answer'
                    and state.get('company_id') and not state.get('draft_id')
                    and not state['executions'] and not state.get('initial_context_checked')
                    and any(t.name=='create_purchase_draft' for t in permitted)):
                state['initial_context_checked']=True
                state['observations'].append({'status':'ok','data':{
                    'validation_error':'No draft/context tool has run. Do not demand supplier/rate/invoice to create a partial draft. Inspect original message; if it states purchased item/quantity, call create_purchase_draft with only exact grounded fields. For genuinely unsupported/non-purchase input explain the limitation.'},'verified':False})
                await persist(state)
                continue
            # A model saying "finished" is not proof of a completed action.
            verified = bool(completion and await completion(state))
            status = decision.kind if decision.kind != 'finish' else ('completed' if verified else 'needs_input')
            summary = decision.user_response.strip() or 'Task saved hai. Kaunsi detail check ya update karni hai?'
            if decision.kind == 'finish' and not verified:
                summary = 'Task saved; requested outcome is not yet verified. Review the current draft or missing details.'
            if status == 'needs_approval' and not state.get('action_id'):
                status = 'needs_input'
            state.update(status=status, summary=summary)
            await persist(state)
            return state
        if decision.tool not in {t.name for t in permitted}:
            raise ValueError('Unregistered tool')
        tool = registry[decision.tool]
        args = tool.arguments.model_validate(decision.arguments).model_dump(mode='json')
        identity=[tool.name,args]
        if state.get('draft_revision') is not None:identity.append(state['draft_revision'])
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        previous=[e for e in state['executions'] if e['key']==key]
        if any(e['status']!='interrupted_read' for e in previous) or len(previous)>=2:
            break
        await tool.authorize(args)
        event = dict(key=key, tool=tool.name, arguments=args, status='pending', effect=tool.effect)
        state['executions'].append(event)
        await persist(state)
        for attempt in range(2):
            try:
                try:
                    await tool.authorize(args)
                except Exception:
                    event['status']='denied_before_execution'
                    await persist(state)
                    raise
                result = ToolResult.model_validate(await asyncio.wait_for(tool.execute(args),timeout=90))
                break
            except ExecutionNotStarted:
                event['status']='not_started'
                await persist(state)
                raise
            except TransientReadError:
                if tool.effect != 'read' or attempt:
                    raise
                await asyncio.sleep(.25)
        event['status'] = 'settled'
        if result.data.get('capability_group'):
            state['tool_groups']=list(dict.fromkeys([*(state.get('tool_groups') or ['reads' if state.get('outcome')=='answer' else 'purchase']),result.data['capability_group']]))
        state['observations'].append(result.model_dump(mode='json'))
        if result.data.get('draft_id'):
            state['draft_id'] = result.data['draft_id']
        proposal=result.data.get('proposal')
        if isinstance(proposal,dict) and isinstance(proposal.get('revision'),int):
            if tool.effect=='draft' and proposal['revision']!=state.get('draft_revision'):state.pop('action_id',None)
            state['draft_revision']=proposal['revision']
        elif isinstance(result.data.get('revision'),int):
            state['draft_revision']=result.data['revision']
        preview = result.data.get('preview')
        if isinstance(preview, dict) and preview.get('token'):
            state['action_id'] = preview['token']
        if result.data.get('action_id'):
            state['action_id'] = result.data['action_id']
        if result.status == 'waiting_context' and result.data.get('document_id'):
            state['waiting_document_id'] = result.data['document_id']
        if tool.name == 'purchase_context':
            blocker_text = format_tally_blockers(state, result.data)
            if blocker_text:
                result.data['response'] = blocker_text
                state['summary'] = blocker_text
            elif result.data.get('response'):
                state['summary'] = result.data['response']
        elif result.data.get('response'):
            state['summary'] = result.data['response']
        state['status'] = 'running' if result.status == 'ok' else result.status
        answer=settled_stock_answer(state)
        if answer:
            state.update(status='completed' if answer.get('verified') else 'needs_input',summary=answer['data']['response'])
            for key in ('wait_reason','provider_retry_at','auto_resume_until'):state.pop(key,None)
            state['issues']=[]
            await persist(state)
            return state
        await persist(state)
        if result.status != 'ok':
            return state
    state.update(status='needs_input', summary='Task saved; execution limit reached. Review to continue.')
    await persist(state)
    return state
