const MAX_AUDIO_BYTES = 200 * 1024 * 1024
const MAX_UPLOAD_FILES = 9
const AUDIO_EXTENSIONS = ['.aac', '.aif', '.aiff', '.flac', '.m4a', '.mp3', '.oga', '.ogg', '.opus', '.pcm', '.wav', '.webm']
const AUDIO_PICKER_EXTENSIONS = AUDIO_EXTENSIONS.map((extension) => extension.slice(1))

function buildUploadSelection(tempFiles, batchId = Date.now()) {
  const files = Array.isArray(tempFiles) ? tempFiles.slice(0, MAX_UPLOAD_FILES) : []
  const queue = []
  const uploadable = []

  files.forEach((file, index) => {
    const name = String(file && file.name ? file.name : `录音文件 ${index + 1}`)
    const sizeBytes = Math.max(0, Number((file && file.size) || 0))
    const filePath = String((file && (file.path || file.tempFilePath)) || '')
    const error = audioFileValidationError({ name, size: sizeBytes, path: filePath })
    queue.push({
      id: `${batchId}-${index}`,
      name,
      sizeLabel: formatFileSize(sizeBytes),
      status: error ? 'failed' : 'queued',
      statusLabel: error ? '不可上传' : '等待上传',
      progress: 0,
      progressLabel: error ? '' : '等待',
      progressStatus: error ? 'error' : '',
      error
    })
    if (!error) {
      uploadable.push({ queueIndex: index, filePath, name, sizeBytes })
    }
  })

  return {
    queue,
    uploadable,
    invalidCount: queue.length - uploadable.length
  }
}

function audioFileValidationError(file) {
  const name = String((file && file.name) || '').trim()
  const lowerName = name.toLowerCase()
  if (!name || !AUDIO_EXTENSIONS.some((extension) => lowerName.endsWith(extension))) {
    return '仅支持常用音频文件'
  }
  if (!String((file && file.path) || '').trim()) return '无法读取该文件'
  if (Number((file && file.size) || 0) > MAX_AUDIO_BYTES) return '文件不能超过 200MB'
  return ''
}

function formatFileSize(sizeBytes) {
  const bytes = Math.max(0, Number(sizeBytes || 0))
  if (bytes >= 1024 * 1024) return `${formatNumber(bytes / (1024 * 1024))} MB`
  if (bytes >= 1024) return `${formatNumber(bytes / 1024)} KB`
  return `${Math.round(bytes)} B`
}

function formatNumber(value) {
  if (value >= 100) return String(Math.round(value))
  return value.toFixed(1).replace(/\.0$/, '')
}

function normalizeUploadProgress(value) {
  const progress = Number(value || 0)
  if (!Number.isFinite(progress)) return 0
  return Math.max(0, Math.min(100, Math.round(progress)))
}

module.exports = {
  AUDIO_EXTENSIONS,
  AUDIO_PICKER_EXTENSIONS,
  MAX_AUDIO_BYTES,
  MAX_UPLOAD_FILES,
  audioFileValidationError,
  buildUploadSelection,
  formatFileSize,
  normalizeUploadProgress
}
