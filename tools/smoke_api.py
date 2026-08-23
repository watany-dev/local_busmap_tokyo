#!/usr/bin/env python3
"""正規化済みデータに対してHTTP APIと地図配信のスモークテストを行う。

`create_handler` を実ポートに載せて、ネットワーク外部依存なしで
`/api/health`、`/api/feeds`、`/api/routes`、`/api/stops/nearby`、`/` を確認する。
合成データ（`data/sample-run`）でも実データ（`data`）でも動作する。

終了コード:
  0 全チェック成功
  1 いずれかのチェック失敗
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tokyo_local_bus.server import create_handler  # noqa: E402


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True


def _get(base: str, path: str) -> tuple[int, object]:
    with urllib.request.urlopen(base + path, timeout=10) as response:  # noqa: S310
        body = response.read()
        status = response.status
    content_type = ""
    try:
        content_type = response.headers.get("Content-Type", "")
    except AttributeError:
        pass
    if "json" in content_type:
        return status, json.loads(body)
    return status, body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--web-dir", default="web")
    parser.add_argument("--lat", type=float, default=35.7521)
    parser.add_argument("--lon", type=float, default=139.7386)
    parser.add_argument("--radius", type=float, default=100_000)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    handler = create_handler(root / args.web_dir, root / args.data_dir)

    # 静粛化: スモークテスト中のアクセスログは出力しない。
    handler.log_message = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    httpd = _QuietServer(("127.0.0.1", 0), handler)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    failures: list[str] = []
    summary: dict[str, object] = {"base_url": base, "data_dir": str(args.data_dir)}
    try:
        status, health = _get(base, "/api/health")
        if status != 200 or not isinstance(health, dict) or health.get("status") != "ok":
            failures.append(f"/api/health: status={status} body={health!r}")
        else:
            summary["feed_count"] = health.get("feed_count")

        status, feeds = _get(base, "/api/feeds")
        if status != 200 or not isinstance(feeds, dict) or "feeds" not in feeds:
            failures.append(f"/api/feeds: status={status}")

        status, routes = _get(base, "/api/routes")
        if status != 200 or not isinstance(routes, dict):
            failures.append(f"/api/routes: status={status}")
        else:
            summary["route_features"] = len(routes.get("features", []))

        query = f"/api/stops/nearby?lat={args.lat}&lon={args.lon}&radius={args.radius}&limit=50"
        status, nearby = _get(base, query)
        if status != 200 or not isinstance(nearby, dict):
            failures.append(f"/api/stops/nearby: status={status}")
        else:
            features = nearby.get("features", [])
            summary["nearby_features"] = len(features)
            distances = [f["properties"]["distance_m"] for f in features]
            if distances != sorted(distances):
                failures.append("/api/stops/nearby: results are not sorted by distance")

        status, index = _get(base, "/")
        if status != 200 or b"<html" not in bytes(index).lower():
            failures.append(f"/: status={status}")
    finally:
        httpd.shutdown()
        httpd.server_close()

    summary["status"] = "ok" if not failures else "error"
    summary["errors"] = failures
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
