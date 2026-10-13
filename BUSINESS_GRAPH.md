# Business chat: LangGraph and existing evidence retrieval

Implemented in the duplicate development project on 2026-10-08. Original folder remains untouched.

## Runtime flow

Typed chat and transcribed microphone input both call the unchanged `/api/v1/business/command` endpoint. Authentication supplies the principal and database session. The business graph runs one planner, then routes to customer, task, reminder, Tally, history or conversation nodes. Nodes call the extracted `business_command_service.py` and existing repositories/services. Structured frontend choices reuse validated command fields without another model interpretation.

`portfolio_copilot_service.py` provides shared graph construction for legacy and business entry points. Business graph nodes never enter the legacy generated-SQL branch. Principal and DB session live in per-invocation runtime configuration, outside serializable request state. The graph has no checkpointer and does not retry side effects automatically.

Purchase/sale and reminder commands return existing persisted previews. `/business/confirm` invokes the approval node with the stored token; no planner runs. Existing Redis/PG scope, contact version, role, expiry, concurrent confirmation, uncertain execution and replay protections remain authoritative. Tally setup/reconcile URLs remain unchanged.

Customer/portfolio history calls reusable `AskClientService.retrieve` and evidence synthesis. The first search retrieves at most five chunks. An insufficient answer permits one refined search, preserving principal, customer and parsed dates. Empty evidence returns a clear missing-history response. Unsupported answers and unknown source IDs are rejected. Both evidence and parent meeting must match the workspace; members must own both records. Retrieved instructions cannot invoke tools or authorize a send. Answers include meeting dates and additive `source_meetings` metadata, rendered safely as text in chat.

Existing embedding model, 1024-dimensional pgvector data, ingestion job and chunking remain unchanged. No existing records were re-embedded. Stock quantities come from live Tally, not retrieval. Voice responses retain existing TTS; text remains visible if speech fails.

Multi-company stock adds `stock_scope` before the existing `tally_tool`. The state
contains approved company IDs, while database sessions remain runtime-only. Scope
and revocations are checked again before results are returned. No selected company
is required on normal stock queries. See `TALLY_PILOT.md` for pairing, transport and
real-acceptance boundaries.

## Verification

Use the isolated development container with `docker compose -p accounts-dev exec -T app python -m <module>`:

- `scripts.test_business_graph`: graph node routing, one planner/tool invocation, approval bypass, bounded retrieval, source validation, legacy greeting/topology, concurrent sends, cancellation, session mismatch and uncertain-send replay. All 11 tests passed, including ambiguous customer selection preserving the full question.
- `scripts.test_history_scope`: real PostgreSQL/pgvector owner/member, evidence AND parent isolation, customer/date filters and legacy user scope. Fixtures roll back.
- `scripts.test_business_scope`: real DB/Redis tenant scope, ambiguous names, stale contacts and mocked confirmed delivery passed.
- `scripts.test_tally`: XML/scope checks and real PG approval regression with synthetic Tally passed, including concurrent confirmations, expiry and uncertain import.
- `scripts.test_business_voice`: five voice/provider/TTS safety checks passed.
- `scripts.verify_business_tools` and `scripts.verify_tally_interpretation`: authenticated graph APIs, customer/task/reminder previews, Hindi/Hinglish and Tally interpretation passed; drafts cancelled.
- `scripts.verify_business_history`: real cached BGE-M3 embeddings and configured AI provider, synthetic Hinglish customer/date query, accurate source/date, empty date range and legacy AskClient contract passed. Fixtures roll back. Run with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` to require the existing cache. No notification worker starts.
- Live graph stock read returned `Philixa Test: Cement ... 0 bags` with read timestamp. Frontend history query displayed the empty-evidence response successfully. Python compile and chat JavaScript syntax checks passed.

The legacy `tests/test_meeting_notes.py` suite returned 6 passes and 8 failures. Running the identical suite against a temporary read-only copy of the untouched original application produced the same eight failures (stale extraction expectations and rate limiting). These remain pre-existing test debt; full legacy suite health is not claimed. Container-only test dependencies installed: pytest-asyncio, aiosqlite and fakeredis.

## Performance and acceptance limits

`scripts.benchmark_business_graph` compares extracted direct execution with graph dispatch on identical read-only stock/customer queries, using five samples each. Stock medians were 185.15 ms direct / 185.12 ms graph; customer read medians were 2.64 ms / 5.79 ms. Simple structured reads make zero model calls. A separate 30-sample mocked dispatch comparison measured median direct 0.029 ms versus graph 2.228 ms, with one planner and one tool call per request. These measurements describe local dispatch overhead, not a guaranteed production speed improvement. Real synthetic history answered in about 4.1 seconds, excluding a 5.8-second cold embedding model load.

Live purchase/sale acceptance is still pending in the test company: Educational Mode date restrictions must be resolved before claiming writes. Real Email/WhatsApp delivery acceptance requires a designated recipient and explicit send approval. Automatic reminder scheduling, server conversation persistence/checkpoint migration, other connectors, expanded accounting scope and full legacy endpoint migration remain outside this milestone.
