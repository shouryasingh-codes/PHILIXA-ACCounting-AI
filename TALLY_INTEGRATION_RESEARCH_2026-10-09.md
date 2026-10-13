# Philixa–Tally integration decision, 9 October 2026

Research checked on 9 October 2026 at 20:16 IST. This is an architecture recommendation, not a claim that all accounting operations are implemented. Official documentation, upstream repository documentation and the current Philixa source were inspected. No company configuration, accounting data or application feature flags were changed during this research.

## Decision

For the existing Philixa product, retain the installed Windows connector, FastAPI/LangGraph, Pydantic validation, PostgreSQL actions and snapshots. Expose a small operation API inside that connector. Use Tally's official local HTTP interface behind it: retain proven XML operations, and evaluate native JSON for new operations on compatible TallyPrime 7.x installations. Use MCP as an optional tool interface/template source, not as the authority for approvals, company permissions or accounting correctness.

For a new 7.x-only integration, native JSON over local HTTP is a good first transport to evaluate. For Philixa today, replacing the already verified XML customer/purchase path solely to change serialization is unnecessary churn. That recommendation is engineering judgment specific to this codebase; it is not a benchmark proving one format faster.

## Important current findings

1. **Native JSON is real.** Tally documents built-in native JSON exchange from Release 7.0, including master, voucher and report examples. Native-format imports do not require additional TDL merely to understand the format. This corrects the earlier blanket statement that XML is the only integration option. JSON must still follow Tally's object schema, request headers and company context; it is not arbitrary app JSON or a PostgreSQL INSERT. [Official JSON integration](https://help.tallysolutions.com/tally-prime-integration-using-json-1/).
2. **Hosted Philixa still needs a path to the user's PC.** Tally's September 23, 2026 reference design uses a local connector initiating an outbound secure WebSocket, then forwarding to local Tally HTTP. It explicitly says this is a pattern developers implement, not Tally-provided cloud infrastructure. Existing authenticated HTTPS polling can serve the same reachability role; changing to WSS is a later latency/scaling decision, not a prerequisite for customer creation. [Official bridge reference](https://help.tallysolutions.com/secure-websocket-integration-with-tallyprime/).
3. **Current-date voucher testing and customer-master creation differ.** Official licensing guidance says EDU voucher creation is limited to the 1st, 2nd and 31st dates. A transport change cannot remove that restriction. Philixa's saved native/installed acceptance demonstrates zero-balance customer-master creation, not unrestricted current-date purchases or stock corrections. [Licensing guidance](https://help.tallysolutions.com/licensing-best-practices/).
4. Official Release 7.1 notes give May 20, 2026 as the release date; the global download page lists 7.1, while another download page returned 7.0. Therefore these findings establish native JSON availability from 7.0 and documented 7.1 availability, not an assertion that every download channel exposes the same latest installer. The local Tally executable metadata is `TallyPrime / 1.1.7.1`; this research did not execute a live JSON acceptance test. [7.1 notes](https://help.tallysolutions.com/release-notes-tallyprime-7-1/), [global downloads](https://tallysolutions.com/global/download/?productid=14&version=1_1_1_1_0).

## Options and practical value

### Official local HTTP + XML/native JSON — recommended foundation

Tally's prerequisites require a running gateway and a loaded company. A third-party application can retrieve data and store it without manually entering it through Tally's UI. A licensed/compatible installation and correct business objects remain necessary. [Integration prerequisites](https://help.tallysolutions.com/pre-requisites-for-integrations/).

Use operation contracts such as `list_parties`, `get_party`, `create_party`, `preview_purchase`, `post_purchase`, `get_action_status`. Inside the adapter, select XML or native JSON by verified capability. The frontend receives normal JSON regardless of Tally serialization. Do not create both a Python and MCP posting attempt for the same action.

### Tally-MCP — useful tool packaging, not a finished Philixa backend

The inspected Philixa pin is `6619585a351000dd979b046ff63408771435644a`. Its local source sends XML through HTTP, renders Nunjucks templates, and keeps preview confirmations and the SQL cache in process memory. Current upstream documentation likewise describes session-scoped caching and preview/confirmation tools. Retain templates/read tools that pass acceptance; retain Philixa's durable approval/outbox instead of substituting the upstream memory map. Upstream statutory GST/VAT filing coverage must not be inferred from generic voucher/report tools. [Upstream project](https://github.com/faizansworking/Tally-MCP), [pinned architecture](https://github.com/faizansworking/Tally-MCP/blob/6619585a351000dd979b046ff63408771435644a/docs/ARCHITECTURE.md).

MCP standardizes tool discovery/calls; local stdio and remote Streamable HTTP are different deployment transports. It does not itself supply Tally schemas, an accounting engine or offline authorization. Use private stdio if the bundled server remains useful. [MCP architecture](https://modelcontextprotocol.io/docs/learn/architecture).

### Accounting-Companion/TallyConnector — SDK alternative

The project's current documentation describes a C# object abstraction over XML, support for TallyPrime 5/6/7, and .NET runtime requirements. It can reduce handwritten XML effort. Moving Philixa's working Python connector to it would introduce a .NET integration/packaging boundary; the Python quickstart is not proof of a pure Python runtime. No local acceptance was performed for this SDK. Evaluate one missing complex voucher family in isolation before adopting it broadly. [Project source](https://github.com/Accounting-Companion/TallyConnector).

### NienHQ/tally — simple REST facade to evaluate, not an automatic replacement

The project describes a single Go executable with JSON REST endpoints for ledgers/vouchers and a sync mode. Its public repository showed two commits during inspection. The documented sync cursor follows new voucher MasterIDs; that description alone does not prove full edit/delete synchronization or uncertain-write reconciliation. It also exposes a raw XML endpoint. Its README's XML-only description should not override Tally's newer official native JSON documentation. Treat it as an implementation candidate, not evidence of production completeness. No local acceptance or security audit was performed. [Project source](https://github.com/NienHQ/tally).

### ODBC / custom TDL / screen automation

ODBC is attractive for SQL-style reporting: Tally documents SELECT queries against exposed collections. That is not evidence of PostgreSQL-style INSERT/UPDATE support into Tally, so do not choose it as the general write backend. [Official ODBC documentation](https://help.tallysolutions.com/odbc-integrations/).

Custom TDL can add missing exports, events or specialized business behavior; use it only when a supported object/report interface cannot meet the requirement. Official XML guidance recommends creating a native sample and exporting it to determine optional voucher tags. Screen clicks should be an inspection/acceptance fallback, not the primary write API. [Official sample XML workflow](https://help.tallysolutions.com/sample-xml/).

## What “full access” can honestly mean

Approved-company read/write coverage can include supported masters, inventory, vouchers and reports. It does not mean a model receives unrestricted access to every Tally screen, bypasses license/date restrictions, or gets complete GST filing merely by installing an MCP server. Define an operation catalog and qualify each family independently. Read access, write approval and delete approval are separate capabilities.

Accounting correctness still requires explicit company identity, canonical masters, units, dates, balanced entries/tax configuration, confirmation, a durable action reference, and read-back verification. For unknown write outcomes, reconcile before resending. Official bridge guidance explicitly warns that replaying writes is not inherently idempotent. This is necessary implementation work rather than an XML-specific defect.

## Current Philixa evidence and actual blockers

- `app/services/tally_connector.py`: existing HTTP/XML implementation; frontend never needs to see XML.
- `app/services/tally_sync.py`: PostgreSQL action approval, company/device checks and snapshot publishing already exist. Preserve them.
- `data/customer-installed-acceptance.json`: actual paired connector acceptance reports verified, one ledger, CRM link, no duplicate confirmation and verified QA cleanup. `data/customer-install-test.json` reports installed 3.3.0/startup registration. These are saved acceptance evidence, not a new live runtime check today.
- `app/services/tally_sync_protocol.py:52`: current purchase pilot requires a direct `Sundry Creditors` parent; the customer feature creates `Sundry Debtors`. This exact validator explains why a newly created customer is rejected as the purchase supplier. It is Philixa's current eligibility policy, not proof Tally universally forbids buying from a debtor party.
- `app/services/tally_mcp_service.py`: reads return disabled unless `PHILIXA_MCP_READ_ENABLED=1`. Supplier questions routed into that feature cannot magically work because the connector is online. This research inspected the source gate, not deployment environment secrets.
- `app/services/tally_count.py`: `COUNT_CODEC_CERTIFIED=False`; count writes are intentionally not enabled. No format or flag should be presented as accepted until native voucher/report tests pass.

## Smallest reliable build sequence

1. Wire supplier list/detail directly to existing approved-company ledger snapshots/live reads. Resolve parent-group hierarchy, not merely an exact English parent string. Label saved versus live data. Add an honest capability response for unsupported requests; never invent a button.
2. Generalize the already verified customer-master path into a party operation with explicit customer/supplier role. Reuse its durable approval, native identity marker and CRM link. Existing names/groups require an explicit choice; never silently reclassify an existing customer.
3. Complete existing purchase acceptance with the chosen supplier: online, offline, restart/timeout, exactly one native voucher and independent stock/ledger verification. Use licensed Tally for unrestricted current-date tests.
4. Evaluate one read-only native JSON request, then one isolated master write/read-back on the installed version. If it improves adapter maintenance, add it behind the same operation contracts. Keep already-submitted XML actions reconcilable using their original codec.
5. Add sale, returns, count correction, orders and edits/deletes only after each family's native acceptance. For taxes/statutory work, use verified company configuration and representative native reports; do not assume broad access from tool count.

The easiest end-user setup remains one installer, one pairing, company approval and automatic background reconnect. A second user-facing Node server, .NET setup, tunnel or separate MCP configuration would increase setup work. A signed/reliably packaged installer and understandable status matter more to that experience than whether the local payload is XML or JSON.

No numeric delivery-time, reliability or cost claim is made: the alternative libraries were not benchmarked locally. Research is complete; this document does not enable any new accounting operation.
