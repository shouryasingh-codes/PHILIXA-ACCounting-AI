# Browser acceptance — 25 October 2026

Executed in the agent's in-app browser, authenticated INDIVIDUAL workspace, Philixa Test company. Synthetic sources only. Existing posted test invoices were not reposted.

- Reload restored all seven pre-existing saved drafts and conversations. Connection eventually reported Live available; initial badge had shown unreachable before refresh.
- Uploaded frozen C01.pdf (QA26-001). Extracted original and draft survived reload. Supplier/item, 2 October 2026, 5 bags at INR100, taxable500, CGST45, SGST45 and total590 matched the frozen manifest. Saved tax check matched. Preview showed the correct company and tax ledgers.
- Confirmed this new dummy purchase once. It progressed from queued to verified. Native Tally read confirms exactly one active Purchase with reference QA26-001, voucher22. Preserve it; do not blindly resend. Evidence: data/accountant-pack/browser-native-proof.json and browser-native-count.json.
- Uploaded C10-resend.pdf, identical C01 bytes under another name. UI returned 0 new files / 1 already saved; no second document appeared.
- Existing test-bill.pdf has buyer Sharma Construction and selected company Philixa Test. Create Tally preview returned company mismatch / No posting created, without a confirmation control.
- Uploaded frozen C06.jpg (mild tilt), extracted through the app. QA26-006, supplier Local, Goods18, 6 bags at100, taxable600, GST18, HSN2523, CGST54/SGST54, invoice date2 October and total708 matched. Kept as an unposted review draft.
- Deliberately changed only the dummy photo draft rate to101 and saved revision1. Saved tax validation rejected it: Line1 invoice taxable amount mismatch/missing. Restored rate100, saved revision2, reloaded/reopened. Correct value persisted and saved tax validation returned708.

Found/fixed a misleading document status: an older completed extraction in a batch could cause a newly queued document to show Extraction complete. Status now follows the selected document id. A regression reproduces mixed old-ready/new-queued documents and passes after the fix. Browser JPEG check showed queued/processing first, then complete/review only after actual completion. Documents asset version advanced5 to6. Controller suite scripts/test_bill_documents_ui.cjs passed. No background service restart was needed for this static asset change.

Evidence screenshot: output/pdf/accountant-v1/browser-photo-reviewed.png. Test environment now has nine saved drafts (five verified/four attention). Review warnings are not erased by testing. All-ten browser scenarios, new PNG browser extraction, cross-workspace attacks and real accountant handling-time validation were not performed in this round. Prior offline synthetic results remain separate evidence, not a fresh browser claim. No real-company entries, payments, cloud provider configuration changes or new paid subscriptions were made.
