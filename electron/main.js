const { app, BrowserWindow, shell } = require('electron')
const path = require('path')
const fs = require('fs')
const { spawn } = require('child_process')

const isDev = process.argv.includes('--dev') || process.env.NODE_ENV === 'development'
// iPaper.app/Contents/MacOS/iPaper.sh 启动时已经自己起了一个 uvicorn 后端，传 --skip-backend
// 让 main.js 不要再 spawn 一个 python main.py 重复绑 3000 端口。
const SKIP_BACKEND = process.argv.includes('--skip-backend')
const BACKEND_URL = 'http://127.0.0.1:3000/'

// 顶部菜单栏显示成 iPaper（默认会跟着 Electron.app 的 CFBundleName 显示成 "Electron"）。
// Dock 显示的图标 label 由 Electron.app/Contents/Info.plist 的 CFBundleName 决定，那个由
// iPaper.sh 启动前 patch；这里 setName 主要影响 macOS 应用菜单 "About iPaper" 之类。
app.setName('iPaper')

const SINGLE_INSTANCE_LOCK = app.requestSingleInstanceLock()

let mainWindow
let backendProcess

if (!SINGLE_INSTANCE_LOCK) {
  app.quit()
}

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
  if (!SINGLE_INSTANCE_LOCK) return

  // macOS Dock 图标：iPaper.app 是 AppleScript applet 包装，applet.icns 只决定 Finder
  // 里和"未启动时"的 Dock 图标。Electron 启动后 Dock 图标会被 Electron 进程接管，默认
  // 是灰齿轮，必须显式 dock.setIcon 才能用我们设计的紫色 i。
  //
  // 注意：必须包 try/catch。Electron 28 在 macOS 上对 .icns 的解析有时会抛
  //   "Failed to load image from path"，那个错会冒成 unhandled rejection 把外层 async
  //   回调直接 abort，导致 createWindow 永远不被调用、用户看到主进程在跑但没窗口。
  //   优先 PNG（最原生稳）；fallback icns；都失败就静默放弃，不影响主窗口。
  if (process.platform === 'darwin' && app.dock) {
    const candidates = [
      path.join(__dirname, 'iPaper-dock.png'),
      path.join(__dirname, 'iPaper.icns'),
    ]
    for (const iconPath of candidates) {
      if (!fs.existsSync(iconPath)) continue
      try {
        app.dock.setIcon(iconPath)
        break
      } catch (err) {
        console.warn(`[dock.setIcon] 加载 ${iconPath} 失败，尝试下一个:`, err.message)
      }
    }
  }

  if (!SKIP_BACKEND) {
    startBackend()
  }

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

app.on('second-instance', () => {
  if (!mainWindow) return
  if (mainWindow.isMinimized()) {
    mainWindow.restore()
  }
  mainWindow.focus()
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

