#!/usr/bin/env python3
"""GitHub Pages向け静的サイトをHTTPで検証する。

Python APIは使わない。`export_pages.py` が出力したディレクトリを一時ポートに載せ、
HTML・JS・GeoJSONが相対パスで配信されることと、フロントが `/api/` に依存していない
ことを確認する。

終了コード:
  0 全チェック成功
  1 いずれかのチェック失敗
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def _get(base: str, path: str) -> tuple[int, bytes]:
    with urlopen(base + path, timeout=10) as response:  # noqa: S310
        return response.status, response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", default="site")
    args = parser.parse_args()

    site_dir = Path(args.site_dir).resolve()
    if not (site_dir / "index.html").is_file():
        print(json.dumps({"status": "error", "error": f"missing index.html in {site_dir}"}, ensure_ascii=False))
        return 1

    handler = partial(_QuietHandler, directory=str(site_dir))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    failures: list[str] = []
    summary: dict[str, object] = {"base_url": base, "site_dir": str(site_dir)}
    try:
        status, index = _get(base, "/")
        html = index.decode("utf-8", errors="replace")
        if status != 200 or "<html" not in html.lower():
            failures.append(f"/: status={status}")
        if 'href="/styles.css"' in html or 'src="/app.js"' in html:
            failures.append("index.html uses root-absolute asset paths (breaks project Pages)")
        if 'href="styles.css"' not in html or 'src="app.js"' not in html:
            failures.append("index.html is missing relative asset paths")

        status, app_js = _get(base, "/app.js")
        script = app_js.decode("utf-8", errors="replace")
        if status != 200 or "nearbyStops" not in script:
            failures.append(f"/app.js: status={status} or nearbyStops missing")
        if "/api/" in script:
            failures.append("app.js still calls /api/ (not static-hostable)")
        if 'DATA_BASE = "data/normalized/all"' not in script and "data/normalized/all" not in script:
            failures.append("app.js is not loading GeoJSON via relative data paths")

        status, catalog_body = _get(base, "/data/normalized/all/catalog.json")
        if status != 200:
            failures.append(f"/data/normalized/all/catalog.json: status={status}")
        else:
            catalog = json.loads(catalog_body)
            summary["feed_count"] = catalog.get("feed_count")

        status, stops_body = _get(base, "/data/normalized/all/stops.geojson")
        if status != 200:
            failures.append(f"/data/normalized/all/stops.geojson: status={status}")
        else:
            stops = json.loads(stops_body)
            summary["stop_features"] = len(stops.get("features", []))

        status, routes_body = _get(base, "/data/normalized/all/routes.geojson")
        if status != 200:
            failures.append(f"/data/normalized/all/routes.geojson: status={status}")
        else:
            routes = json.loads(routes_body)
            summary["route_features"] = len(routes.get("features", []))
    finally:
        httpd.shutdown()
        httpd.server_close()

    summary["status"] = "ok" if not failures else "error"
    summary["errors"] = failures
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
