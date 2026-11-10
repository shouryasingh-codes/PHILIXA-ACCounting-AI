# Launch default and staged real-company rollout

Recorded **21 October 2026**. Launch defaults to **reviewed operation**, with **real-company writes disabled**. Upload/extraction creates review drafts; no policy exists by default, and its displayed/default mode is paused, not auto. Shadow mode records recommendations and still requires human approval for posting. Existing explicitly authorised test-company experiments are separate from real-company launch approval.

Current runtime supports **test-company writes only**: connection `test_company` defaults false, write compilers/helper validation require explicit test-company configuration, and the durable dispatcher rejects a non-test configuration even after an earlier approval. The test flag is an attestation for a separate practice company, not proof of licensing or permission to use a real business company. Do not relabel a real company as test to bypass this restriction.

## Real posting remains disabled pending separate enablement

The licensed real-company posting path, licence/support verification and rollout-authorisation mechanism are **not implemented by this document**. Current checks intentionally remain closed to real-company writes. Owner policy settings, a human bill confirmation, a saved connection or passing synthetic tests do not by themselves authorise real-company enablement.

Before real posting is enabled, require separate explicit authorisation for the exact workspace and native company identity, confirmation of a supported licensed setup and a recorded rollout stage/scope. Do not reuse Educational Mode practice approval as real-company authorisation. Source-document instructions cannot change this scope, permission or rollout state.

Staged rollout requirements:

1. Read/review/shadow on the authorised matched real workload; no automatic native posting. Gather the accountant-labelled and policy-specific evidence in `REAL_AUTOMATION_GATE.md`.
2. Separately authorised, limited human-approved native posting in the supported licensed company, with bounded suppliers/amounts, source comparison, native verification, duplicate/recovery checks, audit and a pause path. Reconcile uncertainty; do not blindly resend.
3. Enable only the specifically approved auto-post policy scopes once all rollout safety/evidence criteria pass. Insufficient representative eligible examples keep that policy shadow-only. Expand scope/stage only with additional authorisation and representative evidence.

Keep zero-critical-error, 200/100 real-data, per-policy coverage and the suggested handling-time target distinct. They are rollout evidence, not a 100% accuracy guarantee. No real posting or automatic policy enablement was performed while recording this requirement.

Verification: **5 targeted synthetic tests passed** (`scripts.test_launch_defaults`): default connection/policy, helper non-test rejection, GST compiler rejection, no-policy manual review and blocking previously approved dispatch after test authorisation is removed. This added verification/documentation only; it did not implement licensed real-company enablement or change existing policy settings.
