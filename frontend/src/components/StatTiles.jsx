import { motion } from "framer-motion";
import {
  ArrowDownRight,
  ArrowUpRight,
  Mountain,
  Radio,
  Users,
} from "lucide-react";

import AqiGauge from "./AqiGauge";
import { AqiSceneChip } from "./AqiScene";
import PhotoBackdrop from "./PhotoBackdrop";
import { AnimatedNumber, Skeleton, fadeUp, stagger } from "./primitives";
import { UNIT, fmtPopulation } from "../lib/format";
import { AQI_BANDS, bandForPm25, pm25ToAqi, textOn } from "../lib/aqi";
import { bandPhoto } from "../lib/photos";

/**
 * KPI row.
 *
 * Three rules, after several passes that broke all of them:
 *
 *  1. A KPI is a headline, so it is set at headline size. The earlier
 *     version put 10px labels over 15px numbers, which made the most
 *     important figures on the page the smallest text on it.
 *  2. Every card fills its height. Cards that stop short leave ragged
 *     gaps between the row and the map, and empty space in a card
 *     reads as unfinished rather than as restraint.
 *  3. Photography sets the mood, the numbers carry the meaning. The
 *     image is always behind a scrim and never the thing being read.
 */

export default function StatTiles({
  stats,
  loading,
  isDark,
  onSelectCity,
  bandFilter,
  onToggleBand,
}) {
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
      className="grid grid-cols-1 items-stretch gap-3 xl:grid-cols-12"
    >
      {/* ── hero ── */}
      <motion.section
        variants={fadeUp}
        whileHover={{ y: -3 }}
        transition={{ type: "spring", stiffness: 280, damping: 24 }}
        className="card relative flex min-h-[22rem] flex-col overflow-hidden xl:col-span-5"
      >
        {/* Soft scrim here too, now that the header, the gauge and the
            body all sit on plates. With everything plated the image no
            longer has to be suppressed to keep text readable, which is
            the whole reason it looked washed out before. */}
        <PhotoBackdrop
          photo={bandPhoto(national?.name)}
          width={760}
          height={380}
          scrim="soft"
        />

        {/* The band tint breathes, so the largest card on the page is
            never completely still. */}
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background: `radial-gradient(120% 120% at 100% 0%, ${national?.color} 0%, transparent 62%)`,
          }}
          animate={{ opacity: [0.08, 0.16, 0.08] }}
          transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }}
        />

        <div className="relative flex flex-1 flex-col p-5 sm:p-6">
          <div className="flex items-start justify-between gap-3">
            <div className="plate flex items-center gap-2.5 px-3 py-2">
              <AqiSceneChip aqi={nationalAqi} size={32} isDark={isDark} />
              <div>
                <div className="text-base font-semibold tracking-tight text-fg">
                  National average
                </div>
                <div className="text-xs text-fg-muted">
                  {stats.cities_reporting} cities, all 7 provinces
                </div>
              </div>
            </div>

            {/* The band is the single most important word on the card,
                so it is set at body size on an opaque plate rather than
                as 11px caps floating over a photograph. */}
            <span
              className="inline-flex shrink-0 items-center gap-1.5 rounded-xl px-3
                         py-2 text-sm font-bold tracking-tight shadow-sm"
              style={{
                background: national?.color,
                color: textOn(national?.color),
              }}
            >
              <Radio size={14} />
              {national?.abbr}
            </span>
          </div>

          {/* The headline. Gauge and numeral are deliberately the same
              visual weight -- one gives position on the scale, the
              other the value, and neither is the footnote. */}
          <div className="mt-5 flex flex-1 items-center gap-5 sm:gap-7">
            <motion.div
              className="plate shrink-0 !rounded-full p-1"
              initial={{ scale: 0.84, opacity: 0, rotate: -8 }}
              animate={{ scale: 1, opacity: 1, rotate: 0 }}
              transition={{ type: "spring", stiffness: 130, damping: 16 }}
            >
              <AqiGauge aqi={nationalAqi} size={168} />
            </motion.div>

            <div className="plate min-w-0 flex-1 p-3.5">
              <div className="flex items-end gap-2">
                <AnimatedNumber
                  value={stats.national_mean_pm25}
                  digits={1}
                  className="metric text-[3.25rem] leading-none text-fg"
                />
                <span className="pb-2 text-sm font-semibold text-fg-muted">
                  {UNIT}
                </span>
              </div>
              <div className="mt-1.5 text-sm font-semibold text-fg-muted">
                PM2.5 mass concentration
              </div>
              <p className="mt-2.5 text-[13px] leading-relaxed text-fg-muted">
                {national?.advice}
              </p>
            </div>
          </div>

          {/* Footer strip: three real numbers at real sizes, divided by
              hairlines rather than floated in whitespace. */}
          <div className="plate mt-5 grid grid-cols-3">
            <Stat
              label="Median"
              value={stats.national_median_pm25}
              unit={UNIT}
            />
            <Stat
              label="Reporting"
              value={stats.cities_reporting}
              digits={0}
              unit="of 134"
              divider
            />
            <Stat label="Provinces" value={7} digits={0} unit="of 7" divider />
          </div>
        </div>
      </motion.section>

      {/* ── extremes ── */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:col-span-4">
        <CityStat
          label="Most polluted"
          icon={ArrowUpRight}
          city={stats.worst}
          band={worst}
          isDark={isDark}
          onSelect={onSelectCity}
        />
        <CityStat
          label="Cleanest"
          icon={ArrowDownRight}
          city={stats.best}
          band={best}
          isDark={isDark}
          onSelect={onSelectCity}
        />
      </div>

      {/* ── distribution ── */}
      <motion.section
        variants={fadeUp}
        whileHover={{ y: -3 }}
        transition={{ type: "spring", stiffness: 280, damping: 24 }}
        className="card flex flex-col p-5 xl:col-span-3"
      >
        <div className="text-sm font-semibold tracking-tight text-fg">
          Air quality spread
        </div>
        <p className="mt-0.5 text-xs text-fg-subtle">
          Click a category to filter the map
        </p>
        <CategoryBreakdown
          counts={stats.category_counts}
          total={stats.cities_reporting}
          isDark={isDark}
          active={bandFilter}
          onToggle={onToggleBand}
        />
      </motion.section>
    </motion.div>
  );
}

/** One cell of the hero footer strip. */
function Stat({ label, value, unit, digits = 1, divider = false }) {
  return (
    <div
      className={`px-3.5 py-3 ${divider ? "border-l border-line" : ""}`}
      title={`${label}: ${value}`}
    >
      <div className="text-2xs font-semibold uppercase tracking-[0.1em] text-fg-faint">
        {label}
      </div>
      <div className="mt-1.5 flex items-baseline gap-1">
        <AnimatedNumber
          value={value}
          digits={digits}
          className="metric text-2xl text-fg"
        />
      </div>
      {unit ? (
        <div className="mt-0.5 truncate text-2xs text-fg-faint">{unit}</div>
      ) : null}
    </div>
  );
}

function CityStat({ label, icon: Icon, city, band, isDark, onSelect }) {
  const clickable = Boolean(onSelect && city?.city_id);
  return (
    <motion.div
      variants={fadeUp}
      whileHover={{ y: -4 }}
      whileTap={clickable ? { scale: 0.985 } : undefined}
      transition={{ type: "spring", stiffness: 300, damping: 22 }}
      // A card naming a city that the map can centre on should open it.
      // Keyboard users get the same affordance, which is why this is a
      // real button role with a key handler rather than a bare onClick.
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={clickable ? () => onSelect(city.city_id) : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(city.city_id);
              }
            }
          : undefined
      }
      title={clickable ? `Open ${city.city_name}` : undefined}
      className={`card group relative flex min-h-[12.5rem] flex-col justify-between
                 overflow-hidden p-4 sm:p-5 ${
                   clickable ? "cursor-pointer" : ""
                 }`}
    >
      {/* Soft scrim, because every word on this card sits on a plate.
          The photograph is allowed to actually look like a photograph. */}
      <PhotoBackdrop
        photo={bandPhoto(band?.name)}
        width={440}
        height={300}
        scrim="soft"
      />

      <motion.div
        aria-hidden
        className="absolute inset-x-0 bottom-0 h-[3px] origin-left"
        style={{ background: band?.color }}
        initial={{ scaleX: 0 }}
        animate={{ scaleX: 1 }}
        transition={{ duration: 0.75, ease: [0.22, 1, 0.36, 1] }}
      />

      {/* "Most polluted" was 11px caps at muted contrast over a photo,
          which is unreadable however good the scrim is. It is now 13px
          semibold at full foreground contrast on its own plate. */}
      <div className="tag relative self-start !rounded-xl !py-1.5">
        <span className="transition-transform duration-300 group-hover:scale-110">
          <AqiSceneChip aqi={city?.aqi_us} size={22} isDark={isDark} />
        </span>
        <Icon size={15} className="text-fg-muted" />
        <span className="text-[13px] font-semibold tracking-tight text-fg">
          {label}
        </span>
      </div>

      <div className="plate relative mt-3 p-3">
        {/* Every element gets its own row, and no row competes for width.
            Sharing a line was the whole problem: the name had to fight a
            chip whose width depends on the band ("Good" vs "Very
            Unhealthy"), so it truncated to "Faisala..."; and the AQI
            shared the value's line with `flex-wrap`, so it wrapped at
            three digits and not at two -- the two cards laid out
            differently purely because of how polluted their city was.
            Fixed rows mean both cards always look identical. */}
        <div className="truncate text-xl font-semibold tracking-tight text-fg">
          {city?.city_name ?? "—"}
        </div>
        <div className="truncate text-xs font-medium text-fg-muted">
          {city?.province ?? ""}
        </div>

        <div className="mt-2 flex items-end gap-1.5">
          {/* The numeral is foreground, not band colour: at Moderate the
              band colour is 1.89:1 on white. */}
          <span className="metric text-[2.25rem] leading-none text-fg">
            {city?.pm2_5?.toFixed(1) ?? "—"}
          </span>
          <span className="pb-1 text-xs font-medium text-fg-muted">{UNIT}</span>
        </div>

        <div className="mt-2 flex items-center gap-2">
          <motion.span
            className="min-w-0 truncate rounded-lg px-2 py-1 text-xs font-bold shadow-sm"
            style={{ background: band?.color, color: textOn(band?.color) }}
            animate={{ scale: [1, 1.04, 1] }}
            transition={{ duration: 3.5, repeat: Infinity, ease: "easeInOut" }}
          >
            {band?.abbr}
          </motion.span>
          <span className="ml-auto shrink-0 font-mono text-[13px] font-bold text-fg-muted">
            AQI {city?.aqi_us ?? "—"}
          </span>
        </div>

        <div
          className="mt-2.5 flex items-center gap-3.5 border-t pt-2 text-xs font-medium text-fg-muted"
          style={{ borderColor: "var(--hairline)" }}
        >
          <span className="flex min-w-0 items-center gap-1.5">
            <Users size={13} className="shrink-0 text-fg-subtle" />
            <span className="truncate">{fmtPopulation(city?.population)}</span>
          </span>
          {Number.isFinite(city?.elevation_m) ? (
            <span className="flex shrink-0 items-center gap-1.5">
              <Mountain size={13} className="shrink-0 text-fg-subtle" />
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
 *
 * Bars are scaled to the largest category, not to the total: with 134
 * cities spread over six bands, scaling to the total leaves every bar
 * a stub. The share of the total is given as a percentage instead.
 */
function CategoryBreakdown({ counts, total, isDark, active, onToggle }) {
  if (!counts || !total) return null;

  const rows = AQI_BANDS.map((band) => ({
    band,
    n: counts[band.name] ?? 0,
  }));
  const max = Math.max(...rows.map((r) => r.n), 1);

  return (
    <div className="mt-4 flex flex-1 flex-col justify-between gap-2.5">
      {rows.map(({ band, n }, i) => {
        const empty = n === 0;
        const isActive = active === band.name;
        const pct = Math.round((n / total) * 100);
        return (
          <motion.button
            key={band.name}
            type="button"
            disabled={empty || !onToggle}
            onClick={() => onToggle?.(band.name)}
            title={
              empty
                ? `${band.name}: no cities in this category`
                : isActive
                  ? `Showing only ${band.name} — click to clear`
                  : `${band.name}: ${n} of ${total} cities (${pct}%) — click to filter the map`
            }
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            whileTap={empty ? undefined : { scale: 0.98 }}
            transition={{ duration: 0.4, delay: i * 0.06 }}
            className={`group -mx-2 rounded-lg px-2 py-1 text-left transition-colors
                        duration-150 disabled:cursor-default ${
                          isActive
                            ? "bg-accent/12 ring-1 ring-accent/35"
                            : empty
                              ? ""
                              : "hover:bg-raised"
                        }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-2">
                {/* A scene instead of a square swatch: the scale now
                    shows what each band looks like, not just its hex. */}
                <span
                  className="transition-transform duration-200 group-hover:scale-110"
                  style={{ opacity: empty ? 0.35 : 1 }}
                >
                  <AqiSceneChip
                    aqi={band.lower + 1}
                    size={22}
                    isDark={isDark}
                  />
                </span>
                <span
                  className={`truncate text-[13px] font-medium ${
                    empty ? "text-fg-faint" : "text-fg-muted"
                  }`}
                >
                  {band.abbr}
                </span>
              </span>
              <span className="flex shrink-0 items-baseline gap-1">
                <span
                  className={`metric text-base ${
                    empty ? "text-fg-faint" : "text-fg"
                  }`}
                >
                  {n}
                </span>
                <span className="w-8 text-right text-2xs text-fg-faint">
                  {pct}%
                </span>
              </span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-sunken">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${(n / max) * 100}%` }}
                transition={{
                  duration: 0.8,
                  delay: 0.2 + i * 0.07,
                  ease: [0.22, 1, 0.36, 1],
                }}
                className="h-full rounded-full"
                style={{
                  background: `linear-gradient(90deg, ${band.color}99, ${band.color})`,
                }}
              />
            </div>
          </motion.button>
        );
      })}
    </div>
  );
}

function StatSkeleton() {
  return (
    <div className="grid grid-cols-1 items-stretch gap-3 xl:grid-cols-12">
      <div className="card min-h-[22rem] p-6 xl:col-span-5">
        <Skeleton className="h-4 w-40" />
        <div className="mt-6 flex items-center gap-6">
          <Skeleton className="h-40 w-40 shrink-0 rounded-full" />
          <div className="flex-1">
            <Skeleton className="h-12 w-40" />
            <Skeleton className="mt-3 h-4 w-48" />
            <Skeleton className="mt-3 h-10 w-full" />
          </div>
        </div>
        <Skeleton className="mt-6 h-20 w-full rounded-xl" />
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:col-span-4">
        {[0, 1].map((i) => (
          <div key={i} className="card min-h-[12.5rem] p-5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-5 h-7 w-32" />
            <Skeleton className="mt-3 h-9 w-24" />
            <Skeleton className="mt-3 h-3 w-28" />
          </div>
        ))}
      </div>
      <div className="card p-5 xl:col-span-3">
        <Skeleton className="h-4 w-32" />
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Skeleton key={i} className="mt-3 h-6 w-full" />
        ))}
      </div>
    </div>
  );
}
