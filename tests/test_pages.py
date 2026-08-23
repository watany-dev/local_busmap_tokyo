from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tokyo_local_bus.server import haversine_m, nearby_stops


ROOT = Path(__file__).resolve().parents[1]


class NearbyAndPagesTest(unittest.TestCase):
    def test_nearby_sorts_by_distance_and_clamps_radius(self) -> None:
        collection = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [139.7386, 35.7521]},
                    "properties": {"stop_name": "テスト王子駅"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [139.7320, 35.7550]},
                    "properties": {"stop_name": "テスト中央公園"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [139.7350, 35.7505]},
                    "properties": {"stop_name": "テスト区役所"},
                },
            ],
        }
        result = nearby_stops(
            collection,
            lat=35.7521,
            lon=139.7386,
            radius_m=100_000,
            limit=50,
        )
        names = [feature["properties"]["stop_name"] for feature in result["features"]]
        distances = [feature["properties"]["distance_m"] for feature in result["features"]]
        self.assertEqual(["テスト王子駅", "テスト区役所", "テスト中央公園"], names)
        self.assertEqual(distances, sorted(distances))
        self.assertEqual(0.0, distances[0])
        self.assertEqual(20_000.0, result["query"]["radius_m"])
        self.assertLess(haversine_m(35.7521, 139.7386, 35.7550, 139.7320), 1000)

        tight = nearby_stops(
            collection,
            lat=35.7521,
            lon=139.7386,
            radius_m=50,
            limit=50,
        )
        self.assertEqual(["テスト王子駅"], [f["properties"]["stop_name"] for f in tight["features"]])

    def test_frontend_is_static_hostable(self) -> None:
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        script = (ROOT / "web/app.js").read_text(encoding="utf-8")
        self.assertIn('href="styles.css"', html)
        self.assertIn('src="app.js"', html)
        self.assertNotIn('href="/styles.css"', html)
        self.assertNotIn('src="/app.js"', html)
        self.assertNotIn("/api/", script)
        self.assertIn("const EARTH_RADIUS_M = 6371008.8;", script)
        self.assertIn("function nearbyStops(", script)
        self.assertIn('loadJson(`${DATA_BASE}/stops.geojson`', script)

    def test_export_pages_and_static_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            out_dir = Path(temp_dir) / "site"
            aggregate = data_dir / "normalized" / "all"
            aggregate.mkdir(parents=True)
            (aggregate / "catalog.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-08-22T00:00:00+00:00",
                        "feed_count": 1,
                        "feeds": [
                            {
                                "id": "TEST",
                                "municipality": "テスト区",
                                "service_name": "テスト循環",
                                "license": "TEST ONLY",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (aggregate / "stops.geojson").write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {"type": "Point", "coordinates": [139.7386, 35.7521]},
                                "properties": {"stop_name": "テスト王子駅", "feed_id": "TEST"},
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (aggregate / "routes.geojson").write_text(
                json.dumps({"type": "FeatureCollection", "features": []}),
                encoding="utf-8",
            )

            export = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/export_pages.py"),
                    "--web-dir",
                    str(ROOT / "web"),
                    "--data-dir",
                    str(data_dir),
                    "--out",
                    str(out_dir),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, export.returncode, export.stdout + export.stderr)
            summary = json.loads(export.stdout)
            self.assertEqual("ok", summary["status"])
            self.assertEqual(1, summary["feed_count"])
            self.assertEqual(1, summary["stop_features"])
            self.assertTrue((out_dir / ".nojekyll").is_file())

            smoke = subprocess.run(
                [sys.executable, str(ROOT / "tools/smoke_static.py"), "--site-dir", str(out_dir)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, smoke.returncode, smoke.stdout + smoke.stderr)
            smoke_summary = json.loads(smoke.stdout)
            self.assertEqual("ok", smoke_summary["status"])
            self.assertEqual(1, smoke_summary["feed_count"])
            self.assertEqual(1, smoke_summary["stop_features"])


if __name__ == "__main__":
    unittest.main()
