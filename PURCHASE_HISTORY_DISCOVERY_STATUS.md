# Purchase history discovery — 2026-11-01

Added a read-only extension to the existing purchase conversation. The full
purchase-agent feature flag remains unchanged/off; posting gates are unchanged.

For a missing supplier, up to three current Sundry Creditors are queried using
the existing protocol-v10, company/device-bound native-history jobs. Every query
must be complete and fresh. Only one supplier may have matching history; a
second supplier with unusable/conflicting prices still prevents inference.
Supplier and suggested rates remain unset until explicit combined confirmation.
Confirmation rechecks fresh evidence and its digest, and the draft revision.
It never fills invoice reference/date, quantity, totals or tax evidence from history.
Explicit rates are retained. Larger supplier lists require explicit selection.

Live read-only acceptance in Philixa Test:

- Interstate test supplier: complete, zero matching Cement lines.
- Local test supplier: complete, zero matching Cement lines.
- Sharma Traders: complete, five native Cement lines; latest matching rate
  INR 350.00/bags on 2026-10-02.
- Existing five-bag draft now renders supplier/rate suggestion and combined
  confirmation in the browser; restored successfully after reload.
- No live suggestion acceptance or voucher posting was performed.

Validation: 35 tests passed across purchase conversation, supplier discovery,
purchase context, purchase agent and v10 bridge isolation. JavaScript syntax
check passed. Synthetic confirmation tests cover stale evidence rejection and
leaving invoice reference/date unset. Native suggestions retain existing
generation/page/hash, current master fingerprint and 15-minute freshness checks.

Screenshot: output/purchase-history-suggestion-20261101.png.

Limitations: this is bounded exact-history assistance, not an autonomous
accountant. No history, multiple suppliers, unsupported units, incomplete reads
or missing stable identities cause abstention. Background reads can require the
history-status button to refresh the same task. Real accountant time savings and
general accounting accuracy remain unmeasured.
