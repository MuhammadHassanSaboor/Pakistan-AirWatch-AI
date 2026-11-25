import { useEffect, useMemo, useState } from "react";
import {
  CircleMarker,
  MapContainer,
  Pane,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { AnimatePresence, motion } from "framer-motion";
import "leaflet/dist/leaflet.css";

import { colorForPm25, radiusForCity, bandForPm25 } from "../lib/aqi";
import { UNIT, fmtPopulation } from "../lib/format";

/** Pakistan's extent, used for the initial view and the "reset" control. */
const PK_CENTER = [30.3753, 69.3451];
const PK_BOUNDS = [
  [23.4, 60.6],
  [37.2, 77.9],
];

/** CARTO dark basemap: free, no API key, and designed for data overlays. */
const TILE_URL =
  "https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png";
const LABEL_URL =
  "https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png";
const TILE_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
  '&copy; <a href="https://carto.com/attributions">CARTO</a>';

function ZoomWatcher({ onZoom }) {
  useMapEvents({ zoomend: (e) => onZoom(e.target.getZoom()) });
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

export default function MapView({
  features,
  loading,
  selectedCity,
  onSelectCity,
  showLabels = true,
  resetSignal,
}) {
  const [zoom, setZoom] = useState(5);
  const [hovered, setHovered] = useState(null);

  const points = useMemo(
    () =>
      (features ?? []).filter(
        (f) =>
          f.latitude != null &&
          f.longitude != null &&
          f.pm2_5_pred != null,
      ),
    [features],
  );

  const selected = useMemo(
    () => points.find((p) => p.city_id === selectedCity) ?? null,
    [points, selectedCity],
  );

  return (
    <div className="relative h-full w-full overflow-hidden rounded-2xl">
      <MapContainer
        center={PK_CENTER}
        zoom={5}
        minZoom={4}
        maxZoom={11}
        scrollWheelZoom
        zoomControl
        className="h-full w-full"
        preferCanvas
      >
        <TileLayer url={TILE_URL} attribution={TILE_ATTR} subdomains="abcd" />

        {/* Labels sit ABOVE the markers so city names stay readable
            over dense clusters in Punjab. */}
        {showLabels ? (
          <Pane name="labels" style={{ zIndex: 650, pointerEvents: "none" }}>
            <TileLayer url={LABEL_URL} subdomains="abcd" />
          </Pane>
        ) : null}

        <ZoomWatcher onZoom={setZoom} />
        <FlyToCity city={selected} />
        <FitPakistan trigger={resetSignal} />

        {points.map((p) => {
          const isSelected = p.city_id === selectedCity;
          const isHovered = p.city_id === hovered;
          const color = colorForPm25(p.pm2_5_pred);
          const radius = radiusForCity(p.population, zoom);

          return (
            <CircleMarker
              key={p.city_id}
              center={[p.latitude, p.longitude]}
              radius={isSelected || isHovered ? radius * 1.32 : radius}
              pathOptions={{
                color: isSelected ? "#FFFFFF" : color,
                weight: isSelected ? 2.4 : isHovered ? 1.8 : 1,
                opacity: isSelected ? 1 : 0.85,
                fillColor: color,
                fillOpacity: isSelected ? 0.92 : isHovered ? 0.82 : 0.62,
              }}
              eventHandlers={{
                click: () => onSelectCity(p.city_id),
                mouseover: () => setHovered(p.city_id),
                mouseout: () => setHovered(null),
                keypress: (e) => {
                  if (e.originalEvent.key === "Enter") onSelectCity(p.city_id);
                },
              }}
            >
              <Tooltip direction="top" offset={[0, -6]} opacity={1}>
                <MarkerTooltip point={p} />
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>

      {/* loading veil */}
      <AnimatePresence>
        {loading ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="pointer-events-none absolute inset-0 z-[500] flex items-center justify-center bg-ink-950/55 backdrop-blur-[2px]"
          >
            <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-ink-900/90 px-4 py-2.5 shadow-panel">
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
              <span className="text-xs font-medium text-ink-200">
                Generating forecasts for 134 cities&hellip;
              </span>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {/* city counter */}
      <div className="pointer-events-none absolute bottom-3 left-3 z-[600]">
        <div className="rounded-lg border border-white/10 bg-ink-900/85 px-2.5 py-1.5 text-[11px] text-ink-300 backdrop-blur">
          <span className="font-mono font-semibold text-white">
            {points.length}
          </span>{" "}
          cities shown
        </div>
      </div>
    </div>
  );
}

function MarkerTooltip({ point }) {
  const band = bandForPm25(point.pm2_5_pred);
  return (
    <div className="min-w-[180px] px-1 py-0.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[13px] font-semibold text-white">
          {point.city_name ?? point.city_id}
        </span>
        <span className="text-[10px] text-ink-400">{point.province}</span>
      </div>

      <div className="mt-1.5 flex items-baseline gap-1.5">
        <span
          className="font-mono text-lg font-bold tabular-nums"
          style={{ color: band?.color }}
        >
          {point.pm2_5_pred?.toFixed(1)}
        </span>
        <span className="text-[10px] text-ink-400">{UNIT}</span>
        <span className="ml-auto text-[10px] font-semibold text-ink-300">
          AQI {point.aqi_us}
        </span>
      </div>

      <div
        className="mt-1 rounded px-1.5 py-0.5 text-[10px] font-semibold"
        style={{
          background: `${band?.color}22`,
          color: band?.color,
        }}
      >
        {band?.name}
      </div>

      <div className="mt-1.5 space-y-0.5 border-t border-white/10 pt-1.5 text-[10px] text-ink-400">
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
          <span className="font-medium text-accent-soft">AI forecast</span>
        </div>
      </div>
    </div>
  );
}
