# Original public invoice test bundle

## Use this file

`timenet-philixa-test.pdf` is the recommended upload: one page, about 0.77 MB.
It is an edited scan of an actually issued invoice, NOT a newly generated dummy invoice.
The earlier `original-invoice-adapted-for-philixa-test.pdf` is a research candidate with an unpriced bundled monitor row. Do not use that earlier candidate as the successful-posting acceptance case.

## Provenance and changes

Public source: https://www.sctce.ac.in/uploads/c2/4.3.2%20Computers%20Purchased%20Bill.pdf

The immutable full download is `sctce-original.pdf`; `timenet-original-page10.pdf` is the original invoice page extracted without changing its content.
`timenet-test-manifest.json` records hashes, all changes, manually transcribed expected values and limitations.

The adapted copy changes the buyer to existing Philixa Test / Haryana / test GST registration, invoice date to 02-Nov-2026 and Net30 due date to 02-Dec-2026. Original Kerala CGST + SGST become interstate IGST because the test buyer is in Haryana. Taxable value, overall tax and grand total do not change. A visible test-only notice distinguishes the copy from the issued invoice.

Supplier, original invoice reference, all six original goods/descriptions/HSNs, quantities (12 No each), rates and amounts remain source data. Original stamps and historical purchase-order references remain visible for fidelity; they are NOT approval or evidence of a new transaction. The original low contrast has not been cleaned into an artificially easy invoice.

This is an ADAPTED-COPY workflow test. Do not count its changed tax treatment as an untouched-original regulatory accuracy test. Source HSNs are reproduced, not independently certified classifications. Do not use the copy for real accounts, payment, tax filing or ITC.

## Before a Tally posting test

1. Confirm exact native Philixa Test identity, current permissions and test GST registration. The preparation used the existing snapshot: Haryana, 06ABCPE1234F1ZF. Do not use a real company.
2. Confirm original TIMENET SOLUTIONS PVT LTD supplier (GSTIN 32AACCT0612L1ZP), six original goods and the No unit exist. Do not substitute the unrelated synthetic supplier/items already in the company.
3. `timenet-test-masters-PREPARED-NOT-IMPORTED.xml` describes missing-master setup for this exact company: one unit, one supplier and six goods; no voucher and no opening stock/balance. It has NOT been imported or native-validated. Inspect existing masters first; do not repeatedly import or overwrite existing records.
4. Existing configured purchase/input IGST ledgers and godown must resolve through normal Philixa validation. The test copy's date must be accepted by the running Tally instance; do not change an approved date silently.

## Test with Philixa itself

Upload the adapted PDF through chat. Let the normal extraction worker create the draft. The manifest is a comparison checklist only: do NOT manually feed it into the extraction result and claim the AI read the invoice.

Compare supplier, buyer, reference/date and every row. Expected totals: taxable 326100.00; IGST 58698.00; grand total 384798.00; no discount or round-off. The six original rates are 9950 / 4900 / 1325 / 2050 / 1350 / 7600, each quantity 12.

Resolve genuine extraction errors or missing masters through normal review. Missing source data or master ambiguity must block posting; do not invent values. After preview/review and authorised confirmation, compare the actual native voucher and all six stock changes. An uncertain result must reconcile the same action, never blind resend.

## What has actually been verified

- Source/full-download and excerpt hashes; original source retained.
- Adapted PDF renders legibly, has one page and fits the 10 MB / 20-page upload limits.
- Changed buyer, dates and IGST text, plus source supplier GSTIN checksum and test GSTIN checksum.
- Every original row quantity x rate; sum of six lines; IGST and grand-total arithmetic.
- Prepared XML targets Philixa Test and contains six stock items, one supplier, one unit and ZERO vouchers.

Philixa OCR/extraction, native master import and actual voucher posting have NOT been verified by this artifact-preparation task. None is being reported as passed.
