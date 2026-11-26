import { useMemo } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";

import { AQI_BANDS, aqiCategory, colorForPm25, pm25ToAqi } from "../lib/aqi";
import { UNIT } from "../lib/format";

const Plot = createPlotlyComponent(Plotly);

/**
 * Chart theming.
 *
 * Plotly needs concrete colour values, not CSS variables, so the
 * tokens are read back off the document at render time. That keeps a
 * single source of truth in index.css and lets every chart follow the
 * light/dark toggle instead of hard-coding one palette.
 */
function readToken(name, fallback) {
  if (typeof window === "undefined") return fallback;
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  if (!raw) return fallback;
  // Tokens are stored as "r g b" for Tailwind's alpha support.
  return /^[0-9]/.test(raw) ? `rgb(${raw.split(/\s+/).join(",")})` : raw;
}

function useChartTheme(themeKey) {
  return useMemo(() => {
    // `themeKey` both triggers the recompute and supplies the
    // fallbacks used during server-side or pre-paint rendering, when
    // getComputedStyle cannot see the tokens yet.
    const light = themeKey === "light";

    const fg = readToken("--c-fg", light ? "#0E1726" : "#EDF2F9");
    const muted = readToken("--c-fg-muted", light ? "#3E4D63" : "#B0BDCF");
    const subtle = readToken("--c-fg-subtle", light ? "#5F7088" : "#8695AA");
    const faint = readToken("--c-fg-faint", light ? "#8594AA" : "#647287");
    const surface = readToken("--c-surface", light ? "#FFFFFF" : "#111826");
    const line = readToken("--c-line", light ? "#DBE3EE" : "#2A364A");
    const accent = readToken("--c-accent", light ? "#2556D4" : "#6091FF");
    // A translucent accent for range bands under a line. Derived from
    // the token so it tracks the palette instead of being a second,
    // drifting copy of it.
    const accentSoft = accent.startsWith("rgb(")
      ? accent.replace("rgb(", "rgba(").replace(")", ",0.16)")
      : "rgba(96,145,255,0.16)";

    const axis = {
      gridcolor: line,
      zerolinecolor: line,
      linecolor: line,
      tickfont: { color: subtle, size: 11, family: "Inter, sans-serif" },
      title: { font: { color: faint, size: 12, family: "Inter, sans-serif" } },
      automargin: true,
    };

    const layout = {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "Inter, sans-serif", color: muted, size: 12 },
      margin: { l: 56, r: 20, t: 16, b: 48 },
      hoverlabel: {
        bgcolor: surface,
        bordercolor: line,
        font: { family: "Inter, sans-serif", size: 12, color: fg },
      },
      legend: {
        orientation: "h",
        y: 1.16,
        x: 0,
        font: { size: 11, color: subtle },
        bgcolor: "rgba(0,0,0,0)",
      },
      transition: { duration: 300, easing: "cubic-in-out" },
    };

    return {
      axis,
      layout,
      accent,
      accentSoft,
      fg,
      muted,
      subtle,
      faint,
      line,
      surface,
    };
  }, [themeKey]);
}

const CONFIG = {
  displayModeBar: "hover",
  displaylogo: false,
  responsive: true,
  modeBarButtonsToRemove: [
    "select2d",
    "lasso2d",
    "autoScale2d",
    "toggleSpikelines",
    "hoverClosestCartesian",
    "hoverCompareCartesian",
  ],
};

/** Shaded AQI bands behind a time series, so a value reads as a
 *  severity rather than just a number. */
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
      opacity: 0.09,
      line: { width: 0 },
      layer: "below",
    };
  });
}

/* ── observed history + model forecast ───────────────────── */

export function TrendChart({
  observed,
  providerForecast,
  modelPredictions,
  height = 300,
  theme,
}) {
  const t = useChartTheme(theme);

  const traces = useMemo(() => {
    const out = [];

    if (observed?.length) {
      out.push({
        type: "scatter",
        mode: "lines",
        name: "Observed",
        x: observed.map((d) => d.timestamp),
        y: observed.map((d) => d.pm2_5),
        line: { color: t.muted, width: 2, shape: "spline", smoothing: 0.5 },
        fill: "tozeroy",
        fillcolor: "rgba(127,140,160,0.10)",
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
        line: { color: "#3B82F6", width: 1.8, dash: "dot" },
        hovertemplate: `<b>Provider</b><br>%{x|%d %b %H:%M}<br>%{y:.1f} ${UNIT}<extra></extra>`,
      });
    }

    const valid = (modelPredictions ?? []).filter((p) => p.pm2_5_pred != null);
    if (valid.length) {
      out.push({
        type: "scatter",
        mode: "lines+markers",
        name: "Our AI forecast",
        x: valid.map((p) => p.valid_time),
        y: valid.map((p) => p.pm2_5_pred),
        line: { color: t.accent, width: 3 },
        marker: {
          size: 10,
          color: valid.map((p) => colorForPm25(p.pm2_5_pred)),
          line: { color: t.accent, width: 2 },
        },
        customdata: valid.map((p) => p.horizon),
        hovertemplate:
          `<b>AI forecast +%{customdata}h</b><br>%{x|%d %b %H:%M}<br>` +
          `%{y:.1f} ${UNIT}<extra></extra>`,
      });
    }

    return out;
  }, [observed, providerForecast, modelPredictions, t]);

  const maxY = useMemo(() => {
    const vals = [
      ...(observed ?? []).map((d) => d.pm2_5),
      ...(modelPredictions ?? []).map((p) => p.pm2_5_pred),
    ].filter((v) => v != null);
    return vals.length ? Math.max(...vals) : 100;
  }, [observed, modelPredictions]);

  if (!traces.length) return null;

  return (
    <Plot
      data={traces}
      layout={{
        ...t.layout,
        height,
        margin: { l: 56, r: 20, t: 28, b: 44 },
        shapes: aqiBandShapes(maxY),
        xaxis: { ...t.axis, type: "date" },
        yaxis: {
          ...t.axis,
          title: { ...t.axis.title, text: `PM2.5 (${UNIT})` },
          rangemode: "tozero",
        },
        hovermode: "x unified",
      }}
      config={CONFIG}
      style={{ width: "100%" }}
      useResizeHandler
    />
  );
}

/* ── average by province ─────────────────────────────────── */

export function ProvinceChart({ features, height = 280, theme }) {
  const t = useChartTheme(theme);

  const rows = useMemo(() => {
    const groups = new Map();
    for (const f of features ?? []) {
      if (f.pm2_5_pred == null || !f.province) continue;
      if (!groups.has(f.province)) groups.set(f.province, []);
      groups.get(f.province).push(f.pm2_5_pred);
    }
    return [...groups.entries()]
      .map(([province, vals]) => ({
        province,
        mean: vals.reduce((a, b) => a + b, 0) / vals.length,
        n: vals.length,
      }))
      .sort((a, b) => a.mean - b.mean);
  }, [features]);

  if (!rows.length) return null;

  return (
    <Plot
      data={[
        {
          type: "bar",
          orientation: "h",
          x: rows.map((r) => r.mean),
          y: rows.map((r) => r.province),
          marker: {
            color: rows.map((r) => colorForPm25(r.mean)),
            opacity: 0.9,
            line: { color: t.line, width: 1 },
          },
          text: rows.map((r) => r.mean.toFixed(0)),
          textposition: "outside",
          textfont: { color: t.subtle, size: 11 },
          cliponaxis: false,
          customdata: rows.map((r) => r.n),
          hovertemplate:
            `<b>%{y}</b><br>%{x:.1f} ${UNIT} average<br>` +
            `%{customdata} cities<extra></extra>`,
        },
      ]}
      layout={{
        ...t.layout,
        height,
        margin: { l: 140, r: 36, t: 12, b: 44 },
        xaxis: {
          ...t.axis,
          title: { ...t.axis.title, text: `Mean PM2.5 (${UNIT})` },
        },
        yaxis: { ...t.axis, automargin: true },
        bargap: 0.3,
      }}
      config={CONFIG}
      style={{ width: "100%" }}
      useResizeHandler
    />
  );
}

/* ── most polluted cities ────────────────────────────────── */

export function TopCitiesChart({
  features,
  topN = 12,
  height = 340,
  onSelect,
  theme,
}) {
  const t = useChartTheme(theme);

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
            opacity: 0.92,
            line: { color: t.line, width: 1 },
          },
          text: rows.map((r) => r.pm2_5_pred.toFixed(0)),
          textposition: "outside",
          textfont: { color: t.subtle, size: 11 },
          cliponaxis: false,
          customdata: rows.map((r) => [r.province, r.aqi_us, r.city_id]),
          hovertemplate:
            `<b>%{y}</b> &middot; %{customdata[0]}<br>` +
            `%{x:.1f} ${UNIT}<br>AQI %{customdata[1]}<extra></extra>`,
        },
      ]}
      layout={{
        ...t.layout,
        height,
        margin: { l: 124, r: 40, t: 12, b: 44 },
        xaxis: {
          ...t.axis,
          title: { ...t.axis.title, text: `Forecast PM2.5 (${UNIT})` },
        },
        yaxis: { ...t.axis, automargin: true },
        bargap: 0.3,
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

/* ── distribution across cities ──────────────────────────── */

export function DistributionChart({ features, height = 340, theme }) {
  const t = useChartTheme(theme);

  /**
   * Bins are computed here rather than handed to Plotly's `histogram`
   * trace, because `plotly.js-basic` ships only bar, pie and scatter.
   * Asking it for a histogram produced a meaningless jagged line.
   *
   * Binning by AQI breakpoints is also more informative than equal
   * widths: each bar answers "how many cities are Unhealthy?" rather
   * than "how many fall between 73 and 81 µg/m³".
   */
  const bins = useMemo(() => {
    const values = (features ?? [])
      .map((f) => f.pm2_5_pred)
      .filter((v) => v != null && Number.isFinite(v));
    if (values.length < 3) return null;

    const edges = [0, 9, 35.4, 55.4, 125.4, 225.4, Infinity];
    const counts = new Array(AQI_BANDS.length).fill(0);

    for (const v of values) {
      for (let i = 0; i < edges.length - 1; i += 1) {
        if (v >= edges[i] && v < edges[i + 1]) {
          counts[i] += 1;
          break;
        }
      }
    }

    return {
      counts,
      ranges: AQI_BANDS.map((_, i) =>
        Number.isFinite(edges[i + 1])
          ? `${edges[i]}–${edges[i + 1]}`
          : `${edges[i]}+`,
      ),
      names: AQI_BANDS.map((b) => b.abbr ?? b.name),
      colors: AQI_BANDS.map((b) => b.color),
      total: values.length,
    };
  }, [features]);

  if (!bins) return null;

  return (
    <Plot
      data={[
        {
          type: "bar",
          x: bins.names,
          y: bins.counts,
          marker: {
            color: bins.colors,
            opacity: 0.92,
            line: { color: t.line, width: 1 },
          },
          customdata: bins.ranges.map((range, i) => [
            range,
            ((bins.counts[i] / bins.total) * 100).toFixed(0),
          ]),
          hovertemplate:
            `<b>%{x}</b><br>%{y} cities (%{customdata[1]}%)<br>` +
            `%{customdata[0]} ${UNIT}<extra></extra>`,
          text: bins.counts.map((c) => (c > 0 ? String(c) : "")),
          textposition: "outside",
          textfont: { color: t.subtle, size: 11 },
          cliponaxis: false,
        },
      ]}
      layout={{
        ...t.layout,
        height,
        margin: { l: 52, r: 20, t: 24, b: 86 },
        xaxis: {
          ...t.axis,
          tickangle: -28,
          tickfont: { ...t.axis.tickfont, size: 10 },
        },
        yaxis: {
          ...t.axis,
          title: { ...t.axis.title, text: "Number of cities" },
          rangemode: "tozero",
        },
        bargap: 0.3,
      }}
      config={CONFIG}
      style={{ width: "100%" }}
      useResizeHandler
    />
  );
}

/* ── population exposure ─────────────────────────────────── */

/**
 * How many PEOPLE are breathing each category, by province.
 *
 * This replaced a population-versus-PM2.5 scatter. The scatter was
 * honest but close to unreadable: 134 overlapping dots on a log axis,
 * from which the only recoverable finding was "the cloud slopes
 * upwards a bit". It also answered a question nobody asks. The useful
 * question is not whether big cities are dirtier, it is how many
 * people are affected -- and a city of 15 million at Unhealthy matters
 * enormously more than a town of 40,000 at the same level, which a
 * scatter gives exactly equal visual weight.
 *
 * Stacking population by category turns the dataset into the sentence
 * a reader actually wants: "X million people in Punjab wake up to air
 * the EPA calls Unhealthy." Severity order is preserved left to right,
 * and provinces are ordered by total population so the bars form a
 * clean descending shape rather than a ragged one.
 */
export function ExposureChart({ features, height = 330, theme }) {
  const t = useChartTheme(theme);

  const { provinces, series } = useMemo(() => {
    const rows = (features ?? []).filter(
      (f) => f.pm2_5_pred != null && f.province && f.population > 0,
    );

    const totals = new Map();
    for (const r of rows) {
      totals.set(r.province, (totals.get(r.province) ?? 0) + r.population);
    }
    // Ascending, because a horizontal bar chart draws its first
    // category at the bottom.
    const ordered = [...totals.entries()]
      .sort((a, b) => a[1] - b[1])
      .map(([name]) => name);

    const byBand = AQI_BANDS.map((band) => {
      const population = ordered.map((province) =>
        rows
          .filter(
            (r) =>
              r.province === province &&
              aqiCategory(pm25ToAqi(r.pm2_5_pred))?.name === band.name,
          )
          .reduce((sum, r) => sum + r.population, 0),
      );
      const cities = ordered.map(
        (province) =>
          rows.filter(
            (r) =>
              r.province === province &&
              aqiCategory(pm25ToAqi(r.pm2_5_pred))?.name === band.name,
          ).length,
      );
      return { band, population, cities };
    });

    return { provinces: ordered, series: byBand };
  }, [features]);

  if (provinces.length === 0) return null;

  return (
    <Plot
      data={series
        .filter((d) => d.population.some((v) => v > 0))
        .map((d) => ({
          type: "bar",
          orientation: "h",
          name: d.band.abbr,
          y: provinces,
          x: d.population,
          customdata: d.cities,
          marker: {
            color: d.band.color,
            line: { color: t.surface, width: 1 },
          },
          hovertemplate:
            `<b>%{y}</b><br>${d.band.name}<br>` +
            `%{x:,.0f} residents &middot; %{customdata} cities<extra></extra>`,
        }))}
      layout={{
        ...t.layout,
        height,
        barmode: "stack",
        bargap: 0.28,
        margin: { l: 112, r: 18, t: 8, b: 44 },
        showlegend: true,
        legend: {
          ...t.layout.legend,
          orientation: "h",
          y: -0.18,
          x: 0,
          font: { ...t.layout.font, size: 10 },
        },
        xaxis: {
          ...t.axis,
          title: { ...t.axis.title, text: "Residents" },
          tickformat: ".2s",
        },
        yaxis: { ...t.axis, automargin: true },
      }}
      config={CONFIG}
      style={{ width: "100%" }}
      useResizeHandler
    />
  );
}

/* ── altitude profile ────────────────────────────────────── */

/**
 * Mean PM2.5 against altitude, binned.
 *
 * Also a scatter before, and the physical signal was buried in the
 * spread: the Indus plain holds ~90 cities between 100 m and 250 m, so
 * most of the chart was a single vertical stripe of dots. Binning the
 * altitude and plotting the mean shows the actual relationship -- smog
 * trapped under winter inversions on the plain, cleaner ventilated air
 * in the highlands -- as one falling line.
 *
 * The band behind the line is the min-max range within each bin, which
 * keeps the chart honest: it shows that the trend has wide spread and
 * is not a tidy law.
 */
const ALTITUDE_BINS = [
  { label: "0-250 m", lo: 0, hi: 250 },
  { label: "250-500 m", lo: 250, hi: 500 },
  { label: "500-1 km", lo: 500, hi: 1000 },
  { label: "1-2 km", lo: 1000, hi: 2000 },
  { label: "2 km+", lo: 2000, hi: Infinity },
];

export function AltitudeProfile({ features, height = 330, theme }) {
  const t = useChartTheme(theme);

  const bins = useMemo(() => {
    const rows = (features ?? []).filter(
      (f) => f.pm2_5_pred != null && f.elevation_m != null,
    );
    return ALTITUDE_BINS.map((bin) => {
      const inBin = rows.filter(
        (r) => r.elevation_m >= bin.lo && r.elevation_m < bin.hi,
      );
      const values = inBin.map((r) => r.pm2_5_pred);
      const mean = values.length
        ? values.reduce((a, b) => a + b, 0) / values.length
        : null;
      return {
        ...bin,
        n: values.length,
        mean,
        min: values.length ? Math.min(...values) : null,
        max: values.length ? Math.max(...values) : null,
      };
    }).filter((b) => b.n > 0);
  }, [features]);

  if (bins.length < 2) return null;

  const labels = bins.map((b) => b.label);

  return (
    <Plot
      data={[
        // Range band: drawn as an up-then-back-down closed shape.
        {
          type: "scatter",
          mode: "lines",
          x: [...labels, ...[...labels].reverse()],
          y: [
            ...bins.map((b) => b.max),
            ...[...bins].reverse().map((b) => b.min),
          ],
          fill: "toself",
          fillcolor: t.accentSoft,
          line: { width: 0 },
          hoverinfo: "skip",
          showlegend: false,
        },
        {
          type: "scatter",
          mode: "lines+markers",
          x: labels,
          y: bins.map((b) => b.mean),
          line: { color: t.accent, width: 3, shape: "spline", smoothing: 0.8 },
          marker: {
            size: bins.map((b) => Math.max(10, Math.min(30, 7 + b.n * 0.32))),
            color: bins.map((b) => colorForPm25(b.mean)),
            line: { color: t.surface, width: 2 },
          },
          customdata: bins.map((b) => [b.n, b.min, b.max]),
          hovertemplate:
            `<b>%{x}</b><br>mean %{y:.1f} ${UNIT}<br>` +
            `range %{customdata[1]:.1f}-%{customdata[2]:.1f}<br>` +
            `%{customdata[0]} cities<extra></extra>`,
          showlegend: false,
        },
      ]}
      layout={{
        ...t.layout,
        height,
        margin: { l: 56, r: 20, t: 14, b: 48 },
        xaxis: {
          ...t.axis,
          title: { ...t.axis.title, text: "Elevation band" },
          type: "category",
        },
        yaxis: {
          ...t.axis,
          title: { ...t.axis.title, text: `Forecast PM2.5 (${UNIT})` },
          rangemode: "tozero",
        },
      }}
      config={CONFIG}
      style={{ width: "100%" }}
      useResizeHandler
    />
  );
}
