#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

configure_playwright_browser() {
  local mac_chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  if [[ -z "${PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH:-}" && -x "$mac_chrome" ]]; then
    export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="$mac_chrome"
  fi
}

run_backend() {
  echo "==> backend"
  cd "$ROOT_DIR/backend"

  local python_bin="${PYTHON:-python3}"
  if ! "$python_bin" -c "import pytest" >/dev/null 2>&1; then
    echo "pytest is unavailable for $python_bin." >&2
    echo "Install backend test dependencies: $python_bin -m pip install -r backend/requirements-dev.txt" >&2
    return 1
  fi

  "$python_bin" -m pytest .
  "$python_bin" -m compileall -q .
}

run_frontend() {
  echo "==> frontend"
  cd "$ROOT_DIR/frontend"
  npm run lint
  npm run test:run
  npm run build
}

run_e2e() {
  echo "==> e2e"
  cd "$ROOT_DIR/e2e"
  configure_playwright_browser
  npm test
}

run_e2e_web() {
  echo "==> e2e:web"
  cd "$ROOT_DIR/e2e"
  configure_playwright_browser
  npm run test:web
}

run_e2e_electron() {
  echo "==> e2e:electron"
  cd "$ROOT_DIR/e2e"
  npm run test:electron
}

usage() {
  cat <<'EOF'
Usage: scripts/test.sh [backend|frontend|e2e|e2e:web|e2e:electron]...

With no arguments, runs the quick cross-platform suite:
backend + frontend + deterministic Web E2E.
EOF
}

if [[ $# -eq 0 ]]; then
  targets=(backend frontend e2e:web)
else
  targets=("$@")
fi

for target in "${targets[@]}"; do
  case "$target" in
    backend) run_backend ;;
    frontend) run_frontend ;;
    e2e) run_e2e ;;
    e2e:web) run_e2e_web ;;
    e2e:electron) run_e2e_electron ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown test target: $target" >&2
      usage >&2
      exit 2
      ;;
  esac
done
