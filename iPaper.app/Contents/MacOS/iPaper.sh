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

cleanup() {
    # 1. PID 文件精准清理
    if [ -f "$PID_FILE" ]; then
        kill "$(cat "$PID_FILE")" 2>/dev/null
        rm -f "$PID_FILE"
    fi
    pkill -f "uvicorn main:app" 2>/dev/null
    pkill -f "/Users/admin/workspace/iPaper/electron/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron . --dev --skip-backend" 2>/dev/null
    sleep 1
    # 2. 端口兜底：不管什么进程，确保端口腾出来
    lsof -ti :$BACKEND_PORT | xargs kill 2>/dev/null
    lsof -ti :$FRONTEND_PORT | xargs kill 2>/dev/null
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

start_electron() {
    cd "$PROJECT_DIR/electron"
    ./node_modules/electron/dist/Electron.app/Contents/MacOS/Electron . --dev --skip-backend
}

cleanup
start_backend
start_frontend
wait_for_services
start_electron
