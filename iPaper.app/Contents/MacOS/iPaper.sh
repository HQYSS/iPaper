#!/bin/bash

# iPaper 一键启动脚本

PROJECT_DIR="/Users/admin/workspace/iPaper"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

PYTHON="/Users/admin/miniconda3/bin/python"
NPM="/opt/homebrew/bin/npm"

export PATH="/opt/homebrew/bin:/Users/admin/miniconda3/bin:$PATH"

BACKEND_PORT=3000
FRONTEND_PORT=5173
PID_FILE="$LOG_DIR/backend.pid"

kill_pattern_if_running() {
    local pattern="$1"
    # 用 SIGKILL（-9）而不是默认 SIGTERM：之前踩过坑——上一次 iPaper.app 退出时 Electron
    # 主进程因故没响应 SIGTERM 变成孤儿（ppid=1），仍持有 Electron singleInstanceLock，
    # 导致下一次启动 Electron 拿不到 lock 立即 quit、用户看不到窗口。
    pgrep -f "$pattern" >/dev/null 2>&1 && pkill -9 -f "$pattern" 2>/dev/null || true
}

cleanup() {
    # 1. PID 文件精准清理（先 SIGTERM，给后端机会清理；不响应则进入 pattern + 端口兜底）
    if [ -f "$PID_FILE" ]; then
        kill "$(cat "$PID_FILE")" 2>/dev/null
        rm -f "$PID_FILE"
    fi
    # 2. 按命令行 pattern 强杀老进程（含相对路径 ./node_modules 启动的 Electron）
    kill_pattern_if_running "uvicorn main:app"
    kill_pattern_if_running "Electron\\.app/Contents/MacOS/Electron \\. --dev --skip-backend"
    sleep 1
    # 3. 端口兜底：不管什么进程，确保端口腾出来（用 -9 避免孤儿持有端口）
    lsof -ti :$BACKEND_PORT | xargs kill -9 2>/dev/null
    lsof -ti :$FRONTEND_PORT | xargs kill -9 2>/dev/null
}

start_backend() {
    cd "$PROJECT_DIR/backend"
    nohup env IPAPER_SYNC_ROLE=client "$PYTHON" -m uvicorn main:app --host 127.0.0.1 --port $BACKEND_PORT > "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$PID_FILE"
}

start_frontend() {
    cd "$PROJECT_DIR/frontend"
    nohup "$NPM" run dev -- --host 127.0.0.1 --port $FRONTEND_PORT > "$LOG_DIR/frontend.log" 2>&1 &
}

wait_for_services() {
    # 等待后端（健康检查端点是 GET /）
    for i in {1..30}; do
        if curl -s "http://127.0.0.1:$BACKEND_PORT/" 2>/dev/null | grep -q "ok"; then
            break
        fi
        sleep 1
    done

    # 等待前端
    for i in {1..30}; do
        if curl -s "http://127.0.0.1:$FRONTEND_PORT" > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done
}

patch_electron_branding() {
    # 把 node_modules 里的 Electron.app 改名成 iPaper、换图标。
    # 否则 Dock 里 Electron 进程会显示成 "Electron" + 默认 Atom 图标，用户看着像两个不
    # 相干的 app（iPaper applet + Electron）。
    # 幂等执行：每次启动都跑一遍，npm install 覆盖 node_modules 后下次启动会自动重 patch。
    local electron_app="$PROJECT_DIR/electron/node_modules/electron/dist/Electron.app"
    local plist="$electron_app/Contents/Info.plist"
    [ -f "$plist" ] || return 0

    # 把 iPaper.icns 复制进 Electron.app 的 Resources
    if [ -f "$PROJECT_DIR/electron/iPaper.icns" ]; then
        cp "$PROJECT_DIR/electron/iPaper.icns" "$electron_app/Contents/Resources/iPaper.icns" 2>/dev/null || true
    fi

    /usr/libexec/PlistBuddy -c "Set :CFBundleName iPaper" "$plist" 2>/dev/null || true
    /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName iPaper" "$plist" 2>/dev/null || true
    /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile iPaper" "$plist" 2>/dev/null || true

    # 触发 Launch Services 重读 bundle 元信息。光 touch 不够 —— LS 会缓存 bundle 名，
    # Dock 仍显示老的 "Electron"。lsregister -f 强制重新登记这个 bundle，Dock 才会刷成 iPaper。
    touch "$electron_app"
    local lsregister="/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister"
    if [ -x "$lsregister" ]; then
        "$lsregister" -f "$electron_app" 2>/dev/null || true
    fi
}

start_electron() {
    patch_electron_branding
    cd "$PROJECT_DIR/electron"
    # 重定向 stdout/stderr 到 electron.log，方便诊断窗口不出来 / createWindow 报错等问题
    ./node_modules/electron/dist/Electron.app/Contents/MacOS/Electron . --dev --skip-backend > "$LOG_DIR/electron.log" 2>&1
}

cleanup
start_backend
start_frontend
wait_for_services
start_electron
