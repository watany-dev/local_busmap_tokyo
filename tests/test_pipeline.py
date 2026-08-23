from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tokyo_local_bus.config import FeedConfig, load_feeds
from tokyo_local_bus.geojson import build_routes_geojson, build_stops_geojson
from tokyo_local_bus.gtfs import validate_gtfs
from tokyo_local_bus.pipeline import aggregate_outputs, ingest_feed
from tokyo_local_bus.server import haversine_m


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests/fixtures/minimal_gtfs"
FIXTURE_ZIP = ROOT / "tests/fixtures/minimal_gtfs.zip"


class PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.feed = FeedConfig(
            id="TEST",
            slug="synthetic-test-feed",
            municipality="テスト区",
            service_name="テスト循環",
            url="https://example.invalid/feed.zip",
            license="TEST ONLY",
            priority="A",
        )

    def test_config_has_21_priority_a_feeds(self) -> None:
        feeds = load_feeds(ROOT / "config/feeds.json")
        self.assertEqual(21, len(feeds))
        self.assertTrue(all(feed.priority == "A" for feed in feeds))
        self.assertEqual(len(feeds), len({feed.id for feed in feeds}))

    def test_validate_and_geojson(self) -> None:
        report, data = validate_gtfs(
            self.feed,
            FIXTURE_DIR,
            service_date=date(2026, 8, 22),
        )
        self.assertTrue(report.is_valid, report.to_dict())
        self.assertEqual("valid", report.status)
        self.assertEqual(1, report.active_trip_count)
        stops = build_stops_geojson(self.feed, data)
        routes = build_routes_geojson(self.feed, data)
        self.assertEqual(3, len(stops["features"]))
        self.assertEqual(1, len(routes["features"]))
        self.assertEqual("shapes.txt", routes["features"][0]["properties"]["geometry_source"])

    def test_shape_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "gtfs"
            shutil.copytree(FIXTURE_DIR, target)
            (target / "shapes.txt").unlink()
            for row in (target / "trips.txt").read_text(encoding="utf-8").splitlines():
                pass
            (target / "trips.txt").write_text(
                "route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\n"
                "R1,DAILY,T1,テスト循環,0,\n",
                encoding="utf-8",
            )
            report, data = validate_gtfs(
                self.feed,
                target,
                service_date=date(2026, 8, 22),
            )
            self.assertTrue(report.is_valid)
            routes = build_routes_geojson(self.feed, data)
            self.assertEqual(1, len(routes["features"]))
            self.assertEqual(
                "stop_times.txt fallback",
                routes["features"][0]["properties"]["geometry_source"],
            )

    def test_local_zip_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            result = ingest_feed(
                self.feed,
                data_dir,
                service_date=date(2026, 8, 22),
                local_zip=FIXTURE_ZIP,
            )
            self.assertEqual("ok", result.status, result.error)
            aggregate_outputs(data_dir, [result])
            stops = json.loads(
                (data_dir / "normalized/all/stops.geojson").read_text(encoding="utf-8")
            )
            catalog = json.loads(
                (data_dir / "normalized/all/catalog.json").read_text(encoding="utf-8")
            )
            self.assertEqual(3, len(stops["features"]))
            self.assertEqual(1, catalog["feed_count"])

    def test_haversine(self) -> None:
        distance = haversine_m(35.7521, 139.7386, 35.7550, 139.7320)
        self.assertGreater(distance, 500)
        self.assertLess(distance, 1000)


if __name__ == "__main__":
    unittest.main()
