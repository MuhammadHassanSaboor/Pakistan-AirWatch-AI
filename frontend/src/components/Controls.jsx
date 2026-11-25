import { motion } from "framer-motion";
import { Clock, Layers, Maximize2, Search, X } from "lucide-react";
import clsx from "clsx";
import { useMemo, useState } from "react";

import { AQI_BANDS } from "../lib/aqi";
import { UNIT } from "../lib/format";

/* ── forecast horizon selector ─────────────────────────────
   A segmented control rather than a free slider: the model is trained
   on exactly these four lead times, so offering +7h would be a lie. */

export function HorizonSelector({ horizons, value, onChange, disabled }) {
  return (
    <div className="flex items-center gap-2">
      <Clock size={13} className="text-fg-faint" />
      <div className="relative flex rounded-lg border border-line bg-raised p-0.5">
        {horizons.map((h) => {
          const active = h === value;
          return (
            <button
              key={h}
              type="button"
              disabled={disabled}
              onClick={() => onChange(h)}
              className={clsx(
                "relative z-10 rounded-md px-3 py-1 text-xs font-semibold transition-colors duration-200",
                active ? "text-canvas" : "text-fg-muted hover:text-fg",
                disabled && "cursor-not-allowed opacity-50",
              )}
            >
              {active ? (
                <motion.span
                  layoutId="horizon-pill"
                  className="absolute inset-0 -z-10 rounded-md bg-accent"
                  transition={{ type: "spring", stiffness: 420, damping: 32 }}
                />
              ) : null}
              +{h}h
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ── province filter + city search ───────────────────────── */

export function CitySearch({ cities, onSelect, selectedCity }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return (cities ?? [])
      .filter(
        (c) =>
          c.city_name.toLowerCase().includes(q) ||
          c.province.toLowerCase().includes(q),
      )
      .slice(0, 8);
  }, [cities, query]);

  return (
    <div className="relative">
      <div className="flex items-center gap-2 rounded-lg border border-line bg-raised px-2.5 py-1.5 focus-within:border-accent/50">
        <Search size={13} className="shrink-0 text-fg-faint" />
        <input
          type="text"
          value={query}
          placeholder="Search city…"
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          className="w-32 bg-transparent text-xs text-fg placeholder:text-fg-faint focus:outline-none sm:w-40"
        />
        {query ? (
          <button
            type="button"
            onClick={() => {
              setQuery("");
              setOpen(false);
            }}
            className="text-fg-faint hover:text-fg"
            aria-label="Clear search"
          >
            <X size={12} />
          </button>
        ) : null}
      </div>

      {open && matches.length > 0 ? (
        <motion.ul
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.16 }}
          className="absolute right-0 z-[1200] mt-1.5 w-60 overflow-hidden rounded-xl border border-line bg-surface/95 shadow-panel backdrop-blur-xl"
        >
          {matches.map((c) => (
            <li key={c.city_id}>
              <button
                type="button"
                onMouseDown={() => {
                  onSelect(c.city_id);
                  setQuery("");
                  setOpen(false);
                }}
                className={clsx(
                  "flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs transition-colors",
                  c.city_id === selectedCity
                    ? "bg-accent/15 text-accent"
                    : "text-fg hover:bg-raised",
                )}
              >
                <span className="font-medium">{c.city_name}</span>
                <span className="text-2xs text-fg-faint">{c.province}</span>
              </button>
            </li>
          ))}
        </motion.ul>
      ) : null}
    </div>
  );
}

/* ── layer / display toggles ──────────────────────────────── */

export function LayerControls({ showLabels, onToggleLabels, onResetView }) {
  return (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        onClick={onToggleLabels}
        className={clsx("btn !px-2.5", showLabels && "btn-accent")}
        title="Toggle place names"
      >
        <Layers size={13} />
        <span className="hidden lg:inline">Labels</span>
      </button>
      <button
        type="button"
        onClick={onResetView}
        className="btn !px-2.5"
        title="Reset the map to the whole country"
      >
        <Maximize2 size={13} />
        <span className="hidden lg:inline">Reset</span>
      </button>
    </div>
  );
}

/* ── AQI legend ───────────────────────────────────────────
   Shows BOTH the AQI band and the µg/m³ range it maps to, and names
   the standard. Mixing the two scales without saying which is which
   is the classic air-quality visualisation error. */

export function Legend({ bands, standard }) {
  const list = bands?.length ? bands : AQI_BANDS;

  return (
    <div className="px-4 py-3">
      <div className="space-y-1.5">
        {list.map((b, i) => {
          const name = b.name;
          const lower = b.pm25_lower ?? (i === 0 ? 0 : null);
          const upper = b.pm25_upper ?? b.pm ?? null;
          return (
            <motion.div
              key={name}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.035, duration: 0.3 }}
              className="flex items-center gap-2.5"
            >
              <span
                className="h-3 w-3 shrink-0 rounded-sm"
                style={{ background: b.color }}
              />
              <span className="flex-1 truncate text-xs text-fg-muted">
                {name}
              </span>
              <span className="shrink-0 font-mono text-2xs tabular-nums text-fg-faint">
                {upper && Number.isFinite(upper)
                  ? `${lower ?? 0}–${upper}`
                  : `${lower ?? 0}+`}
              </span>
            </motion.div>
          );
        })}
      </div>

      <p className="mt-3 border-t border-line pt-2 text-2xs leading-relaxed text-fg-faint">
        Ranges in {UNIT}. Colours follow the{" "}
        <span className="text-fg-subtle">{standard ?? "US EPA"}</span> AQI
        breakpoints for PM2.5.
      </p>
    </div>
  );
}
