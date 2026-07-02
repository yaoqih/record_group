import { describe, expect, test } from 'vitest'
import {
  isTaskActive,
  mergeTaskSummary,
  parseUploadTaskResponse,
  normalizeTaskTitleInput,
  requestJson,
  resolveSelectedTask,
  shouldLoadTaskWorkspace,
  shouldPollSelectedTask,
  taskExportUrl,
} from './App'
import type { SiteTask } from './proofreader'

function buildTask(overrides: Partial<SiteTask> = {}): SiteTask {
  return {
    id: 'task-1',
    title: '测试任务',
    source_name: 'audio.ogg',
    status: 'completed',
    points_cost: 2,
    charge_basis: '61.0s -> 2 points',
    duration_seconds: 61,
    error: null,
    media: null,
    ...overrides,
  }
}

describe('App logic helpers', () => {
  test('isTaskActive only returns true for in-flight statuses', () => {
    expect(isTaskActive(buildTask({ status: 'uploaded' }))).toBe(true)
    expect(isTaskActive(buildTask({ status: 'starting' }))).toBe(true)
    expect(isTaskActive(buildTask({ status: 'queued' }))).toBe(true)
    expect(isTaskActive(buildTask({ status: 'transcribing' }))).toBe(true)
    expect(isTaskActive(buildTask({ status: 'completed' }))).toBe(false)
    expect(isTaskActive(buildTask({ status: 'confirmed' }))).toBe(false)
    expect(isTaskActive(buildTask({ status: 'failed' }))).toBe(false)
  })

  test('mergeTaskSummary preserves heavy editor payload when list api returns lightweight summary', () => {
    const previous = buildTask({
      media: {
        id: 'm1',
        url: 'https://cdn.example.com/audio.ogg',
        public_url: 'https://public.example.com/audio.ogg',
        source_name: 'audio.ogg',
        stored_name: 'audio.compressed.ogg',
        content_type: 'audio/ogg',
      },
    })
    const incoming = buildTask({
      media: null,
    })

    const merged = mergeTaskSummary(previous, incoming)
    expect(merged.media?.id).toBe('m1')
  })

  test('shouldLoadTaskWorkspace only loads workspace data for editable or active tasks', () => {
    expect(shouldLoadTaskWorkspace(buildTask({ status: 'completed' }))).toBe(true)
    expect(shouldLoadTaskWorkspace(buildTask({ status: 'confirmed' }))).toBe(true)
    expect(shouldLoadTaskWorkspace(buildTask({ status: 'transcribing' }))).toBe(true)
    expect(shouldLoadTaskWorkspace(buildTask({ status: 'failed' }))).toBe(false)
    expect(shouldLoadTaskWorkspace(buildTask({ status: 'uploaded' }))).toBe(true)
    expect(shouldLoadTaskWorkspace(null)).toBe(false)
  })

  test('shouldPollSelectedTask only polls the currently selected active task', () => {
    const tasks = [
      buildTask({ id: 'done', status: 'completed' }),
      buildTask({ id: 'live', status: 'transcribing' }),
    ]

    expect(shouldPollSelectedTask(tasks, 'live')?.id).toBe('live')
    expect(shouldPollSelectedTask(tasks, 'done')).toBeNull()
    expect(shouldPollSelectedTask(tasks, '')).toBeNull()
  })

  test('parseUploadTaskResponse surfaces json error details instead of generic parse failure', () => {
    expect(() =>
      parseUploadTaskResponse(400, 'Bad Request', '{"detail":"点数不足"}', 'application/json'),
    ).toThrow('点数不足')
  })

  test('parseUploadTaskResponse falls back to raw response text when body is not json', () => {
    expect(() =>
      parseUploadTaskResponse(502, 'Bad Gateway', '<html>upstream timeout</html>', 'text/html'),
    ).toThrow('upstream timeout')
  })

  test('resolveSelectedTask does not auto-fallback to the first completed task', () => {
    const tasks = [buildTask({ id: 'done-1' }), buildTask({ id: 'done-2', status: 'confirmed' })]
    expect(resolveSelectedTask(tasks, '')).toBeNull()
    expect(resolveSelectedTask(tasks, 'missing')).toBeNull()
  })

  test('normalizeTaskTitleInput trims whitespace and rejects empty values', () => {
    expect(normalizeTaskTitleInput('  新名字.m4a  ')).toBe('新名字.m4a')
    expect(normalizeTaskTitleInput('   ')).toBe('')
  })

  test('taskExportUrl builds encoded download URLs', () => {
    expect(taskExportUrl('task 1/客户', 'srt')).toBe('/site/tasks/task%201%2F%E5%AE%A2%E6%88%B7/export?format=srt')
    expect(taskExportUrl('task-1', 'text')).toBe('/site/tasks/task-1/export?format=text')
  })

  test('requestJson surfaces non-json error bodies as readable messages', async () => {
    const originalFetch = globalThis.fetch
    globalThis.fetch = (() =>
      Promise.resolve(
        new Response('Internal Server Error', {
          status: 500,
          headers: { 'Content-Type': 'text/plain' },
        }),
      )) as typeof fetch

    await expect(requestJson('/site/tasks')).rejects.toThrow('Internal Server Error')
    globalThis.fetch = originalFetch
  })
})
