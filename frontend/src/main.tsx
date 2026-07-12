import { createElement, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { isAdminPath } from './admin.ts'

async function bootstrap() {
  const appModule = isAdminPath(window.location.pathname)
    ? await import('./AdminApp.tsx')
    : await import('./App.tsx')
  createRoot(document.getElementById('root')!).render(createElement(StrictMode, null, createElement(appModule.default)))
}

void bootstrap()
