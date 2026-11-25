import { motion } from "framer-motion";
import { ArrowDownRight, ArrowUpRight, Wind } from "lucide-react";

import { AnimatedNumber, Skeleton, fadeUp, stagger } from "./primitives";
import { UNIT } from "../lib/format";
import { AQI_BANDS, bandForPm25 } from "../lib/aqi";

/**
 * KPI row.
 *
 * Four identical boxes give four equally important numbers, which is
 * the same as giving none. This lays out one HERO metric — the
 * national average, the thing the page is actually about — beside
 * three supporting ones, so the eye lands somewhere first.
 *
 * Colour is carried by the AQI band and nothing else: a red card
 * means dangerous air, never "this card is special".
 */

export default function StatTiles({ stats, loading }) {
  if (loading && !stats) return <StatSkeleton />;
  if (!stats) return null;

  const national = bandForPm25(stats.national_mean_pm25);
  const worst = bandForPm25(stats.worst?.pm2_5);
  const best = bandForPm25(stats.best?.pm2_5);

  return (
    <motion.div
      variants={stagger}
      initial="hidden"
      animate="show"
      className="grid grid-cols-1 gap-3 lg:grid-cols-12"
    >
      {/* ── hero ── */}
      <motion.section
        variants={fadeUp}
        className="card card-hover relative overflow-hidden p-6 lg:col-span-5"
      >
        {/* A wash of the band colour, so severity registers before
            any number is read. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.10]"
          style={{
            background: `radial-gradient(120% 100% at 0% 0%, ${national?.color} 0%, transparent 62%)`,
          }}
        />

        <div className="relative">
          <div className="flex items-center gap-2">
            <Wind size={13} className="text-fg-faint" />
            <span className="eyebrow">National average · PM2.5</span>
          </div>

          <div className="mt-4 flex flex-wrap items-end gap-x-4 gap-y-2">
            <AnimatedNumber
              value={stats.national_mean_pm25}
              digits={1}
              className="metric text-[3.25rem] text-fg"
            />
            <span className="pb-1.5 text-sm text-fg-subtle">{UNIT}</span>

            <span
              className="mb-1.5 ml-auto inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold"
              style={{
                background: `${national?.color}1F`,
                color: national?.color,
              }}
            >
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: national?.color }}
              />
              {national?.name}
            </span>
          </div>

          <div className="mt-5 divider" />

          <div className="mt-4 grid grid-cols-3 gap-4">
            <MiniStat
              label="Median"
              value={stats.national_median_pm25}
              unit={UNIT}
            />
            <MiniStat
              label="Reporting"
              value={stats.cities_reporting}
              unit="of 134"
              digits={0}
            />
            <MiniStat
              label="Provinces"
              value={7}
              unit="covered"
              digits={0}
            />
          </div>
        </div>
      </motion.section>

      {/* ── worst / best ── */}
      <motion.div
        variants={fadeUp}
        className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:col-span-4"
      >
        <CityStat
          label="Most polluted"
          icon={ArrowUpRight}
          city={stats.worst}
          band={worst}
        />
        <CityStat
          label="Cleanest"
          icon={ArrowDownRight}
          city={stats.best}
          band={best}
        />
      </motion.div>

      {/* ── distribution ── */}
      <motion.section
        variants={fadeUp}
        className="card card-hover p-5 lg:col-span-3"
      >
        <span className="eyebrow">Air quality spread</span>
        <CategoryBreakdown
          counts={stats.category_counts}
          total={stats.cities_reporting}
        />
      </motion.section>
    </motion.div>
  );
}

function MiniStat({ label, value, unit, digits = 1 }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-fg-faint">
        {label}
      </div>
      <div className="mt-1 flex items-baseline gap-1">
        <AnimatedNumber
          value={value}
          digits={digits}
          className="metric text-lg text-fg"
        />
        <span className="text-[10px] text-fg-faint">{unit}</span>
      </div>
    </div>
  );
}

function CityStat({ label, icon: Icon, city, band }) {
  return (
    <div className="card card-hover relative flex flex-col justify-between overflow-hidden p-5">
      <div
        aria-hidden
        className="absolute inset-x-0 bottom-0 h-[3px]"
        style={{ background: band?.color, opacity: 0.85 }}
      />

      <div className="flex items-center gap-2">
        <Icon size={13} style={{ color: band?.color }} />
        <span className="eyebrow">{label}</span>
      </div>

      <div className="mt-3">
        <div className="truncate text-xl font-semibold tracking-tight text-fg">
          {city?.city_name ?? "—"}
        </div>

        <div className="mt-2.5 flex items-baseline gap-1.5">
          <span
            className="metric text-2xl"
            style={{ color: band?.color }}
          >
            {city?.pm2_5?.toFixed(1) ?? "—"}
          </span>
          <span className="text-[10px] text-fg-faint">{UNIT}</span>
        </div>

        <div className="mt-2.5 flex items-center justify-between">
          <span className="truncate text-[11px] text-fg-subtle">
            {band?.short ?? band?.name}
          </span>
          <span className="shrink-0 font-mono text-[11px] font-semibold text-fg-muted">
            AQI {city?.aqi_us ?? "—"}
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * Horizontal band breakdown.
 *
 * A stacked stripe is pretty but unreadable at these proportions —
 * a 3-city band becomes a 2px sliver. Stacked rows give every band
 * a readable label and count while still showing relative size.
 */
function CategoryBreakdown({ counts, total }) {
  if (!counts || !total) return null;

  const rows = AQI_BANDS.map((band) => ({
    band,
    n: counts[band.name] ?? 0,
  }))
    .filter((r) => r.n > 0)
    .sort((a, b) => b.n - a.n);

  const max = Math.max(...rows.map((r) => r.n), 1);

  return (
    <div className="mt-3.5 space-y-2">
      {rows.map(({ band, n }, i) => (
        <div key={band.name} className="group">
          <div className="flex items-center justify-between gap-2">
            <span className="flex min-w-0 items-center gap-1.5">
              <span
                className="h-2 w-2 shrink-0 rounded-sm"
                style={{ background: band.color }}
              />
              <span className="truncate text-[11px] text-fg-muted">
                {band.short ?? band.name}
              </span>
            </span>
            <span className="shrink-0 font-mono text-[11px] font-semibold text-fg">
              {n}
            </span>
          </div>
          <div className="mt-1 h-1 overflow-hidden rounded-full bg-sunken">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${(n / max) * 100}%` }}
              transition={{
                duration: 0.6,
                delay: i * 0.05,
                ease: [0.22, 1, 0.36, 1],
              }}
              className="h-full rounded-full"
              style={{ background: band.color }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function StatSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
      <div className="card p-6 lg:col-span-5">
        <Skeleton className="h-3 w-36" />
        <Skeleton className="mt-5 h-14 w-48" />
        <Skeleton className="mt-6 h-10 w-full" />
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:col-span-4">
        {[0, 1].map((i) => (
          <div key={i} className="card p-5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-4 h-6 w-28" />
            <Skeleton className="mt-3 h-5 w-20" />
          </div>
        ))}
      </div>
      <div className="card p-5 lg:col-span-3">
        <Skeleton className="h-3 w-28" />
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="mt-3 h-4 w-full" />
        ))}
      </div>
    </div>
  );
}
