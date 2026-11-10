# Meaning-based routing — implementation and acceptance status

Updated: 7 November 2026. **Mandatory conversation guard is active when the existing task agent is enabled. Full seeded purchase-context rollout remains OFF; review-only remains ON.**

## 7 November: social-message queue incident

- The previous fallback sent every free-text message into an accounting task with a verified-entry outcome. “or bata kiya haal hai” therefore waited in the document/agent queue and later failed a completely irrelevant native-outcome check.
- Provider timing for the original task was only 751 ms. Worker logs additionally showed duplicate wake jobs for the same task and delayed recovery processing; a live heartbeat had been misrepresented as this particular task thinking.
- Classification is now mandatory before accounting dispatch, even when the full context/seed rollout is OFF. Semantic `smalltalk` returns a safe direct conversational reply. It creates/resumes no accounting task. Business requests retain the existing domain pipeline; new grounded seeds remain gated. No phrase-specific smalltalk matcher was added.
- Social prefaces do not count as a second business task. Current legacy tasks can be supplied as scoped candidate hints; the server decides whether a message actually continues them. Explicit card actions still bind exact task/revision.
- Queue presentation now separates waiting-worker, running-with-live-lease and waiting-context. A worker heartbeat alone no longer turns on a thinking animation.
- Initial enqueue, document completion and recovery scans use stable task/revision wake IDs. An isolated real-Redis test proved ten parallel wakes create one pending job; a new revision gets its own job. Document processing concurrency was not increased and no queue was purged.
- Browser verified exact Hinglish plus different English check-in. Recorded server response times: 899 ms, 653 ms, and final reloaded build 601 ms. These are observed backend timings, not a universal UI latency guarantee. Each used one real Groq call and created zero accounting tasks. Proof: `data/social-routing-verification.json`; screenshot: `social-routing-verified.png`.
- Final combined regression run: **139 tests passed**. Lifecycle fixtures were isolated from the live worker to remove an actual cancellation race in the tests. Accounting approval/cancel safeguards were preserved.
- Full-domain evaluation below is historical and does not establish acceptance for the new classifier contract. The source/fingerprint gate continues to block the seeded purchase rollout; no paid cap was raised and no native Tally posting was performed.

## Earlier implementation and full-rollout acceptance

## Implemented

- Existing semantic router is the authoritative front door when the task agent is enabled; its full seeded-domain rollout is separately gated. Free text no longer inherits a previous task from frontend topic regexes. Explicit card actions bind their own task/revision.
- Current message + last three conversation turns + bounded current draft/choice context + authoritative attachment index are passed to classification. Index is limited to 10 documents / 20 drafts overall and discloses incomplete coverage. No raw OCR is included.
- Document questions use a document-only target field, exact scoped source/draft readers and generation/revision checks. They do not resume or mutate an accounting task. Help and independent reads do not render inherited bill cards.
- Semantic intent determines permitted handler; server compiles independent-task relation from actual context and retains the model-reported relation in audit. A model cannot select another task or authorize posting.
- Internal rationale and public reply are separate contracts. Missing public output gets safe clarification.
- Classifier has an 8-second deadline, one transmitted attempt and no automatic routing retry. Timeout/quota produces explicit Retry. Status polling does not replay commands.
- POST /api/v1/business/routing/{route_id}/retry accepts a stable request_id. Only classification failures can retry; uncertain dispatch uses status reconciliation. Retry idempotency survives chat saves and reloads. Existing command/resume APIs remain compatible; additive JSON fields require no DB migration.
- Existing caps, permissions, approval, duplicate and native-verification gates remain unchanged. No paid fallback, model replacement or Tally posting was performed.

## Verification

- Routing/agent/attachment/receipt/recovery backend suite: **93 tests passed**. Final routing/agent/pilot-gate suite: **82 passed** (overlapping).
- Separate purchase/GST/routing regression run: **67 passed**; overlaps with the 93, do not sum.
- UI checks passed: chat task identity/status polling, explicit old-card targeting, attachment picker/upload, draft review, extraction, GST and private-document viewer.
- Mocked integration: two bill drafts -> unrelated help leaves original task unchanged; second-bill total reads the correct source; no accounting action is linked.
- Browser semantic review pilot: **not run / not accepted**. Feature gate intentionally prevents pilot enablement until classifier acceptance passes.

## Live evaluation, including failures

- `scripts/fixtures/intent_routing/golden-v3.json`: original frozen 120 development / 60 held-out cases.
- First pre-repair held-out run: 23 recorded, 13 exact passes. It exposed an ambiguous wire target field and inconsistent relation labels. This failed report is retained at `data/intent-router-golden-v3-live-heldout.json` and is not a claim about the final contract.
- Document-only target naming was repaired. Fresh development supplier, stock and bill-total checks passed through the real free-tier gateway.
- `golden-v4.json`: 120 development / 60 fresh held-out / 23 retained consumed regressions. Evaluated v3 cases were removed from the unseen split and replaced; failed records were not erased.
- Current frozen-contract run: **14 of 60 recorded; 12 exact passes; 2 failures; 46 pending.** See `data/intent-router-golden-v4-live-heldout.json`.
- Failures: one task-answer/correction label mismatch and one unsupported extracted update path. Both fail closed; classifier-only evaluation executes no domain tools. These are not ignored or counted as passes.
- Existing **local daily call cap** stopped further calls. No cap was raised. This partial, category-ordered sample is not a real-world accuracy estimate.

## Resume and release

Run from the repository root in the existing app container:

```powershell
docker compose -p accounts-dev exec -T -e LITELLM_LOCAL_MODEL_COST_MAP=True app python -m scripts.run_routing_evaluation
```

The runner resumes only unseen/unrecorded cases with the same dataset/prompt/schema/adapter fingerprint, follows unsent quota delays, never automatically retries a recorded transmitted failure, and stops at daily/local caps or an unreachable 95% gate. A changed fingerprint requires a new report/evaluation; consumed held-out cases must not be presented as fresh.

Release still requires all 60 held-out cases, >=95% intent/relation/target exact match, zero established critical errors, matching regression evidence and browser acceptance. `scripts.intent_router_pilot_config` now binds evidence to the current classifier fingerprint and implementation hash. Its `acceptance` action requires the full classifier gate plus regressions before a temporary local review-only browser test; `enable` additionally requires browser and zero-critical-error acceptance. The guard was checked and refused activation with the current incomplete report. Full seeded-domain default remains OFF.

The current classifier fingerprint is pinned in the report; the failed pre-repair generation is retained separately. Browser acceptance is not claimed from mocked UI tests.

Remaining work: finish live acceptance when existing quota permits; address any remaining failures with development/regression evidence and fresh held-out replacements if tuning occurs; then perform browser review-only acceptance. Do not claim full completion from unit tests or a single example.


## 2026-11-07: conversational reply correction
Removed the universal smalltalk response from dispatch. The same bounded semantic call now returns a typed conversational_reply, which is persisted/replayed with the route; no second generation call. Only greeting/smalltalk may supply this field; missing smalltalk output fails validation rather than using a canned answer. Accounting handlers still require domain reads and authority.
Validation: 34 routing model/contracts/PostgreSQL lifecycle tests passed, including distinct responses, idempotent replay, no task creation, and rejection of conversational output attached to stock reads. Three live free-tier model calls returned distinct responses for identity/check-in/human identity. Those calls exposed English output for Hinglish and a generic check-in; instructions were tightened. Two subsequent validation attempts were deferred by the shared quota gateway before transmission. Final language quality and fresh browser acceptance remain unverified. No Tally writes. Full release gate is not passed.

## 2026-11-07: duplicate quota guards
Current provider token remaining/reset snapshots now replace the additional rolling-token admission check while fresh; RPM, account daily guards, atomic reservations, 10% headroom and provider cooldown remain. Missing/expired headers keep conservative rolling fallback. No assumed token refill was added. The extra business-layer 50 free-call/day cap defaults to absent only with the shared gateway enabled; explicit PHILIXA_GROQ_LOCAL_DAILY_CALLS remains available and gateway-disabled legacy defaults to 50. Paid budget unchanged. Router errors distinguish unsent local admission from provider rejection.
35 PostgreSQL quota/routing/worker tests passed, including parallel admission, provider snapshots, expired-header fallback, daily caps and uncertain-call recovery. One live existing free-tier model request passed and returned a relevant Hinglish identity response (1999 tokens). No native Tally writes; browser acceptance not performed for this change.

## 2026-11-07: personal identity routing
Latest failed user route 2aa606e3bef9028b20204c8f4a651c6c recorded RoutingOutputError, but historical validator detail was not retained; its exact failed invariant cannot be recovered. Added sanitized RoutingOutputError diagnostics to route telemetry and replaced unrelated accounting-menu fallback with an honest response-generation failure. No exact-message rule added.
An empty-context live synthetic reproduction of "who i am" initially returned help, showing an independent semantic taxonomy defect. Updated general prompt boundaries: capability help versus identity/social questions; I/me versus you; no name/profile inference from suppliers/documents; unknown personal information is a legitimate conversational response. Live "Do you know my name?" then correctly returned smalltalk and an unknown-name answer. The shorter identity question returned clarification; full clarification quality and subsequent live cases remain pending because gateway admission deferred calls. Saved private conversation replay was rejected by automatic approval review and was not performed; only synthetic empty/fictional context used for live requests.
36 router contract/model/PostgreSQL integration tests passed. These mocked semantic outputs verify wiring and authority, not live model accuracy. No browser acceptance or Tally writes performed.

## 2026-11-07: conversational and capability boundary
Added a server product capability catalogue tied by an AST regression to registered tools. Catalogue explicitly excludes browsing, banking payments and unreleased sales/payment/bank automation; catalogue is never execution authority. The same semantic request can now answer capability/general-conversation questions directly. Semantic help no longer discards the model answer in favour of the universal capability template; unsupported actions may return a specific limitation without creating a task. Typed/known broad help retains its existing catalogue fast path. Actual private-data reads and mutations remain domain-bound; conversational replies on stock/purchase routes remain invalid. No wording-specific rule was added.
38 router/model/PostgreSQL integration tests passed. Empty-context live synthetic tests: internet capability -> help and explicit no-browsing answer; bank payment -> unsupported and explicit no-transfer answer. Other synthetic explanation/stock/file-access cases were not transmitted due quota. Hinglish capability answer came back in English despite instruction, so language adherence remains unverified. Browser acceptance and full unseen held-out gate remain pending; this is not a general reliability completion claim. No native writes.

## 2026-11-07: remove broad-help template override
Removed help_answer matching from the authoritative free-text router. Broad help now uses the same bounded semantic model request as specific capability questions. A help route requires conversational_reply; dispatch no longer substitutes the static capability paragraph. Explicit read/selection controls remain deterministic. Legacy business_help module is retained for rollback consumers rather than deleted. Updated tests to assert semantic help, required reply, idempotency, and existing authority separation. 38 targeted tests passed after correcting a test-only reservation telemetry mock. Live empty-context broad Hinglish help prompt returned intent help and a generated supported-capabilities answer; it still answered in English, so language compliance remains pending. No Tally writes or browser acceptance.

## 2026-11-09: conversational token load and rejected requests
Compacted duplicated routing instructions (7471 -> approximately 3500 characters) while retaining full schema, output allowance, evidence/authority checks and existing provider limits. Empty-context reservation estimate fell from 3908 to approximately 3070 tokens. Initial compact candidate allowed three consecutive synthetic calls (1672/1679/1644 actual tokens), but replies exposed capability-answer quality problems; instructions and agent-scope catalogue were corrected rather than claiming those answers pass. Final fresh live verification received provider HTTP403 twice; full reservation charges then caused a local quota defer. Explicit pre-generation 400/401/403/404/405/413/415/422 rejections now release token reservations; transmitted request counting and uncertain timeout reservations remain. Historical ledger was not cleared. Offline router/quota tests: 53 pass. Current final live quality/browser acceptance remains pending due provider access rejection. No native writes, paid fallback or quota-limit raise.

## 2026-11-09: provider-access failure
Screenshot-associated latest route 41e68afff034ea6be5a0996bb034b57c failed AIExtractionError: HTTP403, 478ms provider time, zero charged tokens. Unauthenticated Windows and Docker requests to api.groq.com/openai/v1/models both returned Cloudflare403; Windows console.groq.com also returned403. No proxy environment variables present. This establishes failure before semantic routing; it does not establish VPN as the specific cause. No keys/prompts/private accounting payload used for network checks.
Router now distinguishes provider_access_denied403 and provider_authentication_failed401 from unclear input, quota and timeout. Existing failed routes retain their original audit; new/retried routes use the clear classification. Network/VPN state requested from user; access recovery and full live/browser acceptance pending.
