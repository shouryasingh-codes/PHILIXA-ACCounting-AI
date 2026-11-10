# Day 8 — implemented and verified

Verified on 16 October 2026 (India time).

## Result

One new digital dummy PDF, `PHILIXA-D8-AUTO-20261016`, automatically queued and posted without human bill confirmation. The installed protocol-9 connector verified **Purchase voucher 20**, **₹211.20**, in **Philixa Test**. The company automation policy was paused after acceptance. Existing Day 5 vouchers were not reposted.

Evidence: `data/day8/live-auto-post-proof.json`, original `data/day8/day8-dummy-digital.pdf`, and `data/day8/worker-source-proof.json`.

## Implemented

- Company-scoped owner/admin policy: paused, shadow, auto; explicit supplier and item allowlists bound to stable master identity/fingerprint. Every positive per-invoice, daily amount and daily count limit is required; incomplete policy disables automation.
- Immutable policy-edit events and per-draft suggested `auto_post`, `review`, `blocked` decisions, reasons, source/content hashes, draft/policy revision and posting-action links.
- Shadow mode creates a validated preview only. Human approval is still required; no automatic write or budget reservation.
- Digital PDF evidence is independently re-read from the checksum-verified private original using bounded PyMuPDF parsing. Buyer, reference/date, every line identity/unit/quantity/rate/discount/HSN/taxable amount, tax treatment, tax amounts, round-off and total must match. Large raster/scanned pages, including scans with text layers, remain reviewed.
- Existing exact master/approved alias validation, tax compiler, local/native duplicate guard, durable outbox and connector reconciliation remain mandatory.
- PostgreSQL locks and durable daily reservations prevent concurrent overbooking. India-time daily budgets survive restarts and policy edits. Reservations remain consumed for failed/cancelled/uncertain entries; this deliberately conservative behavior prevents limit recycling. Previous-day queued actions require review.
- Worker and helper-claim checks revalidate current policy revision/mode, owner permissions, source and master bindings before automatic dispatch. Pause during read-only validation prevents posting. Once a write has been dispatched it must be reconciled; pause cannot undo that write.
- Background ARQ automation sweep processes new source drafts; revision/policy decision filtering avoids repeated work starving later bills. Explicit saved-bill evaluation supports retry after a corrected environment. Uncertain/previous actions never get blind automatic resends.
- Bills UI includes policy controls, emergency pause available during evaluation, saved decision history and correct verified status after reload. Dirty unsaved bills cannot be evaluated.

## Integration fixes found during acceptance

- Non-GST previews now preserve original invoice evidence rather than dropping the stated total and line evidence.
- Helper result publication uses PostgreSQL `FOR NO KEY UPDATE`, retaining credential/revocation serialization while avoiding a deadlock against the uncommitted preview's organization FK `KEY SHARE` lock. Initial live attempts timed out safely without posting; the corrected read/result flow completed successfully.
- The dedicated Tally worker now shares the existing document-capable app image and uses the internal private MinIO endpoint. Its real private-original source gate passed independently.

## Validation

- **18 Day 8 backend tests passed**, including concurrent budgets, shadow/no approval, missing limits, policy pause during native validation, revoked permission, changed master, duplicate/ambiguous input, previous-day reservation, uncertain reconciliation, worker sweep, helper claim after pause, helper result lock compatibility, original checksum/buyer checks and scanned PDF rejection. Report: `data/day8-tests.txt`.
- **75 existing regression tests passed** across memory, bridge compatibility, review/bulk approval, drafts, multi-item/GST/native exports, extraction/OCR and upload deduplication. Report: `data/day8-regressions.txt`.
- **5 JavaScript UI suites passed**, including `scripts/test_purchase_automation_ui.cjs` and existing drafts/GST/review/memory suites.
- Live native auto-post verified one voucher; policy paused. Browser reload preserved the verified bill, decision history, limits and daily usage.
- Existing test infrastructure emits SQLAlchemy/psycopg connection cleanup ResourceWarnings and an Element truth-value deprecation warning; suites completed successfully.

## Boundaries

This is controlled **test-company** automation on the supported purchase workflow, not unrestricted production-company posting. Photos, scans, handwriting, unsupported layouts/tax treatments and ambiguous/missing evidence remain reviewed. One successful dummy PDF is not a claim of universal extraction accuracy. No new OCR provider, subscription, vector database or frontend framework was added.

Migration: `x0q7r8s9t0u1_purchase_automation.py` (additive policy, policy-event, decision and reservation tables). Existing PostgreSQL/MinIO volumes and connector pairing were preserved.
