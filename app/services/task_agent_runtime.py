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

def format_inr(val) -> str:
    try:
        if val is None or str(val).strip() == "":
            return ""
        clean = str(val).replace('₹', '').replace('Rs.', '').replace('Rs', '').replace(',', '').strip()
        num = float(clean)
        parts = f"{num:.2f}".split('.')
        whole, dec = parts[0], parts[1]
        if len(whole) <= 3:
            formatted = whole
        else:
            last3 = whole[-3:]
            rest = whole[:-3]
            groups = []
            while len(rest) > 2:
                groups.insert(0, rest[-2:])
                rest = rest[:-2]
            if rest:
                groups.insert(0, rest)
            groups.append(last3)
            formatted = ",".join(groups)
        return f"₹{formatted}.{dec}"
    except Exception:
        return f"₹{val}"


def format_qty(qty, unit) -> str:
    try:
        if qty is None or str(qty).strip() == "":
            return ""
        q_float = float(str(qty).strip())
        q_str = f"{int(q_float)}" if q_float.is_integer() else f"{q_float:.2f}"
        u_str = (unit or "").strip()
        if u_str.lower() in ('no', 'nos', 'no.'):
            u_str = 'Nos'
        elif u_str.lower() in ('pc', 'pcs', 'piece', 'pieces'):
            u_str = 'Pcs'
        return f"{q_str} {u_str}".strip() if u_str else q_str
    except Exception:
        return f"{qty} {unit}".strip()


def clean_item_name(name: str) -> str:
    if not name:
        return "Item"
    cleaned = name.strip()
    cleaned = re.sub(r'\b13-(\d{4,5})\b', r'i3-\1', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\(\d+-Core.*?\)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\(10th Generation\)', '(10th Gen)', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    return cleaned


def format_bill_date(date_str: str) -> str:
    try:
        if not date_str:
            return ""
        parts = str(date_str).strip().split('-')
        if len(parts) == 3 and len(parts[0]) == 4:
            from datetime import datetime
            dt = datetime.strptime(str(date_str).strip(), '%Y-%m-%d')
            return dt.strftime('%d-%b-%Y')
        return str(date_str)
    except Exception:
        return str(date_str)


def format_tally_blockers(state: dict, data: dict) -> str | None:
    """Articulate Tally blockers directly in conversational Hinglish:
    - Mention supplier name, invoice number, date, and formatted INR total.
    - State clearly which masters are missing in Tally (e.g. TimeNet Solutions is not in Sundry Creditors; 6 stock items missing).
    - List the items cleanly with readable names, quantity, and rates.
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

    # 3. Invoice Number & Date
    inv_num = content.get('invoice_number')
    entry_date = content.get('entry_date')
    if not inv_num or not entry_date:
        for source in state.get('attachment_sources', []):
            for d in source.get('drafts', []):
                c = d.get('content', {})
                if not inv_num and c.get('invoice_number'):
                    inv_num = c.get('invoice_number')
                if not entry_date and c.get('entry_date'):
                    entry_date = c.get('entry_date')
            if inv_num and entry_date:
                break

    raw_supplier = ''
    for source in state.get('attachment_sources', []):
        for d in source.get('drafts', []):
            meta = d.get('extraction_metadata') or {}
            raw_supplier = (meta.get('field_evidence', {}).get('party_name', {}).get('value')
                            or meta.get('source_evidence', {}).get('supplier_name', {}).get('raw')
                            or '').strip()
            if raw_supplier:
                break
        if raw_supplier:
            break

    lines_content = content.get('lines', [])
    tot_formatted = format_inr(total) if total else ''

    blocks = []

    # 1. Header with invoice, date and total:
    if raw_supplier and supplier and raw_supplier.casefold() != supplier.casefold() and supplier != 'Supplier':
        header_lines = [f"Maine {raw_supplier} ka bill check kar liya hai (Tally me mapped: {supplier}):"]
    else:
        header_lines = [f"Maine {supplier} ka bill check kar liya hai:"]
    meta = []
    if inv_num:
        meta.append(f"Invoice: #{inv_num}")
    if entry_date:
        f_date = format_bill_date(entry_date)
        if f_date:
            meta.append(f"Date: {f_date}")
    if tot_formatted:
        meta.append(f"Total: {tot_formatted}")

    if meta:
        header_lines.append(f"• {'  |  '.join(meta)}")

    blocks.append("\n".join(header_lines))

    # 2. Master blockers articulation:
    if supplier_missing and missing_items:
        blocks.append(f"Tally me entry chadhane ke liye ye masters confirm karne hain:\n"
                      f"• Supplier: {supplier} Sundry Creditors me nahi hai\n"
                      f"• Stock Items: Is bill ke {len(missing_items)} stock items missing hain:")
    elif supplier_missing:
        blocks.append(f"Tally me {supplier} Sundry Creditors me nahi hai.")
    elif missing_items:
        blocks.append(f"Tally me entry chadhane ke liye ye {len(missing_items)} items match nahi hue:")

    # 3. Item bullets:
    if missing_items:
        item_bullets = []
        for idx, item_issue in enumerate(missing_items[:6]):
            try:
                line_idx = int(str(item_issue.get('field', '0')).split(':')[0])
                line = lines_content[line_idx] if line_idx < len(lines_content) else {}
            except (ValueError, IndexError):
                line = {}
            raw_name = line.get('item_name') or f"Item {idx + 1}"
            name = clean_item_name(raw_name)
            qty = line.get('quantity')
            unit = line.get('unit') or ''
            qty_formatted = format_qty(qty, unit)
            rate = line.get('rate')
            rate_formatted = format_inr(rate) if rate else ""

            spec = []
            if qty_formatted:
                spec.append(qty_formatted)
            if rate_formatted:
                spec.append(f"@ {rate_formatted}")
            spec_str = f" — {' '.join(spec)}" if spec else ""
            item_bullets.append(f"  {idx + 1}. {name}{spec_str}")

        if len(missing_items) > 6:
            item_bullets.append(f"  ...aur baaki {len(missing_items) - 6} items.")
        blocks.append("\n".join(item_bullets))

    # 4. Actionable closing question:
    if supplier_missing:
        blocks.append(f"Kya main Tally me {supplier} ka Sundry Creditor ledger bana doon ya kisi existing ledger se map karna hai?")
    elif missing_items:
        blocks.append("Tally me ye stock items exist nahi karte. Kya aap inhe Tally ke existing items se map karna chahenge, ya pehle Tally me ye items bana kar sync karenge?")

    return "\n\n".join(blocks)

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
