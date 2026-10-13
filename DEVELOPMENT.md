# Accounting development copy

This folder is the editable PHILIXA baseline for the accounting product.

- Compose project: `accounts-dev`
- Browser: http://127.0.0.1:8001 (use this hostname to keep cookies separate from the original app on localhost)
- PostgreSQL: localhost:5433
- Redis: localhost:6380
- MinIO API: localhost:9100; console: http://127.0.0.1:9101

Run commands from this directory in PowerShell:

```powershell
$dockerCli = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe"
& $dockerCli compose up -d --no-build
& $dockerCli compose ps
& $dockerCli compose logs --tail 50 app
```

The initial app and worker images were tagged from the existing PHILIXA image because both copies have the same requirements. Source code, migrations, scripts, and local data are mounted from this directory. Database, Redis, object storage, and model cache use separate `accounts-dev` volumes.

HTML/CSS/JavaScript changes appear after refreshing the browser (Ctrl+F5 if cached). Python app changes trigger Uvicorn reload; polling is enabled for Windows mounts. Worker changes require:

```powershell
& $dockerCli compose restart worker
```

After changing dependencies or the Dockerfile, rebuild:

```powershell
& $dockerCli compose up -d --build
```

To stop this development copy while preserving its database:

```powershell
& $dockerCli compose stop
```

The `.env` is private and excluded from Git and Docker build context. This copy starts with its own database; original accounts and records are not imported.

Voice chat uses the existing `/api/v1/live/transcribe` ticketed PCM pipeline and
`/api/v1/voice/speak`. The new `/api/v1/voice/business-chat` is conversation only:
no CRM tools, accounting writes, calendar scheduling or notification dispatch.
Mic: press, speak, then press again or pause for 3 seconds. Replies play with an
on-screen audio control; press the mic for another turn. Browser mic permission
is required. Chat history is held in the current browser page and cleared on new
chat, workspace change or sign-out. Recording caps at 30 seconds.

Focused checks in the duplicate app container:
`docker compose exec -T app python -m scripts.test_business_voice`
`docker compose exec -T app python -m scripts.verify_business_voice`
The latter uses synthetic Hindi audio and configured providers (small API usage).

Business chat now connects saved customer contacts/latest meeting memory, follow-up
creation and pending/today/overdue tasks. Save/update/complete actions require a
server-issued 15-minute preview and explicit confirmation. Approval tokens are
bound to workspace, user and session. Replays return the stored result or refuse
another execution; contacts are revalidated before sending.

Messages use the existing ReminderService. Both full content and recipients are
shown in the preview. Confirmed send reuses the existing SMTP/Meta credentials;
missing configuration or recipient details block confirmation. No additional
`PHILIXA_BUSINESS_*_VERIFIED` flags are required. Provider errors are reported by
the existing adapters. On 2026-10-08 SMTP authentication and a read-only WhatsApp
phone-ID request both passed. These establish authentication/access, not recipient
delivery. WhatsApp messages remain subject to Meta messaging-window/template rules.
No live messages were sent during development verification. To repeat the
read-only checks: `docker compose exec -T app python -m scripts.check_delivery_connections`.

Tasks are date-based (IST), not calendar events or automatic timed notifications.
External calendars remain unconnected. The local Tally pilot now implements live
stock and confirmed single-item non-GST purchase/sale through a separately
configured test company. Live stock read is verified; live voucher acceptance remains pending. See
`TALLY_PILOT.md` for setup, limitations and acceptance checks. Customer
memory is read from existing saved, permission-scoped meetings; this change does
not add a new meeting capture feature or durable conversation history.

Checks:
`docker compose exec -T app python -m scripts.verify_business_tools`
`docker compose exec -T app python -m scripts.test_business_scope`
These create and remove their own temporary customers/tasks in the duplicate
workspace. The scope test uses mocked message transport, never real delivery.


Business command and confirmation endpoints now use the shared LangGraph construction
in `portfolio_copilot_service.py`, with actual typed tool services and scoped meeting
evidence retrieval. See `BUSINESS_GRAPH.md` for data flow, checks and remaining acceptance limits.
