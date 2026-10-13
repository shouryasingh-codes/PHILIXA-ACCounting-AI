# Day 4 — durable invoice extraction and review

Updated 2026-10-12 after bug review and fixes.

## Behaviour

- Upload PDF/JPG/PNG in **Upload bills · originals**. File validation finishes first.
- **Extract & review draft** requests a durable background extraction; the HTTP response is 202 with queued status.
- The documents panel polls queued/processing extraction. Reloading retains database state. Once finished, **Review extracted draft** opens the editable draft alongside authenticated source pages.
- Repeat clicks reuse the same extraction/drafts, preserving edits; requests and draft creation serialize on the source document row.
- Vision processes all uploaded pages (up to 20), with correct JPEG/PNG MIME types, structured JSON response schema and a 100-line bound. PDF parsing/rendering runs in bounded subprocesses.
- Digital PDF embedded-text parsing is a limited fallback with an explicit review warning and no claimed AI confidence. Photos/scanned PDFs require a working configured vision provider. Unavailable OCR produces a visible retryable error, never invented invoice details.
- Missing/negative/invalid quantities and rates remain unresolved with raw evidence. Unknown units remain blank. Fuzzy/normalized supplier and item names are suggestions; only exact matches auto-resolve masters.
- Missing/low confidence highlights review fields; confidence is model-reported, not measured accounting accuracy.
- Split uses cached extraction and explicit non-overlapping invoice page groups. Continuation pages never become invented invoices. Original combined multi-invoice drafts cannot create a posting preview; split drafts have their own header evidence.
- Extraction creates editable, unposted drafts. Tally writes still require a separate preview and explicit confirmation.

## Technology and recovery

FastAPI, Pydantic, SQLAlchemy/PostgreSQL, Alembic, existing ARQ/Redis document worker, private MinIO originals, PyMuPDF/Pillow, existing Gemini HTTP provider helper, HTML/CSS/JavaScript.

Migrations: `t6m3n4o5p6q7` (document/draft linkage), then `u7n4o5p6q7r8` (durable extraction fields).

PostgreSQL stores extraction status, cached raw result, safe error, attempt/generation counters, requested split mode and a fenced 360-second lease. Worker timeout is 300 seconds. Startup and minute recovery scans wake pending/stale jobs; transient interruptions have bounded retries. Stale workers cannot overwrite new leases. Current workspace membership and enabled company are checked by the worker.

## Interfaces

- POST `/api/v1/business/documents/{id}/extract`: 202 queued/processing or existing draft references.
- POST `/api/v1/business/documents/{id}/split`: 202 split job or existing split draft references.
- GET `/api/v1/business/documents/{id}`: validation/extraction state and safe extraction error.
- GET `/api/v1/business/documents/{id}/drafts`: durable linked drafts.

Original file size/page/batch limits and private authenticated viewer remain unchanged.

## Verification

Tests cover blank photos, signed numbers, missing units/confidence, ambiguous master names, malformed provider responses, all 20 pages, JPEG MIME/schema, duplicate requests/drafts, source splitting, queued state after reload, interrupted and stale workers, visible errors/retry, zero extraction-created Tally actions, and a real ARQ worker processing cached synthetic extraction without paid provider calls.

UI suites cover documents upload/reload/polling/review, side-by-side source navigation, draft revisions/approval safety and chat refresh.

Live Gemini recognition accuracy on real accountant bills remains unmeasured. Tests use synthetic files and mocked provider responses; these checks do not establish real-bill accuracy or production readiness.

Verified combined regression suite: **168 tests passed**. Four Node UI suites passed. Local Alembic is at `u7n4o5p6q7r8` head.

## Simple manual check

1. Ctrl+Shift+R in Philixa.
2. Upload a readable bill PDF/photo and wait for file check.
3. Click **Extract & review draft**; wait for **Review extracted draft**.
4. Open it, compare every value to the original, edit and save.
5. Reload and reopen: the same edited draft should remain. An OCR error should show a clear retry message rather than dummy values.
