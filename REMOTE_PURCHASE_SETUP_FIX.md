# Remote purchase onboarding — 26 October 2026

The Jaipur helper is paired with protocol9/version3.6.0 and Tally is reachable. Assignment No2 is disabled; STOCK INVENTORY ASSIGNMENT1 is enabled. Both saved catalogs are non-GST, with Main Location and purchase/sales masters. No workspace purchase configuration exists. The old chat purchase handler checked this missing configuration before asking which item was purchased, and showed a generic connect/non-GST message despite the successful remote connection.

Changes:
- Resolve only approved, enabled, role-scoped companies first. Multiple companies require selection. A missing item is requested with scoped saved-master choices, preserving quantity/unit and selected company. No write configuration/action is created by this prompt.
- Missing, non-test or different-company configuration produces a company-specific purchase setup action. Existing posting validation/test-company requirements remain.
- A visible Purchase entry setup button opens the existing settings form and approved company discovery, including through a chat action. It rejects stale/unapproved company hints. Multiple purchase ledgers start with an explicit Select choice; saved defaults apply only to the same company. Practice-company confirmation is cleared, never silently granted. Changing companies clears that confirmation again.
- Helper status recognises protocol9 for existing supported capabilities instead of falsely demanding an update. Unknown future protocols remain unsupported.
- Browser asset version24. Chat still supports legacy non-GST purchases; supported GST invoices use Bills review. No claim of production-company write support.

Validation:52 backend tests passed across tally_sync, connector_status, connector_download and legacy tally; connector UI suite/syntax passed. New cases cover missing config/item collection with no write authorization, disabled company denial, wrong-config company, multiple-company selection, protocol9 status, guided UI routing, explicit ledger choice and unchecked test confirmation. Tests use isolated fixtures and synthetic Tally transport.

Read-only acceptance against the actual Jaipur company returned two item choices, the correct company-specific setup hint, Main Location, Purchase/Purchase Return and non-GST eligibility. Tally action count unchanged; configuration remains absent. No company permissions, GST settings, helper pairing or remote entries were changed. The friend must explicitly choose Purchase (rather than Purchase Return), confirm that the selected company is a separate practice company, and save configuration before a chat purchase can be previewed. Existing server validation still checks those settings against approved company masters.

Authenticated local browser verified visible setup entry point, populated permitted masters and an unchecked practice confirmation. Screenshot:output/purchase-setup-fixed.png. The Jaipur browser's final save/post flow was not performed by the agent; do not call remote posting complete. Ngrok and the running app serve this same source. OCR's unsupported-image issue is separate and not fixed by this onboarding change.
