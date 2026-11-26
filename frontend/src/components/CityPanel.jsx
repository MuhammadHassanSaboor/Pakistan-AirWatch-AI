import { AnimatePresence, motion } from "framer-motion";
import {
  Droplets,
  Gauge,
  Mountain,
  Thermometer,
  Users,
  Wind,
  X,
} from "lucide-react";

import { EASE, ErrorState, Skeleton, SourceBadge } from "./primitives";
import { TrendChart } from "./charts";
import AqiScene from "./AqiScene";
import { bandForPm25, pm25ToAqi } from "../lib/aqi";
import {
  UNIT,
  fmtNumber,
  fmtPopulation,
  fmtTime,
  sourceLabel,
} from "../lib/format";

function Metric({ icon: Icon, label, value, unit }) {
  return (
    <div className="rounded-lg border border-line bg-raised p-2.5">
      <div className="flex items-center gap-1.5 text-2xs uppercase tracking-wider text-fg-faint">
        <Icon size={11} />
        {label}
      </div>
      <div className="mt-1 font-mono text-sm font-semibold tabular-nums text-fg">
        {value}
        {unit ? (
          <span className="ml-1 text-2xs text-fg-faint">{unit}</span>
        ) : null}
      </div>
    </div>
  );
}

export default function CityPanel({
  cityId,
  data,
  loading,
  error,
  onClose,
  onRetry,
  theme,
}) {
  return (
    <AnimatePresence mode="wait">
      {cityId ? (
        <motion.aside
          key={cityId}
          initial={{ opacity: 0, x: 28 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 28 }}
          transition={{ duration: 0.38, ease: EASE }}
          className="card flex max-h-full flex-col overflow-hidden"
        >
          <Content
            data={data}
            loading={loading}
            error={error}
            onClose={onClose}
            onRetry={onRetry}
            theme={theme}
          />
        </motion.aside>
      ) : null}
    </AnimatePresence>
  );
}

function Content({ data, loading, error, onClose, onRetry, theme }) {
  if (error) {
    return (
      <>
        <Head title="Error" onClose={onClose} />
        <ErrorState error={error} onRetry={onRetry} compact />
      </>
    );
  }

  if (loading || !data) {
    return (
      <>
        <Head title="Loading…" onClose={onClose} />
        <div className="space-y-3 p-4">
          <Skeleton className="h-16 w-full" />
          <div className="grid grid-cols-2 gap-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-14" />
            ))}
          </div>
          <Skeleton className="h-48 w-full" />
        </div>
      </>
    );
  }

  const city = data.city ?? {};
  const latest = data.observed?.at(-1) ?? {};
  const band = bandForPm25(latest.pm2_5);

  // The +24h prediction is the headline; fall back to whatever the
  // model returned if that horizon is unavailable.
  const headline =
    data.model_predictions?.find((p) => p.horizon === 24) ??
    data.model_predictions?.find((p) => p.pm2_5_pred != null);

  return (
    <>
      <Head
        title={city.city_name ?? "City"}
        subtitle={city.province}
        onClose={onClose}
      />

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {/* current reading */}
        <section>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-2xs font-semibold uppercase tracking-wider text-fg-faint">
              Latest estimate
            </span>
            <SourceBadge
              {...sourceLabel("reanalysis")}
              title="Open-Meteo CAMS reanalysis, not a local ground sensor"
            />
          </div>

          <div
            className="rounded-xl border p-3.5"
            style={{
              borderColor: `${band?.color}40`,
              background: `linear-gradient(135deg, ${band?.color}14, transparent 70%)`,
            }}
          >
            <div className="flex items-end justify-between gap-3">
              <div>
                <div className="flex items-baseline gap-1.5">
                  <span
                    className="font-mono text-4xl font-bold tabular-nums leading-none"
                    style={{ color: band?.color }}
                  >
                    {fmtNumber(latest.pm2_5)}
                  </span>
                  <span className="text-xs text-fg-subtle">{UNIT}</span>
                </div>
                <div
                  className="mt-1.5 text-xs font-semibold"
                  style={{ color: band?.color }}
                >
                  {band?.name ?? "Unknown"}
                </div>
              </div>
              <div className="flex items-center gap-2.5">
                <div className="text-right">
                  <div className="text-2xs uppercase tracking-wider text-fg-faint">
                    AQI
                  </div>
                  <div className="font-mono text-xl font-bold text-fg">
                    {pm25ToAqi(latest.pm2_5) ?? "—"}
                  </div>
                </div>
                <AqiScene
                  aqi={pm25ToAqi(latest.pm2_5)}
                  size={52}
                  isDark={theme !== "light"}
                />
              </div>
            </div>
            <div className="mt-2.5 border-t border-line pt-2 text-2xs text-fg-faint">
              Observed {fmtTime(latest.timestamp)}
            </div>
          </div>
        </section>

        {/* model forecast */}
        {headline ? (
          <section>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-2xs font-semibold uppercase tracking-wider text-fg-faint">
                Our forecast &middot; +{headline.horizon}h
              </span>
              <SourceBadge
                {...sourceLabel("model_prediction")}
                title={`Model version ${headline.model_version}`}
              />
            </div>
            <div className="flex items-center justify-between rounded-xl border border-accent/25 bg-accent/[0.07] p-3">
              <div className="flex items-baseline gap-1.5">
                <span className="font-mono text-2xl font-bold tabular-nums text-accent">
                  {fmtNumber(headline.pm2_5_pred)}
                </span>
                <span className="text-2xs text-fg-subtle">{UNIT}</span>
              </div>
              <div className="text-right text-2xs leading-tight text-fg-subtle">
                <div>{headline.aqi_category}</div>
                <div className="text-fg-faint">
                  valid {fmtTime(headline.valid_time)}
                </div>
              </div>
            </div>
          </section>
        ) : null}

        {/* weather context */}
        <section>
          <div className="mb-2 text-2xs font-semibold uppercase tracking-wider text-fg-faint">
            Conditions
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Metric
              icon={Thermometer}
              label="Temperature"
              value={fmtNumber(latest.temperature_2m, 0)}
              unit="°C"
            />
            <Metric
              icon={Droplets}
              label="Humidity"
              value={fmtNumber(latest.relative_humidity_2m, 0)}
              unit="%"
            />
            <Metric
              icon={Wind}
              label="Wind"
              value={fmtNumber(latest.wind_speed_10m, 1)}
              unit="km/h"
            />
            <Metric
              icon={Gauge}
              label="PM10"
              value={fmtNumber(latest.pm10, 0)}
              unit={UNIT}
            />
          </div>
        </section>

        {/* trend */}
        <section>
          <div className="mb-1 text-2xs font-semibold uppercase tracking-wider text-fg-faint">
            Recent history &amp; forecast
          </div>
          <TrendChart
            observed={data.observed}
            providerForecast={data.provider_forecast}
            modelPredictions={data.model_predictions}
            height={250}
            theme={theme}
          />
          <p className="mt-1 text-2xs leading-relaxed text-fg-faint">
            Grey is the reanalysis estimate, dotted blue is the provider&rsquo;s
            own forecast, teal is our model. They are shown separately on
            purpose &mdash; our prediction is not the same thing as a
            measurement.
          </p>
        </section>

        {/* city facts */}
        <section className="grid grid-cols-2 gap-2 border-t border-line pt-3">
          <Metric
            icon={Users}
            label="Population"
            value={fmtPopulation(city.population)}
          />
          <Metric
            icon={Mountain}
            label="Elevation"
            value={fmtNumber(city.elevation_m, 0)}
            unit="m"
          />
          <div className="col-span-2 rounded-lg border border-line bg-raised p-2.5">
            <div className="text-2xs uppercase tracking-wider text-fg-faint">
              Coordinates
            </div>
            <div className="mt-1 font-mono text-xs text-fg">
              {fmtNumber(city.latitude, 4)}&deg;N,{" "}
              {fmtNumber(city.longitude, 4)}&deg;E
            </div>
          </div>
        </section>
      </div>
    </>
  );
}

function Head({ title, subtitle, onClose }) {
  return (
    <header className="card-head shrink-0">
      <div className="min-w-0">
        <h2 className="truncate text-sm font-bold tracking-tight text-fg">
          {title}
        </h2>
        {subtitle ? <p className="text-xs text-fg-faint">{subtitle}</p> : null}
      </div>
      <button
        type="button"
        onClick={onClose}
        className="rounded-md p-1 text-fg-subtle transition-colors hover:bg-raised hover:text-fg"
        aria-label="Close panel"
      >
        <X size={15} />
      </button>
    </header>
  );
}
