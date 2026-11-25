/**
 * US EPA PM2.5 AQI bands.
 *
 * These MUST stay in step with src/serving/aqi.py. The API also serves
 * them from GET /api/legend, which the app prefers when available —
 * this table is the offline fallback so the map still renders if the
 * API is unreachable.
 */
export const AQI_BANDS = [
  { name: "Good", lower: 0, upper: 50, pm: 9.0, color: "#00E400", text: "#052E05" },
  { name: "Moderate", lower: 51, upper: 100, pm: 35.4, color: "#FFD400", text: "#2E2700" },
  { name: "Unhealthy for Sensitive Groups", short: "Sensitive", lower: 101, upper: 150, pm: 55.4, color: "#FF7E00", text: "#2E1700" },
  { name: "Unhealthy", lower: 151, upper: 200, pm: 125.4, color: "#FF3B30", text: "#FFF" },
  { name: "Very Unhealthy", short: "Very Unhealthy", lower: 201, upper: 300, pm: 225.4, color: "#8F3F97", text: "#FFF" },
  { name: "Hazardous", lower: 301, upper: 500, pm: Infinity, color: "#7E0023", text: "#FFF" },
];

const BREAKPOINTS = [
  [0.0, 9.0, 0, 50],
  [9.1, 35.4, 51, 100],
  [35.5, 55.4, 101, 150],
  [55.5, 125.4, 151, 200],
  [125.5, 225.4, 201, 300],
  [225.5, 325.4, 301, 500],
];

/** Convert a PM2.5 concentration (ug/m3) to a US EPA AQI value. */
export function pm25ToAqi(value) {
  if (value == null || Number.isNaN(value) || value < 0) return null;
  const c = Math.trunc(value * 10) / 10;
  for (const [cLow, cHigh, iLow, iHigh] of BREAKPOINTS) {
    if (c >= cLow && c <= cHigh) {
      return Math.round(((iHigh - iLow) / (cHigh - cLow)) * (c - cLow) + iLow);
    }
  }
  return 500;
}

export function bandForPm25(value) {
  const aqi = pm25ToAqi(value);
  if (aqi == null) return null;
  return AQI_BANDS.find((b) => aqi >= b.lower && aqi <= b.upper) ?? AQI_BANDS.at(-1);
}

export function colorForPm25(value) {
  return bandForPm25(value)?.color ?? "#475569";
}

/**
 * Marker radius. Scales with population so the map reads as a country
 * rather than a uniform dot grid, with a floor so small cities stay
 * clickable and a ceiling so Karachi does not swallow the map.
 */
export function radiusForCity(population, zoom = 5) {
  const base = Math.sqrt(Math.max(population ?? 50000, 20000)) / 420;
  const zoomFactor = 1 + (zoom - 5) * 0.28;
  return Math.max(5, Math.min(26, base * 7 * zoomFactor));
}
