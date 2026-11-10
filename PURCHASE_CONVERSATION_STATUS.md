# Purchase conversation — 2026-10-28

Implemented the first deterministic, revisioned missing-details purchase workflow. No model training or new paid provider was required. This is a constrained purchase assistant, not a general autonomous accountant.

## Behavior

- GST chat working copies now ask the next missing detail directly in chat instead of requiring the form. Non-GST partial purchases with an approved read company also use this flow; already-complete legacy non-GST previews are retained.
- Exact supplier choices require user selection; fuzzy suggestions never decide an identity. Known quantity/rate values are retained. Exact item unit and available dated supplier GSTIN / effective HSN / GST rate are proposed from scoped saved masters; original bill verification remains required.
- Each answer is saved in the PostgreSQL draft with existing revision protection and audit events. Master proposals have a distinct system:masters / master_suggested audit event, not a fabricated human correction.
- Browser sends answers to a scoped draft endpoint with expected revision and question key. Stale answers refresh the question without replaying the mutation. Reload restores question context from the saved conversation; accounting data remains in PostgreSQL. Separate chats have separate working-copy seeds.
- New stock/report/purchase topics leave the active answer flow. Narrative task instructions cannot become invoice references. Invalid numeric/tax/date answers do not overwrite the current draft.
- Invoice reference/date, printed taxable amounts, tax breakup and final total remain evidence fields, not guesses. Explicit adjustment confirmation is bound to adjustment content. Full summary and explicit review precede the existing validated preview. Normal human posting approval remains separate.
- Bill photo/PDF upload opens the existing private intake/OCR flow. An extracted draft can use Continue in chat; populated fields are reused. It is not automatically merged into an unrelated chat draft.
- Detailed review remains a fallback for corrections, discounts/round-off edits, missing company tax setup and unsupported layouts/cases. Only the latest question's controls remain visible to reduce clutter.

## Verification

- 56 Python conversation/chat/GST/sync regression tests passed; final focused 11 tests also passed after strict invoice/date parsing and source-warning changes.
- Chat persistence/routing, connector rendering, purchase drafts and GST UI harnesses passed. Coverage includes scope/role isolation, stale replies, invalid answers, persisted answers, exact supplier selection, master suggestions, pause/resume, new-topic switching, no blind replay, per-chat isolation and unchanged disabled GST approval gates.
- Browser: continued the prior unposted test draft, selected Sharma Traders, answered 50 bags and 350, then received the invoice-number question. Reload restored the same progress without reasking supplier/quantity/rate. No invoice number/date invented; no preview confirmed or Tally voucher posted.
- Screenshot output/purchase-conversation-verified.png.

## Limits

This is supported purchase field collection and validation, not unrestricted multi-task reasoning. It does not guarantee all bill layouts, automate tax judgments, create masters or authorize real-company posting. Complex corrections use detailed review. Real accountant time savings and broad real-world accuracy remain unverified. Chat active handling time is not yet measured by the form review timer.
