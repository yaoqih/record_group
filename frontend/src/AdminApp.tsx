import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Coins,
  Download,
  Edit3,
  Eye,
  EyeOff,
  FileAudio,
  Gauge,
  KeyRound,
  LayoutDashboard,
  List,
  LoaderCircle,
  LogOut,
  Play,
  Plus,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  Trash2,
  UserRound,
  UsersRound,
  WalletCards,
  X,
  type LucideIcon,
} from 'lucide-react'
import {
  ADMIN_API_KEY_STORAGE_KEY,
  ADMIN_ENVIRONMENTS,
  AdminRequestError,
  adminEnvironmentUrl,
  adminRequest,
  attentionAdminTasks,
  deriveAdminMetrics,
  filterAdminTasks,
  filterAdminUsers,
  recentAdminTasks,
  resolveAdminEnvironment,
  taskStatusCounts,
  type AdminDashboardData,
  type AdminEnvironmentId,
  type AdminPointLedgerItem,
  type AdminTask,
  type AdminUser,
  type AdminUserAgreement,
} from './admin'
import './AdminApp.css'

type SessionState = 'locked' | 'checking' | 'ready'
type AdminView = 'overview' | 'users' | 'tasks' | 'ledger'
type Banner = { tone: 'error' | 'success'; message: string } | null
type ServiceMeta = { environment?: string; service_name?: string; server_time?: string }
type NormalizedDashboard = Omit<AdminDashboardData, 'agreements'> & {
  agreements: AdminUserAgreement[]
}
type TaskEditorResponse = {
  task: AdminTask
  editor: {
    utterances: Array<{
      text?: string
      speaker?: string
      start_time?: number
      end_time?: number
    }>
  }
}
type TaskDetailState =
  | { status: 'idle'; data: null; error: '' }
  | { status: 'loading'; data: null; error: '' }
  | { status: 'ready'; data: TaskEditorResponse; error: '' }
  | { status: 'error'; data: null; error: string }
type DialogState =
  | { kind: 'create-user' }
  | { kind: 'edit-user'; user: AdminUser }
  | { kind: 'adjust-points'; user: AdminUser }
  | { kind: 'rename-task'; task: AdminTask }
  | { kind: 'task-action'; action: 'start' | 'confirm' | 'delete'; task: AdminTask }
  | null

const PAGE_SIZE = 20

const STATUS_LABELS: Record<string, string> = {
  uploaded: '待确认',
  starting: '启动中',
  queued: '排队中',
  transcribing: '转写中',
  completed: '待校对',
  confirmed: '已确认',
  failed: '异常',
  expired: '已过期',
}

const ROLE_LABELS: Record<string, string> = {
  user: '普通用户',
  admin: '管理员',
}

const LEDGER_KIND_LABELS: Record<string, string> = {
  recharge: '人工充值',
  consume: '任务消费',
  refund: '任务退款',
  signup_bonus: '注册奖励',
  dev_signup_bonus: '开发奖励',
  wechatpay_recharge: '微信支付',
  admin_adjustment_credit: '后台发放',
  admin_adjustment_debit: '后台扣减',
}

const VIEW_CONFIG: Array<{ id: AdminView; label: string; icon: LucideIcon }> = [
  { id: 'overview', label: '运营概览', icon: Gauge },
  { id: 'users', label: '用户管理', icon: UsersRound },
  { id: 'tasks', label: '任务管理', icon: FileAudio },
  { id: 'ledger', label: '点数流水', icon: List },
]

const ACTIVE_TASK_STATUSES = new Set(['uploaded', 'starting', 'queued', 'transcribing'])

function initialView(): AdminView {
  const requested = new URLSearchParams(window.location.search).get('view')
  return VIEW_CONFIG.some((item) => item.id === requested) ? requested as AdminView : 'overview'
}

function normalizeDashboard(data: AdminDashboardData): NormalizedDashboard {
  return {
    users: Array.isArray(data.users) ? data.users : [],
    tasks: Array.isArray(data.tasks) ? data.tasks : [],
    point_ledger: Array.isArray(data.point_ledger) ? data.point_ledger : [],
    agreements: Array.isArray(data.agreements) ? data.agreements : [],
  }
}

function readStoredAdminKey(): string {
  try {
    return window.localStorage.getItem(ADMIN_API_KEY_STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

function saveStoredAdminKey(apiKey: string): boolean {
  try {
    window.localStorage.setItem(ADMIN_API_KEY_STORAGE_KEY, apiKey)
    return true
  } catch {
    return false
  }
}

function removeStoredAdminKey(): void {
  try {
    window.localStorage.removeItem(ADMIN_API_KEY_STORAGE_KEY)
  } catch {
    // Clearing the in-memory key is enough when browser storage is unavailable.
  }
}

function errorText(error: unknown): string {
  if (error instanceof AdminRequestError && error.status === 401) {
    return 'API Key 无效或已失效，请核对后重试。'
  }
  return error instanceof Error ? error.message : '请求失败，请稍后重试。'
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status || '未知'
}

function statusTone(status: string): string {
  if (status === 'failed' || status === 'expired') return 'danger'
  if (['uploaded', 'starting', 'queued', 'transcribing'].includes(status)) return 'active'
  if (status === 'completed') return 'warning'
  if (status === 'confirmed') return 'success'
  return 'neutral'
}

function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function formatDuration(value?: number | null): string {
  const total = Math.max(0, Math.round(Number(value) || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  if (hours > 0) return `${hours}时${minutes}分`
  if (minutes > 0) return `${minutes}分${seconds}秒`
  return `${seconds}秒`
}

function formatTimecode(value?: number): string {
  const totalSeconds = Math.max(0, Math.floor(Number(value || 0) / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function formatBytes(value?: number | null): string {
  const bytes = Math.max(0, Number(value) || 0)
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes.toFixed(0)} B`
}

function userName(users: AdminUser[], userId: string): string {
  return users.find((user) => user.id === userId)?.name || userId
}

function environmentLabel(environment: AdminEnvironmentId): string {
  if (environment === 'production') return '线上环境'
  if (environment === 'staging') return '测试环境'
  return '本地环境'
}

function environmentShortLabel(environment: AdminEnvironmentId): string {
  if (environment === 'production') return '线上'
  if (environment === 'staging') return '测试'
  return '本地'
}

function ledgerKindLabel(kind: string): string {
  return LEDGER_KIND_LABELS[kind] || kind || '其他'
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`admin-status admin-status--${statusTone(status)}`}>{statusLabel(status)}</span>
}

function EnvironmentSwitch({
  current,
  onSwitch,
}: {
  current: AdminEnvironmentId
  onSwitch: (environment: Exclude<AdminEnvironmentId, 'local'>) => void
}) {
  return (
    <div className="admin-environment" aria-label={`当前为${environmentLabel(current)}`}>
      <span className={`admin-environment__indicator admin-environment__indicator--${current}`}>
        <Server size={14} /> {environmentShortLabel(current)}
      </span>
      <div className="admin-environment__switch" role="group" aria-label="切换服务环境">
        {Object.values(ADMIN_ENVIRONMENTS).map((environment) => (
          <button
            key={environment.id}
            type="button"
            className={current === environment.id ? 'is-active' : ''}
            aria-pressed={current === environment.id}
            onClick={() => onSwitch(environment.id)}
          >
            {environment.id === 'staging' ? '测试' : '线上'}
          </button>
        ))}
      </div>
    </div>
  )
}

function MetricCard({
  icon: Icon,
  label,
  value,
  hint,
  tone = 'default',
}: {
  icon: LucideIcon
  label: string
  value: string | number
  hint: string
  tone?: 'default' | 'active' | 'danger'
}) {
  return (
    <article className={`admin-metric admin-metric--${tone}`}>
      <div className="admin-metric__icon" aria-hidden="true"><Icon size={18} /></div>
      <div className="admin-metric__content">
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{hint}</small>
      </div>
    </article>
  )
}

function Pagination({
  page,
  pageSize,
  total,
  onChange,
}: {
  page: number
  pageSize: number
  total: number
  onChange: (page: number) => void
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  if (total <= pageSize) return null
  return (
    <div className="admin-pagination" aria-label="分页">
      <span>第 {page} / {pageCount} 页，共 {total} 条</span>
      <div>
        <button
          className="admin-icon-button"
          type="button"
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          aria-label="上一页"
          title="上一页"
        ><ChevronLeft size={18} /></button>
        <button
          className="admin-icon-button"
          type="button"
          onClick={() => onChange(page + 1)}
          disabled={page >= pageCount}
          aria-label="下一页"
          title="下一页"
        ><ChevronRight size={18} /></button>
      </div>
    </div>
  )
}

function DialogFrame({
  title,
  description,
  busy,
  onClose,
  children,
}: {
  title: string
  description?: string
  busy: boolean
  onClose: () => void
  children: ReactNode
}) {
  return (
    <div className="admin-dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !busy) onClose()
    }}>
      <section className="admin-dialog" role="dialog" aria-modal="true" aria-labelledby="admin-dialog-title">
        <header className="admin-dialog__head">
          <div>
            <h2 id="admin-dialog-title">{title}</h2>
            {description ? <p>{description}</p> : null}
          </div>
          <button className="admin-icon-button" type="button" onClick={onClose} disabled={busy} aria-label="关闭" title="关闭">
            <X size={19} />
          </button>
        </header>
        {children}
      </section>
    </div>
  )
}

function UserFormDialog({
  user,
  busy,
  onClose,
  onSubmit,
}: {
  user?: AdminUser
  busy: boolean
  onClose: () => void
  onSubmit: (values: { name: string; role: string; initialPoints: number }) => void
}) {
  const [name, setName] = useState(user?.name || '')
  const [role, setRole] = useState(user?.role || 'user')
  const [initialPoints, setInitialPoints] = useState('0')
  const points = Number(initialPoints)
  const valid = Boolean(name.trim()) && Number.isInteger(points) && points >= 0

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (valid) onSubmit({ name: name.trim(), role, initialPoints: points })
  }

  return (
    <DialogFrame
      title={user ? '编辑用户' : '创建用户'}
      description={user ? user.id : undefined}
      busy={busy}
      onClose={onClose}
    >
      <form className="admin-dialog__form" onSubmit={submit}>
        <label className="admin-field">
          <span>用户名称</span>
          <input value={name} maxLength={60} onChange={(event) => setName(event.target.value)} disabled={busy} autoFocus />
        </label>
        <label className="admin-field">
          <span>账号角色</span>
          <select value={role} onChange={(event) => setRole(event.target.value)} disabled={busy}>
            <option value="user">普通用户</option>
            <option value="admin">管理员</option>
          </select>
        </label>
        {!user ? (
          <label className="admin-field">
            <span>初始点数</span>
            <input
              type="number"
              min="0"
              step="1"
              value={initialPoints}
              onChange={(event) => setInitialPoints(event.target.value)}
              disabled={busy}
            />
          </label>
        ) : null}
        <div className="admin-dialog__actions">
          <button className="admin-secondary-button" type="button" onClick={onClose} disabled={busy}>取消</button>
          <button className="admin-primary-button" type="submit" disabled={busy || !valid}>
            {busy ? <LoaderCircle className="admin-spin" size={18} /> : <Check size={18} />}
            {busy ? '提交中' : '保存'}
          </button>
        </div>
      </form>
    </DialogFrame>
  )
}

function PointAdjustmentDialog({
  user,
  busy,
  onClose,
  onSubmit,
}: {
  user: AdminUser
  busy: boolean
  onClose: () => void
  onSubmit: (delta: number, note: string) => void
}) {
  const [direction, setDirection] = useState<'credit' | 'debit'>('credit')
  const [points, setPoints] = useState('100')
  const [note, setNote] = useState('后台人工调整')
  const numericPoints = Number(points)
  const valid = Number.isInteger(numericPoints)
    && numericPoints > 0
    && (direction === 'credit' || numericPoints <= Number(user.points_balance || 0))

  return (
    <DialogFrame title={`调整 ${user.name} 的点数`} description={`当前余额 ${Number(user.points_balance || 0).toLocaleString('zh-CN')} 点`} busy={busy} onClose={onClose}>
      <form className="admin-dialog__form" onSubmit={(event) => {
        event.preventDefault()
        if (valid) onSubmit(direction === 'credit' ? numericPoints : -numericPoints, note.trim())
      }}>
        <div className="admin-field">
          <span>调整方向</span>
          <div className="admin-segmented" role="group" aria-label="调整方向">
            <button type="button" className={direction === 'credit' ? 'is-active' : ''} onClick={() => setDirection('credit')} disabled={busy}>
              <ArrowUpRight size={17} /> 发放
            </button>
            <button type="button" className={direction === 'debit' ? 'is-active is-danger' : ''} onClick={() => setDirection('debit')} disabled={busy}>
              <ArrowDownRight size={17} /> 扣减
            </button>
          </div>
        </div>
        <label className="admin-field">
          <span>点数</span>
          <input type="number" min="1" step="1" value={points} onChange={(event) => setPoints(event.target.value)} disabled={busy} autoFocus />
        </label>
        <label className="admin-field">
          <span>流水备注</span>
          <input value={note} maxLength={100} onChange={(event) => setNote(event.target.value)} disabled={busy} />
        </label>
        {direction === 'debit' && numericPoints > Number(user.points_balance || 0) ? (
          <p className="admin-field-error">扣减点数不能超过当前余额。</p>
        ) : null}
        <div className="admin-dialog__actions">
          <button className="admin-secondary-button" type="button" onClick={onClose} disabled={busy}>取消</button>
          <button className={direction === 'debit' ? 'admin-danger-button' : 'admin-primary-button'} type="submit" disabled={busy || !valid}>
            {busy ? <LoaderCircle className="admin-spin" size={18} /> : <CircleDollarSign size={18} />}
            {busy ? '提交中' : direction === 'credit' ? '确认发放' : '确认扣减'}
          </button>
        </div>
      </form>
    </DialogFrame>
  )
}

function RenameTaskDialog({
  task,
  busy,
  onClose,
  onSubmit,
}: {
  task: AdminTask
  busy: boolean
  onClose: () => void
  onSubmit: (title: string) => void
}) {
  const [title, setTitle] = useState(task.title || task.source_name)
  return (
    <DialogFrame title="重命名任务" description={task.id} busy={busy} onClose={onClose}>
      <form className="admin-dialog__form" onSubmit={(event) => {
        event.preventDefault()
        if (title.trim()) onSubmit(title.trim())
      }}>
        <label className="admin-field">
          <span>任务名称</span>
          <input value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} disabled={busy} autoFocus />
        </label>
        <div className="admin-dialog__actions">
          <button className="admin-secondary-button" type="button" onClick={onClose} disabled={busy}>取消</button>
          <button className="admin-primary-button" type="submit" disabled={busy || !title.trim()}>
            {busy ? <LoaderCircle className="admin-spin" size={18} /> : <Check size={18} />}
            {busy ? '提交中' : '保存'}
          </button>
        </div>
      </form>
    </DialogFrame>
  )
}

function TaskActionDialog({
  action,
  task,
  busy,
  onClose,
  onConfirm,
}: {
  action: 'start' | 'confirm' | 'delete'
  task: AdminTask
  busy: boolean
  onClose: () => void
  onConfirm: () => void
}) {
  const config = action === 'delete'
    ? { title: '删除任务', detail: '任务记录、转写内容和关联媒体将被永久删除。', label: '确认删除', danger: true }
    : action === 'start'
      ? { title: '启动任务', detail: `将代表用户确认并扣除 ${task.points_cost} 点，然后进入转写队列。`, label: '确认启动', danger: false }
      : { title: '确认转写结果', detail: '确认后任务将标记为已完成，可继续导出内容。', label: '确认结果', danger: false }
  return (
    <DialogFrame title={config.title} description={task.title || task.source_name} busy={busy} onClose={onClose}>
      <div className={`admin-confirm ${config.danger ? 'admin-confirm--danger' : ''}`}>
        {config.danger ? <AlertTriangle size={21} /> : <CheckCircle2 size={21} />}
        <p>{config.detail}</p>
      </div>
      <div className="admin-dialog__actions">
        <button className="admin-secondary-button" type="button" onClick={onClose} disabled={busy}>取消</button>
        <button className={config.danger ? 'admin-danger-button' : 'admin-primary-button'} type="button" onClick={onConfirm} disabled={busy}>
          {busy ? <LoaderCircle className="admin-spin" size={18} /> : config.danger ? <Trash2 size={18} /> : <Check size={18} />}
          {busy ? '处理中' : config.label}
        </button>
      </div>
    </DialogFrame>
  )
}

function ApiKeyGate({
  value,
  checking,
  error,
  environment,
  onEnvironmentSwitch,
  onChange,
  onSubmit,
}: {
  value: string
  checking: boolean
  error: string
  environment: AdminEnvironmentId
  onEnvironmentSwitch: (environment: Exclude<AdminEnvironmentId, 'local'>) => void
  onChange: (value: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
}) {
  const [showKey, setShowKey] = useState(false)
  return (
    <main className="admin-gate">
      <section className="admin-gate__card" aria-labelledby="admin-login-title">
        <div className="admin-gate__top">
          <div className="admin-brand">
            <span className="admin-brand__mark" aria-hidden="true"><LayoutDashboard size={20} /></span>
            <span><strong>RecordFlow</strong><small>管理控制台</small></span>
          </div>
          <EnvironmentSwitch current={environment} onSwitch={onEnvironmentSwitch} />
        </div>
        <div className="admin-gate__intro">
          <span><ShieldCheck size={16} /> {environmentLabel(environment)}</span>
          <h1 id="admin-login-title">管理员登录</h1>
        </div>
        <form className="admin-gate__form" onSubmit={onSubmit}>
          <label htmlFor="admin-api-key">API Key</label>
          <div className="admin-key-field">
            <KeyRound size={18} aria-hidden="true" />
            <input
              id="admin-api-key"
              name="apiKey"
              type={showKey ? 'text' : 'password'}
              value={value}
              autoComplete="current-password"
              placeholder="请输入 X-API-Key"
              disabled={checking}
              onChange={(event) => onChange(event.target.value)}
              autoFocus
            />
            <button
              className="admin-key-field__toggle"
              type="button"
              onClick={() => setShowKey((current) => !current)}
              aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}
              title={showKey ? '隐藏 API Key' : '显示 API Key'}
              disabled={checking}
            >
              {showKey ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
          {error ? <div className="admin-form-error" role="alert">{error}</div> : null}
          <button className="admin-primary-button admin-gate__submit" type="submit" disabled={checking || !value.trim()}>
            {checking ? <LoaderCircle className="admin-spin" size={18} /> : <ShieldCheck size={18} />}
            {checking ? '正在验证' : '进入管理端'}
          </button>
        </form>
      </section>
    </main>
  )
}

function DetailField({ label, children }: { label: string; children: ReactNode }) {
  return <div className="admin-detail-field"><dt>{label}</dt><dd>{children || '—'}</dd></div>
}

function UserDetailDrawer({
  user,
  tasks,
  ledger,
  agreements,
  onClose,
  onEdit,
  onAdjust,
  onOpenTask,
}: {
  user: AdminUser
  tasks: AdminTask[]
  ledger: AdminPointLedgerItem[]
  agreements: AdminUserAgreement[]
  onClose: () => void
  onEdit: () => void
  onAdjust: () => void
  onOpenTask: (task: AdminTask) => void
}) {
  const userTasks = recentAdminTasks(tasks.filter((task) => task.user_id === user.id))
  const userLedger = ledger.filter((item) => item.user_id === user.id)
  const userAgreements = agreements.filter((item) => item.user_id === user.id)
  return (
    <div className="admin-drawer-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <aside className="admin-drawer" role="dialog" aria-modal="true" aria-labelledby="admin-user-detail-title">
        <header className="admin-drawer__head">
          <div className="admin-drawer__identity">
            <span className="admin-avatar admin-avatar--large" aria-hidden="true"><UserRound size={21} /></span>
            <div><h2 id="admin-user-detail-title">{user.name}</h2><p>{user.id}</p></div>
          </div>
          <button className="admin-icon-button" type="button" onClick={onClose} aria-label="关闭用户详情" title="关闭"><X size={19} /></button>
        </header>
        <div className="admin-drawer__body">
          <section className="admin-detail-section">
            <h3>账号信息</h3>
            <dl className="admin-detail-grid">
              <DetailField label="角色">{ROLE_LABELS[user.role] || user.role}</DetailField>
              <DetailField label="点数余额">{Number(user.points_balance || 0).toLocaleString('zh-CN')} 点</DetailField>
              <DetailField label="任务数量">{userTasks.length}</DetailField>
              <DetailField label="流水数量">{userLedger.length}</DetailField>
              <DetailField label="创建时间">{formatDateTime(user.created_at)}</DetailField>
              <DetailField label="最近更新">{formatDateTime(user.updated_at)}</DetailField>
            </dl>
          </section>
          <section className="admin-detail-section">
            <div className="admin-detail-section__head"><h3>协议记录</h3><span>{userAgreements.length} 条</span></div>
            {userAgreements.length ? (
              <div className="admin-compact-list">
                {userAgreements.map((agreement) => (
                  <div key={`${agreement.user_id}-${agreement.agreement_version}`}>
                    <strong>{agreement.agreement_version}</strong>
                    <span>{agreement.client || '未知客户端'} · {formatDateTime(agreement.accepted_at)}</span>
                  </div>
                ))}
              </div>
            ) : <p className="admin-empty-text">暂无协议接受记录</p>}
          </section>
          <section className="admin-detail-section">
            <div className="admin-detail-section__head"><h3>最近任务</h3><span>{userTasks.length} 个</span></div>
            {userTasks.length ? (
              <div className="admin-compact-list">
                {userTasks.slice(0, 6).map((task) => (
                  <button type="button" key={task.id} onClick={() => onOpenTask(task)}>
                    <span><strong>{task.title || task.source_name}</strong><small>{formatDateTime(task.created_at)}</small></span>
                    <StatusBadge status={task.status} />
                  </button>
                ))}
              </div>
            ) : <p className="admin-empty-text">暂无任务</p>}
          </section>
          <section className="admin-detail-section">
            <div className="admin-detail-section__head"><h3>最近点数变动</h3><span>{userLedger.length} 笔</span></div>
            {userLedger.length ? (
              <div className="admin-compact-list">
                {userLedger.slice(0, 6).map((item) => (
                  <div key={item.id}>
                    <span><strong>{ledgerKindLabel(item.kind)}</strong><small>{item.note || '无备注'} · {formatDateTime(item.created_at)}</small></span>
                    <b className={item.delta < 0 ? 'is-negative' : 'is-positive'}>{item.delta > 0 ? '+' : ''}{item.delta}</b>
                  </div>
                ))}
              </div>
            ) : <p className="admin-empty-text">暂无点数流水</p>}
          </section>
        </div>
        <footer className="admin-drawer__actions">
          <button className="admin-secondary-button" type="button" onClick={onEdit}><Edit3 size={17} /> 编辑资料</button>
          <button className="admin-primary-button" type="button" onClick={onAdjust}><Coins size={17} /> 调整点数</button>
        </footer>
      </aside>
    </div>
  )
}

function TaskDetailDrawer({
  task,
  user,
  detail,
  exportBusy,
  onClose,
  onRename,
  onAction,
  onExport,
}: {
  task: AdminTask
  user?: AdminUser
  detail: TaskDetailState
  exportBusy: boolean
  onClose: () => void
  onRename: () => void
  onAction: (action: 'start' | 'confirm' | 'delete') => void
  onExport: (format: 'srt' | 'text' | 'doc') => void
}) {
  const [exportFormat, setExportFormat] = useState<'srt' | 'text' | 'doc'>('srt')
  const resolvedTask = detail.status === 'ready' ? detail.data.task : task
  const utterances = detail.status === 'ready' ? detail.data.editor.utterances || [] : []
  const active = ACTIVE_TASK_STATUSES.has(resolvedTask.status) && resolvedTask.status !== 'uploaded'
  return (
    <div className="admin-drawer-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <aside className="admin-drawer admin-drawer--wide" role="dialog" aria-modal="true" aria-labelledby="admin-task-detail-title">
        <header className="admin-drawer__head">
          <div>
            <div className="admin-drawer__title-line"><StatusBadge status={resolvedTask.status} /><span>{resolvedTask.id}</span></div>
            <h2 id="admin-task-detail-title">{resolvedTask.title || resolvedTask.source_name}</h2>
            <p>{user?.name || resolvedTask.user_id} · {resolvedTask.source_name}</p>
          </div>
          <button className="admin-icon-button" type="button" onClick={onClose} aria-label="关闭任务详情" title="关闭"><X size={19} /></button>
        </header>
        <div className="admin-drawer__body">
          {detail.status === 'loading' ? <div className="admin-detail-loading"><LoaderCircle className="admin-spin" size={21} /> 正在加载完整详情</div> : null}
          {detail.status === 'error' ? <div className="admin-inline-error"><AlertTriangle size={18} /> {detail.error}</div> : null}
          <section className="admin-detail-section">
            <h3>任务信息</h3>
            <dl className="admin-detail-grid">
              <DetailField label="状态"><StatusBadge status={resolvedTask.status} /></DetailField>
              <DetailField label="所属用户">{user?.name || resolvedTask.user_id}</DetailField>
              <DetailField label="时长">{formatDuration(resolvedTask.duration_seconds)}</DetailField>
              <DetailField label="文件大小">{formatBytes(resolvedTask.original_size_bytes)}</DetailField>
              <DetailField label="点数成本">{resolvedTask.points_cost} 点</DetailField>
              <DetailField label="计费依据">{resolvedTask.charge_basis || '—'}</DetailField>
              <DetailField label="内容类型">{resolvedTask.content_type || '—'}</DetailField>
              <DetailField label="协议版本">{resolvedTask.agreement_version || '—'}</DetailField>
            </dl>
          </section>
          <section className="admin-detail-section">
            <h3>关联资源</h3>
            <dl className="admin-detail-grid admin-detail-grid--single">
              <DetailField label="Workspace ID">{resolvedTask.workspace_id || '—'}</DetailField>
              <DetailField label="Media ID">{resolvedTask.media_id || '—'}</DetailField>
              <DetailField label="Job ID">{resolvedTask.job_id || '—'}</DetailField>
              <DetailField label="本地文件">{resolvedTask.local_file_path || '—'}</DetailField>
            </dl>
          </section>
          <section className="admin-detail-section">
            <h3>时间记录</h3>
            <dl className="admin-detail-grid">
              <DetailField label="创建时间">{formatDateTime(resolvedTask.created_at)}</DetailField>
              <DetailField label="最近更新">{formatDateTime(resolvedTask.updated_at)}</DetailField>
              <DetailField label="开始确认">{formatDateTime(resolvedTask.confirmed_at)}</DetailField>
              <DetailField label="转写完成">{formatDateTime(resolvedTask.completed_at)}</DetailField>
              <DetailField label="任务过期">{formatDateTime(resolvedTask.expires_at)}</DetailField>
              <DetailField label="本地文件过期">{formatDateTime(resolvedTask.local_expires_at)}</DetailField>
            </dl>
          </section>
          <section className="admin-detail-section">
            <div className="admin-detail-section__head"><h3>完成通知</h3><span>{resolvedTask.notification_status || 'disabled'}</span></div>
            <dl className="admin-detail-grid">
              <DetailField label="是否订阅">{resolvedTask.notify_on_complete ? '是' : '否'}</DetailField>
              <DetailField label="通知状态">{resolvedTask.notification_status || '未启用'}</DetailField>
              <DetailField label="尝试次数">{resolvedTask.notification_attempts ?? 0}</DetailField>
              <DetailField label="发送时间">{formatDateTime(resolvedTask.notification_sent_at)}</DetailField>
            </dl>
            {resolvedTask.notification_last_error ? <div className="admin-inline-error"><AlertTriangle size={17} /> {resolvedTask.notification_last_error}</div> : null}
          </section>
          {resolvedTask.error ? (
            <section className="admin-detail-section">
              <h3>异常信息</h3>
              <pre className="admin-error-block">{resolvedTask.error}</pre>
            </section>
          ) : null}
          <section className="admin-detail-section">
            <div className="admin-detail-section__head"><h3>转写内容</h3><span>{utterances.length} 段</span></div>
            {detail.status === 'ready' && utterances.length ? (
              <div className="admin-transcript">
                {utterances.map((utterance, index) => (
                  <article key={`${utterance.start_time || 0}-${index}`}>
                    <time>{formatTimecode(utterance.start_time)}</time>
                    <div>
                      {utterance.speaker ? <strong>{utterance.speaker}</strong> : null}
                      <p>{utterance.text || '—'}</p>
                    </div>
                  </article>
                ))}
              </div>
            ) : detail.status === 'ready' ? <p className="admin-empty-text">暂无可查看的转写内容</p> : null}
          </section>
        </div>
        <footer className="admin-drawer__actions admin-drawer__actions--task">
          <button className="admin-secondary-button" type="button" onClick={onRename}><Edit3 size={17} /> 重命名</button>
          {resolvedTask.status === 'uploaded' ? <button className="admin-primary-button" type="button" onClick={() => onAction('start')}><Play size={17} /> 启动</button> : null}
          {resolvedTask.status === 'completed' ? <button className="admin-primary-button" type="button" onClick={() => onAction('confirm')}><Check size={17} /> 确认结果</button> : null}
          {['completed', 'confirmed'].includes(resolvedTask.status) ? (
            <div className="admin-export-control">
              <select value={exportFormat} onChange={(event) => setExportFormat(event.target.value as 'srt' | 'text' | 'doc')} aria-label="导出格式">
                <option value="srt">SRT</option>
                <option value="text">TXT</option>
                <option value="doc">Word</option>
              </select>
              <button className="admin-secondary-button" type="button" onClick={() => onExport(exportFormat)} disabled={exportBusy}>
                {exportBusy ? <LoaderCircle className="admin-spin" size={17} /> : <Download size={17} />}
                导出
              </button>
            </div>
          ) : null}
          <button className="admin-danger-button admin-drawer__delete" type="button" onClick={() => onAction('delete')} disabled={active} title={active ? '进行中的任务不能删除' : '删除任务'}>
            <Trash2 size={17} /> 删除
          </button>
        </footer>
      </aside>
    </div>
  )
}

export default function AdminApp() {
  const [initialKey] = useState(readStoredAdminKey)
  const [apiKey, setApiKey] = useState(initialKey)
  const [apiKeyInput, setApiKeyInput] = useState(initialKey)
  const [sessionState, setSessionState] = useState<SessionState>(initialKey ? 'checking' : 'locked')
  const [authError, setAuthError] = useState('')
  const [dashboard, setDashboard] = useState<NormalizedDashboard | null>(null)
  const [serviceMeta, setServiceMeta] = useState<ServiceMeta | null>(null)
  const [activeView, setActiveView] = useState<AdminView>(initialView)
  const [refreshing, setRefreshing] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [banner, setBanner] = useState<Banner>(null)
  const [userQuery, setUserQuery] = useState('')
  const [userRole, setUserRole] = useState('all')
  const [userPage, setUserPage] = useState(1)
  const [taskQuery, setTaskQuery] = useState('')
  const [taskStatus, setTaskStatus] = useState('all')
  const [taskPage, setTaskPage] = useState(1)
  const [ledgerQuery, setLedgerQuery] = useState('')
  const [ledgerKind, setLedgerKind] = useState('all')
  const [ledgerPage, setLedgerPage] = useState(1)
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [taskDetail, setTaskDetail] = useState<TaskDetailState>({ status: 'idle', data: null, error: '' })
  const [taskDetailRevision, setTaskDetailRevision] = useState(0)
  const [dialog, setDialog] = useState<DialogState>(null)
  const [mutationBusy, setMutationBusy] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)

  const currentEnvironment = resolveAdminEnvironment(window.location.hostname, serviceMeta?.environment)

  useEffect(() => {
    if (sessionState !== 'checking' || !apiKey) return
    let cancelled = false
    void adminRequest<AdminDashboardData>('/site/admin/dashboard', apiKey)
      .then((data) => {
        if (cancelled) return
        setDashboard(normalizeDashboard(data))
        setLastUpdated(new Date())
        setAuthError('')
        setSessionState('ready')
        if (!saveStoredAdminKey(apiKey)) {
          setBanner({ tone: 'error', message: '浏览器未保存登录凭据，本次登录仅在当前页面有效。' })
        }
        void loadServiceMeta(apiKey)
      })
      .catch((error: unknown) => {
        if (cancelled) return
        if (error instanceof AdminRequestError && error.status === 401) removeStoredAdminKey()
        setAuthError(errorText(error))
        setSessionState('locked')
      })
    return () => {
      cancelled = true
    }
  }, [apiKey, sessionState])

  useEffect(() => {
    function updateFromHistory() {
      setActiveView(initialView())
    }
    window.addEventListener('popstate', updateFromHistory)
    return () => window.removeEventListener('popstate', updateFromHistory)
  }, [])

  useEffect(() => {
    if (!selectedTaskId || !apiKey) return
    let cancelled = false
    void adminRequest<TaskEditorResponse>(`/site/tasks/${encodeURIComponent(selectedTaskId)}/editor`, apiKey)
      .then((data) => {
        if (!cancelled) setTaskDetail({ status: 'ready', data, error: '' })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        if (error instanceof AdminRequestError && error.status === 401) {
          handleLogout()
          setAuthError(errorText(error))
          return
        }
        setTaskDetail({ status: 'error', data: null, error: errorText(error) })
      })
    return () => {
      cancelled = true
    }
  }, [apiKey, selectedTaskId, taskDetailRevision])

  const metrics = useMemo(() => (dashboard ? deriveAdminMetrics(dashboard) : null), [dashboard])
  const statusCounts = useMemo(() => taskStatusCounts(dashboard?.tasks || []), [dashboard])
  const filteredUsers = useMemo(() => {
    const matched = filterAdminUsers(dashboard?.users || [], userQuery)
    return userRole === 'all' ? matched : matched.filter((user) => user.role === userRole)
  }, [dashboard, userQuery, userRole])
  const filteredTasks = useMemo(
    () => recentAdminTasks(filterAdminTasks(dashboard?.tasks || [], dashboard?.users || [], taskQuery, taskStatus)),
    [dashboard, taskQuery, taskStatus],
  )
  const filteredLedger = useMemo(() => {
    const normalized = ledgerQuery.trim().toLocaleLowerCase('zh-CN')
    return (dashboard?.point_ledger || []).filter((item) => {
      if (ledgerKind !== 'all' && item.kind !== ledgerKind) return false
      if (!normalized) return true
      return [
        item.id,
        item.kind,
        ledgerKindLabel(item.kind),
        item.note,
        item.task_id,
        item.user_id,
        userName(dashboard?.users || [], item.user_id),
      ].some((value) => String(value || '').toLocaleLowerCase('zh-CN').includes(normalized))
    })
  }, [dashboard, ledgerKind, ledgerQuery])
  const attentionTasks = useMemo(() => attentionAdminTasks(dashboard?.tasks || []).slice(0, 6), [dashboard])
  const ledgerKinds = useMemo(() => Array.from(new Set((dashboard?.point_ledger || []).map((item) => item.kind))).sort(), [dashboard])
  const selectedUser = dashboard?.users.find((user) => user.id === selectedUserId) || null
  const selectedTask = dashboard?.tasks.find((task) => task.id === selectedTaskId) || null

  async function loadServiceMeta(key: string) {
    try {
      const meta = await adminRequest<ServiceMeta>('/site/admin/meta', key)
      setServiceMeta(meta)
    } catch {
      // The host mapping remains a reliable fallback during rolling deploys.
    }
  }

  function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const candidate = apiKeyInput.trim()
    if (!candidate) return
    setAuthError('')
    setApiKey(candidate)
    setSessionState('checking')
  }

  function handleLogout() {
    removeStoredAdminKey()
    setApiKey('')
    setApiKeyInput('')
    setDashboard(null)
    setServiceMeta(null)
    setSelectedUserId(null)
    setSelectedTaskId(null)
    setDialog(null)
    setBanner(null)
    setAuthError('')
    setSessionState('locked')
  }

  function switchEnvironment(target: Exclude<AdminEnvironmentId, 'local'>) {
    if (target === currentEnvironment) return
    if (target === 'production' && !window.confirm('即将进入线上环境，请确认后续操作将影响真实用户数据。')) return
    window.location.assign(adminEnvironmentUrl(target))
  }

  function changeView(view: AdminView) {
    setActiveView(view)
    const url = new URL(window.location.href)
    if (view === 'overview') url.searchParams.delete('view')
    else url.searchParams.set('view', view)
    window.history.pushState({}, '', `${url.pathname}${url.search}`)
  }

  function openTask(taskId: string) {
    setTaskDetail({ status: 'loading', data: null, error: '' })
    setSelectedTaskId(taskId)
  }

  async function refreshDashboard({ preserveBanner = false }: { preserveBanner?: boolean } = {}) {
    if (!apiKey || refreshing) return
    setRefreshing(true)
    if (!preserveBanner) setBanner(null)
    try {
      const data = await adminRequest<AdminDashboardData>('/site/admin/dashboard', apiKey)
      setDashboard(normalizeDashboard(data))
      setLastUpdated(new Date())
      void loadServiceMeta(apiKey)
    } catch (error) {
      if (error instanceof AdminRequestError && error.status === 401) {
        handleLogout()
        setAuthError(errorText(error))
        return
      }
      setBanner({ tone: 'error', message: errorText(error) })
    } finally {
      setRefreshing(false)
    }
  }

  async function runMutation(action: () => Promise<unknown>, successMessage: string, options: { closeTask?: boolean; refreshDetail?: boolean } = {}) {
    if (mutationBusy) return
    setMutationBusy(true)
    setBanner(null)
    try {
      await action()
      setDialog(null)
      if (options.closeTask) setSelectedTaskId(null)
      setBanner({ tone: 'success', message: successMessage })
      await refreshDashboard({ preserveBanner: true })
      if (options.refreshDetail) {
        setTaskDetail({ status: 'loading', data: null, error: '' })
        setTaskDetailRevision((current) => current + 1)
      }
    } catch (error) {
      if (error instanceof AdminRequestError && error.status === 401) {
        handleLogout()
        setAuthError(errorText(error))
        return
      }
      setBanner({ tone: 'error', message: errorText(error) })
    } finally {
      setMutationBusy(false)
    }
  }

  function submitCreateUser(values: { name: string; role: string; initialPoints: number }) {
    void runMutation(
      () => adminRequest('/site/admin/users', apiKey, {
        method: 'POST',
        body: JSON.stringify({ name: values.name, role: values.role, initial_points: values.initialPoints }),
      }),
      `已创建用户 ${values.name}。`,
    )
  }

  function submitEditUser(user: AdminUser, values: { name: string; role: string }) {
    void runMutation(
      () => adminRequest(`/site/admin/users/${encodeURIComponent(user.id)}`, apiKey, {
        method: 'PATCH',
        body: JSON.stringify({ name: values.name, role: values.role }),
      }),
      `已更新用户 ${values.name}。`,
    )
  }

  function submitPointAdjustment(user: AdminUser, delta: number, note: string) {
    void runMutation(
      () => adminRequest(`/site/admin/users/${encodeURIComponent(user.id)}/points`, apiKey, {
        method: 'POST',
        body: JSON.stringify({ delta, note: note || '后台人工调整' }),
      }),
      `已${delta > 0 ? '发放' : '扣减'} ${Math.abs(delta).toLocaleString('zh-CN')} 点。`,
    )
  }

  function submitRenameTask(task: AdminTask, title: string) {
    void runMutation(
      () => adminRequest(`/site/tasks/${encodeURIComponent(task.id)}`, apiKey, {
        method: 'PATCH',
        body: JSON.stringify({ title }),
      }),
      `任务已重命名为 ${title}。`,
      { refreshDetail: true },
    )
  }

  function submitTaskAction(action: 'start' | 'confirm' | 'delete', task: AdminTask) {
    const requests = {
      start: () => adminRequest(`/site/tasks/${encodeURIComponent(task.id)}/start`, apiKey, {
        method: 'POST',
        body: JSON.stringify({ confirm_points: true }),
      }),
      confirm: () => adminRequest(`/site/tasks/${encodeURIComponent(task.id)}/confirm`, apiKey, { method: 'POST' }),
      delete: () => adminRequest(`/site/tasks/${encodeURIComponent(task.id)}`, apiKey, { method: 'DELETE' }),
    }
    const messages = {
      start: '任务已进入处理队列。',
      confirm: '任务结果已确认。',
      delete: '任务已删除。',
    }
    void runMutation(requests[action], messages[action], { closeTask: action === 'delete', refreshDetail: action !== 'delete' })
  }

  async function exportTask(task: AdminTask, format: 'srt' | 'text' | 'doc') {
    if (exportBusy) return
    setExportBusy(true)
    setBanner(null)
    try {
      const response = await fetch(`/site/tasks/${encodeURIComponent(task.id)}/export?format=${format}`, {
        headers: { 'X-API-Key': apiKey },
      })
      if (!response.ok) {
        const raw = await response.text()
        let message = raw
        try {
          const parsed = JSON.parse(raw) as { detail?: string }
          message = parsed.detail || raw
        } catch {
          // Plain text responses are shown as-is.
        }
        throw new AdminRequestError(message || `导出失败：HTTP ${response.status}`, response.status)
      }
      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      const extension = format === 'text' ? 'txt' : format === 'doc' ? 'doc' : 'srt'
      anchor.href = objectUrl
      anchor.download = `${(task.title || task.source_name || task.id).replace(/[\\/:*?"<>|]/g, '_')}.${extension}`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(objectUrl)
      setBanner({ tone: 'success', message: '导出文件已生成。' })
    } catch (error) {
      if (error instanceof AdminRequestError && error.status === 401) {
        handleLogout()
        setAuthError(errorText(error))
      } else {
        setBanner({ tone: 'error', message: errorText(error) })
      }
    } finally {
      setExportBusy(false)
    }
  }

  if (sessionState !== 'ready' || !dashboard || !metrics) {
    return (
      <div className="admin-app">
        <ApiKeyGate
          value={apiKeyInput}
          checking={sessionState === 'checking'}
          error={authError}
          environment={currentEnvironment}
          onEnvironmentSwitch={switchEnvironment}
          onChange={setApiKeyInput}
          onSubmit={handleLogin}
        />
      </div>
    )
  }

  const totalTaskCount = Math.max(1, dashboard.tasks.length)
  const visibleUsers = filteredUsers.slice((userPage - 1) * PAGE_SIZE, userPage * PAGE_SIZE)
  const visibleTasks = filteredTasks.slice((taskPage - 1) * PAGE_SIZE, taskPage * PAGE_SIZE)
  const visibleLedger = filteredLedger.slice((ledgerPage - 1) * PAGE_SIZE, ledgerPage * PAGE_SIZE)
  const currentView = VIEW_CONFIG.find((item) => item.id === activeView) || VIEW_CONFIG[0]

  return (
    <div className="admin-app admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-brand admin-sidebar__brand">
          <span className="admin-brand__mark" aria-hidden="true"><LayoutDashboard size={20} /></span>
          <span><strong>RecordFlow</strong><small>管理控制台</small></span>
        </div>
        <EnvironmentSwitch current={currentEnvironment} onSwitch={switchEnvironment} />
        <nav className="admin-sidebar__nav" aria-label="管理模块">
          {VIEW_CONFIG.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              className={activeView === id ? 'is-active' : ''}
              aria-current={activeView === id ? 'page' : undefined}
              onClick={() => changeView(id)}
            >
              <Icon size={18} /> <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="admin-sidebar__footer">
          <span><span className="admin-connection-dot" /> 管理接口正常</span>
          <small>{serviceMeta?.service_name || 'RecordFlow'} · {environmentShortLabel(currentEnvironment)}</small>
        </div>
      </aside>

      <div className="admin-workspace">
        <header className="admin-topbar">
          <div>
            <currentView.icon size={19} />
            <strong>{currentView.label}</strong>
          </div>
          <nav className="admin-topbar__actions" aria-label="全局操作">
            <span className="admin-refresh-time">更新于 {lastUpdated ? formatDateTime(lastUpdated.toISOString()) : '—'}</span>
            <button className="admin-icon-button" type="button" onClick={() => void refreshDashboard()} disabled={refreshing} aria-label="刷新数据" title="刷新数据">
              <RefreshCw className={refreshing ? 'admin-spin' : ''} size={17} />
            </button>
            <button className="admin-icon-button admin-logout-button" type="button" onClick={handleLogout} aria-label="退出管理端" title="退出管理端">
              <LogOut size={17} />
            </button>
          </nav>
        </header>

        <main className="admin-main">
          {banner ? (
            <div className={`admin-banner admin-banner--${banner.tone}`} role={banner.tone === 'error' ? 'alert' : 'status'}>
              {banner.tone === 'error' ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
              <span>{banner.message}</span>
              <button type="button" onClick={() => setBanner(null)} aria-label="关闭提示" title="关闭提示"><X size={17} /></button>
            </div>
          ) : null}

          {activeView === 'overview' ? (
            <>
              <header className="admin-page-head">
                <div><h1>运营概览</h1><p>{environmentLabel(currentEnvironment)}的实时运行数据</p></div>
              </header>
              <section className="admin-metrics" aria-label="关键指标">
                <MetricCard icon={UsersRound} label="用户总数" value={metrics.users.toLocaleString('zh-CN')} hint={`${dashboard.agreements.length} 条协议记录`} />
                <MetricCard icon={FileAudio} label="任务总数" value={metrics.tasks.toLocaleString('zh-CN')} hint="全部历史任务" />
                <MetricCard
                  icon={Activity}
                  label="正在处理"
                  value={metrics.activeTasks.toLocaleString('zh-CN')}
                  hint={metrics.failedTasks ? `${metrics.failedTasks} 个异常任务` : '队列运行正常'}
                  tone={metrics.failedTasks ? 'danger' : 'active'}
                />
                <MetricCard icon={WalletCards} label="用户总余额" value={`${metrics.totalBalance.toLocaleString('zh-CN')} 点`} hint={`${metrics.ledgerEntries} 笔点数流水`} />
              </section>
              <section className="admin-overview-grid">
                <article className="admin-surface">
                  <header className="admin-surface__head"><div><h2>任务状态</h2><p>当前任务分布</p></div><strong>{dashboard.tasks.length}</strong></header>
                  <div className="admin-status-chart">
                    {statusCounts.length ? statusCounts.map((item) => (
                      <div className="admin-status-row" key={item.status}>
                        <div><StatusBadge status={item.status} /><strong>{item.count}</strong></div>
                        <span><i className={`admin-status-row__fill admin-status-row__fill--${statusTone(item.status)}`} style={{ width: `${Math.max(4, (item.count / totalTaskCount) * 100)}%` }} /></span>
                      </div>
                    )) : <div className="admin-empty"><FileAudio size={22} /><span>暂无任务数据</span></div>}
                  </div>
                </article>
                <article className="admin-surface">
                  <header className="admin-surface__head"><div><h2>需要关注</h2><p>异常和进行中任务</p></div><strong>{attentionTasks.length}</strong></header>
                  {attentionTasks.length ? (
                    <div className="admin-attention-list">
                      {attentionTasks.map((task) => (
                        <button type="button" key={task.id} onClick={() => openTask(task.id)}>
                          <span className={`admin-attention-icon admin-attention-icon--${statusTone(task.status)}`}>{task.status === 'failed' ? <AlertTriangle size={17} /> : <Clock3 size={17} />}</span>
                          <span><strong>{task.title || task.source_name}</strong><small>{userName(dashboard.users, task.user_id)} · {formatDateTime(task.updated_at)}</small></span>
                          <StatusBadge status={task.status} />
                        </button>
                      ))}
                    </div>
                  ) : <div className="admin-empty admin-empty--healthy"><CheckCircle2 size={23} /><span>没有待处理异常</span></div>}
                </article>
              </section>
              <section className="admin-surface">
                <header className="admin-surface__head"><div><h2>点数收支</h2><p>全部流水累计</p></div><button className="admin-text-button" type="button" onClick={() => changeView('ledger')}>查看流水 <ChevronRight size={16} /></button></header>
                <div className="admin-flow-summary">
                  <div><span><ArrowUpRight size={17} /> 累计入账</span><strong className="is-positive">+{metrics.pointCredits.toLocaleString('zh-CN')}</strong></div>
                  <div><span><ArrowDownRight size={17} /> 累计支出</span><strong className="is-negative">-{metrics.pointDebits.toLocaleString('zh-CN')}</strong></div>
                  <div><span><Coins size={17} /> 净变动</span><strong className={metrics.pointNet < 0 ? 'is-negative' : 'is-positive'}>{metrics.pointNet > 0 ? '+' : ''}{metrics.pointNet.toLocaleString('zh-CN')}</strong></div>
                </div>
              </section>
            </>
          ) : null}

          {activeView === 'users' ? (
            <>
              <header className="admin-page-head">
                <div><h1>用户管理</h1><p>共 {dashboard.users.length} 个账号</p></div>
                <button className="admin-primary-button" type="button" onClick={() => setDialog({ kind: 'create-user' })}><Plus size={17} /> 创建用户</button>
              </header>
              <section className="admin-surface admin-data-surface">
                <div className="admin-toolbar">
                  <label className="admin-search-field"><Search size={17} /><input type="search" value={userQuery} onChange={(event) => { setUserQuery(event.target.value); setUserPage(1) }} placeholder="搜索名称、ID 或角色" aria-label="搜索用户" /></label>
                  <label className="admin-select-field"><span className="admin-sr-only">筛选用户角色</span><select value={userRole} onChange={(event) => { setUserRole(event.target.value); setUserPage(1) }} aria-label="筛选用户角色"><option value="all">全部角色</option><option value="user">普通用户</option><option value="admin">管理员</option></select></label>
                  <span className="admin-toolbar__count">{filteredUsers.length} 条结果</span>
                </div>
                <div className="admin-table-wrap">
                  <table className="admin-table">
                    <thead><tr><th>用户</th><th>角色</th><th>点数余额</th><th className="admin-hide-mobile">任务数</th><th className="admin-hide-tablet">创建时间</th><th className="admin-actions-column">操作</th></tr></thead>
                    <tbody>
                      {visibleUsers.map((user) => {
                        const taskCount = dashboard.tasks.filter((task) => task.user_id === user.id).length
                        return (
                          <tr key={user.id}>
                            <td><button className="admin-cell-link admin-user-cell" type="button" onClick={() => setSelectedUserId(user.id)}><span className="admin-avatar"><UserRound size={16} /></span><span><strong>{user.name}</strong><small>{user.id}</small></span></button></td>
                            <td>{ROLE_LABELS[user.role] || user.role}</td>
                            <td><strong>{Number(user.points_balance || 0).toLocaleString('zh-CN')}</strong> 点</td>
                            <td className="admin-hide-mobile">{taskCount}</td>
                            <td className="admin-hide-tablet">{formatDateTime(user.created_at)}</td>
                            <td>
                              <div className="admin-row-actions">
                                <button className="admin-icon-button" type="button" onClick={() => setSelectedUserId(user.id)} aria-label={`查看 ${user.name}`} title="查看详情"><Eye size={16} /></button>
                                <button className="admin-icon-button" type="button" onClick={() => setDialog({ kind: 'edit-user', user })} aria-label={`编辑 ${user.name}`} title="编辑用户"><Edit3 size={16} /></button>
                                <button className="admin-icon-button" type="button" onClick={() => setDialog({ kind: 'adjust-points', user })} aria-label={`调整 ${user.name} 的点数`} title="调整点数"><Coins size={16} /></button>
                              </div>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                  {!visibleUsers.length ? <div className="admin-empty"><UsersRound size={22} /><span>没有匹配的用户</span></div> : null}
                </div>
                <Pagination page={userPage} pageSize={PAGE_SIZE} total={filteredUsers.length} onChange={setUserPage} />
              </section>
            </>
          ) : null}

          {activeView === 'tasks' ? (
            <>
              <header className="admin-page-head"><div><h1>任务管理</h1><p>共 {dashboard.tasks.length} 个任务</p></div></header>
              <section className="admin-surface admin-data-surface">
                <div className="admin-toolbar">
                  <label className="admin-search-field"><Search size={17} /><input type="search" value={taskQuery} onChange={(event) => { setTaskQuery(event.target.value); setTaskPage(1) }} placeholder="搜索任务、用户或异常" aria-label="搜索任务" /></label>
                  <label className="admin-select-field"><span className="admin-sr-only">筛选任务状态</span><select value={taskStatus} onChange={(event) => { setTaskStatus(event.target.value); setTaskPage(1) }} aria-label="筛选任务状态"><option value="all">全部状态</option>{statusCounts.map((item) => <option key={item.status} value={item.status}>{statusLabel(item.status)}（{item.count}）</option>)}</select></label>
                  <span className="admin-toolbar__count">{filteredTasks.length} 条结果</span>
                </div>
                <div className="admin-table-wrap">
                  <table className="admin-table">
                    <thead><tr><th>任务</th><th>用户</th><th>状态</th><th className="admin-hide-mobile">时长 / 点数</th><th className="admin-hide-tablet">更新时间</th><th className="admin-actions-column">操作</th></tr></thead>
                    <tbody>
                      {visibleTasks.map((task) => (
                        <tr key={task.id}>
                          <td><button className="admin-cell-link admin-task-cell" type="button" onClick={() => openTask(task.id)}><strong>{task.title || task.source_name}</strong><small>{task.source_name} · {formatBytes(task.original_size_bytes)}</small></button></td>
                          <td>{userName(dashboard.users, task.user_id)}</td>
                          <td><StatusBadge status={task.status} /></td>
                          <td className="admin-hide-mobile">{formatDuration(task.duration_seconds)}<small className="admin-table-subline">{task.points_cost} 点</small></td>
                          <td className="admin-hide-tablet">{formatDateTime(task.updated_at || task.created_at)}</td>
                          <td><div className="admin-row-actions"><button className="admin-icon-button" type="button" onClick={() => openTask(task.id)} aria-label={`查看 ${task.title || task.source_name}`} title="查看完整详情"><Eye size={16} /></button><button className="admin-icon-button" type="button" onClick={() => setDialog({ kind: 'rename-task', task })} aria-label={`重命名 ${task.title || task.source_name}`} title="重命名"><Edit3 size={16} /></button></div></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!visibleTasks.length ? <div className="admin-empty"><FileAudio size={22} /><span>没有匹配的任务</span></div> : null}
                </div>
                <Pagination page={taskPage} pageSize={PAGE_SIZE} total={filteredTasks.length} onChange={setTaskPage} />
              </section>
            </>
          ) : null}

          {activeView === 'ledger' ? (
            <>
              <header className="admin-page-head"><div><h1>点数流水</h1><p>共 {dashboard.point_ledger.length} 笔记录</p></div></header>
              <section className="admin-ledger-metrics">
                <div><span>累计入账</span><strong className="is-positive">+{metrics.pointCredits.toLocaleString('zh-CN')}</strong></div>
                <div><span>累计支出</span><strong className="is-negative">-{metrics.pointDebits.toLocaleString('zh-CN')}</strong></div>
                <div><span>净变动</span><strong className={metrics.pointNet < 0 ? 'is-negative' : 'is-positive'}>{metrics.pointNet > 0 ? '+' : ''}{metrics.pointNet.toLocaleString('zh-CN')}</strong></div>
              </section>
              <section className="admin-surface admin-data-surface">
                <div className="admin-toolbar">
                  <label className="admin-search-field"><Search size={17} /><input type="search" value={ledgerQuery} onChange={(event) => { setLedgerQuery(event.target.value); setLedgerPage(1) }} placeholder="搜索用户、备注或任务" aria-label="搜索点数流水" /></label>
                  <label className="admin-select-field"><span className="admin-sr-only">筛选流水类型</span><select value={ledgerKind} onChange={(event) => { setLedgerKind(event.target.value); setLedgerPage(1) }} aria-label="筛选流水类型"><option value="all">全部类型</option>{ledgerKinds.map((kind) => <option key={kind} value={kind}>{ledgerKindLabel(kind)}</option>)}</select></label>
                  <span className="admin-toolbar__count">{filteredLedger.length} 条结果</span>
                </div>
                <div className="admin-table-wrap">
                  <table className="admin-table">
                    <thead><tr><th>用户</th><th>变动</th><th>类型</th><th className="admin-hide-mobile">备注</th><th className="admin-hide-tablet">关联任务</th><th className="admin-hide-tablet">时间</th></tr></thead>
                    <tbody>
                      {visibleLedger.map((item) => (
                        <tr key={item.id}>
                          <td><button className="admin-cell-link" type="button" onClick={() => setSelectedUserId(item.user_id)}>{userName(dashboard.users, item.user_id)}</button></td>
                          <td><strong className={item.delta < 0 ? 'is-negative' : 'is-positive'}>{item.delta > 0 ? '+' : ''}{Number(item.delta).toLocaleString('zh-CN')}</strong></td>
                          <td>{ledgerKindLabel(item.kind)}</td>
                          <td className="admin-hide-mobile">{item.note || '—'}</td>
                          <td className="admin-hide-tablet">{item.task_id ? <button className="admin-cell-link admin-id-link" type="button" onClick={() => openTask(item.task_id || '')}>{item.task_id}</button> : '—'}</td>
                          <td className="admin-hide-tablet">{formatDateTime(item.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!visibleLedger.length ? <div className="admin-empty"><Coins size={22} /><span>没有匹配的流水</span></div> : null}
                </div>
                <Pagination page={ledgerPage} pageSize={PAGE_SIZE} total={filteredLedger.length} onChange={setLedgerPage} />
              </section>
            </>
          ) : null}
        </main>
      </div>

      {selectedUser && !dialog ? (
        <UserDetailDrawer
          user={selectedUser}
          tasks={dashboard.tasks}
          ledger={dashboard.point_ledger}
          agreements={dashboard.agreements}
          onClose={() => setSelectedUserId(null)}
          onEdit={() => setDialog({ kind: 'edit-user', user: selectedUser })}
          onAdjust={() => setDialog({ kind: 'adjust-points', user: selectedUser })}
          onOpenTask={(task) => {
            setSelectedUserId(null)
            openTask(task.id)
          }}
        />
      ) : null}

      {selectedTask && !dialog ? (
        <TaskDetailDrawer
          task={selectedTask}
          user={dashboard.users.find((user) => user.id === selectedTask.user_id)}
          detail={taskDetail}
          exportBusy={exportBusy}
          onClose={() => setSelectedTaskId(null)}
          onRename={() => setDialog({ kind: 'rename-task', task: selectedTask })}
          onAction={(action) => setDialog({ kind: 'task-action', action, task: selectedTask })}
          onExport={(format) => void exportTask(selectedTask, format)}
        />
      ) : null}

      {dialog?.kind === 'create-user' ? <UserFormDialog busy={mutationBusy} onClose={() => setDialog(null)} onSubmit={submitCreateUser} /> : null}
      {dialog?.kind === 'edit-user' ? <UserFormDialog user={dialog.user} busy={mutationBusy} onClose={() => setDialog(null)} onSubmit={(values) => submitEditUser(dialog.user, values)} /> : null}
      {dialog?.kind === 'adjust-points' ? <PointAdjustmentDialog user={dialog.user} busy={mutationBusy} onClose={() => setDialog(null)} onSubmit={(delta, note) => submitPointAdjustment(dialog.user, delta, note)} /> : null}
      {dialog?.kind === 'rename-task' ? <RenameTaskDialog task={dialog.task} busy={mutationBusy} onClose={() => setDialog(null)} onSubmit={(title) => submitRenameTask(dialog.task, title)} /> : null}
      {dialog?.kind === 'task-action' ? <TaskActionDialog action={dialog.action} task={dialog.task} busy={mutationBusy} onClose={() => setDialog(null)} onConfirm={() => submitTaskAction(dialog.action, dialog.task)} /> : null}
    </div>
  )
}
