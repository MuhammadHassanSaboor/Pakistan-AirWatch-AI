import { motion } from "framer-motion";
import { ArrowDown, ArrowUp, Gauge, MapPin } from "lucide-react";
import clsx from "clsx";

import { AnimatedNumber, Skeleton, fadeUp, stagger } from "./primitives";
import { UNIT, fmtInt } from "../lib/format";
import { AQI_BANDS, bandForPm25 } from "../lib/aqi";

/**
 * KPI cards.
 *
 * Previous version packed a label, a value, a unit, a category and a
 * stacked bar into a small box at 10–11px, so nothing read as more
 * important than anything else. This one establishes a clear
 * hierarchy: one dominant number per card, a plain label above it,
 * and one supporting line below. The coloured rail on the left is the
 * only decoration, and it carries meaning (the AQI band).
 */

function Tile({ accent, children, className }) {
  return (
    <motion.div
      variants={fadeUp}
      className={clsx(
        "panel relative flex flex-col overflow-hidden p-5 pl-6",
        className,
      )}
    >
      {accent ? (
        <span
          aria-hidden
          className="absolute inset-y-0 left-0 w-1"
          style={{ background: accent }}
        />
      ) : null}
      {children}
    </motion.div>
  );
}

function Label({ icon: Icon, children }) {
  return (
    <div className="flex items-center gap-2 text-2xs font-semibold uppercase tracking-[0.1em] text-fg-subtle">
      {Icon ? <Icon size={13} className="shrink-0" /> : null}
      <span className="truncate">{children}</span>
    </div>
  );
}

export default function StatTiles({ stats, loading }) {
  if (loading && !stats) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="panel p-5">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="mt-4 h-10 w-32" />
            <Skeleton className="mt-3 h-3 w-36" />
          </div>
        ))}
      </div>
    );
  }

  if (!stats) return null;

  const national = bandForPm25(stats.national_mean_pm25);
  const worst = bandForPm25(stats.worst?.pm2_5);
  const best = bandForPm25(stats.best?.pm2_5);

  return (
    <motion.div
      variants={stagger}
      initial="hidden"
      animate="show"
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
    >
      {/* national average */}
      <Tile accent={national?.color}>
        <Label icon={Gauge}>National average</Label>
        <div className="mt-3 flex items-baseline gap-2">
          <AnimatedNumber
            value={stats.national_mean_pm25}
            digits={1}
            className="card-value text-fg"
          />
          <span className="text-xs font-medium text-fg-subtle">{UNIT}</span>
        </div>
        <div className="mt-3 flex items-center gap-2">
          <span
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ background: national?.color }}
          />
          <span className="truncate text-xs font-medium text-fg-muted">
            {national?.name ?? "Unknown"}
          </span>
          <span className="ml-auto shrink-0 text-2xs text-fg-faint">
            median {stats.national_median_pm25}
          </span>
        </div>
      </Tile>

      {/* most polluted */}
      <Tile accent={worst?.color}>
        <Label icon={ArrowUp}>Most polluted</Label>
        <div className="mt-3 truncate text-2xl font-bold tracking-tight text-fg">
          {stats.worst?.city_name ?? "—"}
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span
            className="font-mono text-xl font-semibold tnum"
            style={{ color: worst?.color }}
          >
            {stats.worst?.pm2_5?.toFixed(1) ?? "—"}
          </span>
          <span className="text-xs text-fg-subtle">{UNIT}</span>
          <span className="ml-auto rounded-md bg-raised px-2 py-0.5 text-2xs font-semibold text-fg-muted">
            AQI {stats.worst?.aqi_us ?? "—"}
          </span>
        </div>
      </Tile>

      {/* cleanest */}
      <Tile accent={best?.color}>
        <Label icon={ArrowDown}>Cleanest</Label>
        <div className="mt-3 truncate text-2xl font-bold tracking-tight text-fg">
          {stats.best?.city_name ?? "—"}
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span
            className="font-mono text-xl font-semibold tnum"
            style={{ color: best?.color }}
          >
            {stats.best?.pm2_5?.toFixed(1) ?? "—"}
          </span>
          <span className="text-xs text-fg-subtle">{UNIT}</span>
          <span className="ml-auto rounded-md bg-raised px-2 py-0.5 text-2xs font-semibold text-fg-muted">
            AQI {stats.best?.aqi_us ?? "—"}
          </span>
        </div>
      </Tile>

      {/* coverage + distribution */}
      <Tile>
        <Label icon={MapPin}>Cities reporting</Label>
        <div className="mt-3 flex items-baseline gap-2">
          <AnimatedNumber
            value={stats.cities_reporting}
            digits={0}
            className="card-value text-fg"
          />
          <span className="text-xs font-medium text-fg-subtle">of 134</span>
        </div>
        <CategoryBar
          counts={stats.category_counts}
          total={stats.cities_reporting}
        />
      </Tile>
    </motion.div>
  );
}

/**
 * Distribution of cities across AQI bands.
 *
 * Previously an unlabelled stripe. Now every visible segment is
 * readable on hover and the two largest bands are named underneath,
 * so the bar states something instead of merely decorating.
 */
function CategoryBar({ counts, total }) {
  if (!counts || !total) return null;

  const present = AQI_BANDS.map((band) => ({
    band,
    n: counts[band.name] ?? 0,
  })).filter((d) => d.n > 0);

  const top = [...present].sort((a, b) => b.n - a.n).slice(0, 2);

  return (
    <div className="mt-3">
      <div className="flex h-2 w-full gap-0.5 overflow-hidden rounded-full bg-sunken">
        {present.map(({ band, n }) => (
          <motion.div
            key={band.name}
            initial={{ width: 0 }}
            animate={{ width: `${(n / total) * 100}%` }}
            transition={{ duration: 0.65, ease: [0.22, 1, 0.36, 1] }}
            style={{ background: band.color }}
            title={`${band.name}: ${n} ${n === 1 ? "city" : "cities"}`}
          />
        ))}
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1">
        {top.map(({ band, n }) => (
          <span
            key={band.name}
            className="inline-flex items-center gap-1.5 text-2xs text-fg-muted"
          >
            <span
              className="h-2 w-2 rounded-sm"
              style={{ background: band.color }}
            />
            {band.short ?? band.name}
            <span className="font-mono font-semibold text-fg">{n}</span>
          </span>
        ))}
        <span className="ml-auto text-2xs text-fg-faint">
          {fmtInt(total)} across 7 provinces
        </span>
      </div>
    </div>
  );
}
