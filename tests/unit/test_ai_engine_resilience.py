import asyncio
from types import SimpleNamespace

import pytest

from app.services import ai_engine_manager
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
