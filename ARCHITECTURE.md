<div align="center">

# 🚀 PHILIXA 6.0
### The Agentic AI-First CRM for Modern Relationship Managers & Wealth Advisors

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI_0.137-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL_16_+_pgvector-316192?style=for-the-badge&logo=postgresql)](https://github.com/pgvector/pgvector)
[![LangGraph](https://img.shields.io/badge/AI_Orchestration-LangGraph_StateGraph-blueviolet?style=for-the-badge&logo=langchain)](https://langchain-ai.github.io/langgraph/)
[![Groq Cloud](https://img.shields.io/badge/Inference-Groq_Llama_3.3_70B-F55036?style=for-the-badge)](https://groq.com/)
[![Redis & ARQ](https://img.shields.io/badge/Task_Queue-Redis_7_+_ARQ_Worker-DC382D?style=for-the-badge&logo=redis)](https://arq-docs.helpmanual.io/)
[![MinIO S3](https://img.shields.io/badge/Object_Storage-MinIO_S3-C72C48?style=for-the-badge&logo=minio)](https://min.io/)
[![Docker](https://img.shields.io/badge/Containers-5_Service_Compose-2496ED?style=for-the-badge&logo=docker)](https://www.docker.com/)
[![Deepgram](https://img.shields.io/badge/STT-Deepgram_Nova--3-13EF93?style=for-the-badge)](https://deepgram.com/)
[![Sarvam AI](https://img.shields.io/badge/Voice_TTS-Sarvam_AI_Hinglish-6842FF?style=for-the-badge)](https://www.sarvam.ai/)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](https://opensource.org/licenses/MIT)

<br/>

**[ [🌐 Local Web App](http://localhost:8000) ] · [ [📖 Local API Docs (Swagger)](http://localhost:8000/docs) ] · [ [📚 Local ReDoc Reference](http://localhost:8000/redoc) ] · [ [🗄️ Local MinIO Console](http://localhost:9001) ] · [ [🏗 System Architecture](#-system-architecture) ] · [ [🚀 Quickstart](#-quickstart--deployment-guide) ] · [ [💬 WhatsApp Webhook](#29-notification-preferences--whatsapp-webhooks) ]**

</div>

---

## 📑 Table of Contents

- [Executive Overview](#-executive-overview)
- [Why Philixa 6.0?](#-why-philixa-60)
- [System Architecture](#-system-architecture)
  - [High-Level Architecture Topology](#high-level-architecture-topology)
  - [End-to-End Component Flowchart](#end-to-end-component-flowchart)
  - [LangGraph Agentic Copilot Routing](#langgraph-agentic-copilot-routing)
- [Deep Dive: Core Subsystems](#-deep-dive-core-subsystems)
  - [1. Multi-Tenant Workspace, Hardened Auth & Gateway Security](#1-multi-tenant-workspace-hardened-auth--gateway-security)
    - [SlowAPI IP Rate Limiting Infrastructure](#slowapi-ip-rate-limiting-infrastructure)
    - [Demo Sandbox Multi-Tiered Quotas in Redis](#demo-sandbox-multi-tiered-quotas-in-redis)
  - [2. Multi-Modal Ingestion & Audio DSP Pipeline](#2-multi-modal-ingestion--audio-dsp-pipeline)
    - [Deepgram Nova-3 STT & Keepalive Heartbeat](#deepgram-nova-3-stt--keepalive-heartbeat)
    - [Linear Interpolation Audio Resampling](#linear-interpolation-audio-resampling)
    - [Strict HITL Client Creation Policy](#strict-hitl-client-creation-policy)
  - [3. Stateful Agentic Copilot, Vector RAG & Multi-Modal Reminders](#3-stateful-agentic-copilot-vector-rag--multi-modal-reminders)
    - [Two-Phase Interactive Reminder Drafting & Redis Staging](#two-phase-interactive-reminder-drafting--redis-staging)
    - [Multi-Modal Reminder Dispatch (Voice vs Copilot)](#multi-modal-reminder-dispatch-voice-vs-copilot)
    - [Bilingual Hinglish Confirmation Fast-Paths](#bilingual-hinglish-confirmation-fast-paths)
  - [4. Conversational Voice Assistant & 6-Way Intent Engine](#4-conversational-voice-assistant--6-way-intent-engine)
    - [Sarvam AI Bulbul:v3 Hinglish Voice Synthesis & Fallbacks](#sarvam-ai-bulbulv3-hinglish-voice-synthesis--fallbacks)
  - [5. Automated Rules Engine, Risk Scoring & CRM Intelligence](#5-automated-rules-engine-risk-scoring--crm-intelligence)
  - [6. Distributed ARQ Worker & Scheduled Sweeps](#6-distributed-arq-worker--scheduled-sweeps)
    - [Worker Memory Optimization (Whisper Preload Bypass)](#worker-memory-optimization-whisper-preload-bypass)
    - [Standalone CLI Tool: Demo Account Purging](#standalone-cli-tool-demo-account-purging)
  - [7. Dual-Channel Notification Engine & Delivery Audit](#7-dual-channel-notification-engine--delivery-audit)
    - [Simulated Notification Adapter for Testing](#simulated-notification-adapter-for-testing)
    - [Real-Time Webhook Synchronization for Communication Logs](#real-time-webhook-synchronization-for-communication-logs)
- [Frontend Single-Page Application (SPA) Architecture](#-frontend-single-page-application-spa-architecture)
  - [1. 6-View Fullscreen Auth Modal & State Machine](#1-6-view-fullscreen-auth-modal--state-machine)
  - [2. Google Identity Services (GSI) One-Tap SSO Integration](#2-google-identity-services-gsi-one-tap-sso-integration)
  - [3. Multi-Tenant Workspace Context Switcher & Plan Badge](#3-multi-tenant-workspace-context-switcher--plan-badge)
  - [4. Workspace Team Member Management & Dynamic RBAC Modal](#4-workspace-team-member-management--dynamic-rbac-modal)
  - [5. User Profile Avatar Dropdown, Initials Badges & Account Deletion](#5-user-profile-avatar-dropdown-initials-badges--account-deletion)
  - [6. Responsive App Shell, Collapsible 64px Icon-Rail & Mobile Drawer](#6-responsive-app-shell-collapsible-64px-icon-rail--mobile-drawer)
  - [7. Dark / Light Theme System with WCAG AAA Contrast Tokens](#7-dark--light-theme-system-with-wcag-aaa-contrast-tokens)
  - [8. Homogeneous 4-Card Verdict Strip Metrics with Jump Navigation](#8-homogeneous-4-card-verdict-strip-metrics-with-jump-navigation)
  - [9. Mobile Bottom Navigation Bar & 4 App-Level Tab Sections (<= 768px)](#9-mobile-bottom-navigation-bar--4-app-level-tab-sections--768px)
  - [10. Tablet Responsive Segmented Tab Switcher (< 1024px)](#10-tablet-responsive-segmented-tab-switcher--1024px)
  - [11. 4-Tab Smart Intake Editor & Audio DSP Worklets](#11-4-tab-smart-intake-editor--audio-dsp-worklets)
    - [AudioWorklet Raw PCM Audio Streaming Engine](#audioworklet-raw-pcm-audio-streaming-engine-pcm-processorjs)
    - [Web Speech API Fast Dictation Engine with Android Workaround](#web-speech-api-fast-dictation-engine-with-android-workaround)
    - [Audio Upload 4-State Polling State Machine & Manual Review Fallback](#audio-upload-4-state-polling-state-machine--manual-review-fallback)
    - [Runtime Feature Flag Graceful UI Degradation](#runtime-feature-flag-graceful-ui-degradation)
  - [12. Structured Diff Review Workbench (60/40 Split Master-Detail)](#12-structured-diff-review-workbench-6040-split-master-detail)
  - [13. Global Client Filter Omnibar, Cascade Delete & Owner Decoration](#13-global-client-filter-omnibar-cascade-delete--owner-decoration)
  - [14. Client Profile & Communication History Modal](#14-client-profile--communication-history-modal)
  - [15. Client Memory Dossier Accordion & Pre-Meeting Brief Card](#15-client-memory-dossier-accordion--pre-meeting-brief-card)
  - [16. In-Dossier Client Q&A with Dedicated Voice Mic Auto-Submit](#16-in-dossier-client-qa-with-dedicated-voice-mic-auto-submit)
  - [17. Interactive Commitment Ledger Table & Optimistic Status Toggling](#17-interactive-commitment-ledger-table--optimistic-status-toggling)
  - [18. Daily Priorities List & Dynamic False-Alarm Safe Risk Monitor](#18-daily-priorities-list--dynamic-false-alarm-safe-risk-monitor)
  - [19. Team Performance Overview Dashboard Table](#19-team-performance-overview-dashboard-table)
  - [20. Workspace Scope Toggle (Team Workspace vs My Workspace)](#20-workspace-scope-toggle-team-workspace-vs-my-workspace)
  - [21. Persistent 380px AI Copilot Sidecar with Dynamic Token Budget Meter](#21-persistent-380px-ai-copilot-sidecar-with-dynamic-token-budget-meter)
  - [22. Hero Voice Assistant Interaction Hub & Rotating Conic Halo](#22-hero-voice-assistant-interaction-hub--rotating-conic-halo)
  - [23. Philixa Brain Voice Assistant 4-State Visual State Machine & 4000ms Silence](#23-philixa-brain-voice-assistant-4-state-visual-state-machine--4000ms-silence)
  - [24. Multi-Modal Client Reminder Scheduling UI Workflows (Voice vs Copilot)](#24-multi-modal-client-reminder-scheduling-ui-workflows-voice-vs-copilot)
  - [25. Notification Preferences Modal & Quiet Hours Configuration](#25-notification-preferences-modal--quiet-hours-configuration)
  - [26. Client-Side Single-Flight Refresh Queue & Double-Submit CSRF Guard](#26-client-side-single-flight-refresh-queue--double-submit-csrf-guard)
  - [27. Toast Notification System](#27-toast-notification-system)
  - [28. Comprehensive Keyboard Shortcuts & WCAG 2.2 AAA Accessibility](#28-comprehensive-keyboard-shortcuts--wcag-22-aaa-accessibility)
  - [29. Synchronous LocalStorage FOAC Prevention Script](#29-synchronous-localstorage-foac-prevention-script)
- [Interactive Developer & Management Portals](#-interactive-developer--management-portals)
- [Complete 50-Endpoint API Catalog](#-complete-50-endpoint-api-catalog)
- [Database Entity Relationship & 18 Relational Models](#-database-entity-relationship--18-relational-models)
- [Master Configuration Matrix](#-master-configuration-matrix)
- [Standalone CLI Scripts & Developer Diagnostics](#-standalone-cli-scripts--developer-diagnostics)
- [Quickstart & Deployment Guide](#-quickstart--deployment-guide)
  - [Option A: 5-Container Docker Compose (Recommended)](#option-a-5-container-docker-compose-recommended)
  - [Option B: Bare-Metal Virtualenv Setup](#option-b-bare-metal-virtualenv-setup)
  - [One-Click Demo Sandbox Evaluation](#one-click-demo-sandbox-evaluation)
- [Verified cURL Workflows](#-verified-curl-workflows)
- [Testing & Quality Assurance](#-testing--quality-assurance)
- [Roadmap & Engineering Milestones](#-roadmap--engineering-milestones)
- [Contributing & License](#-contributing--license)

---

## 🎯 Executive Overview

**PHILIXA 6.0** is an enterprise-grade, agentic AI-first Customer Relationship Management (CRM) platform engineered specifically for **Relationship Managers (RMs), Private Wealth Advisors, Corporate Bankers, and B2B Account Executives**. 

Traditional CRMs turn client-facing professionals into manual data-entry clerks, resulting in stale client context, unfulfilled commitments, and lost revenue. Philixa 6.0 eliminates manual administrative overhead by transforming **unstructured client interactions**—including dictated voice notes, multipart audio recordings, live meeting audio streams, and raw pasted notes—into structured CRM entities, automated commitment logs, and proactive relationship briefings.

### Architectural Pillars for Systems Architects & Hiring Managers
- 🛡️ **Enterprise Multi-Tenancy & Hardened Session Security**: Strict tenant isolation across all entities via `TenantMixin`, Bcrypt password hashing (`cost >= 12`), Google OAuth 2.0 (`POST /auth/google`) with automatic workspace provisioning, HttpOnly + SameSite=Lax JWT cookie pairs, single-flight 401 refresh token rotation, double-submit CSRF protection (`X-CSRF-Token`), SlowAPI IP rate limiting (60/min global; 5/min on login, 10/min on meeting notes, 20/min on copilot), 10MB payload limiters (`enforce_payload_size_limit`), production security validation (`validate_production_settings`), demo sandbox multi-tiered quotas (2 meetings, 5 Copilot queries per 24 hours in Redis, live WebSocket lockout), and single-use Redis-backed WebSocket ticket replay defense.
- 🎙️ **Multi-Modal Meeting Capture & Audio DSP**: Four specialized ingestion pipelines supporting direct raw text (`MeetingSourceType.PASTED_NOTE`), MinIO S3 multipart audio uploads (`AUDIO_UPLOAD`, 10MB limit, `.mp3, .m4a, .wav, video/mp4`), live 16kHz Int16 PCM WebSocket streaming (`LIVE_BROWSER`), and zero-latency browser dictation in Indian English (`en-IN`). Powered by FFmpeg audio filter chains, in-memory linear interpolation resampling (`resample_to_16k`), dynamic Whisper client-name prompt injection (capped at 20 clients), Solo/Meeting PyAnnote 3.1 diarization, ASR Hinglish translation normalization (`translate_transcript`), Deepgram Nova-3 STT (`language="hi"`, 300ms endpointing, 5s keepalive), and automated MinIO storage purging (`PHILIXA_RETAIN_AUDIO`).
- 🧠 **Hybrid LangGraph State Machine, Vector RAG & Multi-Modal Reminders**: A stateful LangGraph execution graph orchestrating natural language-to-SQL generation with automatic multi-tenant RBAC injection, deterministic fast-path routing, bilingual Hinglish confirmation/rejection interceptors, heuristic sentiment/concern interceptors (`_requires_evidence_search`), hybrid cosine similarity search over 1024-dimensional `BAAI/bge-m3` vectors in PostgreSQL `pgvector`, and a two-phase Human-In-The-Loop `action_node` drafting and staging client reminders in Redis with 300s TTL before concurrent multi-channel email/WhatsApp dispatch.
- 🗣️ **Conversational Voice Assistant with 6-Way Intent Engine**: Philixa Brain voice assistant featuring 6-way intent classification (`QUERY`, `SAVE_MEETING`, `SEND_REMINDER`, `GENERAL_CHAT`, `CONFIRM_ACTION`, `REJECT_ACTION`), asynchronous background meeting ingestion via FastAPI `BackgroundTasks`, 4000ms silence auto-stop, 10-turn rolling conversation memory, Hindi name phonetic translation, and streaming TTS via Sarvam AI `bulbul:v3` (`speaker="shreya"`, `hi-IN`) with Deepgram Aura fallback (`POST /api/v1/voice/speak`).
- ⚡ **Asynchronous Background Processing & Distributed Cron**: Powered by ARQ (`asyncio` + Redis) workers handling offline Whisper `large-v3-turbo` CPU int8 transcription with worker RAM optimization (saving ~2GB RAM when audio upload is disabled), Pyannote diarization, vector embedding generation, automated business rules synchronization (`RulesEngineService`), real-time meeting completion alerts, 4 distributed cron sweeps (07:00 UTC morning RM briefings, 08:00 UTC overdue commitment sweeps, every 15m notification retries, and hourly demo sandbox account purging), and a standalone maintenance CLI (`python scripts/cleanup_demo_accounts.py`).
- 🖥️ **Full-Featured Modern Frontend SPA**: 60/40 Split Structured Diff Review Workbench, Client Profile & Communication History audit modal (`#clientProfileModal`), Mobile Bottom Navigation (`#mfdBottomNav`) with 4 views (Home, Notes, Today, Memory), Hero Voice Assistant Hub (`.mfd-hero`) with 132px 360° rotating conic halo (`.mfd-halo`) and 96px mic, AudioWorklet raw PCM engine (`pcm-processor.js`), Web Speech fast dictation (`fast-dictation.js`) with Android crash auto-restart, 380px Persistent Copilot Sidecar Dock with dynamic token budget meter (1,420 baseline / 8,192 max), Google One-Tap SSO UI, 4-card verdict strip with jump navigation, collapsible 64px icon rail, dark/light theme engine with WCAG 2.2 AAA tokens, and synchronous `<head>` FOAC prevention.
- 📱 **Dual-Channel Notification Architecture & Delivery Audit**: Strict architectural decoupling between isolated transactional SMTP email (`aiosmtplib`) for authentication workflows, Meta WhatsApp Cloud API v25.0 for proactive RM alerts with quiet-hours enforcement and delivery receipt tracking, `communication_logs` (18th database model) real-time webhook status reconciliation, and `SimulatedNotificationAdapter` for offline testing.

---

## 💡 Why Philixa 6.0?

| Capability / Architectural Dimension | Traditional Legacy CRMs (Salesforce / HubSpot) | Generic AI Wrapper CRMs | **Philixa 6.0 Enterprise Platform** |
|---|---|---|---|
| **Data Ingestion Paradigm** | Manual forms, rigid dropdowns, tedious manual data entry | Single text box with generic prompt wrapper | **4 Ingestion Modes**: Text Paste, MinIO Audio Drag-and-Drop (10MB Limit, Audio & MP4 Video), Live PCM Streaming via AudioWorklet (Solo/Meeting), and Fast Web Speech Dictation |
| **Meeting Intelligence & Audio DSP** | None (Requires third-party recorder extensions) | Basic OpenAI call with generic unstructured summary | **Hinglish-Tuned Multi-Stage AI Pipeline**: FFmpeg DSP, in-memory linear interpolation audio resampling (`resample_to_16k`), dynamic client-name Whisper prompt injection (capped at 20 clients), ASR Hinglish translation normalization, Deepgram Nova-3 (`language="hi"`, 300ms endpointing, 5s keepalive), PyAnnote 3.1 diarization, Groq Llama 3.3 70B extraction with precomputed calendar reference map, and Gemini fallback |
| **Human-in-the-Loop (HITL) Triage** | Manual duplicate merging | Full blind AI auto-creation (causes data pollution) | **60/40 Structured Diff Review Workbench**: Category filter pills, interactive diff cards, inline editing, source quote attribution, micro-dismissal, batch sync (`Cmd+Shift+Enter`), strict HITL client confirmation (`#confirmPanel`, silent auto-create disabled), and 4-state transcript correction (`#editTranscriptPanel`) |
| **Portfolio Querying & Copilot** | Complex SQL/SOQL or static reports | Vector-only semantic search or ungrounded SQL | **Hybrid LangGraph StateGraph**: Deterministic fast-paths, bilingual Hinglish confirmation/rejection interceptors, heuristic evidence interceptor (`_requires_evidence_search`), safe read-only SQL with auto RBAC filters, pgvector cosine search, and two-phase 300s Redis TTL `action_node` reminder dispatch |
| **Voice & Action Capabilities** | None / Add-on plugins | Passive chatbot replies | **6-Intent Conversational Voice Assistant**: `QUERY`, `SAVE_MEETING` (async background save), `SEND_REMINDER` (2-phase draft staging), `GENERAL_CHAT`, `CONFIRM_ACTION` ("yes", "haan bhej do"), `REJECT_ACTION` ("no", "mat bhej"), with Sarvam AI `bulbul:v3` streaming TTS, 4000ms silence detection, and Hero Hub UI |
| **Tenant & Data Isolation** | Organization-level tables with high licensing cost | Single-tenant or software-level user filtering | **Strict Multi-Tenant Model**: Composite memberships (`owner`, `admin`, `member`), repository-level scoping, 18 relational models (including `communication_logs`), 21 Alembic migrations up to head `924be62947b0`, Google OAuth2 SSO, decoupled products (`products_owned_json` vs `products_interested_json`), and cascade deletion |
| **Session Security & Defense** | Standard session cookies | Insecure Bearer tokens in `localStorage` | **Hardened Security**: HttpOnly JWT cookies, single-flight refresh rotation (`fetchWithAuth`), per-request DB session revocation checks, double-submit CSRF with conditional checking, SlowAPI IP rate limiting (60/min default, 5/m login, 10/m notes, 20/m copilot), 10MB payload limiter, production settings validator, single-use signed WS tickets, and demo sandbox quotas (2 notes, 5 copilot queries/24h in Redis, live WS blocked) |
| **Background Queue & Automation** | Expensive Enterprise schedulers | Synchronous request blocking or toy threading | **Distributed ARQ + Redis Workers**: Async STT queues with faster-whisper `large-v3-turbo` CPU int8, RAM optimization (skips Whisper preload when audio upload is disabled saving ~2GB RAM), event-driven meeting completion alerts, 4 automated cron sweeps (07:00 UTC morning brief, 08:00 UTC overdue follow-up, 15m retry, hourly demo purge), and standalone `cleanup_demo_accounts.py` CLI |
| **Proactive RM Notification** | Generic email digests | In-app notification popups only | **Meta WhatsApp Cloud API v25.0** + isolated SMTP with midnight-spanning quiet hours, multi-channel `ReminderService` with 300s Redis draft staging, `communication_logs` table audit trail with webhook status reconciliation, and `SimulatedNotificationAdapter` |

---

## 🏗 System Architecture

### High-Level Architecture Topology

```
+-----------------------------------------------------------------------------------------------------------------------------------+
|                                                 PHILIXA 6.0 DISTRIBUTED ARCHITECTURE                                              |
+-----------------------------------------------------------------------------------------------------------------------------------+

      [ Single-Page Application (SPA) ]               [ External Channels ]                 [ AI & Cloud Microservices ]
     /        |               |        \                        |                                        |
+-------+ +-------+       +-------+ +-------+           +---------------+              +-----------------------------------+
| Paste | | Audio |       | Live  | | Voice |           | Meta WhatsApp |              |  Groq Cloud (Llama 3.3 70B Vers)  |
| Notes | | Drag  |       | Audio | | Brain |           |  Cloud v25.0  |              |  Google Gemini (2.5/3.6 Flash)    |
| (Raw) | | (10M) |       | (PCM) | | (Hero)|           |  (Webhooks)   |              |  Deepgram Nova-3 / Sarvam AI TTS  |
+-------+ +-------+       +-------+ +-------+           +---------------+              |  BAAI/bge-m3 (SentenceTransf.)    |
    |         |               |         |                       |                      +-----------------------------------+
    |         |               |         |                       |                                        ^
    +---------+---------------+---------+                       |                                        |
                      |                                         |                                        |
                      v                                         v                                        v
+-----------------------------------------------------------------------------------------------------------------------------------+
|                                          FASTAPI ASYNC APPLICATION CORE (Port :8000)                                              |
|                                                                                                                                   |
|  [ Gateway Security & Middlewares ]                                                                                               |
|  * SlowAPI IP Rate Limiter (60/min Global; 5/min /auth/login; 10/min /meeting-notes/process; 20/min /dashboard/copilot/ask)       |
|  * 10MB Global Request Payload Limiter (enforce_payload_size_limit -> HTTP 413)                                                   |
|  * Production Settings Security Validator (validate_production_settings: JWT entropy, CORS rules, SMTP, Cookie HTTPS)             |
|  * CSRFProtectionMiddleware (Double-Submit X-CSRF-Token Verification against csrf_token cookie; exempt paths; auto-seeding on GET)   |
|  * CORS Policy & Security Headers                                                                                                 |
|                                                                                                                                   |
|  [ Security & Multi-Tenant Context ]                                                                                              |
|  * Bcrypt Hashing (Cost 12)  * Google OAuth2 One-Tap Sign-In (/auth/google)  * HttpOnly JWT Cookies (Access 15m / Refresh 30d)     |
|  * Per-Request UserSession Revocation Checks  * WS Single-Use Tickets (60s TTL + Replay Guard)                                    |
|  * Demo Sandbox Quotas (2-Meeting Note Limit, 5 Copilot Queries/24h in Redis, Live WebSocket Lockout, 1d Session Expiry)          |
|  * CurrentPrincipal Injection: User ID, Active Organization ID, Canonical Role (owner | admin | member)                            |
|                                                                                                                                   |
|  [ API Router Subsystems (50 Distinct Operations, Dual-Mounted at / and /api/v1/) ]                                                |
|  * /auth (12 ops)   * /workspaces (7 ops)  * /api/v1/clients (9 ops)      * /api/v1/meeting-notes (4 ops) * /api/v1/commitments (2 ops)|
|  * /audio (2 ops)   * /live/transcribe     * /api/v1/voice (2 ops)        * /api/v1/dashboard (4 ops)    * /api/v1/preferences (2 ops)|
|  * /api/v1/webhooks/whatsapp (2 ops)       * /api/v1/jobs (1 op)          * /health (1 op)               * / (1 op static SPA)        |
|                                                                                                                                   |
|  [ Hybrid LangGraph Agentic Copilot & Voice Engine ]                                                                             |
|  * Deterministic Fast-Paths: Greeting / Asia/Kolkata Calendar / Client Profile Lookup / Bilingual Hinglish Confirmation           |
|  * Heuristic Interceptor (_requires_evidence_search): Forces vector route for sentiment/discount/complaint queries                 |
|  * StateGraph: planner_node --> (sql_generator_node | semantic_node [pgvector] | action_node [ReminderService]) --> synthesizer_node|
|  * Two-Phase Interactive Reminder Staging: 300s Redis TTL (pending_reminder:{uid} / pending_reminder_copilot:{uid})               |
|  * VoiceAssistantService: 6-Intent Routing (QUERY, SAVE_MEETING, SEND_REMINDER, GENERAL_CHAT, CONFIRM_ACTION, REJECT_ACTION)        |
|  * ASR Hinglish Translation & Normalization Layer (Phonetic error correction & Indian name preservation)                         |
+-----------------------------------------------------------------------------------------------------------------------------------+
           |                                     |                                         |
           v                                     v                                         v
+-----------------------+             +-----------------------+                 +-----------------------+
|  POSTGRESQL + PGVECTOR|             |     REDIS 7 CACHE     |                 |  MINIO S3 OBJECT STR  |
|      (Port :5432)     |             |      (Port :6379)     |                 |  (API :9000 | UI :9001)|
+-----------------------+             +-----------------------+                 +-----------------------+
| * 18 Relational Tables|             | * ARQ Job Queues      |                 | * Bucket: philixa-audio|
| * Multi-Tenant Scoping|             | * WS Replay Guard Keys|                 | * Tenant Namespaces:  |
| * Decoupled Products  |             | * 300s Reminder Drafts|                 |   {org}/{user}/{meet} |
|   (owned vs interested|             | * Demo Copilot Quotas |                 | * 10MB Max File Size  |
| * 1024-dim BAAI/bge-m3|             | * User Session State  |                 | * Auto-Purge Lifecycle|
|   Cosine Index (<=>)  |             | * Single-Flight Queue |                 |   (PHILIXA_RETAIN_    |
| * communication_logs  |             |                       |                 |    AUDIO=0)           |
+-----------------------+             +-----------------------+                 +-----------------------+
           ^                                     ^                                         ^
           |                                     |                                         |
           +-------------------------------------+-----------------------------------------+
                                                 |
                                                 v
+-----------------------------------------------------------------------------------------------------------------------------------+
|                                            ARQ ASYNCHRONOUS BACKGROUND WORKER CONTAINER                                           |
|                                                                                                                                   |
|  [ Async Jobs ]                                              [ Distributed Cron Sweeps (4 Total) ]                                |
|  * process_meeting_transcription (DSP + Whisper + Pyannote) |  * 07:00 UTC: send_pre_interaction_briefs (Daily Morning RM Brief) |
|  * Worker RAM Opt: Skips Whisper preload if upload disabled  |  * 08:00 UTC: send_client_followups (Overdue Commitment Sweep)     |
|  * generate_meeting_embeddings (1024-dim BAAI/bge-m3 pgvect) |  * Every 15m: retry_failed_notifications (Exp. Backoff Retry)      |
|  * RulesEngineService (Auto Task & Risk Signal Scoring)      |  * Hourly (Min 0): cleanup_demo_accounts (Demo Sandbox Purge)      |
|  * _notify_meeting_processed (Instant Post-Meeting Alert)    |  * Standalone CLI: python scripts/cleanup_demo_accounts.py        |
+-----------------------------------------------------------------------------------------------------------------------------------+
```

---

### End-to-End Component Flowchart

```mermaid
flowchart TD
    subgraph Clients["Client Presentation Tier (SPA & Omnichannel)"]
        UI["SPA Web Application\n(app/web/index.html & app.js)"]
        MobileNav["Mobile Bottom Nav Bar\n(4 Views: Home, Notes, Today, Memory)"]
        HeroVoice["Hero Voice Assistant Hub\n(132px Rotating Halo + 96px Mic)"]
        ClientModal["Client Profile & Comm History Modal\n(#clientProfileModal & #communicationFeed)"]
        DiffWorkbench["60/40 Diff Review Workbench\n(Interactive Staging & Inline Edit)"]
        CopilotSidecar["380px Copilot Sidecar Dock\n(Dynamic Token Meter & Evidence Badges)"]
        VoiceFAB["Philixa Brain Voice Assistant\n(4-State Visual Machine: philixa-voice.js)"]
        Dictation["Fast Dictation\n(en-IN Web Speech API + Android Auto-Restart)"]
        GoogleSSO["Google One-Tap SSO\n(Google Identity Services SDK)"]
        WhatsAppUser["RM on WhatsApp\n(Meta Graph API v25.0 Mobile)"]
    end

    subgraph Gateway["FastAPI Application Gateway (:8000)"]
        RateLimiter["SlowAPI IP Rate Limiter\n(60/min Global; 5/min Login; 10/min Notes; 20/min Copilot)"]
        PayloadLimiter["10MB Payload Size Limiter\n(enforce_payload_size_limit)"]
        CSRF["CSRF Protection Middleware\n(Double-Submit X-CSRF-Token Verification)"]
        AuthContext["Auth Context & RBAC Injection\n(CurrentPrincipal: Org, User, Role)"]
        APIRouters["50 Rest & WS Endpoints\n(Dual-Mounted / and /api/v1/)"]
    end

    subgraph AI_Engine["Hybrid Intelligence, Voice & RAG Core"]
        LangGraph["LangGraph StateGraph Router\n(Planner -> SQL / Semantic / Action -> Synthesizer)"]
        EvidenceInterceptor{"_requires_evidence_search\nHeuristic Interceptor?"}
        FastPaths{"Deterministic\nFast-Path?"}
        HinglishFastPath{"Hinglish Reminder\nConfirmation Fast-Path?"}
        ReminderEngine["ReminderService Engine\n(2-Phase Draft Staging & Concurrent Dispatch)"]
        VoiceRouter["VoiceAssistantService (6 Intents)\n(QUERY, SAVE, REMINDER, CHAT, CONFIRM, REJECT)"]
        HinglishLayer["ASR Hinglish Translation & Normalization\n(Phonetic Fixes & Indian Entity Preservation)"]
        Groq["Groq Cloud API\n(Llama 3.3 70B Versatile + Calendar Reference)"]
        Gemini["Google Gemini\n(2.5/3.6 Flash Fallback)"]
        Sarvam["Sarvam AI Bulbul:v3 / Deepgram Nova-3\n(Voice TTS & Real-Time STT)"]
        BGE["BAAI/bge-m3\n(1024-dim Dense Embeddings)"]
    end

    subgraph Storage["Storage & Caching Tier"]
        PG[("PostgreSQL 15/16 + pgvector\n18 Multi-Tenant Tables & communication_logs")]
        Redis[("Redis 7 Cache & Broker\nARQ Queues, WS Replay Guard & 300s Reminder Drafts")]
        MinIO[("MinIO S3 Storage\nTenant Audio & Auto-Purging (10MB Limit)")]
    end

    subgraph Worker["ARQ Asynchronous Background Worker"]
        TranscriptionJob["process_meeting_transcription\n(FFmpeg DSP + Whisper large-v3-turbo CPU int8)"]
        EmbeddingJob["generate_meeting_embeddings\n(1024-dim pgvector chunks)"]
        RulesEngine["RulesEngineService\n(Dynamic Task & Risk Scoring)"]
        CronMorning["07:00 UTC Cron\nPre-Interaction Briefs"]
        CronFollowup["08:00 UTC Cron\nOverdue Commitment Alerts"]
        CronRetry["Every 15m Cron\nNotification Retry Backoff"]
        CronDemoPurge["Hourly (Min 0) Cron\nDemo Account Cascade Purge"]
        RealtimeNotify["_notify_meeting_processed\nEvent-Driven Meeting Alerts"]
    end

    UI --> MobileNav & HeroVoice & ClientModal
    UI -->|HTTP + Cookies| RateLimiter
    RateLimiter --> PayloadLimiter --> CSRF --> AuthContext --> APIRouters
    GoogleSSO -->|id_token| RateLimiter
    HeroVoice & VoiceFAB -->|POST /voice/chat & speak| RateLimiter
    Dictation -->|Populates Smart Intake| UI
    UI --> DiffWorkbench
    UI --> CopilotSidecar

    APIRouters -->|Copilot Query| HinglishFastPath
    HinglishFastPath -->|Yes: Spoken/Typed Affirmation| ReminderEngine
    HinglishFastPath -->|No: Standard Query| EvidenceInterceptor
    EvidenceInterceptor -->|Sentiment/Discount/Concern| LangGraph
    EvidenceInterceptor -->|Standard Query| FastPaths
    FastPaths -->|Yes: Direct Lookup| PG
    FastPaths -->|No: Agent Routing| LangGraph
    LangGraph -->|Action Route: 2-Phase Staging| ReminderEngine
    ReminderEngine -->|Stage Draft (300s TTL)| Redis
    ReminderEngine -->|Confirmed: Concurrent Dispatch| Worker
    ReminderEngine -->|Log Outbound Message| PG
    APIRouters -->|Voice Chat / Dictate| VoiceRouter
    VoiceRouter -->|SAVE_MEETING| BackgroundSave["FastAPI BackgroundTasks\nMeetingProcessingService"]
    BackgroundSave --> PG
    VoiceRouter -->|SEND_REMINDER / CONFIRM / REJECT| ReminderEngine
    LangGraph --> Groq & Gemini & PG
    APIRouters -->|Audio Upload| MinIO
    APIRouters -->|Enqueue STT/Embeddings| Redis

    Redis --> Worker
    Worker --> MinIO & PG & BGE & Groq & RulesEngine
    Worker --> RealtimeNotify
    RealtimeNotify -->|WhatsApp / Email| WhatsAppUser
    CronMorning & CronFollowup -->|Meta Graph v25.0| WhatsAppUser
```

---

### LangGraph Agentic Copilot Routing

```mermaid
stateDiagram-v2
    [*] --> InboundQuery: User sends natural language query
    InboundQuery --> HinglishCheck: Check pending_reminder_copilot in Redis
    
    HinglishCheck --> ConfirmFastPath: Input matches 'yes', 'send', 'haan bhej do'
    HinglishCheck --> RejectFastPath: Input matches 'no', 'cancel', 'mat bhej'
    HinglishCheck --> EvidenceCheck: No pending draft or standard query
    
    ConfirmFastPath --> DispatchStagedReminder: Retrieve staged draft from Redis
    DispatchStagedReminder --> [*]: Dispatch concurrent WhatsApp/Email & update communication_logs
    
    RejectFastPath --> PurgeStagedReminder: Delete draft from Redis
    PurgeStagedReminder --> [*]: Return 'Cancelled message'
    
    EvidenceCheck --> Semantic_Route: Matches sentiment/discount/concern keywords
    EvidenceCheck --> FastPathCheck: Standard query flow

    state FastPathCheck {
        [*] --> GreetingMatch
        GreetingMatch --> CalendarLookup: Not a greeting
        CalendarLookup --> ClientDirectLookup: Not calendar lookup
        ClientDirectLookup --> LLMPlanner: No fast-path match
    }

    GreetingMatch --> ReturnFastAnswer: Greeting detected
    CalendarLookup --> QueryCalendarSQL: Asia/Kolkata schedule query
    ClientDirectLookup --> QueryClientDirectSQL: "Who is [Client]?"
    QueryCalendarSQL --> ReturnFastAnswer
    QueryClientDirectSQL --> ReturnFastAnswer

    state LangGraph_StateGraph {
        LLMPlanner --> SQL_Route: Analytical / Aggregation Query
        LLMPlanner --> Semantic_Route: Unstructured Narrative Query
        LLMPlanner --> Action_Route: Client Reminder / Follow-up Action
        
        SQL_Route --> GenerateSQL: Groq Llama 3.3 70B
        GenerateSQL --> InjectRBAC: Append 'AND user_id = :user_id' for members
        InjectRBAC --> ExecuteSafeSQL: Read-only SELECT execution
        ExecuteSafeSQL --> Synthesizer: Tabular DB Results
        
        Semantic_Route --> EmbedQuery: BAAI/bge-m3 1024-dim vector
        EmbedQuery --> CosineSearch: PostgreSQL pgvector '<=>'
        CosineSearch --> Synthesizer: Top-K Meeting Evidence Chunks

        Action_Route --> ReminderService: Extract Client, Channel & Message Intent
        ReminderService --> StageDraftRedis: AI drafts email_body & whatsapp_body
        StageDraftRedis --> Synthesizer: Cache in Redis (300s TTL) & return Preview Prompt
        
        Synthesizer --> SynthesizeResponse: Final grounded response generation
    }

    Synthesizer --> [*]: HTTP 200 JSON {answer, citations, preview_or_delivery}
    ReturnFastAnswer --> [*]: HTTP 200 JSON Fast-Path
```

---

## 🔬 Deep Dive: Core Subsystems

### 1. Multi-Tenant Workspace, Hardened Auth & Gateway Security

Philixa 6.0 implements an enterprise-grade multi-tenancy model backed by a multi-layered defense-in-depth security architecture.

```
                           +-----------------------------------------------+
                           |               USERS (Global Table)            |
                           |  id | email | password_hash | is_verified    |
                           +-----------------------------------------------+
                                                   |
                         +------------------------+------------------------+
                         |                                                 |
                         v                                                 v
    +-----------------------------------------+       +-----------------------------------------+
    |       ORGANIZATION_MEMBERSHIPS          |       |              USER_SESSIONS              |
    | org_id | user_id | role (owner/admin/m) |       | session_id | user_id | refresh_hash     |
    +-----------------------------------------+       +-----------------------------------------+
                         |
                         v
    +-------------------------------------------------------------------------------------------+
    |                           TENANT-SCOPED ENTITIES (TenantMixin)                            |
    | organizations | clients | meetings | commitments | meeting_evidence | follow_up_tasks     |
    +-------------------------------------------------------------------------------------------+
```

- **Tenancy Partitioning (`TenantMixin`)**: All domain models inherit `organization_id` and `user_id`. Queries are strictly partitioned at the repository layer (`ClientRepository`, `MeetingRepository`, `CommitmentRepository`).
- **Role-Based Access Control (RBAC)**:
  - `UserRole.OWNER` (`owner`): Full workspace administration, member role modification, workspace invite dispatch, billing, and team performance analytics.
  - `UserRole.ADMIN` (`admin`): Workspace member invitation, member removal, and team-wide CRM analytics.
  - `UserRole.MEMBER` (`member`): Access strictly isolated to personally assigned clients, meetings, and commitments.
- **Google OAuth2 One-Tap Sign-In (`POST /auth/google`)**:
  - Verifies Google ID tokens cryptographically using `google.oauth2.id_token.verify_oauth2_token` against the configured Google Client ID.
  - Automatically provisions a verified user profile and creates an individual workspace (e.g., `"{given_name}'s Workspace"`) with Owner privileges on first login.
  - Issues full HttpOnly session cookies (`access_token`, `refresh_token`, `csrf_token`) and is explicitly exempt from CSRF validation.
- **Dual-Mounted Route Architecture**: Core authentication and workspace endpoints (`/auth`, `/workspaces`, `/audio`, `/live`, `/ws-ticket`) are dual-mounted at both the root `/` and `/api/v1/` for seamless client compatibility and backward integration.
- **10MB Global Request Payload Limiter (`enforce_payload_size_limit`)**: Middleware in `app/main.py` intercepts all incoming HTTP requests and enforces `MAX_CONTENT_LENGTH = 10 * 1024 * 1024` (10MB). Requests exceeding this ceiling are immediately rejected with `HTTP 413 Payload Too Large` without consuming downstream application or memory resources.
- **Production Settings Security Validator (`validate_production_settings`)**: Pre-flight security audit executed during FastAPI lifespan startup (`app/core/lifespan.py`). When `APP_ENV=production`, it enforces:
  1. `PHILIXA_JWT_SECRET` must be $\ge 32$ characters and cannot contain insecure default/demo strings.
  2. `PHILIXA_ALLOWED_ORIGINS` cannot contain wildcards (`*`).
  3. `PHILIXA_SMTP_USERNAME` and SMTP credentials must be configured.
  4. `PHILIXA_COOKIE_SECURE` must be set to `True` (HTTPS enforcement).
- **SlowAPI IP Rate Limiting Infrastructure (`app/core/rate_limit.py`)**:
  - Built on SlowAPI with client IP key resolution (`get_remote_address`).
  - **Global IP Default**: Enforces a baseline rate limit of **60 requests/minute per IP** across all non-custom endpoints.
  - **Targeted Security & Resource Limits**:
    - `POST /auth/login`: `@limiter.limit("5/minute")` mitigating brute-force credential stuffing attacks.
    - `POST /api/v1/meeting-notes/process`: `@limiter.limit("10/minute")` protecting AI LLM extraction throughput and concurrency.
    - `POST /api/v1/dashboard/copilot/ask`: `@limiter.limit("20/minute")` throttling complex LangGraph planner and SQL generation calls.
  - **HTTP 429 Handling**: Global `_rate_limit_exceeded_handler` transforms threshold breaches into standard `HTTP 429 Too Many Requests` responses with informative cooldown details.
- **Session & Cookie Security**:
  - Bcrypt password hashing (`cost >= 12`).
  - Dual JWT HS256 cookies: `access_token` (15-minute lifespan) and `refresh_token` (30-day lifespan).
  - Single-flight token rotation via `POST /auth/refresh` preventing concurrency race conditions.
  - Anti-replay defense: Refresh tokens are SHA-256 hashed and matched against `user_sessions.refresh_token_hash`.
  - **Per-Request Database Session Revocation Checks**: For every authenticated request containing a session identifier (`sid`), `get_current_principal` (`app/core/auth.py`) checks the database `user_sessions` record verifying `revoked_at is None`, `expires_at >= utc_now()`, and `user_id == user.id`. This ensures instantaneous revocation across all devices upon logout or password changes without waiting for JWT access token expiry.
  - **Email Verification Dual-Input & HTTP 410 Gone**: `POST /auth/verify-email` accepts verification tokens via URL query string (`?token=...`) or JSON request body (`{"token": "..."}`). If the token has already been consumed (`used_at is not None`) or has expired, it explicitly returns `HTTP 410 Gone`.
  - **Development API Key Header Bypass**: The authentication dependency inspects the `X-API-Key` HTTP header. If the header matches `settings.api_key`, `settings.demo_api_key`, or `"dev-api-key"`, it provisions development principal credentials (`dev@philixa.com`, `Dev Org`) with `owner` privileges, bypassing cookie workflows during automated testing.
- **Double-Submit CSRF Protection (`CSRFProtectionMiddleware`)**:
  - Verifies the `X-CSRF-Token` HTTP header against the `csrf_token` cookie for all mutating HTTP methods (`POST`, `PUT`, `PATCH`, `DELETE`) using constant-time string comparison (`secrets.compare_digest`).
  - **Exemption Architecture (`CSRF_EXEMPT_PATHS`)**: Exempts public authentication routes (`/auth/register`, `/auth/login`, `/auth/google`, `/auth/verify-email`, `/auth/forgot-password`, `/auth/reset-password`), inbound webhooks (`/api/v1/webhooks/whatsapp`), health checks (`/health`), documentation (`/docs`, `/redoc`, `/openapi.json`), and static assets (`/static/*`).
  - **Cookie-Presence Conditional Verification**: CSRF validation is only enforced when session cookies (`access_token`, `refresh_token`, or `csrf_token`) are present, allowing stateless API clients using Bearer tokens to operate without CSRF headers.
  - **Auto-Seeding on GET**: Safe GET requests lacking a `csrf_token` cookie automatically receive a new cryptographically generated token cookie via `set_csrf_cookie(response)`.
- **Single-Use WebSocket Tickets**: Prevents passing JWTs over WebSocket query strings. Clients mint a 60-second signed ticket (`POST /ws-ticket`). Upon connection to `WS /live/transcribe`, Redis key `philixa:ws_ticket_used:{jti}` is written with a 60-second TTL to guarantee single-use replay defense.
- **Demo Sandbox Mode & Multi-Tiered Quotas**: Instant one-click workspace evaluation (`POST /auth/demo-login`) provisioning a pre-seeded workspace with realistic Indian wealth management clients, overdue commitments, and portfolio meetings.
  - **Meeting Extraction Quota**: Demo guest accounts (`demo_guest_*`) are capped at a maximum of **2 meeting note processings** (`HTTP 403 Forbidden`).
  - **Copilot Query Quota in Redis**: Tracks Copilot chat usage in Redis key `philixa:demo_copilot:{user_id}` with an 86,400-second (24-hour) TTL. Exceeding **5 Copilot queries** in 24 hours returns `HTTP 403 Forbidden` (*"Demo limit reached (Max 5 Copilot queries). Please create a free Philixa account to continue!"*).
  - **Live WebSocket Lockout**: Live audio WebSocket connections (`WS /live/transcribe`) by demo guest users are strictly blocked and rejected with `WS_1008_POLICY_VIOLATION` to protect speech infrastructure resources.
  - **Session Expiry & Cascade Cleanup**: Demo sessions expire after **1 day** (vs 30 days for standard accounts). Expired demo accounts and all associated organizations, clients, meetings, commitments, and vectors are purged hourly via background worker cron sweeps and standalone CLI execution.

---

### 2. Multi-Modal Ingestion & Audio DSP Pipeline

Philixa 6.0 handles the full spectrum of meeting ingestion formats across asynchronous and real-time paths:

```
[ Ingestion Modes ] ──────────────► [ Processing Pipeline ] ──────────────► [ CRM Output ]
1. PASTED_NOTE (Raw Text)  ───────► Direct LLM Extraction  ──────────────► Structured Brief
2. AUDIO_UPLOAD (MinIO S3) ───────► FFmpeg DSP -> Whisper STT ───────────► Entities & Tasks
3. LIVE_BROWSER (16kHz PCM)──────► WebSocket -> Deepgram Nova-3 ────────► Live Transcript
4. Fast Dictation (Web Speech) ──► Client-Side Low-Latency en-IN ────────► Note Input Form
```

1. **Pasted Notes (`MeetingSourceType.PASTED_NOTE`)**: Direct text ingestion via `POST /api/v1/meeting-notes/process`. Directly triggers AI entity extraction, client resolution, commitment tracking, and risk signal detection.
2. **Audio Upload (`MeetingSourceType.AUDIO_UPLOAD`)**:
   - Accepts multipart audio and video files (`audio/mpeg`, `audio/mp4`, `audio/x-m4a`, `audio/wav`, `audio/x-wav`, `video/mp4`) via `POST /audio/upload`.
   - **Enforced 10MB Ceiling**: The backend strictly limits upload sizes to **10MB** (`MAX_FILE_SIZE = 10 * 1024 * 1024` and `MAX_CONTENT_LENGTH = 10MB`). Files exceeding 10MB return `HTTP 413 Payload Too Large`.
   - **Pre-Bound Client Linking (`known_client_id`)**: Accepts an optional form field `known_client_id: int | None`, allowing advisors to explicitly pre-bind an audio recording to an existing client profile and bypass ambiguous identification heuristics.
   - **MinIO Path Sanitization**: `sanitize_filename` purges path traversal sequences (`..`, `/`, `\`), eliminates non-alphanumeric characters, and generates deterministic S3 storage keys under `{organization_id}/{user_id}/{meeting_id}`.
   - **Atomic Two-Phase Rollback**: If MinIO upload or database record allocation succeeds but ARQ background task enqueueing fails, an automated rollback handler purges the S3 object and deletes the database record, returning HTTP 500.
3. **Deepgram Nova-3 Real-Time STT Engine & Keepalive Heartbeat (`app/services/live_strategies.py`)**:
   - The live WebSocket audio transcription session utilizes Deepgram **Nova-3** (`model="nova-3"`).
   - **Language Configuration**: Set to `language="hi"`, specifically chosen to handle natural Indian English, Hindi, and colloquial Hinglish code-switching with high phonetic accuracy.
   - **300ms Endpointing**: Configured with `endpointing=300`, which forces sentence finalization after 300ms of speaker silence to virtually eliminate latency lag.
   - **5-Second Keepalive Heartbeat Loop**: Runs a background asynchronous task (`_keepalive_loop`) that continuously pings Deepgram via `dg_connection.keep_alive()` every 5 seconds. This prevents `net0001` socket dropouts during natural pauses in conversation.
   - **Clean Buffer Flush**: Upon session termination, sends empty frame `b''` to flush Deepgram's acoustic buffer before disconnecting.
4. **In-Memory Linear Interpolation Audio Resampling (`resample_to_16k`)**:
   - Implemented in `app/services/live_transcription_service.py` via `np.interp`.
   - While the transcription pipeline expects standard 16,000Hz mono audio, browser Web Audio contexts frequently record at native hardware rates (44,100Hz or 48,000Hz).
   - The server dynamically calculates resampling factors, maps time indices, and interpolates raw Int16 PCM samples directly to 16kHz Float32 arrays in memory without temporary disk I/O, preventing acoustic pitch distortions and transcription pipeline crashes.
5. **Live Diarized PCM Streaming & Watchdogs (`MeetingSourceType.LIVE_BROWSER`)**:
   - Captures browser microphone audio via an `AudioWorklet` (`pcm-processor.js`), streaming 16kHz Int16 raw PCM frames over `WS /live/transcribe` with ticket replay protection.
   - **120-Second Idle Timeout**: `IDLE_TIMEOUT_SECONDS = 120`. If an open WebSocket receives no audio bytes for 2 minutes, the server dispatches `{"action": "timeout", "is_final": True}` and closes the connection to reclaim server memory.
   - **Minimum Audio Duration Guard**: Validates that accumulated audio is $\ge 1.0\text{s}$ (`(total_bytes / 2) / sample_rate`). Recordings shorter than 1 second return `{"action": "stopped", "confirmed": "", "error": "Recording too short"}` and skip Whisper/Deepgram.
6. **Local faster-whisper `large-v3-turbo` CPU int8 Engine**:
   - Offline transcription is powered by faster-whisper `large-v3-turbo` with `device='cpu'` and `compute_type='int8'` quantization.
   - **20-Client Prompt Injection Cap**: To prevent exceeding Whisper's 224-token prompt buffer, dynamic client-name prompt injection (`_build_initial_prompt`) caps injected active tenant client names to 20 (`names_str = ", ".join(client_names[:20])`).
   - Dual Diarization Modes: PyAnnote 3.1 speaker diarization supports **Solo Mode** (`diarize=False` for ~20s single-speaker voice memos) and **Meeting Mode** (`diarize=True` for multi-party advisory calls).
   - Voice Activity Detection (VAD) & Hallucination Suppression: Filters silent or degraded audio chunks (`no_speech_prob > 0.6 and avg_logprob < -1.0`, `compression_ratio > 2.4`).
7. **ASR Hinglish Translation & Normalization Layer (`translate_transcript`)**:
   - Pre-extraction AI translation layer (`app/services/ai_routing_service.py`, `app/ai/provider.py`) translates colloquial Hinglish speech into polished professional English.
   - Automatically repairs common Indian English / Hinglish ASR phonetic corruptions (e.g., `"Dil"` $\rightarrow$ `"Deal"`, `"Mande"` $\rightarrow$ `"Monday"`).
   - Enforces strict entity preservation rules: maintains Indian names in standard English transliteration (e.g., `'मनोज'` / `'Daksh'`, not phonetic approximations) and preserves competitor financial product names.
8. **Dynamic Relative Calendar Reference Map**:
   - Prior to invoking Groq Llama 3.3 for meeting intelligence extraction (`app/ai/provider.py`), the backend precomputes a `calendar_reference` dictionary based on `meeting_date`.
   - Computes exact ISO dates for `tomorrow`, `next_monday`, `next_tuesday`, `next_wednesday`, `next_thursday`, `next_friday`, `next_saturday`, and `next_sunday`.
   - The extraction system prompt explicitly instructs the LLM: *"CRITICAL: Convert ALL relative times like 'tomorrow', 'monday', 'next week' into exact YYYY-MM-DD by looking them up in the provided 'calendar_reference' dictionary. NEVER calculate dates yourself."*
9. **Strict Human-in-the-Loop (HITL) Client Creation Policy**:
   - The system strictly **disables silent automatic client creation** (`app/services/client_identification_service.py`).
   - Even when LLM extraction confidence is 1.0, unrecognized client names are always returned with status `client_identification_required`.
   - Forces the frontend to display the `#confirmPanel` modal, allowing the relationship manager to confirm or edit the client's name, pre-populated email (`new_client_email`), and WhatsApp phone number (`new_client_whatsapp_phone`).
10. **PII Sanitization & Dynamic Token Cost Estimation**:
    - `AIRoutingService._log_audit` scrubs sensitive customer financial data from persistent plain-text logs by recording `raw_response_json='{"stored": false}'` in `ai_extraction_logs`.
    - Dynamically estimates inference costs in USD based on model tiers ($0.00001/prompt + $0.00002/completion for 8B/Flash models; $0.0001/prompt + $0.0002/completion for 70B models) and records this into `AIExtractionLog.cost_usd`.
11. **Word-Based Semantic Chunking with Sliding Window**:
    - Splits meeting transcripts into semantic chunks using a 300-word window with a 50-word overlap (`chunk_size=300, overlap=50`) before generating 1024-dimensional `BAAI/bge-m3` vectors for PostgreSQL `pgvector`.
12. **Startup Model Preloading & Lifespan Optimizations**:
    - During FastAPI lifespan initialization (`app/core/lifespan.py`), background tasks preload `BAAI/bge-m3` and Faster-Whisper into RAM.
    - If `transcription_mode == "cloud"`, the Whisper preload is skipped, saving ~4GB RAM on the API server.
13. **MinIO Storage Purging Lifecycle (`PHILIXA_RETAIN_AUDIO`)**:
    - Audio files uploaded to MinIO are automatically purged post-transcription when `PHILIXA_RETAIN_AUDIO=0` (default), retaining only structured transcripts and embeddings.
14. **Fast Browser Dictation (`en-IN`)**: Client-side speech-to-text using the browser's native Web Speech API (`fast-dictation.js`), tuned specifically for Indian English financial terminology with automated Android restart handling.
15. **Human-in-the-Loop (HITL) Triage Modals**:
    - **Client Confirmation Modal (`#confirmPanel`)**: Surfaced when AI client identification confidence is low or ambiguous; allows the advisor to assign the meeting to an existing client or create a new one with email and phone (`POST /api/v1/meeting-notes/{id}/confirm-client`).
    - **Transcript Review Modal (`#editTranscriptPanel`)**: Allows advisors to review, correct acoustic errors in audio transcripts, and trigger re-extraction (`PATCH /api/v1/meeting-notes/{id}/transcript`).

---

### 3. Stateful Agentic Copilot, Vector RAG & Action Engine

The Copilot subsystem (`app/services/portfolio_copilot_service.py`) combines deterministic fast-paths, heuristic query interception, and a compiled LangGraph state machine:

```
                                      [ User Query ]
                                             |
                                             v
                             +-------------------------------+
                             | _requires_evidence_search()?  |
                             +-------------------------------+
                                     /               \
                          (Yes: Sentiment)        (No: Standard)
                                   /                   \
                                  v                     v
                 +----------------------+    +-------------------------------+
                 | Direct Vector Route  |    |   Deterministic Fast-Paths    |
                 | (Bypasses Broken SQL)|    | - Greetings                   |
                 +----------------------+    | - Asia/Kolkata Calendar Check |
                                  |          | - Direct Client Lookups       |
                                  |          +-------------------------------+
                                  |                     | (If no match)
                                  |                     v
                                  |          +-------------------------------+
                                  |          |    LangGraph: planner_node    |
                                  |          +-------------------------------+
                                  |                   /        |        \
                                  |                  /         |         \
                                  |                 v          v          v
                                  |         +-----------+ +-----------+ +-----------+
                                  |         | sql_gen_  | | semantic_ | |  action_  |
                                  |         |   node    | |   node    | |   node    |
                                  |         +-----------+ +-----------+ +-----------+
                                  |               \            |            /
                                  +--------------> \           |           /
                                                    v          v          v
                                             +-------------------------------+
                                             |       synthesizer_node        |
                                             | Grounded Answer with Evidence |
                                             +-------------------------------+
```

- **Unstructured Evidence Query Interceptor (`_requires_evidence_search`)**:
  - Deterministic regex interceptor scanning inbound queries for unstructured sentiment and qualitative terms (`discount`, `concern`, `complaint`, `issue`, `problem`, `sentiment`, `mood`, `interested`, `manga`, `chinta`, `pareshan`).
  - Directly forces routing to `semantic_node` (pgvector cosine search), preventing the LLM from hallucinating invalid SQL queries on nonexistent relational columns.
- **Deterministic Fast-Paths**:
  - `_is_greeting(query)`: Immediate conversational greeting without LLM latency.
  - `_meeting_schedule_date(query)`: Calculates weekday calendar schedules in `Asia/Kolkata` timezone (e.g., "milna", "Monday meetings").
  - `_extract_client_lookup_name(query)`: Direct SQL profile retrieval for queries like "Who is Vikram Malhotra?" or "Vikram kaun hai".
- **Safe Read-Only NL-to-SQL (`sql_generator_node`)**: Generates PostgreSQL queries with system prompt guardrails preventing mutating operations. For `member` roles, automatically appends tenant RBAC constraints (`AND user_id = :user_id`).
- **Semantic Evidence Retrieval (`semantic_node`)**:
  - Transcripts are chunked and embedded into 1024-dimensional vectors using `BAAI/bge-m3`.
  - Stored in the `meeting_evidence` table with Cosine Distance indexing (`<=>`).
- **LangGraph Action Node (`action_node`) & Two-Phase Interactive Reminder Staging**:
  - When an advisor issues an actionable natural language command (e.g., *"Send a reminder to Vikram about Friday's mutual fund allocation"*), the `planner_node` routes execution to `action_node`.
  - **Phase 1: Validation, Copy Generation & Redis Staging (300s TTL)**:
    1. `ReminderService.draft_client_reminder` resolves the client in the active workspace and verifies contact channels (`email` and/or `whatsapp_phone`).
    2. Prompts the LLM to generate channel-tailored JSON drafts: an executive `email_subject` and `email_body`, plus a concise `whatsapp_body` (< 700 characters, no markdown formatting).
    3. Caches the pending action payload in **Redis with a 300-second (5-minute) TTL** under key:
       - `pending_reminder_copilot:{user_id}` for Copilot chat requests.
       - `pending_reminder:{user_id}` for Voice assistant requests.
    4. Formulates a preview confirmation prompt for the advisor (e.g., *"I drafted this for Vikram. WhatsApp: '...' and Email subject '...'. Should I send it?"*).
  - **Phase 2: Confirmation or Cancellation Turn**:
    1. **Bilingual Fast-Path Affirmation**: Spoken affirmations (*"yes"*, *"send it"*, *"haan bhej do"*) or Copilot typed keywords (*"yes"*, *"send"*, *"haan"*, *"bhej do"*, *"confirm"*) retrieve the staged payload from Redis, invoke `ReminderService.dispatch_client_reminder()`, execute concurrent asynchronous dispatch, persist delivery records in the `communication_logs` table, and delete the Redis key.
    2. **Cancellation Fast-Path**: Spoken cancellations (*"no"*, *"cancel"*, *"mat bhej"*) or Copilot typed keywords (*"no"*, *"cancel"*, *"stop"*, *"mat bhej"*) purge the Redis draft immediately and confirm cancellation without invoking the LLM planner.
  - **Natural Language Channel Disambiguation (`ReminderService._resolve_channel`)**:
    - If `"whatsapp"` or `"what's app"` is present without `"email"` $\rightarrow$ channel is `"whatsapp"`.
    - If `"email"` or `"e-mail"` is present without `"whatsapp"` $\rightarrow$ channel is `"email"`.
    - If both or neither are mentioned $\rightarrow$ defaults to `"both"` (concurrent multi-channel delivery).

> 🔔 **Multi-Modal / Multi-Agent Client Reminder Scheduling**:
> Relationship Managers can schedule and send client reminders through **EITHER** interface modality:
> 1. **Conversational Voice (Philixa Brain FAB & Hero Mic)**: Dictate naturally in English or Hinglish (e.g., *"Philixa, WhatsApp Manoj that I will call him tomorrow at 10 AM"* or *"Email Vikram ko mutual fund comparison bhej do"*). The voice assistant classifies the `SEND_REMINDER` intent, drafts the copy, stages the draft in Redis (`pending_reminder:{user_id}` for 300s), and speaks a confirmation preview back via TTS. The advisor simply confirms with *"Haan bhej do"* or *"Yes send it"* (`CONFIRM_ACTION`) to trigger dispatch.
> 2. **Copilot Text & Chat (380px Sidecar Dock & REST API)**: Type into the Copilot chat sidecar or submit to `POST /api/v1/dashboard/copilot/ask` (e.g., *"Send an email and WhatsApp reminder to Priya about our portfolio review"*). The LangGraph state machine routes to `action_node`, drafts message copy, stages the payload in Redis (`pending_reminder_copilot:{user_id}` for 300s), and returns a formatted preview bubble. The advisor confirms with a quick reply (*"yes"*, *"bhej do"*) which triggers the deterministic Hinglish fast-path interceptor.
> 
> In both modalities, `ReminderService` generates channel-tailored copy, dispatches concurrently via `asyncio.gather` across Meta WhatsApp Cloud API v25.0 and transactional SMTP email, and audits delivery in the `communication_logs` database table.

- **Multi-Tier AI Routing**:
  - Primary Extraction & Planning: Groq Cloud (`llama-3.3-70b-versatile`).
  - Review / Fallback: Google Gemini (`gemini-2.5-flash` / `gemini-3.6-flash`).
  - Copilot Reasoning: Threaded execution preventing event loop starvation.

---

### 4. Conversational Voice Assistant & 6-Way Intent Engine

Philixa Brain (`app/services/voice_assistant.py`) is a full-duplex conversational voice agent tailored for mobile and desktop advisors:

- **6-Way Intent Classification Engine**:
  - `VoiceAssistantService.chat` evaluates spoken input and classifies it into one of six discrete operational intents:
    1. `QUERY`: Natural language question regarding CRM data or client history (delegates to Copilot).
    2. `SAVE_MEETING`: Dictation of meeting notes or interaction summary. Creates a `Meeting` record with `source_type="voice"` and triggers asynchronous processing via FastAPI `BackgroundTasks`.
    3. `SEND_REMINDER`: Voice command to follow up or message a client via WhatsApp or Email. Invokes `ReminderService.draft_client_reminder`, stages draft in Redis (`pending_reminder:{user_id}`, 300s TTL), and prompts for confirmation.
    4. `CONFIRM_ACTION`: Affirms a pending staged reminder (*"yes"*, *"send it"*, *"haan bhej do"*, *"correct"*). Fetches the staged draft from Redis, executes concurrent dispatch, records outbound communications, and cleans up Redis.
    5. `REJECT_ACTION`: Cancels a pending staged reminder (*"no"*, *"cancel"*, *"stop"*, *"mat bhej"*). Immediately purges the Redis key and confirms cancellation.
    6. `GENERAL_CHAT`: Conversational advisory assistance.
- **Bilingual Hinglish Regex Fallback Parsers**:
  - `_looks_like_reminder_command(text)` provides a deterministic safety net catching reminder commands if the LLM classifier is slow or unavailable (matches combinations of `"reminder"|"email"|"message"|"whatsapp"` and `"send"|"bhej"`).
  - `_reminder_client_name_from_text(text)` parses Indian speech patterns: extracts client names from Hinglish constructs (`r"^\s*([a-z...]+)\s+ko\b"`, e.g., *"Rajesh ko message bhejo"*) and English patterns (`r"(?:remind|email|message)\s+([a-z...]+)\s+(?:that|about|to)\b"`).
- **Asynchronous Background Meeting Ingestion**:
  - When the `SAVE_MEETING` intent is classified, the service immediately creates a `Meeting` database record with `source_type="voice"` and dispatches an asynchronous background task via FastAPI `BackgroundTasks` calling `MeetingProcessingService.process_existing_meeting`.
  - Returns an instant audio/text acknowledgment to the advisor while entity extraction, commitment tracking, and risk analysis run in the background.
- **Hindi Name & Phonetic Normalization**: Translates spoken Devanagari names to standard English representations (e.g., `'मनोज'` $\rightarrow$ `'Manoj'`).
- **Sarvam AI `bulbul:v3` Hinglish Voice Synthesis & Dual Fallback (`POST /api/v1/voice/speak`)**:
  - **Priority 1 (Sarvam AI)**: When `PHILIXA_SARVAM_API_KEY` is configured, streams high-fidelity Indian-accented speech synthesis via model `bulbul:v3`, speaker `shreya`, and language `hi-IN` (returning `audio/wav`).
  - **Priority 2 (Deepgram Aura Fallback)**: If Sarvam AI is unconfigured or encounters API exceptions, automatically falls back to Deepgram Aura (`model="aura-asteria-en"`, returning `audio/mpeg`).

---

### 5. Automated Rules Engine, Risk Scoring & CRM Intelligence

Philixa 6.0 features automated business intelligence services managing client lifecycles and proactive risk scoring:

- **Automated Rules Engine (`RulesEngineService`)**:
  - `sync_client_tasks_and_risks`: Synchronizes extracted meeting commitments into `FollowUpTask` items, dynamically calculating status flags (`is_completed`, `is_overdue`, and `is_due_today`) based on current UTC time and configured due date thresholds (`PHILIXA_DUE_DATE_THRESHOLD`).
  - **Deterministic Risk Signal Scoring**: Evaluates extracted meeting concerns and creates `RiskSignal` records. Sets `is_high_risk = True` and `requires_review = True` if:
    $$\text{severity} \in \{\text{"high"}, \text{"critical"}\} \quad \lor \quad (\text{severity} == \text{"medium"} \land \text{confidence} > 0.85)$$
- **Ask-Client Timeline Query Parser & Semantic Search (`AskClientService`)**:
  - `POST /api/v1/clients/{id}/ask` utilizes `_parse_query` to extract structured JSON metadata (`start_date`, `end_date`, `exact_keywords`, `optimized_query`) from natural language queries.
  - Executes date-bounded pgvector hybrid semantic search over `meeting_evidence`, generating synthesized answers with exact meeting citations (e.g., `Sources: Meetings 12, 15`).
- **Fuzzy Commitment Deduplication**:
  - Normalizes task strings and computes text similarity (`app/utils/text_normalization.py`). Commitments with similarity $\ge 0.72$ against existing open tasks for the same client are deduplicated, updating status lifecycles rather than creating duplicate clutter.
- **Pre-Meeting Briefing & Talking Point Synthesis (`MemoryService`)**:
  - Generates executive pre-meeting dossiers summarizing the last interaction, open commitments, owned banking products, primary client concerns, and AI-suggested conversational talking points.
- **Decoupled Client Product Tracking**:
  - Decouples `products_owned_json` (active banking/investment products held by client) from `products_interested_json` (prospective upsell interest noted during discussions).
- **Cascade Client Deletion (`ClientRepository`)**:
  - Deleting a client (`DELETE /api/v1/clients/{id}`) safely cascades deletion across all meetings, commitments, tasks, risk signals, and vector embeddings in `meeting_evidence`.

---

### 6. Distributed ARQ Worker & Scheduled Sweeps

Background execution is handled by an asynchronous ARQ worker container (`app/worker.py`) sharing Redis connection pools and database sessions:

- **Registered Asynchronous Tasks**:
  - `process_meeting_transcription`: Downloads audio from MinIO, executes FFmpeg filtering, Whisper transcription with Hinglish banking prompts, PyAnnote diarization, LLM entity extraction, rules engine synchronization, and enqueues embedding generation.
  - `generate_meeting_embeddings`: Splits transcripts into semantic chunks, generates 1024-dim `BAAI/bge-m3` vectors, and persists them into `meeting_evidence`.
  - `_notify_meeting_processed`: Real-time post-meeting notification dispatch sending immediate bilingual WhatsApp/Email alerts to the RM upon processing completion or failure.
- **Worker Configuration & Memory Optimizations**:
  - **Conditional Whisper Preloading**: On worker startup (`startup(ctx)`), the system evaluates `settings.enable_audio_upload`. If `False` (`0`), the worker skips preloading the heavy Whisper model and PyAnnote diarization pipeline into worker memory, logging: *"Audio Upload disabled. Skipping Whisper preload (Saved ~2GB RAM!)"*.
  - **Worker Concurrency Controls**: Configured with `max_jobs = 10` concurrent job slots and `allow_abort_jobs = True` to enable aborting hanging tasks via Redis.
- **Registered Distributed Cron Jobs (4 Total Sweeps)**:
  - `send_pre_interaction_briefs` (**07:00 UTC Daily**): Aggregates upcoming meetings for the day and sends executive briefings to RMs.
  - `send_client_followups` (**08:00 UTC Daily**): Identifies overdue commitments and pending client follow-up tasks and dispatches alerts.
  - `retry_failed_notifications` (**Every 15 Minutes**): Retries failed WhatsApp and email dispatches with exponential backoff.
  - `cleanup_demo_accounts` (**Hourly at Minute 0**): Purges expired `demo_guest_*` sandbox users and cascade-deletes all associated temporary organizations, meetings, commitments, and vectors.
- **Standalone CLI Maintenance Tool (`scripts/cleanup_demo_accounts.py`)**:
  - In addition to the hourly ARQ worker cron, operators can manually purge expired demo accounts or schedule OS-level cron sweeps using the standalone CLI script:
    ```bash
    python scripts/cleanup_demo_accounts.py
    ```
  - The script executes database cascade deletions removing expired guest accounts, organization memberships, sessions, clients, meetings, commitments, and vector embeddings in a single atomic transaction.

---

### 7. Dual-Channel Notification Engine & Delivery Audit

Philixa 6.0 strictly separates transactional authentication messaging from operational CRM alerts and client reminders:

```
[ Notification Intent ] ────────────────► [ Routing Adapter ] ──────────────► [ Delivery Target ]
Auth / Invite / Reset   ────────────────► aiosmtplib (SMTP)   ──────────────► User Email Inbox
Daily Briefs / Overdue  ────────────────► WhatsAppAdapter      ──────────────► Meta Graph API v25.0
Client Reminders (Both) ────────────────► ReminderService      ──────────────► WhatsApp + SMTP
Offline Dev / Testing   ────────────────► SimulatedAdapter     ──────────────► Synthetic Delivery
```

1. **Isolated Transactional Email (`EmailAdapter` via `aiosmtplib`)**:
   - Exclusively handles user email verification, password reset links, and workspace member invitations.
   - Operates independently of the global notification channel preference.
2. **Meta WhatsApp Cloud API Adapter (`WhatsAppAdapter`)**:
   - Integrates with Meta Graph API `v25.0` (`https://graph.facebook.com/v25.0/{phone_number_id}/messages`).
   - Evaluates per-user quiet hours (`quiet_hours_start`, `quiet_hours_end`) and timezone settings, supporting midnight-spanning intervals (e.g. 22:00 to 08:00).
   - Prevents duplicate dispatches using PostgreSQL JSONB idempotency queries (`metadata_payload.op("->>")("idempotency_key") == idempotency_key`).
   - Tracks internal delivery receipts (`SENT`, `DELIVERED`, `READ`, `FAILED`) in `notification_deliveries`.
3. **Real-Time Webhook Synchronization for `communication_logs` (18th Table)**:
   - Outbound client reminders dispatched via `ReminderService` are tracked in the tenant-scoped `communication_logs` table.
   - When Meta WhatsApp Cloud API webhooks deliver status updates (`sent`, `delivered`, `read`, `failed`), `app/api/v1/routes_webhooks.py` simultaneously reconciles **both** internal RM alerts (`NotificationDelivery`) and client-facing reminders (`CommunicationLog`) via `CommunicationRepository.update_status_by_provider_id`.
   - On delivery failures, nested Meta Graph API error structures (`errors[0]`: `code`, `title`, `error_data.details`) are extracted and formatted into clear error descriptions.
4. **Simulated Notification Adapter (`SimulatedNotificationAdapter`)**:
   - Implemented in `app/services/notifications/simulator.py` for zero-cost offline development and automated testing.
   - When `PHILIXA_NOTIFICATION_MODE` is set to `"simulated"`, the simulator generates synthetic message IDs (`sim_{uuid}`), simulates 500ms network latency, logs payloads, and automatically transitions status from `SENT` to `DELIVERED` on subsequent status checks.

---

## 🎨 Frontend Single-Page Application (SPA) Architecture

Philixa 6.0 features a responsive, accessible, full-featured Single-Page Application (SPA) built with vanilla modern JavaScript (`app/web/app.js`), semantic HTML5 (`app/web/index.html`), and a bespoke CSS design system (`app/web/styles.css`).

```
+-------------------------------------------------------------------------------------------------------------------------------+
|                                            PHILIXA 6.0 SPA WORKBENCH INTERACTION MAP                                          |
+-------------------------------------------------------------------------------------------------------------------------------+

  [ Topbar: Workspace Switcher Dropdown | Scope Toggle (Team/Me) | Copilot Sidecar Trigger | Avatar Profile & Settings ]
  +---------------------------------------------------------------------------------------------------------------------------+
  |  [ 4-Card Verdict Strip: Active Clients (#) | Pending Tasks (#) | Meetings Logged (#) | Risk Alerts (Status Badge) ]      |
  +---------------------------------------------------------------------------------------------------------------------------+
  |  [ Hero Voice Assistant Hub (.mfd-hero): 132px Rotating Conic Halo (.mfd-halo) + 96px Pulse Mic (.mfd-mic) + Time Greeting]
  +---------------------------------------------------------------------------------------------------------------------------+
  |                                                  DESKTOP 60 / 40 WORKBENCH                                                |
  |  +-----------------------------------------------------+  +------------------------------------------------------------+  |
  |  | LEFT PANE (60%): 4-Tab Smart Intake Editor          |  | RIGHT PANE (40%): Structured Diff Review Workbench         |  |
  |  | * Tab 1: Paste Notes (Cmd+Enter Process)            |  | * Category Filter Pills (All / Commitments / Risks / Memory)|  |
  |  | * Tab 2: S3 Audio Drag-and-Drop (10MB Limit)        |  | * Interactive Diff Cards (Spacebar / Click Selection)      |  |
  |  | * Tab 3: Live Audio Worklet (Solo vs Diarize PCM)   |  | * Inline Title Edit (✎) & Due Date Pickers                 |  |
  |  | * Tab 4: Fast Dictation (en-IN Web Speech + Restart)|  | * Batch Action Bar (Cmd+Shift+Enter / Cmd+S Batch Sync)    |  |
  |  +-----------------------------------------------------+  +------------------------------------------------------------+  |
  +---------------------------------------------------------------------------------------------------------------------------+
  |  [ Daily Priorities & Risk Monitor ]  [ Client Memory Dossier Accordion & Q&A ]  [ Interactive Commitment Ledger Table ]  |
  +---------------------------------------------------------------------------------------------------------------------------+
  |  [ Persistent 380px AI Copilot Sidecar Dock (Cmd+Shift+L) with Grounded Client Pill & Dynamic Token Budget Progress Meter] |
  |  [ Philixa Brain Voice Agent (4-State Visual Machine: Idle / Listening / Thinking / Speaking + 4000ms Silence Auto-Stop) ] |
  |  [ Mobile Bottom Navigation Bar (#mfdBottomNav <= 768px): Home | Notes | Today | Memory Quick Tabs                       ] |
  +---------------------------------------------------------------------------------------------------------------------------+
```

### 1. 6-View Fullscreen Auth Modal & State Machine
The client authentication layer (`#authModal`) operates as a complete 6-state machine managing onboarding and recovery flows:
- **State 1: Login (`#viewLogin`)**: Email and password authentication with demo workspace shortcut.
- **State 2: Registration (`#viewRegister`)**: Account creation with a toggle between **Company Workspace** (team collaboration) and **Individual Workspace** (solo advisor).
- **State 3: Email OTP Verification (`#viewVerifyEmail`)**: 6-digit OTP entry view with resend countdown.
- **State 4: Forgot Password Request (`#viewForgotPassword`)**: Email submission for password recovery links.
- **State 5: Password Reset Confirmation (`#viewResetPassword`)**: Token-authenticated password reset with client-side password matching validation.
- **State 6: Workspace Invite Acceptance (`#viewInviteAccept`)**: Allows invited team members to accept invites and establish credentials.
- **Deep-Linking & FOAC Prevention**: Supports URL deep-linking (`?action=verify-email`, `?action=reset-password`, `?invite=...`) and uses `.not-logged-in` CSS gating to eliminate Flash of Unauthenticated Content (FOAC). Left panel highlights CRM value propositions with `/static/premium_dashboard.jpg`.

### 2. Google Identity Services (GSI) One-Tap SSO Integration
Integrated Google Sign-In SDK (`https://accounts.google.com/gsi/client`) providing one-tap authentication (`#g_id_onload`, `.g_id_signin`). Captures Google ID tokens and submits them to `POST /api/v1/auth/google` via `handleGoogleCredentialResponse()`.

### 3. Multi-Tenant Workspace Context Switcher & Plan Badge
Sidebar dropdown selector (`#workspaceSelect`) populated with user's active organization memberships. Switching triggers `POST /workspaces/switch`, updates CSRF and session state, and re-renders the dashboard. Topbar displays dynamic subscription plan badge (`#topbarPlanBadge` e.g., "Free", "Pro").

### 4. Workspace Team Member Management & Dynamic RBAC Modal
Interactive modal (`#memberModal`) accessible to Owners/Admins via avatar dropdown. Displays member count badge (`#memberCountBadge`) and active roster table (User/Email, Role, Status, Joined date). Includes:
- **In-App Invitation Form (`#inviteMemberForm`)**: Invites members by email and role.
- **In-Place Role Selector (`.member-role-select`)**: Allows Owners to promote/demote members (`PATCH /workspaces/members/{id}/role`).
- **Member Removal Action (`.btn-remove-member`)**: Removes users with confirmation safeguards (`DELETE /workspaces/members/{id}`).

### 5. User Profile Avatar Dropdown, Initials Badges & Account Deletion
Circular avatar button (`#avatarBtn`) displaying computed 1-2 letter uppercase initials based on user name/email. Opens dropdown menu (`#avatarMenu`) containing display name, email, shortcuts for Member Management, Preferences, Theme Toggle, and Sign Out. In Settings Modal, features a "Danger Zone" with a "Permanently Delete Account" button (`#deleteAccountBtn`) issuing `DELETE /auth/me` with double-confirmation prompt.

### 6. Responsive App Shell, Collapsible 64px Icon-Rail & Mobile Drawer
Dual-state responsive navigation:
- **Desktop Collapse to 64px Icon Rail**: On viewports $> 768\text{px}$, toggling navigation via `#sidebarToggleBtn`, logo click (`#logoToggleBtn`), or `Cmd+[` / `Ctrl+[` shrinks the sidebar from 240px to 64px (`.mfd-layout.sidebar-collapsed`). Brand titles, client selector text, and nav labels hide cleanly, leaving centered iconography.
- **Mobile Slide-Over Drawer with Blurred Backdrop**: On mobile viewports ($\le 768\text{px}$), the sidebar is parked off-screen (`left: -280px`). Tapping hamburger button `#mobileNavToggleBtn` activates `.mobile-sidebar-open` on `<body>`, sliding the drawer into view alongside an injected blurred backdrop (`#mobileSidebarBackdrop`). Tapping anywhere on the backdrop dismisses the drawer. Includes Zoho-style loading splash screen (`#contentLoader`) with pulsing "P6" logo.

### 7. Dark / Light Theme System with WCAG AAA Contrast Tokens
Complete dark/light semantic design system (`.dark-theme`) mapped to zinc palettes and WCAG AAA contrast tokens (`--bg`, `--panel`, `--ink`, `--muted`, `--line`, `--accent`, `--success-*`, `--warning-*`, `--danger-*`, `--primary-*`, `--ai-*`). Theme toggle button in avatar menu (`#themeToggleBtn`) dynamically switches theme and saves to `localStorage.getItem("theme")`, loaded synchronously in `<head>` to prevent theme flash.

### 8. Homogeneous 4-Card Verdict Strip Metrics with Jump Navigation
Modern 4-card metric strip replacing legacy asymmetrical cards, built with `role="button"` and `tabindex="0"` for full mouse and keyboard (`Enter` / `Spacebar`) accessibility:
1. **Active Clients Card (`#verdictCardClients`)**: Shows active client count; clicking or pressing Enter focuses the `#topClientSelect` Global Client Filter.
2. **Pending Commitments Card (`#verdictCardPending`)**: Shows open commitment count; clicking or pressing Enter smooth-scrolls the viewport directly to `#commitmentPanel`.
3. **Meetings Logged Card (`#verdictCardMeetings`)**: Displays monthly processed meeting count from `/api/v1/dashboard/metrics`; clicking or pressing Enter focuses the `#rawNotes` textarea.
4. **Risk Alerts Card (`#verdictCardRisks`)**: Shows active deal/churn risk count with dynamic badge ("All clear" green vs "N Active" rose); clicking or pressing Enter smooth-scrolls directly to `#day4Panel` (Daily Priorities & Risk Signals).

### 9. Mobile Bottom Navigation Bar & 4 App-Level Tab Sections (<= 768px)
On mobile displays ($\le 768\text{px}$), the vertical desktop layout adapts to an app-native mobile shell controlled by a fixed 60px blurred bottom navigation bar (`#mfdBottomNav`):
- 🏠 **Home**: Displays the greeting, 4-card metric strip, and the large animated Hero Voice Assistant.
- 📝 **Notes**: Surfaces the 4-tab Smart Intake Editor (Paste, Audio, Live, Fast Dictation) and Extracted Diff Review Workbench.
- ☀️ **Today**: Houses Daily Priorities Follow-up tasks (Overdue, Due Today, Upcoming) and False-Alarm Safe Risk Monitor.
- 🧠 **Memory**: Displays the Client Memory Dossier, Pre-Meeting Brief Card, Ask AI Q&A, Commitment Ledger, and Team Performance table.
- **Behavior**: Tapping any tab executes `switchMobileTab(tabName)`, toggling `.active` states and smooth-scrolling `.mfd-main` to the top. On window resize $> 768\text{px}$, all panels restore simultaneously to desktop layout.

### 10. Tablet Responsive Segmented Tab Switcher (< 1024px)
On tablet displays ($< 1024\text{px}$), transforms desktop 60/40 horizontal split into full-width segmented tab switcher between "📝 Meeting Note Intake" (`#tabMobileIntake`) and "✨ Extracted Diffs (N)" (`#tabMobileDiffs`). Automatically switches to Extracted Diffs tab upon completion of note extraction.

### 11. 4-Tab Smart Intake Editor & Audio DSP Worklets
Master smart intake editor with 4 ingestion modes:
- **Paste Notes (`#viewText`)**: Textarea with spellcheck, meeting date picker, and "✨ Process with AI" CTA (`Cmd+↵`).
- **Upload Audio (`#viewAudio`) with 4-State Polling Loop**:
  - Drag-and-drop zone (`#uploadBox`) enforcing the **10MB file ceiling** (`.mp3, .m4a, .wav, video/mp4`).
  - **4-State Polling State Machine**: Queries `GET /api/v1/meeting-notes/{meeting_id}` every 5 seconds, handling:
    1. `processed`: Displays success, renders extracted diff cards, and refreshes metrics.
    2. `client_identification_required`: Auto-populates `#newClientName`, `#newClientEmail`, `#newClientPhone` and displays `#confirmPanel`.
    3. `manual_review_required` / `failed`: Displays "Audio Needs Review", injects raw transcript into `#editTranscriptText`, opens the `#editTranscriptPanel` modal, and prompts the advisor to edit and click "Save & Re-process" (`#saveTranscriptBtn`).
    4. *In-progress*: Animates pulsating progress status.
- **Runtime Feature Flag Graceful UI Degradation (`health.enable_audio_upload`)**:
  - On startup, `bootstrapApp()` queries `/health`. If `enable_audio_upload === false`, the UI dynamically removes the Upload Audio tab button (`#tabAudioBtn.style.display = 'none'`) and hides `#viewAudio`, preventing advisors from uploading files when MinIO or FFmpeg is disabled.
- **Live Record Hub (`#viewLive`) & AudioWorklet Engine (`pcm-processor.js`)**:
  - Runs a high-priority browser audio thread via `AudioWorkletProcessor`, sampling Web Audio Float32 inputs, clamping, and converting to 16-bit Int16 little-endian chunks.
  - Utilizes an internal **4096-sample buffer** (~256ms at 16kHz) to eliminate audio crackling on mobile devices.
  - Emits chunks via zero-copy transferable `ArrayBuffer` memory pipes directly to `WS /api/v1/live/transcribe`.
  - **Protocol Action Handling**: Handles server messages for `processing`, `timeout` (auto-stopped after 2 minutes of silence), and `stopped` (receives confirmed transcript, automatically injects it into `#rawNotes`, and triggers `tabTextBtn.click()` for immediate review).
- **⚡ Fast Dictation (`#viewFastDictation`) with Android Auto-Restart (`fast-dictation.js`)**:
  - Browser-native speech recognition configured for `en-IN` (Indian English).
  - **Android Premature Termination Fix**: Chromium on Android drops recognition when `continuous: true` is set; `fast-dictation.js` sets `continuous: false` and uses an `onend` auto-restart loop to provide continuous dictation.
  - **Dual-Style Live Renderer**: Renders committed final words in bold ink text and unconfirmed interim hypotheses in muted italics in real time.
  - Stop & Save transfers complete text directly to `#rawNotes` and activates the Paste tab.
- **Pre-selection Client Dropdown (`#knownClient`)**.

### 12. Structured Diff Review Workbench (60/40 Split Master-Detail)
Right-pane 40% interactive staging workbench for reviewing extracted entities before synchronizing to client memory:
- **Category Filter Pills**: Real-time filtering with badge counters for `All`, `Commitments`, `Risks`, `Memory`.
- **Interactive Diff Cards**: Full-card click or spacebar to toggle selection (`role="checkbox"`, `aria-checked`).
- **Inline Editing**: Inline editable Title (`✎` button) and Due Date input (`<input type="date">`).
- **Source Quote Attribution**: Verbatim quotes linking extracted points to transcript text.
- **Micro-Dismiss Action**: `✕` button to discard specific hallucinations or invalid items.
- **Batch Diff Action Bar**: `Discard All` and `✓ Sync Selected (N)` (`<kbd>⌘⇧↵</kbd>` / `Cmd+S`).
- **Focus Trapping**: Automatically shifts focus to the first diff card when extraction finishes (`window.setTimeout(() => firstCard.focus(), 50)`).

### 13. Global Client Filter Omnibar, Cascade Delete & Owner Decoration
Sidebar client filter dropdown (`#topClientSelect`) filtering all CRM views and dossier memory:
- **Cascade Delete Action**: Selecting a client displays `#deleteSelectedClientBtn` (🗑️) to delete the client profile and cascade-delete all meetings, commitments, and vectors (`DELETE /api/v1/clients/{id}`).
- **Team Scope Client Dropdown Owner Decoration**: In "Team Workspace" scope, all client dropdowns (`#topClientSelect`, `#knownClient`, `#confirmClientSelect`) automatically decorate client entries with owner attribution (e.g. `Rajesh Sharma · A` or `Rajesh Sharma (advisor@apexwealth.com)`) to prevent name collisions across multiple advisors.

### 14. Client Profile & Communication History Modal (`#clientProfileModal`)
Comprehensive client relationship and communication audit modal:
- **Sidebar Profile Button (`#viewClientProfileBtn`, 📝)**: Appears beside client delete button when a client is selected.
- **Contact Details Management**: Opens `#clientProfileModal`, loads client WhatsApp phone (`#profileWhatsapp`) and Email (`#profileEmail`) via `GET /api/v1/clients/{id}`, and allows RMs to update details with real-time feedback (`PUT /api/v1/clients/{id}`).
- **Chronological Communication Audit Feed (`#communicationFeed`)**: Calls `GET /api/v1/clients/{id}/communications` to render outbound interaction history. Each log card (`.comm-log-item`) displays:
  - Channel badge (`.comm-log-channel`, emerald for WhatsApp, blue for Email).
  - Locale-formatted timestamp.
  - Delivery status badge (`.comm-log-status`: `sent`, `delivered`, `read`, `failed`).
  - Full message text body (`.comm-log-content`).
  - Explanatory error banner in red if delivery failed.

### 15. Client Memory Dossier Accordion & Pre-Meeting Brief Card
Collapsible accordion interface (`#memoryPanel`) rendering a rich **AI Pre-Meeting Executive Brief Card** (Last Meeting recap, Pending commitments list, Products owned tags, Primary client concern, and Suggested Talking Points for the advisor). Includes a nested collapsible "Detailed History" sub-accordion showing the rolling narrative, meeting summaries, historical concerns, and relationship notes.

### 16. In-Dossier Client Q&A with Dedicated Voice Mic Auto-Submit
Interactive Q&A bar inside Client Memory (`#askClientInput`, `#askClientBtn`) allowing advisors to ask natural language questions about a specific client. Features a dedicated microphone button (`#askClientVoiceBtn`):
- Initializes `webkitSpeechRecognition` in `en-IN`.
- Updates button appearance to active red (`var(--danger)`) and sets placeholder to "Listening...".
- Upon speech completion, automatically inserts transcript into `#askClientInput` and programmatically clicks `#askClientBtn`, querying `POST /api/v1/clients/{id}/ask` and displaying synthesized answers with source meeting citations (`Sources: Meetings 12, 15`).

### 17. Interactive Commitment Ledger Table & Optimistic Status Toggling
Commitment table with Client Name, Task Description, Owner, Extraction Confidence percentage (`Confidence: 95%`), Due Date, Urgency badge (`high`, `medium`, `low`), Status badge (`pending`, `completed`), and Quick-action toggle link (`Complete` / `Reopen`). Supports status filtering (`#commitmentFilter`: All/Pending/Completed) and optimistic UI updates calling `PATCH /api/v1/commitments/{id}/status`.

### 18. Daily Priorities List & Dynamic False-Alarm Safe Risk Monitor
Dual-panel daily workbench:
- **Follow-up Tasks List (`#taskList`)**: Categorizes tasks into `Overdue` (red badge), `Due Today` (amber badge), and `Upcoming` (blue badge).
- **Risk Signals List (`#riskList`)**: False-alarm-safe header with dynamic badge (`#riskSignalsBadge`): green "0 Active Risks - All Clear" when 0 risks vs rose pulsing badge "${N} Action Required" when risks exist. Cards display severity badge (`high`, `medium`, `low`), review state badge ("Review needed" vs "Monitoring"), and AI confidence percentage score.

### 19. Team Performance Overview Dashboard Table
Performance dashboard table (`#teamPerformanceSection`) dynamically shown only to workspace Owners and Admins in "Team Workspace" scope. Displays employee email, total clients owned, total meetings logged, and an interactive colored commitment completion progress bar (Green $\ge 80\%$, Amber $\ge 50\%$, Red $< 50\%$) with completed vs pending counts.

### 20. Workspace Scope Toggle (Team Workspace vs My Workspace)
Scope dropdown (`#scopeSelect`) in the sidebar for Owners and Admins to toggle between "Team Workspace" (organization-wide aggregation) and "My Workspace" (individual RM assignment mode). Automatically refetches clients, commitments, and team performance metrics.

### 21. Persistent 380px AI Copilot Sidecar with Dynamic Token Budget Meter
Persistent 380px slide-out sidecar dock (`#copilotSidecar`) accessible from topbar (`#topbarCopilotBtn`) or shortcuts (`Cmd+Shift+L`, `Cmd+/`, `Cmd+J`):
- **Grounded Client Pill (`#copilotGroundedClient`)**: Displays active client context dossier, reflecting `#topClientSelect`.
- **Dynamic Token Budget Progress Meter (`#copilotTokenText`, `#copilotTokenFill`)**:
  - Initializes at baseline `1,420 / 8,192 tokens` (base system prompt + client memory context).
  - Character-to-token heuristic (`Math.ceil(text.length / 3.8)`) dynamically increments token count on every user query and AI answer.
  - Updates visual percentage width on `#copilotTokenFill`.
- **Auto-Focus**: Opening the sidecar automatically shifts focus to `#copilotInput` after 100ms.
- **Chat Stream & Provenance Badges**: Chat bubbles, "Thinking..." indicator, and search provenance tags ("✨ Generated via Database Search" vs "✨ Generated via Vector Search").

### 22. Hero Voice Assistant Interaction Hub & Rotating Conic Halo (`.mfd-hero`)
Dedicated high-visibility voice interaction centerpiece on the advisor's dashboard:
- **132px Rotating Conic Gradient Halo (`.mfd-halo`)**: 6-second continuous 360° spinning gradient aura (`@keyframes mfd-spin`).
- **96px Radial Mic Button (`.mfd-mic`)**: Dual box-shadow glow rings (`var(--mfd-teal-glow)`) with acoustic pulse animation (`@keyframes mfd-mic-pulse`) when recording.
- **Dynamic Time-of-Day Salutation Engine**: In `revealApp()`, inspects `new Date().getHours()` to greet the RM:
  - Morning ($< 12$): *"Good morning, {FirstName} 👋"*
  - Afternoon ($12 - 17$): *"Good afternoon, {FirstName} 👋"*
  - Evening ($\ge 17$): *"Good evening, {FirstName} 👋"*
- **Advisory Workflow Ethos**: Prominently displays: *"Just 3 steps today: Speak → Review → Forget. I'll remember the rest."*

### 23. Philixa Brain Voice Assistant 4-State Visual State Machine & 4000ms Silence
Voice assistant interaction engine (`philixa-voice.js`):
- **4 Visual States**: `idle` (🎙️ PHILIXA), `listening` (🔴 LISTENING...), `thinking` (🤔 THINKING...), `speaking` (💬 SPEAKING...).
- **4000ms Silence Detection Timer (`SILENCE_LIMIT_MS = 4000`)**: Incoming audio chunks reset the countdown; 4 seconds of silence triggers `stopVoiceListening()` transitioning UI to thinking.
- **10-Turn Rolling Conversation Memory Array**: Client-side array sliding window (`conversationHistory.slice(-10)`) sent to `/api/v1/voice/chat`.
- **Conversational Auto-Continuation**: `audio.onended` parses spoken AI responses for conversational triggers (`?`, `save`, `karein`, `bataiye`) and automatically restarts voice listening for hands-free dialogue.
- **Audio Memory Cleanup**: Calls `URL.revokeObjectURL(audioUrl)` on `ended` and `error` events to prevent browser memory leaks.
- **Voice-Triggered Client Confirmation HITL Flow**: Background 2000ms polling after voice note save; automatically pops up `#confirmPanel` with suggested client name pre-filled if backend returns `client_identification_required`.

### 24. Multi-Modal Client Reminder Scheduling UI Workflows (Voice vs Copilot)
Advisors can schedule client reminders via WhatsApp or Email across two distinct UI workflows:
- **Workflow A: Conversational Voice UI (Hero Mic / FAB)**:
  1. Advisor taps mic and speaks reminder command in English or Hinglish (e.g. *"WhatsApp Vikram that our quarterly portfolio review is set for Monday"*).
  2. Audio streams via AudioWorklet/WebSocket; on silence detection, dispatches to `POST /api/v1/voice/chat`.
  3. AI classifies `SEND_REMINDER`, drafts message copy, and caches in Redis (`pending_reminder:{user_id}`, 300s TTL).
  4. Calls `speakAIResponse()`, streaming TTS preview audio (*"I drafted this for Vikram. Should I send it?"*).
  5. Advisor confirms verbally (*"Haan bhej do"* / *"Yes send it"*), triggering `CONFIRM_ACTION` which dispatches the reminder and logs to `communication_logs`.
- **Workflow B: Copilot Text Chat UI (380px Sidecar Dock)**:
  1. Advisor opens sidecar (`Cmd+Shift+L`) and types reminder instruction into `#copilotInput`.
  2. Shows animated thinking bubble (`<span class="loading-dots">Thinking...</span>`) and posts to `POST /api/v1/dashboard/copilot/ask`.
  3. Action node drafts email and WhatsApp copy, caching in Redis (`pending_reminder_copilot:{user_id}`, 300s TTL), and renders a preview bubble asking for confirmation.
  4. Advisor types *"yes"* or *"haan bhej do"*. The Copilot Hinglish fast-path intercepts the reply, dispatches messages concurrently, and updates delivery status badges in real time.

### 25. Notification Preferences Modal & Quiet Hours Configuration
Preferences modal dialog (`#settingsModal`) accessible via avatar dropdown. Allows advisors to configure notification opt-in (`#prefOptIn`), WhatsApp phone number or email (`#prefContact`), and quiet hours time pickers (`#prefQuietStart`, `#prefQuietEnd`) to enforce disturbance-free periods (`PUT /api/v1/preferences`).

### 26. Client-Side Single-Flight Refresh Queue & Double-Submit CSRF Guard
Universal `fetchWithAuth()` client-side security wrapper (`app/web/app.js:221-326`):
- Automatic `X-CSRF-Token` header injection extracted from `csrf_token` cookie for mutating HTTP requests.
- Single-flight token refresh queue (`isRefreshing`, `refreshQueue`, `processRefreshQueue`) that catches 401s, pauses concurrent API calls, executes a single refresh call to `/api/v1/auth/refresh`, updates CSRF token, and replays all queued requests seamlessly.
- Single-use signed WebSocket ticket generation (`mintWsTicket()`, `POST /api/v1/ws-ticket`).

### 27. Toast Notification System
Toast notification banner (`#toast`, `.toast.show`, `.toast.error`) providing real-time feedback for background tasks, save events, error alerts, and status changes with automatic 2.8-second auto-dismiss.

### 28. Comprehensive Keyboard Shortcuts & WCAG 2.2 AAA Accessibility
Global keyboard shortcut system with focus disambiguation:
- `Cmd+Enter` / `Ctrl+Enter`: Exclusively triggers Meeting Notes AI Intake (guarded: suppressed when `#copilotInput` is focused).
- `Cmd+Shift+Enter` / `Ctrl+Shift+Enter` (or `Cmd+S`): Exclusively triggers Batch Diff Synchronization.
- `Cmd+Shift+L` / `Ctrl+Shift+L` (also `Cmd+/`, `Cmd+J`): Toggles AI Copilot Sidecar Dock.
- `Cmd+[` / `Ctrl+[`: Toggles Navigation Sidebar collapse between 240px and 64px.
- `Esc`: Closes Copilot Sidecar, Settings Modal, Member Modal, or exits diff inline editing.
- `Spacebar`: Toggles selection of focused Diff Card (`role="checkbox"`).
- `Enter`: Saves inline diff title edit; activates verdict card jump navigation.
- Focus Trapping: Shifts focus to first diff card 50ms after extraction completes.
- Unified WCAG 2.2 Level AAA Focus Ring system (`outline: 2px solid var(--accent) !important; outline-offset: 2px !important;`).

### 29. Synchronous LocalStorage FOAC Prevention Script
To eliminate Flash of Unauthenticated Content (FOAC) before CSS renders:
- An inline `<script>` runs synchronously in `<head>` before any body DOM paints:
  ```javascript
  if (localStorage.getItem("p6_logged_in") !== "true") {
    document.documentElement.classList.add("not-logged-in");
  }
  ```
- Coupled with CSS (`html.not-logged-in .mfd-layout { display: none !important; }`), this ensures unauthenticated visitors never see unrendered dashboard layouts prior to auth modal display.

---

## 🖥 Interactive Developer & Management Portals

Once the Philixa infrastructure is running, the following portals are accessible:

| Service / Interface | URL | Default Credentials / Port | Description |
|---|---|---|---|
| **Single-Page Application (SPA)** | `http://localhost:8000/` | Interactive Web UI | Full CRM dashboard, 60/40 Diff Review Workbench, Copilot Sidecar, Voice FAB, Ingestion Tabs, and HITL panels. |
| **Interactive Swagger API Docs** | `http://localhost:8000/docs` | Public / Open | OpenAPI interactive documentation for testing all 50 endpoints. |
| **ReDoc API Reference** | `http://localhost:8000/redoc` | Public / Open | Comprehensive, human-readable API specification and schemas. |
| **OpenAPI Schema JSON** | `http://localhost:8000/openapi.json` | Public / Open | Raw JSON schema for SDK generation and contract testing. |
| **MinIO Object Storage Console** | `http://localhost:9001` | `philixa_minio` / `philixa_secret` | Web interface to inspect audio buckets and tenant namespaces. |
| **System Health Check** | `http://localhost:8000/health` | Public | JSON status: `{"status": "ok", "app_version": "1.0.0", "database": "ok", "enable_audio_upload": false}`. |

---

## 📖 Complete 50-Endpoint API Catalog

The backend exposes **50 distinct API operations** across 11 route modules (accessible under `/api/v1` and dual-mounted for `/auth`, `/workspaces`, `/audio`, `/live`, and `/ws-ticket`):

### 2.1 Authentication & Session Management (`app/api/v1/routes_auth.py`)

| # | Method | Endpoint | Security / Auth | Description |
|---|:---:|---|---|---|
| 1 | `POST` | `/auth/register` | Public | Onboard new user, create primary organization, and send verification email. |
| 2 | `POST` | `/auth/verify-email` | Query / JSON Body | Verify user email with 24-hour SHA-256 token (supports query `?token=` or JSON body; returns HTTP 410 if expired/consumed). |
| 3 | `POST` | `/auth/login` | Public (5/min IP) | Verify credentials (bcrypt), create user session, issue HttpOnly JWT cookies. Throttled via SlowAPI. |
| 4 | `POST` | `/auth/google` | Public | Verify Google OAuth2 ID token, auto-provision user and workspace, issue session cookies. |
| 5 | `POST` | `/auth/demo-login` | Public | Instant one-click sandbox workspace provisioning with pre-seeded CRM data. |
| 6 | `GET` | `/auth/me` | JWT Cookie / Bearer | Retrieve active user profile, memberships, active workspace context, and role. |
| 7 | `POST` | `/auth/refresh` | Cookie `refresh_token` | Single-flight token rotation; issues fresh access token and rotates refresh token hash. |
| 8 | `POST` | `/auth/logout` | JWT Cookie / Bearer | Revoke active user session in database and clear session cookies. |
| 9 | `POST` | `/auth/forgot-password` | Public | Send 1-hour password reset email link with secure token. |
| 10 | `POST` | `/auth/reset-password` | Token Query | Reset password using valid token. |
| 11 | `DELETE` | `/auth/me` | JWT Cookie / Bearer | Account deletion cascade (purges sessions, memberships, and owned records). |
| 12 | `POST` | `/ws-ticket` | JWT Cookie / Bearer | Mint a 60-second single-use signed ticket for WebSocket audio streaming. |

### 2.2 Multi-Tenant Workspace & Team Management (`app/api/v1/routes_workspace.py`)

| # | Method | Endpoint | Security / RBAC | Description |
|---|:---:|---|---|---|
| 13 | `GET` | `/workspaces` | Authenticated | List all organizations/workspaces the authenticated user belongs to. |
| 14 | `POST` | `/workspaces/switch` | Authenticated (Member) | Switch active workspace context and issue updated session cookies. |
| 15 | `POST` | `/workspaces/invite` | Owner / Admin | Send 7-day email invitation to onboard a new team member. |
| 16 | `POST` | `/workspaces/invite/accept` | Public / Token | Accept workspace invite token and set user password. |
| 17 | `GET` | `/workspaces/members` | Authenticated | List all members and roles in the active workspace. |
| 18 | `PATCH` | `/workspaces/members/{id}/role` | Owner Only | Update member role (`admin`, `member`). Last owner cannot be demoted. |
| 19 | `DELETE` | `/workspaces/members/{id}` | Owner / Admin | Remove user from active workspace. Last owner cannot be removed. |

### 2.3 Client Relationship & Memory Management (`app/api/v1/routes_clients.py`)

| # | Method | Endpoint | Security / RBAC | Description |
|---|:---:|---|---|---|
| 20 | `POST` | `/api/v1/clients` | Authenticated | Create a new tenant-scoped client profile. |
| 21 | `GET` | `/api/v1/clients` | Authenticated | List clients with pending commitment counts (supports `?scope=team` vs `?scope=me`). |
| 22 | `GET` | `/api/v1/clients/{id}` | Tenant-Scoped | Retrieve client profile, contact details, products owned/interested, and rolling narrative. |
| 23 | `PUT` | `/api/v1/clients/{id}` | Tenant-Scoped | Update client metadata, decoupled products owned/interested JSON, and relationship notes. |
| 24 | `DELETE` | `/api/v1/clients/{id}` | Tenant-Scoped | Cascade delete client and all dependent meetings, commitments, and vectors. |
| 25 | `GET` | `/api/v1/clients/{id}/memory` | Tenant-Scoped | Retrieve structured rolling brief, open commitments, and top historical concerns. |
| 26 | `POST` | `/api/v1/clients/{id}/ask` | Tenant-Scoped | Natural language Q&A over a specific client's history with meeting citations. |
| 27 | `GET` | `/api/v1/clients/{id}/meetings` | Tenant-Scoped | List chronological meeting records for a specific client. |
| 28 | `GET` | `/api/v1/clients/{client_id}/communications` | Tenant-Scoped | Retrieve complete outbound communication history (WhatsApp, Email, SMS) with delivery statuses and provider IDs. |

### 2.4 Meeting Intelligence & Human-in-the-Loop (`app/api/v1/routes_meeting_notes.py`)

| # | Method | Endpoint | Security / RBAC | Description |
|---|:---:|---|---|---|
| 29 | `POST` | `/api/v1/meeting-notes/process` | Authenticated (10/min IP) | Ingest raw notes (`PASTED_NOTE`), run LLM extraction, match client, extract tasks (demo max 2). Throttled via SlowAPI. |
| 30 | `GET` | `/api/v1/meeting-notes/{id}` | Tenant-Scoped | Retrieve meeting summary, raw notes, discussion points, concerns, and status. |
| 31 | `POST` | `/api/v1/meeting-notes/{id}/confirm-client` | HITL Scoped | Manually assign an ambiguous meeting to an existing client or create client with pre-filled email and WhatsApp phone. |
| 32 | `PATCH` | `/api/v1/meeting-notes/{id}/transcript` | HITL Scoped | Correct noisy audio transcript and trigger re-extraction and vector generation. |

### 2.5 Commitment Tracking (`app/api/v1/routes_commitments.py`)

| # | Method | Endpoint | Security / RBAC | Description |
|---|:---:|---|---|---|
| 33 | `GET` | `/api/v1/commitments` | Authenticated | List commitments with filtering (`status`, `client_id`, `due_before`, `scope`). |
| 34 | `PATCH` | `/api/v1/commitments/{id}/status` | Tenant-Scoped | Toggle commitment status between `pending`, `completed`, and `cancelled`. |

### 2.6 Audio Storage & Live Streaming (`app/api/v1/routes_audio.py`, `routes_live.py`)

| # | Method | Endpoint | Security / RBAC | Description |
|---|:---:|---|---|---|
| 35 | `POST` | `/audio/upload` | Authenticated | Upload multipart audio or MP4 video (10MB limit) to MinIO, pre-bind via `known_client_id`, enqueue ARQ transcription. |
| 36 | `GET` | `/audio/{id}/url` | Tenant-Scoped | Generate temporary presigned MinIO S3 download URL (1-hour expiry). |
| 37 | `WS` | `/live/transcribe` | Single-Use Ticket | Real-time WebSocket PCM audio streaming with Redis ticket replay protection, 120s idle watchdog, and 1.0s duration guard. |

### 2.7 Conversational Voice Assistant (`app/api/v1/routes_voice.py`)

| # | Method | Endpoint | Security / RBAC | Description |
|---|:---:|---|---|---|
| 38 | `POST` | `/api/v1/voice/speak` | Authenticated | Text-to-Speech audio streaming via Sarvam AI (`bulbul:v3`, speaker `shreya`, `hi-IN`) with Deepgram Aura fallback. |
| 39 | `POST` | `/api/v1/voice/chat` | Authenticated | 6-intent conversational voice agent reasoning (`QUERY`, `SAVE_MEETING`, `SEND_REMINDER`, `CHAT`, `CONFIRM`, `REJECT`). |

### 2.8 Dashboard Analytics & Agentic Copilot (`app/api/v1/routes_dashboard.py`)

| # | Method | Endpoint | Security / RBAC | Description |
|---|:---:|---|---|---|
| 40 | `GET` | `/api/v1/dashboard/priorities` | Authenticated | Daily actionable priorities: overdue commitments and client risk signals. |
| 41 | `GET` | `/api/v1/dashboard/metrics` | Authenticated | High-level summary metrics (total clients, meetings processed, open tasks). |
| 42 | `GET` | `/api/v1/dashboard/team-performance` | Owner / Admin | Per-advisor CRM workload, meeting velocity, and commitment resolution stats. |
| 43 | `POST` | `/api/v1/dashboard/copilot/ask` | Authenticated (20/min IP) | Hybrid LangGraph Copilot (NL-to-SQL + pgvector + 2-phase Reminders). Throttled via SlowAPI; demo max 5 queries/24h in Redis. |

### 2.9 Notification Preferences & WhatsApp Webhooks (`app/api/v1/routes_preferences.py`, `routes_webhooks.py`)

| # | Method | Endpoint | Security / RBAC | Description |
|---|:---:|---|---|---|
| 44 | `GET` | `/api/v1/preferences` | Authenticated | Retrieve user notification settings (WhatsApp number, quiet hours, timezone). |
| 45 | `PUT` | `/api/v1/preferences` | Authenticated | Update user notification preferences. |
| 46 | `GET` | `/api/v1/webhooks/whatsapp` | Hub Verify | Meta WhatsApp Cloud API webhook hub challenge verification (`hub.challenge`). |
| 47 | `POST` | `/api/v1/webhooks/whatsapp` | Meta Webhook | Inbound WhatsApp delivery status reconciliation updating `notification_deliveries` and `communication_logs`. |

### 2.10 Background Jobs & System Health (`app/api/v1/routes_jobs.py`, `routes_health.py`, `app/main.py`)

| # | Method | Endpoint | Security / RBAC | Description |
|---|:---:|---|---|---|
| 48 | `GET` | `/api/v1/jobs/{job_id}` | Authenticated | Poll ARQ background transcription/embedding job progress and completion status. |
| 49 | `GET` | `/health` | Public | Real-time health check returning database status, app version, and `enable_audio_upload` runtime flag. |
| 50 | `GET` | `/` | Public | Serves static Single-Page Application (SPA) HTML shell (`app/web/index.html`). |

---

## 🗄 Database Entity Relationship & 18 Relational Models

The relational schema is managed by **21 sequential Alembic migrations** up to `h5c3d4e5f6g7_multi_tenant_auth_and_workspaces.py`, `9a1b2c3d4e5f_decouple_products_owned_and_products_interested.py`, `2fa302439a88_add_communication_log.py`, and `924be62947b0_add_provider_message_id_to_.py`. All 18 SQLAlchemy models map directly to physical PostgreSQL tables:

```
+-------------------------------------------------------------------------------------------------------------------------------+
|                                                18 PHYSICAL DATABASE TABLES & ROLES                                            |
+-------------------------------------------------------------------------------------------------------------------------------+
| #  | Table Name                 | Primary Key | Scoping Columns        | Foreign Key References & Architectural Purpose       |
+----+----------------------------+-------------+------------------------+------------------------------------------------------+
| 1  | organizations              | id (UUID)   | Root Tenant            | Multi-tenant workspaces with plans (free/pro) & types|
| 2  | organization_memberships   | id (UUID)   | org_id, user_id        | Maps users to workspaces with roles (owner/admin/mem)|
| 3  | users                      | id (UUID)   | Global Table           | User accounts, bcrypt password hash, verified flag   |
| 4  | user_sessions              | id (UUID)   | user_id, org_id        | Active sessions, refresh token SHA-256 hash, expiry  |
| 5  | email_verification_tokens  | id (UUID)   | user_id                | 24-hour verification token hashes                    |
| 6  | password_reset_tokens      | id (UUID)   | user_id                | 1-hour password reset token hashes                   |
| 7  | workspace_invites          | id (UUID)   | org_id, invited_by     | 7-day token-based team member invitation links       |
| 8  | clients                    | id (UUID)   | organization_id, user_id| Client CRM profiles, decoupled products_owned_json &  |
|    |                            |             |                        | products_interested_json, rolling narrative          |
| 9  | meetings                   | id (Int)    | organization_id, user_id| Meeting transcripts, audio S3 URLs, extraction state |
| 10 | meeting_evidence           | id (Int)    | meeting_id, org_id     | 1024-dim pgvector embeddings (BAAI/bge-m3) with <=>  |
| 11 | commitments                | id (Int)    | organization_id, user_id| Actionable tasks with due dates and status lifecycle |
| 12 | commitment_meeting_links   | id (Int)    | commitment_id, meet_id | Many-to-many join linking commitments to meetings    |
| 13 | follow_up_tasks            | id (Int)    | organization_id, user_id| Priority follow-up items surfaced on RM dashboard     |
| 14 | risk_signals               | id (Int)    | organization_id, user_id| Deal and client churn risk flags detected by AI      |
| 15 | notification_preferences   | id (UUID)   | user_id                | Quiet hours, timezone, and preferred channel settings|
| 16 | notification_deliveries    | id (Int)    | user_id, org_id        | Idempotent delivery logs with Meta message IDs       |
| 17 | ai_extraction_logs         | id (Int)    | meeting_id             | Token counts, latencies, model fallbacks audit log   |
| 18 | communication_logs         | id (Int)    | organization_id, user_id| Outbound client reminders across WhatsApp/Email/SMS  |
|    |                            |             |                        | with provider message IDs and real-time delivery logs|
+-------------------------------------------------------------------------------------------------------------------------------+
```

---

## ⚙️ Master Configuration Matrix

Philixa 6.0 configures **69 parameters** via Pydantic `BaseSettings` (`app/core/config.py`), with pre-flight security evaluation (`validate_production_settings`) on boot:

| Category | Environment Variable | Default / Example Value | Description |
|---|---|---|---|
| **App Core** | `PHILIXA_ENV` / `APP_ENV` | `development` | Runtime environment (`development` vs `production`). Enables strict CSRF & security validation. |
| | `PHILIXA_APP_NAME` | `PHILIXA 6.0 V1-MVP` | Human-readable application title. |
| | `PHILIXA_APP_VERSION` | `1.0.0` | Semantic version string. |
| | `PHILIXA_SKIP_STARTUP_CHECKS` | `0` | Set to `1` to bypass pre-flight DB connection checks in test environments. |
| | `PHILIXA_ENABLE_AUDIO_UPLOAD` | `0` (`false`) | Feature flag enabling or disabling audio upload capabilities and Whisper model preloading. |
| **Database & Cache** | `PHILIXA_DATABASE_URL` | `postgresql+psycopg://postgres:dev_only_password@localhost:5432/philixa` | Async PostgreSQL connection string using `psycopg` driver. |
| | `PHILIXA_REDIS_URL` | `redis://localhost:6379/0` | Redis instance for ARQ background queues, WebSocket tickets, and 300s reminder staging. |
| | `db_pool_size` | `15` | SQLAlchemy async connection pool base size. |
| | `db_max_overflow` | `5` | Maximum overflow connections allowed beyond base pool size. |
| | `db_pool_timeout` | `30` | Seconds to wait before timing out on connection pool exhaustion. |
| | `db_pool_pre_ping` | `True` | Tests connection liveliness before checkout to avoid stale socket disconnects. |
| **Auth & Security** | `PHILIXA_JWT_SECRET` | *(32+ char hex string)* | Cryptographic secret for signing HS256 JWT access and refresh tokens. |
| | `PHILIXA_JWT_ALGORITHM` | `HS256` | JWT signing algorithm. |
| | `PHILIXA_CSRF_SECRET` | *(32+ char hex string)* | Cryptographic secret for generating double-submit CSRF tokens. |
| | `PHILIXA_JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifespan. |
| | `PHILIXA_JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Refresh token lifespan. |
| | `PHILIXA_COOKIE_SECURE` | `False` (`True` in prod) | Flag requiring HTTPS for session cookies. |
| | `PHILIXA_COOKIE_DOMAIN` | `None` | Optional domain scoping for auth cookies. |
| | `PHILIXA_COOKIE_SAMESITE` | `lax` | SameSite cookie attribute (`lax` / `strict` / `none`). |
| | `PHILIXA_ALLOWED_ORIGINS` | `http://localhost:8000` | Comma-separated CORS whitelist origins. Disallows `*` in production. |
| | `google_client_id` | `401674766048-...apps.googleusercontent.com` | Google Identity Services OAuth 2.0 Client ID for One-Tap sign-in. |
| | `PHILIXA_DEMO_API_KEY` | `""` | Optional API key for programmatic demo provisioning. |
| | `PHILIXA_API_KEY` | *(Secret Token)* | Master developer API key allowing `X-API-Key` authentication bypass. |
| **Thresholds & Limits** | `PHILIXA_CLIENT_NAME_MAX_CHARS` | `120` | Maximum character length permitted for client names. |
| | `PHILIXA_COMMITMENT_DESCRIPTION_MAX_CHARS` | `500` | Maximum character length permitted for commitment descriptions. |
| | `PHILIXA_RAW_NOTES_MAX_CHARS` | `10000` | Upper character limit permitted for raw meeting notes intake. |
| | `PHILIXA_CLIENT_AUTO_MATCH_THRESHOLD` | `0.85` | String similarity threshold to auto-match an existing client name during extraction. |
| | `PHILIXA_CLIENT_AUTO_CREATE_THRESHOLD` | `0.80` | Configured auto-create threshold (Note: silent auto-creation is disabled in favor of strict HITL confirmation). |
| | `PHILIXA_DUE_DATE_THRESHOLD` | `0.75` | Minimum confidence score required to accept AI extracted due dates. |
| | `PHILIXA_RETAIN_AUDIO` | `0` | Storage lifecycle flag (`0` purges MinIO audio post-transcription; `1` retains audio). |
| **AI LLM Inference** | `PHILIXA_GROQ_API_KEY` | `gsk_...` | High-speed LLM inference key for meeting extraction and Copilot. |
| | `PHILIXA_AI_MODEL` | `llama-3.3-70b-versatile` | Primary Groq LLM model identifier. |
| | `PHILIXA_GEMINI_API_KEY` | `AIzaSy...` | Google Gemini API key for Tier 2 extraction review fallback. |
| | `PHILIXA_AI_REVIEW_MODEL` | `gemini-2.5-flash` | Review LLM model identifier. |
| | `PHILIXA_AI_BASE_URL` | `None` | Custom base URL for OpenAI-compatible LLM gateways. |
| | `PHILIXA_AI_API_KEY` | `""` | Optional generic AI provider API key. |
| | `PHILIXA_AI_TIMEOUT_SECONDS` | `20` | Socket and HTTP timeout in seconds for AI LLM completions. |
| | `PHILIXA_PROMPT_VERSION` | `v1-mvp-2026-06-19` | Prompt version identifier tagged in `ai_extraction_logs`. |
| | `PHILIXA_AI_ECONOMY_PROVIDER` | `groq` | Provider identifier for Tier-1 economy model. |
| | `PHILIXA_AI_ECONOMY_MODEL` | `groq/openai/gpt-oss-20b` | Model identifier for Tier-1 economy model. |
| | `PHILIXA_AI_REVIEW_PROVIDER` | `gemini` | Provider identifier for Tier-2 review fallback. |
| **Voice & Embeddings** | `PHILIXA_EMBEDDING_MODEL` | `BAAI/bge-m3` | SentenceTransformers model for 1024-dim `pgvector` embeddings. |
| | `PHILIXA_DEEPGRAM_API_KEY` | *(Secret Token)* | Real-time Deepgram Nova-3 speech-to-text API key (`language="hi"`). |
| | `PHILIXA_SARVAM_API_KEY` | *(Secret Token)* | Sarvam AI Hinglish voice synthesis API key (`bulbul:v3`, speaker `shreya`). |
| | `PHILIXA_TRANSCRIPTION_MODE` | `local` | STT engine mode (`local` via faster-whisper `large-v3-turbo` CPU int8 vs `cloud`). |
| | `PHILIXA_HF_TOKEN` | `hf_...` | Hugging Face token required for Pyannote speaker diarization models. |
| **Object Storage** | `PHILIXA_MINIO_URL` | `localhost:9000` (`minio:9000` in Docker) | MinIO S3 API endpoint. |
| | `PHILIXA_MINIO_ACCESS_KEY` | `philixa_minio` | MinIO admin access username. |
| | `PHILIXA_MINIO_SECRET_KEY` | `philixa_secret` | MinIO admin secret password. |
| | `PHILIXA_MINIO_BUCKET_NAME` | `philixa-audio` | Default S3 bucket for meeting audio storage (10MB max upload). |
| **Dual Notifications** | `PHILIXA_NOTIFICATION_MODE` | `email` (or `whatsapp`, `simulated`) | Default notification dispatch channel. |
| | `PHILIXA_SMTP_HOSTNAME` | `smtp.gmail.com` | SMTP host for transactional authentication emails. |
| | `PHILIXA_SMTP_PORT` | `587` | SMTP port (STARTTLS). |
| | `PHILIXA_SMTP_USERNAME` | `your_email@gmail.com` | SMTP username. |
| | `PHILIXA_SMTP_PASSWORD` | `your_app_password` | SMTP app password. |
| | `PHILIXA_SMTP_USE_TLS` | `True` (`1`) | Enables STARTTLS encryption for SMTP email delivery. |
| | `PHILIXA_SMTP_FROM_ADDRESS` | `no-reply@philixa.com` | From address header for transactional authentication emails. |
| | `WHATSAPP_PHONE_NUMBER_ID` | `...` | Meta WhatsApp Cloud API Phone Number ID. |
| | `WHATSAPP_BUSINESS_ACCOUNT_ID`| `...` | Meta WhatsApp Cloud API Business Account ID. |
| | `WHATSAPP_ACCESS_TOKEN` | `EAAG...` | Meta Graph API System User permanent access token. |
| | `WHATSAPP_VERIFY_TOKEN` | `...` | Webhook verification token string for Meta challenge handshake. |

---

## 🛠 Standalone CLI Scripts & Developer Diagnostics

Philixa 6.0 provides operational command-line utilities and diagnostic tools for maintenance and automated validation:

### 1. Standalone Demo Sandbox Purge Tool
Run manually or configure via host OS cron to sweep expired sandbox workspaces:
```bash
python scripts/cleanup_demo_accounts.py
```
- Queries all users matching `email.like("demo_guest_%")`.
- Executes atomic database cascade deletions purging expired users, organization memberships, active sessions, clients, meetings, commitments, tasks, risk signals, and vector embeddings in `meeting_evidence`.

### 2. Developer Diagnostic Test Scripts
- **Voice Intent Classifier Test**:
  ```bash
  python test_intent.py
  ```
  Tests Devanagari Hindi and Hinglish speech intent parsing (e.g., verifying *'राजेश शर्मा से मिला'* correctly routes to `SAVE_MEETING` or *'Vikram ko reminder bhejo'* routes to `SEND_REMINDER`).
- **Copilot Query & LangGraph Test**:
  ```bash
  python test_copilot.py
  ```
  Verifies SQL generation, client grounding, and LangGraph planner routing without booting the full web browser.
- **Database Connectivity & Model Test**:
  ```bash
  python test_db.py
  ```
  Verifies PostgreSQL connection pool parameters, pgvector extension availability, and queries client records.

---

## 🚀 Quickstart & Deployment Guide

### Option A: 5-Container Docker Compose (Recommended)

The easiest way to run the entire Philixa 6.0 stack—including database, caching, object storage, API gateway, and background worker—is via Docker Compose.

```bash
# 1. Clone the repository
git clone https://github.com/shouryasingh-codes/philixa-6.0.git
cd philixa-6.0

# 2. Configure environment variables
cp .env.example .env
# Edit .env and supply your PHILIXA_GROQ_API_KEY and other credentials

# 3. Boot all 5 services (db, redis, minio, app, worker)
docker compose up -d --build

# 4. View container logs
docker compose logs -f
```

The 5 booted services:
1. `db`: PostgreSQL 16 with `pgvector` extension on port `5432`.
2. `redis`: Redis 7 Alpine cache and task broker on port `6379`.
3. `minio`: MinIO S3 Object Storage on ports `9000` (API) and `9001` (Console).
4. `app`: FastAPI web application on port `8000` (runs migrations and production security validation on boot).
5. `worker`: ARQ background worker executing transcription, embeddings, rules engine scoring, and 4 cron sweeps.

---

### Option B: Bare-Metal Virtualenv Setup

For local backend development, run the services on bare metal:

#### Prerequisites
- **Python 3.12+**
- **FFmpeg** installed and in system `PATH` (required for audio slicing, DSP filter chains, and Whisper)
- **PostgreSQL 15/16+** with `pgvector` extension
- **Redis 7+** running locally on port `6379`
- **MinIO** running on port `9000`

```bash
# 1. Create and activate Python 3.12 virtual environment
python -m venv .venv

# On Linux / macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1

# 2. Install dependencies (including authentication crypto libraries)
pip install -r requirements.txt
pip install python-jose[cryptography] passlib[bcrypt] itsdangerous bcrypt

# 3. Configure environment
cp .env.example .env
# Ensure PHILIXA_DATABASE_URL and PHILIXA_REDIS_URL match your local setup

# 4. Apply database migrations
alembic upgrade head

# 5. Start the FastAPI Web Server (Terminal 1)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 6. Start the ARQ Background Worker (Terminal 2)
arq app.worker.WorkerSettings
```

---

### One-Click Demo Sandbox Evaluation

To immediately explore the CRM platform without manually registering and verifying emails:

1. Open `http://localhost:8000` in your web browser.
2. Click **"Try Demo Workspace"** on the login overlay.
3. The platform will instantly execute `POST /auth/demo-login`, provisioning a sandboxed organization populated with sample Indian wealth management clients, overdue commitments, and meeting notes!
4. *Sandbox Boundaries*: Demo sessions expire in 1 day and are quota-restricted to 2 meeting note extractions. Temporary accounts are automatically purged every hour by the background cleanup cron.

---

## 💻 Verified cURL Workflows

### 1. One-Click Sandbox Demo Login & Session Capture

```bash
# Provision a demo sandbox workspace and save session cookies
curl -X POST "http://localhost:8000/auth/demo-login" \
     -H "Content-Type: application/json" \
     -c cookies.txt
```

### 2. Standard User Registration & Google SSO Login

```bash
# 1. Register a standard company workspace
curl -X POST "http://localhost:8000/auth/register" \
     -H "Content-Type: application/json" \
     -d '{
       "email": "advisor@apexwealth.com",
       "password": "SecurePassword123!",
       "workspace_name": "Apex Wealth Advisory",
       "workspace_type": "company"
     }'

# 2. Login with Google OAuth2 ID Token
curl -X POST "http://localhost:8000/auth/google" \
     -H "Content-Type: application/json" \
     -c cookies.txt \
     -d '{
       "id_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6Ij..."
     }'
```

### 3. Querying the Agentic Copilot (Verified Fixed Schema & Actions)

> ⚠️ **Schema Requirement**: The Copilot endpoint expects `"query"` (using `"question"` results in an HTTP 422 error). In production, provide the `X-CSRF-Token` from your session cookie.

```bash
# Query the Copilot using captured cookies and CSRF token
curl -X POST "http://localhost:8000/api/v1/dashboard/copilot/ask" \
     -b cookies.txt \
     -H "Content-Type: application/json" \
     -H "X-CSRF-Token: <csrf_token_from_cookie>" \
     -d '{
       "query": "Send a reminder to Vikram about the debt mutual fund comparison by Friday",
       "chat_history": []
     }'
```

### 4. Minting Single-Use WebSocket Ticket for Live Streaming

```bash
curl -X POST "http://localhost:8000/ws-ticket" \
     -b cookies.txt \
     -H "Content-Type: application/json" \
     -H "X-CSRF-Token: <csrf_token_from_cookie>"
```

*Response*:
```json
{
  "ticket": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in": 60
}
```
*Connect to Live Audio WebSocket*: `ws://localhost:8000/live/transcribe?ticket=<ticket>`

### 5. Ingesting Meeting Notes & Resolving Clients (HITL)

```bash
# Ingest raw meeting text
curl -X POST "http://localhost:8000/api/v1/meeting-notes/process" \
     -b cookies.txt \
     -H "Content-Type: application/json" \
     -H "X-CSRF-Token: <csrf_token_from_cookie>" \
     -d '{
       "raw_notes": "Met with Vikram Malhotra at Starbucks. Discussed diversifying 2 Cr portfolio into debt funds. Action: Send debt mutual fund comparison by Friday.",
       "meeting_date": "2026-08-26T10:00:00Z"
     }'
```

---

## 🧪 Testing & Quality Assurance

Philixa 6.0 maintains a structured, robust automated test suite catalog partitioned into Unit, Integration, and End-to-End (E2E) suites:

```
tests/
├── unit/                                   # Isolated logic, crypto, rules, and model tests
│   ├── test_security_crypto.py             # Bcrypt, JWT tokens, CSRF validation
│   ├── test_worker_cron.py                 # ARQ cron schedules & demo cleanup execution
│   ├── test_products_decoupling.py         # products_owned vs products_interested schemas
│   ├── test_m1_data_models_and_migration.py# Schema verification & migration validation
│   ├── test_m5_frontend_rbac_stress.py     # UI RBAC permission guards & role transitions
│   └── test_verification_suite.py          # Regression & core assertions
├── integration/                            # Multi-component & API integration tests
│   ├── test_auth_flow.py                   # Register, login, Google SSO, token refresh
│   ├── test_workspace_management.py        # Workspace switching, member invitations, RBAC
│   ├── test_tenant_isolation.py            # Multi-tenant scoping & repository isolation
│   ├── test_websocket_audio_security.py    # WS ticket replay defense & duration checks
│   └── test_m3_workspace_rbac_csrf_stress.py# CSRF token enforcement & RBAC boundaries
├── e2e/                                    # Real-world user journey simulations
│   └── test_real_world_saas_scenarios.py   # Multi-turn CRM workflows, note intake to brief
└── conftest.py                             # Pytest fixtures, test DB session, async test client
```

### Running the Test Suites

```bash
# Run full test suite
pytest

# Run tests with verbose output and short tracebacks
pytest -v --tb=short

# Run Unit Test Suite
pytest tests/unit/

# Run Integration Test Suite
pytest tests/integration/

# Run End-to-End Test Suite
pytest tests/e2e/

# Run specific domain test files
pytest tests/integration/test_auth_flow.py
pytest tests/integration/test_tenant_isolation.py
pytest tests/unit/test_worker_cron.py
pytest tests/unit/test_products_decoupling.py
```

---

## 🗺️ Roadmap & Engineering Milestones

- [x] **Multi-Tenant Workspace & Role-Based Access Control (RBAC)** (`owner`, `admin`, `member`)
- [x] **Hardened Web Security Core** (HttpOnly JWT cookies, single-flight refresh rotation, double-submit CSRF, 10MB payload limit)
- [x] **Google OAuth2 One-Tap SSO Authentication** (`POST /auth/google` + Google Identity Services SDK)
- [x] **Single-Use WebSocket Tickets with Redis Replay Defense**
- [x] **Multi-Modal Ingestion Pipelines** (Pasted Notes, MinIO S3 Multipart Drag-and-Drop, Live PCM Streaming, Fast Dictation)
- [x] **Audio DSP & Hinglish Normalization** (FFmpeg filter chain, client-name prompt injection, ASR Hinglish translation layer)
- [x] **60/40 Structured Diff Review Workbench & HITL Triage Modals** (Diff cards, inline edit, batch sync, client confirmation)
- [x] **LangGraph Agentic Copilot with PostgreSQL pgvector RAG** (`BAAI/bge-m3` 1024-dim embeddings)
- [x] **Copilot Action Node & AI Reminder Engine** (`ReminderService` 2-phase 300s Redis TTL drafting & confirmation via WhatsApp/Email)
- [x] **Conversational Voice Assistant** (4-State Visual Machine with 132px rotating halo, 6-Way Intent Classifier, Sarvam AI `bulbul:v3` Hindi TTS with Deepgram fallback)
- [x] **Distributed ARQ Background Worker & 4 Scheduled Cron Sweeps** (Morning briefs, overdue alerts, 15m retry, hourly demo purge)
- [x] **Automated Business Rules Engine** (Task status calculation & deterministic risk signal scoring)
- [x] **Decoupled Client Product Tracking** (`products_owned_json` vs `products_interested_json`)
- [x] **One-Click Sandbox Demo Mode with Quota Safeguards**
- [x] **Comprehensive Keyboard Shortcuts & WCAG 2.2 AAA Design System**
- [ ] **React / Next.js Enterprise Frontend Migration**
- [ ] **Stripe Subscription Billing & Metered Usage Webhooks**
- [ ] **Multi-Region Kubernetes (EKS) Helm Chart Deployment**

---

## 🤝 Contributing & License

Contributions are what make the open source community such an empowering environment to build, iterate, and innovate. Any contributions you make are **greatly appreciated**.

1. Fork the Project (`git clone https://github.com/shouryasingh-codes/philixa-6.0.git`)
2. Create your Feature Branch (`git checkout -b feature/EnterpriseFeature`)
3. Commit your Changes (`git commit -m 'feat: Add enterprise capability'`)
4. Push to the Branch (`git push origin feature/EnterpriseFeature`)
5. Open a Pull Request

### License
Distributed under the **MIT License**. See `LICENSE` for details.

### Contact & Links
- **Repository**: [https://github.com/shouryasingh-codes/philixa-6.0](https://github.com/shouryasingh-codes/philixa-6.0)
- **Interactive Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Author**: Shourya Singh & Philixa Core Engineering Team
