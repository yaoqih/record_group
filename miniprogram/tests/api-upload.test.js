const test = require('node:test')
const assert = require('node:assert/strict')

test('uploadTask reports transfer and finalization progress', async () => {
  const requests = []
  global.wx = {
    getStorageSync(key) {
      if (key === 'recordflow_token') return 'token'
      if (key === 'recordflow_agreement_acceptance') {
        return { version: 'v2', accepted: true }
      }
      return ''
    },
    request(options) {
      requests.push(options.url)
      queueMicrotask(() => {
        if (options.url.endsWith('/direct-upload/init')) {
          options.success({
            statusCode: 200,
            data: {
              upload_token: 'upload-token',
              upload: {
                url: 'https://cos.example/upload',
                method: 'POST',
                file_field: 'file',
                form_data: {},
                object_key: 'pending/meeting.mp3'
              }
            }
          })
          return
        }
        options.success({ statusCode: 200, data: { task: { id: 'task-1' } } })
      })
    },
    uploadFile(options) {
      return {
        onProgressUpdate(callback) {
          queueMicrotask(() => {
            callback({ progress: 37, totalBytesSent: 370, totalBytesExpectedToSend: 1000 })
            options.success({ statusCode: 204, data: '' })
          })
        }
      }
    }
  }

  delete require.cache[require.resolve('../utils/config')]
  delete require.cache[require.resolve('../utils/agreement')]
  delete require.cache[require.resolve('../utils/api')]
  const api = require('../utils/api')
  const progressEvents = []
  const result = await api.uploadTask('/tmp/meeting.mp3', 'meeting.mp3', 1000, {
    onProgress: (detail) => progressEvents.push(detail)
  })

  assert.equal(result.task.id, 'task-1')
  assert.deepEqual(progressEvents.map((event) => [event.phase, event.progress]), [
    ['preparing', 0],
    ['uploading', 37],
    ['finalizing', 100],
    ['complete', 100]
  ])
  assert.equal(requests.length, 2)
  delete global.wx
})
