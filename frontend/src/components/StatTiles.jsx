import { motion } from "framer-motion";
import { ArrowDown, ArrowUp, Gauge, MapPin, Users } from "lucide-react";
import clsx from "clsx";

import { AnimatedNumber, Skeleton, fadeUp, stagger } from "./primitives";
import { UNIT, fmtInt } from "../lib/format";
import { AQI_BANDS, bandForPm25 } from "../lib/aqi";

function Tile({ children, className, ...rest }) {
  return (
    <motion.div
      variants={fadeUp}
      className={clsx("panel relative overflow-hidden p-4", className)}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

function Label({ icon: Icon, children }) {
  return (
    <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-500">
      {Icon ? <Icon size={11} /> : null}
      {children}
    </div>
  );
}

export default function StatTiles({ stats, loading }) {
  if (loading && !stats) {
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="panel p-4">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-3 h-8 w-20" />
            <Skeleton className="mt-2 h-3 w-28" />
          </div>
        ))}
      </div>
    );
  }

  if (!stats) return null;

  const worstBand = bandForPm25(stats.worst?.pm2_5);
  const bestBand = bandForPm25(stats.best?.pm2_5);
  const nationalBand = bandForPm25(stats.national_mean_pm25);

  return (
    <motion.div
      variants={stagger}
      initial="hidden"
      animate="show"
      className="grid grid-cols-2 gap-3 lg:grid-cols-4"
    >
      {/* national average */}
      <Tile>
        <Label icon={Gauge}>National average</Label>
        <div className="mt-2 flex items-baseline gap-1.5">
          <AnimatedNumber
            value={stats.national_mean_pm25}
            className="stat-value"
            digits={1}
          />
          <span className="text-xs text-ink-500">{UNIT}</span>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: nationalBand?.color }}
          />
          <span className="text-[11px] text-ink-400">
            {nationalBand?.name ?? "—"}
          </span>
        </div>
        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 h-0.5"
          style={{ background: nationalBand?.color, opacity: 0.6 }}
        />
      </Tile>

      {/* worst city */}
      <Tile>
        <Label icon={ArrowUp}>Most polluted</Label>
        <div className="mt-2 truncate text-xl font-bold tracking-tight text-white">
          {stats.worst?.city_name ?? "—"}
        </div>
        <div className="mt-1 flex items-baseline gap-1.5">
          <span
            className="font-mono text-lg font-semibold tabular-nums"
            style={{ color: worstBand?.color }}
          >
            {stats.worst?.pm2_5?.toFixed(1) ?? "—"}
          </span>
          <span className="text-[11px] text-ink-500">{UNIT}</span>
          <span className="ml-auto text-[11px] text-ink-400">
            AQI {stats.worst?.aqi_us ?? "—"}
          </span>
        </div>
        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 h-0.5"
          style={{ background: worstBand?.color, opacity: 0.7 }}
        />
      </Tile>

      {/* cleanest city */}
      <Tile>
        <Label icon={ArrowDown}>Cleanest</Label>
        <div className="mt-2 truncate text-xl font-bold tracking-tight text-white">
          {stats.best?.city_name ?? "—"}
        </div>
        <div className="mt-1 flex items-baseline gap-1.5">
          <span
            className="font-mono text-lg font-semibold tabular-nums"
            style={{ color: bestBand?.color }}
          >
            {stats.best?.pm2_5?.toFixed(1) ?? "—"}
          </span>
          <span className="text-[11px] text-ink-500">{UNIT}</span>
          <span className="ml-auto text-[11px] text-ink-400">
            AQI {stats.best?.aqi_us ?? "—"}
          </span>
        </div>
        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 h-0.5"
          style={{ background: bestBand?.color, opacity: 0.7 }}
        />
      </Tile>

      {/* category distribution */}
      <Tile>
        <Label icon={MapPin}>Cities reporting</Label>
        <div className="mt-2 flex items-baseline gap-1.5">
          <AnimatedNumber
            value={stats.cities_reporting}
            digits={0}
            className="stat-value"
          />
          <span className="text-xs text-ink-500">of 134</span>
        </div>
        <CategoryBar counts={stats.category_counts} total={stats.cities_reporting} />
      </Tile>
    </motion.div>
  );
}

function CategoryBar({ counts, total }) {
  if (!counts || !total) return null;
  return (
    <div className="mt-2.5">
      <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
        {AQI_BANDS.map((band) => {
          const n = counts[band.name] ?? 0;
          if (!n) return null;
          return (
            <motion.div
              key={band.name}
              initial={{ width: 0 }}
              animate={{ width: `${(n / total) * 100}%` }}
              transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
              style={{ background: band.color }}
              title={`${band.name}: ${n} ${n === 1 ? "city" : "cities"}`}
            />
          );
        })}
      </div>
      <div className="mt-1.5 flex items-center gap-1 text-[10px] text-ink-500">
        <Users size={10} />
        {fmtInt(total)} cities across 7 provinces
      </div>
    </div>
  );
}
