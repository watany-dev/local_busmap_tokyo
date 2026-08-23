from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from .config import FeedConfig
from .gtfs import GtfsData


def normalized_id(feed_id: str, source_id: str) -> str:
    return f"{feed_id}:{source_id}"


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _valid_hex(value: str) -> str | None:
    cleaned = (value or "").strip().lstrip("#")
    if len(cleaned) not in {3, 6}:
        return None
    try:
        int(cleaned, 16)
    except ValueError:
        return None
    return cleaned.upper()


def build_stops_geojson(feed: FeedConfig, data: GtfsData) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for row in data.get("stops.txt"):
        lat = _as_float(row.get("stop_lat", ""))
        lon = _as_float(row.get("stop_lon", ""))
        if lat is None or lon is None:
            continue
        source_id = row.get("stop_id", "")
        feature = {
            "type": "Feature",
            "id": normalized_id(feed.id, source_id),
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": normalized_id(feed.id, source_id),
                "feed_id": feed.id,
                "feed_slug": feed.slug,
                "municipality": feed.municipality,
                "service_name": feed.service_name,
                "license": feed.license,
                "source_stop_id": source_id,
                "stop_code": row.get("stop_code") or None,
                "stop_name": row.get("stop_name") or source_id,
                "stop_desc": row.get("stop_desc") or None,
                "zone_id": row.get("zone_id") or None,
                "location_type": _as_int(row.get("location_type", "0"), 0),
                "parent_station": (
                    normalized_id(feed.id, row["parent_station"])
                    if row.get("parent_station")
                    else None
                ),
                "wheelchair_boarding": row.get("wheelchair_boarding") or None,
            },
        }
        features.append(feature)
    return {
        "type": "FeatureCollection",
        "name": f"{feed.slug}_stops",
        "features": features,
    }


def _stop_times_by_trip(data: GtfsData) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in data.get("stop_times.txt"):
        result[row.get("trip_id", "")].append(row)
    for rows in result.values():
        rows.sort(key=lambda row: _as_int(row.get("stop_sequence", ""), 0))
    return result


def _deduplicate_adjacent(coords: Iterable[list[float]]) -> list[list[float]]:
    result: list[list[float]] = []
    for coord in coords:
        if not result or result[-1] != coord:
            result.append(coord)
    return result


def build_routes_geojson(feed: FeedConfig, data: GtfsData) -> dict[str, Any]:
    routes = {row.get("route_id", ""): row for row in data.get("routes.txt")}
    trips = data.get("trips.txt")
    stops = {row.get("stop_id", ""): row for row in data.get("stops.txt")}
    stop_times_by_trip = _stop_times_by_trip(data)

    shape_points: dict[str, list[tuple[int, list[float]]]] = defaultdict(list)
    for row in data.get("shapes.txt"):
        lat = _as_float(row.get("shape_pt_lat", ""))
        lon = _as_float(row.get("shape_pt_lon", ""))
        if lat is None or lon is None:
            continue
        shape_points[row.get("shape_id", "")].append(
            (_as_int(row.get("shape_pt_sequence", ""), 0), [lon, lat])
        )
    shapes: dict[str, list[list[float]]] = {
        shape_id: _deduplicate_adjacent(coord for _, coord in sorted(points))
        for shape_id, points in shape_points.items()
    }

    trips_by_route: dict[str, list[dict[str, str]]] = defaultdict(list)
    for trip in trips:
        trips_by_route[trip.get("route_id", "")].append(trip)

    features: list[dict[str, Any]] = []
    for route_id, route in routes.items():
        route_trips = trips_by_route.get(route_id, [])
        used_shapes = sorted({trip.get("shape_id", "") for trip in route_trips if trip.get("shape_id")})
        shape_to_directions: dict[str, set[str]] = defaultdict(set)
        for trip in route_trips:
            if trip.get("shape_id"):
                shape_to_directions[trip["shape_id"]].add(trip.get("direction_id", ""))

        route_features = 0
        for shape_id in used_shapes:
            coordinates = shapes.get(shape_id, [])
            if len(coordinates) < 2:
                continue
            route_features += 1
            features.append(
                _route_feature(
                    feed,
                    route,
                    route_id=route_id,
                    geometry_id=shape_id,
                    coordinates=coordinates,
                    directions=sorted(value for value in shape_to_directions[shape_id] if value),
                    geometry_source="shapes.txt",
                )
            )

        if route_features:
            continue

        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for trip in route_trips:
            grouped[trip.get("direction_id", "")].append(trip)
        if not grouped:
            grouped[""] = []

        for direction_id, candidates in sorted(grouped.items()):
            representative = max(
                candidates,
                key=lambda trip: len(stop_times_by_trip.get(trip.get("trip_id", ""), [])),
                default=None,
            )
            if representative is None:
                continue
            coordinates: list[list[float]] = []
            for stop_time in stop_times_by_trip.get(representative.get("trip_id", ""), []):
                stop = stops.get(stop_time.get("stop_id", ""))
                if not stop:
                    continue
                lat = _as_float(stop.get("stop_lat", ""))
                lon = _as_float(stop.get("stop_lon", ""))
                if lat is not None and lon is not None:
                    coordinates.append([lon, lat])
            coordinates = _deduplicate_adjacent(coordinates)
            if len(coordinates) < 2:
                continue
            geometry_id = f"fallback-{direction_id or 'unknown'}"
            features.append(
                _route_feature(
                    feed,
                    route,
                    route_id=route_id,
                    geometry_id=geometry_id,
                    coordinates=coordinates,
                    directions=[direction_id] if direction_id else [],
                    geometry_source="stop_times.txt fallback",
                )
            )

    return {
        "type": "FeatureCollection",
        "name": f"{feed.slug}_routes",
        "features": features,
    }


def _route_feature(
    feed: FeedConfig,
    route: dict[str, str],
    *,
    route_id: str,
    geometry_id: str,
    coordinates: list[list[float]],
    directions: list[str],
    geometry_source: str,
) -> dict[str, Any]:
    feature_id = normalized_id(feed.id, f"{route_id}:{geometry_id}")
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "properties": {
            "id": feature_id,
            "feed_id": feed.id,
            "feed_slug": feed.slug,
            "municipality": feed.municipality,
            "service_name": feed.service_name,
            "license": feed.license,
            "source_route_id": route_id,
            "route_short_name": route.get("route_short_name") or None,
            "route_long_name": route.get("route_long_name") or None,
            "route_desc": route.get("route_desc") or None,
            "route_type": _as_int(route.get("route_type", "3"), 3),
            "route_url": route.get("route_url") or None,
            "route_color": _valid_hex(route.get("route_color", "")),
            "route_text_color": _valid_hex(route.get("route_text_color", "")),
            "directions": directions,
            "geometry_source": geometry_source,
        },
    }


def write_geojson(path: str | Path, collection: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def merge_feature_collections(
    collections: Iterable[dict[str, Any]], *, name: str
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for collection in collections:
        features.extend(collection.get("features", []))
    return {"type": "FeatureCollection", "name": name, "features": features}
