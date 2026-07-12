from __future__ import annotations


USER_SITE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ASR 转写站</title>
  <style>
    :root {
      --bg: #f6f2e8;
      --card: #fffdf8;
      --line: #e5dac6;
      --text: #2b241c;
      --muted: #7a6d5d;
      --brand: #0d6b57;
      --brand-2: #d26f38;
      --warn: #a64226;
      font-family: "SF Pro SC", "PingFang SC", "Noto Sans CJK SC", sans-serif;
      color-scheme: light;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(210,111,56,0.15), transparent 32%),
        radial-gradient(circle at top right, rgba(13,107,87,0.12), transparent 28%),
        var(--bg);
    }
    a { color: inherit; }
    header, main { width: min(1120px, calc(100vw - 32px)); margin: 0 auto; }
    header { padding: 28px 0 12px; }
    h1, h2, h3 { margin: 0; }
    .hero {
      display: grid;
      gap: 12px;
      padding: 24px;
      border: 1px solid var(--line);
      border-radius: 24px;
      background: linear-gradient(135deg, rgba(255,255,255,0.98), rgba(252,247,238,0.96));
      box-shadow: 0 20px 60px rgba(45, 31, 14, 0.08);
    }
    .hero-top { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: center; }
    .hero-badge {
      display: inline-flex; gap: 8px; align-items: center;
      background: rgba(13,107,87,0.08); color: var(--brand);
      border-radius: 999px; padding: 8px 12px; font-size: 13px;
    }
    .hero-nav { display: flex; gap: 12px; flex-wrap: wrap; }
    .hero-nav a { text-decoration: none; color: var(--muted); }
    .hero p { margin: 0; color: var(--muted); max-width: 720px; line-height: 1.6; }
    main { padding: 8px 0 40px; display: grid; gap: 16px; }
    .grid { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 16px; }
    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 18px;
      box-shadow: 0 14px 36px rgba(45, 31, 14, 0.06);
    }
    .card-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-end; margin-bottom: 12px; }
    .muted { color: var(--muted); font-size: 13px; }
    .toolbar, .inline-form { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    .inline-form { margin-top: 12px; }
    input, select, textarea, button {
      font: inherit;
      border-radius: 14px;
      border: 1px solid var(--line);
      padding: 11px 13px;
      background: #fff;
      color: var(--text);
    }
    input, select, textarea { width: 100%; }
    textarea { min-height: 130px; resize: vertical; }
    button {
      background: var(--brand);
      color: #fff;
      border: none;
      cursor: pointer;
      transition: transform 140ms ease, opacity 140ms ease;
    }
    button.secondary { background: var(--brand-2); }
    button.ghost { background: #efe5d4; color: var(--text); }
    button:hover { transform: translateY(-1px); }
    button:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
    label { display: grid; gap: 6px; font-size: 14px; color: var(--muted); }
    .task-list { display: grid; gap: 12px; }
    .task {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      background: #fffcf7;
      display: grid;
      gap: 10px;
    }
    .task-top { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    .status-chip {
      display: inline-flex; align-items: center; gap: 8px;
      border-radius: 999px; padding: 6px 10px; font-size: 12px;
      background: #ece5da; color: var(--text);
    }
    .transcript {
      white-space: pre-wrap;
      word-break: break-word;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px;
      background: #fff;
      line-height: 1.65;
      min-height: 88px;
    }
    .metrics { display: flex; gap: 12px; flex-wrap: wrap; }
    .metric {
      min-width: 120px;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #fff;
    }
    .metric strong { display: block; font-size: 24px; }
    .warn { color: var(--warn); }
    .checkbox { display: flex; gap: 8px; align-items: flex-start; font-size: 13px; color: var(--muted); }
    .checkbox input { width: auto; margin-top: 2px; }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <div class="hero">
      <div class="hero-top">
        <div class="hero-badge">StepAudio 2.5 ASR · 最小可用站点</div>
        <nav class="hero-nav">
          <a href="/">用户端</a>
          <a href="/admin">管理端</a>
          <a href="/agreement" target="_blank">用户协议</a>
        </nav>
      </div>
      <h1>提交音频，自动转写，人工校对后确认</h1>
      <p>这个最小版本走现有 FastAPI + SQLite + B2 + StepAudio 2.5 ASR 基础设施。上传后会先在服务器侧压缩到适合 ASR 的格式，再入库、上传对象存储、发起转写任务。</p>
    </div>
  </header>
  <main>
    <section class="grid">
      <div class="card">
        <div class="card-head">
          <div>
            <h2>1. 选择用户并提交任务</h2>
            <div class="muted">先建用户、充值，再提交音频文件。</div>
          </div>
          <button class="ghost" onclick="refreshAll()">刷新</button>
        </div>
        <div class="inline-form">
          <label style="flex:1 1 220px;">
            当前用户
            <select id="userSelect" onchange="onUserChange()"></select>
          </label>
          <button class="secondary" onclick="createUser()">新建用户</button>
        </div>
        <div class="metrics" style="margin:14px 0 18px;">
          <div class="metric"><strong id="userPoints">0</strong><span class="muted">剩余点数</span></div>
          <div class="metric"><strong id="userTasks">0</strong><span class="muted">任务数</span></div>
        </div>
        <form id="submitForm" onsubmit="submitTask(event)" style="display:grid; gap:12px;">
          <label>
            音频文件
            <input id="taskFile" type="file" accept="audio/*,video/*" required />
          </label>
          <div class="muted">提交即视为你已确认文件具备合法处理权限。<a href="/agreement" target="_blank">查看用户协议</a></div>
          <div class="toolbar">
            <button id="submitButton" type="submit">上传到服务器并创建任务</button>
            <span id="submitStatus" class="muted">准备就绪</span>
          </div>
        </form>
      </div>
      <div class="card">
        <div class="card-head">
          <div>
            <h2>2. 当前任务说明</h2>
            <div class="muted">用户端只做最核心的事情：提交、等结果、校对、确认。</div>
          </div>
        </div>
        <ul style="margin:0; padding-left:18px; line-height:1.8;">
          <li>上传后先落到服务器临时区，立即创建任务单。</li>
          <li>服务端自动读取时长，并按 1 分钟 1 点向上取整给出应扣点数。</li>
          <li>用户确认扣点后，服务器才压缩、上传 B2、入转写队列。</li>
          <li>后台 worker 轮询任务队列，调用 ASR，结果写回数据库。</li>
          <li>本地临时文件 1 天清理，B2 正式数据 7 天清理。</li>
        </ul>
      </div>
    </section>
    <section class="card">
      <div class="card-head">
        <div>
          <h2>3. 我的任务</h2>
          <div class="muted">列表里直接看状态、原始转写、校对文本。</div>
        </div>
      </div>
      <div id="taskList" class="task-list">
        <div class="muted">请先选择用户。</div>
      </div>
    </section>
  </main>
  <script>
    let currentUserId = "";
    let currentTasks = [];

    async function fetchJson(url, options) {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || data.message || JSON.stringify(data));
      }
      return data;
    }

    async function refreshAll() {
      await loadUsers();
      if (currentUserId) {
        await loadUserTasks(currentUserId);
      }
    }

    async function loadUsers() {
      const data = await fetchJson("/site/users");
      const select = document.getElementById("userSelect");
      const users = data.users || [];
      if (!users.length) {
        select.innerHTML = '<option value="">请先创建用户</option>';
        currentUserId = "";
        document.getElementById("userPoints").textContent = "0";
        document.getElementById("userTasks").textContent = "0";
        document.getElementById("taskList").innerHTML = '<div class="muted">还没有用户，请先创建。</div>';
        return;
      }
      if (!currentUserId || !users.find(item => item.id === currentUserId)) {
        currentUserId = users[0].id;
      }
      select.innerHTML = users.map((user) => (
        `<option value="${escapeHtml(user.id)}" ${user.id === currentUserId ? "selected" : ""}>${escapeHtml(user.name)} · ${user.points_balance} 点</option>`
      )).join("");
      const currentUser = users.find(item => item.id === currentUserId);
      document.getElementById("userPoints").textContent = String(currentUser.points_balance || 0);
    }

    async function onUserChange() {
      currentUserId = document.getElementById("userSelect").value;
      if (currentUserId) {
        await loadUserTasks(currentUserId);
      }
    }

    async function loadUserTasks(userId) {
      const data = await fetchJson(`/site/users/${userId}/tasks`);
      currentTasks = data.tasks || [];
      document.getElementById("userTasks").textContent = String(currentTasks.length);
      renderTasks();
    }

    function renderTasks() {
      const container = document.getElementById("taskList");
      if (!currentTasks.length) {
        container.innerHTML = '<div class="muted">当前用户还没有任务。</div>';
        return;
      }
      container.innerHTML = currentTasks.map(renderTask).join("");
    }

    function renderTask(task) {
      const transcript = task.transcript_text || "还没有结果";
      const corrected = task.corrected_text || "";
      const canEdit = ["completed", "confirmed"].includes(task.status);
      const canStart = task.status === "uploaded";
      const canConfirmResult = ["completed", "confirmed"].includes(task.status);
      const startHint = task.status === "queued"
        ? "已入队，等待 worker 开始转写"
        : task.status === "transcribing"
          ? "正在转写中"
          : task.status === "starting"
            ? "正在准备压缩和上传对象存储"
            : "";
      return `
        <article class="task">
          <div class="task-top">
            <div>
              <h3>${escapeHtml(task.title)}</h3>
            <div class="muted">${escapeHtml(task.source_name)} · ${escapeHtml(task.created_at)}</div>
          </div>
          <div class="status-chip">${escapeHtml(task.status)} · ${task.points_cost} 点</div>
          </div>
          <div class="muted">时长 ${Number(task.duration_seconds || 0).toFixed(1)} 秒 · 计费 ${escapeHtml(task.charge_basis || "")}</div>
          ${startHint ? `<div class="muted">${escapeHtml(startHint)}</div>` : ""}
          ${task.error ? `<div class="warn">${escapeHtml(task.error)}</div>` : ""}
          <div>
            <div class="muted">原始转写</div>
            <div class="transcript">${escapeHtml(transcript)}</div>
          </div>
          <div>
            <div class="muted">校对文本</div>
            <textarea id="correction-${escapeHtml(task.id)}" ${canEdit ? "" : "disabled"}>${escapeHtml(corrected)}</textarea>
          </div>
          <div class="toolbar">
            ${canStart ? `<button onclick="startTask('${escapeJs(task.id)}')">确认扣点并开始转写</button>` : ""}
            ${canEdit ? `<button class="secondary" onclick="saveCorrection('${escapeJs(task.id)}')">保存校对</button>` : ""}
            ${canConfirmResult ? `<button onclick="confirmTask('${escapeJs(task.id)}')">确认最终转写</button>` : ""}
            <button class="ghost" onclick="reloadTask('${escapeJs(task.id)}')">刷新该任务</button>
          </div>
        </article>
      `;
    }

    async function createUser() {
      const name = window.prompt("输入用户名");
      if (!name) return;
      await fetchJson("/site/users", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name})
      });
      await refreshAll();
    }

    async function submitTask(event) {
      event.preventDefault();
      if (!currentUserId) {
        alert("请先创建或选择用户。");
        return;
      }
      const fileInput = document.getElementById("taskFile");
      if (!fileInput.files.length) {
        alert("请选择文件。");
        return;
      }
      const button = document.getElementById("submitButton");
      const status = document.getElementById("submitStatus");
      const form = new FormData();
      form.append("file", fileInput.files[0]);
      button.disabled = true;
      status.textContent = "正在上传到服务器并读取时长...";
      try {
        const data = await fetchJson(`/site/users/${currentUserId}/tasks`, {method: "POST", body: form});
        status.textContent = `上传成功，task=${data.task.id}，请确认扣除 ${data.task.points_cost} 点后开始转写`;
        document.getElementById("submitForm").reset();
        await refreshAll();
      } catch (error) {
        status.textContent = `提交失败：${error.message}`;
      } finally {
        button.disabled = false;
      }
    }

    async function saveCorrection(taskId) {
      const value = document.getElementById(`correction-${taskId}`).value;
      await fetchJson(`/site/tasks/${taskId}/correction`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({corrected_text: value})
      });
      await reloadTask(taskId);
    }

    async function startTask(taskId) {
      await fetchJson(`/site/tasks/${taskId}/start`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({confirm_points: true})
      });
      await refreshAll();
    }

    async function confirmTask(taskId) {
      const value = document.getElementById(`correction-${taskId}`).value;
      await fetchJson(`/site/tasks/${taskId}/confirm`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({corrected_text: value})
      });
      await reloadTask(taskId);
    }

    async function reloadTask(taskId) {
      const data = await fetchJson(`/site/tasks/${taskId}`);
      currentTasks = currentTasks.map((task) => task.id === taskId ? data.task : task);
      renderTasks();
      await loadUsers();
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function escapeJs(value) {
      return String(value ?? "").replaceAll("\\\\", "\\\\\\\\").replaceAll("'", "\\\\'");
    }

    refreshAll();
    window.setInterval(() => {
      if (currentUserId) {
        refreshAll().catch(() => {});
      }
    }, 5000);
  </script>
</body>
</html>
"""


ADMIN_SITE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ASR 管理端</title>
  <style>
    :root {
      font-family: "SF Pro SC", "PingFang SC", sans-serif;
      color-scheme: light;
      --bg: #f3f5f7;
      --card: #fff;
      --line: #d9e0e7;
      --text: #1f2937;
      --muted: #64748b;
      --brand: #0f4c81;
      --accent: #c9692c;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: linear-gradient(180deg, #eef4fb, var(--bg)); color: var(--text); }
    header, main { width: min(1180px, calc(100vw - 32px)); margin: 0 auto; }
    header { padding: 28px 0 10px; display: grid; gap: 12px; }
    .nav { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    .nav a { color: var(--muted); text-decoration: none; }
    .hero { background: var(--card); border: 1px solid var(--line); border-radius: 24px; padding: 22px; }
    main { padding: 10px 0 40px; display: grid; gap: 16px; }
    .grid { display: grid; grid-template-columns: 0.9fr 1.1fr; gap: 16px; }
    .card { background: var(--card); border: 1px solid var(--line); border-radius: 22px; padding: 18px; box-shadow: 0 16px 40px rgba(15, 23, 42, 0.06); }
    .metrics { display: flex; gap: 12px; flex-wrap: wrap; }
    .metric { min-width: 130px; border: 1px solid var(--line); border-radius: 16px; padding: 12px 14px; }
    .metric strong { display: block; font-size: 24px; }
    .muted { color: var(--muted); font-size: 13px; }
    input, select, button { font: inherit; border-radius: 14px; padding: 10px 12px; border: 1px solid var(--line); }
    input, select { width: 100%; background: #fff; }
    button { background: var(--brand); color: #fff; border: none; cursor: pointer; }
    button.secondary { background: var(--accent); }
    .toolbar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    .list { display: grid; gap: 10px; }
    .item { border: 1px solid var(--line); border-radius: 16px; padding: 12px; background: #fbfdff; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { border-bottom: 1px solid var(--line); text-align: left; padding: 10px 8px; vertical-align: top; }
    .small { font-size: 12px; color: var(--muted); }
    @media (max-width: 920px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <div class="nav">
      <div><strong>ASR 管理端</strong></div>
      <div class="toolbar">
        <a href="/">用户端</a>
        <a href="/agreement" target="_blank">用户协议</a>
      </div>
    </div>
    <div class="hero">
      <h1 style="margin:0 0 8px;">看用户、充点数、查任务、看 7 天清理前的状态</h1>
      <div class="muted">这是最小管理端，没有复杂权限系统。当前主要服务于内部运营和人工校对流程。</div>
    </div>
  </header>
  <main>
    <section class="card">
      <div class="metrics" id="metrics"></div>
    </section>
    <section class="grid">
      <div class="card">
        <h2 style="margin:0 0 12px;">用户与点数</h2>
        <div class="toolbar" style="margin-bottom:12px;">
          <input id="newUserName" placeholder="新用户名" />
          <button onclick="createUser()">创建用户</button>
        </div>
        <div class="toolbar" style="margin-bottom:14px;">
          <select id="rechargeUser"></select>
          <input id="rechargePoints" type="number" min="1" step="1" placeholder="充值点数" />
          <button class="secondary" onclick="recharge()">充值</button>
        </div>
        <div id="userList" class="list"></div>
      </div>
      <div class="card">
        <h2 style="margin:0 0 12px;">任务列表</h2>
        <div id="taskTableWrap" class="muted">正在加载...</div>
      </div>
    </section>
  </main>
  <script>
    async function fetchJson(url, options) {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || JSON.stringify(data));
      }
      return data;
    }

    async function refreshAdmin() {
      const dashboard = await fetchJson("/site/admin/dashboard");
      renderAdmin(dashboard);
    }

    function renderAdmin(data) {
      const metrics = document.getElementById("metrics");
      metrics.innerHTML = [
        metric("用户数", data.users.length),
        metric("任务数", data.tasks.length),
        metric("待处理", data.tasks.filter(task => ["uploaded", "starting", "queued", "transcribing"].includes(task.status)).length),
        metric("总点数", data.users.reduce((sum, user) => sum + Number(user.points_balance || 0), 0)),
      ].join("");

      const rechargeUser = document.getElementById("rechargeUser");
      rechargeUser.innerHTML = (data.users || []).map((user) =>
        `<option value="${escapeHtml(user.id)}">${escapeHtml(user.name)} · ${user.points_balance} 点</option>`
      ).join("");

      document.getElementById("userList").innerHTML = (data.users || []).map((user) => `
        <div class="item">
          <strong>${escapeHtml(user.name)}</strong>
          <div class="small">id: ${escapeHtml(user.id)} · role: ${escapeHtml(user.role)} · balance: ${user.points_balance}</div>
        </div>
      `).join("") || '<div class="muted">暂无用户</div>';

      const tasks = data.tasks || [];
      if (!tasks.length) {
        document.getElementById("taskTableWrap").innerHTML = '<div class="muted">暂无任务</div>';
        return;
      }
      document.getElementById("taskTableWrap").innerHTML = `
        <table>
          <thead>
            <tr>
              <th>标题</th>
              <th>用户</th>
              <th>状态</th>
              <th>点数</th>
              <th>文件</th>
              <th>创建时间</th>
            </tr>
          </thead>
          <tbody>
            ${tasks.map((task) => `
              <tr>
                <td>${escapeHtml(task.title)}</td>
                <td>${escapeHtml(findUserName(data.users, task.user_id))}</td>
                <td>${escapeHtml(task.status)}</td>
                <td>${task.points_cost}</td>
                <td>${escapeHtml(task.source_name)}</td>
                <td>${escapeHtml(task.created_at)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
    }

    function findUserName(users, userId) {
      const user = (users || []).find((item) => item.id === userId);
      return user ? user.name : userId;
    }

    function metric(label, value) {
      return `<div class="metric"><strong>${value}</strong><span class="muted">${label}</span></div>`;
    }

    async function createUser() {
      const name = document.getElementById("newUserName").value.trim();
      if (!name) return;
      await fetchJson("/site/users", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name})
      });
      document.getElementById("newUserName").value = "";
      await refreshAdmin();
    }

    async function recharge() {
      const userId = document.getElementById("rechargeUser").value;
      const points = Number(document.getElementById("rechargePoints").value || 0);
      if (!userId || points <= 0) return;
      await fetchJson(`/site/users/${userId}/recharge`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({points, note: "管理端充值"})
      });
      document.getElementById("rechargePoints").value = "";
      await refreshAdmin();
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    refreshAdmin();
  </script>
</body>
</html>
"""


AGREEMENT_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>RecordFlow 用户协议与隐私说明</title>
  <style>
    body { margin: 0; font-family: "SF Pro SC", "PingFang SC", sans-serif; background: #f4f7f6; color: #10201d; }
    main { width: min(900px, calc(100vw - 32px)); margin: 24px auto 40px; background: #fff; border: 1px solid #e3ebe8; border-radius: 20px; padding: 26px; line-height: 1.8; }
    h1 { margin: 0; }
    h2 { margin: 28px 0 8px; font-size: 19px; }
    p, li { color: #52635f; }
    .meta { color: #71817c; font-size: 14px; }
  </style>
</head>
<body>
  <main>
    <h1>RecordFlow 用户协议与隐私说明</h1>
    <p class="meta">版本：v2　更新日期：2026年7月11日　生效日期：2026年7月11日</p>
    <p>欢迎使用 RecordFlow。请在注册、登录或上传文件前认真阅读本协议。勾选同意或继续使用服务，表示你已理解并接受本协议。</p>

    <h2>1. 服务内容</h2>
    <p>RecordFlow 提供音频上传、自动语音转写、逐句回听、文本校对和文件导出等功能。具体能力、支持格式和额度以页面实际展示为准。</p>

    <h2>2. 账号与安全</h2>
    <p>你应妥善保管微信账号及登录状态，不得转让、出租账号或利用服务从事违法活动。发现异常使用时，应及时停止使用并联系服务提供方。</p>

    <h2>3. 上传内容与授权</h2>
    <p>你确认对上传内容具有合法处理权限，并已取得录音参与者或相关权利人的必要授权。不得上传违法违规、侵犯隐私、著作权、商业秘密或其他合法权益的内容。</p>

    <h2>4. 点数与支付</h2>
    <p>系统会根据音频时长预估所需点数，并在你明确确认后扣除。充值金额、点数比例和实际扣除以确认页面及支付结果为准。支付异常时请勿重复操作，可先刷新账户状态。</p>

    <h2>5. 自动转写结果</h2>
    <p>自动转写可能受口音、噪声、多人重叠、专业词汇及模型能力影响而产生遗漏或错误。结果仅作为辅助信息，重要用途应由你自行校对和确认。</p>

    <h2>6. 我们处理的数据</h2>
    <p>为提供服务，我们可能处理：微信登录产生的账号标识和你主动填写的昵称；文件名、大小、时长、任务状态等任务数据；你主动上传的录音及其转写、校对和导出内容；充值点数、订单号和支付状态等必要交易信息；以及用于安全、故障排查和性能分析的请求时间、网络地址、设备与操作日志。我们不会要求你提供与转写服务无关的信息。</p>

    <h2>7. 数据使用目的</h2>
    <p>上述数据仅用于账号登录与同步、完成上传和转写、播放与导出、计费和支付确认、处理投诉与故障、保障系统安全以及改进服务质量。未经另行明确同意，我们不会将你的录音或转写内容用于与本服务无关的营销。</p>

    <h2>8. 敏感信息与上传授权</h2>
    <p>录音、声音特征及其中可能出现的身份、健康、工作或商业信息可能属于敏感个人信息。上传前，你应确认已获得录音参与者和相关权利人的合法授权，并仅上传实现转写目的所必要的内容。请勿上传身份证件、银行卡、密码等不必要的高风险信息。</p>

    <h2>9. 第三方服务</h2>
    <p>完成服务可能需要调用微信登录与支付、云对象存储、网络分发及语音识别供应商。这些服务方仅在完成登录、支付、存储、传输和转写所必需的范围内处理数据，并受其自身服务条款和隐私规则约束。具体供应商和部署区域以实际运行环境为准。</p>

    <h2>10. 保存期限与安全措施</h2>
    <p>上传文件和任务结果默认保留不超过 7 天，临时上传文件通常在 1 天内清理；支付、协议同意和必要安全日志会根据交易核验、争议处理及法律要求保留合理期限。我们采取访问控制、身份校验、传输保护、短时授权链接、最小权限和操作审计等措施降低数据风险，但互联网服务无法保证绝对安全。</p>

    <h2>11. 你的数据权利</h2>
    <p>你可以查看任务和账户信息，更正昵称或转写文本，删除任务，并可通过运营方公布的联系方式申请查询、更正、复制或删除相关数据。你可以停止使用服务或撤回后续处理同意，但撤回不影响此前基于同意完成的处理，也不影响依法必须保存的交易与安全记录。</p>

    <h2>12. 数据删除</h2>
    <p>你可以在任务详情中删除任务。系统会按服务能力清理相关任务数据和存储文件；正在处理中的任务可能需要在处理结束或取消完成后执行清理。缓存、备份和安全审计记录将在合理周期内自然过期。</p>

    <h2>13. 未成年人保护</h2>
    <p>若你是未成年人，应在监护人阅读并同意本协议后使用服务。监护人应指导未成年人避免上传包含本人或他人敏感信息的录音。</p>

    <h2>14. 服务变更与中断</h2>
    <p>因系统维护、网络、第三方语音识别服务、对象存储或不可抗力，服务可能暂时中断。我们会在合理范围内恢复服务，但不承诺服务始终无错误或不中断。</p>

    <h2>15. 禁止行为</h2>
    <ul>
      <li>绕过访问控制、批量攻击、探测漏洞或干扰系统运行；</li>
      <li>上传恶意文件，冒用他人身份或侵犯第三方权益；</li>
      <li>利用转写结果实施违法、欺诈、骚扰或其他不当行为。</li>
    </ul>

    <h2>16. 协议更新</h2>
    <p>协议发生重要更新时，我们会更新版本并在产品内提示。继续使用前，可能需要你重新确认最新版本。</p>

    <h2>17. 联系方式</h2>
    <p>如对本协议、隐私处理、数据权利或服务有疑问，请联系服务提供方，客服邮箱：1375626371@qq.com。如需行使个人信息相关权利，请在邮件中说明请求事项，我们将在核验身份后依法处理。</p>

    <h2>18. 运营主体与协议解释</h2>
    <p>本协议由服务提供方负责说明与解释；法律法规或有权机关另有规定的，从其规定。</p>
  </main>
</body>
</html>
"""
