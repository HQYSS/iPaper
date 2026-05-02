# Electron 与部署

## Electron 主进程 (`electron/main.js`)

### 启动流程

```
app.whenReady()
    │
    ├── startBackend()          # 启动 Python 后端进程
    │   └── 以 `IPAPER_SYNC_ROLE=client` 启动后端
    │       spawn python main.py (dev)
    │       或 spawn ipaper-backend (prod)
    │
    ├── waitForBackend()        # 轮询 http://127.0.0.1:3000/，最多 30 秒
    │
    └── createWindow()          # 创建 BrowserWindow
    │   └── loadURL('http://localhost:5173')  (dev)
    │       或 loadFile('frontend/dist/index.html')  (prod)
```

### 开发模式 vs 生产模式

通过 `--dev` 参数或 `NODE_ENV=development` 切换。

| 行为 | 开发模式 | 生产模式 |
|------|---------|---------|
| 后端启动 | `python main.py` | `ipaper-backend` 可执行文件 |
| 前端加载 | `http://localhost:5173` (Vite) | `frontend/dist/index.html` |
| DevTools | 自动打开 | 不打开 |

### 窗口配置

```javascript
{
  width: 1400,
  height: 900,
  minWidth: 1000,
  minHeight: 600,
  titleBarStyle: 'hiddenInset',      // macOS 沉浸式标题栏
  trafficLightPosition: { x: 15, y: 15 }  // macOS 红绿灯位置
}
```

### 安全配置

```javascript
webPreferences: {
  nodeIntegration: false,    // 禁用 Node.js 集成
  contextIsolation: true,    // 上下文隔离
  preload: 'preload.js'     // 预加载脚本
}
```

### 进程管理

- Electron 启动时自动启动后端进程
- Electron 通过环境变量显式将本地后端标记为 `sync_role=client`
- 主动同步职责完全下沉到本地后端；Electron 主进程不再保留第二套 `syncOnce()/startSyncLoops()` 逻辑
- Electron 通过 `app.requestSingleInstanceLock()` 强制单实例运行；再次启动会聚焦已有窗口，而不是并行跑第二只旧主进程
- 只要本地后端在跑，本地写操作就会自动推云端；关闭 Electron 时会一并结束本地后端
- 当前默认云端固定为 `https://www.moshang.xyz/ipaper/api`
- 云端同步使用专用设备凭证，不再复用网页登录 JWT
- 外部链接使用系统浏览器打开
- `before-quit` 事件中杀死后端进程
- macOS 上关闭所有窗口时不退出（遵循 macOS 惯例）

---

## 启动事故排查 — `app.whenReady` 副作用必须 try/catch

**铁律**：`app.whenReady().then(async () => { ... })` 回调里 `createWindow()`
之前的所有"装饰性"副作用（`dock.setIcon` / `setBadge` / 任意可能失败的 IO）
**必须 try/catch 兜底**，绝不能让装饰性失败阻断主流程。

### 历史事故（2026-04-29）

**症状**：双击 iPaper.app 没响应。`ps` 看 Electron 主进程 + GPU helper +
network helper 都活着，**唯独缺 Renderer helper（=BrowserWindow 没创建）**。
applet 在 Dock 上显示"应用程序没有响应"。

**根因**：`app.dock.setIcon('iPaper.icns')` 在 Electron 28 的 macOS 实现里偶
然抛 `Failed to load image from path`。这个错变成 unhandled promise rejection，
把外层 async 回调链直接 abort —— 后续 `startBackend()` / `waitForBackend()`
/ `createWindow()` **全都没执行**。主进程卡在 whenReady 死循环：不退也没窗口。

**怎么定位**：`iPaper.app/Contents/MacOS/iPaper.sh` 已经把 Electron 的
stdout/stderr 重定向到 `logs/electron.log`。下次"窗口不出来"，**第一件事就
是看这个文件**，根因往往一行就在那。

### 配套加固

- `app.dock.setIcon` 优先用 PNG，fallback icns —— Electron 28 的 NativeImage
  对 `.icns` 不稳，对 PNG 稳。`scripts/generate-macos-icns.sh` 会同时输出
  `electron/iPaper-dock.png` 给 `setIcon` 用
- `iPaper.sh` cleanup 改用 `kill -9` —— 之前 SIGTERM 杀不掉孤儿 Electron 主
  进程，那只孤儿持有 `singleInstanceLock` 让下次启动的 Electron 拿不到锁
  立即 `app.quit()`，用户看到主进程在跑但永远没窗口
- `iPaper.app/Contents/Info.plist` 加 `LSUIElement=YES` —— applet 不在 Dock
  显示自己的图标，避免"iPaper 图标 + Electron 图标"两个图标并排
- `iPaper.sh` 启动 Electron 前 patch `node_modules/electron/dist/Electron.app`
  的 `CFBundleName/DisplayName/IconFile` 为 iPaper（图标能换成功；名字 label
  受 Launch Services 缓存顽固限制，可能仍显示 Electron —— 工程妥协可接受）

---

## 预加载脚本 (`electron/preload.js`)

通过 `contextBridge` 暴露 `electronAPI` 给渲染进程：

```javascript
window.electronAPI = {
  platform: process.platform,       // 'darwin', 'win32', 'linux'
  versions: process.versions,
  isElectron: true
}
```

前端可通过 `window.electronAPI` 检测是否在 Electron 环境中运行。

---

## 一键启动器 (`iPaper.app`)

macOS 应用包，双击即可启动全部服务。

### 目录结构

```
iPaper.app/
└── Contents/
    ├── Info.plist           # macOS 应用描述文件
    ├── MacOS/
    │   ├── applet           # AppleScript 生成的 Mach-O 二进制（macOS 启动入口）
    │   └── iPaper.sh        # Bash 启动脚本（被 applet 调用）
    └── Resources/
        ├── applet.icns      # Finder/Dock 显示的 .app 图标（紫色 i，由 scripts/generate-macos-icns.sh 生成）
        ├── applet.rsrc      # AppleScript applet 内置资源
        └── Scripts/         # AppleScript 字节码
```

> **为什么用 AppleScript applet？** macOS Sonoma 不允许通过 Finder/`open` 命令启动以 shell 脚本为可执行文件的 .app bundle（报 `procNotFound -600` 错误）。AppleScript `applet` 是正规的 Mach-O 二进制，macOS 能正常启动。

### 启动脚本流程 (`MacOS/iPaper.sh`)

```
cleanup()           # 杀死可能残留的旧进程
    │
start_backend()     # nohup 启动 Python 后端 → logs/backend.log
    │
start_frontend()    # nohup 启动 npm run dev → logs/frontend.log
    │
wait_for_services() # 轮询后端和前端端口
    │
start_backend_watchdog()
    │               # 每 5s 检查后端 PID + 健康检查，掉线自动拉起
    │
start_electron()    # 启动 Electron（前台运行）
```

**关键细节：**
- 使用**绝对路径**调用 python/npm/node（双击 .app 时 PATH 不含 homebrew/conda）
- 路径硬编码在脚本中：
  - Python: `/Users/admin/miniconda3/bin/python`
  - npm: `/opt/homebrew/bin/npm`
  - node: `/opt/homebrew/bin/node`
- 日志输出到 `项目根目录/logs/`
- `start_backend()` 会显式注入 `IPAPER_SYNC_ROLE=client`，确保本地后端承担主动同步客户端角色，而不是误用云端被动服务端配置
- **PID 文件 + 端口兜底清理**：启动后端后将 PID 写入 `logs/backend.pid`，cleanup 时先读 PID 精准杀进程，再用 `lsof -ti :PORT` 按端口兜底，防止旧进程占端口
- **后端 watchdog**：`start_backend_watchdog()` 在 Electron 壳运行期间每 5 秒检查 `logs/backend.pid` 和 `GET /` 健康检查；如果后端进程退出或 3000 端口不可用，会写入 `logs/backend-watchdog.log` 并自动重启后端，避免前端还在但 API 断掉后刷新进入登录页
- cleanup 会按更宽松的进程模式清掉旧 `uvicorn main:app` 和旧 Electron 开发主进程，再配合 Electron 单实例锁，避免出现"老 Electron 壳 + 新前后端服务"的混合运行态
- **cleanup 用 `kill -9` / `pkill -9`** —— 之前用 SIGTERM 杀不掉孤儿 Electron 主进程（不响应 SIGTERM 的话留下来持有 `singleInstanceLock` 阻断下次启动），见上面"启动事故排查"小节
- **Electron stdout/stderr 重定向到 `logs/electron.log`** —— 否则 `app.dock.setIcon` 之类的报错会被 applet 吞掉，"窗口不出来"完全无法定位
- **`patch_electron_branding`**：启动 Electron 前修改 `node_modules/electron/dist/Electron.app/Contents/Info.plist` 的 `CFBundleName/DisplayName/IconFile` 为 iPaper，并把 `iPaper.icns` 复制进 Electron.app 的 Resources。每次启动幂等执行，npm install 覆盖后下次启动会自动重 patch

**注意：** 如果 Python 或 Node.js 的安装路径变化，需要更新此脚本。`start-cursor-mode.sh` 也使用相同的 PID 文件 + 端口清理机制。

---

## Electron 打包配置 (`electron/package.json`)

使用 `electron-builder` 打包：

```json
{
  "build": {
    "appId": "com.ipaper.app",
    "productName": "iPaper",
    "mac": {
      "target": ["dmg", "zip"]
    },
    "win": {
      "target": ["nsis", "portable"]
    },
    "linux": {
      "target": ["AppImage", "deb"]
    }
  }
}
```

### 生产环境打包（尚未实现）

完整打包需要：
1. 使用 PyInstaller 将 Python 后端打包为独立可执行文件
2. 将后端可执行文件放入 Electron 的 `resources/backend/` 目录
3. 使用 `npm run build` 构建前端
4. 使用 `electron-builder` 打包整个应用

---

## 端口与网络

| 连接 | 说明 |
|------|------|
| Electron → Vite Dev Server | `http://localhost:5173` (开发模式) |
| Vite Proxy → FastAPI | `/api` → `http://127.0.0.1:3000` |
| FastAPI → arXiv | `https://arxiv.org/` (下载论文时) |
| FastAPI → OpenRouter API | `https://openrouter.ai/api/v1` (LLM 对话时) |

所有本地服务绑定在 `127.0.0.1`，不暴露到外网。

---

## PWA / 移动 Web (`https://www.moshang.xyz/ipaper/`)

云端的 `/ipaper/` 同时是 Web 端 + PWA。iPhone Safari 打开后可"分享 → 添加到主屏幕"，独立窗口启动并应用 `MobileLayout`。

### 关键资产

| 文件 | 说明 |
|------|------|
| `frontend/index.html` | iOS 全套 meta：`viewport-fit=cover`、`apple-mobile-web-app-capable`、`apple-mobile-web-app-status-bar-style=black-translucent`、`apple-mobile-web-app-title=iPaper`、亮/暗 `theme-color` |
| `frontend/public/manifest.webmanifest` | PWA manifest：`name` / `short_name` / `start_url=.` / `scope=./` / `display=standalone` / `orientation=portrait`（iPhone 强制竖屏）+ icons 数组（192/512/maskable-512） |
| `frontend/public/icons/` | 全套尺寸：`favicon-16/32`、`apple-touch-icon-180`、`icon-192/512/1024`、`icon-maskable-512`。源图 `assets/m1-letter-i.png`，生成脚本 `/tmp/ipaper-icon-design/generate_icons.py`（PIL，做了像素级 whiteness 提取 + 重建紫色渐变背景，去掉 AI 源图自带的 squircle 描边/阴影/光晕） |
| `frontend/public/sw.js` | Service Worker，缓存静态资源 + `.webmanifest`。**改完任意 PWA 资产必须把 `CACHE_NAME` 加版（如 `v3 → v4`），否则旧客户端不会刷新缓存** |

### 改图标 / PWA 资产的标准动作

```bash
cd /tmp/ipaper-icon-design && python3 generate_icons.py   # 重生成全套 PNG 到 frontend/public/icons/
./scripts/generate-macos-icns.sh                          # 同步到 electron/iPaper.icns + iPaper.app/Contents/Resources/applet.icns，并刷 Finder/Dock 缓存
# 改 sw.js 里的 CACHE_NAME，加一档版本号
./scripts/deploy.sh                                       # 自动 build + 推 dist
```

部署后用 iPhone Safari 强制刷新（关掉 PWA 进程后重开），验证图标和 manifest 已更新。

### macOS 图标的多个位置

iPaper 在 macOS 上的图标分散在多个独立位置，**改设计后必须一起换**（生成脚本
`./scripts/generate-macos-icns.sh` 已经把它们一次性同步到位）：

| 位置 | 用途 | 备注 |
|------|------|------|
| `frontend/public/icons/*.png` | PWA / Web 端，favicon、apple-touch-icon、Web manifest icons | 由 `/tmp/ipaper-icon-design/generate_icons.py` 生成 |
| `iPaper.app/Contents/Resources/applet.icns` | 但因为 `Info.plist` 里 `LSUIElement=YES`，applet 不在 Dock 显示，这个图标实际只影响 Finder 视图 | 因为 LSUIElement 的关系，这个图标的可见性其实很低 |
| `electron/iPaper.icns` | Electron `app.dock.setIcon` 的 fallback 输入（PNG 加载失败时才用到） | Electron 28 对 `.icns` 解析偶尔失败，所以是 fallback 不是首选 |
| `electron/iPaper-dock.png` | **Electron `app.dock.setIcon` 的首选输入** —— Dock 上看到的紫色 i 就是它 | NativeImage 对 PNG 最稳；squircle + 100px 透明边距已在 PNG 里烘焙 |
| `node_modules/electron/dist/Electron.app/Contents/Resources/iPaper.icns` | Electron 进程在 Launch Services 注册时用的 bundle 图标（影响 Cmd+Tab 任务切换器和 Dock 图标） | 由 `iPaper.sh` 启动前从 `electron/iPaper.icns` 复制 + patch Info.plist 的 `CFBundleIconFile` |

如果只换 PWA 图标不换其余几个，本地 iPaper.app 在 Finder 和 Dock 里还是旧图标 —— 这是历史上踩过的坑。

---
