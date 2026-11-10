# Invoice OCR concurrency, retries and spend admission

Document workers run one job concurrently. PostgreSQL also holds a global extraction advisory lock across worker replicas. A busy slot leaves the durable job queued without spending an attempt.

Extraction has at most two total automatic attempts: initial attempt plus one retry for timeout, connection failure, or HTTP 429/500/502/503/504. The durable retry waits 30 seconds. Authentication, model, validation and unknown errors do not automatically retry. The HTTP adapter performs one request per attempt. Automatic paid provider fallback is disabled. Interrupted jobs recover within the same two-attempt bound.

## Configuration

Set both environment variables on the document worker, then recreate that service to load changed environment:

- `PHILIXA_INVOICE_AI_DAILY_CAP_USD`: deployment-wide daily invoice AI budget in USD.
- `PHILIXA_INVOICE_AI_MAX_REQUEST_USD`: reviewed conservative maximum USD cost of one request, covering the configured model and maximum supported input/output.

Both default to zero: paid invoice extraction pauses until positive valid values are configured. No spending amount has been chosen on the user's behalf. General chat/provider usage outside invoice extraction is not covered by this gate.

Each request reserves its full configured maximum in PostgreSQL before HTTP. An advisory transaction lock serializes admission across organizations. The day resets at midnight Asia/Kolkata. Failed, timed-out or interrupted calls retain their reservation; document/workspace deletion does not refund it. The same job attempt cannot reserve twice. This deliberately overcounts rather than refunding uncertain provider work.

This is a conservative reservation cap, not a live provider billing meter. Its financial guarantee depends on a correct worst-case request bound; an underpriced bound cannot guarantee actual charges. Provider account billing limits remain separate. Local OCR and cached results need no paid reservation; local compute is not free in a hosting-cost sense.

When the next reservation would exceed the cap, the current and remaining queued paid documents become durable `paused_budget` records. UI displays the reason and **Budget paused · resume**. Recovery and page reload do not automatically restart them. Resume is explicit, and admission checks the cap again. New uploads and repeated resume cannot bypass the daily ledger. Free cached/local image work can continue.

Migration: `z2s9t0u1v2w3_invoice_ai_budget.py`. Validation: `scripts.test_invoice_ai_limits`, `scripts.test_invoice_transport`, extraction/document regressions and `scripts/test_bill_documents_ui.cjs`. Provider HTTP is mocked for spend/retry tests; no paid verification calls or Tally posting are required.

## Verified 21 October 2026

38 targeted backend tests passed (budget, transport, extraction, private documents), and document UI tests passed including paused reload with no automatic resume. After immediate pause-on-full-reservation was added, all 10 budget/transport tests passed again. Migration applied; document worker restarted with zero active extractions. Budget settings are currently unset/invalid, so paid OCR is disabled until both valid limits are configured. No paid API test calls or Tally writes were performed. Existing test harness emitted connection cleanup warnings on interpreter exit; tests had no failures.
