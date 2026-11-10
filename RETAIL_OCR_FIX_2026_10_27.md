# Public retail GST PNG extraction fix — 2026-10-27

## Diagnosis and choice

Original public sample: `data/ocr-public-samples/sahibill-gst-sample.png`, downloaded unchanged from SahiBill. Raw RapidOCR output is `data/ocr-public-samples/sahibill-tokens.json`.

OCR read the bill; the parser rejected its layout. The legacy reader required specific description, taxable and unit headers. This source uses Item / HSN / Qty / Rate / GST / Amount, combined quantity+unit, tax percentages on a second line, tax-inclusive line Amount, and a separate HSN tax summary.

Chosen first step: keep RapidOCR and add a conservative separate retail-summary reader. Advantages: no new model/runtime or paid provider, traceable coordinates, existing extraction/job/validation reuse. Limitations: this is a supported-layout extension, not general table understanding. It requires a complete unambiguous HSN summary; repeated HSN allocation, missing cells and inconsistent arithmetic fail for review. Other invoice families may still require a structure model such as PP-StructureV3/Docling after a measured comparison.

## Implementation

- `app/services/local_retail_invoice.py`: spatial column/row grouping, strict unique source cells, explicit combined quantity/unit parsing, separate printed tax-inclusive and taxable evidence, per-line HSN-summary/tax/quantity-rate cross-checks with Decimal, payable total/round-off verification, supplier/buyer/reference/date source reading.
- `app/services/local_invoice_ocr.py`: routes explicit Item + Tax Summary layouts to the separate reader. Existing legacy parser unchanged.
- Source tokens, original coordinates, low-confidence evidence, invalid GSTIN warning, pagination checks, existing review/policy/company/master gates retained. No source field hardcoded to this merchant or invoice.
- Restarted only document-worker to load Python code. No schema/configuration changes, paid provider or Tally write.

## Validation

40 tests passed:

`python -m unittest scripts.test_local_retail_invoice scripts.test_local_invoice_ocr scripts.test_extraction_evidence_fixes scripts.test_uploaded_invoice_regression scripts.test_invoice_extraction scripts.test_invoice_ai_limits`

Initial broader run overlapped the live OCR job and three concurrency-sensitive tests saw the single extraction slot busy. Rerun after the live job finished passed all 40; concurrency guard was not changed. Existing unclosed test DB connection ResourceWarnings remain.

Retail regressions include missing/changed quantity, rate, tax, tax summary, line, round-off, total, duplicated HSN, alternate supplier/reference/date. Existing legacy fixtures and extraction budget tests passed.

## Actual app acceptance

Using the authorized in-app browser, retried the exact already-uploaded failed PNG. Real ARQ document-worker local OCR completed in about 12.8 seconds. Opened review, reloaded browser, reopened uploaded document and review.

- Supplier Sharma Kirana Store; buyer Gupta General Store; INV-4; invoice date 2026-10-07.
- Four original lines: 6 PCS ×165; 6 PCS ×158; 3 PCS ×260; 2 BOX ×240.
- Printed taxable lines 990 / 948 / 780 / 480, total 3198.00.
- GST rates 5 / 5 / 5 / 18; CGST 111.15; SGST 111.15.
- Explicit round-off -0.30; invoice and calculated total 3420.00.
- Original source viewer and draft available after reload; status needs_attention / needs_review.
- Invalid sample GSTIN and missing Tally supplier/items correctly remain review warnings. This is extraction success, not a posting-ready bill.
- No preview/approval/post button pressed; no Tally voucher created.

Screenshot: `output/retail-ocr-fixed.png`.

Not established: accuracy across other layouts/phone photos/blurred scans; Jaipur friend's original file still unavailable. No overall accuracy percentage or real-world automation readiness claim.
