#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="$ROOT_DIR"
PYTHON="$PROJECT_DIR/.venv/bin/python"
SERVICE_DATE="${SERVICE_DATE:-$(date +%F)}"

if [ ! -x "$PYTHON" ]; then
  echo "error: .venvがありません。先に tools/bootstrap.sh を実行してください。" >&2
  exit 2
fi
export PYTHONPATH="$PROJECT_DIR/src"
cd "$PROJECT_DIR"
exec "$PYTHON" -m tokyo_local_bus ingest --feed F005 --date "$SERVICE_DATE"
