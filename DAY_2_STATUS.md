# Day 2 — Multi-item purchase implementation

Implemented on 2026-10-12, extending the existing Day 1 draft workflow.

## Working behaviour

- Bills supports adding/removing up to 100 item rows in one purchase draft.
- Each row saves its item, quantity, base unit and rate. Server and browser calculate line totals using decimal/integers and round-half-even to paisa, then sum rounded line totals.
- Existing saved single-item drafts remain readable/editable; legacy chat purchases retain their existing codec and API. Opening and saving a legacy draft in Bills upgrades its content to a line array.
- Supplier/item suggestions come from scoped saved Tally masters. Selecting an exact item fills only a missing base unit; rates are not inferred.
- Incomplete drafts can be saved. Preview requires complete lines and unambiguous supported masters, valid simple-unit precision, and a configured non-GST test company.
- One multi-item preview stages one voucher action. Save, reload and preview do not approve/post it. Existing explicit confirmation is reused.
- Changing any item expires the whole old preview. Revision checks also reject a concurrent edit during snapshot refresh.
- Stock projection sums relevant rows, including repeated items. Uncertain submissions block conflicting item operations.

## Connector and verification

- Protocol 7 adds isolated `purchase_multi_validate/post/reconcile` operations and `tally:queue:v7`.
- V6 helpers continue their existing operations and cannot consume v7 jobs. Multi-item operations require the updated helper; unsupported helpers are refused before an import.
- Server dispatch checks the stored approved payload and company identity; helper validates every line against current masters.
- The SQLite journal prevents repeat imports after duplicate delivery or an uncertain response. Reconciliation checks the date, supplier, bill reference/amount, every inventory line, rates/units/quantities, godown allocations, purchase ledger allocations and total.
- Native Tally GUID replacement and reordered item rows are supported when all approved details and action markers still match.
- Updated installer: `data/downloads/PhilixaTallyConnectorSetup-3.4.0.exe` (protocol 7), retaining the previously bundled MCP runtime.
- Installer SHA256: `27B646C67FFA882EDA03AA41005D1D5BC1A6500FEC4B8929D04CC50CE404938A`.
- The installer was built and packaging-smoke-tested; the user's installed helper was not replaced.

## Validation completed

- **140 tests passed**: new multi-item protocol/database/Redis bridge tests and existing draft, conversation, context, purchase sync, stock/count, supplier, graph and MCP regressions.
- Synthetic 1-, 20- and 50-line imports verified every line and did not duplicate on repeated delivery.
- Tests cover changed totals, missing/wrong lines, native bill exports, unknown units/items, changed masters, lost replies, stale edits, v6/v7 isolation and workspace-scoped master suggestions.
- Node draft-controller and chat-refresh suites passed; draft UI checks cover two rows, ₹3,600 total, explicit approval and read-only pending entries.
- Real browser: saved Cement (8 × ₹350) and Bricks (2 × ₹400), reloaded and reopened both rows with total ₹3,600. Temporary synthetic demo fixture was cleaned; zero accounting actions were created by that UI check.
- Packaged-helper MCP smoke test passed: stdio, 87 tools, direct writes blocked.

Reproduce backend checks:

```powershell
docker compose exec -T app python -m unittest scripts.test_multi_purchase scripts.test_multi_purchase_bridge scripts.test_purchase_drafts scripts.test_business_conversations scripts.test_business_context scripts.test_tally_sync scripts.test_tally.XmlTests scripts.test_tally_count scripts.test_business_graph scripts.test_mcp_business scripts.test_tally_reads scripts.test_tally_suppliers -q
```

## Live acceptance still required

The 1/20/50-line import tests use a synthetic Tally transport. Real Tally multi-item imports have **not** been claimed as verified. Day 2's live acceptance gate remains pending until an approved test-company voucher is imported with the updated helper and compared in Tally.

GST, OCR, discounts, batch/expiry, alternative units and automatic posting remain later milestones. This build supports the existing simple non-GST test-company restrictions.

## Simple user check

1. Hard-refresh the app, open Bills, select a company and enter a supplier.
2. Fill an item row, press Add item and fill another row. Check each amount and the combined total.
3. Save, reload, reopen; both rows must remain. Change a row/remove a row, save and check the new revision/total.
4. For a real Tally test, use exact supported supplier/item names, an allowed test date, and helper version 3.4.0. Review the complete preview before confirming.
5. Check the verified voucher in Tally. A pending/uncertain result must be reconciled instead of submitting another purchase.
