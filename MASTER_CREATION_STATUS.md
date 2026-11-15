# Approved Tally master creation — implementation status

Date: 12 November 2026 (IST).

**Implemented in source; native activation blocked.** The application can prepare an exact supplier/item/unit creation preview. An installed, online protocol-12 connector is required before confirmation can queue a native write. The newly built unsigned connector was blocked by Windows Application Control; it was not installed or published. This is not a completed native end-to-end acceptance.

## Behaviour

- Existing authenticated draft review prepares a durable, scoped master preview without calling Groq or importing XML directly from the server.
- Explicit confirmation binds the current user/session, exact company, draft revision, source evidence and approved definitions. Changed or removed evidence invalidates an unsubmitted review.
- Only the explicitly configured isolated test company and paired protocol-12 device can execute creation. Old/offline helpers cannot confirm this action.
- Creation is create-only, with zero opening balances. Conflicting native identities/fields require review; existing masters are not overwritten.
- New units require explicit decimal precision and UQC. Supplier registration type, HSN and GST rates are not invented. Purchase validation remains separate and may require further native tax setup.
- The helper journals the action before import and verifies native identities/fields afterwards. Uncertain or partially completed imports reconcile the same action instead of blindly resending a batch.
- Verified masters do not mark the purchase bill/task complete or create a purchase voucher.

## Evidence

- Broad regression: 397 tests passed (`data/engineering-audit/final-regression.json`).
- Focused run: 58 tests passed (`masters-tests-final.log`).
- Final focused checks after readiness/source guards: 19 tests passed (`masters-ready-tests-final.log`). Counts overlap; they are not additive. Nonfatal PostgreSQL connection ResourceWarnings remain in the final focused log.
- Ten JavaScript controller suites passed (`masters-ui-results.json`), including direct preview wiring, concurrent-click protection and clearing an unrelated purchase task reference. These are controller tests, not a fresh browser acceptance.
- Windows source-runtime synthetic master test passed (`master-windows-source.json`); it used fake native transport, not real Tally.
- Candidate packaged acceptance did not pass. An earlier artifact exposed a journal file-handle cleanup defect, which was fixed and source-tested. Windows blocked execution of the rebuilt artifact before final packaged acceptance could complete.
- Application and both general/Tally workers are running after reload/restart. No Tally master or voucher was created during this work. No data volumes were reset; no commit or push was made.

## Blocker and next gate

Candidate: `data/connector-candidates/PhilixaTallyConnectorSetup-3.8.1-mcp-candidate.exe`.

SHA-256: `d0418a743729584be170e3dd571ded759fcd72a5829119844c9f35e2b6bd819d`.

Signature: NotSigned. Windows reported: “An Application Control policy has blocked this file.” Build/runtime logs: `master-connector-build.log`, `master-connector-acceptance.log`, `master-connector-acceptance-final.log` in `data/engineering-audit/`.

The remaining gate is a trusted connector build accepted by Windows, then packaged-runtime, browser and authorised isolated native test-company acceptance. Store/MSIX distribution remains a separate gate. Windows protections were not changed, and alternate paths were not used to bypass the block. Existing public connector downloads remain unchanged.

## Main source references

### Trusted-update follow-up (12 November)

Local prerequisite checks found zero code-signing certificates in both CurrentUser/My and LocalMachine/My, no Windows SDK installation at the standard Windows Kits/10/bin location, and no owner-verified Partner Center identity supplied. These are release prerequisites, not a pairing-code problem.

Fixed stale MSIX build metadata: package name, output directory and evidence now derive version/protocol from the actual runtime (currently 3.8.1/protocol 12), rather than reporting 3.7.1/protocol 10. A regression reproduced this defect before the change. Updated the manifest regression to assert the actual runtime version. The source-only MSIX, connector-runtime and connector-lifecycle suites passed 28 tests; PowerShell parsing and diff whitespace checks passed. Log: `data/engineering-audit/trusted-update-source-tests.log`. No signed package was produced, installed or submitted; these checks do not establish Windows trust or native acceptance.

Next owner dependency: create/verify the Microsoft Store developer account and reserve the Philixa connector app, then provide its actual package identity name, publisher, publisher display name and Store product ID. Identity verification requires the owner's participation. Windows SDK packaging tools are also needed before building the MSIX submission candidate. Microsoft documents that the Store signs submitted MSIX packages: https://learn.microsoft.com/en-us/windows/apps/publish/faq/get-started-with-the-microsoft-store . Store certification and the supported Windows test matrix remain required; installation success is not promised from source tests.

- `app/services/master_creation_service.py`: scoped preview, revision/evidence guards, approval readiness and durable dispatch.
- `app/services/tally_master_actions.py`: validated native definitions, create-only XML, journal and readback verification.
- `app/services/tally_sync.py`, `tally_sync_protocol.py`, `tally_bridge.py` and `app/api/v1/routes_tally_bridge.py`: existing approval/paired-device pipeline and protocol-12 dispatch.
- `app/services/task_agent_tools.py`, `task_agent_service.py` and `app/api/v1/routes_business.py`: agent/API integration without purchase false-success.
- `app/web/business-tally.js`: direct preview UI and explicit confirmation handoff.
- `scripts/test_master_creation.py`, `scripts/test_engineering_audit.py`, `scripts/test_connector_ui.cjs`: regression evidence.
