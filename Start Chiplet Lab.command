#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$ROOT_DIR/simplified_rapidchiplet"

if ! command -v python3 >/dev/null 2>&1; then
    echo "找不到 Python 3。請安裝 Python 3.10 或更新版本後，再重新開啟此檔案。"
    open "https://www.python.org/downloads/macos/" >/dev/null 2>&1 || true
    read -r -p "按 Enter 結束……"
    exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Chiplet Lab 需要 Python 3.10 或更新版本。"
    open "https://www.python.org/downloads/macos/" >/dev/null 2>&1 || true
    read -r -p "按 Enter 結束……"
    exit 1
fi

exec python3 "$PROJECT_DIR/scripts/bootstrap_macos.py" --project "$PROJECT_DIR" "$@"
