# Day 3 — Private document intake

Implemented and verified on 2026-10-12. Day 1/2 purchase workflows remain intact.

## User-visible behaviour

- Sidebar **Upload bills · originals** accepts PDF/JPG/PNG, individually uploaded into company-scoped batches.
- Limits: 10 MiB per file (inclusive), 20 PDF pages, 50 distinct files per batch. Multipart overhead is separately bounded, including requests without Content-Length.
- Reload restores saved batches, sources and status from PostgreSQL. Same file bytes in the same user/workspace/company reuse the existing original, even across batches or under a different filename.
- Status distinguishes uploaded/pending, checking, ready, rejected and processing error. Password-protected, corrupt, unsupported and over-limit files show specific errors.
- Ready files have a private original viewer and authenticated download. PDF pages render as bounded PNG previews; embedded scripts/links are not run by the in-app viewer.
- Uploading, validation, retry and viewing never create/approve/post a Tally action. Bill extraction is Day 4 and remains disabled here.

## Tech used

- FastAPI + Pydantic for authenticated upload/status/viewer routes.
- SQLAlchemy + PostgreSQL + Alembic for batches, originals, batch membership and durable processing leases.
- MinIO dedicated private bucket, default `philixa-bill-originals`; existing audio bucket is not reused. `PHILIXA_DOCUMENTS_BUCKET` overrides the documents bucket; public policies and an audio-bucket collision fail closed.
- ARQ + Redis, isolated `bill:intake` queue and dedicated `document-worker` service. No legacy notification/audio jobs run in this worker.
- PyMuPDF 1.28.2 for PDF validation and preview; Pillow for JPG/PNG checks. Parser runs in a separate subprocess with a 30-second timeout.
- Existing HTML/CSS/JavaScript for batch upload, polling, duplicate notices, source view and page navigation.

Dependencies live in `requirements-documents.txt`. The main Dockerfile includes them for clean deployments. `Dockerfile.documents.dev` adds only document dependencies to the existing cached local application image; this fast path was used here.

## Durable processing and privacy

- PostgreSQL retains queued work if Redis enqueue fails. Worker startup and a once-per-minute recovery scan enqueue due pending work.
- A processing lease lasts 120 seconds; an expired lease can be reclaimed after interruption. Completion checks the lease token so an old worker cannot overwrite a newer attempt.
- Transient failures retry at most three processing attempts, then expose a scoped retry action. Invalid source files are terminally rejected; upload a clean copy.
- Scope includes creator, workspace and approved company. Revoked/disabled company access is rejected. Session/workspace changes clear browser state and revoke viewer blob URLs.
- No public/signed MinIO URLs appear in the API. Original bytes are hash/size checked, and responses use no-store, nosniff and attachment headers.

## Interfaces and migration

- `/api/v1/business/document-batches`: create/list.
- `/document-batches/{id}`: read stored files/status.
- `/document-batches/{id}/documents`: upload one file, HTTP 202.
- `/documents/{id}` and `/documents/{id}/retry`: status/bounded retry.
- `/documents/{id}/original`: authenticated original download.
- `/documents/{id}/pages/{page}`: authenticated PDF page image.
- Tables: `document_batches`, `bill_documents`, `document_batch_items`.
- Migration: `s5l2m3n4o5p6`, applied at head.

## Verification completed

- **151 combined database/integration/regression tests passed**, including 11 document tests and all existing Day 1/2 suites.
- Real PostgreSQL/MinIO checks cover PDF/JPG/PNG, 20/21-page PDFs, password/corrupt PDFs, exact 10 MiB upload, oversized chunked request, 50-file limit, concurrent duplicate uploads, creator/workspace isolation, missing authentication, anonymous MinIO denial, durable restart/lease recovery and bounded retries.
- Three Node suites passed: document UI, multi-item drafts UI and chat refresh.
- Real browser: uploaded a synthetic two-page PDF while document-worker was stopped, reloaded with the pending file intact, started the worker, viewed both pages, reuploaded identical bytes and saw the existing-file notice. Restarted the worker and reloaded/viewed the original again.
- Synthetic browser company, database rows and private MinIO objects cleaned; zero Tally actions and zero AI calls.
- App health HTTP 200. Document worker restored to running state.
- Proof: `screenshots/day3-private-documents-verified.png`.

```powershell
docker compose exec -T app python -m unittest scripts.test_bill_documents scripts.test_business_conversations scripts.test_business_context scripts.test_purchase_drafts scripts.test_multi_purchase scripts.test_multi_purchase_bridge scripts.test_tally_sync scripts.test_tally.XmlTests scripts.test_tally_count scripts.test_business_graph scripts.test_mcp_business scripts.test_tally_reads scripts.test_tally_suppliers -q
docker compose up -d document-worker
```

## Simple manual check

Hard-refresh the app, open Upload bills, choose a company, select a harmless PDF/photo and upload. Wait for File checked, open the original, reload and reopen the batch. Upload the same file again; it should say already saved and keep one source. A sample synthetic PDF is available at `data/day3-upload-test.pdf`.

Day 3 does not read invoice fields or fill item rows automatically. That is the next milestone.
