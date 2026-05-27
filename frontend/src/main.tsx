import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import { setupOfflineListeners } from './services/offlineApi'
import { reportClientLog } from './services/api'

window.addEventListener('error', (event) => {
  reportClientLog('error', event.message || 'window error', {
    source: event.filename,
    line: event.lineno,
    column: event.colno,
    stack: event.error?.stack,
  })
})

window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason
  reportClientLog('error', reason?.message || 'unhandled promise rejection', {
    stack: reason?.stack,
  })
})

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    const swUrl = `${import.meta.env.BASE_URL}sw.js`
    navigator.serviceWorker.register(swUrl).catch((error) => {
      reportClientLog('warning', 'service worker registration failed', {
        swUrl,
        error: (error as Error).message,
      })
    })
  })
}

setupOfflineListeners()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

