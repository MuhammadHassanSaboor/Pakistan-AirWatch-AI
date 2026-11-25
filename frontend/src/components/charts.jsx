import { useMemo } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";

import { AQI_BANDS, colorForPm25 } from "../lib/aqi";
import { UNIT } from "../lib/format";

const Plot = createPlotlyComponent(Plotly);

/* A single theme object, applied to every chart, so the dashboard
   reads as one product rather than three different plotting styles. */
const AXIS = {
  gridcolor: "rgba(148,163,184,0.10)",
  zerolinecolor: "rgba(148,163,184,0.18)",
  linecolor: "rgba(148,163,184,0.18)",
  tickfont: { color: "#94A3B8", size: 10, family: "Inter, sans-serif" },
  title: { font: { color: "#64748B", size: 11, family: "Inter, sans-serif" } },
  automargin: true,
};

const LAYOUT = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { family: "Inter, sans-serif", color: "#CBD5E1", size: 11 },
  margin: { l: 48, r: 16, t: 16, b: 40 },
  hoverlabel: {
    bgcolor: "#0F172A",
    bordercolor: "rgba(148,163,184,0.25)",
    font: { family: "Inter, sans-serif", size: 11, color: "#E2E8F0" },
  },
  legend: {
    orientation: "h",
    y: 1.14,
    x: 0,
    font: { size: 10, color: "#94A3B8" },
    bgcolor: "rgba(0,0,0,0)",
  },
  transition: { duration: 320, easing: "cubic-in-out" },
};

const CONFIG = {
  displayModeBar: "hover",
  displaylogo: false,
  responsive: true,
  modeBarButtonsToRemove: [
    "select2d",
    "lasso2d",
    "autoScale2d",
    "toggleSpikelines",
  ],
};

/** Shaded AQI bands behind a time series, so a value reads as a
 *  severity, not just a number. */
function aqiBandShapes(maxValue) {
  const ceiling = Math.max(maxValue * 1.15, 60);
  return AQI_BANDS.filter((b) => (b.pm ?? 0) > 0).map((b, i) => {
    const y0 = i === 0 ? 0 : AQI_BANDS[i - 1].pm;
    const y1 = Number.isFinite(b.pm) ? b.pm : ceiling;
    return {
      type: "rect",
      xref: "paper",
      x0: 0,
      x1: 1,
      yref: "y",
      y0,
      y1: Math.min(y1, ceiling),
      fillcolor: b.color,
      opacity: 0.07,
      line: { width: 0 },
      layer: "below",
    };
  });
}

/* ── observed history + model forecast ───────────────────── */

export function TrendChart({ observed, providerForecast, modelPredictions, height = 300 }) {
  const traces = useMemo(() => {
    const out = [];

    if (observed?.length) {
      out.push({
        type: "scatter",
        mode: "lines",
        name: "Observed",
        x: observed.map((d) => d.timestamp),
        y: observed.map((d) => d.pm2_5),
        line: { color: "#E2E8F0", width: 1.8, shape: "spline", smoothing: 0.5 },
        fill: "tozeroy",
        fillcolor: "rgba(226,232,240,0.06)",
        hovertemplate: `<b>Observed</b><br>%{x|%d %b %H:%M}<br>%{y:.1f} ${UNIT}<extra></extra>`,
      });
    }

    if (providerForecast?.length) {
      out.push({
        type: "scatter",
        mode: "lines",
        name: "Provider forecast",
        x: providerForecast.map((d) => d.timestamp),
        y: providerForecast.map((d) => d.pm2_5),
        line: { color: "#38BDF8", width: 1.6, dash: "dot" },
        hovertemplate: `<b>Provider</b><br>%{x|%d %b %H:%M}<br>%{y:.1f} ${UNIT}<extra></extra>`,
      });
    }

    if (modelPredictions?.length) {
      const valid = modelPredictions.filter((p) => p.pm2_5_pred != null);
      if (valid.length) {
        out.push({
          type: "scatter",
          mode: "lines+markers",
          name: "Our AI forecast",
          x: valid.map((p) => p.valid_time),
          y: valid.map((p) => p.pm2_5_pred),
          line: { color: "#14B8A6", width: 2.6 },
          marker: {
            size: 9,
            color: valid.map((p) => colorForPm25(p.pm2_5_pred)),
            line: { color: "#14B8A6", width: 2 },
            symbol: "circle",
          },
          hovertemplate:
            `<b>AI forecast +%{customdata}h</b><br>%{x|%d %b %H:%M}<br>` +
            `%{y:.1f} ${UNIT}<extra></extra>`,
          customdata: valid.map((p) => p.horizon),
        });
      }
    }

    return out;
  }, [observed, providerForecast, modelPredictions]);

  const maxY = useMemo(() => {
    const values = [
      ...(observed ?? []).map((d) => d.pm2_5),
      ...(modelPredictions ?? []).map((p) => p.pm2_5_pred),
    ].filter((v) => v != null);
    return values.length ? Math.max(...values) : 100;
  }, [observed, modelPredictions]);

  if (!traces.length) return null;

  return (
    <Plot
      data={traces}
      layout={{
        ...LAYOUT,
        height,
        shapes: aqiBandShapes(maxY),
        xaxis: { ...AXIS, type: "date" },
        yaxis: { ...AXIS, title: { ...AXIS.title, text: `PM2.5 (${UNIT})` }, rangemode: "tozero" },
        hovermode: "x unified",
      }}
      config={CONFIG}
      style={{ width: "100%" }}
      useResizeHandler
    />
  );
}

/* ── average by province ─────────────────────────────────── */

export function ProvinceChart({ features, height = 260 }) {
  const { labels, values, colors } = useMemo(() => {
    const groups = new Map();
    for (const f of features ?? []) {
      if (f.pm2_5_pred == null || !f.province) continue;
      if (!groups.has(f.province)) groups.set(f.province, []);
      groups.get(f.province).push(f.pm2_5_pred);
    }
    const rows = [...groups.entries()]
      .map(([province, vals]) => ({
        province,
        mean: vals.reduce((a, b) => a + b, 0) / vals.length,
      }))
      .sort((a, b) => a.mean - b.mean);

    return {
      labels: rows.map((r) => r.province),
      values: rows.map((r) => r.mean),
      colors: rows.map((r) => colorForPm25(r.mean)),
    };
  }, [features]);

  if (!labels.length) return null;

  return (
    <Plot
      data={[
        {
          type: "bar",
          orientation: "h",
          x: values,
          y: labels,
          marker: {
            color: colors,
            opacity: 0.85,
            line: { color: "rgba(255,255,255,0.12)", width: 1 },
          },
          hovertemplate: `<b>%{y}</b><br>%{x:.1f} ${UNIT} average<extra></extra>`,
        },
      ]}
      layout={{
        ...LAYOUT,
        height,
        margin: { l: 130, r: 20, t: 10, b: 36 },
        xaxis: { ...AXIS, title: { ...AXIS.title, text: `Mean PM2.5 (${UNIT})` } },
        yaxis: { ...AXIS, automargin: true },
        bargap: 0.32,
      }}
      config={CONFIG}
      style={{ width: "100%" }}
      useResizeHandler
    />
  );
}

/* ── most polluted cities ────────────────────────────────── */

export function TopCitiesChart({ features, topN = 12, height = 300, onSelect }) {
  const rows = useMemo(
    () =>
      (features ?? [])
        .filter((f) => f.pm2_5_pred != null)
        .sort((a, b) => b.pm2_5_pred - a.pm2_5_pred)
        .slice(0, topN)
        .reverse(),
    [features, topN],
  );

  if (!rows.length) return null;

  return (
    <Plot
      data={[
        {
          type: "bar",
          orientation: "h",
          x: rows.map((r) => r.pm2_5_pred),
          y: rows.map((r) => r.city_name ?? r.city_id),
          marker: {
            color: rows.map((r) => colorForPm25(r.pm2_5_pred)),
            opacity: 0.9,
            line: { color: "rgba(255,255,255,0.12)", width: 1 },
          },
          customdata: rows.map((r) => [r.province, r.aqi_us, r.city_id]),
          hovertemplate:
            `<b>%{y}</b> &middot; %{customdata[0]}<br>` +
            `%{x:.1f} ${UNIT}<br>AQI %{customdata[1]}<extra></extra>`,
        },
      ]}
      layout={{
        ...LAYOUT,
        height,
        margin: { l: 118, r: 20, t: 10, b: 36 },
        xaxis: { ...AXIS, title: { ...AXIS.title, text: `Forecast PM2.5 (${UNIT})` } },
        yaxis: { ...AXIS, automargin: true },
        bargap: 0.28,
      }}
      config={CONFIG}
      style={{ width: "100%" }}
      useResizeHandler
      onClick={(e) => {
        const id = e?.points?.[0]?.customdata?.[2];
        if (id && onSelect) onSelect(id);
      }}
    />
  );
}

/* ── national distribution ───────────────────────────────── */

export function DistributionChart({ features, height = 220 }) {
  const values = useMemo(
    () => (features ?? []).map((f) => f.pm2_5_pred).filter((v) => v != null),
    [features],
  );

  if (values.length < 5) return null;

  return (
    <Plot
      data={[
        {
          type: "histogram",
          x: values,
          nbinsx: 26,
          marker: {
            color: "#14B8A6",
            opacity: 0.75,
            line: { color: "rgba(255,255,255,0.14)", width: 1 },
          },
          hovertemplate: `%{x} ${UNIT}<br>%{y} cities<extra></extra>`,
        },
      ]}
      layout={{
        ...LAYOUT,
        height,
        margin: { l: 44, r: 16, t: 10, b: 40 },
        xaxis: { ...AXIS, title: { ...AXIS.title, text: `PM2.5 (${UNIT})` } },
        yaxis: { ...AXIS, title: { ...AXIS.title, text: "Cities" } },
        bargap: 0.05,
      }}
      config={CONFIG}
      style={{ width: "100%" }}
      useResizeHandler
    />
  );
}
