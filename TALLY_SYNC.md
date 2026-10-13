# Tally saved stock and purchase sync pilot

## Implemented behavior

Approved companies receive durable PostgreSQL snapshots. The dedicated Tally worker refreshes available companies every five minutes, on helper reconnect, on requested refresh, and after verified purchases. Complete snapshots replace previous generations atomically. Failed/incomplete exports retain the previous complete generation. Each native XML collection has a 10 MB limit; bridge pages are bounded and total accepted snapshot data is limited to 40 MB. Oversized companies are reported unsupported rather than silently truncated.

Stock requests use the existing business LangGraph and permissions, prefer live Tally data, and fall back to complete saved snapshots. Replies identify Live/Last synced, company, unit, as-of date and collection time. Pending purchases are separate from confirmed stock. Uncertain imports suppress the expected total. Different companies/compound units are not added together. No snapshot means unknown stock, not zero. Stock/purchase execution does not use embeddings, RAG, generated SQL or model synthesis; existing meeting-history RAG is unchanged.

Purchases use existing masters, quantity validation, voucher builder and confirmation records. Vague “add bags” requests clarify purchase versus stock adjustment. Only explicitly configured non-GST test companies support this purchase queue; offline sales and direct stock adjustments are excluded. Offline previews require complete saved masters. Confirmation binds the immutable payload, original date and GUID to the authenticated user/session and saves a queued action. Confirmed actions do not expire with the preview.

The worker serializes company writes, revalidates current authority/configuration/masters, checks GUID before import and verifies the imported voucher. PostgreSQL stores the durable queue; Redis carries bridge jobs/wakeups. Helper SQLite records submission before import. Duplicate deliveries and restarts do not blindly repeat uncertain imports. Unresolved uncertain entries requiring review freeze further dispatch for that company. Successful verification and refreshed stock remove the pending contribution in one transaction. Helper revocation/replacement invalidates bound actions rather than silently transferring writes.

## Running the updated pilot

Apply `alembic upgrade head`, deploy the changed backend, and run the dedicated `tally-worker` Compose service (or `arq app.tally_worker.WorkerSettings`). Its only scheduled task is Tally sync; it does not enable reminder or embedding cron jobs. Keep PostgreSQL, Redis and this worker available for background sync.

Install the updated `data/downloads/PhilixaConnectSetup.exe` on the Tally PC. Protocol 2 adds typed snapshot/validation/post/reconcile operations. Protocol 1 helpers remain read-only and receive an update-required message for new operations. Pair/approve companies through the existing UI. The existing direct-local developer transport and legacy unapproved single-company write pilot remain compatibility paths; a paired helper never falls back to the server's localhost for configuration reads.

Tally does not need to remain available for saved answers or queued confirmation. Actual posting requires the helper, Tally listener and approved loaded company. Original approved dates are preserved; Tally Educational Mode can reject them. Queued entries can be cancelled before submission; submitted/uncertain entries cannot be described as rolled back.

## Verification and acceptance limits

Automated tests use isolated PostgreSQL fixtures and mocked imports: saved graph reads, offline preview/confirmation, idempotency, cancellation race, authority/device changes, original date, changed masters, incomplete and large snapshots, durable helper journal, uncertain reconciliation and snapshot/pending overlap. Existing graph/read, legacy purchase pilot, history scope and voice regressions were exercised.

Actual read-only verification used the loaded `Philixa Test` company: live Cement stock was 0 bags, the saved graph answer matched, and an offline purchase preview used its real saved masters. Offline transport was simulated; the preview was not confirmed and no real voucher was written.

Subsequent user-confirmed acceptance on 9 October 2026 imported purchase voucher 1, dated 1 October 2026: Sharma Traders, Cement 5 bags at INR 350, total INR 1750, Main Location. The approved financial/inventory fields matched the actual voucher and the refreshed snapshot showed 5 bags; its action is verified. Tally assigned a native GUID, so reconciliation now accepts the exact action narration plus the supplier's unique bill reference, followed by full field verification. Native exports put bill references in ALLLEDGERENTRIES and empty placeholders in compact LEDGERENTRIES; regression coverage includes this shape. The existing voucher was reconciled through the locked sync service with imports prohibited during the operator check. The packaged helper must be updated for this verifier fix on future entries.

Still required before claiming the milestone complete:

- Physically close/reopen Tally around a confirmed offline purchase; verify automatic reconciliation, exactly one voucher, stock against the Tally report and timeout/restart behavior. The online user-confirmed purchase and refreshed stock above do not prove this offline sequence.
- Verify clean Windows install/uninstall, startup, paired-helper reconnect and the packaged binary. This machine's Windows Application Control blocked executing the unsigned generated EXE. Source helper self-test passed GUI, credential storage, allowlist and actual local company discovery; that is not packaged-install acceptance. Do not bypass the OS policy.
- Verify hosted HTTPS phone typed/voice access and continuous background-worker operation. Localhost acceptance does not prove hosted 24/7 availability.

## Repeatable checks

`python -m unittest scripts.test_tally_sync scripts.test_business_graph scripts.test_tally_reads -q`

`python -m unittest scripts.test_tally -q`

`python -m scripts.test_business_voice -q`

`python -m scripts.test_history_scope`

`scripts/run_tally_sync_read_live.py` performs disposable paired read-only acceptance against local Tally; it creates no real voucher. Run voice/history scripts separately because their test runners have independent entry points.
