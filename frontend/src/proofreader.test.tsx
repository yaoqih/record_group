import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import { ProofreaderWorkspace, type SiteTask, type SiteTaskEditor } from './proofreader'

function buildTask(): SiteTask {
  return {
    id: 'task-1',
    title: '测试任务',
    source_name: 'audio.ogg',
    status: 'completed',
    points_cost: 3,
    charge_basis: '125.0s -> 3 points',
    duration_seconds: 125,
    error: null,
    media: {
      id: 'media-1',
      url: 'https://cdn.example.com/audio.ogg',
      public_url: 'https://example.com/audio.ogg',
      source_name: 'audio.ogg',
      stored_name: 'audio.compressed.ogg',
      content_type: 'audio/ogg',
    },
  }
}

function buildEditor(overrides: Partial<SiteTaskEditor> = {}): SiteTaskEditor {
  return {
    utterances: [
      { text: '第一句', start_time: 0, end_time: 1000, words: [] },
      { text: '第二句', start_time: 1000, end_time: 2200, words: [] },
    ],
    ...overrides,
  }
}

describe('ProofreaderWorkspace', () => {
  test('single click selects and highlights the segment, double click enters edit mode', async () => {
    const user = userEvent.setup()
    const onDraftTextChange = vi.fn()
    render(
      <ProofreaderWorkspace
        task={buildTask()}
        editor={buildEditor()}
        draftText={'第一句\n第二句'}
        onDraftTextChange={onDraftTextChange}
        onSave={vi.fn()}
      />,
    )

    const secondSegment = screen.getByText('第二句').closest('[data-segment-row]')
    expect(secondSegment).not.toBeNull()
    await user.click(secondSegment!)
    await waitFor(() => expect(secondSegment).toHaveClass('selected'))

    await user.dblClick(secondSegment!)
    expect(screen.getByLabelText('编辑第 2 句')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument()
  })

  test('editing auto-saves and playback rate is applied from the hover menu immediately', async () => {
    const user = userEvent.setup()
    const onDraftTextChange = vi.fn()
    render(
      <ProofreaderWorkspace
        task={buildTask()}
        editor={buildEditor()}
        draftText={'第一句\n第二句'}
        onDraftTextChange={onDraftTextChange}
        onSave={vi.fn()}
      />,
    )

    await user.dblClick(screen.getByText('第二句').closest('[data-segment-row]')!)
    const editor = screen.getByLabelText('编辑第 2 句')
    await user.clear(editor)
    await user.type(editor, '第二句-修改')
    await user.tab()

    expect(onDraftTextChange).toHaveBeenCalled()
    const audio = document.querySelector('audio') as HTMLAudioElement
    expect(audio.playbackRate).toBe(1)

    await user.click(screen.getByRole('button', { name: '倍速菜单' }))
    await user.click(screen.getByRole('button', { name: '3x' }))

    await waitFor(() => expect(audio.playbackRate).toBe(3))
  })

  test('blur saves rebuilt corrected text from current segments', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(
      <ProofreaderWorkspace
        task={buildTask()}
        editor={buildEditor()}
        draftText={'第一句\n第二句'}
        onDraftTextChange={vi.fn()}
        onSave={onSave}
      />,
    )

    await user.dblClick(screen.getByText('第二句').closest('[data-segment-row]')!)
    const editor = screen.getByLabelText('编辑第 2 句')
    await user.clear(editor)
    await user.type(editor, '第二句-自动保存')
    await user.tab()

    expect(onSave).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({ text: '第一句' }),
        expect.objectContaining({ text: '第二句-自动保存' }),
      ]),
      '第一句\n第二句-自动保存',
    )
  })

  test('editing one sentence with line breaks creates merged sentence structure payload', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(
      <ProofreaderWorkspace
        task={buildTask()}
        editor={buildEditor()}
        draftText={'第一句\n第二句'}
        onDraftTextChange={vi.fn()}
        onSave={onSave}
      />,
    )

    await user.dblClick(screen.getByText('第二句').closest('[data-segment-row]')!)
    const editor = screen.getByLabelText('编辑第 2 句')
    await user.clear(editor)
    await user.type(editor, '第二句前半{shift>}{enter}{/shift}第二句后半')
    await user.tab()

    expect(onSave).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({ text: '第一句' }),
        expect.objectContaining({ text: '第二句前半' }),
        expect.objectContaining({ text: '第二句后半' }),
      ]),
      '第一句\n第二句前半\n第二句后半',
    )
  })

  test('editing one sentence only patches that sentence boundary instead of rebuilding all utterances', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(
      <ProofreaderWorkspace
        task={buildTask()}
        editor={{
          utterances: [
            { id: 'u1', text: '第一句', start_time: 0, end_time: 1000, words: [] },
            { id: 'u2', text: '第二句', start_time: 1000, end_time: 2200, words: [] },
            { id: 'u3', text: '第三句', start_time: 2200, end_time: 3200, words: [] },
          ],
        }}
        draftText={'第一句\n第二句\n第三句'}
        onDraftTextChange={vi.fn()}
        onSave={onSave}
      />,
    )

    await user.dblClick(screen.getByText('第二句').closest('[data-segment-row]')!)
    const editor = screen.getByLabelText('编辑第 2 句')
    await user.clear(editor)
    await user.type(editor, '第二句前半{shift>}{enter}{/shift}第二句后半')
    await user.tab()

    expect(onSave).toHaveBeenCalledWith(
      [
        expect.objectContaining({ id: 'u1', text: '第一句' }),
        expect.objectContaining({ id: 'u2', text: '第二句前半' }),
        expect.objectContaining({ text: '第二句后半' }),
        expect.objectContaining({ id: 'u3', text: '第三句' }),
      ],
      '第一句\n第二句前半\n第二句后半\n第三句',
    )
  })

  test('confirming an edit immediately updates the visible preview text', async () => {
    const user = userEvent.setup()
    render(
      <ProofreaderWorkspace
        task={buildTask()}
        editor={buildEditor()}
        draftText={'第一句\n第二句'}
        onDraftTextChange={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    await user.dblClick(screen.getByText('第二句').closest('[data-segment-row]')!)
    const editor = screen.getByLabelText('编辑第 2 句')
    await user.clear(editor)
    await user.type(editor, '第二句-立即同步')
    await user.click(screen.getByRole('button', { name: '确认' }))

    expect(screen.getByText((content) => content.includes('第二句-立即同步'))).toBeInTheDocument()
  })

  test('editing a tokenized sentence keeps preview driven by updated words instead of falling back to stale text mode', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(
      <ProofreaderWorkspace
        task={buildTask()}
        editor={{
          utterances: [
            {
              text: '你好世界',
              start_time: 0,
              end_time: 1200,
              words: [
                { text: '你好', start_time: 0, end_time: 400 },
                { text: '世界', start_time: 400, end_time: 1200 },
              ],
            },
          ],
        }}
        draftText={'你好世界'}
        onDraftTextChange={vi.fn()}
        onSave={onSave}
      />,
    )

    await user.dblClick(screen.getByRole('button', { name: '词块 世界' }).closest('[data-segment-row]')!)
    const editor = screen.getByLabelText('编辑第 1 句')
    await user.clear(editor)
    await user.type(editor, '你好宇宙')
    await user.click(screen.getByRole('button', { name: '确认' }))

    expect(onSave).toHaveBeenCalledWith(
      [
        expect.objectContaining({
          text: '你好宇宙',
          words: [expect.objectContaining({ text: '你好宇宙', start_time: 0, end_time: 1200 })],
        }),
      ],
      '你好宇宙',
    )
    expect(onSave.mock.calls[0]?.[0]?.[0]?.words?.[0]?.text).toBe('你好宇宙')
  })

  test('playback time update automatically advances the selected sentence highlight', async () => {
    render(
      <ProofreaderWorkspace
        task={buildTask()}
        editor={{
          utterances: [
            { text: '第一句', start_time: 0, end_time: 1000, words: [] },
            { text: '第二句', start_time: 1000, end_time: 2200, words: [] },
          ],
        }}
        draftText={'第一句\n第二句'}
        onDraftTextChange={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    const audio = document.querySelector('audio') as HTMLAudioElement
    Object.defineProperty(audio, 'currentTime', { configurable: true, value: 1.4 })
    audio.dispatchEvent(new Event('play'))
    audio.dispatchEvent(new Event('timeupdate'))

    await waitFor(() => expect(screen.getByText('第二句').closest('[data-segment-row]')).toHaveClass('selected'))
  })

  test('playback-driven sentence advance does not auto-scroll the list repeatedly', async () => {
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    })

    render(
      <ProofreaderWorkspace
        task={buildTask()}
        editor={{
          utterances: [
            { text: '第一句', start_time: 0, end_time: 1000, words: [] },
            { text: '第二句', start_time: 1000, end_time: 2200, words: [] },
          ],
        }}
        draftText={'第一句\n第二句'}
        onDraftTextChange={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    const audio = document.querySelector('audio') as HTMLAudioElement
    Object.defineProperty(audio, 'currentTime', { configurable: true, value: 1.4 })
    audio.dispatchEvent(new Event('play'))
    audio.dispatchEvent(new Event('timeupdate'))

    await waitFor(() => expect(screen.getByText('第二句').closest('[data-segment-row]')).toHaveClass('selected'))
    expect(scrollIntoView).not.toHaveBeenCalled()
  })

  test('playback-driven sentence advance only performs minimal container scroll near viewport edge', async () => {
    const scrollTo = vi.fn()
    render(
      <ProofreaderWorkspace
        task={buildTask()}
        editor={{
          utterances: [
            { text: '第一句', start_time: 0, end_time: 1000, words: [] },
            { text: '第二句', start_time: 1000, end_time: 2200, words: [] },
          ],
        }}
        draftText={'第一句\n第二句'}
        onDraftTextChange={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    const list = document.querySelector('.segment-list') as HTMLDivElement
    const rows = list.querySelectorAll<HTMLElement>('[data-segment-row]')
    Object.defineProperty(list, 'scrollTo', { configurable: true, value: scrollTo })
    Object.defineProperty(list, 'clientHeight', { configurable: true, value: 200 })
    Object.defineProperty(rows[1], 'offsetTop', { configurable: true, value: 260 })
    Object.defineProperty(rows[1], 'clientHeight', { configurable: true, value: 40 })
    Object.defineProperty(list, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ top: 0, bottom: 200 }),
    })
    Object.defineProperty(rows[1], 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ top: 180, bottom: 230 }),
    })

    const audio = document.querySelector('audio') as HTMLAudioElement
    Object.defineProperty(audio, 'currentTime', { configurable: true, value: 1.4 })
    audio.dispatchEvent(new Event('play'))
    audio.dispatchEvent(new Event('timeupdate'))

    await waitFor(() => expect(screen.getByText('第二句').closest('[data-segment-row]')).toHaveClass('selected'))
    expect(scrollTo).toHaveBeenCalled()
  })

  test('editing textarea and outside preview stay on the same draft version', async () => {
    const user = userEvent.setup()
    render(
      <ProofreaderWorkspace
        task={buildTask()}
        editor={buildEditor()}
        draftText={'第一句\n第二句'}
        onDraftTextChange={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    await user.dblClick(screen.getByText('第二句').closest('[data-segment-row]')!)
    const editor = screen.getByLabelText('编辑第 2 句')
    await user.clear(editor)
    await user.type(editor, '第二句-同步中')

    expect(screen.getByDisplayValue('第二句-同步中')).toBeInTheDocument()
    expect(screen.getByText('第二句-同步中')).toBeInTheDocument()
  })

  test('hovering a segment reveals inline ASR word blocks for precise seeking', async () => {
    const user = userEvent.setup()
    render(
      <ProofreaderWorkspace
        task={{
          ...buildTask(),
        }}
        editor={{
          utterances: [
            { text: '第一句', start_time: 0, end_time: 500, words: [] },
            {
              text: '你好世界',
              start_time: 500,
              end_time: 1700,
              words: [
                { text: '你', start_time: 500, end_time: 700 },
                { text: '好', start_time: 700, end_time: 900 },
                { text: '世界', start_time: 900, end_time: 1700 },
              ],
            },
          ],
        }}
        draftText={'第一句\n你好世界'}
        onDraftTextChange={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    const segment = screen.getByRole('button', { name: '词块 世界' }).closest('[data-segment-row]')
    expect(segment).not.toBeNull()
    expect(segment).not.toHaveClass('word-mode-active')
    expect(screen.getByRole('button', { name: '词块 世界' })).toHaveAttribute('data-token-visible', 'false')

    await user.hover(segment!)

    expect(segment).toHaveClass('word-mode-active')
    expect(screen.getByRole('button', { name: '词块 世界' })).toHaveAttribute('data-token-visible', 'true')
  })

  test('only the hovered token shows hovered styling instead of the whole sentence', async () => {
    const user = userEvent.setup()
    render(
      <ProofreaderWorkspace
        task={{
          ...buildTask(),
        }}
        editor={{
          utterances: [
            {
              text: '你好世界',
              start_time: 0,
              end_time: 1200,
              words: [
                { text: '你好', start_time: 0, end_time: 400 },
                { text: '世界', start_time: 400, end_time: 1200 },
              ],
            },
          ],
        }}
        draftText={'你好世界'}
        onDraftTextChange={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    const segment = screen.getByRole('button', { name: '词块 世界' }).closest('[data-segment-row]')
    await user.hover(segment!)

    const firstToken = screen.getByRole('button', { name: '词块 你好' })
    const secondToken = screen.getByRole('button', { name: '词块 世界' })
    await user.hover(firstToken)

    expect(firstToken).toHaveClass('hovered')
    expect(secondToken).not.toHaveClass('hovered')
  })

  test('audio playback prefers media url over public_url', () => {
    render(
      <ProofreaderWorkspace
        task={buildTask()}
        editor={buildEditor()}
        draftText={'第一句\n第二句'}
        onDraftTextChange={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    const audio = document.querySelector('audio') as HTMLAudioElement
    expect(audio.getAttribute('src')).toBe('https://cdn.example.com/audio.ogg')
  })

})
