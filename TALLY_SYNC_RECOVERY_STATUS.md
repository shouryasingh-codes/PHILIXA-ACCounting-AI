# Tally sync restoration — 4 November 2026

The dedicated tally-worker was stopped. Restored it and added unless-stopped
restart policy. The unrelated general worker remains untouched. Removed 1,012
orphan cron wakeups only after an atomic check confirmed absent ARQ payloads.
Pending actions and existing job payloads were preserved.

Fixed connector diagnostic version allowlist to accept installed 3.8.0;
13 connector status tests pass. Live helper status now reports protocol 11,
receipt capable, live_available.

Before restoring dispatch, read-only checks established one queued accounting
action (9883c49d353b5b8b20d1de26296acf9e), automation paused, and no uncertain
company dispatch blockers. The first startup approval was rejected due to
unknown scope; after those checks the normal worker restoration was approved.
One guarded sync tick processed the existing user-approved receipt action.

Final result: failed, uncertain=false. Tally explicitly rejected Receipt Note
PH-GRN-4c26d9ed54ef76e3a238fd2d with voucher date missing error, approved date
2026-11-04. No date changed, no duplicate action created, no successful native
posting claimed. Educational date restrictions are a possible explanation;
this run did not independently prove license/date configuration. A corrected
date requires explicit user facts/approval and a new validated preview.
