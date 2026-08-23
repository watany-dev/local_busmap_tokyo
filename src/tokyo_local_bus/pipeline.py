from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from .config import FeedConfig
from .downloader import DownloadError, download_feed, use_local_zip
from .geojson import (
    build_routes_geojson,
    build_stops_geojson,
    merge_feature_collections,
    write_geojson,
)
from .gtfs import ValidationReport, validate_gtfs, write_report


MAX_ZIP_FILES = 2000
MAX_UNCOMPRESSED_BYTES = 750 * 1024 * 1024


@dataclass(slots=True)
class FeedRunResult:
    feed: FeedConfig
    status: str
    validation: ValidationReport | None = None
    error: str | None = None
    download: dict[str, Any] | None = None
    stop_count: int = 0
    route_geometry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "feed": self.feed.to_dict(),
            "status": self.status,
            "error": self.error,
            "download": self.download,
            "validation": self.validation.to_dict() if self.validation else None,
            "stop_count": self.stop_count,
            "route_geometry_count": self.route_geometry_count,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_extract(zip_path: Path, destination: Path) -> None:
    try:
        with ZipFile(zip_path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_FILES:
                raise ValueError(f"ZIP has too many files: {len(infos)}")
            total = sum(info.file_size for info in infos)
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ValueError(f"ZIP expands to too much data: {total} bytes")
            destination_resolved = destination.resolve()
            for info in infos:
                target = (destination / info.filename).resolve()
                if target != destination_resolved and destination_resolved not in target.parents:
                    raise ValueError(f"Unsafe ZIP path: {info.filename}")
                if info.is_dir():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
    except BadZipFile as exc:
        raise ValueError(f"Invalid ZIP: {zip_path}") from exc


def _flatten_single_directory(directory: Path) -> None:
    txt_files = list(directory.glob("*.txt"))
    children = [path for path in directory.iterdir() if path.is_dir()]
    if txt_files or len(children) != 1:
        return
    child = children[0]
    if not list(child.glob("*.txt")):
        return
    for item in child.iterdir():
        shutil.move(str(item), directory / item.name)
    child.rmdir()


def _extract_atomic(zip_path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{destination.name}-", dir=destination.parent) as temp_dir:
        temp = Path(temp_dir)
        _safe_extract(zip_path, temp)
        _flatten_single_directory(temp)
        old = destination.with_name(destination.name + ".old")
        if old.exists():
            shutil.rmtree(old)
        if destination.exists():
            os.replace(destination, old)
        os.replace(temp, destination)
        if old.exists():
            shutil.rmtree(old)


def ingest_feed(
    feed: FeedConfig,
    data_dir: Path,
    *,
    service_date: date,
    local_zip: Path | None = None,
    timeout_seconds: float = 45.0,
    retries: int = 3,
) -> FeedRunResult:
    raw_dir = data_dir / "raw"
    state_dir = data_dir / "state"
    extracted_dir = data_dir / "extracted" / feed.id
    output_dir = data_dir / "normalized" / feed.slug

    try:
        if local_zip is not None:
            download = use_local_zip(feed, local_zip, raw_dir, state_dir)
        else:
            download = download_feed(
                feed,
                raw_dir,
                state_dir,
                timeout_seconds=timeout_seconds,
                retries=retries,
            )
        _extract_atomic(download.path, extracted_dir)
        report, gtfs = validate_gtfs(feed, extracted_dir, service_date=service_date)
        write_report(output_dir / "validation.json", report)
        if not report.is_valid:
            return FeedRunResult(
                feed=feed,
                status="invalid",
                validation=report,
                download=download.to_dict(),
            )

        stops = build_stops_geojson(feed, gtfs)
        routes = build_routes_geojson(feed, gtfs)
        write_geojson(output_dir / "stops.geojson", stops)
        write_geojson(output_dir / "routes.geojson", routes)
        return FeedRunResult(
            feed=feed,
            status="ok",
            validation=report,
            download=download.to_dict(),
            stop_count=len(stops["features"]),
            route_geometry_count=len(routes["features"]),
        )
    except (DownloadError, OSError, ValueError) as exc:
        return FeedRunResult(
            feed=feed,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )


def aggregate_outputs(data_dir: Path, results: list[FeedRunResult]) -> None:
    stop_collections: list[dict[str, Any]] = []
    route_collections: list[dict[str, Any]] = []
    catalog_feeds: list[dict[str, Any]] = []

    for result in results:
        if result.status != "ok":
            continue
        output_dir = data_dir / "normalized" / result.feed.slug
        stops = json.loads((output_dir / "stops.geojson").read_text(encoding="utf-8"))
        routes = json.loads((output_dir / "routes.geojson").read_text(encoding="utf-8"))
        stop_collections.append(stops)
        route_collections.append(routes)
        catalog_feeds.append(
            {
                **result.feed.to_dict(),
                "status": result.status,
                "stop_count": result.stop_count,
                "route_geometry_count": result.route_geometry_count,
                "feed_start_date": (
                    result.validation.feed_start_date if result.validation else None
                ),
                "feed_end_date": result.validation.feed_end_date if result.validation else None,
                "feed_version": result.validation.feed_version if result.validation else None,
                "active_trip_count": (
                    result.validation.active_trip_count if result.validation else 0
                ),
            }
        )

    aggregate_dir = data_dir / "normalized" / "all"
    write_geojson(
        aggregate_dir / "stops.geojson",
        merge_feature_collections(stop_collections, name="tokyo_local_bus_stops"),
    )
    write_geojson(
        aggregate_dir / "routes.geojson",
        merge_feature_collections(route_collections, name="tokyo_local_bus_routes"),
    )
    catalog = {
        "generated_at": _utc_now(),
        "feed_count": len(catalog_feeds),
        "feeds": catalog_feeds,
    }
    aggregate_dir.mkdir(parents=True, exist_ok=True)
    (aggregate_dir / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_run_report(data_dir: Path, results: list[FeedRunResult]) -> Path:
    report = {
        "generated_at": _utc_now(),
        "total": len(results),
        "ok": sum(result.status == "ok" for result in results),
        "invalid": sum(result.status == "invalid" for result in results),
        "failed": sum(result.status == "failed" for result in results),
        "results": [result.to_dict() for result in results],
    }
    path = data_dir / "state" / "latest-run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
