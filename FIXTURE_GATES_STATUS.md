# Release fixture safety gate — 21 October 2026

The **17 selected assertions across all 9 catalog categories passed**, with no failures, errors or skips. Catalog: `scripts/fixtures/release/manifest.json`. Reproduce with `python -m scripts.run_fixture_gates` inside the app container. Evidence: `data/release-gates/fixtures.json` and `fixtures.log`.

## Covered cases

- Multi-item/mixed tax and discounts: one, twenty and fifty-line fixtures; supported intra/inter-state mixed rates, fixed expected Decimal totals, line/header discounts and disclosed round-off.
- Duplicate PDFs/photos: identical upload bytes reuse the original; different file formats with the same company/supplier/invoice/year cannot bypass the invoice guard. This fixture isolates duplicate logic using known extracted values; clean photo OCR accuracy is measured separately.
- Blurry source: a generated invoice is severely downsampled/blurred, uploaded and processed by actual local OCR through the worker. Failure is visible and creates neither a fabricated draft nor a Tally action.
- Missing pages: printed `Page n of m` / `Page n / m` evidence detects missing, repeated and out-of-order pages. It survives model omission and draft edits and blocks posting. Distinct complete invoices in one PDF can each legitimately be Page 1 of 1; pagination is checked per invoice.
- Two similar suppliers: fuzzy input remains a suggestion; only an explicit exact identity matches.
- Wrong totals: altered totals and contradictory taxable/discount evidence do not compile or post.
- Malicious document instructions: hostile prose embedded in a generated PDF and bogus model approval/status/action/workspace/tool fields cannot authorize dispatch or change tenant/company scope. Only a needs-review draft is created and no Tally action exists.
- Concurrent edits: another DB session changes the draft during snapshot refresh; the stale preview fails while the newer values survive, without a posting action. Revision/audit checks also pass.
- Cross-workspace access: another workspace/user cannot read, edit, audit, preview or retrieve the private source through the scoped service paths.

## Implementation and limits

Added `invoice_source_quality.py`, source-page evidence propagation through deterministic/vision extraction, and a source-evidence check before purchase preview. Automation independently reparses the original and rejects source warnings. Existing drafts are not silently rewritten. No cloud request, real Tally import, email or WhatsApp send was used by these fixtures.

Missing pages cannot be reliably inferred if the original has no pagination or other completeness evidence. The severe-blur fixture is not a universal blur threshold. Malicious-input checks validate application authority boundaries with deterministic/mocked extraction; they do not certify every cloud model against every prompt injection. Real-world accountant accuracy remains unverified.

An added complete-multi-invoice pagination test caught an overly broad batch-level check. It was fixed to evaluate each detected invoice separately. A first new malicious-input assertion incorrectly read a view status from the ORM row; the assertion was corrected without weakening the boundary checks. Initial failing evidence is retained in `data/release-gates/backend-before-final-fix.*`; final runs use stable source fingerprints to reject code changes during test execution.

The broad rerun also exposed an existing customer-helper test race with the live background sync worker: a permitted read-only snapshot job could appear where the fixture expected an empty v5 queue. The fixture now holds the synthetic endpoint's company lock around its bridge assertions. The original v5-denies-customer-write and v6-approved-payload assertions remain unchanged; the full 21-test customer suite passed after isolation. The failing run is retained in `backend-before-customer-isolation.*`.

The unchanged Day 9 golden corpus was also rerun after the final source fix: **166/166 strict fields and 6/6 exact files**, mappings 7/7, accounting 8/8, simulated posting 4/4. This remains a bounded synthetic result.

Final clean broader regression run: **313 backend tests passed**, zero failures/errors/skips and identical before/after source fingerprints. Windows lifecycle 14/14 and JavaScript 11 suites also passed. The 17 catalog assertions overlap the broader suite and must not be added to its count as unique tests.

The malicious-input assertion was subsequently strengthened and passed in a targeted rerun: injected role, permissions, company member grants, automation policy and tool fields cannot alter the authenticated principal, persisted workspace membership, company access list or automation policy. The result remains needs_review with no Tally action. This changed test assertions only, not application code; the 313-test run above precedes this assertion extension.
