# Day 6 — accountant review queue and bulk approval

Implementation and scoped acceptance completed 2026-10-15 after the user started Docker.

## Implemented
- Scoped Processing / Needs attention / Ready / Posting / Verified queue; private source documents without drafts are included. Counts are computed before filtering and pagination (50 rows per page).
- Existing source and editable draft remain side by side. Next issue (Alt+N), previous/next bill (Alt+Up/Down); unsaved edits block bill changes.
- Save & validate saves the current revision and runs the existing company, master, arithmetic and GST preview validation again. Saving never approves.
- Ready means an unexpired purchase preview in the current session with its posting acceptance gate enabled. Current connection/profile/device guards run again at approval and live validation remains in the existing worker.
- Select ready bills and approve up to 50 with one action. Every selection includes draft ID, revision and action ID. Each bill has independent commit/rollback and result. Stale/expired/session-mismatched previews cannot approve; repeat requests cannot queue another action.
- Rollback-safe authenticated identity snapshots preserve isolation across failures. Existing uncertain-posting safeguards remain authoritative.
- No schema migration, provider change, Docker data reset or Tally write performed.

## Verified in this session
- Python compilation of new service, routes and test suite.
- Existing draft controller tests: PASS.
- Existing GST controller tests: PASS.
- New review controller tests: PASS (selection revision/action, per-bill outcomes, filtering, corrected values revalidated without approval).

## Acceptance results
- Docker/PostgreSQL regression command: **36 tests PASS** in 46.671 seconds. Two fixture connection ResourceWarnings were emitted; no test failed.
- 50 synthetic bills reviewed across two pages. A changed revision and an expired preview were rejected independently; the remaining 48 approvals queued successfully. Repeated approval queued no duplicate action.
- Corrected quantity reran the existing preview validation and changed the approved amount from 2800.00 to 1050.00. The previous revision/action could not approve.
- Additional focused test using an ORM-backed authenticated Principal: **1 test PASS**; rollback on the first bill did not break the next bill's approval.
- Live authenticated app: all five view options present, existing five drafts persisted after reload; Needs attention filtered three and Verified filtered two. Processing/Ready/Posting currently empty and displayed an empty-state message with approval disabled.
- Live photo original and editable draft displayed together. Next issue focused the low-confidence unit. Alt+Down navigated JPEG to PNG. GST amount inputs remained editable after a fix for overlapping tax/ledger map keys.
- Fixed late filter responses overwriting newer selections, and blocked approval of selected bills with unsaved edits. UI suites passed after these changes.
- Screenshot: data/day6/review-queue.png.
- No existing bill approved again and no real Tally voucher posted during Day 6 acceptance. Bulk dispatch was verified with isolated synthetic DB records; native Tally financial verification continues to use the existing worker/connector.

Command run:

    docker compose exec -T app python -m unittest scripts.test_purchase_review scripts.test_purchase_drafts scripts.test_invoice_extraction scripts.test_local_invoice_ocr

Day 6's stated synthetic-batch acceptance is met. This does not expand the Day 5 OCR supported-format claims or certify an unattended real-accountant pilot.
