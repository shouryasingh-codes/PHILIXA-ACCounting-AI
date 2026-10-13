# Customer creation with Tally

In a connected workspace, `Rahul customer add karo` follows the existing business
LangGraph into a durable customer ledger preview. The owner/admin confirms once.
The configured approved non-GST test company is the only enabled write scope.
Multiple approved companies require explicit selection. Real-company/GST
activation is not part of this feature.

The connector creates a zero-opening-balance ledger under **Sundry Debtors** with
bill-wise tracking off, verifies its native identity and fields, refreshes the
snapshot, then saves/reuses the Philixa customer and `tally_customer_links` row in
one transaction. Existing customer ledgers are linked without alterations;
existing creditor/other groups are not silently changed. Customer creation does
not make that ledger eligible for the existing creditors-only purchase pilot.

No approved/configured Tally connection retains the existing CRM-only flow with
an explicit **Philixa only** preview. Connected-workspace failures never silently
fall back to a CRM-only success.

Confirmed offline requests use the existing TallyAction outbox. Changed clients,
company identity, device credentials, permissions or ledger preconditions require
review. Unknown imports reconcile without a second import. Native Tally assigns
its own master GUID and does not preserve the supplied NOTES field in the tested
version. An action alias in LANGUAGENAME.LIST/NAME.LIST is persisted and binds
reconciliation to the action; LASTMID=0 is not considered a receipt identity.
The persisted local journal can also use a positive, explicitly returned master
ID where supported. Verification checks a fresh server-side snapshot before
publishing the client/link.

Connector 3.3.0 / protocol 6 is required. Old clients cannot consume the dedicated
v6 job queue. The base installer remains available; the guided update downloads
`/api/v1/integrations/tally/helper/download?capability=customer_ledger`.

Checks:

- `python -m scripts.test_tally_customer`: isolated protocol/database/graph/bridge tests.
- `python -m scripts.check_customer_ledger_live`: native read-only preflight.
- `python -m scripts.check_customer_ledger_live --execute`: only in the explicitly
  configured Philixa Test company, one uniquely named zero-balance QA customer,
  native creation/link verification, duplicate confirmation and verified cleanup.
- `data/customer-ledger-acceptance.json`: native acceptance is distinct from
  installed Windows connector acceptance. No purchase/stock vouchers are created.

Windows acceptance on 9 October 2026:

- Connector 3.3.0 installed successfully, with startup registration and existing
  pairing retained. Packaged GUI/credential/typed-operation smoke checks passed.
- `scripts.check_customer_installed` passed using the actual paired connector,
  existing owner session, LangGraph, durable confirmation and server-side native
  snapshot verification. Exactly one Sundry Debtors ledger linked to one CRM
  customer; repeated confirmation produced no duplicate. QA records were removed
  and the snapshot refreshed. No accounting vouchers or grants were changed.
- Evidence: `data/customer-installed-acceptance.json` and
  `data/customer-install-test.json`. Final regression suite: 72 tests passed.
- This proves the configured test-company customer path. It does not enable
  real-company/GST writes, stock-count posting or supplier creation.
