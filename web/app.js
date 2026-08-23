"use strict";

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

async function requestNearby(lat, lon) {
  const radius = document.getElementById("radius-select").value;
  const response = await loadJson(`/api/stops/nearby?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}&radius=${encodeURIComponent(radius)}&limit=100`, { features: [] });
  const features = (response.features || []).filter((feature) => !state.selectedFeed || feature.properties?.feed_id === state.selectedFeed);
  renderNearby(features);
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
    loadJson("/data/normalized/all/stops.geojson", { type: "FeatureCollection", features: [] }),
    loadJson("/data/normalized/all/routes.geojson", { type: "FeatureCollection", features: [] }),
    loadJson("/data/normalized/all/catalog.json", { feed_count: 0, feeds: [] }),
  ]);
  populateFeedSelect();
  updateMetrics();
  initMap();
  document.getElementById("locate-button").addEventListener("click", locate);
  document.getElementById("radius-select").addEventListener("change", () => {
    if (state.position) requestNearby(state.position.latitude, state.position.longitude);
  });
}

init();
