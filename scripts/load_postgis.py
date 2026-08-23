#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

try:
    import psycopg
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "psycopg is required. Run: python -m pip install -r requirements-postgis.txt"
    ) from exc


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="正規化GeoJSONをPostGISへ投入")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--config", default="config/feeds.json")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("--database-url or DATABASE_URL is required")

    data_dir = Path(args.data_dir)
    config = load_json(Path(args.config))
    catalog = load_json(data_dir / "normalized/all/catalog.json")
    catalog_by_id = {feed["id"]: feed for feed in catalog.get("feeds", [])}
    configured = {feed["id"]: feed for feed in config["feeds"]}
    stops = load_json(data_dir / "normalized/all/stops.geojson").get("features", [])
    routes = load_json(data_dir / "normalized/all/routes.geojson").get("features", [])

    with psycopg.connect(args.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(Path("sql/schema.sql").read_text(encoding="utf-8"))
            for feed_id, feed in configured.items():
                observed = catalog_by_id.get(feed_id, {})
                cursor.execute(
                    """
                    INSERT INTO feed_sources (
                      feed_id, feed_slug, municipality, service_name, license, source_url,
                      feed_start_date, feed_end_date, feed_version, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (feed_id) DO UPDATE SET
                      feed_slug = excluded.feed_slug,
                      municipality = excluded.municipality,
                      service_name = excluded.service_name,
                      license = excluded.license,
                      source_url = excluded.source_url,
                      feed_start_date = excluded.feed_start_date,
                      feed_end_date = excluded.feed_end_date,
                      feed_version = excluded.feed_version,
                      updated_at = now()
                    """,
                    (
                        feed_id,
                        feed["slug"],
                        feed["municipality"],
                        feed["service_name"],
                        feed["license"],
                        feed["url"],
                        observed.get("feed_start_date"),
                        observed.get("feed_end_date"),
                        observed.get("feed_version"),
                    ),
                )

            cursor.execute("TRUNCATE gtfs_route_geometries, gtfs_stops")
            for feature in stops:
                properties = feature.get("properties") or {}
                lon, lat = feature["geometry"]["coordinates"]
                cursor.execute(
                    """
                    INSERT INTO gtfs_stops (
                      id, feed_id, source_stop_id, stop_name, properties, geom
                    ) VALUES (%s, %s, %s, %s, %s::jsonb,
                              ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                    """,
                    (
                        properties["id"],
                        properties["feed_id"],
                        properties["source_stop_id"],
                        properties["stop_name"],
                        json.dumps(properties, ensure_ascii=False),
                        lon,
                        lat,
                    ),
                )
            for feature in routes:
                properties = feature.get("properties") or {}
                cursor.execute(
                    """
                    INSERT INTO gtfs_route_geometries (
                      id, feed_id, source_route_id, properties, geom
                    ) VALUES (%s, %s, %s, %s::jsonb,
                              ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                    """,
                    (
                        properties["id"],
                        properties["feed_id"],
                        properties["source_route_id"],
                        json.dumps(properties, ensure_ascii=False),
                        json.dumps(feature["geometry"], ensure_ascii=False),
                    ),
                )
        connection.commit()
    print(f"loaded: {len(stops)} stops, {len(routes)} route geometries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
