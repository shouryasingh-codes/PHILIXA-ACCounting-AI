# Tally test-company pilot

Implemented: local XML connector, live stock command, single-item purchase/sale
preview, durable PostgreSQL approvals, explicit confirmation, voucher read-back,
stock read-back and read-only reconciliation. Real local Cement stock reads have
been verified; purchase/sale writes still require real Tally acceptance.
Synthetic tests do not establish commercial readiness.

## Multi-company read connection (2026-10-08)

The existing business graph now runs `business_planner → stock_scope → tally_tool`.
Omitted company means all approved companies; named companies and approved aliases
resolve server-side. Members see only explicit grants. Results keep quantities and
units separate per company, include IST as-of/read dates and honest coverage.
Stock bypasses history retrieval, embeddings, generated SQL and answer synthesis.

`Connect Tally` provides helper pairing and a one-time loaded-company multi-select.
GST, multiple godowns and missing purchase/sales ledgers do not block read access.
The old non-GST test-company write pilot remains inside a separate expandable
section. Its saved company never becomes broad read authorization automatically.

Windows package: `data/downloads/PhilixaConnectSetup.exe` (unsigned pilot). The
per-user helper installs to `%LOCALAPPDATA%/PhilixaConnect`, registers login startup,
keeps its origin-bound credential in Windows Credential Manager, and offers tray
status/disconnect. It reads port 9000 first, inspects running Tally's `tally.ini`
read-only for alternatives, and accepts an advanced port override. It never edits
or restarts Tally. Only typed discovery/stock jobs are accepted; no raw XML/URLs,
SQL or shell jobs. Backend communication uses outbound HTTPS polling; development
HTTP requires explicit helper local-test mode (or `PHILIXA_HELPER_DEV_HTTP=1`) and an exact loopback host. The local-test checkbox fills `http://127.0.0.1:8001`; the choice persists for login startup. Pairing starts polling automatically while the user claims the code in Philixa. Public deployments must use
HTTPS and `PHILIXA_ENV=production` to disable legacy development API-key login.

Owner/admin claims a single-use code (10 minutes), approves loaded companies and
optional aliases/member grants, then chats normally. Replacement revokes the old
credential and requires reapproval. Unloaded/renamed companies do not silently
switch. Redis queues/results coordinate workers with 23-second request deadlines,
30-second job expiry, atomic duplicate rejection and 2 MB result bounds.

For developer direct-local onboarding only, set
`PHILIXA_TALLY_ALLOW_LOCAL_READS=1`. This switch is off by default. Operators can set
`PHILIXA_CONNECT_INSTALLER_URL` to an HTTPS package location or serve the built
package through the authenticated `/helper/download` endpoint. Build with
`helper/build.ps1` from a Windows build environment; accountants need no Python.

Verification: `python -m scripts.test_tally_reads` exercises real PostgreSQL/Redis
permissions, multi-company graph nodes, all/named/omitted scope, member isolation,
103 companies, item ambiguity, compound quantities, zero/negative/fractional
balances, partial failures, revocation, pairing replay and bridge duplicates.
Existing graph/history, voice and synthetic write approvals remain regression gates.
The packaged helper `--self-test <report-path>` checks GUI, temporary credential
storage, allowlist rejection and local discovery without installing/startup changes.

Live local bridge verified: temporary workspace pairing → authenticated Windows
helper → Redis jobs/results → the existing business graph → Philixa Test Cement
**0 bags**, as of 2026-10-08. The temporary workspace/credential were revoked and
removed afterward. Packaged GUI/credential/allowlist/discovery smoke checks passed.
The bridge acceptance used local HTTP; it does not establish hosted HTTPS readiness.

Pending real acceptance: two loaded companies with different nonzero quantities,
same-date Stock Summary comparison, GST/restricted-access/compound-unit fixtures,
clean Windows install/startup/reconnect/uninstall and hosted HTTPS phone voice.
Only Philixa Test is currently loaded locally. These gates are not completed by
synthetic tests or by a successful executable build.

## Setup and live acceptance

1. Use an existing TallyPrime installation or obtain it from the official Tally
   website. Check its current licence/trial conditions before buying. Installation
   and any licence/EULA acceptance must be completed separately.
2. Create a separate disposable test company, enable inventory and leave GST off.
   Keep exactly one godown. Create a simple unit (e.g. `bags`, zero decimals), a
   non-batch stock item (e.g. `Cement`), a supplier directly under `Sundry Creditors`,
   a customer directly under `Sundry Debtors`, and purchase/sales ledgers directly
   under `Purchase Accounts` / `Sales Accounts`. Cost centres, compound/alternate
   units, batches, returns and discounts are not supported by this pilot.
3. Enable the Tally HTTP server, normally port 9000, and load the test company.
   Follow the vendor's instructions for the installed version:
   https://help.tallysolutions.com/pre-requisites-for-integrations/
4. Docker uses `host.docker.internal:9000` by default. The server operator can set
   `PHILIXA_TALLY_HOST` to `host.docker.internal`, `127.0.0.1` or `localhost`, and
   `PHILIXA_TALLY_PORT` to the local port. Backend requests disallow public URLs,
   redirects and environment proxies. Never expose the Tally listener publicly.
5. At http://127.0.0.1:8001/ log into the workspace as owner/admin. Select
   **Connect Tally → Connection check → company / godown / ledgers**, acknowledge
   that it is the separate non-GST test company and save the configuration.
6. Manually create one purchase and one sale in Tally and export each as XML.
   Save redacted copies as real integration fixtures; compare the generated XML
   to them, especially signs, inventory/accounting allocations, bill allocations,
   unit precision, company selection and automatic voucher numbering. Current
   generator follows the official sample, not a real-company export:
   https://help.tallysolutions.com/sample-xml/
7. Record opening stock. Type or speak a complete command, e.g.:
   `Supplier se 10 Cement bags 350 rupees per bag kharide, aaj entry karo`.
   Confirm only after checking every preview field. Verify voucher/party/item,
   quantity, rate, total, date, godown and stock increase in Tally itself.
8. Sell a smaller quantity to the test customer; verify voucher and stock decrease.
   Repeat the original confirmation and ensure no second voucher appears.
   Cancel another preview and confirm it creates no voucher.
9. Stop Tally and verify a clear unavailable response. Simulate an import timeout
   in the test harness: the action must remain verification-pending, with no resend.
   Reopen Tally and use **Status check (no resend)** to reconcile. An unresolved or
   mismatched action requires manual inspection; this pilot has no force-retry.

No real vouchers have been written during development. This milestone is complete
only after steps 6–9 pass against the installed Tally version and test company.

## Interfaces and invariants

- Existing `/api/v1/business/command` accepts `stock_read`, `purchase_create`,
  `sale_create`; fields include item/party names, positive decimal quantity/rate,
  exact base unit, optional godown and entry date. Only today's writes are accepted.
- `/api/v1/business/confirm` recognizes PostgreSQL Tally tokens before legacy
  Redis previews. Tokens are scoped to workspace/user/session, expire after 15
  minutes, and bind exact server-generated XML, company and configuration version.
- `GET /api/v1/integrations/tally` exposes only this workspace's configuration.
  Owner/admin-only `POST /test` probes companies/masters and `PUT` saves mappings.
  Stock reads are available to authenticated workspace members; writes require
  owner/admin. Existing CRM customer permissions are unchanged.
- `POST /api/v1/integrations/tally/actions/{token}/reconcile` reads Tally and records
  status; it never imports a voucher. Terminal results are replayed durably.
- Configured canonical item/party/unit names are cached for one hour to help Hindi
  interpretation; masters and stock are always re-read before creating/importing
  a voucher. Missing or ambiguous details ask for clarification/selection.
  Deterministic text checks additionally reject tax/advanced-stock and combined
  instructions even if model interpretation omits the unsupported scope.
- A dedicated PostgreSQL transaction holds a workspace advisory lock through
  validation/import/verification. The durable `submitting` state commits before
  the external write. Crash recovery and repeats cannot reimport that action.
  This is duplicate prevention for our action tokens, not a global exactly-once
  guarantee across independent requests or external Tally users.
- A GUID match is insufficient: verification compares voucher date/type/party,
  item, actual/billed quantities, rate, signed amounts, ledger and godown. Only
  matching voucher plus successful stock read-back yields `verified`. Current
  stock may also include other users' transactions; stock alone does not prove
  this voucher's success.

## Automated checks

Run in the duplicate compose project (`accounts-dev`):

```
docker compose -p accounts-dev exec -T app python -m scripts.test_tally
docker compose -p accounts-dev exec -T app python -m scripts.verify_tally_interpretation
docker compose -p accounts-dev exec -T app python -m scripts.test_business_voice
docker compose -p accounts-dev exec -T app python -m scripts.verify_business_tools
docker compose -p accounts-dev exec -T app python -m scripts.test_business_scope
```

The Tally tests use synthetic XML and isolated temporary database records, never
real Tally. Message transports are mocked or previews cancelled. Never label
synthetic fixtures as exports from a real company.
