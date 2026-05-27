#!/bin/bash
# iPaper 一键部署到服务器
# 用法:
#   ./scripts/deploy.sh            # 自动检测改了前端还是后端
#   ./scripts/deploy.sh --frontend # 只部署前端
#   ./scripts/deploy.sh --backend  # 只部署后端
#   ./scripts/deploy.sh --all      # 前后端都部署

set -e
cd "$(dirname "$0")/.."

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

check_remote_worktree_clean() {
    local status_output
    status_output=$(ssh aws 'cd ~/iPaper && python3 -c "from pathlib import Path; repo = Path.home() / \"iPaper\"; [p.unlink() for p in repo.rglob(\"._*\") if p.is_file()]" >/dev/null 2>&1 && git status --short --untracked-files=all | while IFS= read -r line; do path=${line:3}; path=${path#\"}; path=${path%\"}; case "$path" in backend/venv|backend/venv/*|frontend/dist|frontend/dist/*) ;; *) printf "%s\n" "$line" ;; esac; done')
    if [[ -n "$status_output" ]]; then
        echo "$status_output"
        error "服务器工作树不干净，请先备份并清理远端改动后再部署"
    fi
}

HAS_FRONTEND=0
HAS_BACKEND=0
CHANGED=$(git diff --name-only HEAD~1 2>/dev/null || git diff --name-only)
LOCAL_SHA=$(git rev-parse HEAD)

if [[ "$*" == *"--frontend"* ]]; then HAS_FRONTEND=1; fi
if [[ "$*" == *"--backend"* ]]; then HAS_BACKEND=1; fi
if [[ "$*" == *"--all"* ]]; then HAS_FRONTEND=1; HAS_BACKEND=1; fi

if [[ "$HAS_FRONTEND" -eq 0 && "$HAS_BACKEND" -eq 0 ]]; then
    if echo "$CHANGED" | grep -q "^frontend/"; then HAS_FRONTEND=1; fi
    if echo "$CHANGED" | grep -q "^backend/"; then HAS_BACKEND=1; fi

    if [[ "$HAS_FRONTEND" -eq 0 && "$HAS_BACKEND" -eq 0 ]]; then
        warn "未检测到前端或后端改动，也未指定 --frontend/--backend/--all"
        warn "如果改动已 commit 多次，请手动指定参数"
        exit 0
    fi

    info "自动检测到改动: $([ $HAS_FRONTEND -gt 0 ] && echo '前端 ')$([ $HAS_BACKEND -gt 0 ] && echo '后端')"
fi

if [[ -n $(git status --porcelain) ]]; then
    error "有未提交的改动，请先 git commit"
fi

info "推送到远程..."
git push

info "检查服务器工作树..."
check_remote_worktree_clean

info "服务器拉取代码..."
ssh aws "cd ~/iPaper && git pull --ff-only"
REMOTE_SHA=$(ssh aws "cd ~/iPaper && git rev-parse HEAD")
if [[ "$REMOTE_SHA" != "$LOCAL_SHA" ]]; then
    error "服务器代码版本不一致：local=$LOCAL_SHA remote=$REMOTE_SHA"
fi

if [[ "$HAS_BACKEND" -gt 0 ]]; then
    if echo "$CHANGED" | grep -q "^backend/requirements.txt$"; then
        warn "检测到 backend/requirements.txt 变更；请确认服务器 venv 已安装新依赖"
        warn "如需手动执行：ssh aws 'cd ~/iPaper/backend && ./venv/bin/pip install -r requirements.txt'"
    fi
fi

if [[ "$HAS_FRONTEND" -gt 0 ]]; then
    info "=== 部署前端 ==="
    info "本地构建..."
    cd frontend && npm run build && cd ..

    info "上传到服务器..."
    python - <<'PY'
import tarfile
from pathlib import Path

source_dir = Path("frontend/dist")
target_path = Path("/tmp/dist.tar.gz")

with tarfile.open(target_path, "w:gz") as archive:
    archive.add(source_dir, arcname="dist")
PY
    scp /tmp/dist.tar.gz aws:/tmp/
    ssh aws "cd ~/iPaper/frontend && rm -rf dist && tar xzf /tmp/dist.tar.gz && rm /tmp/dist.tar.gz"
    rm -f /tmp/dist.tar.gz
    info "前端部署完成"
fi

if [[ "$HAS_BACKEND" -gt 0 ]]; then
    info "=== 部署后端 ==="
    ssh aws "sudo systemctl restart ipaper-backend"
    sleep 2
    if ssh aws "systemctl is-active --quiet ipaper-backend"; then
        info "后端重启成功"
    else
        warn "后端可能未正常启动，请检查: ssh aws 'sudo journalctl -u ipaper-backend -n 20'"
    fi
fi

info "验证线上运行版本..."
RUNTIME_JSON=$(curl -fsS https://www.moshang.xyz/ipaper/api/health/runtime)
RUNTIME_SHA=$(RUNTIME_JSON="$RUNTIME_JSON" python3 - <<'PY'
import json
import os
print((json.loads(os.environ["RUNTIME_JSON"]).get("git") or {}).get("sha") or "")
PY
)
if [[ "$RUNTIME_SHA" != "$LOCAL_SHA" ]]; then
    warn "线上运行版本与本地 HEAD 不一致: runtime=$RUNTIME_SHA local=$LOCAL_SHA"
    if [[ "$HAS_BACKEND" -gt 0 ]]; then
        error "后端部署后运行版本未对齐，请检查 systemd/journal"
    fi
else
    info "线上运行版本已对齐: $RUNTIME_SHA"
fi

echo ""
info "=== 部署完成 ==="
[ $HAS_FRONTEND -gt 0 ] && info "  前端: 已更新"
[ $HAS_BACKEND -gt 0 ] && info "  后端: 已重启"
info "  线上地址: https://www.moshang.xyz/ipaper/"
