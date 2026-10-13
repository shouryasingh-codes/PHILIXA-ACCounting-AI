"""Small-business chat tools. Models interpret; scoped repositories execute."""
from __future__ import annotations

import asyncio
import json
import re
import secrets
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import get_ai_provider
from app.api.v1.routes_voice import BusinessTurn, BusinessChatRequest, business_chat
from app.core.config import get_settings
from app.core.redis import get_redis_client
from app.repositories.client_repository import ClientRepository
from app.repositories.commitment_repository import CommitmentRepository
from app.repositories.meeting_repository import MeetingRepository
from app.services.reminder_service import ReminderService
from app.services.rules_engine_service import RulesEngineService

Intent = Literal["supplier_list", "supplier_read", "customer_list", "customer_read", "customer_create", "customer_update", "task_create", "task_list", "task_complete", "reminder_draft", "customer_history", "portfolio_history", "stock_read", "mcp_read", "mcp_write", "purchase_create", "sale_create", "inventory_add", "inventory_change", "stock_count_set", "general"]


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


class CommandFields(BaseModel):
    model_config = ConfigDict(extra='forbid')
    client_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    whatsapp_phone: str | None = Field(default=None, max_length=20, pattern=r"^\+?[0-9]{10,15}$")
    description: str | None = Field(default=None, max_length=500)
    history_query: str | None = Field(default=None, max_length=4000)
    due_date: date | None = None
    channel: Literal["email", "whatsapp", "both"] = "email"
    when: Literal["today", "overdue", "all"] = "all"
    task_id: int | None = Field(default=None, gt=0)
    item_name: str | None = Field(default=None, max_length=200)
    company_query: str | None = Field(default=None, max_length=200)
    company_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    company_scope: Literal['all', 'named'] = 'all'
    party_name: str | None = Field(default=None, max_length=200)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=6)
    rate: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    unit: str | None = Field(default=None, max_length=50)
    godown: str | None = Field(default=None, max_length=200)
    invoice_number: str | None = Field(default=None, max_length=100)
    entry_date: date | None = None
    target_quantity: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=6)
    counted_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=300)
    draft_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    unsupported_reason: str | None = Field(default=None, max_length=300)
    mcp_tool: str | None = Field(default=None, pattern=r'^[a-z_]{1,80}$')
    mcp_arguments: dict = Field(default_factory=dict)


class ParsedCommand(CommandFields):
    intent: Intent


class CommandRequest(BaseModel):
    text: str = Field(default="", max_length=4000)
    conversation_history: list[BusinessTurn] = Field(default_factory=list, max_length=10)
    intent: Intent | None = None
    fields: CommandFields = Field(default_factory=CommandFields)
    client_id: int | None = Field(default=None, gt=0)


class ApprovalRequest(BaseModel):
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
    approve: bool


def approval_key(principal, token):
    return f"business:approval:{principal.organization_id}:{principal.user_id}:{principal.session_id}:{token}"


def delivery_blockers(data: dict) -> list[str]:
    """Reuse existing delivery configuration; dispatch reports provider failures."""
    settings = get_settings()
    reasons = []
    if data.get("wants_email"):
        if not data.get("email_destination"):
            reasons.append("Customer ka email saved nahi hai.")
        if not all((settings.smtp_hostname, settings.smtp_from_address, settings.smtp_username, settings.smtp_password)):
            reasons.append("Email bhejne ke liye SMTP configuration incomplete hai.")
    if data.get("wants_whatsapp"):
        if not data.get("whatsapp_destination"):
            reasons.append("Customer ka WhatsApp number saved nahi hai.")
        if not settings.whatsapp_phone_number_id or not settings.whatsapp_access_token:
            reasons.append("WhatsApp bhejne ke liye Meta configuration incomplete hai.")
    return reasons


def fresh_stock_question(text: str) -> bool:
    if re.search(r'\b(add|remove|delete|edit|correct|actual|physical|counted|ginti|kam|ghata|hata|return\w*|cancel|transfer|purchase|bought|buy|sold|sale|sell|kharid\w*|bech\w*|aaye|aaya|received|update|adjust\w*)\b|खरीद|बेच|जोड़|हटा|घटा|गिनती|असल|वापस|डिलीट',text,re.I):return False
    return bool(re.search(r'\b(stock|inventory)\b.*(?:\b(?:kitn\w*|how|check|show|bata\w*)\b|\?)|\b(?:kitna|kitni|kitne)\b.*\b(?:hai|hain|pass|paas)\b|स्टॉक.*(?:कितन|बत)',text,re.I)
                or re.fullmatch(r'.*\b(?:stock|inventory)\b[?.!]*|.*स्टॉक[?.!]*', text.strip(), re.I))


def starts_tally_topic(text: str) -> bool:
    """Explicit operations/reads start a new topic; item/quantity/rate replies do not."""
    return fresh_stock_question(text) or bool(re.search(
        r'\b(purchase|bought|buy|sale|sales|sold|sell|kharid\w*|bech\w*|'
        r'add|remove|delete|update|adjust\w*|actual|physical|counted|ginti|'
        r'kam|ghata|hata|aaye|aaya|received|returns?|reports?|register|'
        r'balance\s+sheet|trial\s+balance|day\s+book|profit\s+and\s+loss)\b'
        r'|खरीद|बेच|जोड़|हटा|घटा|गिनती|असल|वापस|डिलीट|रिपोर्ट|'
        r'\b(?:suppliers?|customers?)\b.*\b(?:kaun|kon|list|show)\b', text, re.I))


def command_history(request: CommandRequest) -> list[BusinessTurn]:
    """Keep detail replies with their latest topic, never an older operation.

    This is interpretation context only. It cannot authorize a write or replace
    the server's scoped preview/confirmation checks.
    """
    if starts_tally_topic(request.text):
        return []
    history = request.conversation_history
    for index in range(len(history) - 1, -1, -1):
        if history[index].role == 'user' and starts_tally_topic(history[index].content):
            return history[index:]
    return history


def guard_tally_scope(request: CommandRequest, parsed: ParsedCommand) -> ParsedCommand:
    context_text = request.text
    if not request.intent:
        context_text += ' ' + ' '.join(turn.content for turn in command_history(request) if turn.role == 'user')
    context_text = re.sub(r'\b(?:purchase|sales?)\s+(?:reports?|register)\b', 'report', context_text, flags=re.I)
    # A quantity/item/rate reply cannot turn an explicit purchase into an
    # ambiguous stock adjustment merely because the model chose the wrong route.
    if not request.intent and not starts_tally_topic(request.text) and parsed.intent in ('inventory_add', 'inventory_change') \
            and re.search(r'\b(purchase|bought|buy|kharid\w*)\b|खरीद', context_text, re.I):
        parsed.intent = 'purchase_create'
    # Purchase/sales are also report names. Exempt the noun phrase only;
    # explicit mutations elsewhere in the same request must still be blocked.
    mutation_text=re.sub(r'\b(?:purchase|sales?)\s+(?:reports?|register)\b','report',request.text,flags=re.I)
    if not request.intent and parsed.intent=='mcp_read' and re.search(r'\b(add|remove|delete|edit|update|create|correct|purchase|bought|sold|sell|kharid\w*|bech\w*)\b|हटा|जोड़|खरीद|बेच',mutation_text,re.I):
        parsed.unsupported_reason='Ye read report nahi, record change ki request hai. Operation aur details clarify karein.'
        return parsed
    if not request.intent and parsed.intent=='general' and re.search(r'\b(stock|inventory|bags)\b|स्टॉक',request.text,re.I) and re.search(r'\b(add|remove|update|correct|actual|delete)\b|जोड़|हटा',request.text,re.I):
        parsed.intent='inventory_change'
    if not request.intent and fresh_stock_question(request.text) and parsed.intent in ('purchase_create','sale_create','inventory_add'):
        return ParsedCommand(intent='stock_read',item_name=parsed.item_name,company_query=parsed.company_query,
                             company_scope=parsed.company_scope)
    if parsed.intent in ('purchase_create','sale_create','inventory_add','inventory_change','stock_count_set'):
        scope_text=context_text
        scope_text=re.sub(r'\bnon[-\s]?gst\b|\bwithout\s+gst\b|\bgst\s+(?:ke\s+)?(?:bina|nahi)\b|बिना\s+जीएसटी','',scope_text,flags=re.I)
        if re.search(r'\b(gst|cgst|sgst|igst|tax|discount|batch\w*|serial\w*|transfer)\b|जीएसटी|टैक्स|छूट|ट्रांसफर',scope_text,re.I):
            parsed.unsupported_reason='Advanced tax/batch/transfer request unsupported.';return parsed
        if re.search(r'\d.*?\b(?:aur|and)\b.*?\d|\d.*?और.*?\d',scope_text,re.I):
            parsed.unsupported_reason='Combined/conflicting quantities: ek item aur final quantity clarify karein.';return parsed

        if re.search(r'\b(sale|sold|sell|bech\w*|return\w*|delete|cancel.*bill)\b|बेच|वापस|डिलीट',context_text,re.I) or parsed.intent=='sale_create':
            parsed.unsupported_reason='Sale, return aur posted entry edit/delete is milestone mein supported nahi hain.'
            return parsed
        if re.search(r'\b(nahi|nahin|not|mat)\b|नहीं|मत',context_text,re.I):
            parsed.unsupported_reason='Instruction mein negation hai. Operation aur final quantity clearly confirm karein.'
            return parsed
        if not request.intent and re.search(r'\b(remove|kam|ghata|hata)\b|हटा|घटा',request.text,re.I):
            parsed.intent='inventory_change';return parsed
        if not request.intent and re.search(r'\b(actual|physical|counted|ginti)\b|गिनती|असल',request.text,re.I):
            parsed.intent='stock_count_set';return parsed
    if not request.intent and parsed.intent=='stock_count_set' and not re.search(r'\b(actual|physical|counted|ginti)\b|गिनती|असल',context_text,re.I):
        parsed.intent='inventory_change';return parsed
    if not request.intent and parsed.intent=='purchase_create' and not re.search(r'\b(purchase|bought|buy|kharid\w*)\b|खरीद',context_text,re.I):
        parsed.intent='inventory_add' if re.search(r'\b(add|aaye|aaya|received)\b|जोड़|आए',context_text,re.I) else 'inventory_change';return parsed
    if parsed.intent not in ('purchase_create','sale_create'):


        return parsed
    text = context_text
    if not request.intent and parsed.intent=='purchase_create' and re.search(r'\b(add|aaye|aaya|received)\b|जोड़|आए',text,re.I) and not re.search(r'\b(purchase|bought|buy|kharid\w*)\b|खरीद',text,re.I):
        return ParsedCommand(intent='inventory_add',**parsed.model_dump(exclude={'intent'}))
    scope_text = re.sub(r'\bnon[-\s]?gst\b|\bwithout\s+gst\b|\bgst\s+(?:ke\s+)?(?:bina|nahi)\b|बिना\s+जीएसटी','',text,flags=re.I)
    if re.search(r'\b(gst|cgst|sgst|igst|tax|discount|return\w*|batch\w*|serial\w*|transfer|correction)\b|जीएसटी|टैक्स|छूट|वापस|ट्रांसफर',scope_text,re.I):
        parsed.unsupported_reason = 'Tax/GST, discounts, returns ya advanced stock requests is pilot mein supported nahi hain.'
    if re.search(r'\d.*?\b(?:aur|and)\b.*?\d|\d.*?और.*?\d',text,re.I):
        parsed.unsupported_reason = 'Combined instructions supported nahi hain. Ek item ki quantity aur rate ke saath ek entry boliye.'
    return parsed


async def interpret(request: CommandRequest, customer_names: list[str] | None = None, tally_names: dict | None = None) -> ParsedCommand:
    if request.intent:
        return guard_tally_scope(request, ParsedCommand(intent=request.intent, **request.fields.model_dump()))
    # Fresh party questions cannot inherit an unfinished purchase or CRM form.
    text = request.text.strip()
    if re.fullmatch(r'(?:hamara|hamare|mere|our|my)?\s*(?:suppliers?|supplier\s+list|सप्लायर)\s*(?:kon|kaun|kaunse|kaun\s+kaun|list|dikhao|batao|कौन|दिखाओ)?\s*(?:hai|hain|हैं|है)?[?.!]*', text, re.I):
        return ParsedCommand(intent='supplier_list')
    match = re.fullmatch(r'(.+?)\s+(?:ye\s+)?(?:kon|kaun|कौन)\s+(?:hai|है)[?.!]*', text, re.I)
    if match and any(n.casefold() == match[1].strip().casefold() for n in (tally_names or {}).get('suppliers', [])):
        return ParsedCommand(intent='supplier_read', party_name=match[1].strip())
    if re.fullmatch(r'\s*(?:tally\s+)?(?:reports?|रिपोर्ट)(?:\s+(?:dikhao|show|dikha|दिखाओ))?\s*',request.text,re.I):
        return ParsedCommand(intent='mcp_read')
    settings = get_settings()
    prompt = (
        f"Interpret a Hindi/Hinglish/English small-business command. Today is {today().isoformat()} in India. "
        "Return only JSON matching the supplied schema. No tools or execution. "
        "supplier_list=show actual Tally suppliers (hamara supplier kaun hai). supplier_read=details of a named Tally supplier, party_name required (Sharma Traders kaun hai). These are accounting master reads, never CRM history, general chat or mcp_read. A customer is not automatically a supplier. Do not carry previous purchase fields into a fresh supplier question. "
        "customer_list=list customers; customer_read=contact or latest conversation; "
        "customer_history=search a named customer past meeting evidence/topics across history; "
        "portfolio_history=search meeting evidence across customers, such as who asked for discount; "
        "For history intents, history_query is the full question with customer/topic/date context, "
        "including earlier user turns when the current turn only supplies a missing customer or detail. "
        "customer_create=save a new customer; customer_update=change existing contact; "
        "task_create=save a future follow-up/payment call task; task_list=pending/today/overdue work; "
        "task_complete=mark a task done; reminder_draft=compose a message to send NOW via email/WhatsApp. "
        "Future reminders mean task_create, not automatic message scheduling. "
        "stock_read=current stock for item_name; purchase_create=goods bought from supplier party_name; "
        "mcp_read=read-only Tally financial reports or account master lists. Choose mcp_tool from: "
        "get_ledgers, get_stock_items, get_vouchers (Day Book), get_company_info, get_profit_and_loss, "
        "get_balance_sheet, get_trial_balance, get_groups, get_voucher_types, get_cost_centres, get_stock_summary, "
        "get_bills_receivable, get_bills_payable, get_cash_flow, get_funds_flow, get_ratio_analysis, "
        "get_sales_register, get_purchase_register, get_journal_register, get_payment_register, "
        "get_receipts_and_payments, get_reorder_status, get_vat_liability_summary, get_gst_liability_summary, "
        "get_ledger_vouchers, get_health_check. Populate mcp_arguments only with explicit fields: "
        "from/to for period reports, asOf for balance sheet/stock summary/bills, ledgerName for ledger transactions, "
        "optional query for ledger name search. Dates YYYY-MM-DD. Never assume a financial reporting period; "
        "missing dates are collected in a form. Only explicit aaj/today may use today's date. "
        "A request to change, add, remove, edit or delete any record is never mcp_read. "
        "A fresh stock question for one item stays stock_read, not mcp_read. "
        "A vague instruction to add stock or goods arrived without saying purchase must be inventory_add, "
        "which asks whether purchase or stock adjustment. Never invent an accounting transaction. "
        "Stock: company_query only if a company is explicitly named; company_scope=named in that case, otherwise all. "
        "Never infer a selected company from old chat turns for a fresh stock query. Never invent company_id. "
        "stock_count_set=explicit actual physical final count; extract target_quantity (zero allowed), counted_at timezone-aware, reason. Never use relative add/remove quantity as final count. "
        "inventory_change=ambiguous removal or adjustment; clarify. Unsupported sales/returns/edit/delete must not become purchase. "
        "sale_create=goods sold to customer party_name. Extract single item_name, quantity, unit, rate, godown and entry_date. "
        "For GST/tax, discounts, returns, multiple items, serial/batch stock, transfers or correction requests: "
        "set unsupported_reason explaining unsupported scope; never silently reduce them to a simple entry. "
        "Never invent missing item, party, quantity, unit or rate. A date omitted for Tally means today. "
        "A user correction can fill earlier missing fields from history; do not execute or confirm anything. "
        "For a detail-only reply (item, party, quantity, unit or rate), continue the latest operation in supplied history, "
        "keep its explicitly supplied fields, and replace only fields explicitly corrected by the current message. "
        "For example, a purchase followed by 'quantity 8 bags' stays purchase_create, not inventory_change. "
        "Do not use an earlier operation after a new stock/report question. Sales remain sale_create even when only details follow. "
        'Tally extraction example: "Supplier se 10 Cement bags 350 rupees per bag kharide" means '
        '{"intent":"purchase_create","party_name":"Supplier","item_name":"Cement","quantity":"10","unit":"bags","rate":"350"}. '
        '"Customer ko 2 Cement bags 400 per bag beche" means '
        '{"intent":"sale_create","party_name":"Customer","item_name":"Cement","quantity":"2","unit":"bags","rate":"400"}. '
        '"Cement ka stock" means {"intent":"stock_read","item_name":"Cement"}. '
        'Copy values only from the actual instruction/context, never from these examples. '
        "general=other queries including analytics, other accounting and calendar. "
        "Extract only explicitly supplied contact details. Never invent a name, email, phone, ID or date. "
        "If 'kal' is future it means tomorrow. Use YYYY-MM-DD dates. If a specific time is supplied "
        "retain that time in description; tasks are date-based, not timed notifications. "
        "client_name is the existing customer to find. customer_update must not rename. "
        "Default channel email; both only when requested. when=today for today's tasks, overdue for overdue only, otherwise all. "
        "History is context only. A bare yes/confirm is general: approval happens through a preview button. "
        "For Hindi-script names, use the matching spelling from available customer names only if unambiguous. "
        "Do not expand a partial name if multiple customers match it. Available customer names: "
        + json.dumps(customer_names or [], ensure_ascii=False)
        + '\nAvailable Tally master names (context only, never authorization): '
        + json.dumps(tally_names or {}, ensure_ascii=False)
        + '. Match Hindi-script item/party/unit names only when unambiguous; otherwise retain the supplied partial name.'
    )
    history = [turn.model_dump() for turn in command_history(request)]
    user_data = json.dumps({"history": history, "message": request.text}, ensure_ascii=False)
    incomplete = None
    for name, model in [(settings.ai_economy_provider, settings.ai_economy_model), (settings.ai_review_provider, settings.ai_review_model)]:
        if name == "local":
            continue
        try:
            provider = get_ai_provider(name, settings)
            raw = await asyncio.to_thread(provider.generate_json, model, prompt + "\nConversation: " + user_data, ParsedCommand.model_json_schema())
            parsed = guard_tally_scope(request, ParsedCommand.model_validate_json(raw))
            if parsed.intent in ('stock_read','purchase_create','sale_create') and not parsed.unsupported_reason and not any(
                    (parsed.item_name, parsed.party_name, parsed.quantity, parsed.rate, parsed.unit)):
                incomplete = parsed
                continue  # Try the existing review provider when classification omitted all details.
            return parsed
        except Exception:
            continue
    if incomplete:
        return incomplete
    raise HTTPException(503, "Baat samajh nahi aayi. Customer/Kaam buttons use karein ya dobara bolein.")


async def resolve_client(db, principal, request, command):
    repo = ClientRepository()
    if request.client_id:
        client = await repo.get_by_id(db, principal, request.client_id)
        if not client:
            raise HTTPException(404, "Customer nahi mila.")
        return client, None
    clients = await repo.list(db, principal)
    name = (command.client_name or "").strip().casefold()
    exact = [c for c in clients if c.name.casefold() == name] if name else []
    matches = exact or ([c for c in clients if name in c.name.casefold()] if name else clients)
    if len(matches) == 1 and name:
        return matches[0], None
    if not matches:
        return None, {"response": "Is naam ka customer nahi mila. Pehle customer add karein ya poora naam dein."}
    # Preserve the interpreted command on selection instead of re-interpreting it.
    return None, {"response": "Kaunsa customer? Naam select karein.", "choices": [{"id": c.id, "name": c.name} for c in matches[:100]],
                  "selection_command": {"intent": command.intent, "fields": command.model_dump(mode="json", exclude={"intent"})}}


async def preview(principal, kind, payload, title, lines, client=None, blockers=None):
    token = secrets.token_hex(16)
    data = {"kind": kind, "payload": payload}
    if client:
        data.update(client_id=client.id, client_version=client.updated_at.isoformat())
    redis = await get_redis_client()
    try:
        await redis.set(approval_key(principal, token), json.dumps(data), ex=900)
    finally:
        await redis.aclose()
    return {"response": "Details check karein. Confirmation se pehle kuch save/send nahi hua.",
            "preview": {"token": token, "title": title, "lines": lines, "can_confirm": not blockers, "blockers": blockers or [], "send": kind == "reminder"}}


async def plan_command(request: CommandRequest, principal, db: AsyncSession) -> ParsedCommand:
    if request.fields.draft_id and request.intent!='mcp_write':
        from app.models.tally import TallyAction
        from app.services.tally_sync import now
        draft=await db.get(TallyAction,request.fields.draft_id)
        if not draft or (draft.organization_id,draft.user_id,draft.session_id)!=(principal.organization_id,principal.user_id,principal.session_id) or draft.expires_at<=now() or draft.payload.get('operation')!='inventory_clarification':
            raise HTTPException(410,'Clarification draft unavailable/expired.')
        if request.intent not in ('purchase_create','stock_count_set'):raise HTTPException(422,'Invalid clarification operation.')
        merged={**draft.payload['fields'],**request.fields.model_dump(mode='json',exclude_unset=True)}
        merged.pop('draft_id',None)
        if request.intent=='stock_count_set':merged['quantity']=None
        request=request.model_copy(update={'fields':CommandFields.model_validate(merged)})

    repo, tasks = ClientRepository(), CommitmentRepository()
    if not request.intent and not request.text.strip():
        raise HTTPException(422, "Message cannot be blank")
    names = [c.name for c in (await repo.list(db, principal))[:100]] if not request.intent else None
    tally_names = None
    if not request.intent:
        from app.models.tally import TallyConnection
        cfg = await db.get(TallyConnection, principal.organization_id)
        if cfg and principal.role in ('owner','admin'):
            redis = await get_redis_client()
            try:
                cached = await redis.get(f'tally:masters:{principal.organization_id}:{cfg.version}')
                tally_names = json.loads(cached) if cached else None
            except Exception:
                tally_names = None  # Optional interpretation hints; live execution still revalidates masters.
            finally:
                await redis.aclose()
        from app.services.tally_stock import resolve_scope
        permitted = await resolve_scope(db, principal, ParsedCommand(intent='stock_read'))
        tally_names = dict(tally_names or {})
        tally_names['companies'] = [{'name':c.name,'aliases':c.aliases} for c in permitted]
        from app.services.tally_sync import saved_snapshot
        for company in permitted:
            try:snapshot=await saved_snapshot(db,company)
            except Exception:continue
            if snapshot:
                tally_names.setdefault('items',[]).extend(i['item'] for i in snapshot.items)
                from app.services.tally_sync_protocol import deserialize_catalog
                from app.services.tally_connector import name, value
                catalog=deserialize_catalog(snapshot.catalog)
                tally_names.setdefault('parties',[]).extend(name(l) for l in catalog['ledgers'] if value(l,'PARENT') in ('Sundry Creditors','Sundry Debtors'))
                from app.services.tally_supplier_codec import supplier_rows
                tally_names.setdefault('suppliers',[]).extend(name(l) for l in supplier_rows(catalog))
                tally_names.setdefault('units',[]).extend(name(u) for u in catalog['units'])
        for key in ('items','parties','suppliers','units'):
            if key in tally_names:tally_names[key]=list(dict.fromkeys(tally_names[key]))[:100]
    parsed = await interpret(request, names, tally_names)
    if parsed.intent in ('customer_history','portfolio_history') and not request.intent:
        parsed.history_query = parsed.history_query or request.text
    return parsed


async def execute_command(request: CommandRequest, principal, db: AsyncSession, parsed: ParsedCommand) -> dict:
    repo, tasks = ClientRepository(), CommitmentRepository()
    if parsed.intent in ('supplier_list', 'supplier_read'):
        from app.services.tally_suppliers import read_suppliers
        return await read_suppliers(db, principal, parsed)
    if parsed.intent == 'stock_count_set':
        from app.services.tally_count import create_draft
        return await create_draft(db,principal,parsed)
    if parsed.intent in ('inventory_add','inventory_change'):
        if parsed.unsupported_reason:return {'response':parsed.unsupported_reason}
        fields=parsed.model_dump(mode='json',exclude={'intent'})
        if isinstance(db,AsyncSession):
            from app.models.tally import TallyAction
            from app.services.tally_sync import now
            from datetime import timedelta
            token=secrets.token_hex(16);stamp=now()
            db.add(TallyAction(token=token,organization_id=principal.organization_id,user_id=principal.user_id,session_id=principal.session_id,
                created_at=stamp,expires_at=stamp+timedelta(minutes=15),connection_version=0,payload={'operation':'inventory_clarification','fields':fields},xml_payload='',status='draft',attempts=0))
            await db.commit();fields={**fields,'draft_id':token}
        return {'response':'Ye purchase hai ya actual final count (stock adjustment) correct karna hai? Relative add/remove aur entry delete supported nahi.',
                'tally_choices':[{'name':'Purchase se aaye hain','command':{'intent':'purchase_create','fields':fields}}, {'name':'Actual count correct karna','command':{'intent':'stock_count_set','fields':{**fields,'quantity':None,'target_quantity':None}}}]}
    if parsed.intent in ('stock_read','purchase_create','sale_create'):
        if parsed.intent == 'stock_read':
            from app.services.tally_stock import read_stock
            return await read_stock(db, principal, parsed)
        from app.services.tally_business import handle_command
        return await handle_command(db, principal, parsed)
    if parsed.intent in ("customer_history", "portfolio_history"):
        from app.services.ask_client_service import AskClientService
        client_id = None
        if parsed.intent == "customer_history":
            client, selection = await resolve_client(db, principal, request, parsed)
            if selection:
                return selection
            client_id = client.id
        return await AskClientService().business_history(db, principal, parsed.history_query or request.text, client_id)
    if parsed.intent == "general":
        return await business_chat(BusinessChatRequest(text=request.text or "Help", conversation_history=request.conversation_history), principal)
    if parsed.intent == "customer_list":
        clients = await repo.list(db, principal)
        return {"response": f"{len(clients)} customers saved hain. Details ke liye naam select karein.",
                "choices": [{"id": c.id, "name": c.name} for c in clients[:100]], "selection_command": {"intent": "customer_read"}}
    if parsed.intent == "task_list":
        rows = await tasks.list(db, principal, status="pending")
        if parsed.when == "today":
            rows = [t for t in rows if t.due_date and t.due_date <= today()]
        elif parsed.when == "overdue":
            rows = [t for t in rows if t.due_date and t.due_date < today()]
        clients = {c.id: c.name for c in await repo.list(db, principal)}
        entries = [{"id": t.id, "customer": clients.get(t.client_id, "Customer"), "description": t.description,
                    "due_date": t.due_date.isoformat() if t.due_date else None,
                    "overdue": bool(t.due_date and t.due_date < today())} for t in rows[:100]]
        summary = f"{len(rows)} pending kaam mile.\n" + "\n".join(f"{t['customer']}: {t['description']} — {t['due_date'] or 'Date nahi hai'}{' (Overdue)' if t['overdue'] else ''}" for t in entries[:5])
        return {"response": summary if rows else "Is filter mein koi pending kaam nahi hai.", "tasks": entries}
    if parsed.intent == "task_complete":
        if not parsed.task_id:
            return {"response": "Pending kaam kholkar us task ka Done button dabayein."}
        task = await tasks.get_by_id(db, principal, parsed.task_id)
        if not task:
            raise HTTPException(404, "Task nahi mila.")
        return await preview(principal, "task_complete", {"task_id": task.id, "status": task.status}, "Kaam completed mark karein?", [task.description])
    if parsed.intent == "customer_create":
        from app.models.tally import TallyConnection, TallyReadCompany
        from sqlalchemy import select
        configured = await db.get(TallyConnection, principal.organization_id)
        approved = await db.scalar(select(TallyReadCompany.id).where(TallyReadCompany.organization_id==principal.organization_id, TallyReadCompany.enabled.is_(True)))
        if configured or approved:
            from app.services.tally_customer import preview_customer
            return await preview_customer(db, principal, parsed)
        if not parsed.client_name or not parsed.client_name.strip():
            return {"response": "Naye customer ka naam bataiye."}
        existing = await repo.list(db, principal)
        if any(c.name.casefold() == parsed.client_name.strip().casefold() for c in existing):
            return {"response": "Is naam ka customer pehle se saved hai. Details update karni hain to update boliye."}
        payload = {"name": parsed.client_name.strip(), "email": parsed.email, "whatsapp_phone": parsed.whatsapp_phone}
        return await preview(principal, "customer_create", payload, "Customer add karein? — Philixa only", [payload["name"], "Tally connected nahi hai: sirf Philixa customer save hoga, Tally ledger nahi.", f"Email: {parsed.email or 'Not supplied'}", f"WhatsApp: {parsed.whatsapp_phone or 'Not supplied'}"])
    client, selection = await resolve_client(db, principal, request, parsed)
    if selection:
        return selection
    if parsed.intent == "customer_read":
        meetings = await MeetingRepository().list(db, principal, client_id=client.id)
        meetings = sorted(meetings, key=lambda m: (m.meeting_date, m.created_at), reverse=True)
        lines = [client.name, f"Phone / WhatsApp: {client.whatsapp_phone or 'Saved nahi hai'}", f"Email: {client.email or 'Saved nahi hai'}"]
        if meetings:
            lines.append(f"Pichhli baat ({meetings[0].meeting_date}): {meetings[0].summary or 'Summary saved nahi hai'}")
        else:
            lines.append("Abhi koi meeting/baat saved nahi hai.")
        pending = await tasks.list(db, principal, client_id=client.id, status="pending")
        lines.extend(f"Pending: {t.description} — {t.due_date or 'Date nahi hai'}" for t in pending[:5])
        return {"response": "\n".join(lines), "source": "Saved customer records", "customer": {"id": client.id, "name": client.name, "email": client.email, "whatsapp_phone": client.whatsapp_phone}}
    if parsed.intent == "customer_update":
        changes = {k: getattr(parsed, k) for k in ("email", "whatsapp_phone") if getattr(parsed, k) is not None}
        if not changes:
            return {"response": "Naya email ya WhatsApp number bataiye."}
        return await preview(principal, "customer_update", changes, f"{client.name}: contact update?", [f"{k}: {v}" for k, v in changes.items()], client)
    if parsed.intent == "task_create":
        if not parsed.description or not parsed.description.strip() or not parsed.due_date:
            return {"response": "Customer ke liye kya kaam karna hai aur kis date ko? Poora instruction dobara boliye."}
        if parsed.due_date < today():
            return {"response": "Ye date beet chuki hai. Follow-up ke liye aaj ya aage ki date dein."}
        data = {"client_id": client.id, "description": parsed.description.strip(), "due_date": parsed.due_date.isoformat(), "owner": "Business user"}
        return await preview(principal, "task_create", data, "Follow-up save karein?", [client.name, data["description"], f"Date: {data['due_date']} (IST)", "Ye saved task hai; automatic timed notification nahi."], client)
    # Exact scoped customer ID avoids accidentally drafting for similarly named customers.
    instruction = parsed.description or request.text
    if not instruction.strip():
        return {"response": "Customer ko kya message bhejna hai?"}
    drafted = await ReminderService().draft_client_reminder(db, principal.organization_id, principal.user_id, principal.role,
                    client.name, instruction, parsed.channel, client_id=client.id)
    if drafted["status"] != "success":
        return {"response": drafted["message"]}
    data = drafted["draft_data"]
    lines = [client.name]
    if data["wants_email"]:
        lines.extend([f"Email to: {data['email_destination'] or 'Not saved'}", f"Subject: {data['draft']['email_subject']}", data["draft"]["email_body"]])
    if data["wants_whatsapp"]:
        lines.extend([f"WhatsApp to: {data['whatsapp_destination'] or 'Not saved'}", data["draft"]["whatsapp_body"]])
    return await preview(principal, "reminder", data, "Message ka preview", lines, client, delivery_blockers(data))


async def confirm(request: ApprovalRequest, principal, db: AsyncSession) -> dict:
    from app.services.tally_business import confirm_action
    tally_result = await confirm_action(db, principal, request.token, request.approve)
    if tally_result is not None:
        return tally_result
    redis = await get_redis_client()
    key = approval_key(principal, request.token)
    try:
        done = await redis.get(key + ":result")
        if done:
            return json.loads(done)
        raw = await redis.get(key)
        if not raw:
            raise HTTPException(410, "Preview expire ho gaya. Naya preview banayein.")
        data = json.loads(raw)
        if request.approve and data["kind"] == "reminder":
            reasons = delivery_blockers(data["payload"])
            if reasons:
                raise HTTPException(409, " ".join(reasons))
        # Single-use operation, scoped to workspace, user and authenticated session.
        if not await redis.set(key + ":used", "1", nx=True, ex=86400):
            raise HTTPException(409, "Ye action process ho raha hai/already process hua. Dobara send nahi hoga.")
        try:
            if not request.approve:
                result = {"response": "Cancel kar diya. Kuch save/send nahi hua."}
            else:
                payload, kind = data["payload"], data["kind"]
                client = None
                if data.get("client_id"):
                    client = await ClientRepository().get_by_id(db, principal, data["client_id"])
                    if not client or client.updated_at.isoformat() != data["client_version"]:
                        raise HTTPException(409, "Customer details badal gayi hain. Naya preview banayein.")
                if kind == "customer_create":
                    existing = await ClientRepository().list(db, principal)
                    if any(c.name.casefold() == payload["name"].casefold() for c in existing):
                        raise HTTPException(409, "Customer pehle se saved hai.")
                    client = await ClientRepository().create(db, principal, payload)
                    result = {"response": f"{client.name}: customer save ho gaya.", "customer_id": client.id}
                elif kind == "customer_update":
                    await ClientRepository().update(db, principal, client.id, payload)
                    result = {"response": f"{client.name}: contact update ho gaya."}
                elif kind == "task_create":
                    if date.fromisoformat(payload["due_date"]) < today():
                        raise HTTPException(409, "Task ki date beet chuki hai. Naya preview banayein.")
                    existing = await CommitmentRepository().list(db, principal, scope="me", client_id=client.id, status="pending")
                    duplicate = next((t for t in existing if t.description.casefold() == payload["description"].casefold() and str(t.due_date) == payload["due_date"]), None)
                    task = duplicate or await CommitmentRepository().create(db, principal, payload)
                    await RulesEngineService.sync_client_tasks_and_risks(db, client.id)
                    result = {"response": f"{client.name}: follow-up {task.due_date} ke liye saved hai. Automatic message schedule nahi hua.", "task_id": task.id}
                elif kind == "task_complete":
                    task = await CommitmentRepository().get_by_id(db, principal, payload["task_id"])
                    if not task or task.status != payload["status"]:
                        raise HTTPException(409, "Task badal gaya. Pending list dobara kholein.")
                    await CommitmentRepository().update_status(db, principal, task.id, "completed")
                    result = {"response": "Task completed mark ho gaya."}
                elif kind == "reminder":
                    if payload["email_destination"] != client.email or payload["whatsapp_destination"] != client.whatsapp_phone:
                        raise HTTPException(409, "Contact details badal gayi hain. Naya preview banayein.")
                    delivery = await ReminderService().dispatch_client_reminder(payload, db=db, user_id=principal.user_id, organization_id=principal.organization_id)
                    result = {"response": delivery["message"], "delivery_status": delivery["status"]}
                else:
                    raise HTTPException(400, "Unknown action")
                await db.commit()
            await redis.set(key + ":result", json.dumps(result), ex=86400)
            await redis.delete(key)
            return result
        except Exception:
            await db.rollback()
            # Never retry a possibly sent message automatically after an uncertain failure.
            await redis.delete(key)
            raise
    finally:
        await redis.aclose()
