#!/bin/bash
# Canonical iPaper deployment. The backend runs on mb; the VPS only serves
# frontend assets and proxies /ipaper/api/ through the existing FRP tunnel.

set -euo pipefail
cd "$(dirname "$0")/.."

DEPLOY_HOST="${IPAPER_MB_HOST:-mb}"
REMOTE_ROOT="${IPAPER_MB_ROOT:-/user/liuhanyu/iPaper}"
REMOTE_FRP_DIR="${IPAPER_MB_FRP_DIR:-/user/liuhanyu/frp}"
WEB_HOST="${IPAPER_WEB_HOST:-ali_fast}"
WEB_ROOT="${IPAPER_WEB_ROOT:-/home/admin/iPaper}"
PUBLIC_URL="${IPAPER_PUBLIC_URL:-https://59.110.154.252/ipaper}"
BUNDLE_PATH="/tmp/ipaper-mb-${RANDOM}-$$.tar.gz"
FRONTEND_BUNDLE=""

HAS_FRONTEND=0
HAS_BACKEND=0
for arg in "$@"; do
  case "$arg" in
    --frontend) HAS_FRONTEND=1 ;;
    --backend) HAS_BACKEND=1 ;;
    --all) HAS_FRONTEND=1; HAS_BACKEND=1 ;;
    *) echo "Usage: $0 [--frontend|--backend|--all]" >&2; exit 2 ;;
  esac
done
if [ "$HAS_FRONTEND" -eq 0 ] && [ "$HAS_BACKEND" -eq 0 ]; then
  CHANGED_FILES="$({ git diff --name-only HEAD~1 2>/dev/null || true; git diff --name-only; git diff --cached --name-only; } | sort -u)"
  printf '%s\n' "$CHANGED_FILES" | grep -q '^frontend/' && HAS_FRONTEND=1 || true
  printf '%s\n' "$CHANGED_FILES" | grep -Eq '^(backend|scripts)/' && HAS_BACKEND=1 || true
  if [ "$HAS_FRONTEND" -eq 0 ] && [ "$HAS_BACKEND" -eq 0 ]; then
    HAS_FRONTEND=1
    HAS_BACKEND=1
  fi
fi

cleanup() {
  rm -f "$BUNDLE_PATH"
  if [ -n "$FRONTEND_BUNDLE" ]; then
    rm -f "$FRONTEND_BUNDLE"
  fi
}
trap cleanup EXIT

if [ "$HAS_BACKEND" -eq 1 ]; then
  echo "[INFO] packaging backend source"
  tar czf "$BUNDLE_PATH" \
    --exclude='./backend/venv' --exclude='./frontend/node_modules' \
    --exclude='./frontend/dist' --exclude='./.git' --exclude='./llmcenter.pdf' \
    --exclude='._*' \
    backend scripts
  echo "[INFO] uploading backend to $DEPLOY_HOST:$REMOTE_ROOT"
  ssh -o RemoteCommand=none -o RequestTTY=no "$DEPLOY_HOST" "mkdir -p '$REMOTE_ROOT' '$REMOTE_ROOT/logs'"
  scp -o RemoteCommand=none -o RequestTTY=no "$BUNDLE_PATH" "$DEPLOY_HOST:/tmp/ipaper-mb-deploy.tar.gz"
  ssh -o RemoteCommand=none -o RequestTTY=no "$DEPLOY_HOST" "tar xzf /tmp/ipaper-mb-deploy.tar.gz -C '$REMOTE_ROOT' && rm -f /tmp/ipaper-mb-deploy.tar.gz"
  echo "[INFO] preparing backend environment"
  ssh -o RemoteCommand=none -o RequestTTY=no "$DEPLOY_HOST" "cd '$REMOTE_ROOT/backend' && python -m venv venv 2>/dev/null || true && venv/bin/pip install -r requirements.txt"
  echo "[INFO] waiting for active generations to drain"
  ssh -o RemoteCommand=none -o RequestTTY=no "$DEPLOY_HOST" "python3 - <<'PY'
import json
import time
import urllib.request

deadline = time.monotonic() + 1800
while True:
    try:
        with urllib.request.urlopen('http://127.0.0.1:3000/api/health/generations', timeout=5) as response:
            status = json.load(response)
    except Exception:
        # Older releases do not expose the drain endpoint yet.
        break
    running = status.get('chat_running', 0) + status.get('cloud_generation_running', 0)
    if running == 0:
        break
    if time.monotonic() >= deadline:
        raise SystemExit('active generations did not drain within 30 minutes; deployment cancelled')
    print(f'[INFO] {running} generation(s) still active; waiting...', flush=True)
    time.sleep(5)
PY"
  ssh -o RemoteCommand=none -o RequestTTY=no "$DEPLOY_HOST" "install -m 755 '$REMOTE_ROOT/scripts/initd-ipaper-backend' /etc/init.d/ipaper-backend && '$REMOTE_ROOT/scripts/initd-ipaper-backend' restart"
  echo "[INFO] ensuring FRP backend tunnel configuration"
  ssh -o RemoteCommand=none -o RequestTTY=no "$DEPLOY_HOST" "if ! grep -q 'name = \"ipaper-api\"' '$REMOTE_FRP_DIR/frpc2.toml'; then python3 - '$REMOTE_FRP_DIR/frpc2.toml' <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
s += '\n[[proxies]]\nname = \"ipaper-api\"\ntype = \"tcp\"\nlocalIP = \"127.0.0.1\"\nlocalPort = 3000\nremotePort = 33000\n'
p.write_text(s)
PY
if [ -x /etc/init.d/frpc2 ]; then /etc/init.d/frpc2 restart; else '$REMOTE_FRP_DIR/bin/frpc-0.68.0' -c '$REMOTE_FRP_DIR/frpc2.toml' >/user/liuhanyu/logs/frpc2-ipaper.log 2>&1 & fi; fi
"
fi

if [ "$HAS_FRONTEND" -eq 1 ]; then
  echo "[INFO] building frontend locally"
  (cd frontend && npm run build)
  RELEASE_ID="$(git rev-parse --short=12 HEAD)-$(date -u +%Y%m%dT%H%M%SZ)"
  printf '{"release_id":"%s","git_sha":"%s","built_at":"%s"}\n' \
    "$RELEASE_ID" \
    "$(git rev-parse HEAD)" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > frontend/dist/release.json
  FRONTEND_BUNDLE="/tmp/ipaper-frontend-$$.tar.gz"
  tar czf "$FRONTEND_BUNDLE" -C frontend dist
  echo "[INFO] uploading frontend to $WEB_HOST:$WEB_ROOT/frontend"
  scp "$FRONTEND_BUNDLE" "$WEB_HOST:/tmp/ipaper-frontend.tar.gz"
  ssh "$WEB_HOST" "rm -rf '$WEB_ROOT/frontend/dist.next' && mkdir -p '$WEB_ROOT/frontend/dist.next' && tar xzf /tmp/ipaper-frontend.tar.gz -C '$WEB_ROOT/frontend/dist.next' --strip-components=1 && rm -rf '$WEB_ROOT/frontend/dist.old' && if [ -d '$WEB_ROOT/frontend/dist' ]; then mv '$WEB_ROOT/frontend/dist' '$WEB_ROOT/frontend/dist.old'; fi && mv '$WEB_ROOT/frontend/dist.next' '$WEB_ROOT/frontend/dist' && rm -f /tmp/ipaper-frontend.tar.gz"
  rm -f "$FRONTEND_BUNDLE"
  FRONTEND_BUNDLE=""
  echo "[INFO] verifying public frontend release $RELEASE_ID"
  PUBLIC_RELEASE="$(curl -k -fsS --retry 10 --retry-delay 1 "$PUBLIC_URL/release.json?release=$RELEASE_ID")"
  LOCAL_RELEASE="$(tr -d '\r\n' < frontend/dist/release.json)"
  if [ "$PUBLIC_RELEASE" != "$LOCAL_RELEASE" ]; then
    echo "[ERROR] public frontend release does not match local build" >&2
    echo "[ERROR] local:  $LOCAL_RELEASE" >&2
    echo "[ERROR] public: $PUBLIC_RELEASE" >&2
    exit 1
  fi
fi

echo "[INFO] verifying public runtime"
ssh -o RemoteCommand=none -o RequestTTY=no "$DEPLOY_HOST" "for i in \$(seq 1 30); do curl -fsS http://127.0.0.1:3000/api/health/ready >/dev/null && exit 0; sleep 1; done; exit 1"
curl -k -fsS --retry 20 --retry-delay 1 --retry-all-errors "$PUBLIC_URL/api/health/runtime" >/dev/null
echo "[INFO] deployment complete: $PUBLIC_URL/"
