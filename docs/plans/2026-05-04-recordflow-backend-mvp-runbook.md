# RecordFlow Backend MVP Runbook

日期：2026-05-04

## 本地启动

```bash
export RECORDFLOW_LLM_API_KEY="your-api-key"
docker compose up --build
```

健康检查：

```bash
curl http://localhost:8000/health
```

浏览器访问：

```text
http://localhost:8000/
```

后台 worker：

```bash
python3 -m recordflow_agent.worker --db-path var/recordflow.db
```

只处理一个 pending job 后退出：

```bash
python3 -m recordflow_agent.worker --db-path var/recordflow.db --once
```

## PostgreSQL

生产或共享测试环境不要用容器内 SQLite 文件。API 和 worker 必须连接同一个 Postgres：

```bash
export DATABASE_URL="postgresql:///recordflow?host=/var/run/postgresql"

uvicorn recordflow_agent.api:app --host 0.0.0.0 --port 8000
python3 -m recordflow_agent.worker
```

数据库选择规则：

- 设置 `DATABASE_URL`：使用 PostgreSQL，适合托管或自建 PostgreSQL 服务。
- 不设置 `DATABASE_URL`：使用 SQLite，适合本地开发和单进程验证。
- `--db-path` 只用于强制 worker 跑本地 SQLite。

真实连接串属于密钥，只放在本机 shell、`.env` 或部署平台 Secret，不写入源码和文档。

## API Key 鉴权

可选配置：

```bash
export RECORDFLOW_APP_API_KEY="your-app-key"
```

配置后，除 `/` 和 `/health` 外，其它 API 需要带：

```text
X-API-Key: your-app-key
```

创建 Workspace：

```bash
curl -X POST http://localhost:8000/workspaces \
  -H 'Content-Type: application/json' \
  -d '{"name":"RecordFlow product","profile":"project_meeting"}'
```

提交 Record：

```bash
curl -X POST http://localhost:8000/workspaces/{workspace_id}/records \
  -H 'Content-Type: application/json' \
  -d '{"title":"meeting 1","text":"决定先做文本导入 MVP。张三负责后端，周五前完成。","use_llm":false}'
```

查询状态页：

```bash
curl http://localhost:8000/workspaces/{workspace_id}/state
```

查询 Review Queue：

```bash
curl http://localhost:8000/workspaces/{workspace_id}/review
```

查询异步 Job：

```bash
curl http://localhost:8000/jobs/{job_id}
```

确认 Review：

```bash
curl -X POST http://localhost:8000/review/{change_event_id} \
  -H 'Content-Type: application/json' \
  -d '{"status":"accepted"}'
```

## 当前上线边界

已包含：

- FastAPI 后端。
- SQLite 持久化。
- PostgreSQL 持久化。
- Workspace / Record / State / Review API。
- 浏览器最小 UI。
- 可选 API Key 鉴权。
- DB-backed 异步 Job Queue。
- Worker CLI。
- 规则型 pipeline。
- 可选 LLM 抽取。
- Docker 部署。

未包含：

- 用户账号与权限。
- 完整前端应用。
- 音频上传和 ASR。
- 对象存储。

## 生产化下一步

1. 增加上传文件和 ASR。
2. 增加对象存储，音频不要写入 Postgres。
3. 增加前端 Review Queue 和 State Page。
4. 增加用户账号与 workspace 权限。
5. 增加运行 trace 和质量评估集。
