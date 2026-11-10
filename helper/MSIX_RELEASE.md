# MSIX-first connector 3.7.1 / protocol 10

This is a source implementation, not an approved Store release. Do not enable the
purchase agent or advertise MSIX availability based on unit tests alone.

## Build prerequisites

- Windows x64, Python 3.12 with working Tk, existing `.helper-build` environment.
- Windows SDK containing x64 MakeAppx. This development PC currently has no detected
  `C:\Program Files (x86)\Windows Kits\10\bin` tools.
- Owner-verified Partner Center app identity. Owner confirmed no record exists yet.
- `identity.json` supplied privately by the owner with `partner_center_verified: true`,
  `name`, exact `publisher` distinguished name, `publisher_display_name`, and `product_id`.
  Do not invent these values. No example identity is shipped as a release template.

From the repository root: `powershell -File helper/build-msix.ps1 -IdentityFile <verified-file>`.
The script builds an onedir payload, includes pinned Node/MCP, assets, dependency
licences and hashes, and runs MakeAppx validation. The resulting MSIX is unsigned
and withheld. It does not install or execute a blocked binary, sign, submit to
Store, purchase a certificate, or publish a download.

Build evidence distinguishes `published:false`, `signed:false`, and runtime acceptance
pending. A verified identity input is an administrative prerequisite, not evidence
of Store certification or a cryptographically verified release.

## Lifecycle

- Runtime resources load from the read-only package payload. Mutable data is
  `ApplicationData.Current.LocalFolder/PhilixaConnect`.
- Credential target remains `PhilixaConnect/device`; migration does not touch it.
- Packaged launch uses the same user mutex, asks an active legacy helper to drain,
  waits up to 60 seconds, and stops migration if it cannot acquire the lock.
- Settings and SQLite WAL are backed up; source files remain. Interrupted promotion
  resumes from hash-checked staging. An unexplained existing destination is blocked.
- Startup state is read through WinRT; disabled-by-user/policy is never re-enabled.
- Legacy scheduled startup is removed only after authenticated heartbeat plus native
  company discovery succeeds and packaged startup is enabled. Its XML is backed up.
  Query/identity/permission errors preserve recovery status and retry later.
- Legacy Run-key variants are deliberately not deleted by this delivery. Their
  retirement requires a verified matching command and separate acceptance coverage.

## Diagnostics

`network-diagnostics.jsonl` in the data folder contains exception type, frame module/
function/line, known CA resolved paths with user profile redacted, file existence,
and frozen status. No exception message, locals, URL, credential or invoice is logged.
The CA fix remains a candidate: the exact original packaged missing file is still
unverified. Runtime-hook failures and network-client initialization failures are
distinct from Windows execution blocking.

## Release configuration

Existing server API contracts remain. Optional heartbeat fields are `package_kind`,
`startup_state`, `transport_state`. MSIX `startup_configured` is derived from startup
state. Offline means offline; it does not diagnose SAC.

Only after exact artifact acceptance and Store approval configure:

- `PHILIXA_STORE_PRODUCT_ID` with the actual 12-character product ID.
- `PHILIXA_STORE_RELEASE_APPROVED=1`.

Absent/invalid configuration returns distribution `unavailable`; legacy API fields
stay compatible. The Store channel uses `https://apps.microsoft.com/detail/<id>`.
Do not set `PHILIXA_PURCHASE_AGENT_ENABLED=1` until all required live gates pass.

## Required acceptance record (all pending)

Run on Windows 10 22H2 x64 and supported Windows 11 x64, recording OS build, exact
artifact SHA256, package identity/publisher, Store signature and test timestamps:

1. Fresh install/first launch; reboot/login; disabled-by-user/policy.
2. Working 3.6 and affected 3.7 upgrades: credential reuse, settings, WAL integrity,
   pending action identity, interruption recovery, legacy/MSIX simultaneous launches.
3. Sync/async HTTPX initialization, native async Tally read, hosted valid HTTPS,
   invalid certificate AND hostname rejection. Source TLS tests do not replace this.
4. Tally closed/open; company unavailable; disconnect/server outage; MCP tool reads;
   native v10 history; old-helper protocol routing.
5. Task/context/compact proposal/grouped correction/reload/final review. Explicit
   user rate unchanged; no invented transaction date/reference; no Tally posting.
6. SAC-on fresh Store-signed execution and managed-device restriction reporting.

No binary execution on this PC is attempted to work around existing SAC blocks.
Store account verification, certification, SDK setup and the two-OS pilot remain
external prerequisites. Record failures exactly; no universal Windows compatibility
or real-world accuracy/time-saving claim follows from this implementation.
