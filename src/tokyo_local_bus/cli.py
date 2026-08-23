from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .config import FeedConfig, load_feeds
from .pipeline import aggregate_outputs, ingest_feed, write_run_report
from .server import serve


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def _parse_local_zip(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--local-zip must be FEED_ID=PATH: {value}")
        feed_id, path = value.split("=", 1)
        result[feed_id] = Path(path)
    return result


def _select_feeds(feeds: list[FeedConfig], requested: list[str]) -> list[FeedConfig]:
    if not requested:
        return feeds
    by_id = {feed.id: feed for feed in feeds}
    missing = sorted(set(requested) - by_id.keys())
    if missing:
        raise ValueError(f"Unknown feed id(s): {', '.join(missing)}")
    return [by_id[feed_id] for feed_id in requested]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tokyo-local-bus",
        description="東京都内ローカルバスのGTFSを取得・検証し、GeoJSONへ正規化する",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_parser = subparsers.add_parser("validate-config", help="フィード設定を検証")
    config_parser.add_argument("--config", default="config/feeds.json")

    ingest = subparsers.add_parser("ingest", help="GTFSを取得・検証・GeoJSON化")
    ingest.add_argument("--config", default="config/feeds.json")
    ingest.add_argument("--data-dir", default="data")
    ingest.add_argument("--feed", action="append", default=[], help="対象フィードID。複数指定可")
    ingest.add_argument("--date", type=_parse_date, default=date.today())
    ingest.add_argument(
        "--local-zip",
        action="append",
        default=[],
        metavar="FEED_ID=PATH",
        help="ネットワーク取得せず指定ZIPを使用",
    )
    ingest.add_argument("--timeout", type=float, default=45.0)
    ingest.add_argument("--retries", type=int, default=3)
    ingest.add_argument(
        "--allow-partial",
        action="store_true",
        help="一部失敗でも1件以上成功していれば終了コード0",
    )

    server = subparsers.add_parser("serve", help="地図プレビューと近傍停留所APIを起動")
    server.add_argument("--web-dir", default="web")
    server.add_argument("--data-dir", default="data")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-config":
            feeds = load_feeds(args.config)
            print(json.dumps({"status": "ok", "feed_count": len(feeds)}, ensure_ascii=False))
            return 0

        if args.command == "serve":
            serve(
                web_dir=Path(args.web_dir),
                data_dir=Path(args.data_dir),
                host=args.host,
                port=args.port,
            )
            return 0

        feeds = _select_feeds(load_feeds(args.config), args.feed)
        local_zips = _parse_local_zip(args.local_zip)
        unknown_local = sorted(set(local_zips) - {feed.id for feed in feeds})
        if unknown_local:
            raise ValueError(
                "--local-zip specifies feed(s) not selected: " + ", ".join(unknown_local)
            )
        data_dir = Path(args.data_dir)
        results = []
        for feed in feeds:
            print(f"[{feed.id}] {feed.municipality} {feed.service_name}: start", flush=True)
            result = ingest_feed(
                feed,
                data_dir,
                service_date=args.date,
                local_zip=local_zips.get(feed.id),
                timeout_seconds=args.timeout,
                retries=args.retries,
            )
            results.append(result)
            detail = result.error or (
                f"stops={result.stop_count}, route_geometries={result.route_geometry_count}"
            )
            print(f"[{feed.id}] {result.status}: {detail}", flush=True)

        aggregate_outputs(data_dir, results)
        report_path = write_run_report(data_dir, results)
        ok = sum(result.status == "ok" for result in results)
        failures = len(results) - ok
        print(f"run report: {report_path}")
        print(f"done: {ok} ok, {failures} failed/invalid")
        if failures == 0:
            return 0
        if args.allow_partial and ok > 0:
            return 0
        return 1 if ok > 0 else 2
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
