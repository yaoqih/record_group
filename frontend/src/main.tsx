import { createElement, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { isAdminPath } from './admin.ts'

async function bootstrap() {
  if (!isAdminPath(window.location.pathname)) {
    window.location.replace('/admin')
    return
  }

  const appModule = await import('./AdminApp.tsx')
  createRoot(document.getElementById('root')!).render(createElement(StrictMode, null, createElement(appModule.default)))
}

void bootstrap()
