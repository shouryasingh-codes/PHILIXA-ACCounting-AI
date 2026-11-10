"""Render honest release evidence from the preserved synthetic evaluation."""
import hashlib,json,math,statistics
from pathlib import Path

root=Path(__file__).resolve().parents[1]
report=json.loads((root/'data'/'intent-router-v2-live.json').read_text(encoding='utf-8'))
rows=report['rows'];valid=[r for r in rows if r.get('correct_route')]
latencies=sorted(r['latency_ms'] for r in rows if r.get('path')=='model' and r.get('latency_ms') is not None)
usage=[r.get('usage',{}) for r in rows]
failures=[r for r in rows if not r.get('correct_route')]
sources=['app/services/business_router.py','app/services/intent_router.py','app/services/intent_router_model.py',
    'app/services/task_queue_health.py','app/web/business-chat.js','alembic/versions/f8y5z6a7b8c9_business_routes.py']
manifest={'version':report['version'],'routing_default_enabled':False,'review_only':True,
    'evaluation_fingerprint':report['fingerprint'],'evaluation_cases':len(rows),'valid_routes':len(valid),
    'heldout_remaining':80-len(rows),'release_gate_passed':False,
    'source_sha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in sources},
    'model_latency_ms':{'p50':statistics.median(latencies) if latencies else None,
        'p95':latencies[max(0,math.ceil(len(latencies)*.95)-1)] if latencies else None},
    'observed_prompt_tokens':sum(u.get('prompt_tokens',0) for u in usage),
    'observed_completion_tokens':sum(u.get('completion_tokens',0) for u in usage),
    'cached_prompt_tokens':sum((u.get('prompt_tokens_details') or {}).get('cached_tokens',0) for u in usage),
    'actual_provider_cost_measured':False,'time_savings_verified':False,
    'native_writes_performed':False,'failures':[{'id':r['id'],'category':r['category'],'failure':r.get('failure')} for r in failures]}
manifest['automated_checks']={'routing_runtime_suite_passed':80,'accounting_regression_group_passed':41,'javascript_chat_suite_passed':True,'targeted_whitespace_check_passed':True}
(root/'data'/'intent-router-release-evidence.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
lines=['# Philixa intent routing — implementation and acceptance status',
    '', 'Date: 5 November 2026. Candidate: intent-router-v2.',
    '', '**Implementation present; release gate NOT passed. Normal routing flag restored OFF. Review-only remains ON.**',
    '', '## Delivered',
    '', '- One authenticated server routing entry point behind `PHILIXA_INTENT_ROUTER_ENABLED` (default OFF).',
    '- Pydantic intent contracts, bounded deterministic help/stock/selections/numeric answers, and one semantic classification attempt through the existing Groq gateway.',
    '- The model proposes meaning/explicit fields; server code maps handler and task identity. No arbitrary model SQL/XML or write authority.',
    '- Scoped PostgreSQL route journal, request hash/deduplication, conversation focus, revision checks and recovery by stable task request identity.',
    '- Permission/session/native-company recheck after classification and existing domain checks at dispatch.',
    '- Grounded first-step draft proposal reused by the existing agent, without an extra call just to plan that step again.',
    '- Free text uses the central endpoint when enabled; typed legacy controls and rollback path preserved.',
    '- Worker heartbeat annotation prevents a dead document worker being presented as active thinking. Native outbox actions use their separate status.',
    '- Tokenizer/quota-pool warmup before background embedding preload; no model call during initialization.',
    '- Additive routing migration `f8y5z6a7b8c9` applied. Dev auto-created table adoption checks columns and uniqueness.',
    '', '## Automated verification',
    '', '- Routing/runtime/service/selection/quota/worker/help suite: **80 tests passed**. No native/provider calls in these mocked suites.',
    '- GST, purchase-memory duplicate, receipt-link, recovery and native-read regression group: **41 tests passed**.',
    '- JavaScript chat restore/scope, unified free-text entry, task references, status-only polling and worker-offline rendering: passed.',
    '- Targeted diff whitespace check: passed; only repository CRLF conversion notices remain.',
    '- Earlier legacy-flow test failed while the temporary new-router flag was ON. That test now explicitly selects legacy mode; separate tests cover the new router.',
    '', '## Observed browser acceptance',
    '', '- Existing logged-in in-app browser used; a fresh temporary tab recovered after the original tab cached a restart error.',
    '- Help `tu maire liye kiya kr sakta hai`: correct capability response, no task/Resume card. Backend **190 ms**, **zero Groq requests**; this is backend timing, not browser p95.',
    '- `stock kitna hai`: direct permitted stock read, zero Groq requests. Backend **8,292 ms** because the native read failed/timed out and returned saved data.',
    '- Saved result: Cement 30 bags, Goods18 141 bags, Goods5 23 bags, with last-sync timestamp and Read failed disclosure. This does not prove a fresh live Tally read.',
    '- Browser reload visibly restored the same help/stock conversation; no command was replayed.',
    '- Screenshot observed in tool output. No native posting, approval, voucher deletion or installer action performed.',
    '- Full semantic purchase → corrections → final review browser acceptance is still pending.',
    '', '## Synthetic model evaluation',
    '', 'Frozen v1 had 160 development and 80 held-out synthetic turns. V1 cold-start and output-validation failures remain preserved in `data/intent-routing-live.json`.',
    '', 'V2 removes redundant model-controlled handler/task plumbing. Eight consumed v1 turns became regression-only; 72 unrun turns plus eight new turns formed its frozen 80-turn held-out set. Development templates/prefix variants are correlated synthetic cases, not independent accountant samples.',
    '', f'- V2 tested **{len(rows)}/80** held-out turns; **{len(valid)} valid routes**, **{len(failures)} rejected evidence/output cases**.',
    '- These are strict routing-pipeline results. A rejected extraction is counted failed, never a successful accounting operation.',
    f'- Model-call latency among recorded successful responses: p50 **{manifest["model_latency_ms"]["p50"]} ms**, p95 **{manifest["model_latency_ms"]["p95"]} ms**. Excludes setup/admission waits and failed calls.',
    f'- Observed successful-row usage: prompt **{manifest["observed_prompt_tokens"]}**, completion **{manifest["observed_completion_tokens"]}**, cached prompt **{manifest["cached_prompt_tokens"]}** tokens. Failed/uncertain usage remains conservatively reserved in provider ledgers; these sums are not a billing total.',
    '- Testing stopped at existing local daily call cap. No cap increase, model replacement or paid fallback.',
    f'- Remaining **{80-len(rows)}** held-out turns untested. Already five failures mean this candidate cannot reach the proposed 76/80 pass threshold even if every remaining turn passes.',
    '- No real-world accuracy, real accountant time saving, actual currency cost or unlimited-free-use claim.',
    '', 'Rejected cases:', '']
lines += [f'- `{r["id"]}` — {r["category"]}: {r.get("failure","route mismatch")}' for r in failures]
lines += ['', '## Remaining work before enabling', '',
    '1. Diagnose rejected field/source evidence on development/regression cases; keep final accounting evidence checks strict. Do not tune and re-label this consumed held-out set as untouched.',
    '2. Prepare fresh held-out routing acceptance for the next material candidate and run within the unchanged shared/free-tier budgets.',
    '3. Complete the semantic purchase/correction/topic-switch browser flow, reload/restart and outage acceptance.',
    '4. Resolve the independently failing live Tally stock read; saved fallback is working but is not live-read success.',
    '5. Only after the routing/security/browser gates pass, enable the controlled review pilot. Existing real-company write gates remain unchanged.',
    '', '## Reproduction', '',
    '- Migration: `docker compose exec -T app alembic upgrade head`.',
    '- Backend tests: `docker compose exec -T app python -m unittest scripts.test_intent_router scripts.test_intent_router_model scripts.test_business_router scripts.test_task_queue_health scripts.test_task_agent_runtime scripts.test_task_agent_service scripts.test_task_agent_worker scripts.test_task_agent_selection scripts.test_groq_quota scripts.test_task_resume_presentation scripts.test_business_help`.',
    '- UI: `node scripts/test_business_chat_refresh.cjs`.',
    '- Frozen data/evaluator: `scripts/fixtures/intent_routing/`, `scripts/evaluate_intent_routing.py` and bounded `scripts/run_routing_evaluation.py`. Evaluation never executes domain tools.',
    '- Local-only reversible pilot: `python scripts/intent_router_pilot_config.py enable`; recreate app/worker; `restore` afterwards. Do not treat this utility as release approval.',
    '- Source hashes, usage and measured latencies: `data/intent-router-release-evidence.json`.', '']
(root/'INTENT_ROUTING_STATUS.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'status_report':'INTENT_ROUTING_STATUS.md','tested':len(rows),'valid':len(valid),'release_gate':False}))
