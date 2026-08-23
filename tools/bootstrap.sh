#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="$ROOT_DIR"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="$PROJECT_DIR/.venv"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: $PYTHON_BIN が見つかりません。Python 3.11以上をインストールしてください。" >&2
  exit 2
fi

"$PYTHON_BIN" - <<'PY_VERSION_CHECK'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"Python 3.11以上が必要です: {sys.version.split()[0]}")
print(f"Python: {sys.version.split()[0]}")
PY_VERSION_CHECK

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
export PYTHONPATH="$PROJECT_DIR/src"
cd "$PROJECT_DIR"

python "$ROOT_DIR/tools/verify_repo.py"
python -m tokyo_local_bus validate-config
python -m unittest discover -s tests -v
rm -rf data/sample-run
python -m tokyo_local_bus ingest \
  --config tests/fixtures/test-feeds.json \
  --data-dir data/sample-run \
  --date 2026-08-22 \
  --local-zip TEST=tests/fixtures/minimal_gtfs.zip

cat <<EOF

セットアップとオフライン検証が完了しました。
サンプル地図を起動:
  $ROOT_DIR/tools/start_sample_map.sh

Kバスの実データ取得を開始（配布元へのHTTPS接続が必要）:
  $ROOT_DIR/tools/run_live_kbus.sh
EOF
