# Posting identity and authorization contract

Every supported posting uses its durable Tally action token and compiled action GUID/markers. Approved payloads are snapshotted before dispatch. Helper writes use the persistent company-identity + action-GUID SQLite journal; the server also persists action state before any external import. Uncertain delivery reconciles the same identity, never a blind replacement import or silent date/reference change.

## Explicit audit event

New human confirmations and durable-policy authorizations append a `posting_authorized` event to the existing append-only event store (`bill_evaluation_metrics`). It is committed in the same transaction as queued/submitting state, before an external write. It records action token/GUID, actor/session, target company identity, operation, approved payload SHA256 and event timestamp. This is application-level append-only evidence, not a claim of database-administrator-proof tamper resistance.

`authorization_type=human_approval` records the authenticated confirmation. `authorization_type=policy` additionally links the persisted policy revision, decision ID, action reservation and original-source hash. An automation marker alone cannot produce a policy authorization audit: its matching durable decision/reservation and actor are required. Repeated confirmation of the same already-approved action does not append another approval event or create a new posting.

Events work for actions without a bill draft too, including the legacy direct path. Bill-linked events are exposed as `authorization_events` by the existing scoped evaluation-metrics API. The change uses existing storage and requires no schema migration. Earlier actions are not backfilled with invented approval timestamps.

## Dispatch-time recheck

For policy-authorized actions, the worker rechecks policy before validation and immediately before a new post. Helper job claiming also rechecks it before granting the write payload. Checks cover active/unchanged policy revision and actor permissions, the action's durable reservation/day/amount, approved current supplier/item masters and unchanged original/draft evidence. Pause, revocation or changed policy/evidence stops an unsent automatic write. Human approval does not bypass company/workspace, action identity, approved arguments or current permission checks.

If an import has already been dispatched and delivery is uncertain, reconciliation remains read-only even if policy is paused. Pausing cannot retract an already accepted native voucher; it blocks a new dispatch. Audit/authorization does not itself imply native verification or bypass duplicate protection.

The real-data, per-policy representative-evidence, zero-critical-error and product-time targets in `REAL_AUTOMATION_GATE.md` remain separate rollout requirements. This authorization/audit implementation does not enable real-business rollout or implement that evidence gate.

## Verification — 21 October 2026

117 targeted tests passed across new authorization assertions, legacy direct integration, durable sync, automation/dispatch/helper-claim guards, customer/count/GST posting, protocol compatibility and scoped metrics. New tests distinguish human versus durable policy audit, reject an automation marker without decision/reservation, expose the scoped timestamped event, and verify repeated confirmation creates one authorization record. Legacy integration exercises PostgreSQL scope/concurrent confirmation, approval audit, cancellation, expiry and uncertain delivery with synthetic transport. No real voucher or external message was sent. An initial new legacy assertion missed its `select` import; it was corrected before this passing rerun. Some DB cleanup ResourceWarnings remain.

Reproduce the new assertions with `docker compose exec -T -e LITELLM_LOCAL_MODEL_COST_MAP=True app python -m unittest scripts.test_posting_authorization -v`. Full targeted log: `data/posting-authorization/tests.log`. The full release runner now also includes these assertions and the legacy integration; the earlier 313-test release report predates this implementation and must not be presented as a new full-suite run of it.

An additional **13 bulk-approval/draft tests passed**, including the 50-bill independent-result batch and revision guards (`data/posting-authorization/bulk-drafts.log`). Together these are 130 targeted test executions across the two non-overlapping module runs, not a newly completed full release-suite run.

Deployment follow-up: after verifying zero active accounting actions and zero auto policies, the Tally worker was restarted successfully and its ARQ startup/Redis connection checked. The first restart attempt was not executed because automatic approval review hit its usage limit; the user resumed and the same approved restart subsequently succeeded. No database reset, pairing change or native voucher posting was involved.
