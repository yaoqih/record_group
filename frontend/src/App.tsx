import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CircleDollarSign,
  Clock3,
  Download,
  FileAudio,
  FilePenLine,
  FileText,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserRoundPlus,
} from 'lucide-react'
import './App.css'
import { ProofreaderWorkspace, type SiteTask, type SiteTaskEditor } from './proofreader'

type SiteUser = {
  id: string
  name: string
  points_balance: number
}

type SiteUsersResponse = { users: SiteUser[] }
type SiteTasksResponse = { user: SiteUser; tasks: SiteTask[] }
type SiteTaskResponse = { task: SiteTask }
type SiteTaskEditorResponse = { task: SiteTask; editor: SiteTaskEditor }
type WorkspaceState = { task: SiteTask; editor: SiteTaskEditor; draftText: string }
type ExportFormat = 'srt' | 'text'
type UploadQueueItem = {
  id: string
  fileName: string
  sizeBytes: number
  progress: number
  status: 'queued' | 'uploading' | 'uploaded' | 'starting' | 'started' | 'failed'
  task: SiteTask | null
  error: string | null
}

const MAX_UPLOAD_FILES = 10
const MAX_UPLOAD_BYTES = 100 * 1024 * 1024

export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const responseText = await response.text()
  const data = parseJsonIfPossible(responseText, response.headers.get('Content-Type') || '') || {}
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : ''
    const message = typeof data.message === 'string' ? data.message : ''
    const fallback = normalizeUploadResponseText(responseText)
    throw new Error(detail || message || fallback || `请求失败：HTTP ${response.status}`)
  }
  return data as T
}

function normalizeUploadResponseText(value: string): string {
  return value
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function parseJsonIfPossible(value: string, contentType?: string): Record<string, unknown> | null {
  const trimmed = value.trim()
  const looksLikeJson = contentType?.includes('application/json') || trimmed.startsWith('{') || trimmed.startsWith('[')
  if (!looksLikeJson || !trimmed) return null
  try {
    const parsed = JSON.parse(trimmed)
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null
  } catch {
    return null
  }
}

function uploadErrorMessage(status: number, statusText: string, responseText: string, contentType?: string): string {
  const parsed = parseJsonIfPossible(responseText, contentType)
  const jsonMessage =
    (typeof parsed?.detail === 'string' && parsed.detail) ||
    (typeof parsed?.message === 'string' && parsed.message) ||
    ''
  if (jsonMessage) return jsonMessage
  const plainText = normalizeUploadResponseText(responseText)
  if (plainText) return plainText.slice(0, 160)
  if (statusText) return `上传失败：${status} ${statusText}`
  return `上传失败：HTTP ${status}`
}

export function parseUploadTaskResponse(
  status: number,
  statusText: string,
  responseText: string,
  contentType?: string,
): SiteTask {
  const parsed = parseJsonIfPossible(responseText, contentType)
  if (status < 200 || status >= 300) {
    throw new Error(uploadErrorMessage(status, statusText, responseText, contentType))
  }
  const task = parsed?.task
  if (task && typeof task === 'object') {
    return task as SiteTask
  }
  const plainText = normalizeUploadResponseText(responseText)
  throw new Error(plainText ? `上传成功但返回格式不正确：${plainText.slice(0, 120)}` : '上传成功但服务端未返回任务数据')
}

export function normalizeTaskTitleInput(value: string): string {
  return value.trim()
}

export function taskExportUrl(taskId: string, format: ExportFormat): string {
  return `/site/tasks/${encodeURIComponent(taskId)}/export?format=${format}`
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const hh = Math.floor(total / 3600)
  const mm = Math.floor((total % 3600) / 60)
  const ss = total % 60
  if (hh > 0) {
    return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
  }
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

function taskHint(task: SiteTask): string {
  if (task.status === 'uploaded') return '等待确认转写'
  if (task.status === 'starting') return '正在压缩并上传对象存储'
  if (task.status === 'queued') return '已入队，等待 worker 处理'
  if (task.status === 'transcribing') return '正在转写中'
  if (task.status === 'completed') return '可开始逐句校对'
  if (task.status === 'confirmed') return '已确认最终文本'
  if (task.status === 'failed') return task.error || '任务失败'
  return task.status
}

function uploadStatusLabel(status: UploadQueueItem['status']): string {
  if (status === 'queued') return '等待上传'
  if (status === 'uploading') return '上传中'
  if (status === 'uploaded') return '待统一转写'
  if (status === 'starting') return '正在启动'
  if (status === 'started') return '已开始'
  if (status === 'failed') return '失败'
  return status
}

export function isTaskActive(task: SiteTask | null | undefined): boolean {
  if (!task) return false
  return ['uploaded', 'starting', 'queued', 'transcribing'].includes(task.status)
}

export function shouldLoadTaskWorkspace(task: SiteTask | null | undefined): boolean {
  if (!task) return false
  return ['uploaded', 'starting', 'queued', 'transcribing', 'completed', 'confirmed'].includes(task.status)
}

export function shouldPollSelectedTask(tasks: SiteTask[], selectedTaskId: string): SiteTask | null {
  if (!selectedTaskId) return null
  const selected = tasks.find((task) => task.id === selectedTaskId) || null
  return isTaskActive(selected) ? selected : null
}

export function resolveSelectedTask(tasks: SiteTask[], selectedTaskId: string): SiteTask | null {
  if (!selectedTaskId) return null
  return tasks.find((task) => task.id === selectedTaskId) || null
}

export function mergeTaskSummary(previous: SiteTask | undefined, incoming: SiteTask): SiteTask {
  if (!previous) return incoming
  return {
    ...previous,
    ...incoming,
    media: incoming.media ?? previous.media,
  }
}

function App() {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [users, setUsers] = useState<SiteUser[]>([])
  const [currentUserId, setCurrentUserId] = useState('')
  const [tasks, setTasks] = useState<SiteTask[]>([])
  const [workspaceByTaskId, setWorkspaceByTaskId] = useState<Record<string, WorkspaceState>>({})
  const [selectedTaskId, setSelectedTaskId] = useState('')
  const [statusText, setStatusText] = useState('准备就绪')
  const [loading, setLoading] = useState(false)
  const [workspaceLoading, setWorkspaceLoading] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const [uploadQueue, setUploadQueue] = useState<UploadQueueItem[]>([])
  const [editingTaskTitle, setEditingTaskTitle] = useState(false)
  const [taskTitleDraft, setTaskTitleDraft] = useState('')

  const currentUser = users.find((user) => user.id === currentUserId) || null
  const selectedTaskSummary = resolveSelectedTask(tasks, selectedTaskId)
  const selectedWorkspace = selectedTaskSummary ? workspaceByTaskId[selectedTaskSummary.id] || null : null
  const selectedTask = selectedWorkspace?.task || null
  const selectedEditor = selectedWorkspace?.editor || null
  const uploadedBatchTasks = useMemo(
    () => uploadQueue.filter((item) => item.status === 'uploaded' && item.task).map((item) => item.task as SiteTask),
    [uploadQueue],
  )
  const uploadedBatchPoints = uploadedBatchTasks.reduce((sum, task) => sum + task.points_cost, 0)
  const uploadedBatchDuration = uploadedBatchTasks.reduce((sum, task) => sum + task.duration_seconds, 0)
  const batchReadyToConfirm =
    uploadedBatchTasks.length > 0 &&
    uploadQueue.every((item) => item.status === 'uploaded' || item.status === 'started' || item.status === 'failed')

  useEffect(() => {
    void loadUsers()
  }, [])

  useEffect(() => {
    if (!currentUserId && users[0]) {
      setCurrentUserId(users[0].id)
    }
  }, [users, currentUserId])

  useEffect(() => {
    if (!currentUserId) return
    void loadTasks(currentUserId)
  }, [currentUserId])

  useEffect(() => {
    if (!selectedTaskId) return
    const selectedSummary = tasks.find((task) => task.id === selectedTaskId) || null
    if (!selectedSummary) return
    if (shouldLoadTaskWorkspace(selectedSummary)) {
      void loadTaskWorkspace(selectedTaskId)
    }
  }, [selectedTaskId])

  useEffect(() => {
    if (selectedTaskId && !tasks.find((task) => task.id === selectedTaskId)) {
      setSelectedTaskId('')
    }
  }, [tasks, selectedTaskId])

  useEffect(() => {
    const activeTask = shouldPollSelectedTask(tasks, selectedTaskId)
    if (!activeTask) return
    const timer = window.setInterval(() => {
      void loadTaskWorkspace(activeTask.id)
    }, 5000)
    return () => window.clearInterval(timer)
  }, [selectedTaskId, tasks])

  useEffect(() => {
    if (!editingTaskTitle && selectedTask) {
      setTaskTitleDraft(selectedTask.source_name)
    }
  }, [selectedTask, editingTaskTitle])

  async function loadUsers() {
    const data = await requestJson<SiteUsersResponse>('/site/users')
    setUsers(data.users || [])
  }

  async function loadTasks(userId: string) {
    const data = await requestJson<SiteTasksResponse>(`/site/users/${userId}/tasks`)
    setTasks((previous) => {
      const previousMap = new Map(previous.map((task) => [task.id, task]))
      return (data.tasks || []).map((task) => mergeTaskSummary(previousMap.get(task.id), task))
    })
  }

  async function refreshTask(taskId: string) {
    const data = await requestJson<SiteTaskResponse>(`/site/tasks/${taskId}`)
    setTasks((previous) => {
      const next = previous.map((task) => (task.id === taskId ? data.task : task))
      return next.some((task) => task.id === taskId) ? next : [data.task, ...next]
    })
  }

  async function loadTaskWorkspace(taskId: string) {
    setWorkspaceLoading(true)
    try {
      const data = await requestJson<SiteTaskEditorResponse>(`/site/tasks/${taskId}/editor`)
      setTasks((previous) => {
        const next = previous.map((task) => (task.id === taskId ? mergeTaskSummary(task, data.task) : task))
        return next.some((task) => task.id === taskId) ? next : [data.task, ...next]
      })
      setWorkspaceByTaskId((previous) => {
        const current = previous[taskId]
        return {
          ...previous,
          [taskId]: {
            task: data.task,
            editor: data.editor,
            draftText: current?.draftText ?? data.editor.utterances.map((item) => item.text).join('\n'),
          },
        }
      })
    } finally {
      setWorkspaceLoading(false)
    }
  }

  async function refreshSelectedTaskWorkspace(taskId: string) {
    await refreshTask(taskId)
    await loadTaskWorkspace(taskId)
  }

  async function createUser() {
    const name = window.prompt('输入用户名')
    if (!name) return
    await requestJson<{ user: SiteUser }>('/site/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    await loadUsers()
  }

  async function rechargePoints() {
    if (!currentUserId) return
    const raw = window.prompt('充值点数')
    if (!raw) return
    const points = Number(raw)
    if (!Number.isFinite(points) || points <= 0) {
      window.alert('请输入大于 0 的整数')
      return
    }
    await requestJson(`/site/users/${currentUserId}/recharge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ points: Math.ceil(points), note: 'frontend recharge' }),
    })
    await loadUsers()
  }

  function patchQueueItem(id: string, updater: (current: UploadQueueItem) => UploadQueueItem) {
    setUploadQueue((previous) => previous.map((item) => (item.id === id ? updater(item) : item)))
  }

  function buildQueueItem(file: File): UploadQueueItem {
    return {
      id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
      fileName: file.name,
      sizeBytes: file.size,
      progress: 0,
      status: 'queued',
      task: null,
      error: null,
    }
  }

  function validateFiles(files: File[]): File[] {
    const accepted: File[] = []
    for (const file of files) {
      if (accepted.length >= MAX_UPLOAD_FILES) break
      if (file.size > MAX_UPLOAD_BYTES) {
        setStatusText(`${file.name} 超过 100MB，已跳过`)
        continue
      }
      accepted.push(file)
    }
    return accepted
  }

  async function uploadTaskFile(userId: string, queueId: string, file: File): Promise<SiteTask> {
    return await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      const form = new FormData()
      form.append('file', file)
      xhr.open('POST', `/site/users/${userId}/tasks`)
      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) return
        const progress = Math.min(100, Math.round((event.loaded / event.total) * 100))
        patchQueueItem(queueId, (current) => ({ ...current, progress }))
      }
      xhr.onerror = () => reject(new Error('上传失败'))
      xhr.onload = () => {
        try {
          resolve(
            parseUploadTaskResponse(
              xhr.status,
              xhr.statusText,
              xhr.responseText || '',
              xhr.getResponseHeader('Content-Type') || '',
            ),
          )
        } catch (error) {
          reject(error instanceof Error ? error : new Error('上传失败'))
        }
      }
      xhr.send(form)
    })
  }

  async function enqueueFiles(files: File[]) {
    if (!currentUserId) {
      window.alert('请先选择用户')
      return
    }
    const accepted = validateFiles(files).slice(0, MAX_UPLOAD_FILES)
    if (accepted.length === 0) return

    const nextItems = accepted.map(buildQueueItem)
    setUploadQueue(nextItems)
    setLoading(true)
    setStatusText('正在批量上传并读取时长...')

    for (const [index, file] of accepted.entries()) {
      const queueId = nextItems[index].id
      patchQueueItem(queueId, (current) => ({ ...current, status: 'uploading', progress: 0, error: null }))
      try {
        const task = await uploadTaskFile(currentUserId, queueId, file)
        patchQueueItem(queueId, (current) => ({
          ...current,
          status: 'uploaded',
          progress: 100,
          task,
          error: null,
        }))
      } catch (error) {
        patchQueueItem(queueId, (current) => ({
          ...current,
          status: 'failed',
          error: error instanceof Error ? error.message : '上传失败',
        }))
      }
    }

    await loadTasks(currentUserId)
    await loadUsers()
    setStatusText('上传完成，请确认转写本批次任务')
    setLoading(false)
  }

  async function confirmUploadedBatch() {
    if (!currentUserId || uploadedBatchTasks.length === 0) return
    if ((currentUser?.points_balance || 0) < uploadedBatchPoints) {
      window.alert(`点数不足，当前剩余 ${currentUser?.points_balance || 0} 点，本批次需要 ${uploadedBatchPoints} 点`)
      return
    }
    setLoading(true)
    setStatusText(`正在确认 ${uploadedBatchTasks.length} 个任务开始转写...`)
    for (const item of uploadQueue) {
      if (item.status !== 'uploaded' || !item.task) continue
      patchQueueItem(item.id, (current) => ({ ...current, status: 'starting' }))
      try {
        await requestJson(`/site/tasks/${item.task.id}/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirm_points: true }),
        })
        patchQueueItem(item.id, (current) => ({ ...current, status: 'started' }))
      } catch (error) {
        patchQueueItem(item.id, (current) => ({
          ...current,
          status: 'failed',
          error: error instanceof Error ? error.message : '确认失败',
        }))
      }
    }
    await loadTasks(currentUserId)
    await loadUsers()
    setStatusText('本批次已开始转写')
    setLoading(false)
  }

  async function startTask(taskId: string) {
    await requestJson(`/site/tasks/${taskId}/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm_points: true }),
    })
    setSelectedTaskId(taskId)
    await loadTaskWorkspace(taskId)
    if (currentUserId) {
      await loadTasks(currentUserId)
    }
    await loadUsers()
  }

  async function deleteTask(taskId: string) {
    if (!window.confirm('确认删除这个任务吗？')) return
    await requestJson(`/site/tasks/${taskId}`, { method: 'DELETE' })
    setTasks((previous) => previous.filter((task) => task.id !== taskId))
    setWorkspaceByTaskId((previous) => {
      const next = { ...previous }
      delete next[taskId]
      return next
    })
    if (selectedTaskId === taskId) {
      setSelectedTaskId('')
    }
    if (currentUserId) {
      await loadTasks(currentUserId)
      await loadUsers()
    }
    setStatusText('任务已删除')
  }

  async function renameTask(taskId: string, value: string) {
    const nextTitle = normalizeTaskTitleInput(value)
    if (!nextTitle) {
      setTaskTitleDraft(selectedTask?.source_name || '')
      setEditingTaskTitle(false)
      return
    }
    const data = await requestJson<SiteTaskResponse>(`/site/tasks/${taskId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: nextTitle }),
    })
    setTasks((previous) => previous.map((task) => (task.id === taskId ? mergeTaskSummary(task, data.task) : task)))
    setWorkspaceByTaskId((previous) => {
      const current = previous[taskId]
      if (!current) return previous
      return {
        ...previous,
        [taskId]: {
          ...current,
          task: {
            ...current.task,
            ...data.task,
          },
        },
      }
    })
    setEditingTaskTitle(false)
  }

  function downloadTaskExport(taskId: string, format: ExportFormat) {
    window.location.href = taskExportUrl(taskId, format)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="panel hero-panel">
          <div className="eyebrow">RecordFlow ASR Workspace</div>
          <h1>前后端分离版音频校对台</h1>
          <p>
            React 前端负责任务工作台，Python 后端继续负责上传、压缩、对象存储、队列、ASR 和清理。
          </p>
        </div>

        <div className="panel">
          <div className="section-head">
            <div>
              <h2>用户与点数</h2>
              <p>选择用户、充值、提交任务。</p>
            </div>
            <button className="ghost-button icon-button" onClick={() => currentUserId && void loadTasks(currentUserId)}>
              <RefreshCw size={16} />
            </button>
          </div>
          <div className="stack">
            <select value={currentUserId} onChange={(event) => setCurrentUserId(event.target.value)}>
              {users.length === 0 ? <option value="">请先创建用户</option> : null}
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.name} · {user.points_balance} 点
                </option>
              ))}
            </select>
            <div className="button-row">
              <button type="button" onClick={createUser}>
                <UserRoundPlus size={16} />
                新建用户
              </button>
              <button type="button" className="secondary-button" onClick={rechargePoints} disabled={!currentUser}>
                <CircleDollarSign size={16} />
                充值
              </button>
            </div>
            <div className="stats-grid">
              <div className="stat-card">
                <span>剩余点数</span>
                <strong>{currentUser?.points_balance ?? 0}</strong>
              </div>
              <div className="stat-card">
                <span>任务数量</span>
                <strong>{tasks.length}</strong>
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="section-head">
            <div>
              <h2>提交任务</h2>
              <p>上传到服务器，直接使用文件名建任务，服务端读取时长并计算点数。</p>
            </div>
          </div>
          <div className="stack">
            <input
              ref={fileInputRef}
              name="file"
              type="file"
              accept="audio/*,video/*"
              multiple
              className="sr-file-input"
              onChange={(event) => {
                const files = Array.from(event.target.files || [])
                void enqueueFiles(files)
                event.currentTarget.value = ''
              }}
            />
            <button
              type="button"
              className={`upload-dropzone ${dragActive ? 'drag-active' : ''}`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(event) => {
                event.preventDefault()
                setDragActive(true)
              }}
              onDragLeave={(event) => {
                event.preventDefault()
                setDragActive(false)
              }}
              onDrop={(event) => {
                event.preventDefault()
                setDragActive(false)
                const files = Array.from(event.dataTransfer.files || [])
                void enqueueFiles(files)
              }}
            >
              <FileAudio size={20} />
              <span>拖动文件到这里，或点击上传文件</span>
              <small>单文件最多 100MB，单次最多 10 个，上传完成后自动返回时长和扣点</small>
            </button>
            <button type="button" className="ghost-button" disabled={loading || !currentUser} onClick={() => fileInputRef.current?.click()}>
              {loading ? <LoaderCircle size={16} className="spin" /> : <FileAudio size={16} />}
              从本地选择文件
            </button>
            {uploadQueue.length > 0 ? (
              <div className="upload-queue">
                <div className="upload-summary">
                  <div className="upload-summary-card">
                    <span>本批次</span>
                    <strong>{uploadQueue.length} 个文件</strong>
                  </div>
                  <div className="upload-summary-card">
                    <span>已创建任务</span>
                    <strong>{uploadedBatchTasks.length} 个</strong>
                  </div>
                  <div className="upload-summary-card">
                    <span>总时长</span>
                    <strong>{formatDuration(uploadedBatchDuration)}</strong>
                  </div>
                  <div className="upload-summary-card">
                    <span>总点数</span>
                    <strong>{uploadedBatchPoints} 点</strong>
                  </div>
                </div>
                <div className="upload-items">
                  {uploadQueue.map((item) => (
                    <div key={item.id} className={`upload-item upload-${item.status}`}>
                      <div className="upload-item-head">
                        <strong>{item.fileName}</strong>
                        <span className="upload-item-size">{formatBytes(item.sizeBytes)}</span>
                      </div>
                      <div className="upload-item-bar">
                        <div className="upload-item-progress" style={{ width: `${item.progress}%` }} />
                      </div>
                      <div className="upload-item-meta">
                        <span>{uploadStatusLabel(item.status)}</span>
                        <span>{item.task ? `${formatDuration(item.task.duration_seconds)} · ${item.task.points_cost} 点` : `${item.progress}%`}</span>
                      </div>
                      {item.error ? <div className="error-note">{item.error}</div> : null}
                    </div>
                  ))}
                </div>
                <button type="button" disabled={loading || !batchReadyToConfirm || uploadedBatchTasks.length === 0} onClick={() => void confirmUploadedBatch()}>
                  {loading ? <LoaderCircle size={16} className="spin" /> : <ShieldCheck size={16} />}
                  确认转写本批次 {uploadedBatchPoints} 点
                </button>
              </div>
            ) : null}
            <div className="inline-note">{statusText}</div>
          </div>
        </div>

        <div className="panel task-panel">
          <div className="section-head">
            <div>
              <h2>任务列表</h2>
              <p>直接从这里进到逐句校对。</p>
            </div>
          </div>
          <div className="task-list">
            {tasks.length === 0 ? <div className="empty-card">当前用户还没有任务。</div> : null}
            {tasks.map((task) => (
              <article
                key={task.id}
                className={`task-card ${selectedTask?.id === task.id ? 'selected' : ''}`}
              >
                <div className="task-card-top">
                  <strong title={task.source_name}>{task.source_name}</strong>
                  <span className={`status-chip status-${task.status}`}>{task.status}</span>
                </div>
                <div className="task-meta">
                  <span>
                    <Clock3 size={14} />
                    {formatDuration(task.duration_seconds)}
                  </span>
                  <span>
                    <CircleDollarSign size={14} />
                    {task.points_cost} 点
                  </span>
                </div>
                <div className="task-hint">{taskHint(task)}</div>
                <div className="task-card-actions">
                  <button type="button" className="ghost-button task-action-button" onClick={() => setSelectedTaskId(task.id)}>
                    <FilePenLine size={14} />
                    查看
                  </button>
                  {task.status === 'uploaded' ? (
                    <button type="button" className="task-action-button" onClick={() => void startTask(task.id)}>
                      <ShieldCheck size={14} />
                      确认转写
                    </button>
                  ) : null}
                  <button type="button" className="ghost-button task-action-button danger-button" onClick={() => void deleteTask(task.id)}>
                    <Trash2 size={14} />
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>
      </aside>

      <main className="workspace">
        {selectedTask ? (
          <>
            <section className="workspace-top">
              <div className="panel detail-panel">
                <div className="detail-header">
                  <div className="detail-heading-stack">
                    {editingTaskTitle ? (
                      <input
                        aria-label="编辑任务文件名"
                        className="task-title-input"
                        value={taskTitleDraft}
                        onChange={(event) => setTaskTitleDraft(event.target.value)}
                        onBlur={() => void renameTask(selectedTask.id, taskTitleDraft)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') {
                            event.preventDefault()
                            void renameTask(selectedTask.id, taskTitleDraft)
                          }
                          if (event.key === 'Escape') {
                            event.preventDefault()
                            setTaskTitleDraft(selectedTask.source_name)
                            setEditingTaskTitle(false)
                          }
                        }}
                        autoFocus
                      />
                    ) : (
                      <strong
                        className="editable-task-title"
                        title={selectedTask.source_name}
                        onDoubleClick={() => {
                          setTaskTitleDraft(selectedTask.source_name)
                          setEditingTaskTitle(true)
                        }}
                      >
                        {selectedTask.source_name}
                      </strong>
                    )}
                    <div className="detail-inline-meta">
                      <span className={`status-chip status-${selectedTask.status}`}>{selectedTask.status}</span>
                      <span>{selectedTask.points_cost} 点</span>
                      <span>{formatDuration(selectedTask.duration_seconds)}</span>
                    </div>
                    <div className="detail-inline-hint">{taskHint(selectedTask)}</div>
                  </div>
                  <div className="detail-actions">
                    <button type="button" className="ghost-button" onClick={() => void refreshSelectedTaskWorkspace(selectedTask.id)}>
                      <RefreshCw size={16} />
                      刷新
                    </button>
                    <button
                      type="button"
                      className="ghost-button"
                      disabled={(selectedEditor?.utterances.length || 0) === 0}
                      onClick={() => downloadTaskExport(selectedTask.id, 'srt')}
                    >
                      <Download size={16} />
                      SRT
                    </button>
                    <button
                      type="button"
                      className="ghost-button"
                      disabled={(selectedEditor?.utterances.length || 0) === 0}
                      onClick={() => downloadTaskExport(selectedTask.id, 'text')}
                    >
                      <FileText size={16} />
                      Text
                    </button>
                  </div>
                </div>
                {selectedTask.error ? <div className="error-note">{selectedTask.error}</div> : null}
              </div>
            </section>
            <ProofreaderWorkspace
              task={selectedTask}
              editor={selectedEditor || { utterances: [] }}
              draftText={selectedWorkspace?.draftText || ''}
              onDraftTextChange={(value) => {
                if (!selectedTaskSummary) return
                setWorkspaceByTaskId((previous) => {
                  const current = previous[selectedTaskSummary.id]
                  if (!current || current.draftText === value) return previous
                  return {
                    ...previous,
                    [selectedTaskSummary.id]: {
                      ...current,
                      draftText: value,
                    },
                  }
                })
              }}
              onSave={(utterances, value) => {
                setWorkspaceByTaskId((previous) => {
                  const current = previous[selectedTask.id]
                  if (!current) return previous
                  return {
                    ...previous,
                    [selectedTask.id]: {
                      ...current,
                      editor: {
                        ...current.editor,
                        utterances,
                      },
                      draftText: value,
                    },
                  }
                })
                void requestJson<SiteTaskResponse>(`/site/tasks/${selectedTask.id}/correction`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ utterances }),
                })
                  .then((data) => {
                    setTasks((previous) =>
                      previous.map((task) => (task.id === selectedTask.id ? data.task : task)),
                    )
                    setWorkspaceByTaskId((previous) => {
                      const current = previous[selectedTask.id]
                      if (!current) return previous
                      return {
                        ...previous,
                        [selectedTask.id]: {
                          ...current,
                          task: {
                            ...current.task,
                            ...data.task,
                          },
                        },
                      }
                    })
                  })
                  .catch(() => {
                    void refreshTask(selectedTask.id)
                    void loadTaskWorkspace(selectedTask.id)
                  })
              }}
            />
          </>
        ) : (
          <section className="panel empty-state">
            <h2>请选择一个任务</h2>
            <p>左侧卡片可以直接查看、确认转写或删除；只有点开任务后才进入校对区。</p>
          </section>
        )}
        {!selectedTask && selectedTaskSummary && workspaceLoading ? (
          <section className="panel empty-state">
            <h2>正在加载工作区</h2>
            <p>正在拉取任务详情、音频和句级校对数据。</p>
          </section>
        ) : null}
      </main>
    </div>
  )
}

export default App
