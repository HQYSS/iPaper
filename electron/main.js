const { app, BrowserWindow, shell } = require('electron')
const path = require('path')
const { spawn } = require('child_process')

// 开发模式检测
const isDev = process.argv.includes('--dev') || process.env.NODE_ENV === 'development'

let mainWindow
let backendProcess

// 启动 Python 后端
function startBackend() {
  const backendPath = path.join(__dirname, '..', 'backend')
  
  // 开发模式下使用 python 直接运行
  if (isDev) {
    backendProcess = spawn('python', ['main.py'], {
      cwd: backendPath,
      stdio: 'inherit'
    })
  } else {
    // 生产模式下使用打包后的可执行文件
    const backendExe = process.platform === 'win32' ? 'ipaper-backend.exe' : 'ipaper-backend'
    const backendExePath = path.join(process.resourcesPath, 'backend', backendExe)
    
    backendProcess = spawn(backendExePath, [], {
      cwd: path.dirname(backendExePath),
      stdio: 'inherit'
    })
  }

  backendProcess.on('error', (err) => {
    console.error('Failed to start backend:', err)
  })

  backendProcess.on('exit', (code) => {
    console.log(`Backend process exited with code ${code}`)
  })
}

// 等待后端启动
async function waitForBackend(maxRetries = 30) {
  const http = require('http')
  
  for (let i = 0; i < maxRetries; i++) {
    try {
      await new Promise((resolve, reject) => {
        const req = http.get('http://127.0.0.1:3000/', (res) => {
          resolve(res)
        })
        req.on('error', reject)
        req.setTimeout(1000, () => {
          req.destroy()
          reject(new Error('Timeout'))
        })
      })
      console.log('Backend is ready')
      return true
    } catch (e) {
      console.log(`Waiting for backend... (${i + 1}/${maxRetries})`)
      await new Promise(r => setTimeout(r, 1000))
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
      preload: path.join(__dirname, 'preload.js')
    },
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 15, y: 15 }
  })

  // 开发模式加载 Vite 开发服务器
  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
  } else {
    // 生产模式加载打包后的文件
    mainWindow.loadFile(path.join(__dirname, '..', 'frontend', 'dist', 'index.html'))
  }

  // 外部链接使用系统浏览器打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

app.whenReady().then(async () => {
  // 启动后端
  startBackend()
  
  try {
    // 等待后端就绪
    await waitForBackend()
    
    // 创建窗口
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
  // 关闭后端进程
  if (backendProcess) {
    backendProcess.kill()
  }
})

