#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
export LANG=C

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DEPLOY_HOST="${IPAPER_MB_HOST:-mb}"
REMOTE_ROOT="${IPAPER_MB_ROOT:-/user/liuhanyu/iPaper}"
PUBLIC_URL="${IPAPER_PUBLIC_URL:-https://59.110.154.252/ipaper}"
LOCAL_URL="${IPAPER_LOCAL_URL:-http://127.0.0.1:3000}"

CHECK_BACKEND=0
CHECK_FRONTEND=0
CHECK_LOCAL_RUNTIME=0
CHECK_SYNC=0

usage() {
  cat <<'EOF'
Usage: scripts/verify-delivery.sh [--backend] [--frontend] [--electron] [--sync]

Use explicit scopes in a dirty worktree. With no arguments, scopes are inferred
from changed files and may intentionally require delivery of unrelated changes.

  --backend   Compare deployed backend source and verify cloud runtime.
  --frontend  Compare local and public release.json.
  --electron  Verify the local runtime was restarted and has one process chain.
  --sync      Verify backend deployment, local restart, and a completed sync run.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --backend) CHECK_BACKEND=1 ;;
    --frontend) CHECK_FRONTEND=1 ;;
    --electron) CHECK_LOCAL_RUNTIME=1 ;;
    --sync)
      CHECK_SYNC=1
      CHECK_BACKEND=1
      CHECK_LOCAL_RUNTIME=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ $# -eq 0 ]]; then
  changed_files="$({
    git diff --name-only
    git diff --cached --name-only
    git ls-files --others --exclude-standard
  } | sort -u)"
  grep -q '^backend/' <<<"$changed_files" && CHECK_BACKEND=1 || true
  grep -q '^frontend/' <<<"$changed_files" && CHECK_FRONTEND=1 || true
  grep -Eq '^(electron/|iPaper\.app/|scripts/.*(start|launch))' <<<"$changed_files" && CHECK_LOCAL_RUNTIME=1 || true
  grep -Eq '(^|/)(sync_service\.py|sync\.py)$' <<<"$changed_files" && {
    CHECK_SYNC=1
    CHECK_BACKEND=1
    CHECK_LOCAL_RUNTIME=1
  } || true
fi

failures=0

report() {
  local key="$1"
  local value="$2"
  printf '%s=%s\n' "$key" "$value"
}

fail() {
  report "$1" "no"
  failures=$((failures + 1))
}

runtime_role() {
  local url="$1"
  curl -k -fsS "$url/api/health/runtime" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("sync_role", ""))'
}

backend_manifest() {
  local root="$1"
  find "$root/backend" -type f \
    \( -name '*.py' -o -name 'requirements*.txt' \) \
    ! -name '._*' ! -path '*/venv/*' ! -path '*/__pycache__/*' -print0 \
    | LC_ALL=C sort -z \
    | while IFS= read -r -d '' file; do
        local relative="${file#"$root"/}"
        local digest
        digest="$(shasum -a 256 "$file" | awk '{print $1}')"
        printf '%s %s\n' "$digest" "$relative"
      done
}

if [[ "$CHECK_BACKEND" -eq 1 ]]; then
  if [[ "$(runtime_role "$PUBLIC_URL" 2>/dev/null || true)" == "server" ]]; then
    report CLOUD_RUNTIME_OK yes
  else
    fail CLOUD_RUNTIME_OK
  fi

  local_manifest="$(mktemp)"
  remote_manifest="$(mktemp)"
  trap 'rm -f "$local_manifest" "$remote_manifest"' EXIT
  backend_manifest "$ROOT_DIR" >"$local_manifest"
  if ssh -o RemoteCommand=none -o RequestTTY=no "$DEPLOY_HOST" \
    "cd '$REMOTE_ROOT' && find backend -type f \( -name '*.py' -o -name 'requirements*.txt' \) ! -name '._*' ! -path '*/venv/*' ! -path '*/__pycache__/*' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | awk '{print \$1 \" \" \$2}'" \
    >"$remote_manifest" 2>/dev/null \
    && cmp -s "$local_manifest" "$remote_manifest"; then
    report CLOUD_SOURCE_MATCH yes
  else
    fail CLOUD_SOURCE_MATCH
  fi
fi

if [[ "$CHECK_FRONTEND" -eq 1 ]]; then
  if [[ -f frontend/dist/release.json ]] \
    && public_release="$(curl -k -fsS "$PUBLIC_URL/release.json?verify=$(date +%s)" 2>/dev/null)" \
    && [[ "$(tr -d '\r\n' < frontend/dist/release.json)" == "$public_release" ]]; then
    report FRONTEND_RELEASE_MATCH yes
  else
    fail FRONTEND_RELEASE_MATCH
  fi
fi

if [[ "$CHECK_LOCAL_RUNTIME" -eq 1 ]]; then
  if [[ "$(runtime_role "$LOCAL_URL" 2>/dev/null || true)" == "client" ]]; then
    report LOCAL_RUNTIME_OK yes
  else
    fail LOCAL_RUNTIME_OK
  fi

  backend_listeners="$(lsof -tiTCP:3000 -sTCP:LISTEN 2>/dev/null | sort -u | wc -l | tr -d ' ')"
  frontend_listeners="$(lsof -tiTCP:5173 -sTCP:LISTEN 2>/dev/null | sort -u | wc -l | tr -d ' ')"
  electron_mains="$(pgrep -f 'Electron\.app/Contents/MacOS/Electron \. --dev --skip-backend' 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$backend_listeners" == "1" && "$frontend_listeners" == "1" && "$electron_mains" == "1" ]]; then
    report LOCAL_PROCESS_CHAIN_UNIQUE yes
  else
    fail LOCAL_PROCESS_CHAIN_UNIQUE
  fi
fi

if [[ "$CHECK_SYNC" -eq 1 ]]; then
  latest_start="$(rg -n 'starting backend sha=' logs/backend.log 2>/dev/null | tail -1 | cut -d: -f1)"
  if [[ -n "$latest_start" ]] \
    && sync_log="$(sed -n "${latest_start},\$p" logs/backend.log)" \
    && grep -q 'sync completed run=' <<<"$sync_log" \
    && ! grep -q '409 Conflict' <<<"$sync_log"; then
    report SYNC_RUN_VERIFIED yes
  else
    fail SYNC_RUN_VERIFIED
  fi
fi

if [[ "$failures" -eq 0 ]]; then
  report DELIVERY_COMPLETE yes
  exit 0
fi

report DELIVERY_COMPLETE no
exit 1
