from __future__ import annotations

import json
import math
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


EARTH_RADIUS_M = 6_371_008.8
NEARBY_RADIUS_MIN_M = 10.0
NEARBY_RADIUS_MAX_M = 20_000.0
NEARBY_LIMIT_MIN = 1
NEARBY_LIMIT_MAX = 500


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def clamp_nearby_params(radius_m: float, limit: int) -> tuple[float, int]:
    return (
        min(max(radius_m, NEARBY_RADIUS_MIN_M), NEARBY_RADIUS_MAX_M),
        min(max(limit, NEARBY_LIMIT_MIN), NEARBY_LIMIT_MAX),
    )


def nearby_stops(
    collection: dict[str, Any],
    *,
    lat: float,
    lon: float,
    radius_m: float,
    limit: int,
) -> dict[str, Any]:
    """現在地から半径内の停留所を距離昇順で返す。GitHub Pages用JSと同じ計算。"""
    radius_m, limit = clamp_nearby_params(radius_m, limit)
    matches: list[dict[str, Any]] = []
    for feature in collection.get("features", []):
        try:
            stop_lon, stop_lat = feature["geometry"]["coordinates"]
            distance = haversine_m(lat, lon, float(stop_lat), float(stop_lon))
        except (KeyError, TypeError, ValueError):
            continue
        if distance <= radius_m:
            copied = dict(feature)
            copied["properties"] = dict(feature.get("properties") or {})
            copied["properties"]["distance_m"] = round(distance, 1)
            matches.append(copied)
    matches.sort(key=lambda feature: feature["properties"]["distance_m"])
    return {
        "type": "FeatureCollection",
        "query": {"lat": lat, "lon": lon, "radius_m": radius_m, "limit": limit},
        "features": matches[:limit],
    }


def _load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def create_handler(web_dir: Path, data_dir: Path) -> type[BaseHTTPRequestHandler]:
    web_root = web_dir.resolve()
    data_root = data_dir.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "TokyoLocalBus/0.1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self._handle_api(parsed.path, parse_qs(parsed.query))
                return
            self._handle_static(parsed.path)

        def _handle_api(self, path: str, query: dict[str, list[str]]) -> None:
            if path == "/api/health":
                catalog = _load_json(data_root / "normalized/all/catalog.json", {})
                self._json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "feed_count": catalog.get("feed_count", 0),
                        "generated_at": catalog.get("generated_at"),
                    },
                )
                return
            if path == "/api/feeds":
                self._json(
                    HTTPStatus.OK,
                    _load_json(
                        data_root / "normalized/all/catalog.json",
                        {"generated_at": None, "feed_count": 0, "feeds": []},
                    ),
                )
                return
            if path == "/api/stops/nearby":
                self._nearby(query)
                return
            if path == "/api/routes":
                self._json(
                    HTTPStatus.OK,
                    _load_json(
                        data_root / "normalized/all/routes.geojson",
                        {"type": "FeatureCollection", "features": []},
                    ),
                )
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "API endpoint not found"})

        def _nearby(self, query: dict[str, list[str]]) -> None:
            try:
                lat = float(query["lat"][0])
                lon = float(query["lon"][0])
                radius_m = float(query.get("radius", ["800"])[0])
                limit = int(query.get("limit", ["50"])[0])
            except (KeyError, IndexError, ValueError):
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "lat and lon are required; radius and limit must be numeric"},
                )
                return
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "lat/lon out of range"})
                return

            collection = _load_json(
                data_root / "normalized/all/stops.geojson",
                {"type": "FeatureCollection", "features": []},
            )
            self._json(
                HTTPStatus.OK,
                nearby_stops(
                    collection,
                    lat=lat,
                    lon=lon,
                    radius_m=radius_m,
                    limit=limit,
                ),
            )

        def _handle_static(self, path: str) -> None:
            clean = unquote(path)
            if clean == "/":
                target = web_root / "index.html"
            elif clean.startswith("/data/"):
                target = (data_root / clean.removeprefix("/data/")).resolve()
                if target != data_root and data_root not in target.parents:
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
            else:
                target = (web_root / clean.lstrip("/")).resolve()
                if target != web_root and web_root not in target.parents:
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
            if not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            payload = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, status: HTTPStatus, value: Any) -> None:
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            print(f"{self.address_string()} - {format % args}")

    return Handler


def serve(*, web_dir: Path, data_dir: Path, host: str, port: int) -> None:
    handler = create_handler(web_dir, data_dir)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"Tokyo local bus map: http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
