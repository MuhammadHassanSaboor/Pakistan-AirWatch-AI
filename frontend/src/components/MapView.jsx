import { useEffect, useMemo, useState } from "react";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Marker,
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
import L from "leaflet";
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
import pakistanBoundary from "../data/pakistan-boundary.json";
import mapLabels from "../data/map-labels.json";

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
    /* The active style used to be white-on-accent, which inverted with
       the theme and left black text on a dark toolbar. The selected
       item now stays in the accent colour on a tinted pill, so it reads
       the same way in both themes: bolder, brighter, lifted -- never a
       colour swap that depends on which theme is on. */
    <div className="flex rounded-xl border border-line bg-sunken p-1">
      {BASEMAPS.map((b) => {
        const Icon = STYLE_ICONS[b.id] ?? MapIcon;
        const active = b.id === value;
        return (
          <motion.button
            key={b.id}
            type="button"
            onClick={() => onChange(b.id)}
            title={`${b.name} basemap`}
            whileHover={{ y: -1 }}
            whileTap={{ scale: 0.94 }}
            transition={{ type: "spring", stiffness: 500, damping: 30 }}
            className={clsx(
              "relative flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs transition-colors duration-200",
              active
                ? "font-bold text-accent"
                : "font-medium text-fg-subtle hover:text-fg",
            )}
          >
            {active ? (
              <motion.span
                layoutId="basemap-pill"
                className="absolute inset-0 -z-10 rounded-lg border border-accent/40 bg-accent/15 shadow-glow"
                transition={{ type: "spring", stiffness: 420, damping: 34 }}
              />
            ) : null}
            <motion.span
              animate={
                active ? { rotate: [0, -12, 0], scale: [1, 1.18, 1] } : {}
              }
              transition={{ duration: 0.45, ease: "easeOut" }}
              className="flex"
            >
              <Icon size={13} />
            </motion.span>
            <span className="hidden sm:inline">{b.name}</span>
          </motion.button>
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

/* ── national outline ────────────────────────────────────── */

/**
 * Pakistan, outlined the way the Government of Pakistan's official
 * map shows it.
 *
 * The geometry is Natural Earth's admin-0 polygon dissolved with Azad
 * Jammu & Kashmir and Gilgit-Baltistan (scripts/build_pakistan_
 * boundary.py). Dissolving matters: drawn as three separate polygons,
 * the shared edges become black lines through the middle of the
 * country, which is the one thing a national border must not do.
 *
 * It is drawn as a cased line -- a soft light halo under a black core.
 * A bare black stroke is invisible against a dark basemap or satellite
 * imagery, and casing is how printed maps have always kept a dark
 * boundary legible over dark ground. The border itself stays black in
 * both themes.
 */
function PakistanOutline() {
  return (
    <Pane name="pk-outline" style={{ zIndex: 440, pointerEvents: "none" }}>
      <GeoJSON
        data={pakistanBoundary}
        interactive={false}
        style={{
          color: "#FFFFFF",
          weight: 5,
          opacity: 0.5,
          fill: false,
          lineJoin: "round",
        }}
      />
      <GeoJSON
        data={pakistanBoundary}
        interactive={false}
        style={{
          color: "#000000",
          weight: 2,
          opacity: 0.95,
          fill: false,
          lineJoin: "round",
        }}
      />
    </Pane>
  );
}

/**
 * Place names that are not drawn as territory -- a label only, with no
 * outline and no fill.
 *
 * A divIcon rather than a permanent tooltip on an invisible marker: a
 * divIcon is plain positioned HTML that renders regardless, while a
 * tooltip depends on its host layer staying alive and interactive, and
 * a zero-radius non-interactive CircleMarker is exactly the case where
 * that quietly does nothing.
 */
function MapLabels() {
  const icon = (text) =>
    L.divIcon({
      className: "airwatch-place-label",
      html: `<span>${text}</span>`,
      iconSize: [130, 34],
      iconAnchor: [65, 17],
    });

  return (
    <Pane name="pk-labels" style={{ zIndex: 445, pointerEvents: "none" }}>
      {mapLabels.map((entry) => (
        <Marker
          key={entry.label}
          position={[entry.lat, entry.lon]}
          icon={icon(entry.label)}
          interactive={false}
          keyboard={false}
        />
      ))}
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
  // Separate from `hovered` on purpose: the inspector keeps showing the
  // last city after the pointer leaves, so its numbers can be read
  // instead of disappearing on the way to them.
  const [inspectedId, setInspectedId] = useState(null);
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

  const inspected = useMemo(
    () =>
      points.find((p) => p.city_id === (selectedCity ?? inspectedId)) ?? null,
    [points, selectedCity, inspectedId],
  );

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

          <PakistanOutline />
          <MapLabels />

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
                  mouseover: () => {
                    setHovered(p.city_id);
                    setInspectedId(p.city_id);
                  },
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

      <CityInspector point={inspected} horizon={horizon} />
    </div>
  );
}

/**
 * City detail, below the map rather than floating on it.
 *
 * This replaced per-marker Leaflet tooltips. Those opened on mouseover
 * and closed on mouseout, but when the forecast reloads the markers
 * are rebuilt underneath a stationary cursor: the new marker fires its
 * mouseover and the old one is destroyed before it can fire mouseout,
 * so its tooltip is never closed. Reload the page with the pointer
 * over Punjab and four or five cards are left stranded across the map,
 * each needing a click to dismiss. No amount of z-index fixes that --
 * the lifecycle is the bug.
 *
 * A single strip outside the map cannot strand anything, is always in
 * the same place, and never covers the country. It keeps the last
 * hovered city after the pointer leaves, so the numbers can actually
 * be read instead of vanishing on the way to them.
 */
function CityInspector({ point, horizon }) {
  const band = point ? bandForPm25(point.pm2_5_pred) : null;

  return (
    <div className="flex h-[58px] items-center gap-3 border-t border-line bg-surface px-3">
      <AnimatePresence mode="wait">
        {point ? (
          <motion.div
            key={point.city_id}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.18 }}
            className="flex min-w-0 flex-1 items-center gap-3"
          >
            <span
              className="h-8 w-1 shrink-0 rounded-full"
              style={{ background: band?.color }}
            />

            <div className="min-w-0">
              <div className="truncate text-[13px] font-semibold text-fg">
                {point.city_name ?? point.city_id}
              </div>
              <div className="truncate text-2xs text-fg-subtle">
                {point.province}
              </div>
            </div>

            <div className="ml-1 flex items-baseline gap-1">
              <span className="metric text-xl text-fg">
                {point.pm2_5_pred?.toFixed(1)}
              </span>
              <span className="text-2xs text-fg-faint">{UNIT}</span>
            </div>

            <span
              className="shrink-0 whitespace-nowrap rounded-md px-2 py-0.5 text-2xs font-bold"
              style={{ background: band?.color, color: textOn(band?.color) }}
            >
              {band?.abbr}
            </span>

            <div className="ml-auto hidden items-center gap-4 text-2xs text-fg-subtle sm:flex">
              <span className="font-mono">AQI {point.aqi_us}</span>
              <span className="font-mono">+{horizon}h</span>
              <span className="hidden md:inline">
                {fmtPopulation(point.population)}
              </span>
              <span className="hidden font-medium text-accent lg:inline">
                AI forecast
              </span>
            </div>
          </motion.div>
        ) : (
          <motion.span
            key="idle"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="text-xs text-fg-subtle"
          >
            Hover a city for its forecast, or click to open its history.
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  );
}
