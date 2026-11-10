# Repeat-purchase review — 3 November 2026

Supported flow: current item/quantity → complete matching native history → supplier/rate suggestion and current-quantity subtotal in the existing card → explicit selection → grouped remaining current-transaction facts → authorised final preview/posting pipeline.

History is a suggestion, not proof of the new transaction. Old invoice number/date, tax amounts, quantity and final bill total are never copied. Explicit current prices win. Subtotal is clearly before discount/GST, calculated from current quantities and proposed rates. Ambiguous/incomplete history abstains.

An exact standalone `done`/`haan` can accept a single current server-issued supplier/rate suggestion; ambiguous choices or corrections go through normal understanding. Permission, company identity, master fingerprints, native history, revision and evidence freshness are rechecked. This does not authorise or submit a Tally action. Existing final approval remains required and action/revision bound.

Live synthetic task `74a29c02a06c40e71ea9ca7ca37ee392`, draft `f30c5e5e6a3d4632fc17100f8dfb9411`: one original purchase message produced Sharma Traders, ₹350/bag and ₹1,750 subtotal for 5 Cement bags. One model call total. `done` saved supplier/rate with zero extra model calls. Invoice/date/tax fields stayed blank; no action was created or voucher posted. Reopened draft retains the fields. Known rate is no longer repeated in the remaining bill/receipt question.

23 repeat/selection/situation tests passed (includes imported fixture tests); chat in-place update/status polling and connector/proposal UI checks passed. In-app browser control remained unavailable, so new visual acceptance is not claimed. Evidence: `data/live-repeat-acceptance.json`; read-only inspection: `python -m scripts.live_repeat_acceptance` in the app container.
