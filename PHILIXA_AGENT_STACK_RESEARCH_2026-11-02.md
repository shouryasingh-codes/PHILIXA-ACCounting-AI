# Philixa agent stack decision — 2 November 2026 (IST)

## Decision

For this existing, budget-constrained Tally product, retain Python/FastAPI/Pydantic/PostgreSQL and LangGraph. Build one bounded, tool-selecting task agent over reusable accounting capabilities. Retain the authorised action/outbox/reconciliation layer as the only route to Tally writes. Do not restart the project, train a foundation model, or add multiple orchestration frameworks.

This is an engineering recommendation based on official documentation and inspected source, not a benchmark proving which model is best at Indian accounting. Research made no paid inference requests, changed no runtime flags and posted no vouchers.

## What the present source actually contains

- `requirements.txt`: FastAPI, Pydantic, SQLAlchemy, PostgreSQL driver, ARQ/Redis, LiteLLM, LangGraph, MinIO and pgvector dependencies. Some agent dependencies have broad lower bounds rather than reproducible locks.
- `app/core/config.py`: default model `groq/openai/gpt-oss-20b`; environment overrides and account access were not inspected. This is a source default, not proof of the currently running model.
- `app/services/purchase_agent.py`: explicit graph edges `masters -> history -> validate -> proposal -> END`. This is a stateful workflow, not an open-ended model-selected tool loop. Its useful guards should be preserved.
- `app/services/purchase_checkpoint.py`: custom JSON-only PostgreSQL-backed LangGraph saver. It is not the standard `AsyncPostgresSaver` simply because it uses PostgreSQL.
- `requirements-local-ocr.txt` and `local_invoice_ocr.py`: RapidOCR/ONNX/OpenCV plus geometry/header/layout rules. Reading words and interpreting arbitrary invoice tables are separate jobs. Handcrafted layout branches explain why new layouts can require more code; this inspection is not a fresh accuracy test.

The largest architectural gap is connecting existing capabilities to one task execution contract. Another framework name alone will not close it.

## Recommended components and tradeoffs

### Agent runtime: LangGraph, one primary agent

Use a bounded loop: understand task, inspect scoped context, choose a typed tool, observe its result, update plan, then finish or ask for genuinely missing facts. Persist task ID, draft/action IDs, revisions, evidence references and unresolved issues. Keep calculation and posting subflows deterministic.

Benefits: fits current implementation; supports persistent state and human interrupts; model/provider choice remains independent. Cost: replay, concurrent edits and external effects still require deliberate engineering. Checkpoints do not themselves make a Tally write exactly-once. On resume, recheck current permissions, master evidence and approved revision. [LangGraph workflow/agent distinction](https://docs.langchain.com/oss/python/langgraph/workflows-agents), [persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts).

Keep the custom saver initially. Evaluate the supported Postgres saver against existing tenant isolation, JSON-only serialization and migrations before replacing it. Lock tested dependency versions and rerun compatibility/security checks.

### Models: measure 20B against 120B before switching

Keep GPT-OSS 20B as the cheap baseline for explicit field extraction and simple intent. Evaluate GPT-OSS 120B as the first candidate for task planning, multiple corrections and recovery decisions. Both are text models with tool/schema capabilities; neither directly reads invoice photos. As checked today, Groq lists per-million-token prices of $0.075/$0.30 input/output for 20B and $0.15/$0.60 for 120B. Account quotas and availability still vary. [Groq production model list](https://console.groq.com/docs/models), [20B](https://console.groq.com/docs/model/openai/gpt-oss-20b), [120B](https://console.groq.com/docs/model/openai/gpt-oss-120b).

At an illustrative aggregate 10,000 input + 2,000 billed output tokens, model-token charges are $0.00135 vs $0.00270. This excludes retries, extra rounds, OCR, infrastructure and other charges; it is not cost per completed task. Measure aggregate usage rather than assuming a short user message is cheap.

Stronger hosted comparison candidates include GPT-6 Astra, Claude Sonnet/Opus 5.5 and Gemini 3.8 Flash. Official pages establish capabilities/availability, not Philixa task accuracy. GPT-6 Astra's listed $10/$50 per-million text-token standard rates make it an expensive default for this budget; use only in a separately funded comparison. Gemini 3.8 Flash is a current stable multimodal candidate, useful for the document-reading comparison. No provider/model change is authorised by this report. [OpenAI model](https://developers.openai.com/api/docs/models/gpt-6-astra), [Claude lineup](https://platform.claude.com/docs/en/models/overview), [Gemini lineup](https://ai.google.dev/gemini-api/docs/models).

Use strict typed output where supported, but validate facts against evidence. JSON conformity does not prove that a supplier, amount or tax is true. [Groq structured output](https://console.groq.com/docs/structured-outputs).

### Typed tools and accounting engine

Pydantic contracts should expose business operations, not arbitrary SQL, XML or shell access. Each capability declares input/output schemas, permissions, required evidence, freshness, supported cases, side-effect class and recovery behaviour. Good tool families: resolve identity, inspect purchases, read balances/stock, match invoices/payments, draft transaction, validate draft, request authorised action, check native result.

Model chooses useful reads and proposes actions. Server resolves exact company/native IDs, computes Decimal amounts, checks dates/taxes/duplicates and enforces authority. A failed or ambiguous posting becomes an explicit unknown/reconciliation state. Never equate HTTP success with verified voucher creation. Existing action-specific identity, durable outbox and local SQLite journal should stay.

This shared contract supports purchase, sales, receipt/payment, inventory and reconciliation capabilities without building a separate chat application for each. Each accounting operation still needs a correct native adapter and tests; no general agent eliminates that work.

### Tally integration: native XML first, version-gated JSON where useful

Retain the paired outbound Windows connector and tested XML adapter. Prefer native structured reads/writes over screen clicking. TallyPrime 7.0 supports native JSON as well; discover the installed version/capabilities before selecting it. JSON can simplify serialization but cannot solve identity, accounting correctness or recovery. Older Tally versions must remain supported through the existing adapter. [Tally XML](https://help.tallysolutions.com/xml-integration/), [native JSON/version requirements](https://help.tallysolutions.com/tally-prime-integration-using-json-1/).

MCP is an optional standardized tool interface, not the brain, a permission system, or proof that an arbitrary third-party Tally server is safe. Keep the server-owned authorisation layer even when tools are exposed through MCP. Scope credentials and tools to user/company/device. [MCP security guidance](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices).

Tally being closed means live native reads/writes are unavailable. Philixa may process documents and retain clearly dated cached data, then resume after reconnecting. Hosting the assistant 24/7 cannot make a closed desktop application live.

### Documents: a tiered reader, not one regex parser for every bill

1. Digital PDFs: preserve native text, page positions and table evidence with existing PyMuPDF.
2. CPU baseline: retain RapidOCR/ONNX for text boxes and targeted rereads. Its ONNX deployment is useful for low-cost local processing, but text recognition alone is not a complete invoice understanding engine. [RapidOCR](https://rapidai.github.io/RapidOCRDocs/latest/).
3. Evaluate a layout/table model such as PP-StructureV3 and the current PaddleOCR-VL-1.6 on isolated representative fixtures. Official Paddle releases now include 1.6 and newer parsing work; recommending only the older 1.5 as today's latest would be inaccurate. GPU/RAM, latency and packaging must be measured on actual available hardware. Vendor document benchmarks are not invoice-level Indian GST accuracy. [PaddleOCR releases](https://github.com/PaddlePaddle/PaddleOCR).
4. If funded and approved, compare Gemini 3.8 Flash document vision for difficult layouts; keep page/crop evidence and strict independent total checks. Network/quota/privacy/cost remain tradeoffs. No silent unlimited cloud fallback. [Document understanding](https://ai.google.dev/gemini-api/docs/document-processing), [model](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash).

Deploy readers as replaceable workers, not inside the Windows Tally helper. Budget-zero mode remains local with honest review/unsupported outcomes. Self-hosting large vision models has hardware costs even when model weights are free. Do not train a new model until labelled failures show that training solves a specific recurring defect.

### Memory, jobs, UI and evaluation

- PostgreSQL: authoritative tasks, accounting drafts/actions, approved mappings and scoped SQL read models. Retrieve relevant records by exact identities/time range. Retain pgvector only for genuinely semantic document/help retrieval; embeddings must not decide supplier identity, totals or duplicates.
- ARQ/Redis: preserve current background execution. PostgreSQL owns durable task/action state. Independent safe reads may run concurrently; posting serialisation follows company/action constraints. One bounded retry for transient reads, no blind write retries.
- MinIO: retain private originals and evidence crops, with authorised access and content identity.
- UI: keep current frontend. Show task progress, compact proposal, exceptions and final result; open details only for correction. Replacing HTML with React would not create intelligence.
- Observability: begin with structured task/tool traces, token/latency/cost counters and existing regression fixtures. Add Langfuse only if its evaluation/tracing UI saves more effort than its deployment adds. Human-labelled references and deterministic accounting graders remain necessary; another LLM's agreement is not ground truth. [Langfuse evaluations](https://langfuse.com/docs/evaluation/overview).

## Alternatives considered

**PydanticAI:** credible typed-agent alternative, with durable runtime integrations. Strong candidate for a greenfield Python agent. Here it duplicates orchestration already present; adopt only if an isolated comparison shows less complexity or better outcomes. Pydantic validation itself stays regardless. [Overview](https://pydantic.dev/docs/ai/overview/), [durability](https://pydantic.dev/docs/ai/capabilities/durable_execution/overview/).

**Temporal:** useful when long-running cross-service execution and operational recovery outgrow current jobs. It adds a service, worker/versioning and replay constraints. Its activities also need idempotence; it cannot by itself prevent a duplicate Tally voucher after an uncertain response. Do not layer it beside ARQ without assigning one execution owner. [Temporal activities](https://docs.temporal.io/activities).

**CrewAI:** supports event-driven flows and persistence, but a multi-role crew is not required for this task. Another manager/delegation loop would add behaviour to measure and debug. Start with one agent and reusable tools; parallel workers can process independent bills without pretending each worker is an autonomous accountant. [CrewAI Flows](https://docs.crewai.com/en/concepts/flows).

**OpenAI hosted agent stack / provider SDKs:** capable alternatives for managed orchestration and tool execution. They do not remove the local Tally bridge or authoritative posting checks. Existing provider-independent LangGraph plus the required Windows bridge is the lower-disruption choice here. [Official OpenAI agent guide](https://developers.openai.com/tracks/building-agents).

## Implementation order proposed, not performed

1. Stabilise connector install/reconnect and exact paired native identity; finish current candidate acceptance independently of agent changes.
2. Introduce a common task/capability registry over existing services. Preserve current purchase guards and recovery. Let the model choose bounded reads and group missing facts instead of hardcoding one-question-per-field chat.
3. Run the same tools/context/prompt on 20B and 120B. Include explicit rate, no-bill receipt, conflicting supplier, multi-item correction, topic change, stale evidence, offline Tally, duplicate and malicious document content. Compare completion and review effort, not answer style.
4. Connect existing purchase/bill capabilities to that task system. Add sales, receipts/payments, inventory and bank reconciliation as separately tested adapters on the same foundation. The product target remains broad Tally work automation; these are capability rollout boundaries, not a narrowed product goal.
5. Upgrade the document reader only after a controlled benchmark. Never bundle model changes, connector protocol changes and OCR replacement into one untraceable release.

## Acceptance before claiming an intelligent accountant assistant

Measure exact identity/date/reference/line/tax/total correctness, native verification, duplicate creation, tool-selection quality, unnecessary questions, manual corrections, active review time, latency and total cost. Include restart, repeated request, changed permission and ambiguous-result recovery. Compare against the same manually completed workload.

Retain the previously agreed real-automation evidence gate: at least 200 representative accountant-labelled invoices including a separate 100-invoice held-out set, zero critical errors in the eligible auto-post subset, and policy-specific evidence. These are rollout criteria, not results from this research. Broader task types need their own representative cases too. Real-world accuracy and time savings remain unverified until measured.

**Final choice:** existing Python stack + LangGraph task agent + typed business tools + company-scoped SQL memory + deterministic accounting/action engine + tiered document reader. Keep 20B baseline; evaluate 120B first for better planning. A larger model can improve decisions; reliable tools and verified outcomes are what turn those decisions into useful accounting work.
