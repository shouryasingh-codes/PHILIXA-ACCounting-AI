# Day 10 — controlled pilot recovery validated

Verified on **20 October 2026**. Accounting recovery and the current Windows installer/update checks passed. This is a supervised test-company pilot; extraction accuracy is not production-certified.

## Fresh verification

- **71 backend regression tests passed** across durable sync, GST purchases, business memory and controlled automation. Coverage includes repeated confirmation, timeout/no resend, configuration/session expiry, permissions revoked before dispatch, changed masters, policy pause, helper compatibility and uncertain-action preservation.
- **16 document/review tests passed**, including durable leases/recovery, private originals, duplicate upload, malformed/over-limit sources and the independent 50-bill approval batch. Tests use isolated synthetic fixtures; no real Tally write is dispatched.
- **2 new process-boundary recovery tests passed** (`scripts.test_day10_recovery`). One synthetic import persists before the helper process exits abruptly; new processes reconcile the same action and see exactly one import. A timeout with no visible voucher remains verification_pending across fresh processes and imports exactly once. The original approved payload/date is retained. Transport is synthetic, not a crash injected into real Tally.
- **14 native Windows lifecycle tests passed**: disconnected polling, credential revocation, pause/resume, singleton polling, least-privilege startup, settings preservation, corrupt settings handling, busy update deferral and failed-update executable rollback. Initial sandbox runs could not complete Windows asyncio/temp operations; the same isolated tests passed in native Windows execution with a workspace temp directory.
- Connector and automation JavaScript suites passed. No UI implementation changed for Day 10.

## Actual app/worker restart

Automation was paused and there were **zero active accounting actions** before restarting only `app`, `document-worker` and `tally-worker`. PostgreSQL, Redis, MinIO and all their volumes remained intact.

`data/day10/before-restart.json` and `after-restart.json` contain the same durable state hash:

`14cb7362f205ccc098120664ce5740e89840aaea478dacaefd0d6b7acc147804`

Six drafts and five document records survived. The pre-existing Day 8 dummy purchase action `22e86d253510d4528b17a5820c47de17`, approved date **2026-10-02**, matched the native Tally voucher before and after restart. Accounting workers resumed recovery/sync ticks. No new voucher was posted. The process test suite was rerun fully after its initial run was interrupted by the deliberate container restart.

## Installer/build/update

Current **helper 3.6.0 / protocol 9** is the compatibility target; the plan's v7 is an older protocol and was not installed as a downgrade.

- Rebuilt current sources with PyInstaller using the already pinned Windows dependencies and existing pinned MCP payload. No new dependency download was needed.
- Build command: `.helper-build\Scripts\python.exe -m PyInstaller --noconfirm --distpath data\day10\installer --workpath .helper-build\day10-build .helper-build\PhilixaTallyConnectorSetup-3.6.0.spec`
- Candidate: `data/day10/installer/PhilixaTallyConnectorSetup-3.6.0.exe`
- SHA256: **dc23a890cf5f0f50cf2bde4b988953660cc2a6ed6ddc8f8f651d01c319636842**
- Packaged invoice duplicate/full-financial-year self-test and GST arithmetic/strict-verifier self-test passed. Both are synthetic, with no native imports.
- Actual per-user installer/update ran successfully, registered and started its scheduled task. Installed executable matches the candidate hash. Pairing credential, connection settings and SQLite journal were compared before/after and preserved. No credential value was emitted.
- `data/day10/helper-update-proof.json`, `helper-install.json`, `packaged-invoice.json`, `packaged-gst.json` and `build.log` retain evidence.
- Final `after-helper-update.json`: same six drafts/five documents and same state hash, **all five private original checksums intact**, native existing voucher verified, no active accounting actions, automation paused.

The old downloadable 3.6.0 artifact was not overwritten. Use this explicitly hashed pilot candidate for this validation; it is unsigned and has not been published as a general public release. Fresh-machine installation was not performed; existing-user update/startup was exercised and installer failure paths have isolated tests.

## Limitations and operating guide

See **PILOT_RELEASE.md** for supported workflow, company/master requirements, Educational Mode date restrictions, same-action reconciliation and the rule against blind resend or deleting the local journal/volumes.

At the original Day 10 recovery acceptance, Day 9 extraction gaps remained (154/166 fields, 0/6 exact files). A subsequent extraction follow-up on 20 October fixed those observed gaps and reran the unchanged corpus at 166/166 fields and 6/6 exact files; see DAY_9_STATUS.md and the latest report. Photos/scans stay reviewed. Real anonymised bills, human accountant accuracy/time savings, production backup/restore and wider Tally/version/environment coverage remain unverified. Existing Day 8 end-to-end posting evidence was rechecked through persisted state and native readback; Day 10 deliberately did not create another real voucher.

The unrelated general reminder worker remains stopped after its earlier system-clock jump failure; this release check did not restart it or send reminders. PostgreSQL teardown ResourceWarnings appeared in some regression tests although assertions passed. Accounting document/Tally workers are running.
