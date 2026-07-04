# RecordFlow Server Deployment

This deployment keeps the runtime simple:

- `recordflow-migrate.service`: one-shot PostgreSQL migrations
- `recordflow-api.service`: FastAPI on `127.0.0.1:8000`
- `recordflow-worker.service`: background job worker
- PostgreSQL: local database on `127.0.0.1:5432`
- Caddy: public HTTPS reverse proxy

## 1. Prepare the app

Install system packages:

```bash
sudo apt update
sudo apt install -y python3-venv ffmpeg postgresql-client
```

```bash
sudo useradd --system --create-home --home-dir /opt/recordflow --shell /usr/sbin/nologin recordflow
sudo mkdir -p /opt/recordflow /etc/recordflow
sudo chown -R recordflow:recordflow /opt/recordflow
```

Copy or clone this repository to `/opt/recordflow`, then install dependencies:

```bash
cd /opt/recordflow
sudo -u recordflow python3 -m venv .venv
sudo -u recordflow .venv/bin/python -m pip install -r requirements.txt
```

## 2. Configure environment

```bash
sudo cp deploy/recordflow.env.example /etc/recordflow/recordflow.env
sudo chmod 600 /etc/recordflow/recordflow.env
sudo nano /etc/recordflow/recordflow.env
```

Set at least:

```env
DATABASE_URL=postgresql://recordflow:your-password@127.0.0.1:5432/recordflow
RECORDFLOW_SESSION_SECRET=your-long-random-string
```

If OSS is mounted on the server, use the filesystem storage backend:

```env
RECORDFLOW_MEDIA_STORAGE_BACKEND=filesystem
RECORDFLOW_FS_STORAGE_ROOT=/record
RECORDFLOW_FS_PUBLIC_BASE_URL=https://oss.example.com/record
```

`RECORDFLOW_FS_PUBLIC_BASE_URL` must be reachable by the ASR provider because
background transcription jobs pass the stored media URL to the ASR API.

If OSS/COS is only temporary storage for raw uploads and compressed files still
go to B2, keep `RECORDFLOW_MEDIA_STORAGE_BACKEND=b2` and only move pending
uploads:

```env
RECORDFLOW_PENDING_UPLOAD_ROOT=/record/production/pending
RECORDFLOW_PENDING_UPLOAD_PUBLIC_BASE_URL=https://record-1439403413.cos.ap-shanghai.myqcloud.com/production/pending
RECORDFLOW_COS_BUCKET=record-1439403413
RECORDFLOW_COS_REGION=ap-shanghai
RECORDFLOW_COS_DIRECT_UPLOAD_PREFIX=production/pending
```

For Mini Program direct upload to COS, the backend exposes a short-lived init
API that returns the upload form and a RecordFlow upload token. If the temporary
COS bucket is intentionally public-writable, set:

```env
RECORDFLOW_COS_DIRECT_UPLOAD_PUBLIC_WRITE=true
```

In that mode, COS accepts the upload directly and the backend still requires
the RecordFlow upload token before creating a task from the mounted
`/record/.../pending` file. If the bucket is private, keep public write disabled
and configure a COS key that has `PostObject` permission:

```env
TENCENTCLOUD_SECRET_ID=...
TENCENTCLOUD_SECRET_KEY=...
RECORDFLOW_COS_DIRECT_UPLOAD_PUBLIC_WRITE=false
```

## 3. Install services

```bash
sudo cp deploy/systemd/recordflow-migrate.service /etc/systemd/system/
sudo cp deploy/systemd/recordflow-api.service /etc/systemd/system/
sudo cp deploy/systemd/recordflow-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now recordflow-api recordflow-worker
```

`recordflow-api` and `recordflow-worker` both require `recordflow-migrate`, so
database migrations run before either long-running service starts.

Check status and logs:

```bash
systemctl status recordflow-migrate recordflow-api recordflow-worker
journalctl -u recordflow-migrate -n 100
journalctl -u recordflow-api -f
journalctl -u recordflow-worker -f
```

## 4. Add HTTPS

Point DNS `api.example.com` to the server IP, then install Caddy:

```bash
sudo apt update
sudo apt install -y caddy
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Verify:

```bash
curl https://api.example.com/health
```

## 5. Update clients

For the Mini Program, set `miniprogram/utils/config.js`:

```js
const API_BASE = 'https://api.example.com'
```

Also add the HTTPS domain in the WeChat Mini Program console for `request`, `uploadFile`, and `downloadFile`.

## Updates

Use this order for a normal release:

```bash
cd /opt/recordflow
sudo -u recordflow git pull
sudo -u recordflow .venv/bin/python -m pip install -r requirements.txt
sudo -u recordflow .venv/bin/python -m pytest -q
sudo systemctl restart recordflow-api recordflow-worker
```

The restart runs `recordflow-migrate` first. To run migrations manually:

```bash
cd /opt/recordflow
sudo -u recordflow .venv/bin/python -m recordflow_agent.db_migrate
```

For schema changes, add a new file under `migrations/postgres/` instead of
editing an existing migration. Applied migrations are tracked in the
`schema_migrations` table with a checksum.

Before production updates that change data shape, take a database backup:

```bash
pg_dump "$DATABASE_URL" > "recordflow-$(date +%Y%m%d%H%M%S).sql"
```

## Staging and Production

Keep staging and production identical except for environment values:

- separate PostgreSQL databases
- separate `/etc/recordflow/*.env` files
- separate domains, for example `staging-api.example.com` and `api.example.com`
- the same code revision after staging has passed smoke tests

The simplest production setup is one server for staging and one server for
production. If both run on one server, use separate app directories, ports, env
files, databases, and systemd unit names, for example:

- `/opt/recordflow-staging` with `/etc/recordflow/staging.env` on port `8001`
- `/opt/recordflow` with `/etc/recordflow/production.env` on port `8000`

Do not share the same database between staging and production.

Suggested smoke tests after deploy:

```bash
curl https://api.example.com/health
curl https://api.example.com/site/admin/dashboard
```
