const test = require('node:test')
const assert = require('node:assert/strict')

const {
  MAX_AUDIO_BYTES,
  MAX_UPLOAD_FILES,
  AUDIO_PICKER_EXTENSIONS,
  buildUploadSelection,
  normalizeUploadProgress
} = require('../utils/upload')

test('buildUploadSelection keeps valid audio files and explains rejected files', () => {
  const selection = buildUploadSelection([
    { path: '/tmp/meeting.mp3', name: 'meeting.mp3', size: 1024 },
    { path: '/tmp/notes.txt', name: 'notes.txt', size: 100 },
    { path: '/tmp/large.wav', name: 'large.wav', size: MAX_AUDIO_BYTES + 1 }
  ], 123)

  assert.equal(selection.queue.length, 3)
  assert.equal(selection.uploadable.length, 1)
  assert.equal(selection.invalidCount, 2)
  assert.equal(selection.uploadable[0].queueIndex, 0)
  assert.equal(selection.queue[0].status, 'queued')
  assert.equal(selection.queue[1].status, 'failed')
  assert.match(selection.queue[1].error, /音频/)
  assert.match(selection.queue[2].error, /200MB/)
})

test('buildUploadSelection enforces the batch limit without exposing file paths to the view', () => {
  const files = Array.from({ length: MAX_UPLOAD_FILES + 2 }, (_, index) => ({
    path: `/tmp/${index}.m4a`,
    name: `${index}.m4a`,
    size: index + 1
  }))
  const selection = buildUploadSelection(files, 456)

  assert.equal(selection.queue.length, MAX_UPLOAD_FILES)
  assert.equal(selection.uploadable.length, MAX_UPLOAD_FILES)
  assert.equal(Object.hasOwn(selection.queue[0], 'filePath'), false)
})

test('normalizeUploadProgress clamps and rounds progress values', () => {
  assert.equal(normalizeUploadProgress(-2), 0)
  assert.equal(normalizeUploadProgress(42.6), 43)
  assert.equal(normalizeUploadProgress(102), 100)
  assert.equal(normalizeUploadProgress('invalid'), 0)
})

test('picker extensions use the format required by wx.chooseMessageFile', () => {
  assert.ok(AUDIO_PICKER_EXTENSIONS.includes('mp3'))
  assert.equal(AUDIO_PICKER_EXTENSIONS.some((extension) => extension.startsWith('.')), false)
})
