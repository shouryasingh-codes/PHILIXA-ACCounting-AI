# Purchase task card — 3 November 2026

Task-driven purchase controls now share one panel. Supplier/history/rate choices, grouped correction input, collapsed extras and final preview stay within the panel. Manual refresh/status buttons are omitted from this task panel; server context scheduling and GET-only task polling remain responsible for progress.

Card actions update the same assistant record rather than appending a user/assistant bubble pair. They retain task ID, revision, server-issued selection references and request idempotency. The exact input remains in server task audit even when the display does not append a chat bubble. Ordinary chat and legacy purchase behaviour are preserved. Approval result updates the same task card; this change does not authorise or perform posting.

The grouped field accepts actual missing facts/corrections in one message. Unknown-details acknowledgement remains visible; it does not repeatedly ask the same fields. Missing invoice/date/tax facts are not fabricated.

Validation: connector/proposal UI tests pass including one-panel nesting, inline grouped input and no manual status buttons. Chat restore tests pass including selection updates without extra bubbles and same task/reference payload. Backend lifecycle checks run separately. In-app browser returned `browser.user is unavailable`, so current visual layout and screenshot acceptance remain unverified. No Tally posting was performed.
