# Connector 3.7.1 MSIX implementation — 30 October 2026

Update, 1 November: the packaged runtime's missing vendor SSL security-policy PEM
was identified and is now collected unchanged by both build recipes. Packaged
sync/async/history/duplicate/MCP checks passed. With explicit user approval for a
local EXE exception, 3.7.1 was installed on this PC with pairing/journal preserved;
fresh native read and graceful helper restart passed. See
`CONNECTOR_REPAIR_STATUS.md` for evidence. This does not satisfy Store/MSIX or the
two-OS public-release matrix; those gates remain unchanged.

Status: source implementation and local regressions completed; Store/package runtime
release remains **withheld**, not end-to-end passed.

Added:

- Packaged identity/storage/startup adapter using WinRT, with explicit legacy guards
  against self-copy, executable replacement, scheduled-task installation and uninstall.
- Shared mutex and graceful legacy drain before migration; no force-kill.
- Consistent SQLite backup including WAL, preserved action IDs/settings/source files,
  backup hashes, integrity checks and interrupted-promotion recovery. Credential target
  unchanged; no automatic credential replacement.
- Legacy scheduled-startup retirement gated on enabled packaged startup,
  authenticated heartbeat and successful native company discovery; saved task XML.
- Redacted traceback frames and known CA path/existence diagnostics for initialization
  failures; clear UI failure instead of silent background-thread death.
- Sync and async client initialization/TLS assertions in the transport self-test.
- Onedir MSIX build recipe, verified-identity prerequisite, minimal full-trust manifest,
  pinned WinRT bindings, Node/MCP preservation, deterministic icons, dependency licences
  and artifact/file hash evidence. No unsigned artifact auto-publishing.
- Optional backwards-compatible heartbeat fields, derived MSIX startup boolean,
  approved Store distribution link and corresponding UI handling.

Verified:

- 12 isolated source tests: migration/WAL/action identity, interruption/hash tampering,
  invalid data, manifest identity/privileges, startup-disabled state, diagnostic
  redaction, retirement gate and CA/TLS configuration.
- 18 server/protocol regressions: existing authenticated heartbeat/status plus MSIX
  startup state, Store configuration, version 3.7.1 and old-helper protocol gating.
- Connector JavaScript DOM harness including Store navigation, legacy download,
  disabled startup, status and existing compact proposal.
- Python compile and PowerShell parser checks.
- `.env` retains `PHILIXA_PURCHASE_AGENT_ENABLED=0`.

Not verified / external blockers:

- Owner confirmed no Partner Center app record/verified package identity yet.
- Windows SDK MakeAppx not detected on this machine. No MSIX artifact was produced.
- No Store signing/certification, packaged runtime execution, hosted HTTPS/invalid
  certificate runtime checks, Windows 10/11 installation/upgrade or SAC-on pilot.
- Original packaged FileNotFoundError is **not closed**; diagnostics/CA candidate need
  actual approved packaged-runtime evidence. Windows blocking is a separate issue.
- Legacy Run-key variants require separate retirement acceptance; this delivery only
  retires the known scheduled task after proof. Existing source data/startup backups
  remain available for recovery.

No Tally voucher posted, installed helper replaced, pairing changed, Windows protection
disabled, Store account created or paid purchase made during this implementation.

Build instructions and full pending acceptance checklist: `helper/MSIX_RELEASE.md`.
