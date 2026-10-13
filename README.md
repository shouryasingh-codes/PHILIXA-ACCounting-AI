<div align="center">

# 🚀 PHILIXA 6.0
### The Agentic AI-First CRM for Relationship Managers & Wealth Advisors

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL_+_pgvector-316192?style=for-the-badge&logo=postgresql)](https://github.com/pgvector/pgvector)
[![LangGraph](https://img.shields.io/badge/AI-LangGraph-blueviolet?style=for-the-badge)](https://langchain-ai.github.io/langgraph/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

**Turn voice notes, meeting audio & raw text into AI-proposed CRM updates, commitments & proactive briefings — with human review before anything is saved.**

[Project Showcase](https://philixa.me) · [Run Locally](#-quickstart) · [Local API Docs](http://localhost:8000/docs) · [Architecture](ARCHITECTURE.md) · [Project Notes](PROJECT.md)

</div>

---

## Why Philixa?

Traditional CRMs force Relationship Managers and Wealth Advisors to become data-entry clerks. Philixa 6.0 flips that:

- **4 ways to capture** → Paste notes, upload audio/video (≤10 MB), live browser recording, or fast dictation
- **AI does the heavy lifting** → Extracts clients, commitments, risks, products & talking points
- **Human-in-the-loop** → Review & edit before anything is saved
- **Voice + Copilot** → Talk or type in English / Hinglish; schedule WhatsApp/Email reminders
- **Enterprise ready** → Multi-tenant, RBAC, hardened auth, rate limiting, audit logs

Built for Private Wealth, Corporate Banking and B2B Relationship teams.

---

## ✨ Key Features

### 🎙️ Multi-Modal Capture
- **4 Intake Modes**: Paste notes, drag-drop audio/MP4 (≤10 MB), live browser PCM streaming, or fast Web Speech dictation (en-IN + Android fix)
- **Audio DSP Pipeline**: FFmpeg + linear resampling + Deepgram Nova-3 (Hinglish) + faster-whisper large-v3-turbo
- **Speaker Diarization**: Solo mode or full PyAnnote meeting mode

### 🧠 AI Intelligence
- **Structured Extraction**: Clients, commitments, risks, products owned vs interested, talking points
- **LangGraph Copilot**: Natural language → safe SQL + pgvector RAG + action routing
- **Client Memory Dossier**: Pre-meeting brief + Ask-Client Q&A with citations

### 🗣️ Philixa Brain Voice Assistant + Reminders
- **Speak to send reminders**: Just say<br>
  *“WhatsApp Vikram that I’ll call him tomorrow”* or<br>
  *“Email Priya the mutual fund comparison”*
- Philixa drafts the message → you confirm (“Yes send it” / “Haan bhej do”) → sends via WhatsApp + Email
- 6-intent engine: Query, Save Meeting, **Send Reminder**, Confirm, Reject, Chat
- Sarvam AI `bulbul:v3` Hinglish TTS + Deepgram fallback
- 4000 ms silence auto-stop + 10-turn memory + hands-free conversation

### 🖥️ Modern Workbench UI
- **60/40 Diff Review Workbench**: Category filters, inline edit, source quotes, batch sync
- **Hero Voice Hub**: Rotating halo + pulse mic + time-of-day greeting
- **Persistent Copilot Sidecar**: Token budget meter + grounded client context
- Dark/Light theme, mobile bottom nav, keyboard shortcuts, WCAG AAA

### 🛡️ Enterprise Security & Multi-Tenancy
- Workspaces with Owner / Admin / Member RBAC
- HttpOnly JWT + single-flight refresh + double-submit CSRF
- SlowAPI rate limiting + 10 MB payload guard + demo quotas
- Google One-Tap SSO + cascade delete + audit logs

### ⚡ Background & Notifications
- ARQ workers for transcription, embeddings, rules engine
- Daily morning briefs + overdue commitment sweeps
- Meta WhatsApp Cloud API + quiet hours + delivery webhooks
- Simulated adapter for offline testing

---

## 🏗 System Architecture (High Level)

```
SPA (Vanilla JS)  →  FastAPI Gateway (Auth + Rate Limit + CSRF)
                         ↓
              ┌──────────┼──────────┐
              │          │          │
         PostgreSQL   Redis      MinIO
         + pgvector   (ARQ)     (Audio)
              │          │
         LangGraph   ARQ Worker
         Copilot     (Whisper, Embeddings, Rules, Cron)
```

Full detailed architecture, Mermaid diagrams, 50-endpoint catalog, database models and config matrix → see [ARCHITECTURE.md](ARCHITECTURE.md) and [PROJECT.md](PROJECT.md).

---

## 🚀 Quickstart

### Option 1 – Docker Compose (Recommended)

```bash
git clone https://github.com/shouryasingh-codes/philixa-6.0.git
cd philixa-6.0
cp .env.example .env
# Add your PHILIXA_GROQ_API_KEY (and optional Deepgram / Sarvam / WhatsApp keys)

docker compose up -d --build
```

Open the **local** app → [http://localhost:8000](http://localhost:8000)

Click **“Try Demo Workspace”** for instant access (pre-seeded clients + data).

### Option 2 – Local Development

Requires Python 3.12+, PostgreSQL 16 + pgvector, Redis 7, FFmpeg, MinIO.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head

# Terminal 1
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2
arq app.worker.WorkerSettings
```

---

## 🔑 Essential Environment Variables

| Variable | Purpose |
|----------|---------|
| `PHILIXA_GROQ_API_KEY` | Primary LLM (required) |
| `PHILIXA_DATABASE_URL` | PostgreSQL connection |
| `PHILIXA_REDIS_URL` | Cache + ARQ |
| `PHILIXA_JWT_SECRET` | ≥32 char secret |
| `PHILIXA_ENABLE_AUDIO_UPLOAD` | `1` to enable audio features |
| `PHILIXA_SARVAM_API_KEY` | Hinglish TTS (optional) |
| `WHATSAPP_*` | Meta Cloud API (optional) |

See `.env.example` for the full list (69+ settings).

---

## 📖 Documentation & Portals

| Resource | URL |
|----------|-----|
| Local Web App | [http://localhost:8000](http://localhost:8000) |
| Local Swagger API | [http://localhost:8000/docs](http://localhost:8000/docs) |
| Local ReDoc | [http://localhost:8000/redoc](http://localhost:8000/redoc) |
| Local MinIO Console | [http://localhost:9001](http://localhost:9001) (`philixa_minio` / `philixa_secret`) |
| Local Health Check | [http://localhost:8000/health](http://localhost:8000/health) |

---

## 🧪 Testing

```bash
pytest                          # Full suite
pytest tests/unit/              # Unit
pytest tests/integration/       # Integration
pytest tests/e2e/               # End-to-end
```

---

## 🗺 Roadmap

- [x] Multi-tenant + RBAC + hardened security
- [x] Multi-modal intake + HITL review
- [x] LangGraph Copilot + Voice Assistant
- [x] ARQ background jobs + cron sweeps
- [ ] React / Next.js frontend
- [ ] Stripe billing
- [ ] Kubernetes Helm charts

---

## 📬 Contact & Hiring

PHILIXA is an open-source portfolio project by [Shourya Singh](https://github.com/shouryasingh-codes). For collaboration, implementation work, or hiring conversations, use the [GitHub profile](https://github.com/shouryasingh-codes) or open a [repository issue](https://github.com/shouryasingh-codes/philixa-6.0/issues).

## 🤝 Contributing

1. Fork the repo
2. Create your branch (`git checkout -b feature/AmazingFeature`)
3. Commit (`git commit -m 'feat: Add AmazingFeature'`)
4. Push and open a Pull Request

See `CONTRIBUTING.md` (coming soon) for detailed guidelines.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.

---

<div align="center">

**Built with ❤️ for Relationship Managers who hate data entry**

[Report Bug](https://github.com/shouryasingh-codes/philixa-6.0/issues) · [Request Feature](https://github.com/shouryasingh-codes/philixa-6.0/issues)

</div>
```
