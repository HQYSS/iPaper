#!/usr/bin/env bash
# Unattended local-client setup for a new Mac. Codex should run this and
# fix failures itself; do not ask the user questions.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_PATH="${1:-}"
TARGET_REPO="${IPAPER_TARGET_REPO:-$HOME/workspace/iPaper}"
LOG_FILE="${IPAPER_BOOTSTRAP_LOG:-$HOME/ipaper-new-mac-bootstrap.log}"
NODE_VERSION="${IPAPER_NODE_VERSION:-v22.14.0}"
mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

find_secrets() {
  local candidate
  if [ -n "${SECRETS_PATH}" ]; then
    echo "${SECRETS_PATH}"
    return
  fi
  for candidate in \
    "${IPAPER_SECRETS:-}" \
    "$ROOT_DIR/new-mac.secrets.json" \
    "$HOME/workspace/ipaper-new-mac-handoff/new-mac.secrets.json" \
    "$HOME/ipaper-new-mac-handoff/new-mac.secrets.json" \
    "$(pwd)/new-mac.secrets.json"
  do
    if [ -n "$candidate" ] && [ -f "$candidate" ]; then
      echo "$candidate"
      return
    fi
  done
  die "new-mac.secrets.json not found. Pass it as the first argument."
}

ensure_xcode_cli() {
  if xcode-select -p >/dev/null 2>&1; then
    return
  fi
  log "Xcode Command Line Tools missing; attempting install"
  xcode-select --install >/dev/null 2>&1 || true
}

ensure_homebrew() {
  if command -v brew >/dev/null 2>&1; then
    eval "$($(command -v brew) shellenv)"
    return
  fi
  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
    return
  fi
  if [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
    return
  fi
  log "Homebrew not found; installing to $HOME/.homebrew"
  mkdir -p "$HOME/.homebrew"
  if [ ! -x "$HOME/.homebrew/bin/brew" ]; then
    curl -fsSL https://github.com/Homebrew/brew/tarball/master | tar xz --strip 1 -C "$HOME/.homebrew"
  fi
  eval "$("$HOME/.homebrew/bin/brew" shellenv)"
}

ensure_node() {
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    log "node $(node --version) npm $(npm --version)"
    return
  fi
  if command -v brew >/dev/null 2>&1; then
    brew install node
    return
  fi
  local arch url dest
  dest="$HOME/.local/node"
  case "$(uname -m)" in
    arm64) arch="darwin-arm64" ;;
    *) arch="darwin-x64" ;;
  esac
  url="https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-${arch}.tar.gz"
  log "Installing Node ${NODE_VERSION} to $dest"
  mkdir -p "$HOME/.local"
  curl -fsSL "$url" | tar xz -C "$HOME/.local"
  rm -rf "$dest"
  mv "$HOME/.local/node-${NODE_VERSION}-${arch}" "$dest"
  export PATH="$dest/bin:$PATH"
}

ensure_python() {
  if [ -x "$HOME/miniconda3/envs/ipaper/bin/python" ]; then
    PYTHON_BIN="$HOME/miniconda3/envs/ipaper/bin/python"
    log "python $("$PYTHON_BIN" --version)"
    return
  fi
  if command -v brew >/dev/null 2>&1; then
    brew list python@3.11 >/dev/null 2>&1 || brew install python@3.11
    PYTHON_BIN="$(brew --prefix python@3.11)/bin/python3.11"
    if [ -x "$PYTHON_BIN" ]; then
      log "python $("$PYTHON_BIN" --version)"
      return
    fi
  fi
  local installer arch_url
  case "$(uname -m)" in
    arm64) arch_url="https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh" ;;
    *) arch_url="https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh" ;;
  esac
  installer="/tmp/ipaper-miniconda.sh"
  log "Installing Miniconda to $HOME/miniconda3"
  curl -fsSL "$arch_url" -o "$installer"
  bash "$installer" -b -p "$HOME/miniconda3"
  "$HOME/miniconda3/bin/conda" create -y -n ipaper python=3.10
  PYTHON_BIN="$HOME/miniconda3/envs/ipaper/bin/python"
}

export PATH="/opt/homebrew/bin:/usr/local/bin:${HOME}/miniconda3/envs/ipaper/bin:${HOME}/miniconda3/bin:${HOME}/.local/node/bin:${HOME}/.homebrew/bin:${PATH}"
PYTHON_BIN=""

SECRETS_PATH="$(find_secrets)"
log "Using secrets $SECRETS_PATH"
[ -f "$SECRETS_PATH" ] || die "secrets file missing"

ensure_xcode_cli
ensure_homebrew
ensure_node
ensure_python
command -v git >/dev/null 2>&1 || {
  if command -v brew >/dev/null 2>&1; then
    brew install git
  else
    die "git is required"
  fi
}

if [ ! -d "$TARGET_REPO/.git" ]; then
  log "Cloning iPaper into $TARGET_REPO"
  mkdir -p "$(dirname "$TARGET_REPO")"
  if ! git clone --branch main git@github.com:HQYSS/iPaper.git "$TARGET_REPO"; then
    if command -v gh >/dev/null 2>&1; then
      gh repo clone HQYSS/iPaper "$TARGET_REPO"
    else
      git clone --branch main https://github.com/HQYSS/iPaper.git "$TARGET_REPO"
    fi
  fi
else
  log "Repo already present at $TARGET_REPO"
  git -C "$TARGET_REPO" fetch origin main || true
  git -C "$TARGET_REPO" pull --ff-only origin main || log "fast-forward pull skipped; keep existing worktree"
fi

ROOT_DIR="$(cd "$TARGET_REPO" && pwd)"
cd "$ROOT_DIR"

log "Installing Python dependencies"
"$PYTHON_BIN" -m pip install -r backend/requirements.txt
"$PYTHON_BIN" -m pip install -r backend/requirements-dev.txt || true

log "Installing frontend / Electron dependencies"
( cd frontend && npm install )
( cd electron && npm install )
if [ -f e2e/package.json ]; then
  ( cd e2e && npm install ) || true
fi

log "Writing ~/.ipaper/config.json"
"$PYTHON_BIN" - "$SECRETS_PATH" <<'PY'
import json
import os
from pathlib import Path
import sys

secrets = json.loads(Path(sys.argv[1]).read_text())
data_dir = Path.home() / ".ipaper"
data_dir.mkdir(parents=True, exist_ok=True)
config_path = data_dir / "config.json"
config = {}
if config_path.exists():
    config = json.loads(config_path.read_text())

config["sync_role"] = "client"
config["sync_url"] = secrets.get("sync_url") or "https://59.110.154.252/ipaper/api"
config["sync_verify_ssl"] = False
config["sync_token"] = secrets["sync_token"]
config["local_auth_bypass"] = True
if secrets.get("llm"):
    config["llm"] = secrets["llm"]
if "hjfy_cookie" in secrets:
    config["hjfy_cookie"] = secrets.get("hjfy_cookie") or ""

tmp = config_path.with_name(".config.json.bootstrap.tmp")
tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
tmp.replace(config_path)
os.chmod(config_path, 0o600)
print(config_path)
PY

if [ -x "$ROOT_DIR/chrome-extension/native-host/install_native_host.sh" ]; then
  log "Installing Chrome native host"
  "$ROOT_DIR/chrome-extension/native-host/install_native_host.sh" || true
fi

chmod +x "$ROOT_DIR/iPaper.app/Contents/MacOS/iPaper.sh" || true

log "Launching iPaper.app"
open "$ROOT_DIR/iPaper.app" || true

log "Waiting for local backend"
ok=0
for _ in $(seq 1 60); do
  if curl -sf http://127.0.0.1:3000/ >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 2
done
[ "$ok" = "1" ] || die "local backend did not become ready; see $ROOT_DIR/logs/"

curl -sf http://127.0.0.1:3000/api/health/runtime || true
echo

log "Waiting for cloud sync to populate papers"
papers_ok=0
for _ in $(seq 1 45); do
  count="$(curl -sf http://127.0.0.1:3000/api/papers 2>/dev/null | "$PYTHON_BIN" -c 'import json,sys; data=json.load(sys.stdin); print(len(data) if isinstance(data,list) else len(data.get("papers") or data.get("items") or []))' || echo 0)"
  log "local paper count=$count"
  if [ "${count:-0}" -ge 1 ]; then
    papers_ok=1
    break
  fi
  sleep 4
done
[ "$papers_ok" = "1" ] || log "papers not visible yet; backend is up, sync may still be running"

log "BOOTSTRAP_COMPLETE=yes"
log "repo=$ROOT_DIR"
log "log=$LOG_FILE"
