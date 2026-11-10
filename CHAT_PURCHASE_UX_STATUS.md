# Chat purchase review simplification — 2026-10-28

Chat-origin editable drafts now default to a compact two-step screen, rather than the full accountant batch workspace.

1. Supplier and item / quantity / unit / rate only. Existing values remain populated. Next checks missing/invalid basic fields without saving or posting.
2. Invoice/date and GST evidence, expected tax amounts and the existing validated preview workflow. Optional empty discount/round-off/configuration fields are available through Full view; populated financial adjustments are not hidden as optional. Tax ledger setup remains accessible on the tax step.

Compact mode hides batch toolbar, draft navigation and automation controls, and displays item inputs in two columns. Full view restores the existing accountant workspace. Underlying values and backend validation/approval behavior are retained. No tax data inferred and no posting authorization added.

Missing GST evidence is shown as pending rather than a misleading zero-tax final total. Existing documents and non-chat drafts retain their normal full review UI.

Validation: purchase-draft and GST JS harnesses passed. Added compact-mode default, missing details, forward/back navigation, Full view, no requests from navigation, and missing-tax pending-total checks. Browser verified compact step 1, missing-details block, populated test fields -> step 2, and reload restoring original saved values. Temporary test inputs were not saved. No Tally action approved or posted. Screenshot: output/chat-purchase-simple.png.

This reduces screen clutter, not all manual invoice work. Bill extraction improvements and a full missing-details conversational workflow remain separate work; no accountant time-saving claim has been measured here.
