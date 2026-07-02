import { AudioLines, Pause, Play, Rewind, StepForward } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

export type SiteMedia = {
  id: string
  url?: string
  public_url: string
  source_name: string
  stored_name: string
  content_type: string
}

export type SiteUtterance = {
  id?: string
  text: string
  start_time: number
  end_time: number
  words: Array<{ text: string; start_time: number; end_time: number }>
}

export type SiteTask = {
  id: string
  title: string
  source_name: string
  status: string
  points_cost: number
  charge_basis: string
  duration_seconds: number
  error: string | null
  media: SiteMedia | null
}

export type SiteTaskEditor = {
  utterances: SiteUtterance[]
}

type ProofreaderProps = {
  task: SiteTask
  editor: SiteTaskEditor
  draftText: string
  onDraftTextChange: (value: string) => void
  onSave: (utterances: SiteUtterance[], value: string) => void
}

type SiteWord = SiteUtterance['words'][number]

function normalizeSegmentText(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

function rebuildDraftFromSegments(segments: string[]): string {
  return segments.map((item) => item.trim()).join('\n')
}

function splitDraftLines(text: string | null | undefined): string[] {
  return (text || '')
    .split('\n')
    .map((item) => normalizeSegmentText(item))
    .filter(Boolean)
}

function normalizeUtteranceText(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

function splitEditorLines(text: string): string[] {
  return text
    .split('\n')
    .map((item) => normalizeUtteranceText(item))
    .filter(Boolean)
}

function utteranceDisplayText(utterance: SiteUtterance): string {
  if (utterance.words?.length) {
    const joined = utterance.words.map((word) => normalizeSegmentText(word.text)).filter(Boolean).join('')
    if (joined) return joined
  }
  return normalizeSegmentText(utterance.text)
}

function distributeTimeRange(startTime: number, endTime: number, pieces: string[]): Array<{ start_time: number; end_time: number }> {
  if (pieces.length === 0) return []
  if (pieces.length === 1) {
    return [{ start_time: startTime, end_time: Math.max(startTime, endTime) }]
  }
  const safeEnd = Math.max(startTime, endTime)
  const total = Math.max(1, safeEnd - startTime)
  const totalWeight = Math.max(1, pieces.reduce((sum, item) => sum + Math.max(1, item.length), 0))
  let cursor = startTime
  return pieces.map((piece, index) => {
    if (index === pieces.length - 1) {
      return { start_time: cursor, end_time: safeEnd }
    }
    const slice = Math.max(1, Math.round((total * Math.max(1, piece.length)) / totalWeight))
    const nextEnd = Math.min(safeEnd, cursor + slice)
    const range = { start_time: cursor, end_time: nextEnd }
    cursor = nextEnd
    return range
  })
}

function rebuildWordsFromText(utterance: SiteUtterance, nextText: string): SiteWord[] {
  const pieces = splitEditorLines(nextText)
  if (pieces.length === 0) return []
  const ranges = distributeTimeRange(utterance.start_time, utterance.end_time, pieces)
  return pieces.map((piece, index) => ({
    text: piece,
    start_time: ranges[index]?.start_time ?? utterance.start_time,
    end_time: ranges[index]?.end_time ?? utterance.end_time,
  }))
}

function rebuildUtterancesFromEdit(
  utterances: SiteUtterance[],
  index: number,
  editedValue: string,
): SiteUtterance[] {
  const base = utterances[index]
  if (!base) return utterances
  const pieces = splitEditorLines(editedValue)
  const before = utterances.slice(0, index)
  const after = utterances.slice(index + 1)
  if (pieces.length === 0) {
    return [...before, ...after]
  }
  const ranges = distributeTimeRange(base.start_time || 0, base.end_time || 0, pieces)
  const replacement = pieces.map((piece, pieceIndex) => {
    const startTime = ranges[pieceIndex]?.start_time ?? base.start_time ?? 0
    const endTime = ranges[pieceIndex]?.end_time ?? base.end_time ?? 0
    const nextBase: SiteUtterance = {
      ...base,
      id: pieceIndex === 0 ? base.id : `${base.id || `utt-${index}`}-split-${pieceIndex}`,
      text: piece,
      start_time: startTime,
      end_time: endTime,
      words: [],
    }
    return {
      ...nextBase,
      words: rebuildWordsFromText(nextBase, piece),
    }
  })
  return [...before, ...replacement, ...after]
}

export function ProofreaderWorkspace({
  task,
  editor,
  draftText,
  onDraftTextChange,
  onSave,
}: ProofreaderProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const listRef = useRef<HTMLDivElement | null>(null)
  const lastTaskIdRef = useRef(task.id)
  const shouldAutoScrollRef = useRef(false)
  const lastPlaybackScrollIndexRef = useRef<number | null>(null)
  const rateMenuCloseTimerRef = useRef<number | null>(null)
  const propUtterances = editor.utterances || []
  const [manualIndex, setManualIndex] = useState(0)
  const [playbackIndex, setPlaybackIndex] = useState(-1)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
  const [hoveredWordKey, setHoveredWordKey] = useState<string | null>(null)
  const [playing, setPlaying] = useState(false)
  const [localUtterances, setLocalUtterances] = useState<SiteUtterance[]>(propUtterances)
  const [segmentDrafts, setSegmentDrafts] = useState<string[]>([])
  const [editingOriginalText, setEditingOriginalText] = useState('')
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [playbackRate, setPlaybackRate] = useState(1)
  const [rateMenuOpen, setRateMenuOpen] = useState(false)

  const utterances = localUtterances
  const displayUtterances = utterances
  const canEdit = ['completed', 'confirmed'].includes(task.status)
  const mediaUrl = task.media?.url || task.media?.public_url || ''
  const activeIndex = playing && playbackIndex >= 0 ? playbackIndex : manualIndex
  const utteranceSignature = useMemo(
    () =>
      propUtterances
        .map(
          (utterance) =>
            `${utterance.start_time}:${utterance.end_time}:${utteranceDisplayText(utterance)}:${(utterance.words || [])
              .map((word) => `${word.start_time}-${word.end_time}-${word.text}`)
              .join(',')}`,
        )
        .join('|'),
    [propUtterances],
  )

  useEffect(() => {
    setLocalUtterances(propUtterances)
    const fallbackDraftLines = splitDraftLines(draftText)
    let baseDrafts: string[] = []

    if (propUtterances.length > 0) {
      if (fallbackDraftLines.length === propUtterances.length) {
        baseDrafts = fallbackDraftLines
      } else {
        baseDrafts = propUtterances.map((utterance) => utteranceDisplayText(utterance))
      }
    } else {
      baseDrafts = fallbackDraftLines
    }

    setSegmentDrafts(baseDrafts)
    const isTaskChanged = lastTaskIdRef.current !== task.id
    lastTaskIdRef.current = task.id
    if (isTaskChanged) {
      setManualIndex(0)
      setPlaybackIndex(-1)
    } else {
      setManualIndex((current) => Math.min(Math.max(0, current), Math.max(0, propUtterances.length - 1)))
      setPlaybackIndex((current) => (current < 0 ? -1 : Math.min(current, Math.max(0, propUtterances.length - 1))))
    }
    setEditingIndex(null)
    setEditingOriginalText('')
    lastPlaybackScrollIndexRef.current = null
  }, [propUtterances, task.id, utteranceSignature])

  useEffect(() => {
    onDraftTextChange(rebuildDraftFromSegments(segmentDrafts))
  }, [segmentDrafts, onDraftTextChange])

  useEffect(() => {
    if (!shouldAutoScrollRef.current) return
    const rows = listRef.current?.querySelectorAll<HTMLElement>('[data-segment-row]')
    const active = rows?.[manualIndex]
    active?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    shouldAutoScrollRef.current = false
  }, [manualIndex])

  useEffect(() => {
    if (editingIndex !== null || !playing || playbackIndex < 0) return
    const container = listRef.current
    if (!container) return
    if (lastPlaybackScrollIndexRef.current === playbackIndex) return
    const rows = container.querySelectorAll<HTMLElement>('[data-segment-row]')
    const active = rows?.[playbackIndex]
    if (!active) return

    const containerRect = container.getBoundingClientRect()
    const activeRect = active.getBoundingClientRect()
    const topThreshold = containerRect.top + 56
    const bottomThreshold = containerRect.bottom - 56
    const above = activeRect.top < topThreshold
    const below = activeRect.bottom > bottomThreshold

    if (!above && !below) return

    const targetTop = active.offsetTop - container.clientHeight / 2 + active.clientHeight / 2
    const nextTop = Math.max(0, targetTop)
    if (typeof container.scrollTo === 'function') {
      container.scrollTo({
        top: nextTop,
        behavior: 'auto',
      })
    } else {
      container.scrollTop = nextTop
    }
    lastPlaybackScrollIndexRef.current = playbackIndex
  }, [editingIndex, playbackIndex, playing])

  useEffect(() => {
    if (utterances.length === 0) {
      setPlaybackIndex(-1)
      return
    }
    const nowMs = currentTime * 1000
    const activeIndex = utterances.findIndex((utterance, index) => {
      const start = Math.max(0, utterance.start_time || 0)
      const end = Math.max(start, utterance.end_time || start)
      const nextStart = utterances[index + 1]?.start_time
      const upperBound = end > start ? end : (typeof nextStart === 'number' ? nextStart : end + 1)
      return nowMs >= start && nowMs < upperBound
    })
    setPlaybackIndex(activeIndex)
  }, [currentTime, utterances])

  function isWordActive(utteranceIndex: number, startMs: number, endMs: number) {
    if (utteranceIndex !== activeIndex) return false
    const nowMs = currentTime * 1000
    return nowMs >= startMs && nowMs <= endMs
  }

  function jumpToIndex(index: number, autoplay = false) {
    const utterance = displayUtterances[index]
    if (!utterance) return
    shouldAutoScrollRef.current = true
    setManualIndex(index)
    setPlaybackIndex(index)
    setCurrentTime(utterance.start_time / 1000)
    if (audioRef.current) {
      audioRef.current.currentTime = utterance.start_time / 1000
      if (autoplay) {
        void audioRef.current.play()
        setPlaying(true)
      }
    }
  }

  function togglePlayPause() {
    if (!audioRef.current) return
    if (audioRef.current.paused) {
      void audioRef.current.play()
      setPlaying(true)
      return
    }
    audioRef.current.pause()
    setPlaying(false)
  }

  function jumpToTime(seconds: number, autoplay = false) {
    if (!audioRef.current) return
    audioRef.current.currentTime = Math.max(0, seconds)
    setCurrentTime(Math.max(0, seconds))
    if (autoplay) {
      void audioRef.current.play()
      setPlaying(true)
    }
  }

  function skipRelative(seconds: number) {
    if (!audioRef.current) return
    const next = Math.max(0, audioRef.current.currentTime + seconds)
    audioRef.current.currentTime = next
    setCurrentTime(next)
  }

  function persistSegment(index: number, value: string) {
    const nextUtterances = rebuildUtterancesFromEdit(utterances, index, value)
    const nextSegments = nextUtterances.map((item) => item.text)
    setLocalUtterances(nextUtterances)
    setSegmentDrafts(nextSegments)
    onSave(nextUtterances, rebuildDraftFromSegments(nextSegments))
  }

  function startEditing(index: number) {
    shouldAutoScrollRef.current = true
    setManualIndex(index)
    setEditingIndex(index)
    setEditingOriginalText(segmentDrafts[index] || utteranceDisplayText(utterances[index] || { text: '', start_time: 0, end_time: 0, words: [] }))
  }

  function cancelEditing() {
    if (editingIndex !== null) {
      setSegmentDrafts((current) =>
        current.map((item, index) => (index === editingIndex ? editingOriginalText : item)),
      )
    }
    setEditingIndex(null)
    setEditingOriginalText('')
  }

  function confirmEditing(index: number) {
    persistSegment(index, segmentDrafts[index] || '')
    setEditingIndex(null)
    setEditingOriginalText('')
  }

  function saveEditingOnBlur(index: number) {
    if (editingIndex !== index) return
    confirmEditing(index)
  }

  function handleSegmentKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>, index: number) {
    if (event.key === 'Escape') {
      cancelEditing()
      return
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      confirmEditing(index)
      return
    }
    if (event.key === 'Tab') {
      event.preventDefault()
      confirmEditing(index)
      const nextIndex = event.shiftKey ? Math.max(0, index - 1) : Math.min(utterances.length - 1, index + 1)
      jumpToIndex(nextIndex, false)
      startEditing(nextIndex)
    }
  }

  useEffect(() => {
    if (!audioRef.current) return
    audioRef.current.playbackRate = playbackRate
  }, [playbackRate])

  useEffect(() => {
    return () => {
      if (rateMenuCloseTimerRef.current !== null) {
        window.clearTimeout(rateMenuCloseTimerRef.current)
      }
    }
  }, [])

  function openRateMenu() {
    if (rateMenuCloseTimerRef.current !== null) {
      window.clearTimeout(rateMenuCloseTimerRef.current)
      rateMenuCloseTimerRef.current = null
    }
    setRateMenuOpen(true)
  }

  function scheduleCloseRateMenu() {
    if (rateMenuCloseTimerRef.current !== null) {
      window.clearTimeout(rateMenuCloseTimerRef.current)
    }
    rateMenuCloseTimerRef.current = window.setTimeout(() => {
      setRateMenuOpen(false)
      rateMenuCloseTimerRef.current = null
    }, 300)
  }

  return (
    <div className="proofreader-shell">
      <section className="proofreader-scroll-area">
        <div className="panel transcript-panel">
          {utterances.length === 0 ? (
            <div className="empty-card">当前任务还没有句级时间戳。</div>
          ) : (
            <div className="segment-list" ref={listRef}>
              {utterances.map((utterance, index) => {
                const selected = index === activeIndex
                const editing = index === editingIndex
                const wordModeActive = hoveredIndex === index
                return (
                  <div
                    key={`${task.id}-${index}`}
                    data-segment-row
                    className={`segment-card ${selected ? 'selected' : ''} ${editing ? 'editing' : ''} ${wordModeActive ? 'word-mode-active' : ''}`}
                    onMouseEnter={() => setHoveredIndex(index)}
                    onMouseLeave={() => {
                      setHoveredIndex((current) => (current === index ? null : current))
                      setHoveredWordKey((current) => (current?.startsWith(`${task.id}-${index}-`) ? null : current))
                    }}
                    onClick={() => jumpToIndex(index, true)}
                    onDoubleClick={() => {
                      if (canEdit) startEditing(index)
                    }}
                  >
                    <div className="segment-time">
                      <AudioLines size={15} />
                      <span>{formatDuration(utterance.start_time / 1000)}</span>
                    </div>
                    {editing ? (
                      <div className="segment-editing">
                        <textarea
                          aria-label={`编辑第 ${index + 1} 句`}
                          value={segmentDrafts[index] || ''}
                          onChange={(event) =>
                            setSegmentDrafts((current) =>
                              current.map((item, itemIndex) => (itemIndex === index ? event.target.value : item)),
                            )
                          }
                          onKeyDown={(event) => handleSegmentKeyDown(event, index)}
                          onBlur={() => saveEditingOnBlur(index)}
                          autoFocus
                        />
                        <div className="segment-inline-actions">
                          <button type="button" className="ghost-button" onClick={() => cancelEditing()}>
                            取消
                          </button>
                          <button type="button" onClick={() => confirmEditing(index)}>
                            确认
                          </button>
                        </div>
                      </div>
                    ) : (
                    <div className={`segment-text ${displayUtterances[index]?.words.length > 0 ? 'segment-text-tokenized' : ''}`}>
                      {displayUtterances[index]?.words.length > 0 ? (
                          displayUtterances[index].words.map((word, wordIndex) => (
                            <button
                              key={`${task.id}-${index}-${wordIndex}`}
                              type="button"
                              className={`segment-word ${isWordActive(index, word.start_time, word.end_time) ? 'active' : ''} ${
                                hoveredWordKey === `${task.id}-${index}-${wordIndex}` ? 'hovered' : ''
                              }`}
                              aria-label={`词块 ${word.text}`}
                              data-token-visible={wordModeActive ? 'true' : 'false'}
                              onMouseEnter={() => setHoveredWordKey(`${task.id}-${index}-${wordIndex}`)}
                              onMouseLeave={() =>
                                setHoveredWordKey((current) =>
                                  current === `${task.id}-${index}-${wordIndex}` ? null : current,
                                )
                              }
                              onClick={(event) => {
                                event.stopPropagation()
                                setManualIndex(index)
                                if (word.start_time > 0 || word.end_time > 0) {
                                  setPlaybackIndex(index)
                                  jumpToTime(word.start_time / 1000, true)
                                }
                              }}
                            >
                              {word.text}
                            </button>
                          ))
                        ) : (
                          <span>{utteranceDisplayText(displayUtterances[index]) || '空白句'}</span>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </section>

      <section className="bottom-player-bar">
        <div className="bottom-player-main">
          <div className="bottom-player-title">
            <strong>{task.source_name}</strong>
          </div>
          {mediaUrl ? (
            <audio
              ref={audioRef}
              preload="metadata"
              src={mediaUrl}
              onLoadedMetadata={() => {
                setDuration(audioRef.current?.duration || 0)
                setCurrentTime(audioRef.current?.currentTime || 0)
              }}
              onTimeUpdate={() => setCurrentTime(audioRef.current?.currentTime || 0)}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              className="sr-only-audio"
            />
          ) : null}
          <div className="bottom-player-progress">
            <span>{formatDuration(currentTime)}</span>
            <input
              type="range"
              min={0}
              max={Math.max(duration, 0)}
              step={0.1}
              value={Math.min(currentTime, Math.max(duration, 0))}
              onChange={(event) => jumpToTime(Number(event.target.value), false)}
              disabled={!mediaUrl}
            />
            <span>{formatDuration(duration)}</span>
          </div>
          <div className="bottom-player-controls">
            <button type="button" className="ghost-button icon-button" onClick={() => skipRelative(-2)} disabled={!mediaUrl}>
              <Rewind size={16} />
            </button>
            <button type="button" onClick={togglePlayPause} disabled={!mediaUrl}>
              {playing ? <Pause size={16} /> : <Play size={16} />}
              {playing ? '暂停' : '播放'}
            </button>
            <button
              type="button"
              className="ghost-button icon-button"
              onClick={() => jumpToIndex(Math.min(utterances.length - 1, activeIndex + 1), true)}
              disabled={!mediaUrl || utterances.length === 0}
            >
              <StepForward size={16} />
            </button>
            <div
              className="player-rate-menu-shell"
              onMouseEnter={openRateMenu}
              onMouseLeave={scheduleCloseRateMenu}
            >
              {rateMenuOpen ? (
                <div className="player-rate-popover">
                  <div className="player-rate-options">
                    {[0.75, 1, 1.25, 1.5, 2, 2.5, 3].map((rate) => (
                      <button
                        key={rate}
                        type="button"
                        className={`player-rate-option ${playbackRate === rate ? 'selected' : ''}`}
                        onClick={() => {
                          setPlaybackRate(rate)
                          setRateMenuOpen(false)
                        }}
                      >
                        {rate}x
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              <button
                type="button"
                className="ghost-button player-rate-trigger"
                aria-label="倍速菜单"
                disabled={!mediaUrl}
                onClick={openRateMenu}
                onFocus={openRateMenu}
              >
                {playbackRate}x
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
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
