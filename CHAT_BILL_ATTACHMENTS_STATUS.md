# Chat bill attachments — local review pilot

Implemented 6 November 2026. This is a supported vertical slice, not a claim of perfect OCR or complete accountant automation.

## Available now

- Paperclip opens a file picker. Pending files show company, filename, size, image thumbnail where applicable, and Remove. File-only Send works.
- Existing private batch/upload APIs stage files individually. Failed uploads retain successful references; command retry retains its request ID. Identical document IDs are deduplicated.
- New migration `g9z6a7b8c9d0` records authoritative message/document/task links. Acceptance checks ownership, company, revision, trash and idempotency before committing links and the queued task together.
- Existing document validation/extraction creates or reuses existing drafts. Worker completion notifications and recovery continue without browser-driven extraction. Worker queue is passed explicitly to extraction dispatch.
- Chat displays private originals, progress, sourced summary and exact Review bill links. Reload restores server-owned associations; client transcript metadata grants no access.
- Agent receives an exact source index and document tools first. `read_bill_fields` returns selected current draft facts; no unsolicited purchase-history sync is needed for document Q&A. Ambiguous multiple bills require selection. New chat drafts cannot replace attached-source drafts.
- Original extraction evidence is retained; explicit changed draft values get correction provenance/discrepancy metadata. Revision and extraction-generation checks remain enforced.
- Existing review, tax, duplicate, permission, outbox and posting gates remain in force. This pilot performed no Tally posting.

## Verified

1. Browser: existing authorised dummy PDF attached and sent. Original document and existing verified draft were reused; exactly one draft remained for that document.
2. Browser: fresh-hash synthetic PDF traversed private upload, validation, extraction, saved draft and inline result. The initial run exposed a missing immediate worker enqueue; the queue forwarding fix has a dedicated regression test.
3. Browser: Review opened the fresh PDF, its two item lines, invoice reference and ₹1,167 total. Reload restored the attachment and result.
4. Browser: “Is bill ka total kitna hai?” returned ₹1,167 from the attached draft using one model response and an exact document-field read. Initial upload/reuse itself used zero planner calls.
5. PostgreSQL tests cover atomic links/replay, stale revisions, foreign sources, owner/company permissions, source revocation, recovery dispatch, extraction reuse, read-only status, source-index compaction and field reads. Concurrent Send and ordinal bill references are covered too.
6. Passing test groups: 42 attachment/chat/agent checks; 38 extraction/quota/selection checks; subsequent focused 26-check rerun. Four JavaScript suites passed for attachments, chat refresh, archive intake and extraction review. These counts overlap across reruns and should not be added as unique coverage.

Reproduce evidence with `python -m scripts.chat_attachment_acceptance_report`. Sanitized synthetic fixture evidence is in `output/chat-attachments-acceptance.json`. No action ID was created for either attachment task.

## Rollout and remaining acceptance

`PHILIXA_CHAT_ATTACHMENTS_ENABLED` defaults to OFF in code and is ON only in this local development environment for review testing. OFF restores the legacy upload modal. Existing task-agent and provider budgets are unchanged.

Remaining wider acceptance: representative photo/JPG/PNG and multi-invoice layouts, 50-file browser throughput, responsive/mobile interactions, richer multi-bill follow-up/correction scenarios and interrupted-upload recovery across full browser closure. Synthetic recovery tests passed; a dedicated browser-closed mid-extraction/worker-restart matrix is still needed. Do not call the entire original plan production-complete yet.

Multi-page sources with unverified existing invoice boundaries explicitly require review. General arbitrary invoice splitting is not claimed. Broad real-world OCR accuracy remains unverified.

Staged but unsent originals remain in the private Bills archive under existing ownership/trash rules; they are not automatically deleted or retried for paid extraction. Automatic abandoned-upload retention cleanup is deferred to a separately specified retention policy. Chat deletion never cascades into accounting records.

The browser screenshot capture API failed during the final check; the accessibility state and database evidence verified the result, but no screenshot artifact is claimed.
