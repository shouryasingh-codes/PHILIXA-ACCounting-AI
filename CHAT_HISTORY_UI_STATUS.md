# Recent chats — 1 November 2026

- Uniform left-aligned rows, consistent spacing, full-title hover text, ellipsis for
  overflow and a separate accessible trash button. Decorative prompt arrows removed
  from displayed titles; stored transcripts remain unchanged.
- Scoped, revision-checked soft deletion and Undo restore. Deleting the active chat
  clears its browser copy and selection. Accounting drafts/actions/vouchers are not
  deleted or replayed.
- Deleted conversations are excluded from reads/saves/lists. A stale browser tab
  cannot recreate a deleted conversation from its cached transcript on reload.
- Additive nullable `deleted_at` migration `c5v2w3x4y5z6` applied. Existing records
  retained; no permanent-delete operation introduced.
- 7 PostgreSQL conversation tests passed, including owner/workspace isolation,
  stale revisions, deletion/restore, message retention and no accounting actions.
- Existing browser DOM harness passed with added delete/Undo and stale-cache tests.
- Live browser layout and accessible delete controls verified after reload. Actual
  user conversations were not deleted as part of testing. Undo is offered in the
  current page after deletion.
- Cache versions: chat CSS 20, chat JavaScript 18.

Visual proof: `output/recent-chats-fixed-20261101.png`.
