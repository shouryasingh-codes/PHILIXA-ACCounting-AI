# Stock-count correction implementation and acceptance gates

The existing business LangGraph routes `stock_count_set` and `inventory_change` to its Tally tool. Purchase remains a distinct operation. Vague add/remove requests clarify; relative changes, sale, returns and posted-voucher deletion are not executable in this milestone. Structured clarification choices carry an expiring persisted TallyAction draft bound to workspace/user/session. Existing meeting-history RAG is unchanged.

`stock_count_set` accepts company_id, item_name, target_quantity (zero allowed), unit, counted_at (timezone-aware current IST day) and reason. Company confirmation is explicit. Complete saved masters, an approved company and configured non-GST single-godown test pilot are required. It saves an unsubmitted draft. `/actions/{token}/review` obtains a live baseline and whole-company transaction revision, and produces an expiring preview on the same action. Only the normal authenticated confirmation can queue it. Drafts cannot be confirmed directly. Reconnect never grants approval. Previous-day/future counts, changed masters/config/device, pending item entries and uncertain imports require review.

The PostgreSQL worker and Windows helper serialize company operations. Protocol 3 has isolated count job delivery; protocol 2 helpers retain purchase/snapshot support. Count jobs are bound to persisted action type, payload, workspace, approved company, device credential version, active owner/admin and configuration. The helper uses a cross-process file mutex and records submission before import. Unknown results reconcile without another import. Verification checks Physical Stock identity markers and fields, resulting stock and transaction revision excluding the newly imported voucher. A conflict after submission needs manual review. Draft cancellation cannot resurrect on a late validation response.

The existing JSON action payload stores the new operation and baseline; no database migration is needed. Draft/awaiting_review states are additive. Current action status replaces controls/messages instead of appending repeated status responses. Count forms ask for final count/time/reason, not supplier/rate.

## Important: count posting is disabled pending real acceptance

`COUNT_CODEC_CERTIFIED` in the shared count module deliberately remains false. The XML builder and identity matcher are candidate code tested against synthetic fixtures, not a certified installed-version export. Unknown receipt/delivery tracking also blocks execution; the candidate ISDELIVERYNOTE flag is not treated as evidence when missing. Do not flip this gate based on synthetic tests.

Before enabling, obtain an isolated-company manual Physical Stock export on the installed Tally version; validate its schema, persisted REMOTEID/reference/narration, physical-difference configuration and how to reliably prove receipt/delivery/unbilled inventory disabled. Check in a sanitized fixture and flag evidence, adapt the reader/builder as needed, then verify 10→8, 8→12 and zero against same-date Stock Summary/Physical Stock Register, exactly one voucher per confirmation. Verify offline save→reconnect→review→confirm, concurrent manual activity and crash/timeout outcomes. Only then enable the codec in a reviewed release.

Tally was unreachable during this implementation. On 9 October 2026, the existing EDU installation's date restrictions also prevent treating a backdated test as current-day count acceptance. Do not silently change a count date to obtain a successful import. Clean Windows install/update/reconnect, hosted HTTPS phone voice/typed acceptance and real model routing accuracy remain pending.

## Automated evidence

`python -m unittest scripts.test_tally_count scripts.test_tally_sync scripts.test_business_graph scripts.test_tally_reads scripts.test_tally -q`

The 100 language cases are reviewed template variants exercised against deliberately incorrect model routing. They measure deterministic safety guards, not production LLM accuracy or the requested ≥95% model-routing gate. Existing graph execution/RAG bypass, zero count, stale same-quantity revisions, unknown capabilities, uncertainty/no-reimport, identity changes, approval ownership and offline draft/review/cancel are exercised without actual Tally imports. Run voice/history scripts separately.
