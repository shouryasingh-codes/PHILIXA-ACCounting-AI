# Day 7 — business memory and duplicate protection

Implemented and accepted within the supported Bills workflow on 2026-10-15.

## Accountant workflow
- Save the corrected supplier/item and explicitly choose **Remember supplier correction** or **Remember item correction for this company**.
- Opening/saving a draft alone never learns an alias. Every approval checks the current draft revision and exact target master; the original OCR evidence remains preserved.
- Company memory shows approved aliases and flags changed masters. Aliases bind to the company, stable master GUID/master ID and canonical master fingerprint. A changed/deleted/renamed master invalidates reuse and any pending preview binding; the accountant must review and explicitly approve again.
- Exact case/whitespace matching is supported; punctuation, containment and fuzzy matches remain suggestions. No new vector DB, training or provider is added.

## Duplicate guard
- New Bills previews require supplier invoice reference, invoice date/financial-year evidence and an exact supplier master with stable identity.
- Atomic approval reservations use company scope/identity + supplier master identity + normalized invoice reference + Indian April–March financial year. Company-row serialization plus a unique database key prevents competing approvals of the same invoice.
- Source SHA-256 and overlapping source pages prevent the same original being reposted by editing its reference. Different invoice page groups in a supported split document remain independent.
- The earlier duplicate draft/approved/posted invoice blocks another draft. Renaming/reuploading identical bytes reuses the private original; PNG/JPG/PDF copies with different hashes are also checked by supplier/reference/year.
- Tally's existing vouchers are read for the full financial year before a new Bills preview and again before native posting. Existing standard Purchase references block duplicates; matching references in other voucher types or missing reference/year evidence require manual review. Cancelled/optional vouchers are excluded.
- Legacy/multi invoices write the guarded invoice reference and verify it on reconciliation. An uncertain native outcome is never blindly resent.
- Existing legacy chat actions retain their previous contract; Day 7 protection applies to newly created Bills previews, not retroactive reconstruction of missing references in old chat actions.

## Implementation and deployment
- Added PostgreSQL `purchase_aliases` and `purchase_invoice_claims`, Alembic revision `w9p6q7r8s9t0`. Existing data/volumes preserved.
- FastAPI company memory/correction endpoints; immutable draft audit event records actor, source, target, master identity/fingerprint and selected line.
- Existing extraction/review stack reused. Worker processes restarted to load the new extraction and dispatch code.
- Connector **3.6.0 / protocol 9** built and installed, preserving pairing and startup registration. Guarded jobs use a separate v9 Redis queue; old v7/v8 helpers cannot receive them. Existing unguarded legacy operations retain their compatible queues.
- Released download now prefers the tested 3.6.0 package.

## Acceptance evidence
- **75 backend tests PASS**, 91.478 seconds: `data/day7/final-tests.txt`. Includes actual persisted next-draft alias reuse, company isolation, changed-master invalidation, missing references/years, FY boundary, duplicate reservation, renamed source reuse, real validator synthetic legacy/multi/GST post+reconcile, protocol isolation and the Day 6 50-bill batch.
- **4 UI controller suites PASS**: durable drafts, GST fields, review queue, explicit alias actions. Remembering corrections never approves/posts a bill.
- Packaged helper synthetic duplicate/FY smoke test PASS: `data/day7/helper-self-test.json`.
- Final installed connector authenticated through its existing pairing and returned `duplicate` for PHILIXA-UPLOAD-TEST-01 from actual Philixa Test purchases, via protocol 9. App also blocked the JPEG copy of the already-verified PDF. Evidence: `data/day7/live-native-duplicate-proof.json`.
- Live browser showed the duplicate blocker and **zero confirmation buttons**. Existing JPEG draft stayed revision 1 with no action linked. Screenshot: `data/day7/duplicate-block.png`.
- **No new real Tally voucher was posted during Day 7 acceptance.** Existing dummy purchase was read only; synthetic test imports used fake transports.
- Tests still emit existing SQLAlchemy/psycopg fixture connection ResourceWarnings and an Element truth-value DeprecationWarning; no test failed.

## Limits
This completes the stated Day 7 gates for the supported Bills workflow. It does not certify universal OCR accuracy, custom voucher posting, tax filing correctness or unattended production use. Missing/uncertain evidence remains blocked for accountant review. Full-year native exports over the connector's existing size/timeout limits fail closed.
