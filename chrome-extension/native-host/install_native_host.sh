#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOST_SCRIPT="$SCRIPT_DIR/ipaper_native_host.py"
HOST_NAME="com.ipaper.native_host"
DEFAULT_EXTENSION_ID="niopfodkcphjggappggakadlgkddlogf"
CHROME_HOST_DIRS=(
  "$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
  "$HOME/Library/Application Support/Google/Chrome for Testing/NativeMessagingHosts"
  "$HOME/Library/Application Support/Chromium/NativeMessagingHosts"
)

usage() {
  cat <<EOF
用法:
  $0
  $0 <Chrome 扩展 ID>
  $0 --uninstall

说明:
  chrome-extension/manifest.json 已内置稳定 key，默认扩展 ID 为:
  $DEFAULT_EXTENSION_ID
EOF
}

if [ "${1:-}" = "--uninstall" ]; then
  for host_dir in "${CHROME_HOST_DIRS[@]}"; do
    rm -f "$host_dir/$HOST_NAME.json"
    echo "已卸载 $host_dir/$HOST_NAME.json"
  done
  exit 0
fi

EXTENSION_ID="${1:-$DEFAULT_EXTENSION_ID}"

if [[ ! "$EXTENSION_ID" =~ ^[a-p]{32}$ ]]; then
  echo "扩展 ID 格式不正确：$EXTENSION_ID" >&2
  echo "Chrome 扩展 ID 通常是 32 位 a-p 字符。" >&2
  exit 1
fi

chmod +x "$HOST_SCRIPT"

for host_dir in "${CHROME_HOST_DIRS[@]}"; do
  mkdir -p "$host_dir"
  host_manifest="$host_dir/$HOST_NAME.json"
  cat > "$host_manifest" <<EOF
{
  "name": "$HOST_NAME",
  "description": "iPaper Chrome extension native host",
  "path": "$HOST_SCRIPT",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://$EXTENSION_ID/"
  ]
}
EOF

  echo "已安装 Native Messaging host:"
  echo "$host_manifest"
done
