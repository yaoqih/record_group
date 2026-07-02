# Minimal ASR Site

## 目标

基于现有 `FastAPI + SQLite + Backblaze B2 + StepAudio 2.5 ASR + worker` 基础设施，补齐一个最小可用的 ASR 网站：

- 用户端
  - 提交音频任务
  - 查看任务状态
  - 查看原始转写
  - 编辑校对文本
  - 确认最终转写
- 管理端
  - 创建用户
  - 充值点数
  - 查看全部任务
- 后台
  - 上传后压缩
  - 发起 StepAudio 2.5 转写
  - 结果回写数据库
  - 7 天清理文件和结果

## 页面

- `/`
  - 用户端页面
- `/admin`
  - 管理端页面
- `/agreement`
  - 用户协议

## 核心接口

- `POST /site/users`
  - 创建用户
- `POST /site/users/{user_id}/recharge`
  - 充值点数
- `POST /site/users/{user_id}/tasks`
  - 上传文件并提交转写任务
- `GET /site/users/{user_id}/tasks`
  - 查看用户任务列表
- `GET /site/tasks/{task_id}`
  - 查看单个任务
- `POST /site/tasks/{task_id}/correction`
  - 保存校对文本
- `POST /site/tasks/{task_id}/confirm`
  - 确认转写
- `GET /site/admin/dashboard`
  - 管理端总览

## 任务流程

### 用户提交

1. 用户选择文件并同意协议。
2. API 接收文件。
3. 服务端先压缩到适合 `StepAudio 2.5 ASR` 的格式。
4. 根据时长或大小估算点数并扣点。
5. 写入站点任务表，状态先记为 `uploading`。
6. 上传压缩后的文件到 B2。
7. 写入 `media_records`。
8. 创建 `transcribe_media` job。
9. 任务状态变为 `queued`。

### Worker 转写

1. worker 领取 `transcribe_media` job。
2. 从 B2 下载压缩后的音频。
3. 调用 `stepaudio-2.5-asr`。
4. 把转写结果写回 `media_records`。
5. 同步写回 `site_asr_tasks`。
6. 任务状态改为 `completed`。

### 用户校对

1. 用户编辑 `corrected_text`。
2. 保存后仍保留 `completed`。
3. 用户点击确认后，状态改为 `confirmed`。

## 点数

- 充值：`site_point_ledger.kind = recharge`
- 消耗：`site_point_ledger.kind = consume`
- 扣点发生在任务创建时
- 最小版本暂不做自动退款

当前计费规则：

- 有 `duration_seconds` 时：按分钟向上取整，最少 1 点
- 没有时长时：按压缩后文件大小估算，每 5 MiB 1 点，最少 1 点

## 清理

- `recordflow_agent/scheduler.py`
  - 定期往 `jobs` 表写入 `cleanup_expired_media`
- `recordflow_agent/worker.py`
  - 处理 `cleanup_expired_media`
  - 删除 B2 文件
  - 把任务和媒体标记为 `expired`
  - 清空转写正文和校对正文

默认保留时间：

- 7 天

## 数据表

新增站点表：

- `site_users`
- `site_point_ledger`
- `site_asr_tasks`

复用已有表：

- `media_records`
- `jobs`
- `workspaces`

## 进程拆分

- API 进程
  - `uvicorn recordflow_agent.api:app`
- worker 进程
  - `python3 -m recordflow_agent.worker`
- scheduler 进程
  - `python3 -m recordflow_agent.scheduler`

## 当前边界

- 只支持 SQLite 版本的最小站点能力。
- 还没有账号登录、权限隔离、多租户安全设计。
- 点数目前只做充值和消耗，不做退款、冻结、账单对账。
- 清理是最小可用逻辑，后续可以继续补审计和告警。
