#!/usr/bin/env bash
# 从 frontend/public/icons/icon-1024.png 生成 macOS .icns 文件，
# 同时同步到：
#   - electron/iPaper.icns       (Electron 运行时 app.dock.setIcon 用)
#   - iPaper.app/Contents/Resources/applet.icns (双击 iPaper.app 时 Finder/Dock 显示的图标)
#
# 用法：
#   ./scripts/generate-macos-icns.sh
#
# 替换图标素材的标准流程：
#   1. 改 assets/m1-letter-i.png 或换源图
#   2. 跑 /tmp/ipaper-icon-design/generate_icons.py（重新生成全套 PNG 到 frontend/public/icons/）
#   3. 跑本脚本（生成 .icns 并同步到 Electron 和 iPaper.app）
#   4. ./scripts/deploy.sh 把 PWA 端的 PNG 推到 moshang.xyz
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/frontend/public/icons/icon-1024.png"
OUT_ICNS="$ROOT/electron/iPaper.icns"
APPLET_ICNS="$ROOT/iPaper.app/Contents/Resources/applet.icns"

if [ ! -f "$SRC" ]; then
  echo "[ERROR] 源图不存在：$SRC" >&2
  echo "       请先跑 /tmp/ipaper-icon-design/generate_icons.py 生成 PNG 全套" >&2
  exit 1
fi

if ! command -v sips >/dev/null 2>&1; then
  echo "[ERROR] 找不到 sips（macOS 自带），当前可能不在 macOS 上" >&2
  exit 1
fi

if ! command -v iconutil >/dev/null 2>&1; then
  echo "[ERROR] 找不到 iconutil（macOS 自带），当前可能不在 macOS 上" >&2
  exit 1
fi

WORK="$(mktemp -d)"
ICONSET="$WORK/iPaper.iconset"
mkdir -p "$ICONSET"

echo "[INFO] 从 $SRC 生成 .iconset"
# macOS 标准 .iconset 命名约定：基础尺寸 + @2x 高分屏版本
sips -z 16   16   "$SRC" --out "$ICONSET/icon_16x16.png"      >/dev/null
sips -z 32   32   "$SRC" --out "$ICONSET/icon_16x16@2x.png"   >/dev/null
sips -z 32   32   "$SRC" --out "$ICONSET/icon_32x32.png"      >/dev/null
sips -z 64   64   "$SRC" --out "$ICONSET/icon_32x32@2x.png"   >/dev/null
sips -z 128  128  "$SRC" --out "$ICONSET/icon_128x128.png"    >/dev/null
sips -z 256  256  "$SRC" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
sips -z 256  256  "$SRC" --out "$ICONSET/icon_256x256.png"    >/dev/null
sips -z 512  512  "$SRC" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
sips -z 512  512  "$SRC" --out "$ICONSET/icon_512x512.png"    >/dev/null
cp "$SRC" "$ICONSET/icon_512x512@2x.png"

echo "[INFO] 编译 .icns"
iconutil -c icns "$ICONSET" -o "$OUT_ICNS"

echo "[INFO] 写到 Electron：$OUT_ICNS"

if [ -f "$APPLET_ICNS" ]; then
  cp "$OUT_ICNS" "$APPLET_ICNS"
  echo "[INFO] 同步到 applet：$APPLET_ICNS"
else
  echo "[WARN] iPaper.app 不存在，跳过 applet.icns 同步"
fi

# 触发 Finder/Dock 重读图标缓存（不用 sudo 也能让当前 app 包刷新）
if [ -d "$ROOT/iPaper.app" ]; then
  touch "$ROOT/iPaper.app"
  killall Finder 2>/dev/null || true
  killall Dock 2>/dev/null || true
  echo "[INFO] 已 touch iPaper.app + 重启 Finder/Dock，新图标应立即生效"
fi

rm -rf "$WORK"

echo "[INFO] 完成。要看到 Electron 运行时 Dock 图标更新，下次启动 iPaper.app 即可。"
