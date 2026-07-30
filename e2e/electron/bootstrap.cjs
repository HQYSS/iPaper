const { app, BrowserWindow } = require('electron')
const path = require('node:path')

// Electron removes the app entrypoint from process.argv on some platforms.
// The preload path is deliberately passed as the final bootstrap argument.
const preloadPath = path.resolve(process.argv[process.argv.length - 1])

app.whenReady().then(() => {
  const window = new BrowserWindow({
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: preloadPath,
    },
  })

  window.loadURL(
    'data:text/html;charset=utf-8,' +
      encodeURIComponent('<!doctype html><html><body><main>iPaper Electron E2E</main></body></html>'),
  )
})

app.on('window-all-closed', () => app.quit())
