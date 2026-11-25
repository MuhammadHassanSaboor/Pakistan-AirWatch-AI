/**
 * Basemap providers.
 *
 * All of these are free and need NO API key. Esri's ArcGIS Online
 * basemaps are free for non-commercial use with attribution and give
 * a proper national map: borders, roads, place names and terrain.
 *
 * Why CARTO is not here
 * ---------------------
 * CARTO's free tier is vector-only. Its raster XYZ endpoints — the
 * kind Leaflet consumes — return HTTP 200 with a placeholder tile
 * stamped "API KEY REQUIRED", and they do so WITH a valid key as well
 * as without one. Measured on 2026-11-25 against a valid key:
 *
 *     raster tile, no key    2,513 bytes  (watermark)
 *     raster tile, with key  2,513 bytes  (identical watermark)
 *     vector style.json      67,210 bytes (works)
 *
 * Supporting CARTO would mean replacing Leaflet with MapLibre GL to
 * consume vector styles. Not worth it when the providers below look
 * professional and cost nothing, so the broken options were removed
 * rather than left in the switcher looking broken.
 */

const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";

const ATTR = {
  esri:
    'Tiles &copy; <a href="https://www.esri.com/">Esri</a> &mdash; ' +
    "Esri, HERE, Garmin, FAO, NOAA, USGS",
  esriImagery:
    'Imagery &copy; <a href="https://www.esri.com/">Esri</a>, Maxar, ' +
    "Earthstar Geographics, USDA, USGS, AeroGRID, IGN",
  osm: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
};

/** Providers that never need a key — the defaults. */
const FREE_BASEMAPS = [
  {
    id: "dark",
    name: "Dark",
    theme: "dark",
    url: `${ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    labels: `${ESRI}/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
    attribution: ATTR.esri,
    maxZoom: 16,
  },
  {
    id: "streets",
    name: "Streets",
    theme: "light",
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    labels: null, // OSM tiles already carry their labels
    attribution: ATTR.osm,
    maxZoom: 19,
  },
  {
    id: "satellite",
    name: "Satellite",
    theme: "dark",
    url: `${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`,
    labels: `${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`,
    attribution: ATTR.esriImagery,
    maxZoom: 17,
  },
  {
    id: "terrain",
    name: "Terrain",
    theme: "light",
    url: `${ESRI}/World_Topo_Map/MapServer/tile/{z}/{y}/{x}`,
    labels: null,
    attribution: ATTR.esri,
    maxZoom: 17,
  },
];

export const BASEMAPS = FREE_BASEMAPS;

export const DEFAULT_BASEMAP = BASEMAPS[0].id;

export function getBasemap(id) {
  return BASEMAPS.find((b) => b.id === id) ?? BASEMAPS[0];
}
