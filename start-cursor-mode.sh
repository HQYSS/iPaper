#!/bin/bash
# iPaper Cursor 模式启动脚本
# 启动后端和前端开发服务器，在 Cursor Simple Browser 中使用

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

BACKEND_PORT=3000
PID_FILE="$SCRIPT_DIR/logs/backend.pid"
mkdir -p "$SCRIPT_DIR/logs"

cleanup() {
    echo "正在关闭服务..."
    if [ -f "$PID_FILE" ]; then
        kill "$(cat "$PID_FILE")" 2>/dev/null
        rm -f "$PID_FILE"
    fi
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# 清理可能残留的旧后端进程
if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE")"
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "清理残留后端进程 (PID: $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null
        sleep 1
    fi
    rm -f "$PID_FILE"
fi
# 端口兜底
lsof -ti :$BACKEND_PORT | xargs kill 2>/dev/null && sleep 1

echo "启动后端..."
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port $BACKEND_PORT &
BACKEND_PID=$!
echo $BACKEND_PID > "$PID_FILE"
cd "$SCRIPT_DIR"

echo "等待后端就绪..."
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:$BACKEND_PORT/ > /dev/null 2>&1; then
        echo "后端已就绪"
        break
    fi
    sleep 1
done

# 先清理残留的 Vite 进程，避免端口冲突
EXISTING_VITE_PID=$(lsof -ti :5173 2>/dev/null)
if [ -n "$EXISTING_VITE_PID" ]; then
    echo "清理残留前端进程 (PID: $EXISTING_VITE_PID)..."
    kill $EXISTING_VITE_PID 2>/dev/null
    sleep 1
fi

echo "启动前端..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd "$SCRIPT_DIR"

# 等待前端就绪并检测实际端口
FRONTEND_PORT=""
for i in $(seq 1 15); do
    sleep 1
    for port in 5173 5174 5175; do
        if curl -s http://127.0.0.1:$port/ > /dev/null 2>&1; then
            FRONTEND_PORT=$port
            break 2
        fi
    done
done

if [ -z "$FRONTEND_PORT" ]; then
    FRONTEND_PORT=5173
fi

echo ""
echo "=================================="
echo "  iPaper Cursor 模式已启动"
echo "  在 Cursor Simple Browser 中打开:"
echo "  http://localhost:${FRONTEND_PORT}/?cursor=1"
echo "=================================="
echo ""
echo "按 Ctrl+C 关闭所有服务"

wait
