import { useEffect, useMemo, useState } from "react";
import {
  CircleMarker,
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
import { AQI_BANDS, bandForPm25, colorForPm25, radiusForCity } from "../lib/aqi";
import { UNIT, fmtPopulation } from "../lib/format";

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
    <div className="float pointer-events-auto flex p-1">
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
    <div className="float pointer-events-auto hidden px-3 py-2.5 md:block">
      <div className="eyebrow mb-2">PM2.5 · US EPA AQI</div>
      <div className="flex items-end gap-1">
        {AQI_BANDS.map((b) => (
          <span
            key={b.name}
            className="h-2 w-7 rounded-sm transition-transform hover:scale-y-150"
            style={{ background: b.color }}
            title={`${b.name} · AQI ${b.lower}–${b.upper}`}
          />
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-[9px] text-fg-faint">
        <span>Good</span>
        <span>Hazardous</span>
      </div>
    </div>
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
        (f) => f.latitude != null && f.longitude != null && f.pm2_5_pred != null,
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
    <div className="relative h-full w-full overflow-hidden rounded-2xl">
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

        {showLabels && basemap.labels ? (
          <Pane name="map-labels" style={{ zIndex: 620, pointerEvents: "none" }}>
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

      {/* ── floating controls ── */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-[700] flex items-start justify-between gap-3 p-3">
        <div className="float pointer-events-auto flex items-center gap-2 px-3 py-2">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-accent" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-accent" />
          </span>
          <span className="text-[11px] font-medium text-fg">
            {points.length} cities
          </span>
          {horizon ? (
            <>
              <span className="h-3 w-px bg-line" />
              <span className="font-mono text-[11px] text-fg-subtle">
                +{horizon}h
              </span>
            </>
          ) : null}
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowValues((v) => !v)}
            title="Show PM2.5 values on the map"
            className={clsx(
              "float pointer-events-auto flex items-center gap-1.5 px-2.5 py-2 text-[11px] font-medium transition-colors",
              showValues ? "text-accent" : "text-fg-subtle hover:text-fg",
            )}
          >
            <Tag size={12} />
            <span className="hidden sm:inline">Values</span>
          </button>

          <button
            type="button"
            onClick={onReset}
            title="Reset the view to the whole country"
            className="float pointer-events-auto flex items-center gap-1.5 px-2.5 py-2 text-[11px] font-medium text-fg-subtle transition-colors hover:text-fg"
          >
            <Expand size={12} />
            <span className="hidden sm:inline">Fit</span>
          </button>

          <BasemapSwitcher value={basemapId} onChange={chooseBasemap} />
        </div>
      </div>

      <div className="pointer-events-none absolute bottom-3 right-3 z-[700]">
        <MapLegend />
      </div>

      <AnimatePresence>
        {loading ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="pointer-events-none absolute inset-0 z-[680] flex items-center justify-center bg-canvas/45 backdrop-blur-[3px]"
          >
            <div className="float flex items-center gap-3 px-4 py-2.5">
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
              <span className="text-xs font-medium text-fg">
                Generating forecasts&hellip;
              </span>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {points.length === 0 && !loading ? (
        <div className="pointer-events-none absolute inset-0 z-[670] flex items-center justify-center p-6">
          <div className="float max-w-xs px-4 py-3 text-center">
            <p className="text-xs font-medium text-fg">No predictions yet</p>
            <p className="mt-1 text-[11px] leading-relaxed text-fg-subtle">
              The API returned no forecasts. Check that a model is loaded and
              that upstream data is available.
            </p>
          </div>
        </div>
      ) : null}
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
          className="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold"
          style={{ background: `${band?.color}26`, color: band?.color }}
        >
          AQI {point.aqi_us}
        </span>
      </div>

      <div className="mt-3 flex items-end gap-1.5">
        <span className="metric text-[28px]" style={{ color: band?.color }}>
          {point.pm2_5_pred?.toFixed(1)}
        </span>
        <span className="pb-1 text-[10px] text-fg-faint">{UNIT}</span>
      </div>

      <div
        className="mt-2 rounded-md px-2 py-1 text-center text-[10px] font-semibold"
        style={{ background: `${band?.color}1A`, color: band?.color }}
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
