#!/usr/bin/env python3
"""GitHub Pages向けの静的サイトを組み立てる。

GitHub Pagesは静的ファイルだけを配信できる。Python APIもWASMも使わない。
地図（MapLibre）と近傍検索（Haversine）はブラウザのJavaScriptで動き、
正規化済みGeoJSONを同じオリジンから読む。

終了コード:
  0 書き出し成功
  1 入力不足（web資産の欠落）
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_FILES = ("index.html", "app.js", "styles.css")
DATA_FILES = ("stops.geojson", "routes.geojson", "catalog.json")
EMPTY_COLLECTION = {"type": "FeatureCollection", "features": []}
EMPTY_CATALOG = {"generated_at": None, "feed_count": 0, "feeds": []}


def _copy_or_write_json(source: Path, destination: Path, fallback: object) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copy2(source, destination)
        return
    destination.write_text(
        json.dumps(fallback, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def export_static_site(*, web_dir: Path, data_dir: Path, out_dir: Path) -> dict[str, object]:
    missing = [name for name in WEB_FILES if not (web_dir / name).is_file()]
    if missing:
        raise FileNotFoundError("web assets missing: " + ", ".join(missing))

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    for name in WEB_FILES:
        shutil.copy2(web_dir / name, out_dir / name)

    aggregate = data_dir / "normalized" / "all"
    copied: dict[str, str] = {}
    for name in DATA_FILES:
        destination = out_dir / "data" / "normalized" / "all" / name
        fallback: object = EMPTY_CATALOG if name == "catalog.json" else EMPTY_COLLECTION
        _copy_or_write_json(aggregate / name, destination, fallback)
        copied[name] = "copied" if (aggregate / name).is_file() else "empty-fallback"

    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    catalog = json.loads((out_dir / "data/normalized/all/catalog.json").read_text(encoding="utf-8"))
    stops = json.loads((out_dir / "data/normalized/all/stops.geojson").read_text(encoding="utf-8"))
    routes = json.loads((out_dir / "data/normalized/all/routes.geojson").read_text(encoding="utf-8"))
    return {
        "status": "ok",
        "out_dir": str(out_dir),
        "feed_count": catalog.get("feed_count", 0),
        "stop_features": len(stops.get("features", [])),
        "route_features": len(routes.get("features", [])),
        "data_files": copied,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-dir", default=str(ROOT / "web"))
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--out", default=str(ROOT / "site"))
    args = parser.parse_args()

    try:
        summary = export_static_site(
            web_dir=Path(args.web_dir),
            data_dir=Path(args.data_dir),
            out_dir=Path(args.out),
        )
    except FileNotFoundError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
