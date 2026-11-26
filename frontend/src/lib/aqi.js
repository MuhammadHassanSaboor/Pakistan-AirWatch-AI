/**
 * US EPA PM2.5 AQI bands.
 *
 * These MUST stay in step with src/serving/aqi.py. The API also serves
 * them from GET /api/legend, which the app prefers when available —
 * this table is the offline fallback so the map still renders if the
 * API is unreachable.
 */
/**
 * The six official categories, in severity order.
 *
 * `name` is the EPA's exact wording and must not be paraphrased — a
 * category that reads "Sensitive" is not a standard anyone can look
 * up. `abbr` is the published short form (USG is the EPA's own) for
 * places too narrow to hold the full name, such as an axis tick.
 *
 * ORDER MATTERS. These are always presented Good → Hazardous. Sorting
 * them by city count produces a sequence like "Unhealthy, Moderate,
 * USG, Very Unhealthy, Good" which looks like a bug to anyone who
 * knows the scale.
 *
 * Colours are the EPA's published swatches, darkened slightly where
 * the official value (notably #00E400 and #FFFF00) fails contrast on
 * a light background.
 */
export const AQI_BANDS = [
  {
    name: "Good",
    abbr: "Good",
    lower: 0,
    upper: 50,
    pm: 9.0,
    color: "#00B050",
    advice: "Air quality is satisfactory and poses little or no risk.",
  },
  {
    name: "Moderate",
    abbr: "Moderate",
    lower: 51,
    upper: 100,
    pm: 35.4,
    color: "#E8B600",
    advice:
      "Unusually sensitive people should consider limiting prolonged outdoor exertion.",
  },
  {
    name: "Unhealthy for Sensitive Groups",
    abbr: "USG",
    lower: 101,
    upper: 150,
    pm: 55.4,
    color: "#FF7E00",
    advice:
      "Children, older adults and people with heart or lung disease should reduce prolonged outdoor exertion.",
  },
  {
    name: "Unhealthy",
    abbr: "Unhealthy",
    lower: 151,
    upper: 200,
    pm: 125.4,
    color: "#F03B36",
    advice: "Everyone may begin to experience health effects.",
  },
  {
    name: "Very Unhealthy",
    abbr: "Very Unhealthy",
    lower: 201,
    upper: 300,
    pm: 225.4,
    color: "#8F3F97",
    advice:
      "Health alert: everyone may experience more serious health effects.",
  },
  {
    name: "Hazardous",
    abbr: "Hazardous",
    lower: 301,
    upper: 500,
    pm: Infinity,
    color: "#7E0023",
    advice: "Health warning of emergency conditions.",
  },
];

/** Highest AQI the scale defines — used to position gauges. */
export const AQI_MAX = 500;

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

/** The band an AQI VALUE falls in. */
export function aqiCategory(aqi) {
  if (aqi == null || Number.isNaN(aqi)) return null;
  return (
    AQI_BANDS.find((b) => aqi >= b.lower && aqi <= b.upper) ?? AQI_BANDS.at(-1)
  );
}

/** The band a PM2.5 CONCENTRATION falls in. */
export function bandForPm25(value) {
  return aqiCategory(pm25ToAqi(value));
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

/**
 * Pick black or white text for a solid band-coloured background.
 *
 * Why this exists: an AQI band colour used as TEXT cannot be made
 * readable in both themes, because the six colours span the whole
 * lightness range. Measured against the two surfaces:
 *
 *            as text on white    as text on dark
 *   Good          2.87:1              6.51:1
 *   Moderate      1.89:1              9.89:1
 *   USG           2.55:1              7.32:1
 *   Unhealthy     3.90:1              4.79:1
 *   Very Unhlth   6.31:1              2.96:1
 *   Hazardous    10.99:1              1.70:1
 *
 * Moderate disappears on white; Hazardous disappears on dark. No
 * single rule fixes both, which is why band labels are drawn as a
 * filled chip instead: the band colour becomes the background and the
 * text is whichever of black or white contrasts with it. That lands
 * every band between 5.07:1 and 10.99:1, in both themes, and the
 * published colour is still exactly what the reader sees.
 */
const INK = "#0A0A0C";
const PAPER = "#FFFFFF";

function channel(value) {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** WCAG relative luminance of a #rrggbb string. */
function luminance(hex) {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) =>
    channel(parseInt(h.slice(i, i + 2), 16)),
  );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Contrast ratio between two #rrggbb colours. */
export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** The more readable of black or white on top of `background`. */
export function textOn(background) {
  if (!background) return PAPER;
  return contrast(PAPER, background) >= contrast(INK, background) ? PAPER : INK;
}
