import { motion } from "framer-motion";
import { ArrowDownRight, ArrowUpRight, Mountain, Users } from "lucide-react";

import AqiGauge from "./AqiGauge";
import AqiScene, { AqiSceneChip } from "./AqiScene";
import { AnimatedNumber, Skeleton, fadeUp, stagger } from "./primitives";
import { UNIT, fmtPopulation } from "../lib/format";
import { AQI_BANDS, bandForPm25, pm25ToAqi } from "../lib/aqi";

/**
 * KPI row.
 *
 * Four identical boxes give four equally important numbers, which is
 * the same as giving none. This leads with an illustrated scene plus a
 * gauge -- the scene carries the feeling, the gauge the position on a
 * standard scale -- then three supporting cards.
 *
 * Colour is carried by the AQI band and nothing else: a red card means
 * dangerous air, never "this card is important".
 */

export default function StatTiles({ stats, loading, isDark = true }) {
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
      {/* -- hero: scene + gauge + headline -- */}
      <motion.section
        variants={fadeUp}
        className="card card-hover relative overflow-hidden p-5 sm:p-6 xl:col-span-5"
      >
        {/* The band tint breathes rather than sitting still, which is
            what stops a large card reading as a static panel. */}
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background: `radial-gradient(130% 110% at 100% 0%, ${national?.color} 0%, transparent 60%)`,
          }}
          animate={{ opacity: [0.07, 0.14, 0.07] }}
          transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }}
        />

        {/* The scene is the card's weather: a large illustration bleeding
            off the corner, the way a forecast app leads with sky. It is
            deliberately NOT behind the gauge -- a bright sky under a
            band-coloured numeral destroys the readout's contrast. */}
        <motion.div
          aria-hidden
          className="pointer-events-none absolute -right-12 -top-12
                     sm:-right-14 sm:-top-14"
          initial={{ scale: 0.8, opacity: 0, rotate: -10 }}
          animate={{ scale: 1, opacity: 0.32, rotate: 0 }}
          transition={{ type: "spring", stiffness: 110, damping: 18 }}
        >
          <motion.div
            animate={{ y: [0, 7, 0] }}
            transition={{ duration: 9, repeat: Infinity, ease: "easeInOut" }}
          >
            <AqiScene aqi={nationalAqi} size={168} isDark={isDark} />
          </motion.div>
        </motion.div>

        <div className="relative flex flex-col items-center gap-5 sm:flex-row sm:gap-6">
          <motion.div
            className="relative shrink-0"
            initial={{ scale: 0.86, opacity: 0, rotate: -6 }}
            animate={{ scale: 1, opacity: 1, rotate: 0 }}
            transition={{ type: "spring", stiffness: 140, damping: 16 }}
          >
            <AqiGauge aqi={nationalAqi} size={176} />
          </motion.div>

          <div className="min-w-0 flex-1 text-center sm:text-left">
            {/* A full-opacity scene beside the label: the corner wash is
                atmosphere, this is the legible icon. */}
            <span className="flex items-center justify-center gap-2 sm:justify-start">
              <AqiSceneChip aqi={nationalAqi} size={26} isDark={isDark} />
              <span className="eyebrow">National average</span>
            </span>

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

      {/* -- extremes -- */}
      <motion.div
        variants={fadeUp}
        className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:col-span-4"
      >
        <CityStat
          label="Most polluted"
          icon={ArrowUpRight}
          city={stats.worst}
          band={worst}
          isDark={isDark}
        />
        <CityStat
          label="Cleanest"
          icon={ArrowDownRight}
          city={stats.best}
          band={best}
          isDark={isDark}
        />
      </motion.div>

      {/* -- distribution -- */}
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
          isDark={isDark}
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
        {unit ? (
          <span className="text-[10px] text-fg-faint">{unit}</span>
        ) : null}
      </div>
    </div>
  );
}

function CityStat({ label, icon: Icon, city, band, isDark }) {
  return (
    <motion.div
      whileHover={{ y: -4, scale: 1.012 }}
      transition={{ type: "spring", stiffness: 320, damping: 22 }}
      className="card group relative flex flex-col justify-between overflow-hidden p-5"
    >
      {/* The scene sits in the corner at low opacity: atmosphere, not
          content, so it never competes with the number. */}
      <motion.div
        aria-hidden
        className="pointer-events-none absolute -right-7 -top-7 opacity-25
                   transition-opacity duration-300 group-hover:opacity-45"
        animate={{ y: [0, 5, 0] }}
        transition={{ duration: 8, repeat: Infinity, ease: "easeInOut" }}
      >
        <AqiScene aqi={city?.aqi_us} size={112} isDark={isDark} />
      </motion.div>

      <motion.div
        aria-hidden
        className="absolute inset-x-0 bottom-0 h-[3px] origin-left"
        style={{ background: band?.color }}
        initial={{ scaleX: 0 }}
        animate={{ scaleX: 1 }}
        transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
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
          <span
            className="metric text-[1.75rem]"
            style={{ color: band?.color }}
          >
            {city?.pm2_5?.toFixed(1) ?? "—"}
          </span>
          <span className="pb-1 text-[10px] text-fg-faint">{UNIT}</span>
          <motion.span
            className="mb-0.5 ml-auto shrink-0 rounded-md px-1.5 py-0.5 font-mono text-[10px] font-bold"
            style={{ background: `${band?.color}1F`, color: band?.color }}
            animate={{ scale: [1, 1.06, 1] }}
            transition={{ duration: 3.5, repeat: Infinity, ease: "easeInOut" }}
          >
            AQI {city?.aqi_us ?? "—"}
          </motion.span>
        </div>

        <div className="mt-2 flex items-center gap-3 text-[11px] text-fg-subtle">
          <span className="flex min-w-0 items-center gap-1.5">
            <Users size={11} className="shrink-0 text-fg-faint" />
            <span className="truncate">{fmtPopulation(city?.population)}</span>
          </span>
          {Number.isFinite(city?.elevation_m) ? (
            <span className="flex shrink-0 items-center gap-1.5">
              <Mountain size={11} className="shrink-0 text-fg-faint" />
              <span>{Math.round(city.elevation_m)} m</span>
            </span>
          ) : null}
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
function CategoryBreakdown({ counts, total, isDark }) {
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
          <motion.div
            key={band.name}
            title={`${band.name}: ${n} of ${total} cities`}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.35, delay: i * 0.055 }}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5">
                {/* A tiny scene instead of a square swatch: the row still
                    reads as a legend, but each step now looks like the
                    sky it describes. */}
                <span style={{ opacity: empty ? 0.35 : 1 }}>
                  <AqiSceneChip
                    aqi={band.lower + 1}
                    size={15}
                    isDark={isDark}
                  />
                </span>
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
                  duration: 0.75,
                  delay: 0.15 + i * 0.07,
                  ease: [0.22, 1, 0.36, 1],
                }}
                className="h-full rounded-full"
                style={{ background: band.color }}
              />
            </div>
          </motion.div>
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
