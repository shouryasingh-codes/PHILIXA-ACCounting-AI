# Saved business chats

Private conversations are stored in PostgreSQL, scoped to the authenticated user and workspace. Recent Chats lists the latest 100 conversations. New chat creates a separate conversation when its first message is sent; prior conversations remain available. Titles come from the first user message without another AI call.

Selecting a conversation restores its transcript and report/preview UI. Reload restores the selected conversation. Browser storage is a fallback and migrates any existing same-tab transcript. Opening a chat never confirms/replays a business command. An older login session's preview is disabled; backend accounting approval checks remain authoritative.

Each conversation snapshot retains up to 300 messages and 2.5 MB. Save revisions prevent another tab from silently overwriting an updated chat. Failed saves keep the browser copy and block switching/New chat until saving succeeds. This stores discussion, not accounting records: approved vouchers and their verification remain in the existing Tally action workflow.

## API and migration

- `GET/POST /api/v1/business/conversations`: list or create a private chat.
- `GET/PUT /api/v1/business/conversations/{id}`: restore or save with an expected revision.
- Migration: `q3j0k1l2m3n4`, applied to the accounting development database.

## Verification

- Five focused PostgreSQL tests passed: two-chat retention, user/workspace isolation, stale revisions, cross-login preview safety, and workspace-switch create rejection.
- UI harness passed reload, new tab, delayed auth, legacy migration, sidebar reopening, browser-storage loss, scoped isolation, and no command replay.
- Business-context, graph and purchase-sync regressions passed.
- Actual in-app browser demo: created two read-only chats, reloaded, and reopened the first from Recent Chats. No paid AI calls or Tally writes were required.

```powershell
docker compose exec -T app python -m unittest scripts.test_business_conversations -q
node scripts/test_business_chat_refresh.cjs
```
