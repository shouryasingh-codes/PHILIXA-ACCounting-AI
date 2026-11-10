# Philixa controlled pilot — Day 10

This is a supervised, test-company pilot, not a production accuracy certification.

**Launch default: review mode; real-company writes disabled.** Real posting requires separately authorised staged rollout into an exact supported licensed company. That real-company enablement path is not yet implemented; the test-company flag cannot substitute for it. See `LAUNCH_ROLLOUT.md` for current enforcement and future stage boundaries.

## Supported workflow

Private original upload → durable processing → saved draft and original side by side → accountant correction → validation and duplicate check → explicit approval → durable action → installed helper → native voucher verification. Digital PDF automation additionally requires an active company policy with every required limit and approved identities. Keep automation paused during initial onboarding.

Domestic regular goods purchases with supported company, supplier, item, unit, purchase and GST masters are in scope. Intra/inter-state mixed rates, disclosed discounts and explicit round-off within ₹1 are supported when evidence and masters agree. Missing or ambiguous identities/taxes, wrong buyer/company and duplicate references block posting.

Photos/scans/handwriting require review. The Day 9 extraction follow-up fixed the observed supplier/header-discount and unit-reading gaps; the unchanged six-file synthetic corpus now scores 166/166 strict fields and 6/6 exact complete files. The earlier 154/166 failing run remains archived. This small corpus does not establish real accountant accuracy or time savings. Two-scale crop consensus retains original low-confidence evidence and review warnings. Do not enable unattended photo posting.

## Windows helper and deployment

Current helper is **3.6.0, protocol 9**. The original plan's v7 is an older protocol, not the release version to downgrade to. Legacy operations remain compatible; new guarded operations require their supported helper protocol. Use the validated versioned installer, not an unversioned historical executable. Build and installed acceptance evidence belong in `data/day10/`.

The installer is an **unsigned Windows pilot**. It runs per user, stores pairing in Windows Credential Manager and registers an interactive, least-privilege scheduled task. Do not share pairing credentials. Windows user session, computer, app services and local Tally must be available for live posting. When Tally is closed, saved data/drafts remain available; current Tally reads and writes cannot happen until it reopens.

An update asks the old helper to finish its current operation. Busy updates defer instead of killing a writer; startup-registration failure restores the previous executable. Settings, credentials and the SQLite submission journal must survive updates. Never delete `%LOCALAPPDATA%\PhilixaConnect` to repair a connection.

Printed `Page n of m` / `Page n / m` evidence is checked per detected invoice. Missing, repeated or out-of-order pages block posting until the complete original is uploaded, even if model output omits the warning or draft values are edited. Separate complete invoices can each start at page 1. Unnumbered sources do not provide enough evidence to guarantee missing-page detection. The versioned safety fixture catalog is in `scripts/fixtures/release/manifest.json`.

## Recovery procedure

Posting uses action-specific identity and durable journal/state. Explicit human or policy authorization is recorded before external posting; policy is rechecked by worker dispatch and helper claim. See `POSTING_AUTHORIZATION.md` for audit fields, reservation/decision linkage and uncertain-delivery semantics.

1. Reopen the saved bill and use its existing action/status. Refresh status or reconcile the **same action** after an interrupted submission.
2. `verification_pending` means delivery is uncertain. Do not create a replacement draft, change the invoice reference, remove the SQLite journal or repeatedly import the voucher. Absence in one read is not proof that Tally rejected it.
3. If verification mismatches, retain the original evidence/action and ask the accountant to compare the native voucher. A marker alone never overrides mismatched quantities, rates, taxes or totals.
4. For an explicit rejection, correct the actual reason and create a fresh approved preview only through the app's permitted recovery flow. Do not alter an approved date silently.
5. Restore connectivity/permissions before retrying an unsent action. Revoked membership, company access, helper credentials, changed masters or paused automation must block new dispatch. Already dispatched uncertain actions retain their uncertainty.
6. Restart only the needed application/worker/helper. Preserve PostgreSQL, MinIO, Redis volumes, private originals, pairing and the helper journal. Do not run `docker compose down -v` or delete containers/volumes as a reset procedure.

Tally Educational Mode may restrict entry dates. The app must show the rejection and retain the approved date; an accountant must choose and approve an allowed practice date deliberately. Use licensed Tally and the real document date for production accounting.

## Pilot acceptance boundary

Real-business unattended automation additionally requires at least **200 distinct representative accountant-labelled real invoices total, including a separate untouched 100-invoice held-out set**. Synthetic invoices and duplicate format copies do not count. Sample size alone does not approve release; final quality thresholds must be defined before held-out evaluation. See `REAL_AUTOMATION_GATE.md`. This is currently an unsatisfied release requirement, not a runtime policy change.

Within the frozen auto-post candidate subset, **zero critical errors** are required: company/supplier identity, invoice reference/date, missing/extra/wrong lines, taxes, totals or duplicate posting. One critical error fails the gate; failed candidates cannot be removed or relabelled after seeing outcomes. An empty/unevaluated subset or an unverified timeout cannot count as a passing result.

This is a rollout gate, not a "100% accuracy" guarantee. Every policy needs representative evidence for its own company/supplier/item/format/tax/amount scope. Insufficient eligible examples keep that policy in **shadow mode**, with human approval required for posting. Global sample counts and another policy's passing result cannot authorize an untested policy. See `REAL_AUTOMATION_GATE.md` for scope/version linkage and the distinction between documented release requirements and runtime enforcement.

Suggested product target, **not a current claim**: on matched representative real workload, median active handling time including review/corrections should be at least **50% lower** than the manual baseline. Include intake, approval, exceptions and completion/verification work; compare equivalent completed tasks and disclose failures/setup overhead. Measure both medians on the same sample as specified in `REAL_AUTOMATION_GATE.md`. Safety and per-policy evidence gates still apply independently.

The existing chat, stock, purchase, physical count, customer, connector and source-edge-case synthetic regression gate has passed: 313 backend tests, 14 Windows lifecycle tests and 11 JavaScript suites. The versioned fixture catalog also passes its 17 selected assertions. See `RELEASE_GATES_STATUS.md` for scope, fixture correction, evidence and reproduction. This gate is separate from native pilot acceptance and real-world accuracy evaluation.

Recovery injection uses synthetic transports and separate real operating-system processes; it does not deliberately crash Tally during a real import. Existing test-company native vouchers are read back after application/worker/helper recovery. That proves a bounded supported path, not every Tally version, tax treatment or crash boundary. Existing dummy vouchers must not be reposted.

Start with a small accountant-supervised set, review every result against the original, and record corrections, active review time, failures and provider cost. Keep original bills private. Production rollout requires real anonymised bills/accountant evaluation, resolution of extraction gaps, backup/restore validation and operational monitoring.

Reproduce safe recovery tests:

```powershell
docker compose exec -T -e LITELLM_LOCAL_MODEL_COST_MAP=True app python -m unittest scripts.test_day10_recovery -v
.\.helper-build\Scripts\python.exe -m unittest scripts.test_connector_runtime -v
docker compose exec -T -e LITELLM_LOCAL_MODEL_COST_MAP=True app python -m scripts.day10_pilot_probe probe
```

The probe reads existing vouchers and durable data only. It requires paused/unset automation and no active accounting actions; it never approves or imports a purchase.
