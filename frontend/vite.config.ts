/// <reference types="vitest/config" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/site': 'http://127.0.0.1:8000',
      '/workspaces': 'http://127.0.0.1:8000',
      '/jobs': 'http://127.0.0.1:8000',
      '/dashboard': 'http://127.0.0.1:8000',
      '/review': 'http://127.0.0.1:8000',
      '/state': 'http://127.0.0.1:8000',
      '/agreement': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
})
