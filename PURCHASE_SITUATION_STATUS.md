# Situation-aware purchase agent — 3 November 2026

Existing LangGraph/Groq/Pydantic tool loop now routes supported purchase situations through a grounded intake adapter. New typed tool `record_purchase_situation` reads an original indexed user message; the model cannot supply ungrounded receipt flags/dates. Create/update tools capture supported explicit situation facts from that same source.

Bill pending and goods received must both be explicit before goods-receipt workflow begins. Buying alone proves neither. Exact supplier/item, confirmed quantity/unit/rate are still required. Received date and rate basis are collected together; explicit source facts already supplied are reused. Existing invoice/source cannot silently switch to receipt. Goods explicitly not received block stock-increasing purchase/receipt preview. Unsupported/ambiguous wording requires clarification.

The recognizer supports a bounded set of Hinglish/English/Hindi phrases, not arbitrary-language understanding. Conditional and conflicting statements are not accepted as confirmed facts. Future dates, guessed tax credit, invoice references and historical rates are not invented. Receipt preview preserves existing company, connector, certification, approval and journal gates. Real writes remain disabled unless separately authorised and supported.

UI keeps situation choices, grouped correction input and receipt-review action in the existing task card. Invoice tools retain original tax and duplicate validation.

## Verified live review

Task `14b6940e49469d4e632cd083da1f9547`, draft `e63bc6e8987914109e03273450e90ede`: one synthetic message explicitly gave supplier/item, 1 bag at ₹100 before GST, goods received, bill pending and received date 02-Oct-2026.

Actual model-selected trajectory: `create_purchase_draft` → `receipt_preview`; two AI calls, no additional questions. State `needs_approval`; saved metadata/date/basis reopened correctly. No invoice was invented. The resulting preview correctly disallows confirmation because installed connector lacks protocol 11. No Tally voucher was posted; this is review/routing acceptance, not native posting acceptance.

Evidence: `data/live-situation-acceptance.json`; reproduce read-only inspection with `python -m scripts.live_situation_acceptance` inside the app container.

Automated agent/routing/schema suite: 38 passed. Final worker/routing/tool subset passes separately; counts overlap. UI chat and connector/proposal checks passed. Browser visual acceptance is not claimed in this run. Broader representative accountant evaluation and arbitrary language coverage remain unverified.
