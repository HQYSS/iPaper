const { app, BrowserWindow, shell } = require('electron')
const path = require('path')
const { spawn } = require('child_process')

const isDev = process.argv.includes('--dev') || process.env.NODE_ENV === 'development'
const BACKEND_URL = 'http://127.0.0.1:3000/'

let mainWindow
let backendProcess

function startBackend() {
  const backendPath = path.join(__dirname, '..', 'backend')
  const sharedEnv = {
    ...process.env,
    IPAPER_SYNC_ROLE: 'client',
  }

  if (isDev) {
    backendProcess = spawn('python', ['main.py'], {
      cwd: backendPath,
      stdio: 'inherit',
      env: sharedEnv,
    })
  } else {
    const backendExe = process.platform === 'win32' ? 'ipaper-backend.exe' : 'ipaper-backend'
    const backendExePath = path.join(process.resourcesPath, 'backend', backendExe)

    backendProcess = spawn(backendExePath, [], {
      cwd: path.dirname(backendExePath),
      stdio: 'inherit',
      env: sharedEnv,
    })
  }

  backendProcess.on('error', (err) => {
    console.error('Failed to start backend:', err)
  })

  backendProcess.on('exit', (code) => {
    console.log(`Backend process exited with code ${code}`)
  })
}

async function waitForBackend(maxRetries = 30) {
  const http = require('http')

  for (let i = 0; i < maxRetries; i++) {
    try {
      await new Promise((resolve, reject) => {
        const req = http.get(BACKEND_URL, (res) => resolve(res))
        req.on('error', reject)
        req.setTimeout(1000, () => {
          req.destroy()
          reject(new Error('Timeout'))
        })
      })
      console.log('Backend is ready')
      return
    } catch {
      console.log(`Waiting for backend... (${i + 1}/${maxRetries})`)
      await new Promise((resolve) => setTimeout(resolve, 1000))
    }
  }

  throw new Error('Backend failed to start')
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 600,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 15, y: 15 },
  })

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'frontend', 'dist', 'index.html'))
  }

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

app.whenReady().then(async () => {
  startBackend()

  try {
    await waitForBackend()
    createWindow()
  } catch (err) {
    console.error('Failed to start:', err)
    app.quit()
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  if (backendProcess) {
    backendProcess.kill()
  }
})

