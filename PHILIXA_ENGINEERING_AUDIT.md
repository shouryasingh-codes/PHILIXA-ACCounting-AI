# PHILIXA engineering reliability audit

**12 November follow-up:** The quarantined direct master writer has been replaced with an explicit-preview/approval, paired protocol-12 connector and journalled native-verification implementation. Actual activation remains blocked by Windows Application Control rejecting the new unsigned connector; no native master/purchase write was performed. See [current master-creation status](MASTER_CREATION_STATUS.md) for test evidence and remaining acceptance gates. Quarantine statements below describe the original audit finding.

Date: 12 November 2026 (IST). Scope: purchase agent, bill/draft review, accounting compiler, approvals, connector and recovery. Starting commit: `a723df5` (working tree was clean). No commit or push made.

## Decision

**Not certified production-ready.** This audit reproduced accounting and authority defects, implemented five corrections and quarantined one unsafe capability. Passing synthetic tests establish specific application invariants, not real-invoice accuracy or successful native Tally deployment.

No voucher or Tally master was posted during this audit. Existing environment files, pairing credentials, database volumes and original bills were not edited. Tests created scoped synthetic database fixtures and temporary journals through their existing setup/cleanup routines. No experimental feature or posting gate was enabled. Source edits are not proof that an installed Windows connector has the same fixes.

## 1. Actual architecture and readiness

The workflow was traced in source, including the latest GST/HSN and master-creation changes:

1. Browser composer, attachments and purchase review call the authenticated business APIs. The command endpoint preserves legacy compatibility and can enter the semantic front door when the task agent is enabled.
2. The semantic model proposes a typed intent, continuation relationship and grounded fields. Server routing validates candidate task/document ownership and dispatches reads, document questions or purchase work. Exact issued selections have a model-free path.
3. Durable PostgreSQL tasks/runs/executions feed the bounded task runtime. The model can select typed tools; the separate purchase-context graph has fixed masters/history/validation/proposal nodes. These are two cooperating mechanisms, not a single unrestricted reasoning agent.
4. Native IDs, exact names and approved company-scoped aliases resolve suppliers/items. History suggestions require matching scope and evidence; past invoice/date/reference must not become current facts. Revisions and evidence versions invalidate stale selections and previews.
5. Draft review prepares a supported GST/non-GST payload. Decimal arithmetic, native master definitions, invoice evidence, duplicate guards and tax-ledger profile checks are deterministic.
6. Preview creation is distinct from confirmation. Human confirmation checks principal/session, company/config/device versions, exact payload, current evidence and duplicate reservation, then records durable posting authority. Automation uses its separate policy/limit/release gates.
7. ARQ dispatch and the paired connector carry actions. Helper SQLite journals and native reconciliation are intended to recover an uncertain write with the same identity, not resend it blindly. Verification compares voucher reference/date, party, quantities, units, rates, HSN, taxes, ledger/batch allocation and totals.

Key source entry points (absolute repository root: `C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main`):

- [Business API](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/api/v1/routes_business.py>), [business router](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/business_router.py>), [routing contract](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/intent_router.py>), [model router](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/intent_router_model.py>).
- [Durable task lifecycle](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/task_agent_service.py>), [bounded runtime](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/task_agent_runtime.py>), [typed tools](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/task_agent_tools.py>), [purchase context graph](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/purchase_agent.py>).
- [Conversation/draft enrichment](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/purchase_conversation.py>), [native history context](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/purchase_native_context.py>), [approved identity memory](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/purchase_memory_service.py>).
- [Draft lifecycle](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/purchase_draft_service.py>), [GST preview service](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/purchase_tax_service.py>), [GST compiler/verifier](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/tally_gst_purchase.py>), [action confirmation/dispatch](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/tally_sync.py>), [posting authorization](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/posting_authorization.py>).
- [Task jobs](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/jobs/task_agent_jobs.py>), [helper runtime](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/helper/connect.py>), [wire protocol/journal](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/tally_sync_protocol.py>), [review UI](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/web/business-drafts.js>).

Current source uses FastAPI 0.137.2, SQLAlchemy 2.0.51, Pydantic 2.13.4, psycopg 3.2.3, HTTPX 0.28.1, ARQ 0.26.1, PostgreSQL, Redis, MinIO, LangGraph and the shared Groq gateway. The baseline remains GPT-OSS20B. Helper source version is 3.8.0, protocol 11; this is **not** installed-artifact verification. Some dependencies (including LangGraph/LiteLLM) have lower bounds rather than reproducible exact locks.

Runtime app flag snapshot, read from an explicit allowlist (no secrets): task agent `1`; semantic router flag unset, but front-door compatibility also consults task-agent enablement; deterministic selections `1`; purchase-context feature flag `0`; attachments `1`; local OCR `1`; layout review `1`; purchase reports `1`. GST acceptance flag is unset and currently defaults to **enabled** in the source. These pre-existing values were preserved. Do not interpret the runtime as a globally disabled experimental deployment.

Readiness: scoped reads, draft/preview services and durable task primitives exist and have substantial synthetic coverage. Automatic missing-master creation is now unavailable. Live routing accuracy, packaged helper acceptance, physical reconnect/restart behaviour and fresh native posting remain unverified by this audit.

## 2. Tests actually executed

### Baseline and focused runs

- Baseline: **151 tests, 149 passed, 2 failed, no skips/errors** (159.37 seconds including harness setup). Both failures were investigated rather than hidden.
- The first three new safety regressions failed before the corrections, then **3/3 passed**. Their failure logs prove the unsafe paths were reached.
- Supplier-history date regression failed for both undated and future-only history before correction.
- Master-write boundary regressions failed **2/2** before quarantine, then passed in a **26-test** runtime/selection run.
- Focused accounting/conversation/router/draft run: **79/79 passed** after corrections.
- Independent Decimal arithmetic matrix plus existing GST arithmetic/native-shaped transport cases: **40/40 passed**. Thirty-two cases are the independent matrix; the other eight are existing arithmetic and fake-transport cases. Do not add these overlapping runs to the final unique count.
- Explicit English/Hinglish/Hindi source-grounding matrix: **30/30 passed**. Structured model outputs are supplied by the test; this is not live language-model accuracy measurement.
- First expanded run: **351 attempted, 350 passed, 1 environment import error**. The backend container does not mount the Windows `helper` package. The portable runner now keeps Windows helper tests as an explicit opt-in. The first expanded result is retained, not deleted.
- Portable expanded rerun: **380/380 passed, zero failures/errors/skips** (240.60 seconds in unittest; 249.45 seconds including harness loading). This included the 30 multilingual contracts, independent arithmetic matrix, approval, concurrency, stock/customer/count and recovery regressions.
- A final supplier-registration tightening added one more regression (missing registration type and missing historical GSTIN). Its two subcases failed before correction. The impacted accounting/conversation/draft/automation modules were then rerun: **121/121 passed**. That focused run overlaps the 380-test run; do not sum them. The recorded 380-test JSON predates this last tightening; its post-change evidence is `final-tax-regressions.log`. A fresh full runner invocation now also discovers that additional test.

Ten JavaScript controller suites passed after fixes/harness maintenance: bill documents, bill evaluation, chat attachments, connector UI, GST UI, extraction review, automation, draft lifecycle, company memory and bulk review. These run real controller code with a fake DOM/API, **not a real browser**. The attachment suite initially failed because its assertions assumed a pre-icon/pre-actions-wrapper DOM; the updated test still verifies literal untrusted filename text and the actual original-file button.

### At least 30 realistic agent/domain scenarios

The reproducible multilingual matrix contains ten distinct situations in each of English, Hinglish and Hindi, for 30 separately named cases:

1. Partial purchase, quantity/item/unit present; absent supplier/reference/date remain absent.
2. Complete explicit supplier/rate/reference/date/total input.
3. Rate correction preserves quantity and other existing facts.
4. Quantity correction preserves the explicit rate.
5. Two items with separate quantities/rates/units.
6. Explicit percentage discount.
7. Indian invoice-date normalization.
8. Explicit BOX/NOS unit update without quantity conversion.
9. Proposed rate absent from the source is rejected.
10. Permission/workspace update proposed from a user instruction is rejected.

Additional executed service/runtime tests cover ambiguous suppliers and partial names; historical price acceptance requiring evidence; stale history and changed native identities; missing GST state; explicit tax on a non-GST path; malformed output; repeated commands reopening the same draft; transaction rollback; concurrent routing/attachment requests; cross-workspace/session access; changed permissions; offline context; provider/quota denial; six-round/twelve-tool limits; exactly one transient read retry; no automatic write retry; interrupted-write reconciliation; model completion without native proof; and no private planner rationale as a public reply.

Representative test IDs and exact outcomes are in the JSON ledger. Provider calls, native catalogs and transport are mocked in these scenarios. The tests cannot establish that GPT-OSS20B independently understands 30 unseen live messages. That live evaluation remains a release gate.

### Independent accounting expectations

The new matrix uses `Decimal` and `ROUND_HALF_UP` in a separate reference calculation: four native configured units (`bags`, `PCS`, `BOX`, `NOS`) × intra/inter-state × no discount/7.5% line discount/fixed line discount/invoice discount with disclosed round-off = 32 cases.

Each case checks taxable value, CGST/SGST or IGST, total and retained unit against the independent expected result. Existing cases also cover mixed 18%/5% lines, proportional invoice discounts, UTGST, positive/negative paisa rounding, round-off bounds, absent round-off ledger, wrong grand total, changed GST-effective dates, group inheritance, duplicate effective definitions and missing HSN. Fixture tax rates are test inputs, not an assertion of current statutory HSN classification.

## 3. Confirmed defects and verified fixes

### A. Critical: totals used as line GST evidence, with unrevisioned draft mutation

Preview code divided total invoice tax by total taxable value, assigned the result to missing line GST rates and mutated nested saved content. A mixed-rate invoice can produce a plausible weighted average; balanced totals do not identify any line's true rate. It also implicitly changed tax treatment.

Fix: remove this inference. Positive source tax without an explicit supported treatment, missing line rate/HSN, or unsupported treatment now requires review before compilation. Preview must not fill those facts or alter the draft revision/action. Regression `PreviewEvidence.test_preview_never_fills_missing_rate_from_reconciled_total` fails before the fix and passes after it.

Changed: [purchase_draft_service.py](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/purchase_draft_service.py>).

### B. Critical: invoice fields silently replaced missing effective GST masters

The compiler caught missing native item/group/purchase/company GST details and promoted invoice HSN/rate into the effective master result. Agreement of supplied totals was then mistaken for independent master corroboration.

Fix: require successful native effective-master resolution; no invoice-as-master fallback. Missing or conflicting native evidence blocks supported compilation. Regression `MasterEvidence.test_missing_effective_gst_masters_cannot_be_replaced_by_invoice_values` failed before and passes after.

Changed: [tally_gst_purchase.py](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/tally_gst_purchase.py>).

### C. High: unit names substituted for missing native GST UQC configuration

The compiler guessed BAG/PCS/BOX/NOS reporting codes from a display label when native reporting-unit evidence was missing.

Fix: require configured native UQC; keep unsupported/missing definitions in review. Explicitly configured versions of all four units pass the independent matrix. Regression `MasterEvidence.test_unit_label_cannot_replace_missing_native_uqc` failed before and passes after.

Changed: [tally_gst_purchase.py](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/tally_gst_purchase.py>).

### D. High: invalid supplier GST history fell back to current GSTIN

Blank effective dates were skipped. Future-only dated supplier history also fell back to the parent ledger/current registration. This could make an old invoice appear to have verified registration evidence.

Fix: undated/malformed effective definitions raise a controlled error; when supplier history exists but no definition applies to the invoice date, do not fall back to the current parent. A selected historical definition must provide its own GSTIN and registration type; absent type is not defaulted to Regular. Optional conversation enrichment preserves the draft and displays an unresolved GST warning. Undated, future-only, missing-type and missing-historical-GSTIN regression subcases pass; the existing conversation regression is green.

Changed: [tally_gst_purchase.py](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/tally_gst_purchase.py>), [purchase_conversation.py](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/purchase_conversation.py>).

### E. Critical: native master writes mislabeled as draft-only, outside durable authority

`create_tally_masters` was registered as effect `draft`, so review-mode filtering exposed it. Its service directly constructed a server-local `TallyConnector`, posted XML, and claimed creation without operation-specific approval, paired-device dispatch, durable action/journal identity or independent native result validation. This is especially dangerous for a remote paired device: the web server's local Tally is not necessarily the user's authorized target. Tests reproduced registry exposure and service entry without touching real Tally.

Safe mitigation: classify it as `write` and unconditionally reject the legacy service with HTTP 409 **before database/connector access**. It is quarantined, not reimplemented or certified. Existing invoice review/purchase submission remains through its existing pipeline. A future master-creation adapter must use the same scoped authority, explicit preview, action identity and reconciliation principles as voucher writes. UI suggestions offering automatic creation can now receive an explicit unavailable response; the capability is not usable until redesigned.

Changed: [task_agent_tools.py](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/task_agent_tools.py>), [tally_master_service.py](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/services/tally_master_service.py>).

### F. Medium: busy completion re-enabled mutation controls on read-only drafts

`setBusy(false)` re-enabled form buttons independently of the draft edit lock. Fields stayed read-only while Save/Create preview could become enabled. Server checks remained the authority, but the interface offered an invalid action.

Fix: Save and preview disabled state now also respects `selected.editable`; the asset version was bumped. A regression assertion failed before correction and passes after. The real browser reload then retained disabled Save/preview controls for the inspected verified draft.

Changed: [business-drafts.js](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/web/business-drafts.js>), [index.html](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/app/web/index.html>).

### Test-contract maintenance, not additional product defects

The old semantic-router test expected rejection of stray stock prose, while the latest implementation deliberately strips conversational prose from domain routes. The updated assertion verifies the prose is absent, the handler remains a domain read and no task target is introduced. It does not accept the invented stock value. The attachment test was updated for a decorative filename icon and an actions wrapper, preserving the literal-text and private-preview checks.

## 4. Real browser observations

The actual logged-in in-app browser was opened on localhost:8001. Existing data was inspected without entering new accounting instructions, editing fields, confirming actions or uploading documents.

- The saved chat returned after reload. One active Purchase task control container was present in the inspected conversation. Historical repeated transcript answers were visible; they were not presented as newly executed successes. This sample does not prove every conversation avoids rendering loops.
- Saved Bills showed 35 needs-attention and 7 verified entries, with no Ready or Posting entries at inspection. These are pre-existing application states, not vouchers verified by this audit.
- Existing `C01.pdf` / `QA26-001` reopened after full reload with the same supplier, item, date `2026-10-02`, quantity 5 bags, rate 100, taxable 500, GST rate 18, HSN 2523, CGST 45, SGST 45 and total 590. Its original document appeared beside the draft. Its pre-existing label was Tally verified.
- After the source/UI correction and refreshed asset, read-only item fields and Save/Create preview remained disabled after asynchronous document loading completed.
- No new confirmation button was clicked. A fresh correction → preview → confirmation browser flow and repeated-submit race were **not** executed against user records. Those behaviours have fake-DOM/service coverage only.

## 5. Native Tally, recovery and deployment limits

**Fresh native posting acceptance: blocked/unverified.** Browser connectivity reported Live available and Windows inventory listed TallyPrime, but this audit did not establish a separate isolated native fixture with exact company identity, approved voucher arguments and supported test date. It did not rely on a company name alone to authorize a write. No real business company was used.

Fake-transport and subprocess tests did execute import/reconciliation logic. The crash test kills a synthetic child after its fake import; subsequent child runs reconcile the same identity and assert one import. Timeout-with-no-visible-voucher remains verification_pending across restarts with one attempted send. Native-shaped verifier tests mutate reference, GSTIN, tax ledger values, quantities, allocations, rates and HSN-related fields and reject mismatches. These are valuable regression checks, **not native Tally acceptance**.

Physical connector disconnection/reconnection, worker restart while an actual native request is in flight, Windows installation/update, packaged TLS initialization, and current installed EXE protocol/source alignment were not certified. The backend container's Windows helper contract module could not import because `helper` is not mounted. Host system Python also lacked `pystray`. The existing helper-build interpreter produced no completed result within the audit attempt and was stopped; the reason was not established. No dependency was installed and Windows protections were not changed. These environment failures are retained in the evidence instead of converted into passes.

Existing GST acceptance defaults to enabled when unset, while receipt certification is a source constant. This audit preserved those pre-existing settings. Public rollout should replace implicit release assumptions with explicit artifact/version acceptance and fail-closed operator configuration.

## 6. Remaining risks and unverified claims

- No fresh live Groq labelled evaluation was performed. Mocked structured decisions prove contracts/plumbing, not generalization to unseen Hindi/Hinglish or semantic routing accuracy. No accuracy percentage is claimed.
- No fresh public real-invoice OCR benchmark or accountant-labelled held-out evaluation was performed. Original OCR confidence/unresolved fields must remain reviewable.
- Native/company tax master agreement is not a legal classification authority. Current statutory HSN/rate correctness and exceptions require maintained jurisdiction/domain evidence and accountant review; tax totals alone prove neither.
- The quarantined master writer is a missing capability. It requires a replacement adapter, not a hidden fallback or flag to bypass the block. Some UI creation suggestions still need capability-aware disablement.
- Worker processes and installed helper bundles may retain pre-edit imports; no production worker/helper restart or deployment was performed. Rebuild/install the exact candidate and run native acceptance before claiming the end-user path contains these fixes.
- A psycopg unclosed-connection ResourceWarning appeared after a focused synthetic test run. Test teardown/pool lifecycle needs cleanup; no operational data-loss conclusion can be drawn from that warning alone.
- Broad suites do not exhaust cross-process crash points or all concurrency interleavings. Representative real accountant handling-time/savings and model cost were not measured.

## 7. Top five improvements, in priority order

1. **Finish authority-safe master creation.** Revision/evidence-bound preview and approval, exact paired native company, durable action and SQLite identity, fresh native validation and no blind retry. Keep the legacy block until a reviewed implementation passes remote-device and uncertain-result tests.
2. **Make tax evidence explicit end-to-end.** Distinguish extracted/user-confirmed/master-derived/calculated/unresolved per field; require dated native HSN/rate/UQC support and specific review of conflicts. Add mixed-rate real-invoice golden fixtures before considering auto-post candidates.
3. **Run native acceptance on a deliberately isolated company and exact artifact.** Cover licensed/educational date constraints, approval, full voucher fields, duplicate resend, disconnect/reconnect and restart after uncertain import. Rebuild the helper so packaged/server validation does not drift.
4. **Measure live language routing and recovery, not just mocked contracts.** Held-out Hindi/Hinglish/English, topic changes, ambiguous identities, multi-item corrections and provider failures. Record route trajectory, latency, questions, tokens and failures under existing free-tier/budget caps; no per-phrase patching as the release criterion.
5. **Make review predictable and observable.** Capability-aware buttons, one active proposal, grouped missing facts, persistent unresolved evidence and actionable status; automate browser correction/reload/preview acceptance with disposable fixtures. Pin a release dependency/artifact manifest and enforce these tests in CI.

## Evidence and reproduction

New [audit regressions](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/scripts/test_engineering_audit.py>) and [recorded suite runner](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/scripts/run_engineering_audit.py>) are included. The runner returns nonzero for failures/errors and records every test ID/outcome.

From the repository root, with the existing local services running:

```powershell
docker compose -p accounts-dev -f docker-compose.yml exec -T app python -m scripts.run_engineering_audit --extended --output final-regression
node scripts/test_purchase_drafts_ui.cjs
node scripts/test_chat_attachments_ui.cjs
```

All ten UI suites can be run with `Get-ChildItem scripts/test*ui.cjs`, executing each with Node and checking its own exit code. Windows helper contracts require a functioning helper development environment; they are separate from the portable backend run. Do not install/update the user's connector as part of a unit test.

Logs and per-test JSON are in [audit evidence directory](<C:/Users/admin/Desktop/AI assistant for company accounts/philixa-6.0-main/data/engineering-audit>). Important artifacts: `regression.json/log`, `before-fix.log`, `after-fix.log`, `date-before-fix.log`, `registration-before-fix.log`, `master-write-before-fix.log`, `master-write-after-fix.log`, `ui-before-fix.log`, `focused-after-fix.log`, `final-tax-regressions.log`, `multilingual-contracts.log`, `extended-first-run.json/log`, `final-regression.json/log`, individual UI logs, and `helper-host.log`. `source-manifest.json` records SHA-256 hashes of changed runtime sources and the audit harness/tests. Syntax compilation and `git diff --check` passed.

The evidence directory is local test output, not automatically committed. Preserve the initial failure logs when rerunning. A successful synthetic run does not authorize posting, enable policies or certify a public release.
