#!/bin/bash
# Compatibility entry point. The canonical deployment implementation lives
# in deploy-mb.sh because the FastAPI backend runs on mb.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/deploy-mb.sh" "$@"
