#!/usr/bin/env bash
# 从 frontend/public/icons/icon-1024.png 生成 macOS .icns 文件，
# 同时同步到：
#   - electron/iPaper.icns       (Electron 运行时 app.dock.setIcon 用)
#   - iPaper.app/Contents/Resources/applet.icns (双击 iPaper.app 时 Finder/Dock 显示的图标)
#
# 关键：PWA 的 PNG 是整张紫色背景方形（iOS / Android 会自己加 mask），但 macOS Big Sur+
# 的 Dock 图标都是 squircle 圆角 + 内 padding 设计语言，源图直接拿来做 .icns 在 Dock 里
# 跟其他 app 排在一起会显得正方形突兀。所以本脚本会先用 PIL 给源图加 squircle mask
# + 100px 透明边距，再编 .icns —— 输出和系统其他 app 视觉风格对齐。
#
# 用法：
#   ./scripts/generate-macos-icns.sh
#
# 替换图标素材的标准流程：
#   1. 改源图（assets/m1-letter-i.png 等）
#   2. 跑 /tmp/ipaper-icon-design/generate_icons.py（重新生成全套 PNG 到 frontend/public/icons/）
#   3. 跑本脚本（自动加 macOS squircle，生成 .icns 并同步到 Electron 和 iPaper.app）
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

# 优先用 conda Python（PIL 通常在那里），找不到就 fallback 到 python3
PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  if [ -x "/Users/admin/miniconda3/bin/python" ]; then
    PYTHON_BIN="/Users/admin/miniconda3/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    echo "[ERROR] 找不到 python，无法做 squircle mask" >&2
    exit 1
  fi
fi

if ! "$PYTHON_BIN" -c "from PIL import Image" >/dev/null 2>&1; then
  echo "[ERROR] $PYTHON_BIN 没装 Pillow（PIL）。装一下：$PYTHON_BIN -m pip install Pillow" >&2
  exit 1
fi

WORK="$(mktemp -d)"
ICONSET="$WORK/iPaper.iconset"
mkdir -p "$ICONSET"

# Step 1: 给源图套 macOS squircle mask + 100px 透明边距
# macOS Big Sur+ 应用图标设计模板：1024 画布内 824x824 圆角方块，圆角半径 ≈ 22.37% × 824
# 我们用 PIL 的 rounded_rectangle 近似（普通圆角矩形跟 superellipse squircle 视觉差极小）
#
# CONTENT_ZOOM：把源图先放大 + 居中裁剪再套 squircle，让 i 字母在画面里更饱满。
# 源图（icon-1024.png）四周都是紫色背景，裁掉外圈不损失内容。
# 1.0 = 原图直接缩到 squircle；1.25 = 源图放大 25%、裁中心，i 看起来明显更大。
MASKED="$WORK/icon-macos-1024.png"
CONTENT_ZOOM="${CONTENT_ZOOM:-1.25}"
echo "[INFO] 给 $SRC 加 macOS squircle mask（content zoom = $CONTENT_ZOOM）→ $MASKED"
"$PYTHON_BIN" - "$SRC" "$MASKED" "$CONTENT_ZOOM" <<'PY'
import sys
from PIL import Image, ImageDraw

src_path, out_path, zoom_str = sys.argv[1], sys.argv[2], sys.argv[3]
zoom = float(zoom_str)

CANVAS = 1024
ICON = 824                           # macOS Big Sur+ 模板：1024 内 824 实心
PAD = (CANVAS - ICON) // 2           # 100
RADIUS = round(ICON * 0.2237)        # ≈ 184

src = Image.open(src_path).convert("RGBA")
W, H = src.size

if zoom != 1.0:
    # 先放大整张源图，再居中裁剪回原始尺寸 —— 等价于"放大主体，丢掉边缘留白"
    zw, zh = round(W * zoom), round(H * zoom)
    zoomed = src.resize((zw, zh), Image.LANCZOS)
    left = (zw - W) // 2
    top = (zh - H) // 2
    src = zoomed.crop((left, top, left + W, top + H))

if src.size != (ICON, ICON):
    src = src.resize((ICON, ICON), Image.LANCZOS)

mask = Image.new("L", (ICON, ICON), 0)
draw = ImageDraw.Draw(mask)
draw.rounded_rectangle((0, 0, ICON, ICON), radius=RADIUS, fill=255)

# 用 mask 替换原 alpha
src.putalpha(mask)

canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
canvas.paste(src, (PAD, PAD), src)
canvas.save(out_path, format="PNG")
PY

SRC="$MASKED"

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

# 同步一份 squircle 后的 1024 PNG 给 Electron app.dock.setIcon 使用。
# 之前踩过坑：Electron 28 在 macOS 上对 .icns 解析偶尔抛 "Failed to load image"，
# 导致 main.js 的 whenReady 回调链 abort、createWindow 永远不调、用户看不到窗口。
# PNG 是 Electron NativeImage 最稳的输入，作为 dock.setIcon 的首选。
DOCK_PNG="$ROOT/electron/iPaper-dock.png"
cp "$MASKED" "$DOCK_PNG"
echo "[INFO] 同步 squircle PNG 给 Electron Dock：$DOCK_PNG"

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
