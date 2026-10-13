# Revised Day 1 — Durable purchase drafts

Build date: 2026-10-12. This milestone extends the previously completed chat-context and saved-history work.

## Delivered behaviour

- Sidebar **Bills · saved drafts** opens company-scoped purchase working copies.
- Save incomplete or complete single-item drafts, reload, reopen, edit and inspect revision history.
- Draft creation/editing is independent of a login session. It does not queue a Tally write.
- A complete saved draft can create a fresh preview through the existing non-GST test-company validation path. Explicit confirmation remains required.
- New chat purchase previews also create a linked durable draft in the same transaction.
- Editing a preview's financial values expires the previous token. A stale revision returns HTTP 409; queued, uncertain and verified entries cannot be edited as drafts.
- Linked draft status reads the original action status, avoiding a second accounting status machine.
- Original revision snapshots are append-only through the service/API. No audit update/delete endpoint exists.

## Compatibility and permissions

Existing purchase, chat and approval APIs remain compatible. Drafts are private to their creator and authenticated workspace; the pilot requires owner/admin permissions. Disabled companies are inaccessible. Changing companies requires a new draft.

Only previews created after this release receive a draft link. Older purchases remain in existing chat/action history; this release does not recreate or resend them.

Partial drafts intentionally have no invoice-document metadata or multi-item array yet. Those belong to subsequent milestones. OCR, GST support, autonomous posting and real-company writes are not enabled by this milestone.

## Interfaces and storage

- `/api/v1/business/purchase-drafts`: list/create.
- `/purchase-drafts/companies`: selectable workspace companies.
- `/purchase-drafts/{id}`: get/update with expected revision.
- `/purchase-drafts/{id}/audit`: read revision snapshots.
- `/purchase-drafts/{id}/preview`: fresh preview with expected revision.
- Tables: `purchase_drafts`, `purchase_draft_events`.
- Migration: `r4k1l2m3n4o5`, after `q3j0k1l2m3n4`.

## Validation commands

Completed verification on 2026-10-12:

- Development database migration is at `r4k1l2m3n4o5`.
- 129 database/regression tests passed across the modules below.
- Both Node UI suites passed.
- Real in-app browser: created an incomplete synthetic bill, reloaded and reopened it, edited its item, reloaded again, and verified revision 0/1 history.
- Fixed form loading race found in the browser; input fields now lock until the requested draft has loaded. Browser save/edit/reload was retested successfully.
- Temporary browser fixture cleaned up; zero accounting actions were created by that check.
- Proof: `screenshots/day1-drafts-verified.png`.

```powershell
docker compose exec -T app alembic upgrade head
docker compose exec -T app python -m unittest scripts.test_purchase_drafts scripts.test_business_conversations scripts.test_business_context scripts.test_tally_sync scripts.test_tally.XmlTests scripts.test_tally_count scripts.test_business_graph scripts.test_mcp_business scripts.test_tally_reads scripts.test_tally_suppliers -q
```

Node checks: `scripts/test_purchase_drafts_ui.cjs` and existing `scripts/test_business_chat_refresh.cjs`.

Database integration fixtures and Tally/provider mocks are used for automated tests. Passing them does not measure extraction accuracy or certify new real Tally imports.

## Manual check

1. Open Bills, choose an approved company, enter just a supplier and save.
2. Reload the browser, reopen Bills and select the draft; the supplier must remain.
3. Add an item/quantity/unit/rate/date, save, inspect revision history.
4. Create a preview; the bill remains unposted until explicitly confirmed.
5. Edit and save a preview draft; the previous token must not queue the old values.
6. Switch workspace/sign out; the previous workspace's Bills UI must clear.

For Educational Mode, use an allowed date deliberately in the test company. The application never changes an approved date automatically.
