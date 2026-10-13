# Project: Philixa Vapi.ai Voice Integration

## Architecture
- **Isolation Principle**: Complete side-by-side coexistence. Legacy routes (`routes_live.py`, `routes_voice.py`, `routes_audio.py`) are strictly untouched and operational.
- **Namespace**: All new Vapi endpoints reside under `/api/v1/vapi` isolated namespace in `app/api/v1/routes_vapi.py`.
- **Router Registration**: Exported from `app/api/v1/__init__.py` and included in `app/main.py` via `app.include_router(vapi_router, prefix="/api/v1")` and `app.include_router(vapi_router)`.
- **Configuration**: `Settings` dataclass in `app/core/config.py` extended with `voice_gateway_provider: str = "dual"`, `vapi_api_key: str = ""`, `vapi_webhook_secret: str = ""`, `vapi_custom_llm_secret: str = ""`, and `vapi_custom_llm_url: str = "http://localhost:8000/api/v1/vapi/chat/completions"`. Loaded via `os.getenv` in `get_settings()`.
- **Security**: `/api/v1/vapi/chat/completions`, `/api/v1/vapi/webhook`, and `/api/v1/vapi/assistants/inbound` exempted in `CSRF_EXEMPT_PATHS` in `app/core/csrf.py`. Secret verification via `secrets.compare_digest` with UTF-8 byte encoding and dev-friendly bypass when secrets are unset.
- **Custom LLM Gateway**: SSE stream (`text/event-stream; charset=utf-8`) OpenAI-compatible chat completions endpoint (`POST /api/v1/vapi/chat/completions`). Sets `X-Accel-Buffering: no`, checks `request.is_disconnected()`, leverages `litellm.acompletion(stream=True)`, and cleanly suppresses trailing chunks upon disconnect.
- **Webhook Gateway**: `POST /api/v1/vapi/webhook` handles `assistant-request`, `tool-calls` / `function-call`, `end-of-call-report`, `status-update`, `speech-update`.
- **Database & Domain Models**: Queries `Client.whatsapp_phone` for phone lookups with 10-digit suffix fallback. Multi-tenant isolation strictly enforced with `Client.organization_id == org_id`. Safe first-name splitting and defensive JSON argument parsing via `safe_parse_json_dict()`. Uses `ConfigDict(extra="allow")` on all Pydantic request models.

## Feature Inventory
| # | Feature | Description | Milestone | Source | Status |
|---|---------|-------------|-----------|--------|--------|
| 1 | Configuration & Feature Flag | Add `voice_gateway_provider`, `vapi_api_key`, `vapi_webhook_secret`, `vapi_custom_llm_secret`, `vapi_custom_llm_url` to `Settings` in `app/core/config.py` | M1 | vapi_integration_guide §2.1 | DONE |
| 2 | CSRF Security Exemption | Exempt `/api/v1/vapi/chat/completions`, `/api/v1/vapi/webhook`, `/api/v1/vapi/assistants/inbound` in `CSRF_EXEMPT_PATHS` | M1 | vapi_integration_guide §2.1 | DONE |
| 3 | Router Registration & Isolation | Create `app/api/v1/routes_vapi.py`, re-export in `app/api/v1/__init__.py`, mount in `app/main.py` under `/api/v1/vapi` | M1 | ORIGINAL_REQUEST R2 | DONE |
| 4 | Vapi Pydantic Schemas | Define flexible Pydantic v2 schemas (`ConfigDict(extra="allow")`) for Vapi Webhook and Chat Completion payloads | M1 | vapi_integration_guide §2.3 | DONE |
| 5 | Custom LLM SSE Gateway | Implement `POST /api/v1/vapi/chat/completions` streaming OpenAI-compatible chunks with `litellm.acompletion` and disconnect watchdog | M1 | vapi_integration_guide §2.2 | DONE |
| 6 | Vapi Webhook Receiver | Implement `POST /api/v1/vapi/webhook` handling assistant-request, tool-calls, end-of-call-report, status-update | M1 | vapi_integration_guide §2.3 | DONE |
| 7 | Inbound Assistant Config | Implement `POST /api/v1/vapi/assistants/inbound` returning dynamic assistant config with auth protection | M1 | vapi_integration_guide §2.1 | DONE |
| 8 | Zero Collision Verification | Verify `routes_live.py`, `routes_voice.py`, `routes_audio.py` remain 100% functionally and textually untouched | M1 | ORIGINAL_REQUEST R2 | DONE |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Complete Vapi Integration | Features 1-8: config, CSRF, routes_vapi.py, router mounting, verification | None | DONE |

## Interface Contracts
### Vapi Webhook ↔ Philixa Backend
- `POST /api/v1/vapi/webhook`
- Headers: `x-vapi-secret` (verified via `secrets.compare_digest`)
- Response for `assistant-request`: `{ "assistant": { ... } }` or `{}`
- Response for `tool-calls`: `{ "results": [ { "name": ..., "toolCallId": ..., "result": ... } ] }`
- Response for other events: `{ "status": "ok" }`

### Custom LLM ↔ Vapi Audio Engine
- `POST /api/v1/vapi/chat/completions`
- Headers: `Authorization: Bearer <token>`
- Media Type: `text/event-stream; charset=utf-8`
- Stream chunks: `data: {"id":..., "object":"chat.completion.chunk", "choices":[{"delta":{"content":...},"finish_reason":...}]}` followed by `data: [DONE]`

### Dynamic Inbound Assistant ↔ Vapi Telephony
- `POST /api/v1/vapi/assistants/inbound`
- Headers: `x-vapi-secret`
- Response: `{ "name": ..., "firstMessage": ..., "model": { "url": ... }, "voice": ... }`

## Code Layout
- `app/core/config.py`: Settings dataclass and get_settings() factory.
- `app/core/csrf.py`: CSRF_EXEMPT_PATHS set and middleware.
- `app/api/v1/routes_vapi.py`: Isolated Vapi API router, models, SSE generator, and webhook handlers.
- `app/api/v1/__init__.py`: API v1 router re-exports.
- `app/main.py`: FastAPI app initialization and route inclusion.
- `app/api/v1/routes_live.py`, `routes_voice.py`, `routes_audio.py`: UNTOUCHED legacy files.
