from __future__ import annotations


MOBILE_UPLOAD_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>上传手机文件</title>
  <style>
    :root { font-family: "PingFang SC", "Helvetica Neue", sans-serif; color: #10201d; background: #f4f7f6; }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 20px 16px calc(32px + env(safe-area-inset-bottom)); }
    main { width: min(620px, 100%); margin: 0 auto; }
    h1 { margin: 8px 0 6px; font-size: 25px; letter-spacing: 0; }
    .subtitle { margin: 0 0 22px; color: #71817c; font-size: 14px; line-height: 1.6; }
    .picker { display: block; width: 100%; padding: 30px 20px; border: 1px dashed #7db8a9; border-radius: 8px; background: #fff; text-align: center; cursor: pointer; }
    .picker strong { display: block; color: #08705d; font-size: 17px; }
    .picker span { display: block; margin-top: 8px; color: #71817c; font-size: 13px; }
    input[type=file] { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
    .list { display: grid; gap: 10px; margin-top: 18px; }
    .summary { min-height: 22px; margin-top: 14px; color: #08705d; font-size: 14px; font-weight: 600; }
    .summary.error { color: #b42318; }
    .item { padding: 15px; border: 1px solid #e1e9e6; border-radius: 8px; background: #fff; }
    .row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .name { min-width: 0; overflow: hidden; font-size: 14px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
    .status { flex: 0 0 auto; color: #71817c; font-size: 12px; }
    .status.success { color: #067647; }.status.error { color: #b42318; }
    .track { height: 5px; margin-top: 12px; overflow: hidden; border-radius: 3px; background: #e3ebe8; }
    .bar { width: 0; height: 100%; background: #08705d; transition: width .15s ease; }
    .error-text { margin-top: 8px; color: #b42318; font-size: 12px; line-height: 1.5; }
    button { width: 100%; min-height: 46px; margin-top: 16px; border-radius: 8px; background: #fff; color: #08705d; border: 1px solid #08705d; font: inherit; font-weight: 650; }
    #confirm { display: none; }
    .notice { margin-top: 16px; color: #71817c; font-size: 12px; line-height: 1.6; }
  </style>
</head>
<body>
  <main>
    <h1>上传手机文件</h1>
    <p class="subtitle">从系统文件选择器添加音频或视频，上传后会生成待确认的转写任务。</p>
    <label class="picker" for="files"><strong>选择文件</strong><span>支持 MP3、M4A、WAV、MP4、MOV 等，最多 9 个</span></label>
    <input id="files" type="file" accept="audio/*,video/mp4,video/quicktime,video/webm,.mp3,.m4a,.wav,.aac,.flac,.ogg,.opus,.webm,.mp4,.mov,.m4v" multiple />
    <div id="summary" class="summary"></div>
    <div id="list" class="list"></div>
    <button id="confirm" type="button">返回确认任务</button>
    <p class="notice">单个文件不能超过 200MB。上传期间请保持页面开启。</p>
  </main>
  <script src="https://res.wx.qq.com/open/js/jweixin-1.6.0.js"></script>
  <script>
    const MAX_FILES = 9;
    const MAX_BYTES = 200 * 1024 * 1024;
    const allowed = /\\.(aac|aif|aiff|flac|m4a|m4v|mov|mp3|mp4|oga|ogg|opus|pcm|wav|webm)$/i;
    const token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
    const input = document.getElementById('files');
    const list = document.getElementById('list');
    const summary = document.getElementById('summary');
    const confirm = document.getElementById('confirm');
    let files = [];
    let uploading = false;
    let uploadedTaskIds = [];

    input.addEventListener('change', async () => {
      files = Array.from(input.files || []).slice(0, MAX_FILES);
      render();
      if (!files.length) return;
      if (!token) {
        setSummary('登录状态已失效，请返回小程序重新进入', true);
        return;
      }
      setSummary(`已选择 ${files.length} 个文件，准备上传`);
      await nextPaint();
      startUploads();
    });

    async function startUploads() {
      if (uploading || !files.length || !token) return;
      uploading = true;
      uploadedTaskIds = [];
      confirm.style.display = 'none';
      input.disabled = true;
      let completed = 0;
      let failed = 0;
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        const validation = validate(file);
        if (validation) {
          failed += 1;
          setStatus(index, '不可上传', 0, validation, 'error');
          continue;
        }
        try {
          const result = await uploadFile(file, index);
          if (result && result.task && result.task.id) uploadedTaskIds.push(result.task.id);
          completed += 1;
          setStatus(index, '已上传', 100, '', 'success');
        } catch (error) {
          failed += 1;
          setStatus(index, '上传失败', 0, error.message || '上传失败', 'error');
        }
        setSummary(`上传进度：完成 ${completed} 个，失败 ${failed} 个`);
      }
      uploading = false;
      input.disabled = false;
      setSummary(failed ? `上传完成：成功 ${completed} 个，失败 ${failed} 个` : `上传成功，共 ${completed} 个文件`, failed > 0);
      if (uploadedTaskIds.length) confirm.style.display = 'block';
    }

    confirm.addEventListener('click', () => {
      if (!window.wx || !wx.miniProgram) {
        setSummary('请点击左上角返回小程序，在任务列表中确认任务', true);
        return;
      }
      if (uploadedTaskIds.length === 1) {
        wx.miniProgram.redirectTo({ url: `/pages/task/task?id=${encodeURIComponent(uploadedTaskIds[0])}` });
        return;
      }
      wx.miniProgram.switchTab({ url: '/pages/tasks/tasks' });
    });

    function validate(file) {
      if (!allowed.test(file.name || '')) return '不支持该文件格式';
      if (!file.size) return '文件内容为空';
      if (file.size > MAX_BYTES) return '文件不能超过 200MB';
      return '';
    }

    async function uploadFile(file, index) {
      setStatus(index, '准备上传', 0);
      const init = await apiRequest('/site/me/tasks/direct-upload/init', {
        method: 'POST',
        body: JSON.stringify({
          source_name: file.name,
          content_type: file.type || 'application/octet-stream',
          size_bytes: file.size
        })
      });
      try {
        await uploadToStorage(file, index, init.upload || {});
      } catch (error) {
        setStatus(index, '切换服务器上传', 0);
        return uploadThroughApi(file, index);
      }
      setStatus(index, '正在创建任务', 100);
      return completeUpload(init);
    }

    function uploadToStorage(file, index, target) {
      return new Promise((resolve, reject) => {
        const form = new FormData();
        Object.entries(target.form_data || {}).forEach(([key, value]) => form.append(key, value));
        form.append(target.file_field || 'file', file, file.name);
        const xhr = new XMLHttpRequest();
        xhr.open(target.method || 'POST', target.url);
        Object.entries(target.headers || {}).forEach(([key, value]) => xhr.setRequestHeader(key, value));
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) setStatus(index, '上传中', Math.round(event.loaded / event.total * 100));
        };
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) return resolve();
          reject(new Error(storageError(xhr.responseText) || `上传到存储失败：HTTP ${xhr.status}`));
        };
        xhr.onerror = () => reject(new Error('网络连接失败'));
        xhr.send(form);
      });
    }

    function uploadThroughApi(file, index) {
      return new Promise((resolve, reject) => {
        const form = new FormData();
        form.append('file', file, file.name);
        form.append('source_name', file.name);
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/site/me/tasks');
        xhr.setRequestHeader('Authorization', `Bearer ${token}`);
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) setStatus(index, '服务器上传中', Math.round(event.loaded / event.total * 100));
        };
        xhr.onload = () => {
          let data = {};
          try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) {}
          if (xhr.status >= 200 && xhr.status < 300) return resolve(data);
          reject(new Error(data.detail || `上传失败：HTTP ${xhr.status}`));
        };
        xhr.onerror = () => reject(new Error('网络连接失败'));
        xhr.send(form);
      });
    }

    async function completeUpload(init) {
      let lastError;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          return await apiRequest('/site/me/tasks/direct-upload/complete', {
            method: 'POST',
            body: JSON.stringify({
              upload_token: init.upload_token,
              object_key: init.upload && init.upload.object_key
            })
          });
        } catch (error) {
          lastError = error;
          if (error.status !== 409 || attempt === 2) throw error;
          await new Promise((resolve) => setTimeout(resolve, 800 * (attempt + 1)));
        }
      }
      throw lastError;
    }

    async function apiRequest(path, options) {
      const response = await fetch(path, {
        ...options,
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' }
      });
      let data = {};
      try { data = await response.json(); } catch (_) {}
      if (response.ok) return data;
      const error = new Error(data.detail || `请求失败：HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }

    function storageError(text) {
      const matched = String(text || '').match(/<Message>([^<]+)<[/]Message>/);
      return matched ? matched[1] : '';
    }

    function render() {
      list.innerHTML = '';
      files.forEach((file, index) => {
        const item = document.createElement('div');
        item.className = 'item';
        item.innerHTML = `<div class="row"><div class="name"></div><div class="status">等待上传</div></div><div class="track"><div class="bar"></div></div><div class="error-text"></div>`;
        item.querySelector('.name').textContent = `${file.name} · ${formatSize(file.size)}`;
        item.dataset.index = index;
        list.appendChild(item);
      });
    }

    function setStatus(index, text, progress, error = '', theme = '') {
      const item = list.querySelector(`[data-index="${index}"]`);
      if (!item) return;
      const status = item.querySelector('.status');
      status.textContent = text;
      status.className = `status ${theme}`;
      item.querySelector('.bar').style.width = `${progress}%`;
      item.querySelector('.error-text').textContent = error;
    }

    function setSummary(text, isError = false) {
      summary.textContent = text;
      summary.className = `summary${isError ? ' error' : ''}`;
    }

    function nextPaint() {
      return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }

    function formatSize(bytes) {
      if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
      return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    }
  </script>
</body>
</html>
"""
