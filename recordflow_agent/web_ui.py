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
  <title>用户协议</title>
  <style>
    body { margin: 0; font-family: "SF Pro SC", "PingFang SC", sans-serif; background: #f8f7f3; color: #24211c; }
    main { width: min(900px, calc(100vw - 32px)); margin: 24px auto 40px; background: #fff; border: 1px solid #e7dfd2; border-radius: 20px; padding: 26px; line-height: 1.8; }
    h1, h2 { margin-top: 0; }
  </style>
</head>
<body>
  <main>
    <h1>ASR 网站用户协议</h1>
    <p>本最小站点仅用于内部或受控场景的音频转写与人工校对。你在提交任务前，需要确认自己对上传音频拥有合法处理权限。</p>
    <h2>1. 上传内容</h2>
    <p>你承诺上传内容不违反法律法规，不侵犯第三方隐私、著作权或其他合法权益。</p>
    <h2>2. 点数消耗</h2>
    <p>每次提交任务会按录音时长或文件大小估算消耗点数。点数在任务创建时扣减。</p>
    <h2>3. 数据保留</h2>
    <p>最小版本默认将上传文件和结果保留 7 天。到期后会由后台调度任务触发清理。</p>
    <h2>4. 结果责任</h2>
    <p>自动转写结果可能存在误差，用户需要自行校对并确认最终文本。</p>
  </main>
</body>
</html>
"""
