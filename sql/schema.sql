CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS feed_sources (
  feed_id text PRIMARY KEY,
  feed_slug text NOT NULL UNIQUE,
  municipality text NOT NULL,
  service_name text NOT NULL,
  license text NOT NULL,
  source_url text NOT NULL,
  feed_start_date date,
  feed_end_date date,
  feed_version text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gtfs_stops (
  id text PRIMARY KEY,
  feed_id text NOT NULL REFERENCES feed_sources(feed_id) ON DELETE CASCADE,
  source_stop_id text NOT NULL,
  stop_name text NOT NULL,
  properties jsonb NOT NULL,
  geom geometry(Point, 4326) NOT NULL,
  UNIQUE (feed_id, source_stop_id)
);
CREATE INDEX IF NOT EXISTS gtfs_stops_geom_gix ON gtfs_stops USING gist (geom);
CREATE INDEX IF NOT EXISTS gtfs_stops_feed_idx ON gtfs_stops (feed_id);

CREATE TABLE IF NOT EXISTS gtfs_route_geometries (
  id text PRIMARY KEY,
  feed_id text NOT NULL REFERENCES feed_sources(feed_id) ON DELETE CASCADE,
  source_route_id text NOT NULL,
  properties jsonb NOT NULL,
  geom geometry(LineString, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS gtfs_route_geometries_geom_gix
  ON gtfs_route_geometries USING gist (geom);
CREATE INDEX IF NOT EXISTS gtfs_route_geometries_feed_idx
  ON gtfs_route_geometries (feed_id);

-- 現在地から半径800m以内の停留所を近い順に返す例
-- SELECT id, stop_name,
--        ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS distance_m
-- FROM gtfs_stops
-- WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 800)
-- ORDER BY distance_m
-- LIMIT 50;
