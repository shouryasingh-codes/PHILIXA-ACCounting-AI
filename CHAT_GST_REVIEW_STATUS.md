# Chat purchase GST review — 2026-10-28

Chat now routes an explicitly GST-enabled company's purchase into the existing Bills GST review workflow, instead of passing it to the legacy non-GST voucher compiler.

Behavior:
- Existing non-GST chat previews remain unchanged.
- Once company/item scope is resolved and test-company configuration is present, GST chat requests create a durable partial purchase draft, preserving available supplier, quantity, unit, rate, invoice reference/date and godown. Unprovided GSTIN, HSN, rate, tax amounts, total and date remain empty.
- Response offers GST purchase review. This opens the existing editable Bills form and its ledger setup, tax validation, revision checks and supported GST preview compiler.
- Same-session repeated identical commands reuse the same unposted chat working copy without overwriting edits (serialized advisory lock). A previously action-linked draft is not overwritten or silently reapproved.
- Explicit GST/tax/discount purchase language is routed to review. Unsupported batch/serial/transfer/sale cases remain blocked; an unclear transaction type still requires clarification. Explicit tax on a non-GST company cannot silently become a no-tax voucher.
- Unknown GST master state blocks routing. Real-company authorization, test-company configuration, helper/profile checks, human approval and acceptance gates are unchanged.
- UI identifies this as a Chat working copy, not an OCR-extracted document.

Validation:
- 60 Python tests passed: scripts.test_chat_gst_purchase, scripts.test_tally, scripts.test_tally_sync, scripts.test_gst_purchase.
- Connector UI, purchase drafts UI and GST UI harnesses passed.
- New tests cover partial fields/no Tally action, repeated requests retaining edits, unknown master status, explicit tax on non-GST, GST language guards, and completing the working copy via the existing GST compiler. Synthetic completed fixture total 1167.00; disabled acceptance still blocks confirmation.
- Browser: sent "Cement purchase karna hai" in a new test conversation, received GST review handoff for Philixa Test, opened the partial GST working copy, reloaded and reopened it successfully. No invoice/tax values invented. No Tally posting or configuration changes.
- Screenshot: output/chat-gst-review.png.

Limits: supported domestic regular-goods GST workflow only. This is a chat-to-reviewed-form integration, not a fully conversational tax-entry agent. No new real Tally voucher was posted to test this change. Complete tax details and existing validation/authorization remain necessary. The generic non-GST compiler's restriction was retained deliberately.
