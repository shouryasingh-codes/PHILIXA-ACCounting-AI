import json
import logging
import asyncio
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import TypedDict, Annotated, Literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import litellm
import redis
from langgraph.graph import StateGraph, END

from app.core.config import get_settings
from app.ai.prompts_copilot import PLANNER_SYSTEM_PROMPT, SQL_GENERATOR_PROMPT, SYNTHESIZER_SYSTEM_PROMPT
from app.services.embedding_service import generate_query_embedding
from app.core.redis import get_redis_client
from app.services.reminder_service import ReminderService
from app.models.client import Client
from app.core.auth import Principal

logger = logging.getLogger(__name__)
settings = get_settings()

# Map the custom config keys to the standard env vars Litellm expects
import os
os.environ["OPENAI_API_KEY"] = settings.ai_api_key
os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
os.environ["GROQ_API_KEY"] = settings.ai_api_key


async def _complete_with_retry(*, messages: list[dict], response_format: dict | None = None):
    """Call the LLM without letting a temporary provider failure become a 500."""
    request = {
        "model": settings.ai_economy_model,
        "messages": messages,
    }
    if response_format:
        request["response_format"] = response_format

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            # litellm.completion is synchronous; keep it off FastAPI's event loop.
            return await asyncio.to_thread(litellm.completion, **request)
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Portfolio copilot LLM request failed (attempt %s/2): %s",
                attempt + 1,
                exc,
            )
            if attempt == 0:
                await asyncio.sleep(0.5)

    raise RuntimeError("Portfolio copilot AI provider is unavailable") from last_error

class GraphState(TypedDict):
    query: str
    organization_id: str
    user_id: str
    role: str
    route: str
    sql_query: str
    sql_error: str
    db_result: str
    action_client_name: str
    action_instruction: str
    final_answer: str


# These concepts live inside meeting notes/evidence, not in dedicated SQL columns.
# Route them deterministically so an LLM cannot generate a query for a non-existent
# `discount`, `concern`, or `complaint` column.
VECTOR_SEARCH_TERMS = (
    "discount",
    "concern",
    "complaint",
    "issue",
    "problem",
    "sentiment",
    "mood",
    "interested",
    "interest",
    "asked for",
    "manga",
    "maanga",
    "chinta",
    "pareshan",
)


def _requires_evidence_search(query: str) -> bool:
    normalized_query = query.casefold()
    return any(term in normalized_query for term in VECTOR_SEARCH_TERMS)


def _extract_client_lookup_name(query: str) -> str | None:
    """Recognize simple profile questions that do not need an LLM-generated query."""
    normalized_query = query.strip()
    match = re.search(
        r"(?:who\s+is|who's|tell\s+me\s+about)\s+([a-z][a-z .'-]{0,117})[?!.,]*$",
        normalized_query,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(r"^([a-z][a-z .'-]{0,117})\s+kaun\s+hai[?!.,]*$", normalized_query, re.IGNORECASE)
    if not match:
        return None

    name = match.group(1).strip(" .'-")
    return name if name else None


def _is_greeting(query: str) -> bool:
    return query.strip().casefold().strip("!?.") in {"hi", "hii", "hiii", "hello", "hey", "namaste"}


WEEKDAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _meeting_schedule_date(query: str) -> date | None:
    """Return the upcoming requested weekday for meeting-schedule questions."""
    normalized_query = query.casefold()
    is_meeting_question = any(term in normalized_query for term in ("milna", "milne", "kisse", "kisee", "meet", "meeting"))
    if not is_meeting_question:
        return None

    for weekday_name, weekday_number in WEEKDAY_NAMES.items():
        if weekday_name in normalized_query:
            # Portfolio dates are presented to the user in the product's IST timezone.
            today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
            return today + timedelta(days=(weekday_number - today.weekday()) % 7)
    return None


async def _lookup_meetings_for_date(meeting_date: date, organization_id: str, user_id: str, role: str, db: AsyncSession) -> dict:
    query_text = """
        SELECT COALESCE(c.name, m.suggested_client_name, 'Unassigned client') AS client_name,
               m.meeting_date,
               m.summary
        FROM meetings m
        LEFT JOIN clients c ON c.id = m.client_id
        WHERE m.organization_id = :organization_id
          AND m.meeting_date = :meeting_date
    """
    params = {"organization_id": organization_id, "meeting_date": meeting_date}
    if role != "owner" and role != "admin":
        query_text += " AND m.user_id = :user_id"
        params["user_id"] = user_id
        
    query_text += " ORDER BY c.name NULLS LAST, m.id"
    
    result = await db.execute(text(query_text), params)
    meetings = [dict(row) for row in result.mappings().all()]
    day_label = meeting_date.strftime("%A, %d %b")
    if not meetings:
        return {
            "answer": f"No meetings are recorded in your portfolio for {day_label}.",
            "source_type": "meeting_schedule",
            "data": [],
        }

    details = []
    for meeting in meetings:
        summary = (meeting.get("summary") or "").strip()
        details.append(f"{meeting['client_name']}{f': {summary}' if summary else ''}")
    return {
        "answer": f"Your meetings for {day_label}: " + "; ".join(details) + ".",
        "source_type": "meeting_schedule",
        "data": meetings,
    }


async def _lookup_client_profile(name: str, organization_id: str, user_id: str, role: str, db: AsyncSession) -> dict:
    query_text = """
        SELECT name, products_owned_json, rolling_summary, relationship_notes
        FROM clients
        WHERE organization_id = :organization_id
          AND lower(name) = lower(:name)
          AND is_active = true
    """
    params = {"organization_id": organization_id, "name": name}
    if role != "owner" and role != "admin":
        query_text += " AND user_id = :user_id"
        params["user_id"] = user_id
        
    query_text += " LIMIT 1"
    
    result = await db.execute(text(query_text), params)
    row = result.mappings().first()
    if not row:
        return {
            "answer": f"I couldn't find an active client named {name} in this portfolio.",
            "source_type": "client_lookup",
            "data": [],
        }

    client = dict(row)
    try:
        products = json.loads(client["products_owned_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        products = []
    details = [client["rolling_summary"], client["relationship_notes"]]
    summary = next((detail.strip() for detail in details if detail and detail.strip()), "No profile summary is available yet.")
    product_text = f" Products: {', '.join(products)}." if products else ""
    return {
        "answer": f"{client['name']} is a client in your portfolio. {summary}{product_text}",
        "source_type": "client_lookup",
        "data": [{"name": client["name"], "products": products, "summary": summary}],
    }


async def planner_node(state: GraphState) -> GraphState:
    logger.info("--- PLANNER NODE ---")
    if _requires_evidence_search(state["query"]):
        logger.info("Routing query to vector search based on evidence-search terms")
        return {"route": "vector"}

    response = await _complete_with_retry(
        messages=[
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": state["query"]}
        ],
        response_format={"type": "json_object"}
    )
    result_str = response.choices[0].message.content
    try:
        route_data = json.loads(result_str)
        route = route_data.get("route", "vector")
        if route not in {"sql", "vector", "action"}:
            logger.warning("Planner returned unsupported route %r; using vector search", route)
            route = "vector"
            
        client_name = route_data.get("client_name", "")
        instruction = route_data.get("instruction", "")
    except Exception:
        route = "vector"
        client_name = ""
        instruction = ""
    
    return {"route": route, "action_client_name": client_name, "action_instruction": instruction}

def route_query(state: GraphState) -> Literal["sql_generator_node", "semantic_node", "action_node"]:
    if state.get("route") == "sql":
        return "sql_generator_node"
    elif state.get("route") == "action":
        return "action_node"
    return "semantic_node"

async def sql_generator_node(state: GraphState) -> GraphState:
    logger.info("--- SQL GENERATOR NODE ---")
    error_context = ""
    if state.get("sql_error"):
        error_context = f"\nPREVIOUS ERROR: {state['sql_error']}\nFix the query."
        
    rbac_filter = ""
    if state["role"] not in ("owner", "admin"):
        rbac_filter = f"\n- VERY IMPORTANT: Add AND user_id = '{state['user_id']}' to all WHERE clauses so employees only see their own data."
        
    prompt = SQL_GENERATOR_PROMPT.format(
        organization_id=state["organization_id"],
        rbac_filter=rbac_filter
    )
    response = await _complete_with_retry(
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": state["query"] + error_context}
        ]
    )
    sql_query = response.choices[0].message.content.replace("```sql", "").replace("```", "").strip()
    return {"sql_query": sql_query, "sql_error": ""}

async def semantic_node(state: GraphState) -> GraphState:
    logger.info("--- SEMANTIC NODE ---")
    return {"db_result": "Vector search requested"}

async def synthesizer_node(state: GraphState) -> GraphState:
    logger.info("--- SYNTHESIZER NODE ---")
    return {"final_answer": "Synthesizing output..."}

async def action_node(state: GraphState) -> GraphState:
    logger.info("--- ACTION NODE ---")
    return {"final_answer": "Executing action..."}

def build_workflow(state_type, nodes, entry, edges, routes=None):
    """Shared construction for the legacy copilot and typed business workflow."""
    graph = StateGraph(state_type)
    for node_name, handler in nodes.items():
        graph.add_node(node_name, handler)
    graph.set_entry_point(entry)
    for source, target in edges:
        graph.add_edge(source, target)
    if routes:
        for source, router in routes.items():
            graph.add_conditional_edges(source, router)
    return graph.compile()

app_graph = build_workflow(GraphState, {
    "planner_node": planner_node, "sql_generator_node": sql_generator_node,
    "semantic_node": semantic_node, "action_node": action_node,
    "synthesizer_node": synthesizer_node,
}, "planner_node", [
    ("sql_generator_node", "synthesizer_node"), ("semantic_node", "synthesizer_node"),
    ("action_node", END), ("synthesizer_node", END),
], {"planner_node": route_query})


class BusinessGraphState(TypedDict, total=False):
    request: dict
    parsed: dict
    result: dict
    operation: str
    company_ids: list[str]


def _business_runtime(config):
    # Trusted principal/session live only in per-invocation runtime configuration.
    return config["configurable"]["business_runtime"]


async def business_planner_node(state, config):
    from app.services.business_command_service import CommandRequest, plan_command
    principal, db = _business_runtime(config)
    parsed = await plan_command(CommandRequest.model_validate(state["request"]), principal, db)
    return {"parsed": parsed.model_dump(mode="json")}


def business_route(state):
    intent = state["parsed"]["intent"]
    if intent == "stock_read":
        return "stock_scope"
    if intent in ("supplier_list", "supplier_read", "purchase_create", "sale_create", "inventory_add", "inventory_change", "stock_count_set", "mcp_read", "mcp_write"):
        return "tally_tool"
    if intent in ("customer_history", "portfolio_history"):
        return "history_tool"
    if intent.startswith("customer_"):
        return "customer_tool"
    if intent.startswith("task_"):
        return "task_tool"
    if intent == "reminder_draft":
        return "reminder_tool"
    return "conversation_tool"


def business_entry(state):
    return "approval_tool" if state["operation"] == "approval" else "business_planner"


async def business_start_node(state):
    return {}


def business_tool_node():
    async def execute(state, config):
        from app.services.business_command_service import CommandRequest, ParsedCommand, execute_command
        principal, db = _business_runtime(config)
        parsed = ParsedCommand.model_validate(state["parsed"])
        if parsed.intent == 'mcp_read':
            from app.services.tally_mcp_service import read_report
            result = await read_report(db, principal, parsed)
        elif parsed.intent == 'mcp_write':
            from app.services.tally_mcp_service import prepare_write
            result = await prepare_write(db, principal, parsed)
        elif parsed.intent == 'stock_read':
            from app.services.tally_stock import read_stock, resolve_scope
            scope = await resolve_scope(db, principal, parsed)
            scope = [c for c in scope if c.id in state.get('company_ids', [])]
            result = await read_stock(db, principal, parsed, scope)
        else:
            result = await execute_command(CommandRequest.model_validate(state["request"]), principal, db, parsed)
        return {"result": result}
    return execute


async def business_stock_scope(state, config):
    from app.services.business_command_service import ParsedCommand
    from app.services.tally_stock import resolve_scope
    principal, db = _business_runtime(config)
    rows = await resolve_scope(db, principal, ParsedCommand.model_validate(state['parsed']))
    return {'company_ids': [c.id for c in rows]}


async def business_approval_node(state, config):
    from app.services.business_command_service import ApprovalRequest, confirm
    principal, db = _business_runtime(config)
    return {"result": await confirm(ApprovalRequest.model_validate(state["request"]), principal, db)}


def traced_business_node(node_name, handler):
    async def traced(state, config):
        from time import perf_counter
        start = perf_counter()
        outcome = "ok"
        try:
            return await handler(state, config)
        except Exception:
            outcome = "error"
            raise
        finally:
            logger.info("business_graph node=%s outcome=%s duration_ms=%.1f", node_name, outcome,
                        (perf_counter()-start)*1000)
    return traced


_business_tools = {key: traced_business_node(key, business_tool_node()) for key in (
    "customer_tool", "task_tool", "reminder_tool", "tally_tool", "history_tool", "conversation_tool")}
business_graph = build_workflow(BusinessGraphState, {
    "start": business_start_node,
    "business_planner": traced_business_node("business_planner", business_planner_node),
    "stock_scope": traced_business_node("stock_scope", business_stock_scope),
    "approval_tool": traced_business_node("approval_tool", business_approval_node), **_business_tools,
}, "start", [(key, END) for key in (*_business_tools, "approval_tool")] + [('stock_scope', 'tally_tool')],
    {"start": business_entry, "business_planner": business_route})


async def run_business_graph(request, principal, db, approval=False):
    result = await business_graph.ainvoke({"request": request.model_dump(mode="json"),
                                         "operation": "approval" if approval else "command"},
        {"configurable": {"business_runtime": (principal, db)}, "recursion_limit": 12})
    return result["result"]


async def _process_copilot_query(query: str, organization_id: str, user_id: str, role: str, db: AsyncSession, client_name: str | None = None) -> dict:
    if _is_greeting(query):
        return {
            "answer": "Hi! Ask me about clients, meeting notes, concerns, or upcoming commitments.",
            "source_type": "local",
            "data": None,
        }

    meeting_date = _meeting_schedule_date(query)
    if meeting_date:
        return await _lookup_meetings_for_date(meeting_date, organization_id, user_id, role, db)

    if client_name:
        return await _lookup_client_profile(client_name, organization_id, user_id, role, db)

    extracted_name = _extract_client_lookup_name(query)
    if extracted_name:
        return await _lookup_client_profile(extracted_name, organization_id, user_id, role, db)

    # Check for confirmation intent first (e.g., "yes", "send it", "haan bhej do")
    normalized_query = query.strip().lower()
    confirmation_words = ["yes", "send", "haan", "bhej do", "yep", "confirm", "sure"]
    rejection_words = ["no", "cancel", "stop", "mat bhej", "reject"]

    redis = await get_redis_client()
    redis_key = f"pending_reminder_copilot:{user_id}"

    if any(w == normalized_query for w in confirmation_words) or any(w in normalized_query for w in ["bhej do", "send it", "yes send"]):
        pending_data_str = await redis.get(redis_key)
        if pending_data_str:
            try:
                pending_data = json.loads(pending_data_str)
                result = await ReminderService().dispatch_client_reminder(
                    pending_data, 
                    db=db, 
                    user_id=user_id, 
                    organization_id=organization_id
                )
                await redis.delete(redis_key)
                return {
                    "answer": result["message"],
                    "source_type": "action",
                    "data": None
                }
            except Exception as e:
                logger.error(f"Failed to dispatch pending reminder: {e}")
                return {"answer": "There was an error sending the message.", "source_type": "error"}
    
    if any(w == normalized_query for w in rejection_words) or any(w in normalized_query for w in ["cancel", "mat bhej", "stop"]):
        if await redis.exists(redis_key):
            await redis.delete(redis_key)
            return {"answer": "Okay, I have cancelled the message.", "source_type": "action"}

    initial_state = {
        "query": query,
        "organization_id": organization_id,
        "user_id": user_id,
        "role": role,
        "route": "",
        "sql_query": "",
        "sql_error": "",
        "db_result": "",
        "final_answer": ""
    }
    
    # Run LangGraph Planner & Generator
    final_state = await app_graph.ainvoke(initial_state)
    
    # Execute SQL or Vector DB Operations outside the graph
    if final_state["route"] == "action":
        try:
            result = await ReminderService().draft_client_reminder(
                db=db,
                organization_id=organization_id,
                user_id=user_id,
                role=role,
                client_name=final_state.get("action_client_name", ""),
                instruction=final_state.get("action_instruction", query),
                channel=ReminderService._resolve_channel(query),
            )
            
            if result.get("status") == "success" and "draft_data" in result:
                await redis.setex(
                    redis_key,
                    300, # 5 minutes TTL
                    json.dumps(result["draft_data"])
                )
            
            return {
                "answer": result["message"],
                "source_type": "action",
                "data": None
            }
        except Exception:
            logger.exception("Portfolio copilot action route failed")
            return {
                "answer": "Sorry, I couldn't draft the reminder right now.",
                "source_type": "error",
                "data": None
            }
            
    elif final_state["route"] == "sql" and final_state.get("sql_query"):
        try:
            logger.info(f"GENERATED SQL QUERY: {final_state['sql_query']}")
            result = await db.execute(text(final_state["sql_query"]))
            await db.commit()
            
            if result.returns_rows:
                rows = result.fetchall()
                data = [dict(row._mapping) for row in rows]
            else:
                if result.rowcount == 0:
                    data = [{"status": "error", "message": "No matching records found to update."}]
                else:
                    data = [{"status": "success", "message": f"Database updated successfully. Affected {result.rowcount} rows."}]
            
            synth_prompt = SYNTHESIZER_SYSTEM_PROMPT.format(data=json.dumps(data, default=str))
            synth_resp = await _complete_with_retry(
                messages=[
                    {"role": "system", "content": synth_prompt},
                    {"role": "user", "content": query}
                ]
            )
            return {"answer": synth_resp.choices[0].message.content, "source_type": "sql", "data": data}
        except Exception:
            logger.exception("Portfolio copilot SQL route failed")
            return {
                "answer": "I couldn't retrieve your portfolio data right now. Please try again in a moment.",
                "source_type": "unavailable",
                "data": None,
            }
            
    elif final_state["route"] == "vector":
        query_vector = generate_query_embedding(query)
        
        if role.lower() == "member":
            stmt = text("""
                SELECT me.chunk_text, m.summary 
                FROM meeting_evidence me
                JOIN meetings m ON me.meeting_id = m.id
                WHERE m.organization_id = :org_id AND m.user_id = :user_id
                ORDER BY me.embedding <=> CAST(:vector AS vector)
                LIMIT 5
            """)
            result = await db.execute(stmt, {"org_id": organization_id, "user_id": user_id, "vector": str(query_vector)})
        else:
            stmt = text("""
                SELECT me.chunk_text, m.summary 
                FROM meeting_evidence me
                JOIN meetings m ON me.meeting_id = m.id
                WHERE m.organization_id = :org_id
                ORDER BY me.embedding <=> CAST(:vector AS vector)
                LIMIT 5
            """)
            result = await db.execute(stmt, {"org_id": organization_id, "vector": str(query_vector)})
        rows = result.fetchall()
        data = [dict(row._mapping) for row in rows]
        
        synth_prompt = SYNTHESIZER_SYSTEM_PROMPT.format(data=json.dumps(data, default=str))
        synth_resp = await _complete_with_retry(
            messages=[
                {"role": "system", "content": synth_prompt},
                {"role": "user", "content": query}
            ]
        )
        return {"answer": synth_resp.choices[0].message.content, "source_type": "vector", "data": data}

    return {
        "answer": "I couldn't determine how to answer that. Please rephrase your question.",
        "source_type": "unavailable",
        "data": None,
    }


async def process_copilot_query(query: str, organization_id: str, user_id: str, role: str, db: AsyncSession, client_name: str | None = None) -> dict:
    try:
        return await _process_copilot_query(query, organization_id, user_id, role, db, client_name=client_name)
    except Exception as e:
        logger.error(f"Portfolio Copilot Error: {e}", exc_info=True)
        return {
            "answer": "I couldn't retrieve your portfolio data right now. Please try again in a moment.",
            "source_type": "unavailable",
            "data": None,
        }
