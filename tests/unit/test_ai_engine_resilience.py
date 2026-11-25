import asyncio
import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import arq.connections
import pytest
from pydantic import BaseModel

from app.ai import groq_gateway
from app.ai.groq_gateway import QuotaDeferred
import app.database.session as db_session
from app.jobs import task_agent_jobs
from app.jobs.task_agent_jobs import quota_wait
from app.models.groq_quota import GroqQuotaCooldown, GroqQuotaRequest
from app.services import (
    ai_engine_manager,
    intent_router,
    intent_router_model,
    task_agent_model,
    task_agent_runtime,
    task_agent_service,
    task_agent_tools,
)
from app.services.ai_engine_manager import EngineRequestError, call_gemini_json
from app.services.task_agent_model import AgentProviderUnavailable


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


def _gemini_ok_payload(text: str = '{"intent": "general_chat"}') -> dict:
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"parts": [{"text": text}]},
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 12,
            "candidatesTokenCount": 6,
            "totalTokenCount": 18,
        },
    }


def _patch_gemini_client(monkeypatch: pytest.MonkeyPatch, responses: list[_FakeResponse]) -> list[str]:
    called_urls: list[str] = []
    queue = list(responses)

    class _FakeClient:
        async def post(self, url: str, **kwargs):
            called_urls.append(url)
            return queue.pop(0)

    class _FakeClientCM:
        async def __aenter__(self):
            return _FakeClient()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        ai_engine_manager,
        "get_settings",
        lambda: SimpleNamespace(gemini_api_key="test-gemini-key"),
    )
    monkeypatch.setattr(ai_engine_manager, "gemini_client", lambda: _FakeClientCM())
    return called_urls


def test_gemini_503_falls_back_to_flash_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PHILIXA_GEMINI_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("PHILIXA_GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
    called_urls = _patch_gemini_client(
        monkeypatch,
        [_FakeResponse(503), _FakeResponse(200, _gemini_ok_payload())],
    )

    output, usage = asyncio.run(call_gemini_json("sys", "user", timeout_seconds=8))

    assert output == '{"intent": "general_chat"}'
    assert usage["provider"] == "gemini"
    assert usage["model"] == "gemini-2.5-flash"
    assert usage["attempts"] == 2
    assert len(called_urls) == 2
    assert called_urls[0].endswith("/models/gemini-3.5-flash-lite:generateContent")
    assert called_urls[1].endswith("/models/gemini-2.5-flash:generateContent")


@pytest.mark.parametrize("status_code", [401, 403, 429])
def test_gemini_non_transient_errors_do_not_retry(monkeypatch: pytest.MonkeyPatch, status_code: int):
    monkeypatch.setenv("PHILIXA_GEMINI_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("PHILIXA_GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
    called_urls = _patch_gemini_client(monkeypatch, [_FakeResponse(status_code)])

    with pytest.raises(EngineRequestError) as exc_info:
        asyncio.run(call_gemini_json("sys", "user", timeout_seconds=8))

    assert exc_info.value.code == "provider_http_error"
    assert exc_info.value.status == status_code
    assert len(called_urls) == 1


def test_gemini_503_on_primary_and_fallback_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PHILIXA_GEMINI_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("PHILIXA_GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
    called_urls = _patch_gemini_client(
        monkeypatch,
        [_FakeResponse(503), _FakeResponse(503)],
    )

    with pytest.raises(EngineRequestError) as exc_info:
        asyncio.run(call_gemini_json("sys", "user", timeout_seconds=8))

    assert exc_info.value.code == "provider_http_error"
    assert exc_info.value.status == 503
    assert len(called_urls) == 2


def test_agent_provider_unavailable_503_messages():
    gemini_err = AgentProviderUnavailable(503, provider="gemini")
    groq_err = AgentProviderUnavailable(503, provider="groq")

    assert gemini_err.code == "provider_unavailable"
    assert "503" in gemini_err.safe_message
    assert "Gemini" in gemini_err.safe_message

    assert groq_err.code == "provider_unavailable"
    assert "503" in groq_err.safe_message
    assert "Groq" in groq_err.safe_message


class _FakeQuotaStore:
    def __init__(self):
        self.requests: dict[str, GroqQuotaRequest] = {}
        self.cooldowns: dict[str, GroqQuotaCooldown] = {}


class _FakeQuotaSession:
    def __init__(self, store: _FakeQuotaStore):
        self._store = store

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        return self

    def execute(self, *args, **kwargs):
        return None

    def get(self, model, key):
        if model is GroqQuotaCooldown:
            return self._store.cooldowns.get(key)
        if model is GroqQuotaRequest:
            return self._store.requests.get(key)
        raise AssertionError(f"Unexpected model lookup: {model}")

    def add(self, obj):
        if isinstance(obj, GroqQuotaCooldown):
            self._store.cooldowns[obj.bucket] = obj
        elif isinstance(obj, GroqQuotaRequest):
            self._store.requests[obj.id] = obj
        else:
            raise AssertionError(f"Unexpected object: {type(obj)}")

    def scalars(self, stmt):
        rows = list(self._store.requests.values())
        for criterion in stmt._where_criteria:
            col = criterion.left.key
            expected = criterion.right.value
            op = criterion.operator
            rows = [row for row in rows if op(getattr(row, col), expected)]
        return rows


def _patch_quota_store(monkeypatch: pytest.MonkeyPatch, initial_now: datetime):
    store = _FakeQuotaStore()
    clock = [initial_now]
    monkeypatch.setenv("PHILIXA_GROQ_RPM", "30")
    monkeypatch.setenv("PHILIXA_GROQ_TPM", "8000")
    monkeypatch.setenv("PHILIXA_GROQ_RPD", "1000")
    monkeypatch.setenv("PHILIXA_GROQ_TPD", "200000")
    monkeypatch.setattr(groq_gateway, "Session", lambda _eng: _FakeQuotaSession(store))
    monkeypatch.setattr(groq_gateway, "engine", lambda: object())
    monkeypatch.setattr(groq_gateway, "now", lambda: clock[0])
    return store, clock


def test_groq_admit_succeeds_immediately_after_provider_reset_window(monkeypatch: pytest.MonkeyPatch):
    t0 = datetime(2026, 11, 25, 1, 10, 0, tzinfo=timezone.utc)
    store, clock = _patch_quota_store(monkeypatch, t0)
    bucket = "a" * 64

    ident1 = groq_gateway.admit(bucket, 3500)
    groq_gateway.settle(
        ident1,
        bucket,
        {"total_tokens": 3500},
        {"x-ratelimit-remaining-tokens": "4500", "x-ratelimit-reset-tokens": "13s"},
        200,
        0.2,
    )

    clock[0] = t0 + timedelta(seconds=1)
    with pytest.raises(QuotaDeferred) as caught:
        groq_gateway.admit(bucket, 4800)
    assert caught.value.reason == "minute_quota"
    assert caught.value.retry_at == t0 + timedelta(seconds=13.5)

    clock[0] = t0 + timedelta(seconds=14)
    ident2 = groq_gateway.admit(bucket, 4800)
    assert ident2 in store.requests
    assert store.requests[ident2].status == "reserved"


def test_groq_zero_second_reset_keeps_rolling_fallback(monkeypatch: pytest.MonkeyPatch):
    t0 = datetime(2026, 11, 25, 1, 10, 0, tzinfo=timezone.utc)
    _store, _clock = _patch_quota_store(monkeypatch, t0)
    bucket = "b" * 64

    ident1 = groq_gateway.admit(bucket, 6500)
    groq_gateway.settle(
        ident1,
        bucket,
        {"total_tokens": 6500},
        {"x-ratelimit-remaining-tokens": "7000", "x-ratelimit-reset-tokens": "0s"},
        200,
        0.05,
    )

    with pytest.raises(QuotaDeferred) as caught:
        groq_gateway.admit(bucket, 1000)
    assert caught.value.reason == "minute_quota"


def test_groq_post_reset_still_blocks_concurrent_inflight_reservations(monkeypatch: pytest.MonkeyPatch):
    t0 = datetime(2026, 11, 25, 1, 10, 0, tzinfo=timezone.utc)
    store, clock = _patch_quota_store(monkeypatch, t0)
    bucket = "c" * 64

    ident1 = groq_gateway.admit(bucket, 3500)
    groq_gateway.settle(
        ident1,
        bucket,
        {"total_tokens": 3500},
        {"x-ratelimit-remaining-tokens": "4500", "x-ratelimit-reset-tokens": "13s"},
        200,
        0.2,
    )

    clock[0] = t0 + timedelta(seconds=14)
    ident2 = groq_gateway.admit(bucket, 4800)
    assert store.requests[ident2].status == "reserved"

    with pytest.raises(QuotaDeferred) as caught:
        groq_gateway.admit(bucket, 4000)
    assert caught.value.reason == "minute_quota"


def test_quota_wait_message_and_deadline():
    stamp = datetime(2026, 11, 25, 1, 10, 0, tzinfo=timezone.utc)
    exc1 = QuotaDeferred("minute_quota", stamp + timedelta(seconds=14), sent=False)

    first = quota_wait({}, exc1, stamp)
    assert first["status"] == "waiting_context"
    assert first["wait_reason"] == "minute_quota"
    assert "rate limit" in first["summary"].lower()
    assert "gemini" in first["summary"].lower()
    assert first["auto_resume_until"] == (stamp + timedelta(seconds=120)).isoformat()

    exc2 = QuotaDeferred("minute_quota", stamp + timedelta(seconds=130), sent=False)
    second = quota_wait(first, exc2, stamp + timedelta(seconds=121))
    assert second["auto_resume_until"] == first["auto_resume_until"]
    assert second["status"] == "needs_input"
    assert "provider_retry_at" not in second


def test_groq_estimate_calibrated_for_low_reasoning_json_schema():
    router_payload = intent_router_model.payload(
        "maine 5 laptop kharide Sharma Traders se",
        {"recent_messages": [], "company_id": "c1"},
    )
    assert groq_gateway.estimate(router_payload) < 3000

    state = {
        "messages": ["maine 5 laptop kharide Sharma Traders se"],
        "outcome": "verified_entry",
        "company_id": "c1",
        "tool_groups": ["purchase"],
    }
    tools = task_agent_runtime.available_tools(
        state,
        task_agent_tools.registry(None, None, "c1", state),
    )
    schemas = [
        {"name": t.name, "description": t.description, "parameters": t.arguments.model_json_schema()}
        for t in tools
    ]
    agent_payload = task_agent_model.request_payload(state, schemas)
    agent_est = groq_gateway.estimate(agent_payload)
    assert agent_est < 4000
    assert groq_gateway.estimate(router_payload) + agent_est < 7000

    plain_payload = {
        "model": "openai/gpt-oss-20b",
        "messages": [{"role": "user", "content": "hi"}],
        "max_completion_tokens": 2048,
    }
    assert groq_gateway.estimate(plain_payload) >= 256 + 2048


def test_groq_429_parses_body_try_again_duration(monkeypatch: pytest.MonkeyPatch):
    t0 = datetime(2026, 11, 25, 1, 10, 0, tzinfo=timezone.utc)
    _patch_quota_store(monkeypatch, t0)

    def _raise_429(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://api.groq.com/openai/v1/chat/completions",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b'{"error":{"message":"Rate limit reached. Please try again in 14.25s."}}'),
        )

    monkeypatch.setattr(groq_gateway.urllib.request, "urlopen", _raise_429)

    with pytest.raises(QuotaDeferred) as caught:
        groq_gateway.request(
            "https://api.groq.com/openai/v1/chat/completions",
            {
                "model": "openai/gpt-oss-20b",
                "messages": [{"role": "user", "content": "hi"}],
                "max_completion_tokens": 100,
            },
            {"Authorization": "Bearer test-key"},
            5,
        )

    assert caught.value.reason == "minute_quota"
    delay_s = (caught.value.retry_at - t0).total_seconds()
    assert 14 <= delay_s <= 16


def test_groq_503_without_retry_after_waits_15s(monkeypatch: pytest.MonkeyPatch):
    t0 = datetime(2026, 11, 25, 1, 10, 0, tzinfo=timezone.utc)
    _patch_quota_store(monkeypatch, t0)

    def _raise_503(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://api.groq.com/openai/v1/chat/completions",
            503,
            "Service Unavailable",
            {},
            io.BytesIO(b"{}"),
        )

    monkeypatch.setattr(groq_gateway.urllib.request, "urlopen", _raise_503)

    with pytest.raises(QuotaDeferred) as caught:
        groq_gateway.request(
            "https://api.groq.com/openai/v1/chat/completions",
            {
                "model": "openai/gpt-oss-20b",
                "messages": [{"role": "user", "content": "hi"}],
                "max_completion_tokens": 100,
            },
            {"Authorization": "Bearer test-key"},
            5,
        )

    assert caught.value.reason == "provider_unavailable"
    delay_s = (caught.value.retry_at - t0).total_seconds()
    assert 14 <= delay_s <= 16


def test_intent_router_fails_over_from_groq_quota_to_gemini(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PHILIXA_CROSS_PROVIDER_FAILOVER", "1")
    settings = SimpleNamespace(
        ai_api_key="groq-test-key",
        groq_api_key="",
        ai_economy_model="openai/gpt-oss-20b",
        gemini_api_key="gemini-test-key",
    )
    monkeypatch.setattr(intent_router_model, "ready", lambda: True)
    monkeypatch.setattr(intent_router_model, "get_settings", lambda: settings)
    monkeypatch.setattr(groq_gateway, "enabled", lambda: True)
    monkeypatch.setattr(
        intent_router_model,
        "GroqProvider",
        lambda _s: SimpleNamespace(base_url="https://api.groq.com/openai/v1/chat/completions"),
    )

    async def _active_groq():
        return "groq"

    monkeypatch.setattr(ai_engine_manager, "get_active_engine", _active_groq)

    def _raise_quota(*args, **kwargs):
        raise QuotaDeferred("minute_quota", datetime.now(timezone.utc) + timedelta(seconds=20))

    monkeypatch.setattr(intent_router_model, "_post_json", _raise_quota)

    async def _fake_gemini(system_prompt, user_content, schema=None, timeout_seconds=12):
        return (
            json.dumps({"intent": "purchase", "context_relation": "standalone"}),
            {"provider": "gemini", "model": "gemini-2.5-flash-lite", "attempts": 1},
        )

    monkeypatch.setattr(ai_engine_manager, "call_gemini_json", _fake_gemini)

    decision, usage = asyncio.run(
        intent_router_model.classify(
            "maine 5 laptop kharide Sharma Traders se",
            {"recent_messages": [], "company_id": "c1"},
            "r" * 32,
        )
    )

    assert decision.intent == "purchase"
    assert decision.handler == "agent"
    assert usage["provider"] == "gemini"
    assert usage["failover_from"] == "groq"


def test_task_agent_choose_fails_over_from_groq_quota_to_gemini(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PHILIXA_CROSS_PROVIDER_FAILOVER", "1")
    settings = SimpleNamespace(
        ai_api_key="groq-test-key",
        groq_api_key="",
        ai_model="openai/gpt-oss-20b",
        ai_base_url="https://api.groq.com/openai/v1/chat/completions",
        ai_economy_model="groq/openai/gpt-oss-20b",
        gemini_api_key="gemini-test-key",
    )
    monkeypatch.setattr(task_agent_model, "get_settings", lambda: settings)

    def _raise_quota(*args, **kwargs):
        raise QuotaDeferred("minute_quota", datetime.now(timezone.utc) + timedelta(seconds=20))

    monkeypatch.setattr(task_agent_model, "_post_json", _raise_quota)

    async def _fake_gemini(system_prompt, user_content, schema=None, timeout_seconds=12):
        return (
            json.dumps(
                {
                    "kind": "needs_input",
                    "tool": None,
                    "arguments_json": "",
                    "summary": "Ask per unit rate",
                    "user_response": "Ek laptop ka rate kitna hai?",
                }
            ),
            {"provider": "gemini", "model": "gemini-2.5-flash-lite", "attempts": 1},
        )

    monkeypatch.setattr(ai_engine_manager, "call_gemini_json", _fake_gemini)

    decision, usage = asyncio.run(
        task_agent_model.choose(
            {
                "messages": ["maine 5 laptop kharide Sharma Traders se"],
                "provider": "groq",
                "executions": [],
                "observations": [],
            },
            [],
        )
    )

    assert decision.kind == "needs_input"
    assert decision.user_response == "Ek laptop ka rate kitna hai?"
    assert usage["provider"] == "gemini"
    assert usage["failover_from"] == "groq"


def test_create_purchase_draft_formats_missing_stock_blocker_without_extra_llm():
    class _DraftArgs(BaseModel):
        message_index: int
        updates: list[dict]

    async def _noop_auth(_args):
        return None

    async def _noop_persist(_state):
        return None

    async def _forbid(*_args, **_kwargs):
        raise AssertionError("No extra LLM or budget call expected")

    async def _exec(_args):
        return task_agent_runtime.ToolResult(
            status="needs_input",
            data={
                "draft_id": "d" * 32,
                "issues": [{"kind": "identity", "field": "0:item_name", "message": "Item missing"}],
                "proposal": {
                    "revision": 1,
                    "content": {
                        "party_name": "Sharma Traders",
                        "lines": [{"item_name": "Laptop", "quantity": 5, "unit": "Nos"}],
                    },
                },
            },
        )

    seed = {
        "kind": "tool",
        "tool": "create_purchase_draft",
        "arguments": {
            "message_index": 0,
            "updates": [
                {"path": "party_name", "value": "Sharma Traders", "quote": "Sharma Traders"},
                {"path": "lines.0.item_name", "value": "Laptop", "quote": "laptop"},
                {"path": "lines.0.quantity", "value": "5", "quote": "5"},
            ],
        },
        "summary": "Create purchase draft",
    }
    tool = task_agent_runtime.Tool(
        "create_purchase_draft",
        "Create draft",
        _DraftArgs,
        "draft",
        _noop_auth,
        _exec,
    )
    result = asyncio.run(
        task_agent_runtime.run(
            {
                "messages": ["maine 5 laptop kharide Sharma Traders se"],
                "executions": [],
                "observations": [],
                "routing_first_step": seed,
            },
            [tool],
            _forbid,
            _noop_persist,
            _forbid,
        )
    )

    assert result["model_rounds"] == 0
    assert result["status"] == "needs_input"
    assert "Laptop" in result["summary"]
    assert "purchase details check kar li hain" in result["summary"]
    assert "ka bill check kar liya hai" not in result["summary"]
    assert "stock items" in result["summary"]


def test_is_create_masters_intent_matches_hinglish_add_phrases():
    for phrase in ("haan add kar do", "add krdo", "stock add krdo", "item bana do"):
        assert intent_router.is_create_masters_intent(phrase) is True
    assert intent_router.is_create_masters_intent("add mat karo") is False


def test_inline_fast_path_skips_arq_enqueue_when_completed_inline(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PHILIXA_TASK_AGENT_INLINE_FAST_PATH", "1")
    fake_task = SimpleNamespace(revision=0, status="queued", state={"messages": ["5 laptop"]})

    class _FakeDB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, _model, _ident):
            return fake_task

    fake_pool = SimpleNamespace(
        enqueue_job=AsyncMock(),
        aclose=AsyncMock(),
    )

    async def _fake_create_pool(_settings):
        return fake_pool

    async def _fake_execute(_ctx, _ident, _rev=None):
        fake_task.status = "needs_input"

    exec_mock = AsyncMock(side_effect=_fake_execute)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(arq.connections, "create_pool", _fake_create_pool)
    monkeypatch.setattr(task_agent_jobs, "execute_agent_task", exec_mock)

    asyncio.run(task_agent_service.enqueue("t" * 32))

    exec_mock.assert_awaited_once()
    fake_pool.enqueue_job.assert_not_awaited()
    fake_pool.aclose.assert_awaited_once()



