export const ADMIN_API_KEY_STORAGE_KEY = 'recordflow.admin.api-key'

export const ACTIVE_TASK_STATUSES = ['uploaded', 'starting', 'queued', 'transcribing'] as const

export type AdminEnvironmentId = 'local' | 'staging' | 'production'
export type AdminRemoteEnvironmentId = Exclude<AdminEnvironmentId, 'local'>

export type AdminEnvironmentConfig = {
  id: AdminRemoteEnvironmentId
  label: string
  hostname: string
  origin: string
}

export const ADMIN_ENVIRONMENTS: Record<AdminRemoteEnvironmentId, AdminEnvironmentConfig> = {
  staging: {
    id: 'staging',
    label: '测试环境',
    hostname: 'test-record.blenet.top',
    origin: 'https://test-record.blenet.top',
  },
  production: {
    id: 'production',
    label: '正式环境',
    hostname: 'record-api.blenet.top',
    origin: 'https://record-api.blenet.top',
  },
}

export const TASK_STATUS_ORDER = [
  'failed',
  'uploaded',
  'starting',
  'queued',
  'transcribing',
  'completed',
  'confirmed',
] as const

export type AdminUser = {
  id: string
  name: string
  role: string
  points_balance: number
  created_at?: string | null
  updated_at?: string | null
}

export type AdminTask = {
  id: string
  user_id: string
  workspace_id?: string | null
  media_id?: string | null
  job_id?: string | null
  title: string
  source_name: string
  content_type?: string | null
  status: string
  points_cost: number
  charge_basis?: string | null
  agreement_version?: string | null
  notify_on_complete?: boolean | null
  notification_template_id?: string | null
  notification_job_id?: string | null
  notification_status?: string | null
  notification_attempts?: number | null
  notification_last_error?: string | null
  notification_sent_at?: string | null
  error?: string | null
  confirmed_at?: string | null
  completed_at?: string | null
  expires_at?: string | null
  created_at?: string | null
  updated_at?: string | null
  original_size_bytes?: number | null
  duration_seconds?: number | null
  local_file_path?: string | null
  local_expires_at?: string | null
}

export type AdminPointLedgerItem = {
  id: string
  user_id: string
  delta: number
  kind: string
  note?: string | null
  task_id?: string | null
  created_at?: string | null
}

export type AdminUserAgreement = {
  user_id: string
  agreement_version: string
  accepted_at?: string | null
  client?: string | null
}

export type AdminPointLedgerDirection = 'all' | 'credit' | 'debit'

export type AdminDashboardData = {
  users: AdminUser[]
  tasks: AdminTask[]
  point_ledger: AdminPointLedgerItem[]
  agreements?: AdminUserAgreement[]
}

export type AdminDashboardMetrics = {
  users: number
  tasks: number
  activeTasks: number
  failedTasks: number
  totalBalance: number
  pointCredits: number
  pointDebits: number
  pointNet: number
  ledgerEntries: number
}

export class AdminRequestError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'AdminRequestError'
    this.status = status
  }
}

function numeric(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function searchable(value: unknown): string {
  return String(value ?? '').toLocaleLowerCase('zh-CN')
}

function timestamp(value: string | null | undefined): number {
  if (!value) return 0
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function normalizedEnvironment(value: string | null | undefined): AdminEnvironmentId | null {
  const normalized = String(value || '').trim().toLocaleLowerCase('en-US')
  if (['production', 'prod', 'formal', 'online'].includes(normalized)) return 'production'
  if (['staging', 'stage', 'test', 'testing'].includes(normalized)) return 'staging'
  if (['local', 'localhost', 'development', 'dev'].includes(normalized)) return 'local'
  return null
}

function normalizedHostname(value: string): string {
  let hostname = value.trim().toLocaleLowerCase('en-US')
  if (hostname.includes('://')) {
    try {
      hostname = new URL(hostname).hostname
    } catch {
      return hostname
    }
  }
  if (hostname.startsWith('[')) {
    const closingBracket = hostname.indexOf(']')
    if (closingBracket >= 0) return hostname.slice(1, closingBracket)
  }
  const colon = hostname.indexOf(':')
  if (colon >= 0 && colon === hostname.lastIndexOf(':')) hostname = hostname.slice(0, colon)
  return hostname.replace(/\.$/, '')
}

export function resolveAdminEnvironment(
  hostname: string,
  metaEnvironment?: string | null,
): AdminEnvironmentId {
  const metaMatch = normalizedEnvironment(metaEnvironment)
  if (metaMatch) return metaMatch

  const normalized = normalizedHostname(hostname)
  if (normalized === ADMIN_ENVIRONMENTS.staging.hostname) return 'staging'
  if (normalized === ADMIN_ENVIRONMENTS.production.hostname) return 'production'
  if (normalized === 'localhost' || normalized === '::1' || normalized.startsWith('127.')) return 'local'
  return 'local'
}

export function adminEnvironmentUrl(
  target: AdminRemoteEnvironmentId,
  pathname = '/admin',
): string {
  const normalizedPath = pathname.trim() || '/admin'
  const targetPath = normalizedPath.startsWith('/') ? normalizedPath : `/${normalizedPath}`
  return new URL(targetPath, ADMIN_ENVIRONMENTS[target].origin).toString()
}

export function isAdminPath(pathname: string): boolean {
  return pathname === '/admin' || pathname.startsWith('/admin/')
}

export function isActiveAdminTask(task: AdminTask): boolean {
  return ACTIVE_TASK_STATUSES.includes(task.status as (typeof ACTIVE_TASK_STATUSES)[number])
}

export function deriveAdminMetrics(data: AdminDashboardData): AdminDashboardMetrics {
  const users = data.users || []
  const tasks = data.tasks || []
  const ledger = data.point_ledger || []
  const deltas = ledger.map((item) => numeric(item.delta))

  return {
    users: users.length,
    tasks: tasks.length,
    activeTasks: tasks.filter(isActiveAdminTask).length,
    failedTasks: tasks.filter((task) => task.status === 'failed').length,
    totalBalance: users.reduce((sum, user) => sum + numeric(user.points_balance), 0),
    pointCredits: deltas.filter((delta) => delta > 0).reduce((sum, delta) => sum + delta, 0),
    pointDebits: Math.abs(deltas.filter((delta) => delta < 0).reduce((sum, delta) => sum + delta, 0)),
    pointNet: deltas.reduce((sum, delta) => sum + delta, 0),
    ledgerEntries: ledger.length,
  }
}

export function taskStatusCounts(tasks: AdminTask[]): Array<{ status: string; count: number }> {
  const counts = new Map<string, number>()
  for (const task of tasks || []) {
    counts.set(task.status, (counts.get(task.status) || 0) + 1)
  }
  const knownOrder = new Map<string, number>(TASK_STATUS_ORDER.map((status, index) => [status, index]))
  return Array.from(counts, ([status, count]) => ({ status, count })).sort((left, right) => {
    const leftOrder = knownOrder.get(left.status) ?? TASK_STATUS_ORDER.length
    const rightOrder = knownOrder.get(right.status) ?? TASK_STATUS_ORDER.length
    return leftOrder - rightOrder || left.status.localeCompare(right.status)
  })
}

export function filterAdminUsers(users: AdminUser[], query: string): AdminUser[] {
  const normalized = query.trim().toLocaleLowerCase('zh-CN')
  if (!normalized) return users
  return users.filter((user) =>
    [user.name, user.id, user.role].some((value) => searchable(value).includes(normalized)),
  )
}

export function filterAdminTasks(
  tasks: AdminTask[],
  users: AdminUser[],
  query: string,
  status: string,
): AdminTask[] {
  const normalized = query.trim().toLocaleLowerCase('zh-CN')
  const userNames = new Map(users.map((user) => [user.id, user.name]))
  return tasks.filter((task) => {
    if (status && status !== 'all' && task.status !== status) return false
    if (!normalized) return true
    return [
      task.title,
      task.source_name,
      task.id,
      task.user_id,
      userNames.get(task.user_id),
      task.status,
      task.error,
    ].some((value) => searchable(value).includes(normalized))
  })
}

export function filterAdminPointLedger(
  entries: AdminPointLedgerItem[],
  users: AdminUser[],
  query: string,
  kind = 'all',
  direction: AdminPointLedgerDirection = 'all',
): AdminPointLedgerItem[] {
  const normalizedQuery = query.trim().toLocaleLowerCase('zh-CN')
  const normalizedKind = kind.trim().toLocaleLowerCase('zh-CN')
  const userNames = new Map(users.map((user) => [user.id, user.name]))

  return entries.filter((entry) => {
    if (normalizedKind && normalizedKind !== 'all' && searchable(entry.kind) !== normalizedKind) return false
    if (direction === 'credit' && numeric(entry.delta) <= 0) return false
    if (direction === 'debit' && numeric(entry.delta) >= 0) return false
    if (!normalizedQuery) return true
    return [
      entry.id,
      entry.user_id,
      userNames.get(entry.user_id),
      entry.kind,
      entry.note,
      entry.task_id,
      entry.delta,
    ].some((value) => searchable(value).includes(normalizedQuery))
  })
}

export function recentAdminPointLedger(entries: AdminPointLedgerItem[]): AdminPointLedgerItem[] {
  return [...entries].sort((left, right) => timestamp(right.created_at) - timestamp(left.created_at))
}

export function recentAdminTasks(tasks: AdminTask[]): AdminTask[] {
  return [...tasks].sort(
    (left, right) => timestamp(right.created_at || right.updated_at) - timestamp(left.created_at || left.updated_at),
  )
}

export function attentionAdminTasks(tasks: AdminTask[]): AdminTask[] {
  return recentAdminTasks(tasks)
    .filter((task) => task.status === 'failed' || isActiveAdminTask(task))
    .sort((left, right) => {
      const priority = (task: AdminTask) => (task.status === 'failed' ? 0 : 1)
      return priority(left) - priority(right) || timestamp(right.updated_at) - timestamp(left.updated_at)
    })
}

function responseMessage(rawText: string, contentType: string): string {
  const trimmed = rawText.trim()
  if (!trimmed) return ''
  if (contentType.includes('application/json') || trimmed.startsWith('{')) {
    try {
      const parsed = JSON.parse(trimmed) as { detail?: unknown; message?: unknown }
      if (typeof parsed.detail === 'string') return parsed.detail
      if (typeof parsed.message === 'string') return parsed.message
    } catch {
      // The plain-text fallback below is intentionally used for malformed JSON.
    }
  }
  return trimmed.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, 180)
}

export async function adminRequest<T>(
  url: string,
  apiKey: string,
  init: RequestInit = {},
  fetcher: typeof fetch = globalThis.fetch,
): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('X-API-Key', apiKey)
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetcher(url, { ...init, headers })
  const rawText = await response.text()
  if (!response.ok) {
    const message = responseMessage(rawText, response.headers.get('Content-Type') || '')
    throw new AdminRequestError(message || `请求失败：HTTP ${response.status}`, response.status)
  }
  if (!rawText.trim()) return {} as T
  try {
    return JSON.parse(rawText) as T
  } catch {
    throw new AdminRequestError('服务端返回了无法识别的数据。', response.status)
  }
}
