#!/bin/bash

# iPaper 一键启动脚本

PROJECT_DIR="/Users/admin/workspace/iPaper"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

PYTHON="/Users/admin/miniconda3/bin/python"
NPM="/opt/homebrew/bin/npm"

export PATH="/opt/homebrew/bin:/Users/admin/miniconda3/bin:$PATH"

BACKEND_PORT=3000

cleanup() {
    pkill -f "uvicorn main:app" 2>/dev/null
    pkill -f "vite.*iPaper" 2>/dev/null
    sleep 1
}

start_backend() {
    cd "$PROJECT_DIR/backend"
    nohup "$PYTHON" -m uvicorn main:app --host 127.0.0.1 --port $BACKEND_PORT > "$LOG_DIR/backend.log" 2>&1 &
}

start_frontend() {
    cd "$PROJECT_DIR/frontend"
    nohup "$NPM" run dev > "$LOG_DIR/frontend.log" 2>&1 &
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
        if curl -s http://localhost:5173 > /dev/null 2>&1; then
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
