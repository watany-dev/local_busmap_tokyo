"use strict";

// GitHub Pages は静的配信のみ。近傍検索はサーバーAPIもWASMも使わず、
// 読み込み済み GeoJSON に対して Python 実装と同じ Haversine をブラウザで計算する。
const EARTH_RADIUS_M = 6371008.8;
const DATA_BASE = "data/normalized/all";

const state = {
  map: null,
  stops: { type: "FeatureCollection", features: [] },
  routes: { type: "FeatureCollection", features: [] },
  catalog: { feed_count: 0, feeds: [] },
  position: null,
  selectedFeed: "",
};

const mapStyle = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

async function loadJson(url, fallback) {
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return await response.json();
  } catch (error) {
    console.error(`Failed to load ${url}`, error);
    return fallback;
  }
}

function haversineM(lat1, lon1, lat2, lon2) {
  const toRad = (degrees) => (degrees * Math.PI) / 180;
  const phi1 = toRad(lat1);
  const phi2 = toRad(lat2);
  const deltaPhi = toRad(lat2 - lat1);
  const deltaLambda = toRad(lon2 - lon1);
  const a =
    Math.sin(deltaPhi / 2) ** 2 +
    Math.cos(phi1) * Math.cos(phi2) * Math.sin(deltaLambda / 2) ** 2;
  return EARTH_RADIUS_M * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function nearbyStops(collection, lat, lon, radiusM, limit) {
  const clampedRadius = Math.min(Math.max(Number(radiusM) || 800, 10), 20000);
  const clampedLimit = Math.min(Math.max(Number(limit) || 50, 1), 500);
  const matches = [];
  for (const feature of collection.features || []) {
    const coordinates = feature.geometry && feature.geometry.coordinates;
    if (!coordinates || coordinates.length < 2) continue;
    const stopLon = Number(coordinates[0]);
    const stopLat = Number(coordinates[1]);
    if (!Number.isFinite(stopLat) || !Number.isFinite(stopLon)) continue;
    const distance = haversineM(lat, lon, stopLat, stopLon);
    if (distance <= clampedRadius) {
      matches.push({
        type: feature.type,
        geometry: feature.geometry,
        properties: { ...(feature.properties || {}), distance_m: Math.round(distance * 10) / 10 },
      });
    }
  }
  matches.sort((left, right) => left.properties.distance_m - right.properties.distance_m);
  return matches.slice(0, clampedLimit);
}

function initMap() {
  state.map = new maplibregl.Map({
    container: "map",
    style: mapStyle,
    center: [139.6917, 35.6895],
    zoom: 10,
    maxZoom: 19,
  });
  state.map.addControl(new maplibregl.NavigationControl(), "top-right");
  state.map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
  state.map.on("load", () => {
    state.map.addSource("routes", { type: "geojson", data: filteredRoutes() });
    state.map.addLayer({
      id: "routes-line",
      type: "line",
      source: "routes",
      paint: { "line-width": 4, "line-opacity": 0.76, "line-color": "#2874a6" },
    });

    state.map.addSource("stops", { type: "geojson", data: filteredStops() });
    state.map.addLayer({
      id: "stops-circle",
      type: "circle",
      source: "stops",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 3, 16, 7],
        "circle-color": "#ffffff",
        "circle-stroke-width": 2,
        "circle-stroke-color": "#1b4f72",
      },
    });

    state.map.on("click", "stops-circle", (event) => {
      const feature = event.features && event.features[0];
      if (!feature) return;
      const p = feature.properties || {};
      const coordinates = feature.geometry.coordinates.slice();
      new maplibregl.Popup()
        .setLngLat(coordinates)
        .setHTML(`<strong>${escapeHtml(p.stop_name || "停留所")}</strong><br>${escapeHtml(p.municipality || "")} ${escapeHtml(p.service_name || "")}`)
        .addTo(state.map);
    });
    state.map.on("mouseenter", "stops-circle", () => { state.map.getCanvas().style.cursor = "pointer"; });
    state.map.on("mouseleave", "stops-circle", () => { state.map.getCanvas().style.cursor = ""; });
    fitDataBounds();
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);
}

function filteredStops() {
  if (!state.selectedFeed) return state.stops;
  return {
    type: "FeatureCollection",
    features: state.stops.features.filter((feature) => feature.properties?.feed_id === state.selectedFeed),
  };
}

function filteredRoutes() {
  if (!state.selectedFeed) return state.routes;
  return {
    type: "FeatureCollection",
    features: state.routes.features.filter((feature) => feature.properties?.feed_id === state.selectedFeed),
  };
}

function refreshSources() {
  const stopSource = state.map?.getSource("stops");
  const routeSource = state.map?.getSource("routes");
  if (stopSource) stopSource.setData(filteredStops());
  if (routeSource) routeSource.setData(filteredRoutes());
  updateMetrics();
  fitDataBounds();
  if (state.position) requestNearby(state.position.latitude, state.position.longitude);
}

function fitDataBounds() {
  if (!state.map?.loaded()) return;
  const features = [...filteredStops().features, ...filteredRoutes().features];
  const bounds = new maplibregl.LngLatBounds();
  for (const feature of features) addGeometryToBounds(bounds, feature.geometry);
  if (!bounds.isEmpty()) state.map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 600 });
}

function addGeometryToBounds(bounds, geometry) {
  if (!geometry) return;
  if (geometry.type === "Point") bounds.extend(geometry.coordinates);
  if (geometry.type === "LineString") geometry.coordinates.forEach((coord) => bounds.extend(coord));
}

function updateMetrics() {
  document.getElementById("feed-count").textContent = state.catalog.feed_count || state.catalog.feeds.length || 0;
  document.getElementById("stop-count").textContent = filteredStops().features.length;
  document.getElementById("route-count").textContent = filteredRoutes().features.length;
}

function populateFeedSelect() {
  const select = document.getElementById("feed-select");
  for (const feed of state.catalog.feeds || []) {
    const option = document.createElement("option");
    option.value = feed.id;
    option.textContent = `${feed.municipality}｜${feed.service_name}`;
    select.appendChild(option);
  }
  select.addEventListener("change", () => {
    state.selectedFeed = select.value;
    refreshSources();
  });
}

function renderAttribution() {
  const element = document.getElementById("data-attribution");
  if (!element) return;
  const feeds = state.catalog.feeds || [];
  if (!feeds.length) {
    element.textContent = "";
    return;
  }
  element.textContent = `交通データ: ${feeds.map((feed) => {
    const license = feed.license ? `（${feed.license}）` : "";
    return `${feed.municipality} ${feed.service_name}${license}`;
  }).join("、")}。`;
}

function locate() {
  const button = document.getElementById("locate-button");
  const status = document.getElementById("location-status");
  if (!navigator.geolocation) {
    status.textContent = "このブラウザは位置情報に対応していません。";
    return;
  }
  button.disabled = true;
  status.textContent = "現在地を取得しています。";
  navigator.geolocation.getCurrentPosition(
    (position) => {
      button.disabled = false;
      state.position = position.coords;
      const { latitude, longitude, accuracy } = position.coords;
      status.textContent = `現在地を取得しました（精度 約${Math.round(accuracy)} m）。`;
      state.map.flyTo({ center: [longitude, latitude], zoom: 15 });
      showCurrentLocation(longitude, latitude, accuracy);
      requestNearby(latitude, longitude);
    },
    (error) => {
      button.disabled = false;
      status.textContent = `位置情報を取得できませんでした: ${error.message}`;
    },
    { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 },
  );
}

function showCurrentLocation(lon, lat, accuracy) {
  const point = { type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] }, properties: {} };
  const source = state.map.getSource("current-location");
  if (source) {
    source.setData(point);
    return;
  }
  state.map.addSource("current-location", { type: "geojson", data: point });
  state.map.addLayer({
    id: "current-location-dot",
    type: "circle",
    source: "current-location",
    paint: { "circle-radius": 8, "circle-color": "#c0392b", "circle-stroke-width": 3, "circle-stroke-color": "#ffffff" },
  });
  console.info(`Geolocation accuracy: ${accuracy}m`);
}

function requestNearby(lat, lon) {
  const radius = document.getElementById("radius-select").value;
  renderNearby(nearbyStops(filteredStops(), lat, lon, radius, 100));
}

function renderNearby(features) {
  const list = document.getElementById("nearby-list");
  list.replaceChildren();
  if (!features.length) {
    const item = document.createElement("li");
    item.textContent = "指定範囲に収録済み停留所がありません。";
    list.appendChild(item);
    return;
  }
  for (const feature of features.slice(0, 30)) {
    const p = feature.properties || {};
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.className = "stop-name";
    name.textContent = p.stop_name || "停留所";
    const meta = document.createElement("span");
    meta.className = "stop-meta";
    meta.textContent = `${Math.round(p.distance_m || 0)} m｜${p.municipality || ""} ${p.service_name || ""}`;
    item.append(name, meta);
    item.addEventListener("click", () => {
      const [stopLon, stopLat] = feature.geometry.coordinates;
      state.map.flyTo({ center: [stopLon, stopLat], zoom: 17 });
    });
    list.appendChild(item);
  }
}

async function init() {
  [state.stops, state.routes, state.catalog] = await Promise.all([
    loadJson(`${DATA_BASE}/stops.geojson`, { type: "FeatureCollection", features: [] }),
    loadJson(`${DATA_BASE}/routes.geojson`, { type: "FeatureCollection", features: [] }),
    loadJson(`${DATA_BASE}/catalog.json`, { feed_count: 0, feeds: [] }),
  ]);
  populateFeedSelect();
  updateMetrics();
  renderAttribution();
  if (!(state.catalog.feed_count || (state.catalog.feeds || []).length)) {
    document.getElementById("location-status").textContent =
      "公開中の停留所データがまだありません。GitHub Actions の GTFS 更新後に表示されます。";
  }
  initMap();
  document.getElementById("locate-button").addEventListener("click", locate);
  document.getElementById("radius-select").addEventListener("change", () => {
    if (state.position) requestNearby(state.position.latitude, state.position.longitude);
  });
}

init();
