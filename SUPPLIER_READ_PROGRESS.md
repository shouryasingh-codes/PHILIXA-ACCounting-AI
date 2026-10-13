# Supplier list and details — verified 10 October 2026

Scope: permitted-company supplier list and named supplier details; no supplier creation, reclassification or voucher writes.

Implemented:
- Additive Pydantic supplier_list/supplier_read intents and existing LangGraph tally_tool routing.
- Fresh common supplier questions isolated from previous purchase fields.
- Existing scoped identity/device-bound snapshot transport reused; saved data explicitly labelled.
- Exported group hierarchy classification, excluding debtors, unknown parents and cycles.
- Ambiguous names produce scoped choices; revoked company/device grants rechecked before response.
- Older snapshots remain compatible and disclose unverified subgroup coverage.

Verification:
- `data/supplier-regressions.log`: 97 tests passed across supplier, customer, purchase/sync, count, permissions and connector checks.
- Routing refinement: 8 supplier tests passed again (repeat checks, not additional distinct tests).
- `data/supplier-business-regressions.log`: 16 graph/history-boundary/voice tests passed, plus business-scope fixture checks. Total: 113 distinct unittest checks.
- Native acceptance through the installed connector matches independent Tally exports: one supplier, named details, group and available contact/balance fields. Group coverage verified.
- Real identity-bound saved snapshot matched native suppliers under a simulated transport outage, correctly labelled saved. The user's Tally window was not closed.
- `data/supplier-installed-acceptance.log` contains the successful live/fallback assertions. Zero accounting writes and no pairing/grant changes.
- Connector 3.3.1 packaged and installed, startup registered and existing pairing retained. Website downloads prefer this released build.
- Package GUI, temporary credential storage, typed allowlist and endpoint checks passed. Initial discovery met closed Tally; later installed-connector acceptance establishes live connectivity.
- Bundled MCP stdio check retained the pinned commit and 87 tools; direct writes remain blocked.
- Accounting imports no longer require the meeting embedding runtime; embeddings load when requested. Existing graph/history-boundary/voice regression tests passed.

User check:
- Send `Hamara supplier kaun hai?` in Philixa chat, then select a supplier.
- Send `Sharma Traders ye kon hai?` for the existing test supplier's ledger details.

Scope boundary: this delivery verifies supplier reads, not supplier creation or all MCP operations. Physical Stock and other write gates remain unchanged. Actual Windows/Tally restart and physical outage tests are not implied by the simulated fallback check.
