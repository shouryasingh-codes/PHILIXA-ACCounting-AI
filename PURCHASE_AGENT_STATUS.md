# Purchase context assistant — 29 October 2026

## 30 October research correction — use this diagnosis going forward

The exact blocked-file policy ID is Microsoft's `VerifiedAndReputableDesktop` / Smart App Control (SAC) policy, not evidence by itself that this is a company-managed PC. Read-only registry verification returned `VerifiedAndReputablePolicyState=1`. Microsoft documents no ordinary per-app SAC exception, so generic “ask an admin to allow just this executable” is not a verified solution for this case. No policy was modified.

The packaged `FileNotFoundError` is a separate confirmed symptom. Its exact missing runtime file is not established; the build manifest already includes `certifi/cacert.pem`. The CA-path change remains a candidate fix, despite passing source TLS tests. Do not claim it fixed packaged networking until that test runs successfully in a supported approved distribution/testing environment.

Supported next assessment: Store-distributed MSIX compatibility (Store signing; correct account eligibility and certification required), or direct distribution with an eligible publicly trusted signer. Azure Public Trust individual signing is currently listed only for US/Canada; India eligibility must not be assumed. Raw EXE/MSI Store submission still needs publisher signing. Full research and 25-source register: `output/connector-research-2026-10-30/brief.md`.

## 30 October continuation

- Read-only Code Integrity events 3077/3033 confirm that the unsigned 3.7 candidate and the attempted 3.6 rollback installer failed the device's Enterprise signing requirements (policy ID `0283ac0f-fff1-49ae-ada1-8a933130cad6`). No security policy was altered and no blocked executable was rerouted around that policy.
- No currently valid private code-signing certificate was found in the current-user certificate store (count zero).
- Frozen CA-path configuration moved into `helper/tls.py`, captures a stable path, and fails closed if the bundle is missing. Two source unit tests pass: real CA loading with certificate/hostname verification retained; missing bundle rejection. These are not packaged-executable acceptance.
- Public release now requires both packaged transport/history/invoice/MCP checks and a valid Authenticode signature. Candidates are staged outside downloads. `-ValidateOnly` supports revalidating an externally signed candidate before `-Publish`; a failed gate records no successful publication. PowerShell syntax validation passed.
- Remaining dependency is normal device-admin/trusted application approval and a properly trusted signed distribution. Source changes are ready for a new candidate build, but its packaged transport, installation and paired protocol 10 acceptance remain unverified. Feature remains off; previous installed 3.7 connection problem remains unresolved.

## Latest acceptance update (supersedes earlier blockers below)

- After the user disconnected VPN, the live Groq strict extraction probe passed (seven explicit fields). Direct read-only Tally history also passed: six vouchers, five evidenced lines, latest rate 350.00, no posting.
- Live testing exposed date values/quotes such as `date 02-10-2026`. Date evidence now normalises matching Indian dates to ISO and rejects conflicting date evidence; extraction prompt separates item and unit. The 14-test agent/bridge suite passed.
- Connector 3.7.0 was installed with pairing retained, journal integrity `ok`, connection settings retained and startup registration verified. However, its packaged HTTPX transport test then exposed `FileNotFoundError`; paired protocol 10 acceptance did NOT pass.
- A bundled-CA-path fix and explicit startup diagnostics were added in source. Certificate verification remains enabled. That candidate has NOT passed packaged transport acceptance: Windows Application Control blocked execution (WinError 4551). Attempting the existing 3.6 installer for rollback was also blocked. Therefore rollback was not completed; installed version remains 3.7.0 and its live connection is unresolved.
- The protocol 10 download is withheld; the download route selects the previous 3.6 release. The purchase-agent flag is restored to `0`.
- The build script now stages candidates outside downloads and requires packaged transport/history/invoice/MCP checks before optional `-Publish`. Windows policy denial also prevents promotion. Build-script syntax passed; new candidate runtime acceptance remains blocked.
- A local review-only acceptance draft was created; no Tally entry was posted. Browser continuation was unavailable during this final run, so no new full browser acceptance is claimed.

Next dependency: resolve the Windows Application Control execution restriction through the device's normal trusted/signed application approval path. Then run packaged transport acceptance, install the validated candidate, verify paired history, finish live review/reload checks and enable the review-mode feature. Do not bypass application control or disable TLS validation.

Implemented behind `PHILIXA_PURCHASE_AGENT_ENABLED=1`; default remains off.
This is a review-mode implementation, not a claim of production accuracy or completed live acceptance.

## Delivered

- Strict Groq structured purchase understanding with exact message evidence, multi-line updates, atomic corrections, revision checks and request deduplication. No model-generated SQL/XML.
- LangGraph workflow with PostgreSQL JSON checkpoints and restart/resume support. Six tool-round ceiling and duplicate-call protection.
- Native read-only protocol 10 purchase history: exact native company/supplier/item identities; 180-day query, captured generations, 100-record pages, maximum 5,000 records. Incomplete captures cannot produce a latest-rate suggestion.
- PostgreSQL history cache, 15-minute freshness checks, ARQ refresh/recovery, bounded transient retries, current permission/device/master checks. Historical rates remain suggestions; explicit user rates are retained.
- Compact chat proposal, grouped missing facts, source/check disclosure, grouped rate acceptance and existing final preview/confirmation. Stale evidence/revisions block approval and queued dispatch.
- Existing OCR and real-company posting gates retained. No Tally voucher posted by this implementation's acceptance probes.
- Additive migration `b4u1v2w3x4y5` applied to the local database.
- Versioned connector `data/downloads/PhilixaTallyConnectorSetup-3.7.0.exe` built with bundled MCP. Existing installed connector was not replaced.

## Verification evidence

- Prior broad regression run: 85 tests passed (agent, conversation, GST chat, business graph, count, customer, GST, recovery, duplicate bridge). Latest targeted legacy regression run: 22 tests passed.
- Agent suite: grounding, multiple lines, durable corrections/idempotency, cross-workspace isolation, history generations/pages/limits, stale-cache abstention, permission changes, bounded retry and PostgreSQL graph resume verified. Additional checks cover tool budget and stale action evidence.
- Protocol 10 bridge test verifies old helpers cannot consume history requests and a read requires no posting action. The test permits unrelated legacy snapshot jobs from the running stock worker; those synthetic jobs never contact Tally.
- JavaScript tests pass for chat restore/stale reply handling and compact proposals, visible context errors and evidence-bound suggestion acceptance.
- Packaged connector self-tests pass: history/native identity, full-financial-year duplicate check, MCP stdio (87 tools) and direct-write blocking.
- Installer SHA256: `302A89169A8F101A39A9626A970B87A101CA69EF25B07AFA4853F65D2C2399A9`.
- Earlier read-only native probe: Philixa Test / Sharma Traders / Cement yielded six matching vouchers, five usable lines, latest evidenced rate 350.00. No voucher was created.
- Browser: existing saved draft resumed as a compact proposal; grouped missing facts and unavailable context were visible; same review survived reload. A stale supplier selection refreshed the current draft rather than replaying it. Screenshot capture was unavailable; browser accessibility state was inspected.

## Still unverified / blocked

- Live Groq extraction request received HTTP 403 / Cloudflare Access denied. Requests from both the application container and Windows showed the access problem. This is not an extraction-accuracy pass. No replacement provider or paid retry loop was added.
- Fresh end-to-end message → Groq → native history → final validated review is pending provider access and an open Tally test company with the updated connector.
- Updated connector is built and self-tested; installation and live paired protocol 10 acceptance are pending. Native read-only probe does not substitute for that acceptance.
- No new native posting acceptance performed; test-company posting remains separately authorised. Real-company writes remain governed by existing release gates.
- Real-accountant timing/accuracy and representative workload comparison remain unverified. Message/correction events and active-review timing are instrumented; no time-saving percentage is claimed.

The rollout flag was enabled temporarily for local browser checks, then restored to its original absent/default-off setting. App and document worker were recreated to apply and restore that setting; database volumes were preserved.
