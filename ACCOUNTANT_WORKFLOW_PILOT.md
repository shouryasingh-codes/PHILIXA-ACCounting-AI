# Accountant-style workflow pilot — 24 October 2026

This is agent-operated QA using a researched junior-accountant workflow. It is not a human accountant study, a salary-wide survey, an unseen-invoice benchmark or a measured manual-time comparison. The unchanged invoice had already been used to repair the parser, so it cannot be counted as held-out evidence.

## Research basis

A current employer listing for Junior Accountant / Accounts Executive offers INR15,000–20,000/month and lists Tally entries, accounts payable/receivable, BRS and GST/TDS assistance: https://in.indeed.com/viewjob?jk=c0d674ffea7ae676 . This is one role example, not proof of a national pay norm. Villgro's employer-authored Accounts Executive JD independently lists Tally entries/supporting vouchers, purchase/sale/receipts, bank and ledger reconciliation, month-end reporting and statutory assistance: https://villgro.org/wp-content/uploads/2024/07/Accounts-Executive-JD-2024.docx.pdf . Employer, industry and seniority change the exact workload.

Official Tally purchase workflow: supplier invoice number/date, correct party and company registration, item quantity/rate and tax-ledger selection: https://help.tallysolutions.com/gst-purchases-tally/ . Invoice-level dues require bill-wise tracking and native receivables/payables reports: https://help.tallysolutions.com/manage-receivables-outstanding-tally/ . Tally itself supports these reporting/banking features; their existence is not Philixa differentiation.

## Fresh live acceptance

1. Reviewed extracted PX/26-27/1023 against its unchanged original. No field values retyped. Company Philixa Test, local test supplier, date02-Oct-2026, two lines: 12 bags at125 with5% discount;8 bags at87.50 with0%. Taxable2125, CGST145.75, SGST145.75, round-off+0.50, gross payable2417. Existing original and draft reopened after reload.
2. Native before-read confirmed zero vouchers with this reference; stocks122 and13 bags. Browser created a preview and one explicit confirmation. Result: native Purchase voucher21, exact reference/date/supplier/items/quantity/rate/discount/tax ledgers/total. Existing strict payload verifier passes native export. Stocks134 and21 bags respectively; Cement unchanged25. No real-company posting or actual payment occurred.
3. Renamed identical file reupload through browser returned 0 new /1 already saved. Native reread still exactly one voucher with this reference. No second confirmation or resend used.
4. Live Purchase Register for02-Oct-2026 returned monthly summary gross16867.20. Independently summed active native purchase party gross, excluding cancelled/optional vouchers:16 vouchers,16867.20. This is gross including tax/rounding, not taxable purchase-ledger total14615.00. Initial wrong-basis diagnostic comparison was corrected without altering app data. Monthly summary lacks individual invoice rows; it is insufficient alone for accountant invoice tracing.

Evidence: data/accountant-pilot/before.json, after.json, report-check.json, disabled-workflows.json; browser screenshots output/pdf/accountant-repeat-upload.png and accountant-voucher21-verified.png. No paid AI API was used during this pilot.

## Current gaps and limits

Read-only gate probes of get_bills_receivable, get_bills_payable, get_sales_register and get_receipts_and_payments all return capability disabled: only Purchase Register is enabled. Browser report selector shows the same restricted scope. These tests establish deployment availability, not a failure of native Tally. Broader report contracts exist in code; rollout was not enabled to manufacture a pass. Existing simple sales paths should not be conflated with a complete GST/multi-item sales and collection workflow.

Bank statement ingestion/classification/reconciliation, GST/TDS filing, payroll and accountant month-end completeness were not implemented/exercised by this pilot. CRM follow-ups are not invoice-level outstanding reconciliation. Native supplier bill allocation on voucher21 currently uses an internal GUID as New Ref rather than the printed supplier invoice reference; an accountant-facing invoice/outstanding matching workflow needs separate acceptance. No claim is made that this allocation is an incorrect native posting, but it is a usability/traceability gap to assess.

Only the supported reviewed purchase slice passes here. Human review time, manual Tally baseline, correction time on unseen real bills, real/photo variation and the50% handling-time target remain unmeasured. No claim of replacing a INR20,000/month accountant,100% accuracy or production readiness follows. Next useful evaluation: an accountant reviews authorised representative unseen bills and records active manual versus Philixa handling time and corrections. Do not add unrelated features merely to increase feature count.
