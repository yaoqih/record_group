import { describe, expect, test, vi } from 'vitest'
import {
  ADMIN_ENVIRONMENTS,
  AdminRequestError,
  adminEnvironmentUrl,
  adminRequest,
  attentionAdminTasks,
  deriveAdminMetrics,
  filterAdminPointLedger,
  filterAdminTasks,
  filterAdminUsers,
  isAdminPath,
  recentAdminPointLedger,
  resolveAdminEnvironment,
  taskStatusCounts,
  type AdminDashboardData,
  type AdminTask,
  type AdminUser,
} from './admin'

const users: AdminUser[] = [
  { id: 'usr-1', name: '王小明', role: 'user', points_balance: 80 },
  { id: 'usr-2', name: '运营账号', role: 'admin', points_balance: 20 },
]

function task(overrides: Partial<AdminTask> = {}): AdminTask {
  return {
    id: 'task-1',
    user_id: 'usr-1',
    title: '客户访谈',
    source_name: 'interview.m4a',
    status: 'completed',
    points_cost: 3,
    duration_seconds: 125,
    created_at: '2026-07-10T10:00:00+08:00',
    updated_at: '2026-07-10T10:10:00+08:00',
    ...overrides,
  }
}

describe('admin dashboard helpers', () => {
  test('recognizes every /admin route without changing the operator workspace route', () => {
    expect(isAdminPath('/admin')).toBe(true)
    expect(isAdminPath('/admin/overview')).toBe(true)
    expect(isAdminPath('/administrator')).toBe(false)
    expect(isAdminPath('/')).toBe(false)
  })

  test('derives task and point metrics from dashboard data', () => {
    const data: AdminDashboardData = {
      users,
      tasks: [task(), task({ id: 'active', status: 'transcribing' }), task({ id: 'bad', status: 'failed' })],
      point_ledger: [
        { id: 'l1', user_id: 'usr-1', delta: 120, kind: 'recharge' },
        { id: 'l2', user_id: 'usr-1', delta: -20, kind: 'consume' },
      ],
      agreements: [
        { user_id: 'usr-1', agreement_version: 'v2', accepted_at: '2026-07-10T09:00:00+08:00', client: 'miniapp' },
      ],
    }

    expect(deriveAdminMetrics(data)).toEqual({
      users: 2,
      tasks: 3,
      activeTasks: 1,
      failedTasks: 1,
      totalBalance: 100,
      pointCredits: 120,
      pointDebits: 20,
      pointNet: 100,
      ledgerEntries: 2,
    })
  })

  test('filters users and tasks across user names, task fields and status', () => {
    const tasks = [
      task(),
      task({ id: 'task-2', user_id: 'usr-2', title: '周会', status: 'failed', error: 'ASR timeout' }),
    ]

    expect(filterAdminUsers(users, '运营').map((item) => item.id)).toEqual(['usr-2'])
    expect(filterAdminTasks(tasks, users, '王小明', 'all').map((item) => item.id)).toEqual(['task-1'])
    expect(filterAdminTasks(tasks, users, 'timeout', 'failed').map((item) => item.id)).toEqual(['task-2'])
    expect(filterAdminTasks(tasks, users, '', 'completed').map((item) => item.id)).toEqual(['task-1'])
  })

  test('puts failed attention tasks first and returns stable status statistics', () => {
    const tasks = [
      task({ id: 'active', status: 'queued', updated_at: '2026-07-11T09:00:00+08:00' }),
      task({ id: 'bad', status: 'failed', updated_at: '2026-07-10T09:00:00+08:00' }),
      task({ id: 'done', status: 'confirmed' }),
    ]

    expect(attentionAdminTasks(tasks).map((item) => item.id)).toEqual(['bad', 'active'])
    expect(taskStatusCounts(tasks)).toEqual([
      { status: 'failed', count: 1 },
      { status: 'queued', count: 1 },
      { status: 'confirmed', count: 1 },
    ])
  })

  test('filters point ledger by searchable fields, kind and direction', () => {
    const entries = [
      {
        id: 'ledger-credit',
        user_id: 'usr-1',
        delta: 100,
        kind: 'recharge',
        note: '人工补点',
        created_at: '2026-07-11T10:00:00+08:00',
      },
      {
        id: 'ledger-debit',
        user_id: 'usr-2',
        delta: -3,
        kind: 'consume',
        task_id: 'task-weekly',
        created_at: '2026-07-12T10:00:00+08:00',
      },
    ]

    expect(filterAdminPointLedger(entries, users, '王小明', 'all', 'all').map((item) => item.id))
      .toEqual(['ledger-credit'])
    expect(filterAdminPointLedger(entries, users, 'task-weekly', 'consume', 'debit').map((item) => item.id))
      .toEqual(['ledger-debit'])
    expect(filterAdminPointLedger(entries, users, '', 'recharge', 'credit').map((item) => item.id))
      .toEqual(['ledger-credit'])
    expect(filterAdminPointLedger(entries, users, '', 'all', 'credit').map((item) => item.id))
      .toEqual(['ledger-credit'])
  })

  test('sorts recent point ledger entries without mutating the source list', () => {
    const entries = [
      { id: 'older', user_id: 'usr-1', delta: 1, kind: 'recharge', created_at: '2026-07-10T10:00:00+08:00' },
      { id: 'newer', user_id: 'usr-1', delta: -1, kind: 'consume', created_at: '2026-07-12T10:00:00+08:00' },
      { id: 'undated', user_id: 'usr-1', delta: 2, kind: 'reward' },
    ]

    expect(recentAdminPointLedger(entries).map((item) => item.id)).toEqual(['newer', 'older', 'undated'])
    expect(entries.map((item) => item.id)).toEqual(['older', 'newer', 'undated'])
  })
})

describe('admin environments', () => {
  test('exposes the staging and production service contract', () => {
    expect(ADMIN_ENVIRONMENTS.staging).toEqual({
      id: 'staging',
      label: '测试环境',
      hostname: 'test-record.blenet.top',
      origin: 'https://test-record.blenet.top',
    })
    expect(ADMIN_ENVIRONMENTS.production.hostname).toBe('record-api.blenet.top')
  })

  test('resolves known hosts and keeps localhost addresses local', () => {
    expect(resolveAdminEnvironment('test-record.blenet.top')).toBe('staging')
    expect(resolveAdminEnvironment('record-api.blenet.top')).toBe('production')
    expect(resolveAdminEnvironment('LOCALHOST:5173')).toBe('local')
    expect(resolveAdminEnvironment('127.0.0.1')).toBe('local')
    expect(resolveAdminEnvironment('[::1]:5173')).toBe('local')
    expect(resolveAdminEnvironment('preview.example.com')).toBe('local')
  })

  test('uses recognized server metadata before the browser hostname', () => {
    expect(resolveAdminEnvironment('record-api.blenet.top', 'staging')).toBe('staging')
    expect(resolveAdminEnvironment('test-record.blenet.top', 'prod')).toBe('production')
    expect(resolveAdminEnvironment('test-record.blenet.top', 'unexpected')).toBe('staging')
    expect(resolveAdminEnvironment('record-api.blenet.top', 'development')).toBe('local')
  })

  test('builds absolute admin URLs for switchable environments', () => {
    expect(adminEnvironmentUrl('staging')).toBe('https://test-record.blenet.top/admin')
    expect(adminEnvironmentUrl('production', '/admin/tasks?status=failed'))
      .toBe('https://record-api.blenet.top/admin/tasks?status=failed')
    expect(adminEnvironmentUrl('production', 'admin')).toBe('https://record-api.blenet.top/admin')
  })
})

describe('adminRequest', () => {
  test('attaches the API key header to requests', async () => {
    const fetcher = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(new Headers(init?.headers).get('X-API-Key')).toBe('secret-key')
      return new Response('{"users":[],"tasks":[],"point_ledger":[]}', {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }) as typeof fetch

    const result = await adminRequest<AdminDashboardData>('/site/admin/dashboard', 'secret-key', {}, fetcher)
    expect(result.tasks).toEqual([])
    expect(fetcher).toHaveBeenCalledOnce()
  })

  test('surfaces API authentication errors without exposing the key', async () => {
    const fetcher = vi.fn(async () => new Response('{"detail":"Invalid or missing X-API-Key."}', {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    })) as typeof fetch

    await expect(adminRequest('/site/admin/dashboard', 'wrong-key', {}, fetcher)).rejects.toEqual(
      expect.objectContaining<Partial<AdminRequestError>>({ status: 401, message: 'Invalid or missing X-API-Key.' }),
    )
  })
})
