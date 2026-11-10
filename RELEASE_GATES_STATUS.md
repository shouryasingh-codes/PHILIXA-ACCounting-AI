# Synthetic regression release gate

Completed **21 October 2026 (IST)**. The selected synthetic release gate passes. This validates regressions in the listed suites; it does not certify real-world accounting accuracy or all Tally versions.

Subsequent posting-authorization work has its own 117-test targeted passing run plus 13 passing bulk/draft tests; see `POSTING_AUTHORIZATION.md`. The 313-test baseline below predates that later implementation. The full runner includes its new tests for future runs; no fresh larger full-suite count is claimed here.

- Backend: **313 tests passed**, zero failures, errors or skips, with unchanged before/after source fingerprints. Chat 34; stock/suppliers 25; purchase/GST/sync/drafts/review/memory/automation/report guards 154; physical count 16; customer ledger workflow 21; connector status 7; extraction/documents/metrics 48; source edge cases 8.
- Windows connector lifecycle: **14 tests passed**, native Windows runtime with isolated mocked installation/settings. Actual user pairing or installed helper was not changed by this run.
- JavaScript: **11 suites passed**, covering chat refresh, connector, documents, extraction review, drafts, GST, bulk review, memory, automation, active-review meter and metrics UI.

The old OCR UI fixture was out of date: it mocked the historical draft-list response instead of the current review-queue contract and expected superseded confidence wording. Updated its fake API/DOM and assertion to verify current scoped review-queue loading and the explicit extraction-confidence review warning. Existing side-by-side original viewing, page navigation, invoice splitting and draft reopening assertions still execute and pass. No application behavior was weakened to satisfy that test.

The requested adversarial/source fixture catalog has a separate **17-assertion pass** across 9 categories. See `FIXTURE_GATES_STATUS.md` and `scripts/fixtures/release/manifest.json` for duplicate PDFs/photos, severe blur, missing pagination, similar suppliers, wrong totals, malicious instructions, concurrent edits and scope isolation. The full runner now also records source fingerprints before/after execution and refuses a passing gate if source changes during a run. Customer bridge fixture assertions are protected by the synthetic endpoint's advisory lock so background snapshot reads cannot contaminate its queue contract.

Reproducible backend runner: `scripts/run_release_regressions.py`. It explicitly selects synthetic unittest modules instead of discovering live/setup scripts. Failure, error or skipped test prevents a passing gate; per-group results and the full test log are persisted.

```powershell
docker compose exec -T -e LITELLM_LOCAL_MODEL_COST_MAP=True app python -m scripts.run_release_regressions
.\.helper-build\Scripts\python.exe -m unittest scripts.test_connector_runtime -v
```

Run every `scripts/test_*.cjs` with the available Node runtime for the JS gate. Evidence is in `data/release-gates/backend.json`, `backend.log`, `windows-connector.log`, `javascript.json` and individual JS logs. Backend UTC start time is retained in its JSON; this check was resumed/completed on the client date above.

Providers and accounting/message transports are mocked where used. No real Tally purchase or external email/WhatsApp message was sent. PostgreSQL/Redis/private-storage checks use scoped synthetic fixtures and cleanup. Some tests log deliberately injected provider/worker failures; their assertions pass. The separate Day 9 corpus remains the bounded extraction evaluation; real anonymised bill/accountant testing remains unverified.
