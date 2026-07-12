import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import AdminApp from './AdminApp'
import { ADMIN_API_KEY_STORAGE_KEY, type AdminDashboardData } from './admin'

const dashboard: AdminDashboardData = {
  users: [
    {
      id: 'usr-1',
      name: '测试用户',
      role: 'user',
      points_balance: 98,
      created_at: '2026-07-10T08:00:00+08:00',
      updated_at: '2026-07-11T08:00:00+08:00',
    },
  ],
  tasks: [
    {
      id: 'task-1',
      user_id: 'usr-1',
      workspace_id: 'workspace-1',
      media_id: 'media-1',
      job_id: 'job-1',
      title: '客户访谈',
      source_name: 'interview.m4a',
      content_type: 'audio/mp4',
      status: 'completed',
      points_cost: 2,
      charge_basis: '92s -> 2 points',
      agreement_version: 'v2',
      duration_seconds: 92,
      original_size_bytes: 1024,
      created_at: '2026-07-11T08:00:00+08:00',
      updated_at: '2026-07-11T08:10:00+08:00',
      completed_at: '2026-07-11T08:10:00+08:00',
    },
  ],
  point_ledger: [
    {
      id: 'ledger-1',
      user_id: 'usr-1',
      delta: 100,
      kind: 'recharge',
      note: '首次充值',
      created_at: '2026-07-10T08:00:00+08:00',
    },
  ],
  agreements: [
    {
      user_id: 'usr-1',
      agreement_version: 'v2',
      accepted_at: '2026-07-10T08:00:00+08:00',
      client: 'wechat-miniapp',
    },
  ],
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function defaultResponse(url: string): Response {
  if (url.includes('/site/admin/meta')) {
    return jsonResponse({ environment: 'development', service_name: 'RecordFlow', server_time: '2026-07-12T00:00:00Z' })
  }
  if (url.includes('/editor')) {
    return jsonResponse({
      task: dashboard.tasks[0],
      editor: {
        utterances: [
          { speaker: '说话人 1', start_time: 0, end_time: 4200, text: '这是一段完整的访谈转写。' },
        ],
      },
    })
  }
  return jsonResponse(dashboard)
}

describe('AdminApp', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.history.replaceState({}, '', '/admin')
    vi.restoreAllMocks()
  })

  test('validates the API key, shows the environment and navigates between management views', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      void init
      return defaultResponse(String(url))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AdminApp />)

    expect(screen.getByRole('heading', { name: '管理员登录' })).toBeInTheDocument()
    expect(screen.getByLabelText('当前为本地环境')).toBeInTheDocument()
    await user.type(screen.getByLabelText('API Key'), 'admin-secret')
    await user.click(screen.getByRole('button', { name: '进入管理端' }))

    expect(await screen.findByRole('heading', { name: '运营概览' })).toBeInTheDocument()
    expect(window.localStorage.getItem(ADMIN_API_KEY_STORAGE_KEY)).toBe('admin-secret')
    const dashboardCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/site/admin/dashboard'))
    expect(new Headers(dashboardCall?.[1]?.headers).get('X-API-Key')).toBe('admin-secret')

    await user.click(screen.getByRole('button', { name: '任务管理' }))
    expect(screen.getByRole('heading', { name: '任务管理' })).toBeInTheDocument()
    expect(screen.getByText('客户访谈')).toBeInTheDocument()
    await user.type(screen.getByLabelText('搜索任务'), '不存在的任务')
    expect(screen.getByText('没有匹配的任务')).toBeInTheDocument()
  })

  test('adjusts points in both directions through the audited admin endpoint', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (String(url).includes('/site/admin/users/usr-1/points')) {
        expect(init?.method).toBe('POST')
        expect(JSON.parse(String(init?.body))).toEqual({ delta: -8, note: '后台人工调整' })
        return jsonResponse({ user: { ...dashboard.users[0], points_balance: 90 } })
      }
      return defaultResponse(String(url))
    })
    vi.stubGlobal('fetch', fetchMock)
    window.localStorage.setItem(ADMIN_API_KEY_STORAGE_KEY, 'stored-secret')

    render(<AdminApp />)
    expect(await screen.findByRole('heading', { name: '运营概览' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '用户管理' }))
    await user.click(screen.getByRole('button', { name: '调整 测试用户 的点数' }))

    expect(screen.getByRole('dialog', { name: '调整 测试用户 的点数' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '扣减' }))
    const pointsInput = screen.getByRole('spinbutton', { name: '点数' })
    await user.clear(pointsInput)
    await user.type(pointsInput, '8')
    await user.click(screen.getByRole('button', { name: '确认扣减' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/points'))).toBe(true))
    const adjustmentCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/points'))
    expect(new Headers(adjustmentCall?.[1]?.headers).get('X-API-Key')).toBe('stored-secret')
  })

  test('creates a user with role and initial points', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (String(url).endsWith('/site/admin/users')) {
        expect(init?.method).toBe('POST')
        expect(JSON.parse(String(init?.body))).toEqual({ name: '运营账号', role: 'admin', initial_points: 50 })
        return jsonResponse({ user: { id: 'usr-2', name: '运营账号', role: 'admin', points_balance: 50 } })
      }
      return defaultResponse(String(url))
    })
    vi.stubGlobal('fetch', fetchMock)
    window.localStorage.setItem(ADMIN_API_KEY_STORAGE_KEY, 'stored-secret')

    render(<AdminApp />)
    await screen.findByRole('heading', { name: '运营概览' })
    await user.click(screen.getByRole('button', { name: '用户管理' }))
    await user.click(screen.getByRole('button', { name: '创建用户' }))
    await user.type(screen.getByRole('textbox', { name: '用户名称' }), '运营账号')
    await user.selectOptions(screen.getByRole('combobox', { name: '账号角色' }), 'admin')
    const pointsInput = screen.getByRole('spinbutton', { name: '初始点数' })
    await user.clear(pointsInput)
    await user.type(pointsInput, '50')
    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/site/admin/users'))).toBe(true))
  })

  test('loads complete task details and renames a task', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (String(url).endsWith('/site/tasks/task-1') && init?.method === 'PATCH') {
        expect(JSON.parse(String(init.body))).toEqual({ title: '更新后的访谈' })
        return jsonResponse({ task: { ...dashboard.tasks[0], title: '更新后的访谈' } })
      }
      return defaultResponse(String(url))
    })
    vi.stubGlobal('fetch', fetchMock)
    window.localStorage.setItem(ADMIN_API_KEY_STORAGE_KEY, 'stored-secret')

    render(<AdminApp />)
    await screen.findByRole('heading', { name: '运营概览' })
    await user.click(screen.getByRole('button', { name: '任务管理' }))
    await user.click(screen.getByRole('button', { name: '查看 客户访谈' }))

    expect(await screen.findByRole('dialog', { name: '客户访谈' })).toBeInTheDocument()
    expect(await screen.findByText('这是一段完整的访谈转写。')).toBeInTheDocument()
    expect(screen.getByText('workspace-1')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '重命名' }))
    const titleInput = screen.getByRole('textbox', { name: '任务名称' })
    await user.clear(titleInput)
    await user.type(titleInput, '更新后的访谈')
    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/site/tasks/task-1') && init?.method === 'PATCH')).toBe(true))
  })
})
