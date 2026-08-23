#!/usr/bin/env python3
"""リポジトリの前提条件を検証する。

引き継ぎパッケージ同梱の `verify_handoff.py` を、リポジトリ用に置き換えたもの。
パッケージ版はZIP同梱物のチェックサム照合が主目的だったが、リポジトリでは
ファイルの完全性はGitが担保するため、ここでは実行環境・ランタイム設定・
台帳ファイル・テストフィクスチャが揃っているかを検証する。

終了コード:
  0 検証成功
  1 検証失敗
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_FEED_COUNT = 21
ALLOWED_SCHEMES = {"https"}

REQUIRED_PATHS = [
    "config/feeds.json",
    "config/external_verification_2026-08-22.json",
    "config/external_verification_2026-08-22.csv",
    "src/tokyo_local_bus/cli.py",
    "tests/fixtures/minimal_gtfs.zip",
    "tests/fixtures/test-feeds.json",
    "web/index.html",
    "sql/schema.sql",
    "scripts/load_postgis.py",
]

INVENTORY_WORKBOOKS = [
    "inventory/tokyo_local_bus_inventory_2026-08-22.xlsx",
    "inventory/tokyo_local_bus_inventory_2026-08-22_next_phase.xlsx",
]


def check_python(errors: list[str]) -> None:
    if sys.version_info < (3, 11):
        errors.append(f"Python 3.11以上が必要です: {sys.version.split()[0]}")


def check_required_paths(errors: list[str]) -> None:
    for rel in REQUIRED_PATHS:
        if not (ROOT / rel).is_file():
            errors.append(f"missing: {rel}")


def check_feeds(errors: list[str]) -> int:
    path = ROOT / "config" / "feeds.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        feeds = data["feeds"]
    except (OSError, ValueError, KeyError) as exc:
        errors.append(f"feeds.json parse error: {exc}")
        return 0

    if len(feeds) != EXPECTED_FEED_COUNT:
        errors.append(f"feed count: expected {EXPECTED_FEED_COUNT}, got {len(feeds)}")

    ids = [feed.get("id") for feed in feeds]
    slugs = [feed.get("slug") for feed in feeds]
    if len(ids) != len(set(ids)):
        errors.append("duplicate feed id")
    if len(slugs) != len(set(slugs)):
        errors.append("duplicate feed slug")

    for feed in feeds:
        for key in ("id", "slug", "municipality", "service_name", "url", "license"):
            if not feed.get(key):
                errors.append(f"feed {feed.get('id', '?')}: missing field {key}")
        scheme = urllib.parse.urlparse(feed.get("url", "")).scheme
        if scheme not in ALLOWED_SCHEMES:
            errors.append(f"feed {feed.get('id', '?')}: url scheme must be https")

    return len(feeds)


def check_workbooks(errors: list[str]) -> None:
    for rel in INVENTORY_WORKBOOKS:
        path = ROOT / rel
        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                errors.append(f"invalid xlsx structure: {path.name}")
        except (OSError, zipfile.BadZipFile) as exc:
            errors.append(f"xlsx open error {path.name}: {exc}")


def main() -> int:
    errors: list[str] = []
    check_python(errors)
    check_required_paths(errors)
    feed_count = check_feeds(errors)
    check_workbooks(errors)

    result = {
        "status": "ok" if not errors else "error",
        "python": sys.version.split()[0],
        "feed_count": feed_count,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
