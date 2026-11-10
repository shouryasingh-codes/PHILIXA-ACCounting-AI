# Borderless PDF extraction recovery — 6 November 2026

The failed `itemInvoiceDownload-2.pdf` was reprocessed using Philixa's normal chat Retry → durable worker → extraction → split-draft pipeline. No invoice values were manually inserted into drafts.

## Cause and implementation

- The PDF contains readable embedded text and two invoice identities. Default ruled-table detection found no table. A direct PyMuPDF text-strategy experiment also produced shifted/merged columns, so its raw cells were not accepted blindly.
- Added a general header-anchored embedded-table adapter for quantity, gross, discount, charges, taxable value, tax heads and total. It uses word positions and source labels, checks row arithmetic and column totals, and abstains on missing/ambiguous headers, inconsistent amounts or an unsupported page. Runtime code contains no target filename, supplier, invoice reference or target amount.
- Base units and pre-tax rates remain unknown when not explicitly printed; tax-inclusive gross/discount values remain source evidence, not invented purchase rates. Unsupported service/tax-inclusive treatments block posting.
- Supported local layout results bypass external vision calls. Existing OCR/provider configuration and budgets were preserved.
- Added revisioned, idempotent explicit attachment retry. Error-only results no longer tell users to open a nonexistent review draft.
- Split review opens the draft's own source page. Unsupported treatments and source tax evidence remain visible/preserved through editing; unresolved source tax cannot silently become a non-GST posting.

## Observed acceptance

Browser Retry produced exactly two app-created drafts:

- Source page 1: invoice `I3626BU000060408`, 2 goods rows, original total ₹662.00.
- Source page 2: invoice `I2926MY127634989`, 1 platform-fee row, original total ₹23.00.

Both survived reload. Review opened the exact invoice; second invoice opened source page 2. Source company validation rejected previews for both because the bill buyer differs from Philixa Test. Both action links remained empty; the action count increased by zero.

Read-only verification: `python -m scripts.verify_failed_pdf_recovery`.

56 backend tests passed across layout, chat attachments, extraction, drafts and GST. UI suites for source review, draft save/preview, GST fields and chat attachments passed, including source-page selection and unsupported-treatment display.

## Limits

This is a tested supported layout class, not universal document understanding or broad real-world OCR accuracy. Scans, unknown header arrangements, continuation pages and ambiguous invoice boundaries may still require another supported reader/manual review. No Docling/PaddleOCR installation or paid fallback was added. These extracted drafts are not posting-ready.
