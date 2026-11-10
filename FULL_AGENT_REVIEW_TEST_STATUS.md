# Dummy purchase review acceptance — 3 November 2026

Result: backend live review acceptance passed after repairs. Fresh browser visual acceptance and native posting remain unverified; no posting was authorised or performed.

## Cause and fix

The native manifest reported `Discounted historical line needs review.` That correctly prevents an automatic historical-rate suggestion, but previously also blocked a new purchase whose rate was explicitly supplied by the user.

Current rates with exact user-message provenance can now use fresh native master context without relying on historical prices. History is explicitly marked `not_required`, never falsely marked as a complete historical read. Missing/unproven rates retain the original history checks. Full-financial-year duplicate checks, current tax/total compilation, permissions and native master freshness remain required. Preview actions bind the explicit-rate company/device/master evidence; changed evidence is rejected.

## Live evidence

- Synthetic task: `d94b180a6c040038635f6d9158c750ca`.
- Same saved draft: `e8b7b476cb30f71efc5017243137feff`.
- One original facts message supplied supplier, unique invoice/date, item, 1 bag × ₹100, 18% GST, CGST ₹9, SGST ₹9 and ₹118 total.
- All those fields independently compared successfully after persistence.
- After repair the same draft was resumed with an instruction to show final review; no transaction facts were re-entered. Final state `needs_approval`, preview present, issues empty. Two total model calls across creation and resumption.
- A separate process/database session reopened the same draft, preview token and action identity.
- This is not a clean first-attempt one-message end-to-end pass: the repair required a resume instruction. The report preserves this distinction (`single_user_message=false`).
- No approval, queue dispatch for posting, native voucher creation or deletion occurred.

## Tests

31 agent-tool, purchase-agent and GST tests passed. Additional explicit-rate action-guard test passed after asserting changed master evidence is rejected. Some test shutdowns still emit async-connection ResourceWarnings; these do not indicate functional assertion failures but remain a cleanup concern.

Reproduce read-only report: `docker compose exec -T app python -m scripts.full_agent_review_acceptance`.
Evidence: `data/full-agent-review-acceptance.json`; earlier failed synthetic attempt preserved separately.

In-app browser control was unavailable during this run, so browser reload/screenshots were not claimed as passed. No broad accuracy or accountant time-saving claim follows from this fixture.
