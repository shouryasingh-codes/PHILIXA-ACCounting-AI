# Shorter purchase interaction — 3 November 2026

Changes:
- Pending native history now schedules bounded server-owned context refreshes automatically. Browser polling remains GET-only; the accountant does not need repeated status/refresh messages. Existing combined supplier/rate suggestion is displayed when the native evidence is ready.
- Context refreshes use the existing domain service, not the planner model. Same task, draft and revision guards apply. Five-second wake-ups stop within the original 120-second context deadline; no worker sleep or unlimited retry is added. Recovery cron can recover queued wake-ups.
- An exact standalone unknown-details answer such as `pata nahi` saves an acknowledged pause without a model call, draft mutation or fabricated invoice/tax facts. A subsequent real correction can resume normally. The answer and prior state remain audited; duplicate request IDs return the same result.
- Manual status buttons are suppressed for task-driven history waits. Existing legacy purchase flow remains available.

Validation:
- Task lifecycle, worker and deterministic-selection set: 16 tests passed before the added automatic-history test.
- Final lifecycle/worker set: 13 tests passed, including pending → ready without another user message/model call, and unknown details without enqueue/repeated question. Counts overlap.
- Chat restore/status-only polling JavaScript check passed.
- Idle worker restarted after preflight showed no active actions, running tasks or processing documents. No Tally posting performed.
- Browser control currently returns unavailable; fresh visual/end-to-end acceptance remains unverified. These changes do not prove broad agent accuracy or an accountant time-saving percentage.

Expected interaction: purchase message → automatic context → one explicit supplier/rate acceptance when evidence supports it → grouped genuinely missing facts or an acknowledged saved pause → final validated review. Historical date/invoice/tax values are never invented for the new transaction.

## Follow-up: delayed history queue

Live worker logs exposed a missing web-global Redis pool in the ARQ worker. History records were committed, but initial enqueue did nothing; only the minute cron dispatched them. Fixed `purchase_native_context.enqueue` to obtain and close an owned Redis pool when no shared pool exists. PostgreSQL recovery remains the fallback.

Nine history scheduling/context/worker tests passed, including missing-web-pool immediate enqueue and shared-pool ownership. Idle worker reloaded. Read-only check of the reported task `9f9dff50d793aabf288052ed645223d0` confirmed native history status `ready`, rate suggestion ₹350, same draft, no posting. Browser control was unavailable, so current-screen repaint was not verified.
