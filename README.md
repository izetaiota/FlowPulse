# FlowPulse 心流

English | [中文](./README.zh.md)

> **Hand the busywork to the system — get back to creating.**

## 1. Project Introduction

**FlowPulse** (Chinese: 心流) is a content-operations workbench for individual bloggers and independent creators, deployable via Docker or run locally. The core idea: not to manage your accounts for you, but to cut away operational chores and protect your creative flow. Credentials, subscription data and media files all stay on your own machine.

- Website: <https://izetaiota.github.io/FlowPulse/>
- Product & technical docs: the [docs/](docs/) directory (module plans, architecture notes, migration guides — mostly in Chinese)
- Environment variables: [.env.example](.env.example)

**Currently available:**

| Capability | Directory | Status |
| --- | --- | --- |
| Official Account RSS (WeRead channel) | `src/flowpulse/modules/weread/` | ✅ Working |
| Douyin transcription (parsing + speech-to-text) | `src/flowpulse/modules/douyin/` | ✅ Working |
| Xiaohongshu workbench (crawling / download / export) | `src/flowpulse/modules/xhs/` | ✅ Working |
| Workbench frontend (Vue 3 + Element Plus) | `frontend/` | 🚧 In progress |
| Multi-platform account center / monitoring / publishing / DM | Planned | 📋 See the [migration plan](docs/CREATORHUB_FEATURE_MIGRATION_PLAN.md) (Chinese) |

**Quick start:**

```bash
# One-command Docker deployment (with PostgreSQL)
docker compose up -d --build        # open http://127.0.0.1:8000

# Or run from source (Python 3.11+)
pip install -e . && cp .env.example .env
uvicorn flowpulse.main:app --host 127.0.0.1 --port 8000

# Frontend dev mode
cd frontend && pnpm install && pnpm dev
```

Architecture highlights: a FastAPI modular monolith (plug-in platform modules under `modules/`) + unified wiring in `runtime.py` + dual file / PostgreSQL storage (controlled by `DATABASE_URL`, schema managed by Alembic) + database-driven menus + single-account login (HMAC token). Detailed deployment, configuration and API docs live in [docs/](docs/).

## 2. Feature Highlights

### 📰 Official Account RSS (WeRead channel)

- Subscribe to Official Accounts in the app → scheduled incremental sync → in-app reading / RSS output (`/api/weread/rss/all.xml`, full-text mode supported)
- **QR login + fully automated cookie renewal and self-healing**: headless browser refreshes the cookie daily; when it is rotated by another device, a refresh + retry fires automatically; on total expiry a webhook alert goes out and one scan restores everything
- Per-subscription sync intervals, customizable content cleaning (RSS summary or full text), new-article notifications across channels
- The WeRead channel approach follows [rachelos/we-mp-rss](https://github.com/rachelos/we-mp-rss) — verified stable in practice

### 🎬 Douyin transcription pipeline

- Paste a share text and go: resolve the short link → prefer embedded subtitles → otherwise download the video, extract audio with FFmpeg → transcribe
- **Five-engine routing**: Aliyun Tingwu / faster-whisper (local) / SenseVoice (local) / OpenAI-compatible API / Mock — install and fall back as needed
- Structured artifacts: `source.json` / `transcript.json` / `transcript.srt` / `notes.md`, with an async task model (202 on create + polling + retry)

### 🔴 Xiaohongshu workbench

- **Three login paths**: QR code / SMS verification / pasted cookie (with a companion Chrome extension for one-click capture); sessions encrypted at rest, checked on a schedule, offline alerts
- Data endpoints: keyword search, note details and comments, user profiles, watermark-free media download, notifications, creator center, Pugongying / Qianfan
- Async crawl jobs: batch collection + media download + Excel export, artifacts archived per job directory

### ⚙️ Engineering & deployment

- **Dual-mode storage**: zero-dependency file storage by default (copying `data/` is a complete backup); set `DATABASE_URL` to switch to PostgreSQL — same repository interface, one-shot migration script included
- Credentials Fernet-encrypted at rest; webhook notification channels managed in the UI (with a ring-buffer send log)
- **Console CLI**: one-shot tasks like `python -m flowpulse.console weread-sync` print JSON and use exit codes — a natural fit for cron / Task Scheduler
- Single Docker container bundling frontend + backend (FFmpeg and the Node.js signing runtime included); mainland-China networks can switch mirrors via build args
- Backend modules covered by tests (pytest + respx), frontend type-checked (vue-tsc)

## 3. References, Acknowledgements & Disclaimer

### References & acknowledgements

This project builds on the following projects and materials — many thanks to their authors:

| Project | Use | License |
| --- | --- | --- |
| [rachelos/we-mp-rss](https://github.com/rachelos/we-mp-rss) | WeRead channel approach for Official Account subscriptions (`modules/weread/`) | MIT; its copyright notice is retained in the module |
| [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS) | Upstream for Xiaohongshu data capabilities (`modules/xhs/` ported verbatim with import prefixes rewritten; `integration/` is this project's own layer) | No open-source license; the author states personal study only, commercial use prohibited |
| [3441293738/creatorhub](https://github.com/3441293738/creatorhub) | Architecture reference and feature source for multi-platform content management (Douyin/Kuaishou/Channels/TikTok) | No open-source license; see the disclaimer below |

Key dependencies: FastAPI, SQLAlchemy / Alembic, Pydantic, Vue 3, Element Plus, Pinia, Playwright, curl_cffi, FunASR (SenseVoice), faster-whisper, openpyxl, yt-dlp (planned). Thanks to all these excellent open-source projects.

### Disclaimer

1. **This project currently carries no open-source license** (All rights reserved © 2026 izetaiota). It is for the author's personal local use only — **do not redistribute or use commercially**.
2. The capabilities this project relies on (WeRead, Douyin, Xiaohongshu, etc.) are all **unofficial APIs** that may change or break at any time and may trigger platform risk control. Users assume all risks and consequences. Keep usage low-frequency and small-scale, respect each platform's terms of service, and **never use it for unlawful collection, data resale, or any other illegal purposes**.
3. Rights to the upstream projects belong to their respective authors: the Spider_XHS author has declared it "for personal study and exchange only, commercial use prohibited"; this project's reuse of creatorhub code is **not authorized by its author** — if you obtain a copy of this repository, do not distribute it publicly; the author of this project is not liable for that.
4. All credentials (cookies, etc.) and data are stored only in the local `data/` directory. Manage your own backups, encryption and compliance; this project is not liable for data loss or leakage.
5. This project is provided "as is", without warranty of any kind, express or implied.
