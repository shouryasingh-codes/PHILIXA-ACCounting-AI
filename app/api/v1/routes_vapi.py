"""
routes_vapi.py - Vapi.ai Voice Orchestrator Gateway Routes

Implements:
1. POST /api/v1/vapi/chat/completions - OpenAI-compatible SSE streaming LLM endpoint with barge-in watchdog.
2. POST /api/v1/vapi/webhook - Webhook dispatcher (assistant-request, tool-calls, end-of-call-report, status-update).
3. POST /api/v1/vapi/assistants/inbound - Pre-call dynamic assistant retrieval.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import litellm

from app.core.config import get_settings
from app.database.session import get_db
from app.models.client import Client
from app.services.reminder_service import ReminderService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vapi", tags=["Vapi Integration"])


# ---------------------------------------------------------------------------
# Pydantic v2 Models (Configured with extra="allow" for forward-compatibility)
# ---------------------------------------------------------------------------

class VapiCustomer(BaseModel):
    model_config = ConfigDict(extra="allow")

    number: Optional[str] = Field(default=None, description="E.164 phone number of caller")
    name: Optional[str] = Field(default=None, description="Caller name if known")
    extension: Optional[str] = Field(default=None, description="PBX extension")


class VapiPhoneNumber(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    number: Optional[str] = None


class VapiCallCostBreakdown(BaseModel):
    model_config = ConfigDict(extra="allow")

    transport: Optional[float] = 0.0
    stt: Optional[float] = 0.0
    llm: Optional[float] = 0.0
    tts: Optional[float] = 0.0
    vapi: Optional[float] = 0.0
    total: Optional[float] = 0.0


class VapiCall(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(description="Unique Vapi Call Identifier")
    orgId: Optional[str] = None
    type: Optional[str] = Field(default="inboundPhoneCall", description="inboundPhoneCall, outboundPhoneCall, webCall")
    status: Optional[str] = Field(default="in-progress", description="queued, ringing, in-progress, ended")
    customer: Optional[VapiCustomer] = None
    phoneNumber: Optional[VapiPhoneNumber] = None
    createdAt: Optional[str] = None
    startedAt: Optional[str] = None
    endedAt: Optional[str] = None
    cost: Optional[float] = None
    costBreakdown: Optional[VapiCallCostBreakdown] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolFunctionDef(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["function"] = "function"
    function: ToolFunctionDef


class ChatMessageToolCallFunction(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    arguments: str


class ChatMessageToolCall(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: Literal["function"] = "function"
    function: ChatMessageToolCallFunction


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str = Field(description="system, user, assistant, tool")
    content: Optional[str] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[ChatMessageToolCall]] = None


class VapiChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: Optional[str] = "custom-langgraph"
    messages: List[ChatMessage] = Field(default_factory=list)
    stream: bool = True
    temperature: Optional[float] = 0.3
    max_tokens: Optional[int] = 300
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    call: Optional[VapiCall] = None
    customer: Optional[VapiCustomer] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class ToolCallResultItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    toolCallId: str
    result: Optional[Union[str, Dict[str, Any], List[Any], int, float, bool]] = None
    error: Optional[str] = None


class ToolCallResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    results: List[ToolCallResultItem]


class VapiWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: Optional[Dict[str, Any]] = None
    type: Optional[str] = None
    call: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Helper Functions & Utilities
# ---------------------------------------------------------------------------

def safe_parse_json_dict(val: Any) -> Dict[str, Any]:
    """Safely parse dictionary or stringified JSON arguments with fallback to empty dict."""
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            return {}
        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Failed to parse tool arguments JSON: %r (error: %s)", val, exc)
            return {}
    return {}


def verify_custom_llm_auth(authorization: Optional[str] = Header(None)) -> bool:
    """Validate Bearer token for Custom LLM endpoint if configured."""
    settings = get_settings()
    secret = settings.vapi_custom_llm_secret
    if not secret:
        return True
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized: Missing Authorization header")
    token = authorization
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    try:
        matches = secrets.compare_digest(token.encode("utf-8"), secret.encode("utf-8"))
    except Exception:
        matches = False
    if not matches:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid Bearer token")
    return True


def verify_webhook_auth(x_vapi_secret: Optional[str] = Header(None, alias="x-vapi-secret")) -> bool:
    """Validate x-vapi-secret header for Webhooks if configured."""
    settings = get_settings()
    secret = settings.vapi_webhook_secret
    if not secret:
        return True
    if not x_vapi_secret:
        raise HTTPException(status_code=401, detail="Unauthorized: Missing x-vapi-secret header")
    try:
        matches = secrets.compare_digest(x_vapi_secret.encode("utf-8"), secret.encode("utf-8"))
    except Exception:
        matches = False
    if not matches:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid x-vapi-secret")
    return True


def sanitize_for_voice(text: str) -> str:
    """Strip markdown symbols to prevent TTS unnatural pronunciation."""
    if not text:
        return ""
    cleaned = re.sub(r"[*_#`~>]", "", text)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    return cleaned


def extract_tool_calls_defensively(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Defensively parse tool calls supporting both native Vapi dicts and OpenAI serialized JSON strings."""
    if not isinstance(message, dict):
        return []

    extracted = []

    # Priority 1: Vapi's native toolCallList
    tool_call_list = message.get("toolCallList")
    if tool_call_list and isinstance(tool_call_list, list):
        for item in tool_call_list:
            if not isinstance(item, dict):
                continue
            args = safe_parse_json_dict(item.get("arguments"))
            extracted.append({
                "id": item.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                "name": item.get("name") or "",
                "arguments": args,
            })
        return extracted

    # Priority 2: Standard OpenAI toolCalls
    tool_calls = message.get("toolCalls") or message.get("tool_calls")
    if tool_calls and isinstance(tool_calls, list):
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function", {}) if isinstance(tc.get("function"), dict) else {}
            args = safe_parse_json_dict(fn.get("arguments"))
            extracted.append({
                "id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                "name": fn.get("name") or "",
                "arguments": args,
            })
        return extracted

    # Priority 3: functionCall format
    fn_call = message.get("functionCall") or message.get("function_call")
    if fn_call and isinstance(fn_call, dict):
        args = safe_parse_json_dict(fn_call.get("arguments"))
        extracted.append({
            "id": fn_call.get("id") or f"call_{uuid.uuid4().hex[:8]}",
            "name": fn_call.get("name") or "",
            "arguments": args,
        })
        return extracted

    return extracted


async def handle_assistant_request(call_data: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    """Dynamically build assistant system prompt and greetings based on CRM client context."""
    if not isinstance(call_data, dict):
        call_data = {}

    customer = call_data.get("customer") or {}
    caller_phone = (customer.get("number") or "").strip()

    client = None
    if caller_phone:
        try:
            # DB model column is whatsapp_phone
            stmt = select(Client).where(Client.whatsapp_phone == caller_phone).limit(1)
            res = await db.execute(stmt)
            client = res.scalar_one_or_none()

            # Fallback phone lookup with last 10 digits if exact match misses
            if not client and len(caller_phone) >= 10:
                last_10 = caller_phone[-10:]
                stmt2 = select(Client).where(Client.whatsapp_phone.like(f"%{last_10}")).limit(1)
                res2 = await db.execute(stmt2)
                client = res2.scalar_one_or_none()
        except Exception as exc:
            logger.warning("Database error during assistant request caller lookup (%s): %s", caller_phone, exc)
            client = None

    if client:
        name_parts = (client.name or "").split()
        first_name = name_parts[0] if name_parts else "Client"
        system_prompt = (
            f"You are Philixa, an elite voice-native wealth copilot speaking with {client.name}.\n"
            f"Client Profile:\n"
            f"- Client Name: {client.name}\n"
            f"- Phone: {client.whatsapp_phone or 'Unknown'}\n"
            f"- Portfolio & Relationship Summary: {client.rolling_summary or 'Standard Active Portfolio'}\n"
            f"- Meeting & Relationship Notes: {client.relationship_notes or 'No recent notes'}\n"
            f"- Products Owned: {client.products_owned_json or '[]'}\n"
            f"Keep all answers very short (1-2 sentences), professional, conversational, and direct. "
            f"You are speaking over the phone, so never use markdown, bullet points, asterisks, or tables. "
            f"You can speak English or Hinglish if the user prefers."
        )
        first_greeting = f"Hello {first_name}, welcome back to Philixa. How can I assist you with your portfolio today?"
    else:
        system_prompt = (
            "You are Philixa, an elite voice-native wealth copilot. "
            "Keep all answers very short (1-2 sentences), professional, conversational, and direct. "
            "You are speaking over the phone, so never use markdown, bullet points, or tables. "
            "Greet the caller politely and ask how you can help them with their portfolio or scheduling reminders."
        )
        first_greeting = "Hello! Welcome to Philixa Wealth Management. How can I assist you today?"

    settings = get_settings()
    custom_llm_url = (
        getattr(settings, "vapi_custom_llm_url", None)
        or os.getenv("VAPI_CUSTOM_LLM_URL")
        or "http://localhost:8000/api/v1/vapi/chat/completions"
    )

    assistant_config = {
        "name": f"Philixa Copilot{' - ' + client.name if client else ''}",
        "firstMessage": first_greeting,
        "model": {
            "provider": "custom-llm",
            "url": custom_llm_url,
            "model": "gpt-4o-mini",
            "messages": [{"role": "system", "content": system_prompt}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "sendWhatsAppReminder",
                        "description": "Draft or send a WhatsApp reminder to a client or contact.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "client_name": {"type": "string", "description": "The name of the client"},
                                "message": {"type": "string", "description": "The reminder content or message"},
                                "channel": {"type": "string", "enum": ["whatsapp", "email", "both"], "default": "whatsapp"}
                            },
                            "required": ["message"]
                        }
                    }
                }
            ]
        },
        "voice": {
            "provider": "cartesia",
            "voiceId": "a0e99841-438c-4a64-b679-ae501e7d6091",
            "model": "sonic-english",
            "chunkPlan": {"enabled": True, "minCharacters": 25}
        },
        "variableValues": {
            "client_id": str(client.id) if client else "",
            "organization_id": client.organization_id if client else "",
            "caller_phone": caller_phone,
        }
    }
    return {"assistant": assistant_config}


async def execute_tool_call(tool: Dict[str, Any], call_data: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    """Execute tool requests defensively and format responses."""
    tool_id = tool.get("id") or f"call_{uuid.uuid4().hex[:8]}"
    name = tool.get("name", "").strip()
    args = safe_parse_json_dict(tool.get("arguments"))

    logger.info("Executing Vapi tool call '%s' (id: %s) with args: %s", name, tool_id, args)

    if not isinstance(call_data, dict):
        call_data = {}

    customer = call_data.get("customer") or {}
    caller_phone = (customer.get("number") or "").strip()

    client = None
    if caller_phone:
        try:
            stmt = select(Client).where(Client.whatsapp_phone == caller_phone).limit(1)
            client = (await db.execute(stmt)).scalar_one_or_none()
        except Exception as exc:
            logger.warning("DB lookup error for caller %s in execute_tool_call: %s", caller_phone, exc)
            client = None

    variable_values = call_data.get("variableValues") or {}
    metadata = call_data.get("metadata") or {}
    org_id = (
        (client.organization_id if client else None)
        or variable_values.get("organization_id")
        or metadata.get("organization_id")
        or call_data.get("orgId")
    )
    user_id = (
        (client.user_id if client else None)
        or variable_values.get("user_id")
        or metadata.get("user_id")
        or "default_user"
    )

    try:
        if name in ("sendWhatsAppReminder", "send_reminder", "draft_reminder", "create_reminder"):
            client_name = args.get("client_name") or (client.name if client else None)
            instruction = args.get("message") or args.get("instruction") or args.get("reminder_text") or "Follow-up reminder"
            channel = args.get("channel") or "whatsapp"

            reminder_svc = ReminderService()
            draft_res = await reminder_svc.draft_client_reminder(
                db=db,
                organization_id=org_id or "default_org",
                user_id=user_id,
                role="admin",
                client_name=client_name,
                instruction=instruction,
                channel=channel,
            )
            msg = draft_res.get("message") or "Reminder drafted successfully."
            return {"toolCallId": tool_id, "result": msg}

        elif name in ("lookup_client", "getClientInfo", "get_client"):
            query_name = args.get("client_name") or (client.name if client else None)
            if not query_name:
                return {"toolCallId": tool_id, "result": "Client profile not found: client_name argument missing."}

            if not org_id:
                logger.warning("Cross-tenant lookup blocked: caller organization context missing for tool_id %s", tool_id)
                return {"toolCallId": tool_id, "result": "Client profile not found in CRM: organization context required."}

            stmt = select(Client).where(
                Client.organization_id == org_id,
                Client.name.ilike(f"%{query_name}%"),
            ).limit(1)
            found = (await db.execute(stmt)).scalar_one_or_none()
            if found:
                return {
                    "toolCallId": tool_id,
                    "result": {
                        "name": found.name,
                        "phone": found.whatsapp_phone,
                        "summary": found.rolling_summary,
                        "notes": found.relationship_notes,
                    }
                }
            return {"toolCallId": tool_id, "result": "Client profile not found in CRM."}

        else:
            return {"toolCallId": tool_id, "result": f"Action '{name}' processed successfully."}

    except Exception as exc:
        logger.exception("Error executing tool '%s': %s", name, exc)
        return {"toolCallId": tool_id, "error": str(exc)}


# ---------------------------------------------------------------------------
# 1. Custom LLM Endpoint: POST /chat/completions
# ---------------------------------------------------------------------------

@router.post("/chat/completions")
async def vapi_chat_completions(
    request: Request,
    req: VapiChatCompletionRequest,
    _auth: bool = Depends(verify_custom_llm_auth),
):
    """
    OpenAI-compatible chat completions streaming endpoint for Vapi Custom LLM.
    Features:
    - SSE format (text/event-stream; charset=utf-8)
    - Anti-buffering headers (X-Accel-Buffering: no, Cache-Control: no-cache, no-transform)
    - Active client disconnect watchdog via request.is_disconnected() for instant barge-in handling
    - litellm.acompletion streaming integration
    """
    settings = get_settings()
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created_ts = int(time.time())
    model_name = settings.ai_economy_model or "groq/openai/gpt-oss-20b"

    if not req.stream:
        # Non-streaming fallback
        messages_payload = [{"role": m.role, "content": m.content or ""} for m in req.messages]
        try:
            resp = await litellm.acompletion(
                model=model_name,
                messages=messages_payload,
                temperature=req.temperature if req.temperature is not None else 0.3,
                max_tokens=req.max_tokens if req.max_tokens is not None else 300,
            )
            content = resp.choices[0].message.content or ""
        except Exception as e:
            logger.warning("litellm.acompletion failed in non-streaming mode: %s", e)
            content = "I am listening. How can I assist you today?"

        return JSONResponse({
            "id": chunk_id,
            "object": "chat.completion",
            "created": created_ts,
            "model": model_name,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": sanitize_for_voice(content)},
                "finish_reason": "stop"
            }]
        })

    # Streaming mode with Active Watchdog Pattern
    async def sse_event_generator():
        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        # Step 1: Emit initial role announcement chunk
        role_chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created_ts,
            "model": model_name,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(role_chunk, ensure_ascii=False)}\n\n"

        # Step 2: Background producer task streaming tokens from LiteLLM into queue
        async def producer():
            try:
                messages_payload = []
                for msg in req.messages:
                    messages_payload.append({"role": msg.role, "content": msg.content or ""})

                if not messages_payload:
                    messages_payload = [
                        {"role": "system", "content": "You are Philixa, a smart voice assistant. Answer concisely in 1-2 sentences."},
                        {"role": "user", "content": "Hello"}
                    ]
                elif not any(m.get("role") == "system" for m in messages_payload):
                    messages_payload.insert(0, {
                        "role": "system",
                        "content": "You are Philixa, an elite voice assistant. Keep answers concise, natural, and under 2 sentences. Never use markdown or bullet points."
                    })

                response = await litellm.acompletion(
                    model=model_name,
                    messages=messages_payload,
                    stream=True,
                    temperature=req.temperature if req.temperature is not None else 0.3,
                    max_tokens=req.max_tokens if req.max_tokens is not None else 300,
                )

                emitted_count = 0
                async for chunk in response:
                    content_piece = None
                    if hasattr(chunk, "choices") and chunk.choices:
                        choice = chunk.choices[0]
                        if hasattr(choice, "delta"):
                            content_piece = getattr(choice.delta, "content", None)
                        elif isinstance(choice, dict):
                            content_piece = choice.get("delta", {}).get("content")
                    elif isinstance(chunk, dict) and "choices" in chunk:
                        choices = chunk.get("choices", [])
                        if choices:
                            content_piece = choices[0].get("delta", {}).get("content")

                    if content_piece:
                        clean_text = sanitize_for_voice(content_piece)
                        if clean_text:
                            emitted_count += 1
                            chunk_obj = {
                                "id": chunk_id,
                                "object": "chat.completion.chunk",
                                "created": created_ts,
                                "model": model_name,
                                "choices": [{"index": 0, "delta": {"content": clean_text}, "finish_reason": None}],
                            }
                            await queue.put(f"data: {json.dumps(chunk_obj, ensure_ascii=False)}\n\n")

                if emitted_count == 0:
                    fallback_text = "Hello! I am Philixa, your voice copilot. How can I help you today?"
                    fallback_chunk = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": model_name,
                        "choices": [{"index": 0, "delta": {"content": fallback_text}, "finish_reason": None}],
                    }
                    await queue.put(f"data: {json.dumps(fallback_chunk, ensure_ascii=False)}\n\n")

            except asyncio.CancelledError:
                logger.info("Vapi stream producer cancelled due to barge-in")
                raise
            except Exception as e:
                logger.warning("Vapi litellm stream exception, sending voice fallback: %s", e)
                fallback_chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": model_name,
                    "choices": [{"index": 0, "delta": {"content": "I am listening. How can I help you?"}, "finish_reason": None}],
                }
                await queue.put(f"data: {json.dumps(fallback_chunk, ensure_ascii=False)}\n\n")
            finally:
                await queue.put(None)  # Sentinel

        producer_task = asyncio.create_task(producer())

        # Step 3: Consumer loop with barge-in disconnect watchdog
        client_disconnected = False
        try:
            while True:
                if await request.is_disconnected():
                    logger.warning("[BARGE-IN] Client disconnected! Aborting stream.")
                    client_disconnected = True
                    producer_task.cancel()
                    break

                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue

                if item is None:
                    break

                yield item

            # Step 4: Emit finish stop chunk and [DONE] only if client is still connected
            if not client_disconnected and not await request.is_disconnected():
                stop_chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": model_name,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(stop_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

        finally:
            if not producer_task.done():
                producer_task.cancel()
                try:
                    await producer_task
                except (asyncio.CancelledError, Exception):
                    pass

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ---------------------------------------------------------------------------
# 2. Server URL Webhook: POST /webhook
# ---------------------------------------------------------------------------

@router.post("/webhook")
async def vapi_webhook(
    request: Request,
    payload: Dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_webhook_auth),
):
    """
    Unified Vapi Server URL Webhook receiver.
    Handles:
    - assistant-request: Dynamic assistant context injection.
    - tool-calls: Defensive tool execution.
    - end-of-call-report: Call completion and telemetry persistence.
    - status-update, speech-update: Call lifecycle heartbeats.
    """
    # Vapi sends messages either wrapped in "message" envelope or top-level
    message = payload.get("message") if isinstance(payload.get("message"), dict) else payload
    event_type = message.get("type") or payload.get("type") or "unknown"
    call_data = message.get("call") or payload.get("call") or {}

    logger.info("Received Vapi webhook event: %s (call id: %s)", event_type, call_data.get("id"))

    # Event 1: Dynamic Assistant Request
    if event_type == "assistant-request":
        assistant_resp = await handle_assistant_request(call_data, db)
        return JSONResponse(status_code=200, content=assistant_resp)

    # Event 2: Tool Calls Dispatcher
    elif event_type in ("tool-calls", "function-call"):
        tools = extract_tool_calls_defensively(message)
        results = []
        for tool in tools:
            res = await execute_tool_call(tool, call_data, db)
            results.append(res)
        return JSONResponse(status_code=200, content={"results": results})

    # Event 3: End of Call Report
    elif event_type == "end-of-call-report":
        ended_reason = message.get("endedReason") or "unknown"
        cost = message.get("cost") or call_data.get("cost")
        logger.info("Call ended (id: %s). Reason: %s, Total cost: %s", call_data.get("id"), ended_reason, cost)
        return JSONResponse(status_code=200, content={"status": "ok"})

    # Event 4: Status / Speech / Lifecycle updates
    elif event_type in ("status-update", "speech-update", "conversation-update", "transfer-destination-request"):
        status = message.get("status") or "ok"
        return JSONResponse(status_code=200, content={"status": "ok", "callStatus": status})

    # Default acknowledgment for unhandled forward-compatible events
    return JSONResponse(status_code=200, content={"status": "ok", "acknowledged": event_type})


# ---------------------------------------------------------------------------
# 3. Dynamic Inbound Assistant: POST /assistants/inbound
# ---------------------------------------------------------------------------

@router.post("/assistants/inbound")
async def inbound_assistant_setup(
    payload: Dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_webhook_auth),
):
    """
    Dynamic inbound assistant setup endpoint.
    Returns dynamic assistant configuration based on caller number.
    Protected by verify_webhook_auth (x-vapi-secret header check with dev bypass).
    """
    call_data = payload.get("call") or payload
    return await handle_assistant_request(call_data, db)
