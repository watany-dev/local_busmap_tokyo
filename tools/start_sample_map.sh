#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="$ROOT_DIR"
PYTHON="$PROJECT_DIR/.venv/bin/python"
PORT="${PORT:-8000}"

if [ ! -x "$PYTHON" ]; then
  echo "error: .venvがありません。先に tools/bootstrap.sh を実行してください。" >&2
  exit 2
fi
export PYTHONPATH="$PROJECT_DIR/src"
cd "$PROJECT_DIR"
exec "$PYTHON" -m tokyo_local_bus serve \
  --data-dir data/sample-run \
  --web-dir web \
  --host 127.0.0.1 \
  --port "$PORT"
