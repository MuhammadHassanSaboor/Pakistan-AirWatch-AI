import { useEffect, useMemo, useState } from "react";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Pane,
  ScaleControl,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { AnimatePresence, motion } from "framer-motion";
import {
  Expand,
  Image,
  Layers,
  Map as MapIcon,
  Mountain,
  Tag,
} from "lucide-react";
import clsx from "clsx";
import "leaflet/dist/leaflet.css";

import { BASEMAPS, DEFAULT_BASEMAP, getBasemap } from "../lib/basemaps";
import {
  AQI_BANDS,
  bandForPm25,
  colorForPm25,
  radiusForCity,
  textOn,
} from "../lib/aqi";
import { UNIT, fmtPopulation } from "../lib/format";
import kashmir from "../data/kashmir.json";

const PK_CENTER = [30.3753, 69.3451];
const PK_BOUNDS = [
  [23.4, 60.6],
  [37.2, 77.9],
];

const STYLE_ICONS = {
  dark: MapIcon,
  streets: Layers,
  satellite: Image,
  terrain: Mountain,
};

/* ── map helpers ─────────────────────────────────────────── */

function ZoomWatcher({ onZoom }) {
  useMapEvents({ zoomend: (e) => onZoom(e.target.getZoom()) });
  return null;
}

/**
 * Force Leaflet to re-measure its container.
 *
 * Leaflet caches the container size at init. The panel animates in and
 * uses a viewport-relative height, so the map often initialises while
 * the box is still settling and renders into a stale, sometimes
 * zero-height area — the classic grey map.
 */
function SizeFixer() {
  const map = useMap();

  useEffect(() => {
    const fix = () => map.invalidateSize({ animate: false });
    const raf = requestAnimationFrame(fix);
    const timers = [60, 250, 600].map((ms) => setTimeout(fix, ms));

    const observer =
      typeof ResizeObserver !== "undefined" ? new ResizeObserver(fix) : null;
    observer?.observe(map.getContainer());
    window.addEventListener("resize", fix);

    return () => {
      cancelAnimationFrame(raf);
      timers.forEach(clearTimeout);
      observer?.disconnect();
      window.removeEventListener("resize", fix);
    };
  }, [map]);

  return null;
}

function FlyToCity({ city }) {
  const map = useMap();
  useEffect(() => {
    if (!city) return;
    map.flyTo([city.latitude, city.longitude], Math.max(map.getZoom(), 8), {
      duration: 0.9,
    });
  }, [city, map]);
  return null;
}

function FitPakistan({ trigger }) {
  const map = useMap();
  useEffect(() => {
    if (trigger) map.flyToBounds(PK_BOUNDS, { duration: 0.8 });
  }, [trigger, map]);
  return null;
}

/* ── overlays ────────────────────────────────────────────── */

function BasemapSwitcher({ value, onChange }) {
  return (
    <div className="flex rounded-lg border border-line bg-sunken p-0.5">
      {BASEMAPS.map((b) => {
        const Icon = STYLE_ICONS[b.id] ?? MapIcon;
        const active = b.id === value;
        return (
          <button
            key={b.id}
            type="button"
            onClick={() => onChange(b.id)}
            title={`${b.name} basemap`}
            className={clsx(
              "relative flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition-colors",
              active ? "text-canvas" : "text-fg-subtle hover:text-fg",
            )}
          >
            {active ? (
              <motion.span
                layoutId="basemap-pill"
                className="absolute inset-0 -z-10 rounded-lg bg-accent"
                transition={{ type: "spring", stiffness: 420, damping: 34 }}
              />
            ) : null}
            <Icon size={12} />
            <span className="hidden sm:inline">{b.name}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Legend pinned to the map, so colour never needs decoding by
 *  scrolling to a panel somewhere else on the page. */
function MapLegend() {
  return (
    <div className="hidden items-center gap-2 lg:flex">
      <span className="text-2xs font-medium text-fg-subtle">Good</span>
      <div className="flex items-center overflow-hidden rounded-md">
        {AQI_BANDS.map((b) => (
          <span
            key={b.name}
            className="h-2.5 w-6 transition-transform hover:scale-y-150"
            style={{ background: b.color }}
            title={`${b.name} · AQI ${b.lower}–${b.upper}`}
          />
        ))}
      </div>
      <span className="text-2xs font-medium text-fg-subtle">Hazardous</span>
    </div>
  );
}

/* ── Kashmir ─────────────────────────────────────────────── */

/**
 * The Kashmir region, drawn the way the Government of Pakistan's
 * official map shows it.
 *
 * Geometry is Natural Earth's 10m disputed-areas dataset (public
 * domain), extracted by scripts/build_kashmir_geojson.py. It is not
 * approximated by hand: a boundary drawn from memory is wrong in a way
 * no reviewer can check, and on this subject that is not a cosmetic
 * defect. Each feature keeps Natural Earth's own administration note,
 * so the tooltip states the status rather than our paraphrase of it.
 *
 * Styling carries the distinction. Pakistan-administered territory
 * (Azad Jammu & Kashmir, Gilgit-Baltistan) is drawn in the accent as
 * part of the country. Indian-occupied Jammu & Kashmir is drawn as
 * disputed: a dashed outline with a hatched fill, the standard
 * cartographic treatment for territory under dispute.
 */
const REGION_STYLES = {
  pakistan: { stroke: "var(--c-accent)", dash: null, fill: 0.1, weight: 1.6 },
  occupied: { stroke: "var(--c-warn)", dash: "7 5", fill: 0.14, weight: 1.8 },
  disputed: {
    stroke: "var(--c-fg-subtle)",
    dash: "3 4",
    fill: 0.1,
    weight: 1.4,
  },
  china: { stroke: "var(--c-fg-faint)", dash: "2 5", fill: 0.07, weight: 1.2 },
};

function cssColor(variable) {
  if (typeof document === "undefined") return "#888";
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(variable.replace("var(", "").replace(")", ""))
    .trim();
  return raw ? `rgb(${raw})` : "#888";
}

function KashmirLayer({ themeKey }) {
  const style = (feature) => {
    const spec =
      REGION_STYLES[feature.properties.role] ?? REGION_STYLES.disputed;
    const colour = cssColor(spec.stroke);
    return {
      color: colour,
      weight: spec.weight,
      dashArray: spec.dash ?? undefined,
      fillColor: colour,
      fillOpacity: spec.fill,
      interactive: true,
    };
  };

  const onEachFeature = (feature, layer) => {
    const { label, note } = feature.properties;
    layer.bindTooltip(
      `<span class="font-semibold">${label}</span>` +
        (note ? `<br/><span class="opacity-70">${note}</span>` : ""),
      { direction: "top", sticky: true, className: "airwatch-region-label" },
    );
  };

  return (
    <Pane name="kashmir" style={{ zIndex: 450 }}>
      <GeoJSON
        key={`kashmir-${themeKey}`}
        data={kashmir}
        style={style}
        onEachFeature={onEachFeature}
      />
    </Pane>
  );
}

/* ── main ────────────────────────────────────────────────── */

export default function MapView({
  features,
  loading,
  selectedCity,
  onSelectCity,
  showLabels = true,
  resetSignal,
  onReset,
  theme = "dark",
  horizon,
}) {
  const [zoom, setZoom] = useState(5);
  const [hovered, setHovered] = useState(null);
  const [showValues, setShowValues] = useState(true);

  // A dark basemap under a light UI looks broken, so the map follows
  // the theme until the user picks a style — then theirs wins.
  const [basemapId, setBasemapId] = useState(
    theme === "light" ? "streets" : DEFAULT_BASEMAP,
  );
  const [userChoseBasemap, setUserChoseBasemap] = useState(false);

  useEffect(() => {
    if (userChoseBasemap) return;
    setBasemapId(theme === "light" ? "streets" : DEFAULT_BASEMAP);
  }, [theme, userChoseBasemap]);

  const chooseBasemap = (id) => {
    setUserChoseBasemap(true);
    setBasemapId(id);
  };

  const basemap = getBasemap(basemapId);

  const points = useMemo(
    () =>
      (features ?? []).filter(
        (f) =>
          f.latitude != null && f.longitude != null && f.pm2_5_pred != null,
      ),
    [features],
  );

  const selected = useMemo(
    () => points.find((p) => p.city_id === selectedCity) ?? null,
    [points, selectedCity],
  );

  /**
   * Which cities carry a permanent number.
   *
   * All 134 at once is a wall of overlapping text across Punjab. Show
   * the largest first and reveal more on zoom, the way every mapping
   * product manages label density.
   */
  const labelled = useMemo(() => {
    if (!showValues) return new Set();
    const count =
      zoom <= 5 ? 9 : zoom <= 6 ? 18 : zoom <= 7 ? 40 : points.length;
    return new Set(
      [...points]
        .sort((a, b) => (b.population ?? 0) - (a.population ?? 0))
        .slice(0, count)
        .map((p) => p.city_id),
    );
  }, [points, zoom, showValues]);

  return (
    /* The controls used to float ON the map. On a reload they appeared
       as a scatter of panels over a blank grey rectangle before the
       tiles arrived, which read as stray cards rather than map
       furniture -- and the legend and switcher together covered a good
       part of the country. They live in a toolbar above the map now,
       so the map itself is nothing but map. */
    <div className="flex h-full w-full flex-col overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-accent" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-accent" />
          </span>
          <span className="text-xs font-semibold text-fg">
            {points.length} cities
          </span>
          {horizon ? (
            <span className="font-mono text-xs text-fg-subtle">
              +{horizon}h
            </span>
          ) : null}
        </div>

        <div className="mx-1 hidden h-4 w-px bg-line sm:block" />

        <MapLegend />

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowValues((v) => !v)}
            title="Show PM2.5 values on the map"
            className={clsx(
              "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors",
              showValues
                ? "border-accent/35 bg-accent/12 text-accent"
                : "border-line bg-sunken text-fg-subtle hover:text-fg",
            )}
          >
            <Tag size={13} />
            <span className="hidden sm:inline">Values</span>
          </button>

          <button
            type="button"
            onClick={onReset}
            title="Reset the view to the whole country"
            className="flex items-center gap-1.5 rounded-lg border border-line bg-sunken px-2.5 py-1.5 text-xs font-medium text-fg-subtle transition-colors hover:text-fg"
          >
            <Expand size={13} />
            <span className="hidden sm:inline">Fit</span>
          </button>

          <BasemapSwitcher value={basemapId} onChange={chooseBasemap} />
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        <MapContainer
          center={PK_CENTER}
          zoom={5}
          minZoom={4}
          maxZoom={basemap.maxZoom ?? 16}
          scrollWheelZoom
          zoomControl
          className="h-full w-full"
          preferCanvas
        >
          <TileLayer
            key={`base-${basemap.id}`}
            url={basemap.url}
            attribution={basemap.attribution}
            subdomains={basemap.subdomains ?? "abc"}
            maxZoom={basemap.maxZoom ?? 16}
          />

          <KashmirLayer themeKey={theme} />

          {showLabels && basemap.labels ? (
            <Pane
              name="map-labels"
              style={{ zIndex: 620, pointerEvents: "none" }}
            >
              <TileLayer
                key={`labels-${basemap.id}`}
                url={basemap.labels}
                subdomains={basemap.subdomains ?? "abc"}
                maxZoom={basemap.maxZoom ?? 16}
              />
            </Pane>
          ) : null}

          <SizeFixer />
          <ZoomWatcher onZoom={setZoom} />
          <FlyToCity city={selected} />
          <FitPakistan trigger={resetSignal} />
          <ScaleControl position="bottomleft" imperial={false} />

          {points.map((p) => {
            const isSelected = p.city_id === selectedCity;
            const isHovered = p.city_id === hovered;
            const color = colorForPm25(p.pm2_5_pred);
            const radius = radiusForCity(p.population, zoom);
            const emphasised = isSelected || isHovered;

            return (
              <CircleMarker
                key={p.city_id}
                center={[p.latitude, p.longitude]}
                radius={emphasised ? radius * 1.32 : radius}
                pathOptions={{
                  color: isSelected ? "#FFFFFF" : color,
                  weight: isSelected ? 2.6 : isHovered ? 2 : 1.1,
                  opacity: 1,
                  fillColor: color,
                  fillOpacity: isSelected ? 0.95 : isHovered ? 0.88 : 0.72,
                }}
                eventHandlers={{
                  click: () => onSelectCity(p.city_id),
                  mouseover: () => setHovered(p.city_id),
                  mouseout: () => setHovered(null),
                }}
              >
                {labelled.has(p.city_id) && !emphasised ? (
                  <Tooltip
                    permanent
                    direction="right"
                    offset={[radius + 4, 0]}
                    className="airwatch-value-label"
                  >
                    <span style={{ color }}>{Math.round(p.pm2_5_pred)}</span>
                  </Tooltip>
                ) : null}

                <Tooltip direction="top" offset={[0, -8]} opacity={1} sticky>
                  <MarkerTooltip point={p} />
                </Tooltip>
              </CircleMarker>
            );
          })}
        </MapContainer>

        {/* A corner pill, not a full-map blur. Blurring the whole map on
            every horizon change hid the thing being waited for, and on a
            reload it was the first thing on screen. */}
        <AnimatePresence>
          {loading ? (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="pointer-events-none absolute right-3 top-3 z-[700]"
            >
              <div className="float flex items-center gap-2 px-3 py-1.5">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-accent border-t-transparent" />
                <span className="text-xs font-medium text-fg">
                  Forecasting&hellip;
                </span>
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>

        {points.length === 0 && !loading ? (
          <div className="pointer-events-none absolute inset-0 z-[670] flex items-center justify-center p-6">
            <div className="float max-w-xs px-4 py-3 text-center">
              <p className="text-xs font-medium text-fg">No predictions yet</p>
              <p className="mt-1 text-xs leading-relaxed text-fg-subtle">
                The API returned no forecasts. Check that a model is loaded and
                that upstream data is available.
              </p>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function MarkerTooltip({ point }) {
  const band = bandForPm25(point.pm2_5_pred);
  return (
    <div className="min-w-[206px] p-1">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-[13px] font-semibold text-fg">
            {point.city_name ?? point.city_id}
          </div>
          <div className="text-[10px] text-fg-faint">{point.province}</div>
        </div>
        <span
          className="shrink-0 rounded-md px-2 py-0.5 text-[11px] font-bold"
          style={{ background: band?.color, color: textOn(band?.color) }}
        >
          AQI {point.aqi_us}
        </span>
      </div>

      <div className="mt-3 flex items-end gap-1.5">
        <span className="metric text-[28px] text-fg">
          {point.pm2_5_pred?.toFixed(1)}
        </span>
        <span className="pb-1 text-[10px] text-fg-faint">{UNIT}</span>
      </div>

      {/* Filled, with text picked for contrast: a 10% tint behind
          band-coloured text is unreadable at both ends of the scale. */}
      <div
        className="mt-2 rounded-md px-2 py-1 text-center text-[11px] font-bold"
        style={{ background: band?.color, color: textOn(band?.color) }}
      >
        {band?.name}
      </div>

      <div
        className="mt-2.5 space-y-1 border-t pt-2 text-[10px] text-fg-subtle"
        style={{ borderColor: "var(--hairline)" }}
      >
        <Row label="Forecast" value={`+${point.horizon}h`} mono />
        <Row label="Population" value={fmtPopulation(point.population)} mono />
        <Row label="Source" value="AI forecast" accent />
      </div>

      <div className="mt-2 text-center text-[9px] text-fg-faint">
        click for full history
      </div>
    </div>
  );
}

function Row({ label, value, mono, accent }) {
  return (
    <div className="flex justify-between gap-3">
      <span>{label}</span>
      <span
        className={clsx(
          mono && "font-mono",
          accent ? "font-medium text-accent" : "text-fg-muted",
        )}
      >
        {value}
      </span>
    </div>
  );
}
