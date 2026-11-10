# Purchase context — 28 October 2026

Implemented a read-only context collector in the existing revisioned purchase conversation.

- Same permitted company/workspace; source draft must link to a verified action in that company/workspace and remain active.
- Reads up to 100 most recently updated verified drafts, considers transactions within 180 days and never after the target transaction date or today.
- Exact supplier, item and unit only. Repeated item rows, conflicting prices on the latest transaction day, stale/future/nonfinite prices abstain.
- Historical rate appears as an explicitly sourced suggestion and a one-click answer. It never silently fills price, invoice/date, tax or total. Explicit current prices are retained.
- Short saved-draft summary and complete missing-field overview accompany the next question. Structured context is returned to the client for subsequent review work.
- Existing preview, revision, permission, duplicate, tax and posting gates remain in place. No live voucher posted for this change.

Validation: 16 focused Python tests passed (purchase context, conversation, chat GST). Connector UI regression passed. Integration test proves unverified or unbound actions cannot offer rates, and a suggestion leaves price and invoice unset until the user answers.

Remaining: this is the first context layer, **not completion of the proposed autonomous purchase assistant**. History currently covers purchases verified through Philixa, not every native Tally purchase. Masters still use the existing saved snapshot; this change does not implement a fresh native history tool, graph checkpointing, multi-field natural-language corrections, or a consolidated approval card. No new OCR/model API or paid provider was added. Browser acceptance of the new rate suggestion remains pending.
