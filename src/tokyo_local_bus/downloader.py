from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from .config import FeedConfig


USER_AGENT = "tokyo-local-bus-collector/0.1 (+GTFS research; contact operator before heavy use)"
DEFAULT_MAX_BYTES = 250 * 1024 * 1024


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DownloadResult:
    feed_id: str
    status: str
    path: Path
    requested_url: str
    resolved_url: str
    size_bytes: int
    sha256: str
    downloaded_at: str
    etag: str | None = None
    last_modified: str | None = None
    reused_existing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "feed_id": self.feed_id,
            "status": self.status,
            "path": str(self.path),
            "requested_url": self.requested_url,
            "resolved_url": self.resolved_url,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "downloaded_at": self.downloaded_at,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "reused_existing": self.reused_existing,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _check_zip(path: Path) -> None:
    try:
        with ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise DownloadError(f"ZIP CRC check failed: {bad_member}")
    except BadZipFile as exc:
        raise DownloadError(f"Downloaded content is not a valid ZIP: {path}") from exc


def use_local_zip(feed: FeedConfig, source: str | Path, raw_dir: Path, state_dir: Path) -> DownloadResult:
    source_path = Path(source).resolve()
    if not source_path.is_file():
        raise DownloadError(f"Local ZIP does not exist: {source_path}")
    _check_zip(source_path)

    destination_dir = raw_dir / feed.id
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / "feed.zip"
    temp = destination.with_suffix(".zip.tmp")
    with source_path.open("rb") as src, temp.open("wb") as dst:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            dst.write(chunk)
    os.replace(temp, destination)

    result = DownloadResult(
        feed_id=feed.id,
        status="ok-local",
        path=destination,
        requested_url=feed.url,
        resolved_url=source_path.as_uri(),
        size_bytes=destination.stat().st_size,
        sha256=_sha256(destination),
        downloaded_at=_utc_now(),
        reused_existing=False,
    )
    _atomic_json(state_dir / f"{feed.id}.download.json", result.to_dict())
    return result


def download_feed(
    feed: FeedConfig,
    raw_dir: Path,
    state_dir: Path,
    *,
    timeout_seconds: float = 45.0,
    retries: int = 3,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> DownloadResult:
    destination_dir = raw_dir / feed.id
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / "feed.zip"
    state_path = state_dir / f"{feed.id}.download.json"
    previous = _read_json(state_path)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/zip, application/octet-stream, */*;q=0.8",
    }
    if destination.exists():
        if previous.get("etag"):
            headers["If-None-Match"] = str(previous["etag"])
        if previous.get("last_modified"):
            headers["If-Modified-Since"] = str(previous["last_modified"])

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(feed.url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                resolved_url = response.geturl()
                length_header = response.headers.get("Content-Length")
                if length_header and int(length_header) > max_bytes:
                    raise DownloadError(
                        f"Response exceeds maximum size: {length_header} > {max_bytes} bytes"
                    )

                temp = destination.with_suffix(".zip.part")
                total = 0
                digest = hashlib.sha256()
                with temp.open("wb") as stream:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise DownloadError(
                                f"Response exceeds maximum size while downloading: {total} bytes"
                            )
                        digest.update(chunk)
                        stream.write(chunk)
                _check_zip(temp)
                os.replace(temp, destination)

                result = DownloadResult(
                    feed_id=feed.id,
                    status="ok",
                    path=destination,
                    requested_url=feed.url,
                    resolved_url=resolved_url,
                    size_bytes=total,
                    sha256=digest.hexdigest(),
                    downloaded_at=_utc_now(),
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    reused_existing=False,
                )
                _atomic_json(state_path, result.to_dict())
                return result
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and destination.exists():
                _check_zip(destination)
                result = DownloadResult(
                    feed_id=feed.id,
                    status="not-modified",
                    path=destination,
                    requested_url=feed.url,
                    resolved_url=str(previous.get("resolved_url") or feed.url),
                    size_bytes=destination.stat().st_size,
                    sha256=str(previous.get("sha256") or _sha256(destination)),
                    downloaded_at=_utc_now(),
                    etag=str(previous.get("etag")) if previous.get("etag") else None,
                    last_modified=(
                        str(previous.get("last_modified")) if previous.get("last_modified") else None
                    ),
                    reused_existing=True,
                )
                _atomic_json(state_path, result.to_dict())
                return result
            last_error = exc
        except (OSError, ValueError, DownloadError, urllib.error.URLError) as exc:
            last_error = exc

        if attempt < retries:
            time.sleep(min(2 ** (attempt - 1), 8))

    failure = {
        "feed_id": feed.id,
        "status": "failed",
        "requested_url": feed.url,
        "failed_at": _utc_now(),
        "error": f"{type(last_error).__name__}: {last_error}",
        "reused_existing": False,
    }
    _atomic_json(state_path, failure)
    raise DownloadError(f"{feed.id} download failed after {retries} attempt(s): {last_error}")
