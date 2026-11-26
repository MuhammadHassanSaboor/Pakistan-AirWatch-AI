import { motion } from "framer-motion";
import { ArrowDownRight, ArrowUpRight, Users } from "lucide-react";

import AqiGauge from "./AqiGauge";
import { AnimatedNumber, Skeleton, fadeUp, stagger } from "./primitives";
import { UNIT, fmtPopulation } from "../lib/format";
import { AQI_BANDS, bandForPm25, pm25ToAqi } from "../lib/aqi";

/**
 * KPI row.
 *
 * Four identical boxes give four equally important numbers, which is
 * the same as giving none. This leads with a gauge — position on a
 * standard scale, readable at a glance — then three supporting cards.
 *
 * Colour is carried by the AQI band and nothing else: a red card means
 * dangerous air, never "this card is important".
 */

export default function StatTiles({ stats, loading }) {
  if (loading && !stats) return <StatSkeleton />;
  if (!stats) return null;

  const national = bandForPm25(stats.national_mean_pm25);
  const nationalAqi = pm25ToAqi(stats.national_mean_pm25);
  const worst = bandForPm25(stats.worst?.pm2_5);
  const best = bandForPm25(stats.best?.pm2_5);

  return (
    <motion.div
      variants={stagger}
      initial="hidden"
      animate="show"
      className="grid grid-cols-1 gap-3 xl:grid-cols-12"
    >
      {/* ── hero: gauge + headline ── */}
      <motion.section
        variants={fadeUp}
        className="card card-hover relative overflow-hidden p-5 sm:p-6 xl:col-span-5"
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.09]"
          style={{
            background: `radial-gradient(130% 110% at 100% 0%, ${national?.color} 0%, transparent 60%)`,
          }}
        />

        <div className="relative flex flex-col items-center gap-5 sm:flex-row sm:gap-6">
          <AqiGauge aqi={nationalAqi} size={176} />

          <div className="min-w-0 flex-1 text-center sm:text-left">
            <span className="eyebrow">National average</span>

            <div className="mt-2 flex items-end justify-center gap-2 sm:justify-start">
              <AnimatedNumber
                value={stats.national_mean_pm25}
                digits={1}
                className="metric text-[2.75rem] text-fg"
              />
              <span className="pb-1.5 text-xs text-fg-subtle">{UNIT}</span>
            </div>

            <p className="mt-2 text-[11px] leading-relaxed text-fg-subtle">
              {national?.advice}
            </p>

            <div className="mt-4 divider" />

            <div className="mt-3 grid grid-cols-3 gap-3">
              <MiniStat label="Median" value={stats.national_median_pm25} />
              <MiniStat
                label="Reporting"
                value={stats.cities_reporting}
                unit="/134"
                digits={0}
              />
              <MiniStat label="Provinces" value={7} unit="/7" digits={0} />
            </div>
          </div>
        </div>
      </motion.section>

      {/* ── extremes ── */}
      <motion.div
        variants={fadeUp}
        className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:col-span-4"
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
        className="card card-hover p-5 xl:col-span-3"
      >
        <span className="eyebrow">Air quality spread</span>
        <p className="mt-1 text-[10px] text-fg-faint">
          US EPA categories, best to worst
        </p>
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
      <div className="mt-1 flex items-baseline justify-center gap-0.5 sm:justify-start">
        <AnimatedNumber
          value={value}
          digits={digits}
          className="metric text-base text-fg"
        />
        {unit ? <span className="text-[10px] text-fg-faint">{unit}</span> : null}
      </div>
    </div>
  );
}

function CityStat({ label, icon: Icon, city, band }) {
  return (
    <motion.div
      whileHover={{ y: -2 }}
      transition={{ duration: 0.18 }}
      className="card relative flex flex-col justify-between overflow-hidden p-5"
    >
      <div
        aria-hidden
        className="absolute inset-x-0 bottom-0 h-[3px]"
        style={{ background: band?.color, opacity: 0.9 }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.06]"
        style={{
          background: `radial-gradient(120% 100% at 100% 100%, ${band?.color}, transparent 65%)`,
        }}
      />

      <div className="relative flex items-center gap-2">
        <Icon size={13} style={{ color: band?.color }} />
        <span className="eyebrow">{label}</span>
      </div>

      <div className="relative mt-3">
        <div className="truncate text-xl font-semibold tracking-tight text-fg">
          {city?.city_name ?? "—"}
        </div>

        <div className="mt-2.5 flex items-end gap-1.5">
          <span className="metric text-[1.75rem]" style={{ color: band?.color }}>
            {city?.pm2_5?.toFixed(1) ?? "—"}
          </span>
          <span className="pb-1 text-[10px] text-fg-faint">{UNIT}</span>
          <span
            className="mb-0.5 ml-auto shrink-0 rounded-md px-1.5 py-0.5 font-mono text-[10px] font-bold"
            style={{ background: `${band?.color}1F`, color: band?.color }}
          >
            AQI {city?.aqi_us ?? "—"}
          </span>
        </div>

        <div className="mt-2 flex items-center gap-1.5 text-[11px] text-fg-subtle">
          <Users size={11} className="shrink-0 text-fg-faint" />
          <span className="truncate">
            {fmtPopulation(city?.population)} residents
          </span>
        </div>
      </div>
    </motion.div>
  );
}

/**
 * Distribution across the six EPA categories.
 *
 * Always rendered in severity order, never sorted by count. A list
 * reading "Unhealthy, Moderate, USG, Very Unhealthy, Good" is not a
 * scale any reader can follow and looks like a defect to anyone who
 * knows the standard. Empty categories are kept but dimmed, so the
 * scale stays complete rather than appearing to skip steps.
 */
function CategoryBreakdown({ counts, total }) {
  if (!counts || !total) return null;

  const rows = AQI_BANDS.map((band) => ({
    band,
    n: counts[band.name] ?? 0,
  }));
  const max = Math.max(...rows.map((r) => r.n), 1);

  return (
    <div className="mt-3.5 space-y-2">
      {rows.map(({ band, n }, i) => {
        const empty = n === 0;
        return (
          <div key={band.name} title={`${band.name}: ${n} of ${total} cities`}>
            <div className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5">
                <span
                  className="h-2 w-2 shrink-0 rounded-sm"
                  style={{ background: band.color, opacity: empty ? 0.3 : 1 }}
                />
                <span
                  className={`truncate text-[11px] ${
                    empty ? "text-fg-faint" : "text-fg-muted"
                  }`}
                >
                  {band.abbr}
                </span>
              </span>
              <span
                className={`shrink-0 font-mono text-[11px] font-semibold ${
                  empty ? "text-fg-faint" : "text-fg"
                }`}
              >
                {n}
              </span>
            </div>
            <div className="mt-1 h-1 overflow-hidden rounded-full bg-sunken">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${(n / max) * 100}%` }}
                transition={{
                  duration: 0.65,
                  delay: 0.1 + i * 0.06,
                  ease: [0.22, 1, 0.36, 1],
                }}
                className="h-full rounded-full"
                style={{ background: band.color }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StatSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
      <div className="card flex items-center gap-6 p-6 xl:col-span-5">
        <Skeleton className="h-44 w-44 rounded-full" />
        <div className="flex-1">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="mt-3 h-12 w-40" />
          <Skeleton className="mt-4 h-10 w-full" />
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:col-span-4">
        {[0, 1].map((i) => (
          <div key={i} className="card p-5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-4 h-6 w-28" />
            <Skeleton className="mt-3 h-7 w-24" />
          </div>
        ))}
      </div>
      <div className="card p-5 xl:col-span-3">
        <Skeleton className="h-3 w-28" />
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Skeleton key={i} className="mt-2.5 h-4 w-full" />
        ))}
      </div>
    </div>
  );
}
