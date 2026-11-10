# Philixa intent routing — implementation and acceptance status

Date: 5 November 2026. Candidate: intent-router-v2.

**Implementation present; release gate NOT passed. Normal routing flag restored OFF. Review-only remains ON.**

## Delivered

- One authenticated server routing entry point behind `PHILIXA_INTENT_ROUTER_ENABLED` (default OFF).
- Pydantic intent contracts, bounded deterministic help/stock/selections/numeric answers, and one semantic classification attempt through the existing Groq gateway.
- The model proposes meaning/explicit fields; server code maps handler and task identity. No arbitrary model SQL/XML or write authority.
- Scoped PostgreSQL route journal, request hash/deduplication, conversation focus, revision checks and recovery by stable task request identity.
- Permission/session/native-company recheck after classification and existing domain checks at dispatch.
- Grounded first-step draft proposal reused by the existing agent, without an extra call just to plan that step again.
- Free text uses the central endpoint when enabled; typed legacy controls and rollback path preserved.
- Worker heartbeat annotation prevents a dead document worker being presented as active thinking. Native outbox actions use their separate status.
- Tokenizer/quota-pool warmup before background embedding preload; no model call during initialization.
- Additive routing migration `f8y5z6a7b8c9` applied. Dev auto-created table adoption checks columns and uniqueness.

## Automated verification

- Routing/runtime/service/selection/quota/worker/help suite: **80 tests passed**. No native/provider calls in these mocked suites.
- GST, purchase-memory duplicate, receipt-link, recovery and native-read regression group: **41 tests passed**.
- JavaScript chat restore/scope, unified free-text entry, task references, status-only polling and worker-offline rendering: passed.
- Targeted diff whitespace check: passed; only repository CRLF conversion notices remain.
- Earlier legacy-flow test failed while the temporary new-router flag was ON. That test now explicitly selects legacy mode; separate tests cover the new router.

## Observed browser acceptance

- Existing logged-in in-app browser used; a fresh temporary tab recovered after the original tab cached a restart error.
- Help `tu maire liye kiya kr sakta hai`: correct capability response, no task/Resume card. Backend **190 ms**, **zero Groq requests**; this is backend timing, not browser p95.
- `stock kitna hai`: direct permitted stock read, zero Groq requests. Backend **8,292 ms** because the native read failed/timed out and returned saved data.
- Saved result: Cement 30 bags, Goods18 141 bags, Goods5 23 bags, with last-sync timestamp and Read failed disclosure. This does not prove a fresh live Tally read.
- Browser reload visibly restored the same help/stock conversation; no command was replayed.
- Screenshot observed in tool output. No native posting, approval, voucher deletion or installer action performed.
- Full semantic purchase → corrections → final review browser acceptance is still pending.

## Synthetic model evaluation

Frozen v1 had 160 development and 80 held-out synthetic turns. V1 cold-start and output-validation failures remain preserved in `data/intent-routing-live.json`.

V2 removes redundant model-controlled handler/task plumbing. Eight consumed v1 turns became regression-only; 72 unrun turns plus eight new turns formed its frozen 80-turn held-out set. Development templates/prefix variants are correlated synthetic cases, not independent accountant samples.

- V2 tested **44/80** held-out turns; **39 valid routes**, **5 rejected evidence/output cases**.
- These are strict routing-pipeline results. A rejected extraction is counted failed, never a successful accounting operation.
- Model-call latency among recorded successful responses: p50 **1094 ms**, p95 **2806 ms**. Excludes setup/admission waits and failed calls.
- Observed successful-row usage: prompt **40101**, completion **3045**, cached prompt **2048** tokens. Failed/uncertain usage remains conservatively reserved in provider ledgers; these sums are not a billing total.
- Testing stopped at existing local daily call cap. No cap increase, model replacement or paid fallback.
- Remaining **36** held-out turns untested. Already five failures mean this candidate cannot reach the proposed 76/80 pass threshold even if every remaining turn passes.
- No real-world accuracy, real accountant time saving, actual currency cost or unlimited-free-use claim.

Rejected cases:

- `held-correction-0-v2` — correction: RoutingOutputError
- `held-purchase-1` — purchase: RoutingOutputError
- `held-topic_switch-1` — topic_switch: route mismatch
- `held-supplier_reply-3` — supplier_reply: RoutingOutputError
- `held-topic_switch-3` — topic_switch: RoutingOutputError

## Remaining work before enabling

1. Diagnose rejected field/source evidence on development/regression cases; keep final accounting evidence checks strict. Do not tune and re-label this consumed held-out set as untouched.
2. Prepare fresh held-out routing acceptance for the next material candidate and run within the unchanged shared/free-tier budgets.
3. Complete the semantic purchase/correction/topic-switch browser flow, reload/restart and outage acceptance.
4. Resolve the independently failing live Tally stock read; saved fallback is working but is not live-read success.
5. Only after the routing/security/browser gates pass, enable the controlled review pilot. Existing real-company write gates remain unchanged.

## Reproduction

- Migration: `docker compose exec -T app alembic upgrade head`.
- Backend tests: `docker compose exec -T app python -m unittest scripts.test_intent_router scripts.test_intent_router_model scripts.test_business_router scripts.test_task_queue_health scripts.test_task_agent_runtime scripts.test_task_agent_service scripts.test_task_agent_worker scripts.test_task_agent_selection scripts.test_groq_quota scripts.test_task_resume_presentation scripts.test_business_help`.
- UI: `node scripts/test_business_chat_refresh.cjs`.
- Frozen data/evaluator: `scripts/fixtures/intent_routing/`, `scripts/evaluate_intent_routing.py` and bounded `scripts/run_routing_evaluation.py`. Evaluation never executes domain tools.
- Local-only reversible pilot: `python scripts/intent_router_pilot_config.py enable`; recreate app/worker; `restore` afterwards. Do not treat this utility as release approval.
- Source hashes, usage and measured latencies: `data/intent-router-release-evidence.json`.
