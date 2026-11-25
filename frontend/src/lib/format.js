/** Formatting helpers. Kept in one place so units never drift. */

export const UNIT = "\u00B5g/m\u00B3";

export function fmtNumber(value, digits = 1) {
  if (value == null || Number.isNaN(value)) return "\u2014";
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtInt(value) {
  if (value == null || Number.isNaN(value)) return "\u2014";
  return Math.round(value).toLocaleString("en-US");
}

export function fmtPopulation(value) {
  if (!value) return "\u2014";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}K`;
  return String(value);
}

/** "14:00, 25 Nov" in the viewer's locale. */
export function fmtTime(iso) {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "\u2014";
  return d.toLocaleString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    day: "numeric",
    month: "short",
  });
}

export function fmtHourLabel(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** "3 minutes ago" — used for data-freshness badges. */
export function fmtRelative(iso) {
  if (!iso) return "\u2014";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "\u2014";
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

/**
 * Human label for where a number came from. Showing this on every
 * value is a stated requirement: a model estimate must never be
 * mistaken for a sensor reading.
 */
export const SOURCE_LABELS = {
  model_prediction: { label: "AI forecast", tone: "accent" },
  provider_forecast: { label: "Provider forecast", tone: "blue" },
  ground_station: { label: "Ground sensor", tone: "green" },
  reanalysis: { label: "Reanalysis estimate", tone: "slate" },
};

export function sourceLabel(source) {
  return SOURCE_LABELS[source] ?? { label: source ?? "Unknown", tone: "slate" };
}
