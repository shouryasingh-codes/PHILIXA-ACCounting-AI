# Tally Connector setup and acceptance

## Product flow

Open Philixa → Connect your software → Download Tally Connector. On the Tally PC,
open Chrome Downloads (Ctrl+J), run PhilixaTallyConnectorSetup.exe and click
Install & continue. The installer creates a per-user Windows Start shortcut and
a limited-privilege Scheduled Task; no administrator service is installed.

For a new installation, enter the Philixa website address, generate and copy the
code, paste it into Philixa, and approve the discovered companies. Local HTTP is
available only through Advanced → Local development, for localhost testing.
Existing installation updates preserve Windows Credential Manager pairing,
company grants, settings and the submission journal; do not replace pairing to
perform a routine update.

The connector runs through the Scheduled Task, including Start Menu launches.
Windows login starts it; unexpected process failure triggers task restart after
one minute. X hides the window. Pause is persisted and is respected on restart.
Explicit Exit stops this session; the next Windows login starts it again.
Tally and network recovery retry automatically with backoff capped at 60 seconds.
Revoked credentials require explicit pairing replacement instead of silent retries.

Updates request graceful shutdown and wait up to 30 seconds. Active entries are
allowed to finish; a busy timeout defers the update instead of killing a writer.
An executable backup is retained until setup succeeds and restored on setup failure.
Settings and credentials are never removed by an update. Uninstall removes startup,
shortcut, pairing and settings using the existing uninstall confirmation.

## Status contract

GET /helper/status remains backwards compatible and adds connection_state,
setup_complete, diagnostics, diagnostics_update_required and company_health.
Connector online alone does not imply Tally reachable or successful stock access.
Device-authenticated POST /helper/heartbeat accepts bounded typed version/startup/
reachability diagnostics, with only approved company identities. Diagnostics expire
after 45 seconds and are bound to the credential version. Browser responses do not
expose that credential binding or other members' company diagnostics.

Authenticated POST /setup/check performs a filtered read-only stock collection check
for permitted companies. This checks transport/read access, not inventory quantity
correctness. Successful proofs expire after 90 seconds, are invalidated by closed/
unreachable diagnostics, and require permission revalidation after the network read.
The UI checks again as proof expires; no accounting write is used for setup testing.

Older helpers retain read/purchase/count protocol compatibility; diagnostics missing
or unknown means update required, never "Live available". Physical Stock posting
remains gated off pending real voucher/report acceptance.

## Diagnostics and automated verification

Boot hooks record coarse launch milestones and exception type names only to
%LOCALAPPDATA%\PhilixaConnect\startup.log. No credentials, accounting payloads,
narration or raw exception messages are recorded. Errors before GUI construction
produce an actionable Windows message rather than only disappearing.

The automated suite covers lifecycle, bounded retries, pause, singleton threading,
busy submission exit, diagnostic permissions, stale device credentials, false-live
prevention, real-read proof, offline download visibility, dialog polling and input
preservation. Existing accounting/graph/voice regressions are also required.

## Actual Windows acceptance still required

- Clean standard-user install from Chrome, visible guided screens and code pairing.
- Existing paired upgrade without new code or credential loss.
- Start Menu second launch foregrounds the existing window; no duplicate consumers.
- Windows sign-out/login and unexpected connector process crash recovery.
- Tally close/reopen produces a new Live read without manual reconnect.
- Server/network restart, pause/resume, missing company, revoked pairing and uninstall.
- Windows executable blocking and startup registration failures show usable instructions.

Packaging/synthetic tests do not substitute for these interactive checks. No clean
Windows user or reboot acceptance is claimed from an agent-launched process.
