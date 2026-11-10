# Recoverable bill Trash — 2026-10-28

Implemented owner-scoped Trash and Restore from Upload bills / originals. `Show` selects Active bills or Trash within the selected saved batch. Trash applies to a source across all batches and hides its linked unposted drafts from the list and review queue. Original private bytes and draft history remain stored; no permanent-delete endpoint exists.

Backend authorization and company scope are unchanged. Draft mutations check the current source state; trash/restore increments linked draft revisions and records audit events. Processing documents are blocked. Any document with a linked accounting action (including a preview) is protected; this feature does not cancel actions or delete Tally vouchers. Reuploading a trashed identical file requests Restore instead of creating a duplicate. Recovery workers ignore trashed sources.

Migration a3t0u1v2w3x4 adds only nullable indexed bill_documents.trashed_at; applied successfully. Document worker reloaded; no containers or volumes deleted.

Validation:
- 24 existing document, draft and review tests passed.
- 3 added integration tests passed: source bytes and draft visibility/revisions, linked accounting-action protection, workspace/user/role and processing guards.
- Real documents JS harness passed confirmation cancellation, trash/restore, private viewer, scope cleanup and existing upload/polling behavior.
- Browser tested the existing unposted public sahibill-gst-sample.png: confirm -> Trash -> Restore; final state restored in Active bills. Posted C01.pdf and practice purchase PDF show disabled Trash buttons. No Tally action posted or changed.
- Browser-native confirm initially interfered with automation. Replaced by explicit inline Confirm move to Trash / Cancel with visible explanation. Verified final inline flow in the browser; hidden confirmation controls receive scoped CSS protection.
- Screenshot output/document-trash-verified.png shows recoverable Trash. The sample was restored after screenshot.

Limit: action-linked documents cannot currently be hidden, even if the action is only an unused preview. Trash view is per saved batch; select the batch containing the original to Restore it.
