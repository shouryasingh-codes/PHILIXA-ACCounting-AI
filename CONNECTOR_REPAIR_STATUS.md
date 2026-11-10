# Connector repair — updated 1 November 2026

## Local repair accepted and verified

After the user explicitly approved the limited EXE update on this PC (not a public
distribution change), the validated 3.7.1 candidate was installed normally.

- Installed hash matches `BBB98016466A86E202B2137D822BB8B6195A392D7244F639D752DC87460F7D9D`.
- Original Windows credential is byte-for-byte unchanged. Connection settings are
  preserved and SQLite journal integrity is `ok`.
- Executable/settings/consistent SQLite backup is retained under
  `.helper-build/repair-recovery-274f457be7a74dc1a94bf2a9b5d1f4c4`.
- Authenticated helper heartbeat: online, version 3.7.1, protocol 10,
  `startup_configured:true`, `tally_state:available`, `transport_state:ready`.
- Browser shows “Live available” and “Setup complete. Live stock access verified”.
- Graceful helper restart through its normal shutdown channel and existing startup
  task passed; no force-kill. Fresh heartbeat AND native stock-read timestamps are
  newer than the restart, so stale cache is not counted as recovery success.
- No new pairing, voucher posting, Windows protection change or public release.

Evidence: `output/connector-371-update-proof-20261101.json`,
`output/connector-371-restart-20261101.json`,
`output/connector-371-live-proof-20261101.json`,
`output/connector-live-fixed-20261101.png`.

Scope: local installed connector and approved Philixa Test native-read/restart
acceptance. Windows reboot/login, other PCs/OS builds, Store signing and public MSIX
rollout remain separate gates. Purchase-agent rollout was not enabled here.

The earlier installation rejection below is historical and was resolved by the
user's explicit limited local-test approval; no rejection was bypassed.

## Root cause and packaged verification — 1 November (supersedes old hypotheses)

The normal-policy packaged transport test ran and failed inside `ssl.SSLContext.__new__`.
The build runtime's ssl.py has a vendor security-policy load for
`codex-rejected-cas.pem`. That resource existed beside the build runtime's ssl.py but
was absent from the frozen executable. Archived 3.6 SSL code has no such resource
reference; archived 3.7 SSL code does, without the corresponding bundled file.

Both legacy and MSIX build recipes now collect the exact PEM required by the runtime's
SSL constructor. Its bytes/security policy are unchanged; TLS verification and the
vendor distrust policy are preserved. Missing required policy data blocks a build.

After this fix, actual packaged sync/async initialization, certificate/hostname
verification flags, synthetic native-history/duplicate checks and pinned Node/MCP
self-tests all passed under normal Windows execution. No Windows protection was
disabled and no security warning was bypassed. Earlier CA-only and SSLKEYLOGFILE
hypotheses were not the demonstrated root cause.

Validated candidate SHA256:
`BBB98016466A86E202B2137D822BB8B6195A392D7244F639D752DC87460F7D9D`.
Required policy PEM SHA256:
`c916ce1b14ed8ca69e9b5c9fab22799a900dd610d6d4ec9b1347f4fd48e53718`.
Evidence: candidate `-acceptance.json`, `.static-evidence.json`, and failed prior
`output/connector-371-transport-20261101.json` (the prior failure is historical).

Installation has NOT happened. Automatic approval review rejected replacing the
installed connector with this unsigned legacy-format EXE because the user's locked
plan was MSIX/Store-first. A limited explicit exception for this developer PC's EXE
test update has been requested. Do not retry installation or use UI/indirect commands
to work around the rejection. The installed 3.7.0 remains unchanged and offline.
No new pairing, voucher posting or public release occurred.

## Latest verified state (31 October)

- Server health HTTP 200; Tally process `tally.exe` is running. The earlier
  process-name check for `TallyPrime` was insufficient to determine Tally status.
- Saved Windows pairing exists, its origin matches settings, and its credential
  fingerprint matches an active server device. No credential values were logged.
- Server helper heartbeat is offline; zero pending posting actions found.
- The installed 3.7.0 executable has no `--transport-self-test` entry point. The
  recorded `output/agent-helper-transport.json` FileNotFoundError belongs to a test
  candidate, not a direct transport test of that installed executable. Do not
  attribute its exact failure to the installed build without further evidence.
- A source guard now reuses a saved same-origin pairing when offline; only confirmed
  server rejection allows a new pairing request there. An explicit reconnect button
  resumes saved settings without generating a new credential.
- 18 isolated pairing, transport, migration and TLS tests passed this continuation.
- Build-only/offline support validates pinned cached MCP files and does not execute,
  install or publish the resulting candidate. Normal PowerShell build was approved
  outside the sandbox; no persistent Windows security setting was changed.
- SAC policy state is still 1. No attempt is made to evade this restriction by
  running a blocked executable through a different path or interpreter.
- Existing connector has no targetable visible window currently. User was asked to
  open its tray “Show status” (not Generate code) for the live reconnect test.
- Repair candidate compiled successfully without executing/installing/publishing:
  `data/connector-candidates/PhilixaTallyConnectorSetup-3.7.1-mcp-candidate.exe`.
  SHA256 `FA00A69D362CB38C5538DDF12633207A4AAF71E817E21D3CAA2F69E2D90EFEC5`.
  Static archive checks confirm CA, shared transport, pairing guard, diagnostics and
  pinned MCP/Node hash. Signature is NotSigned; packaged runtime remains unverified.
  This is an internal legacy-format diagnostic candidate, not a Store/MSIX release
  or a change to the MSIX-first public distribution decision.

Older observations below are historical, not current acceptance.

## Live UI continuation — 1 November

- User opened the installed connector through its tray Show status menu.
- Normal Pause then Resume was exercised, without Generate code, credential changes,
  installation, process termination or voucher posting.
- On-disk `paused` returned to false, but UI remained at “Automatic connection paused.
  Resume when ready.” This confirms the resume path is not restoring a truthful live
  state; it does not identify the exact original missing runtime file.
- Source now resets `connected` both when the HTTP client cannot initialize and
  when creating the worker thread itself fails. Connecting/startup-failure text is
  explicit. Three injected-failure tests plus three pairing-preservation tests pass.
- The installed executable is still old 3.7.0; source tests do not repair that
  already-running process. A rebuilt candidate needs normal-policy runtime validation
  before any replacement can be considered.

Current installed connector: 3.7.0, automatic startup configured, not paused.
The two observed PhilixaConnect processes are a parent/child pair at the same
installed path, consistent with PyInstaller onefile; this alone is not proof of
two independent consumers. TallyPrime was not found in the process-name check.

Read-only investigation:

- Both 3.6.0 and 3.7.0 archives contain `certifi/cacert.pem`.
- The current process's corresponding `_MEI383842` extraction has that file too.
- Archived certifi and HTTPX modules match between versions.
- Python DLL hashes differ, but their embedded version metadata is the same
  3.12.14150.1013. A different hash is not proof of a Python-version regression.
- Existing logs do not contain the traceback needed to identify the original
  FileNotFoundError's exact file. No new claim that the original cause is closed.

Repair in source:

- Shared explicit TLS factory for connector hosted sync clients and Tally async
  client. Frozen CA path resolves directly under `_MEIPASS`.
- Certificate and hostname verification stay required. Callers cannot supply
  `verify=False` or opt into arbitrary environment proxy/certificate settings.
- Avoids `ssl.create_default_context`'s unrelated SSLKEYLOGFILE side effect. A missing
  debug-log directory demonstrably raises FileNotFoundError in the default setup;
  both new clients initialize successfully in that same controlled test. This is a
  reproduced failure mode, **not proof of the installed connector's root cause**.
- Redacted diagnostic flags distinguish keylog-path configuration from CA presence.

Validation this repair turn:

- 5 isolated TLS/transport tests passed.
- 27 Tally/status/protocol regressions passed with synthetic Tally fixtures.
- No voucher posted, installed binary launched/replaced, pairing changed, Windows
  protection disabled, or blocked binary executed through an alternate path.

Remaining: build and run the exact packaged artifact in the approved Windows/Store
test route, obtain its actual initialization traceback if it fails, then verify
pairing, native read, restart/reconnect on the supported Windows matrix. The existing
SAC restriction and absent verified Store identity still prevent claiming that the
installed connector is repaired. Purchase-agent release flag remains off.
