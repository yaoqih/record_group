# RecordFlow Agent MVP

This folder contains a minimal offline implementation of RecordFlow with only two user-facing capabilities:

1. 转录和校对
2. 对内容的详细整理和总结

## Run Tests

```bash
python3 -m pytest -q
```

## Run Backend API

Local Python:

```bash
uvicorn recordflow_agent.api:app --host 0.0.0.0 --port 8000
```

Docker:

```bash
docker compose up --build
```

Run only the worker against a local DB:

```bash
python3 -m recordflow_agent.worker --db-path var/recordflow.db --once
```

Run API and worker against Postgres / Neon:

```bash
export DATABASE_URL="postgresql://user:password@host/dbname?sslmode=require"

uvicorn recordflow_agent.api:app --host 0.0.0.0 --port 8000
python3 -m recordflow_agent.worker
```

Health check:

```bash
curl http://localhost:8000/health
```

The public browser test page is intentionally disabled. The browser UI is admin-only:

```text
http://localhost:8000/admin
```

## Frontend Dev

The management console uses a separated React + Vite frontend under `frontend/`.

Development mode:

```bash
uvicorn recordflow_agent.api:app --host 0.0.0.0 --port 8000

cd frontend
npm install
npm run dev
```

Then open:

```text
http://localhost:5173/admin
```

Vite proxies the management API and supporting backend routes to FastAPI on `127.0.0.1:8000`.

Production build served by FastAPI:

```bash
cd frontend
npm run build

cd ..
uvicorn recordflow_agent.api:app --host 0.0.0.0 --port 8000
```

After `frontend/dist` exists, FastAPI serves the built management frontend at `/admin` (including nested admin routes) and its generated assets under `/assets/*`. The root path `/` remains unavailable.

## WeChat Mini Program MVP

An MVP WeChat Mini Program lives under `miniprogram/`. It uses the existing FastAPI backend plus WeChat login.

```bash
export WECHAT_MINIAPP_APPID="your-miniapp-appid"
export WECHAT_MINIAPP_SECRET="your-miniapp-secret"
export RECORDFLOW_SESSION_SECRET="replace-with-a-long-random-secret"
export RECORDFLOW_MINIAPP_SIGNUP_POINTS="100"

uvicorn recordflow_agent.api:app --host 0.0.0.0 --port 8000
python3 -m recordflow_agent.worker --poll-seconds 1
```

Open `miniprogram/` in WeChat DevTools, set the real appid in `miniprogram/project.config.json`, and update `miniprogram/utils/config.js` when using a deployed HTTPS API domain.

Recharge uses WeChat Mini Program Virtual Payment (currency mode). Configure these backend-only secrets before enabling payment:

```bash
export WECHAT_VIRTUAL_OFFER_ID="your-offer-id"
export WECHAT_VIRTUAL_ENV="1" # 1=sandbox, 0=production
export WECHAT_VIRTUAL_APPKEY="sandbox-or-production-appkey"
```

The client uses `wx.requestVirtualPayment`. The server validates encrypted message-push notifications and credits paid orders idempotently; points are never credited from the client success callback alone.

Configure `WECHAT_MESSAGE_TOKEN` and set the mini-program message-push URL to `https://your-api-domain/wechat/callback`. The server validates WeChat's URL verification request before accepting the callback configuration.

## Run CLI

```bash
python3 -m recordflow_agent.cli data/eval/synthetic/project_meeting/record_1.txt --pretty
```

Run two records in the same workspace to see incremental updates:

```bash
python3 -m recordflow_agent.cli \
  data/eval/synthetic/project_meeting/record_1.txt \
  data/eval/synthetic/project_meeting/record_2.txt \
  --pretty
```

## Run With A Model API

The LLM integration uses an OpenAI-compatible `/chat/completions` endpoint. The local `.env` already contains the default base URL and model:

```env
RECORDFLOW_LLM_BASE_URL=https://yunwu.ai/v1
RECORDFLOW_LLM_MODEL=deepseek-v4-flash
```

Do not hardcode API keys in source files. Configure the key through the shell or fill it locally in `.env`:

```bash
export RECORDFLOW_LLM_API_KEY="your-api-key"

python3 -m recordflow_agent.cli \
  data/eval/synthetic/project_meeting/record_1.txt \
  --use-llm \
  --pretty
```

`--use-llm` enables structured object extraction and Record Digest section rewriting. If the LLM call fails, Digest generation falls back to the deterministic sections instead of failing the record.

## Optional App API Key

Set `RECORDFLOW_APP_API_KEY` to protect API routes. `/health`, the agreement page, mini-program authentication/session routes, and the admin shell remain available as required by their clients. API clients must send:

```text
X-API-Key: your-app-key
```

## Current Scope

- Fixed pipeline: segment -> extract -> merge -> render.
- Two product modes: transcription/proofreading and detailed organization/summarization.
- In-memory repository for fast MVP testing.
- SQLite repository for deployable backend persistence.
- Postgres repository for shared API/worker persistence on Neon or similar hosts.
- Admin-only browser console served by FastAPI at `/admin`.
- Optional API key authentication.
- DB-backed async job queue and worker.
- Deterministic top-down Record Digest engine with persisted digests and patchable sections.
- Optional OpenAI-compatible LLM extraction and Digest section rewriting through `--use-llm`.
- Two scene profiles that map to the two product modes.

## Database Selection

RecordFlow chooses the repository from environment variables:

- If `DATABASE_URL` starts with `postgresql://` or `postgres://`, the API and worker use Postgres.
- Otherwise, they use SQLite at `RECORDFLOW_DB_PATH`, defaulting to a temporary local file.

For MVP deployment on Neon, set `DATABASE_URL` in the hosting platform secret
settings. Do not put the real connection string in source files or docs.

See `docs/plans/2026-05-04-recordflow-backend-mvp-runbook.md` for API examples and deployment notes.

 # 生产 API
journalctl -u recordflow-api -f

# 生产 worker
journalctl -u recordflow-worker -f

# 测试 API
journalctl -u recordflow-staging-api -f

# 测试 worker
journalctl -u recordflow-staging-worker -f
