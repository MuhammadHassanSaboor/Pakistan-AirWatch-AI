import { motion } from "framer-motion";
import { Activity, Moon, RefreshCw, Sun, Wind } from "lucide-react";
import clsx from "clsx";

import PakistanFlag from "./PakistanFlag";
import { EASE } from "./primitives";
import { fmtRelative } from "../lib/format";

function StatusDot({ ok, degraded }) {
  const color = ok ? "bg-ok" : degraded ? "bg-warn" : "bg-danger";
  return (
    <span className="relative flex h-2 w-2">
      {ok ? (
        <span
          className={clsx(
            "absolute inline-flex h-full w-full rounded-full opacity-60",
            color,
            "animate-pulse-ring",
          )}
        />
      ) : null}
      <span
        className={clsx("relative inline-flex h-2 w-2 rounded-full", color)}
      />
    </span>
  );
}

export default function Header({
  health,
  modelInfo,
  onRefresh,
  refreshing,
  theme,
  onToggleTheme,
}) {
  const ok = health?.status === "healthy";
  const degraded = health?.status === "degraded";

  return (
    <motion.header
      initial={{ opacity: 0, y: -14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: EASE }}
      className="sticky top-0 z-[1100] border-b border-line bg-surface/85 backdrop-blur-xl"
    >
      <div className="mx-auto flex max-w-[1800px] flex-wrap items-center gap-x-5 gap-y-3 px-4 py-3 sm:px-6">
        {/* brand */}
        <div className="flex items-center gap-3">
          <motion.div
            whileHover={{ rotate: 12, scale: 1.06 }}
            transition={{ type: "spring", stiffness: 320, damping: 16 }}
            className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent-strong shadow-glow"
          >
            <Wind size={18} className="text-canvas" strokeWidth={2.4} />
          </motion.div>
          <div className="leading-tight">
            <h1 className="flex items-center gap-2 text-base font-bold tracking-tight text-fg">
              {/* The flag sits with the country in the title, which is
                  the one place it reads as identity rather than
                  decoration stuck in a corner. */}
              <PakistanFlag width={26} />
              Pakistan AirWatch <span className="text-accent">AI</span>
            </h1>
            <p className="text-xs text-fg-subtle">
              Hourly PM2.5 forecasting &middot; 134 cities
            </p>
          </div>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {/* model */}
          {modelInfo?.model_version ? (
            <div
              className="chip"
              title={`Run ${modelInfo.run_id ?? "unknown"}`}
            >
              <Activity size={12} className="text-accent" />
              <span className="font-mono">
                {modelInfo.algorithm} v{modelInfo.model_version}
              </span>
            </div>
          ) : null}

          {/* upstream freshness */}
          {health?.upstream_cache?.fetched_at ? (
            <div className="chip" title="Age of the cached upstream data">
              <span className="text-fg-faint">data</span>
              <span className="font-mono">
                {fmtRelative(health.upstream_cache.fetched_at)}
              </span>
            </div>
          ) : null}

          {/* service status */}
          <div
            className={clsx(
              "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium",
              ok
                ? "border-ok/35 bg-ok/12 text-ok"
                : degraded
                  ? "border-warn/35 bg-warn/12 text-warn"
                  : "border-danger/35 bg-danger/12 text-danger",
            )}
            title={health?.reason ?? undefined}
          >
            <StatusDot ok={ok} degraded={degraded} />
            {ok ? "Operational" : degraded ? "Degraded" : "Offline"}
          </div>

          <button
            type="button"
            onClick={(e) => {
              // Grow the reveal circle from the button itself, so the
              // sweep visibly starts where the user clicked.
              const r = e.currentTarget.getBoundingClientRect();
              onToggleTheme({
                x: r.left + r.width / 2,
                y: r.top + r.height / 2,
              });
            }}
            className="btn !px-2.5"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          >
            <motion.span
              key={theme}
              initial={{ rotate: -90, opacity: 0, scale: 0.6 }}
              animate={{ rotate: 0, opacity: 1, scale: 1 }}
              transition={{ type: "spring", stiffness: 300, damping: 18 }}
              className="flex"
            >
              {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
            </motion.span>
          </button>

          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            className="btn"
            aria-label="Refresh data"
          >
            <RefreshCw
              size={14}
              className={refreshing ? "animate-spin" : undefined}
            />
            <span className="hidden sm:inline">Refresh</span>
          </button>
        </div>
      </div>
    </motion.header>
  );
}
