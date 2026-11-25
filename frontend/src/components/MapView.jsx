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
import { Image, Layers, Maximize2, Tag } from "lucide-react";
import clsx from "clsx";
import "leaflet/dist/leaflet.css";

import { BASEMAPS, DEFAULT_BASEMAP, getBasemap } from "../lib/basemaps";
import { bandForPm25, colorForPm25, radiusForCity } from "../lib/aqi";
import { UNIT, fmtPopulation } from "../lib/format";

/** Pakistan's extent: the initial view and the "reset" target. */
const PK_CENTER = [30.3753, 69.3451];
const PK_BOUNDS = [
  [23.4, 60.6],
  [37.2, 77.9],
];

/* ── map helpers ─────────────────────────────────────────── */

function ZoomWatcher({ onZoom }) {
  useMapEvents({ zoomend: (e) => onZoom(e.target.getZoom()) });
  return null;
}

/**
 * Force Leaflet to re-measure its container.
 *
 * Leaflet caches the container size at init. Our panel animates in and
 * uses a clamp() height, so the map often initialises while the box is
 * still settling and renders into a stale, sometimes zero-height area
 * — the classic grey map.
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

/* ── basemap switcher ────────────────────────────────────── */

const STYLE_ICONS = { satellite: Image, terrain: Layers };

function BasemapSwitcher({ value, onChange }) {
  return (
    <div className="pointer-events-auto absolute right-3 top-3 z-[700]">
      <div className="flex overflow-hidden rounded-lg border border-line bg-surface/90 shadow-panel backdrop-blur-xl">
        {BASEMAPS.map((b) => {
          const Icon = STYLE_ICONS[b.id];
          const active = b.id === value;
          return (
            <button
              key={b.id}
              type="button"
              onClick={() => onChange(b.id)}
              title={`${b.name} basemap`}
              className={clsx(
                "flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium transition-colors",
                active
                  ? "bg-accent/20 text-accent"
                  : "text-fg-subtle hover:bg-raised hover:text-fg",
              )}
            >
              {Icon ? <Icon size={11} /> : null}
              {b.name}
            </button>
          );
        })}
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
  theme = "dark",
}) {
  const [zoom, setZoom] = useState(5);
  const [hovered, setHovered] = useState(null);
  const [showValues, setShowValues] = useState(true);

  // A dark basemap under a light UI (or the reverse) looks broken, so
  // the map follows the theme until the user picks a style themselves
  // — after that their choice wins and the toggle leaves it alone.
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
   * Which cities get a permanent number next to them.
   *
   * Showing all 134 at once is unreadable — Punjab alone would be a
   * wall of overlapping text. Show the largest cities by default and
   * reveal more as the user zooms in, which is how every mapping
   * product handles label density.
   */
  const labelled = useMemo(() => {
    if (!showValues) return new Set();
    const count = zoom <= 5 ? 10 : zoom <= 6 ? 20 : zoom <= 7 ? 45 : points.length;
    return new Set(
      [...points]
        .sort((a, b) => (b.population ?? 0) - (a.population ?? 0))
        .slice(0, count)
        .map((p) => p.city_id),
    );
  }, [points, zoom, showValues]);

  return (
    <div className="relative h-full w-full overflow-hidden">
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
        {/* `key` forces a clean swap when the provider changes;
            mutating a TileLayer's url in place leaves stale tiles. */}
        <TileLayer
          key={`base-${basemap.id}`}
          url={basemap.url}
          attribution={basemap.attribution}
          subdomains={basemap.subdomains ?? "abc"}
          maxZoom={basemap.maxZoom ?? 16}
        />

        {/* Labels ride ABOVE the markers so place names stay readable
            over the dense cluster of cities in Punjab. */}
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
              radius={emphasised ? radius * 1.3 : radius}
              pathOptions={{
                color: isSelected ? "#FFFFFF" : color,
                weight: isSelected ? 2.6 : isHovered ? 2 : 1.2,
                opacity: 1,
                fillColor: color,
                fillOpacity: isSelected ? 0.92 : isHovered ? 0.85 : 0.7,
              }}
              eventHandlers={{
                click: () => onSelectCity(p.city_id),
                mouseover: () => setHovered(p.city_id),
                mouseout: () => setHovered(null),
              }}
            >
              {/* Permanent value chip for the prominent cities. */}
              {labelled.has(p.city_id) && !emphasised ? (
                <Tooltip
                  permanent
                  direction="right"
                  offset={[radius + 3, 0]}
                  className="airwatch-value-label"
                >
                  <span style={{ color }}>{Math.round(p.pm2_5_pred)}</span>
                </Tooltip>
              ) : null}

              {/* Full detail on hover. */}
              <Tooltip direction="top" offset={[0, -6]} opacity={1} sticky>
                <MarkerTooltip point={p} />
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>

      <BasemapSwitcher value={basemapId} onChange={chooseBasemap} />

      {/* value-label toggle */}
      <div className="pointer-events-auto absolute right-3 top-14 z-[700]">
        <button
          type="button"
          onClick={() => setShowValues((v) => !v)}
          title="Show PM2.5 values on the map"
          className={clsx(
            "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium shadow-panel backdrop-blur-xl transition-colors",
            showValues
              ? "border-accent/40 bg-accent/20 text-accent"
              : "border-line bg-surface/90 text-fg-subtle hover:text-fg",
          )}
        >
          <Tag size={11} />
          Values
        </button>
      </div>

      <AnimatePresence>
        {loading ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="pointer-events-none absolute inset-0 z-[650] flex items-center justify-center bg-canvas/50 backdrop-blur-[2px]"
          >
            <div className="flex items-center gap-3 rounded-xl border border-line bg-surface/95 px-4 py-2.5 shadow-panel">
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
              <span className="text-xs font-medium text-fg">
                Generating forecasts&hellip;
              </span>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {/* counter + hint */}
      <div className="pointer-events-none absolute bottom-3 right-3 z-[650] flex flex-col items-end gap-1.5">
        <div className="rounded-lg border border-line bg-surface/88 px-2.5 py-1.5 text-xs text-fg-muted backdrop-blur">
          <span className="font-mono font-semibold text-fg">
            {points.length}
          </span>{" "}
          cities &middot; <span className="text-fg-faint">PM2.5 {UNIT}</span>
        </div>
        {points.length === 0 && !loading ? (
          <div className="max-w-[220px] rounded-lg border border-amber-400/25 bg-amber-400/10 px-2.5 py-1.5 text-2xs leading-relaxed text-amber-200/90 backdrop-blur">
            No predictions available. Check that the API has a model loaded.
          </div>
        ) : null}
      </div>

      <button
        type="button"
        onClick={() => {
          onSelectCity(null);
        }}
        className="pointer-events-auto absolute bottom-3 left-[4.5rem] z-[650] hidden items-center gap-1.5 rounded-lg border border-line bg-surface/88 px-2.5 py-1.5 text-xs text-fg-muted backdrop-blur transition-colors hover:text-fg sm:flex"
        title="Clear selection"
      >
        <Maximize2 size={11} />
        Clear
      </button>
    </div>
  );
}

function MarkerTooltip({ point }) {
  const band = bandForPm25(point.pm2_5_pred);
  return (
    <div className="min-w-[196px] px-1 py-0.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[13px] font-semibold text-fg">
          {point.city_name ?? point.city_id}
        </span>
        <span className="text-2xs text-fg-subtle">{point.province}</span>
      </div>

      <div className="mt-1.5 flex items-baseline gap-1.5">
        <span
          className="font-mono text-xl font-bold tabular-nums"
          style={{ color: band?.color }}
        >
          {point.pm2_5_pred?.toFixed(1)}
        </span>
        <span className="text-2xs text-fg-subtle">{UNIT}</span>
        <span className="ml-auto text-2xs font-semibold text-fg-muted">
          AQI {point.aqi_us}
        </span>
      </div>

      <div
        className="mt-1 rounded px-1.5 py-0.5 text-center text-2xs font-semibold"
        style={{ background: `${band?.color}22`, color: band?.color }}
      >
        {band?.name}
      </div>

      <div className="mt-1.5 space-y-0.5 border-t border-line pt-1.5 text-2xs text-fg-subtle">
        <div className="flex justify-between gap-3">
          <span>Forecast</span>
          <span className="font-mono">+{point.horizon}h</span>
        </div>
        <div className="flex justify-between gap-3">
          <span>Population</span>
          <span className="font-mono">{fmtPopulation(point.population)}</span>
        </div>
        <div className="flex justify-between gap-3">
          <span>Source</span>
          <span className="font-medium text-accent">AI forecast</span>
        </div>
      </div>

      <div className="mt-1.5 border-t border-line pt-1 text-center text-2xs text-fg-faint">
        click for full history
      </div>
    </div>
  );
}
