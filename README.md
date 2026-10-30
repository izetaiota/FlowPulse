# FlowPulse 心流

English | [中文](./README.zh.md)

> **Hand the busywork to the system — get back to creating.**

**FlowPulse** (Chinese: 心流) is an all-in-one content-operations workbench for individual bloggers and independent creators. It aims to connect WeChat Official Accounts, Douyin, Xiaohongshu (RED) and WeChat Channels, and bring topic planning, asset management, unified inbox, batch publishing, content analytics and ad-spend ROI review into a single system — deployable as SaaS or self-hosted via Docker. The core idea: not to manage your accounts for you, but to cut away operational chores and protect your creative flow.

- Website: <https://izetaiota.github.io/FlowPulse/>
- Product & technical docs: the [docs/](docs/) directory (module plans, architecture notes, migration guides — mostly in Chinese)

## Project Status

FlowPulse is in an **early stage of development**, advancing the MVP along the path "content ingestion → workbench → publishing & analytics". Currently available:

| Capability | Directory | Status | Notes |
| --- | --- | --- | --- |
| Official Account RSS (WeRead channel) | `src/flowpulse/modules/weread/` | ✅ Working | Subscribe / incremental sync / in-app reading / RSS output / built-in scheduling / webhook alerts |
| Douyin transcription | `src/flowpulse/modules/douyin/` | ✅ Working | Short-video parsing + speech-to-text, structured output (JSON / SRT / Markdown) |
| Xiaohongshu crawling | `src/flowpulse/modules/xhs/` | ✅ Working | Note / user / search crawling, media download, Excel export (verified with a real account) |
| Workbench frontend | `frontend/` | 🚧 In progress | Vue 3 + Element Plus; login & auth, DB-driven menus, subscription manager with per-feed RSS customization, Xiaohongshu workbench, transcription tasks, notification-channel settings |
| Website landing page | `website/` | ✅ Live | Auto-deployed to GitHub Pages |
| Unified inbox / topics / asset library / batch publishing / content & ad analytics | — | 📋 Planned | Later milestones on the roadmap |

## Getting Started

### Backend

Python 3.11+ locally, no Docker required:

```powershell
git clone https://github.com/izetaiota/FlowPulse.git
cd FlowPulse

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .

Copy-Item .env.example .env

.\.venv\Scripts\python.exe -m uvicorn flowpulse.main:app `
  --host 127.0.0.1 `
  --port 8000
```

Then open:

- Swagger API docs: <http://127.0.0.1:8000/docs>
- Liveness check: <http://127.0.0.1:8000/health/live>
- Readiness check: <http://127.0.0.1:8000/health/ready>

### Workbench frontend

```powershell
cd frontend
pnpm install
pnpm dev        # http://localhost:5173, /api proxied to 127.0.0.1:8000
```

See [frontend/README.md](frontend/README.md) for the page modules (dashboard, accounts, inbox, topics, assets, subscriptions, content creation, publishing, reports, settings).

### Docker deployment (single container, frontend + backend)

```bash
docker compose up -d --build
```

Open <http://127.0.0.1:8000> for the workbench frontend; `/api` hits the backend on the same origin. All runtime data lives in the host `./data` directory.

- Configuration: copy `.env.example` to `.env` in the project root (transcription engines, WeRead cookie, webhook alerts, etc.); compose injects it into the container.
- If the default registries are slow or blocked (e.g. mainland China networks), override the base images and package mirrors with `--build-arg` (see the header comments in `Dockerfile`):

  ```bash
  docker build \
    --build-arg NODE_IMAGE=docker.1ms.run/library/node:22-alpine \
    --build-arg PYTHON_IMAGE=docker.1ms.run/library/python:3.12-slim-bookworm \
    --build-arg APT_MIRROR=mirrors.tuna.tsinghua.edu.cn \
    --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    --build-arg NPM_REGISTRY=https://registry.npmmirror.com \
    -t flowpulse:latest .
  ```

- The image ships FFmpeg (Douyin audio extraction) and Node.js (Xiaohongshu signing runtime); due to opencv and other dependencies the image is roughly 1.5 GB.
- QR-code login features (WeRead re-login, XHS QR login) need a visible local browser and do not work inside the container — configure credentials via cookie instead.

### Storage: file / PostgreSQL dual mode

- **Default, zero-dependency file storage**: leave `DATABASE_URL` unset and everything is stored under `data/` (atomic JSON writes); copying the directory is a complete backup.
- **PostgreSQL mode**: set `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/flowpulse` (requires `pip install -e ".[postgres]"`); the weread module then switches to database storage — subscriptions / articles / content cache / credentials / scheduler state live in separate tables, with article content isolated in its own table so list queries never drag large columns along. docker-compose ships a `postgres:16` service and defaults to PG mode (remove the variable and the postgres service to use file storage).
- The schema is managed by Alembic (`python -m alembic upgrade head`, connection string from `DATABASE_URL`); the app also creates missing tables idempotently on startup, so an empty database works out of the box.
- Migrating from file storage to PG: `DATABASE_URL=... PYTHONPATH=src python scripts/migrate_weread_to_pg.py` (idempotent, safe to re-run).
- Cookies are Fernet-encrypted at rest in both modes, sharing the key `data/weread/.credential_key` (or `WEREAD_CREDENTIAL_KEY`); ciphertexts are interchangeable across backends.

## Web login (single account)

The workbench supports a single-account login (no per-menu permissions — V1 targets a single user):

- **Off by default**: without `ADMIN_PASSWORD` there is no login page and every endpoint is open (the zero-config local experience stays unchanged).
- **Enabled**: set `ADMIN_USERNAME` (default `admin`) and `ADMIN_PASSWORD`, and the frontend shows a login page; every API then requires a Bearer token (injected automatically after login, valid for 7 days, survives service restarts).
- Header-less clients such as RSS readers can use a query parameter: `/api/weread/rss/all.xml?token=<login token>`; `/health/*` probes stay open. Tokens are HMAC-signed server-side (secret auto-generated at `data/.auth_secret`).
- Logout via the user menu in the top-right corner.

## Scheduled tasks (console CLI)

`src/flowpulse/console/` provides one-shot task commands that exit when done, designed for external schedulers (crontab / Windows Task Scheduler / `docker compose run`). They complement the in-app resident schedulers (WeRead sync, cookie refresh, XHS credential checks) — useful when you prefer to disable the built-in loops and drive everything from system cron, or just need a manual catch-up run.

```bash
python -m flowpulse.console list                  # list all tasks
python -m flowpulse.console weread-sync           # incremental sync of all subscriptions
python -m flowpulse.console weread-status         # credential/subscription health check (non-zero exit on failure)
python -m flowpulse.console weread-refresh-cookie # headless cookie refresh (needs a local browser profile)
python -m flowpulse.console xhs-check             # Xiaohongshu login-state check
```

After a pip install the `flowpulse-console <task>` command is also available. Each task prints a JSON summary (with an `ok` field) and exits non-zero on failure, which is easy for cron and monitoring systems to consume.

Scheduling examples:

```bash
# Linux crontab: sync official accounts every 2 hours
0 */2 * * * cd /opt/flowpulse && python -m flowpulse.console weread-sync >> data/cron.log 2>&1

# Windows Task Scheduler: check credentials daily at 09:05
schtasks /Create /TN FlowPulseStatus /SC DAILY /ST 09:05 /TR "python -m flowpulse.console weread-status"

# Docker (reuses the image and the mounted data volume)
docker compose run --rm flowpulse python -m flowpulse.console weread-sync
```

## Official Account RSS (WeRead channel)

`src/flowpulse/modules/weread/` implements the WeRead channel approach of [rachelos/we-mp-rss](https://github.com/rachelos/we-mp-rss) (MIT): the first step of bringing Official Account content into FlowPulse — **subscribe → scheduled incremental sync → in-app reading / RSS output**.

How it works:

1. Subscribe to the target Official Account inside the **WeRead app** (an account appears as a "book" there, with a bookId like `MP_WXS_3012726261`).
2. FlowPulse holds your WeRead web cookie (key fields: `wr_vid`, `wr_skey`) and polls the WeRead web API for new articles.
3. The original article URL is derived from the record ID (the token's `~` must be restored to `_`, otherwise WeChat returns "invalid parameter").
4. Subscription state is maintained by FlowPulse itself (newer WeRead shelf APIs no longer return Official Accounts); adding a subscription takes a pasted WeRead link or bookId.

### Usage flow

1. **QR-code login (recommended)**: click "Scan to login" on the `/weread` page (or `POST /api/weread/credential/qr-login`); a browser window with the WeRead login QR code opens on the machine running the server, and after scanning the cookie is captured, validated and stored automatically.
2. Or paste a cookie manually: log into the WeRead web client, copy the cookie, and save it via `POST /api/weread/credential` (or set `WEREAD_COOKIE` in `.env`, imported on startup).
3. Add a subscription: `POST /api/weread/subscriptions` with `{"input": "<WeRead link or bookId>"}`; the account name and avatar are resolved automatically and the latest article is stored.
4. Manual full sync: `POST /api/weread/sync`; afterwards the built-in scheduler keeps things in sync incrementally.
5. Subscribe to the RSS output in your reader, or manage everything from the `/weread` page in the workbench.

> QR login/refresh relies on Playwright driving a local browser: `pip install -e ".[weread]"` (it prefers an existing local Chrome/Edge, no browser download needed).
> Note on history: the WeRead list API is deprecated for some accounts; those accounts only track new articles from the latest one at subscription time via the cover channel — backfilling history is not possible.

### API overview

| Group | Endpoints |
| --- | --- |
| Credential | `POST /api/weread/credential` (save), `GET` (masked status), `DELETE`, `POST /api/weread/credential/validate` (immediate validity check) |
| QR login | `POST /api/weread/credential/qr-login` (opens a browser window), `GET` (poll session status), `DELETE` (cancel) |
| Cookie refresh | `POST /api/weread/credential/refresh` (one manual headless refresh), `GET` (refresh schedule and last result) |
| Subscriptions | `GET /api/weread/subscriptions`, `POST` (add), `DELETE /api/weread/subscriptions/{book_id}` |
| Articles | `GET /api/weread/subscriptions/{book_id}/articles` (cursor pagination), `GET /api/weread/articles/{book_id}/{review_id}/content` (in-app reading, content fetched on demand and cached) |
| Sync | `POST /api/weread/sync` (all), `POST /api/weread/subscriptions/{book_id}/sync` (one), `GET /api/weread/status` (credential and per-subscription health) |
| RSS | `GET /api/weread/rss/all.xml` (all subscriptions merged), `GET /api/weread/rss/{book_id}.xml` (single account) |
| Scheduler | `GET /api/weread/scheduler` (status), `POST /api/weread/scheduler/trigger` (trigger one round manually) |

### Configuration

```env
WEREAD_COOKIE=                        # WeRead cookie imported on startup (optional; API/QR login also work)
WEREAD_CREDENTIAL_KEY=                # Fernet key for cookie encryption at rest; empty = auto-generated to data/weread/.credential_key
WEREAD_REQUEST_INTERVAL_SECONDS=2.0   # rate-limit interval between WeRead API calls
WEREAD_SYNC_INTERVAL_MINUTES=120      # sync period; <=0 disables the built-in scheduler
WEREAD_COOKIE_REFRESH_HOURS=24        # headless cookie auto-refresh period; <=0 disables
WEREAD_WEBHOOK_URL=                   # alert webhook (Feishu/DingTalk bot) for cookie expiry, sync failures, re-login needed
WEREAD_RSS_FULL_TEXT=false            # full text in RSS output (default: title + link + summary)
```

Data lives in `data/weread/` (subscriptions, articles, content cache, scheduler state, browser login profile). Cookies are stored Fernet-encrypted (see `WEREAD_CREDENTIAL_KEY`); while valid, `wr_skey` rotates automatically via the daily headless refresh. When the login profile dies completely, the credential is marked invalid and a webhook alert is sent — scan once on the page to recover (the profile persists afterwards and refresh continues automatically). If a sync detects the cookie was rotated by another device, one headless refresh plus a retry fires automatically (15-minute cooldown) with no manual intervention. Deleting the credential also wipes the browser login profile. After a service restart, overdue sync/refresh runs catch up automatically at startup.

> The WeRead channel is an unofficial API. This project is designed for "personal self-hosted use + rate limiting + expiry alerts" — please do not pull at high frequency or volume. See [docs/WECHAT_WEREAD_RSS_PLAN.md](docs/WECHAT_WEREAD_RSS_PLAN.md) for the migration decision and technical details.

## Douyin transcription

Feed in a Douyin share link or the full share text; the video is resolved, embedded subtitles preferred, and when absent the audio is transcribed by a local model, Aliyun Tingwu or an OpenAI-compatible API.

```text
Douyin share text or URL
  -> resolve the share page or a fallback Resolver API
  -> fetch video info and playback URL
  -> check for embedded subtitles
     -> present: normalize directly
     -> absent: download video -> FFmpeg extracts audio -> call a transcription engine
  -> produce source.json / transcript.json / transcript.srt / notes.md
```

- Supports short links, regular links and full share text, with an optional fallback Resolver API (`DOUYIN_RESOLVER_BASE_URL`).
- Engines: **Aliyun Tingwu**, **faster-whisper** (`pip install -e ".[whisper]"`), **SenseVoice** (`pip install -e ".[sensevoice]"`), **OpenAI-compatible API**, **Mock** (API smoke tests, only when explicitly requested).
- FFmpeg lookup order: `FFMPEG_PATH` env var → system `PATH` → `.tools/ffmpeg/bin/ffmpeg.exe` in the project.
- Async task model: `POST /api/v1/tasks/transcribe` to create (202), `GET /api/v1/tasks/<task-id>` to poll, `POST .../retry` to retry, `GET .../artifacts` to download.

Artifacts:

```text
data/tasks/<task-id>/
  task.json          # request, status, progress, errors, artifact list
  source.json        # Douyin video info and raw metadata
  transcript.json    # full text, engine, segment timeline
  transcript.srt     # standard SRT subtitles
  notes.md           # Markdown notes with source info
  video.mp4          # kept only when keep_video=true
```

Engine environment variables and the Tingwu OSS flow are documented in [.env.example](.env.example) and [docs/DOUYIN_TINGWU_PIPELINE.md](docs/DOUYIN_TINGWU_PIPELINE.md).

## Xiaohongshu (XHS) crawling

`src/flowpulse/modules/xhs/` is ported verbatim from [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS) (only import prefixes rewritten), mounted on the same FastAPI app under the `/api/v1/xhs` prefix.

- **Prerequisites**: Node.js (signing runtime) + `cd src/flowpulse/modules/xhs && npm install` (crypto-js); Python extras `pip install -e ".[xhs]"`; optional proxy via `XHS_PROXY`.
- **Login**: cookie paste / QR code / phone verification; sessions persist in `data/xhs/cookies.json`. QR and cookie logins are verified against a real account. Cookie login needs the complete cookie (both `web_session` and `a1`; the bundled Chrome extension under `extension/` grabs it in one click).
- **Data endpoints**: note details / comments / watermark-free media, keyword and user search, homefeed, user profiles and notes, notifications, creator center, Pugongying / Qianfan — all return JSON directly.
- **Async jobs**: `POST /api/v1/xhs/jobs` creates a crawl + download job (media, Excel export); artifacts land in `data/xhs/jobs/<job_id>/`.

Upstream sync notes: when the platform's algorithms change, pull the new version over `apis/`, `xhs_utils/` and `spider/`, rewrite the import prefixes, and leave `integration/` alone.

> ⚠️ The upstream [Spider_XHS](https://github.com/cv-cat/Spider_XHS) repository carries no open-source license; its README states "for personal study and exchange only, commercial use prohibited". Keep this module to personal learning and research, and assess compliance risks yourself before any commercial use.

## Workbench frontend

`frontend/` is a Vue 3 + Vite + TypeScript + Element Plus + Pinia + Tailwind CSS admin skeleton; pages follow the product roadmap:

| Route | Module | Status |
| --- | --- | --- |
| `/weread` | Official Account subscriptions | ✅ Wired to the backend (cookie, subscriptions, articles, RSS, scheduled sync) |
| `/xhs` | Xiaohongshu workbench | ✅ Wired to the backend |
| `/transcribe` | Douyin transcription | ✅ Wired to the backend |
| `/dashboard`, `/accounts`, `/messages`, `/topics`, `/materials`, `/content/create`, `/publish`, `/reports/*`, `/settings` | Dashboard, accounts, inbox, topics, assets, creation, publishing, reports, settings | 🚧 Placeholder |

See [frontend/README.md](frontend/README.md) for details.

## Project structure

```text
src/flowpulse/
  main.py            FastAPI app assembly (create_app)
  runtime.py         service wiring factory shared by web app and console
  config.py          global Settings (.env driven)
  static_site.py     frontend static hosting (single Docker container)
  console/           one-shot task CLI (for external cron / Task Scheduler)
  core/              shared infrastructure: storage (atomic writes) / notify (webhooks) / crypto (credential encryption)
  db/                database layer: SQLAlchemy models and engine (PostgreSQL mode)
  modules/           business module domains (new modules go here)
    weread/          Official Account RSS (WeRead channel): client / service / storage / rss / scheduler / qrlogin / refresh / api
    douyin/          Douyin transcription: resolvers / services / transcribers / renderers / storage / api
    xhs/             Xiaohongshu crawling: apis / xhs_utils / spider (upstream port) + integration (project layer)
frontend/            Vue 3 workbench frontend
website/             landing page (GitHub Pages)
extension/           Chrome extension (one-click XHS cookie capture)
docs/                technical docs
migrations/          Alembic database migrations
scripts/             helper scripts (WeRead probe, PG data migration, etc.)
data/                runtime data (tasks, subscriptions, login state; not committed)
```

## Development & testing

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

## Roadmap

- [x] WeRead Official Account RSS (subscribe / incremental sync / RSS / scheduling / webhook alerts)
- [ ] Land the workbench frontend page by page (dashboard → inbox → topics / asset library)
- [ ] Multi-platform account integration and unified inbox
- [ ] Content editing and batch publishing
- [ ] Content analytics and ad-spend ROI
- [x] Docker self-hosted deployment (Dockerfile + docker-compose, single container)

See the Project Status table above for the feature roadmap.

## Current limitations

- Background tasks and schedulers run inside the FastAPI process; tasks in flight do not resume after a restart (scheduler state is persisted, so overdue runs catch up).
- The WeRead channel is an unofficial API with rate limits and cookie-expiry risk; high-frequency bulk pulling may trigger risk control.
- XHS signing depends on external Node.js and Xiaohongshu's live algorithms — platform updates or risk-control changes can break it; XHS intermediate login sessions live in memory only.
- No rate limiting, task cancellation or SSE progress streaming yet.
- Douyin share-page layout or risk-control changes can break direct resolution; embedded subtitles skip download and Tingwu transcription.

For production deployments, consider API auth hardening, a persistent task queue, concurrency limits and structured logging.

## License

[MIT](LICENSE) © 2026 izetaiota. `src/flowpulse/modules/xhs/` is ported from [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS); the WeRead channel in `src/flowpulse/modules/weread/` follows [rachelos/we-mp-rss](https://github.com/rachelos/we-mp-rss) (MIT, its copyright notice retained in the module).
