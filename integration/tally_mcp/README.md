# Philixa adapter build 0.1.0

Upstream: https://github.com/faizansworking/Tally-MCP
Pinned commit: `6619585a351000dd979b046ff63408771435644a`, version 1.13.1.
Original source and ISC notice are in `third_party/tally_mcp`. They are not edited.
This adapter imports upstream builders, not its HTTP server or raw audit logger.

## Reproducible build

From the project root, install the integration lock with `npm ci --ignore-scripts`
in this directory, then run `python scripts/build_tally_mcp.py`.
For the Windows candidate installer run `helper/build.ps1 -WithMcp`.
The candidate filename is separate from the currently served installer; do not
replace that download until Windows installation and lifecycle acceptance pass.
Node 24 is copied into the payload; end users do not install Node. Production
dependencies, templates, compiled code, registry, Node version and SHA256 digests
are recorded in the bundle manifest. Missing or altered payloads fail closed.

Dependency patch: MCP SDK pinned to 1.31.0 and proxy-addr resolved to 2.0.8 in
the separate integration lock. Original upstream package/lock remain preserved.
`npm audit` reported zero vulnerabilities on 2026-10-09; this is not a security
certification. Lifecycle scripts are not executed during dependency installation.

Documented source patches, applied only to build copies:

- Export the existing `buildWriteXml` function.
- Add compile-only batch vouchers using existing builders. Maximum 50 entries,
  duplicate identities rejected, all entries must compile; no partial execution.
- Use `philixa.ts` as private stdio entry. Direct write, context, SQL/cache and
  audit calls are rejected. Raw arguments/results are not logged. Health output
  omits private gateway URLs and raw error text.

## Implemented boundaries

87 pinned tool contracts: 26 read candidates, 51 write compilers, five cache tools,
two context tools, two upstream approval tools and one audit tool. Every contract
has schema, permission, preview/verification classification and capability state.
These classifications are not independent verification implementations.

`PHILIXA_MCP_READ_ENABLED=1` enables report selection/forms (`Tally reports`) and
`mcp_read` commands on the existing business graph. Fields: `company_id`,
`mcp_tool`, `mcp_arguments`. Reads use protocol 4; compile-only durable drafts
require protocol 5. Older helpers cannot consume compiler jobs. Existing reads
and purchases remain compatible. Reads use existing device/company grants and
revalidate credentials, membership and company scope before returning results.

The helper binds every export envelope to one approved company after checking its
live identity. A private gateway rejects import/action envelopes. One child per
request gives each company a disposable cache without global context mutation.
The execution mutex is per endpoint. Child timeouts terminate the read process;
later requests spawn a new child. No write is retried by this implementation.

`TallyAction` has additive backend/schema/approved-arguments/target/preconditions/
verification fields. Existing rows default to the Python backend. MCP actions
cannot fall through to Python posting or gain executable confirmation. Snapshot
projection does not add unknown backend effects to expected stock.

All 51 write builders have owner/admin forms and session-bound durable drafts.
Explicit company selection is required even when only one company is approved.
Review reuses the original draft; cancelled, expired and forged drafts cannot be
compiled. A protocol-5 `mcp_compile` job builds XML through an export-only gateway
and records its hash; it cannot import. Server, dispatch and helper semantic
validators reject empty entries, unbalanced Decimal ledger totals, invalid/future
dates, negative counts and arbitrary XML `extraFields`. Physical count writes
still need the separate live acceptance gate. These are draft/compiler checks,
not permission to post and not a replacement for canonical master validation.

Physical Stock builder now includes the three upstream reference fields
`PERSISTEDVIEW`, `DIFFACTUALQTY`, and item `ISDEEMEDPOSITIVE`. The live posting
acceptance gate remains closed; a GitHub template is not installed-version proof.

## Still required for the requested full milestone

- Operation-specific durable preview/approval, immutable decimal calculations,
  target GUID binding, preflight revisions and independent reconciliation for
  all 51 writes. Merely compiling XML does not implement posting.
- Company write policy/configuration, verified GST/non-GST scenarios and real
  company activation. Read grants never imply write permission.
- Offline confirmation and automatic dependency-ordered posting for new tools.
  Existing purchase offline queue remains unchanged.
- Session-scoped period/context, SQL cache and workspace-safe audit adapters.
- Full natural-language/voice write routing and operation-specific executable
  previews. Report routing and schema forms exist; this is not a measured model
  accuracy evaluation.
- Actual Tally acceptance across every write family, manual Physical Stock
  exports, uncertain outcomes, duplicates and report comparisons.
- Installed candidate upgrade, sign-out/login and child crash recovery acceptance.

Do not enable writes or report full integration complete until these are done.
Current tests cover adapter contracts and barriers, not actual accounting imports.

## Verification on 2026-10-09

- Adapter: 169 pytest checks passed, including actual Node stdio list/read against
  a fake gateway, every contract schema, all non-read tools blocked, company
  injection, malformed/mutation XML, unknown fields and unsafe numeric precision.
- Actual LangGraph MCP route: six integration checks passed. Existing graph,
  voice, legacy Tally and connector status modules passed (11, 5, 8, 6 checks).
- Durable stock/purchase/count/read regressions: 53 checks passed after the
  additive migration and endpoint serialization changes. Windows lifecycle
  pure runtime suite: 14 checks passed.
- Business permissions and real pgvector history scope scripts passed. Tests
  run in separate processes: legacy scripts with import-time Redis connections
  cannot be mixed into one IsolatedAsyncioTestCase process safely.
- Bundled Node executable: 87-tool stdio inventory and direct-write rejection
  passed independently. No accounting data was submitted.
- Initial 3.1.1 candidate launch was blocked by Windows Application Control
  (`WinError 4551`). Final 3.2.0 candidate launched successfully: packaged stdio,
  87-tool inventory and direct-write rejection passed with exit code zero.
  This is a non-installing smoke test, not installed upgrade/login/crash acceptance.
- The gateway subsequently became reachable. All 26 live report transport and
  display checks passed; a native Stock Summary comparison matched Cement's
  quantity and valuation (Tally's negative debit amount convention preserved).
  Other reports' financial totals still need native comparison.
- Actual Tally is EDU, with active voucher date 1 October 2026. Current-day
  Physical Stock acceptance requires a valid licensed environment; dates are not
  silently changed to make imports pass. No MCP accounting imports were sent.
- Candidate 3.2.1 launch was blocked by Windows Application Control. Installed
  connector and public download stay on 3.1.1; source report checks do not imply
  the installed connector has been upgraded or the report rollout enabled.

These counts are deterministic contract/regression checks, not 95% model-routing
accuracy evidence. Full implementation remains incomplete as listed above.

Final candidate: `data/downloads/PhilixaTallyConnectorSetup-3.2.0-mcp-candidate.exe`.
SHA256: `D58602252B9E841C11F0FD2075490CD2FBC21D883D1D987783164F78E51A30ED`.
Smoke result: `data/mcp-candidate-smoke.json`. The served download remains 3.1.1.

Latest source candidate: `data/downloads/PhilixaTallyConnectorSetup-3.2.1-mcp-candidate.exe`,
rebuilt with protocol 5 and shared semantic validation. SHA256:
`03B3963BA7AF8AB9B2F1BC3ABC7B17974FDAF92A38D863EA6800586ED19AD09D`.
Its build succeeded; installation/lifecycle acceptance has not passed.

Additional checks after the report/draft changes: 33 graph/report/semantic
checks, six PostgreSQL draft checks, 29 synchronization regression checks and
169 adapter checks passed. The UI harness also verifies that previews do not
recursively render status panels. Live read records are in
`data/mcp-live-reports.json` and `data/mcp-native-stock-comparison.json`.
