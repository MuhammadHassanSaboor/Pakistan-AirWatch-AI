import { useCallback, useMemo, useState } from "react";
import { motion } from "framer-motion";

import Header from "./components/Header";
import StatTiles from "./components/StatTiles";
import MapView from "./components/MapView";
import CityPanel from "./components/CityPanel";
import DataSourceBanner from "./components/DataSourceBanner";
import { CitySearch, HorizonSelector, Legend } from "./components/Controls";
import {
  DistributionChart,
  ElevationScatter,
  PopulationScatter,
  ProvinceChart,
  TopCitiesChart,
} from "./components/charts";
import { ErrorState, Skeleton, fadeUp } from "./components/primitives";
import Footer from "./components/Footer";

import { aqiCategory } from "./lib/aqi";
import { api } from "./api/client";
import { useApi, usePolling } from "./hooks/useApi";
import { useTheme } from "./hooks/useTheme";

const HORIZONS = [1, 6, 12, 24];

/** Section card with a quiet header, reused for every analytics block
 *  so the page has one repeating rhythm instead of three layouts. */
function Card({ title, subtitle, action, children, delay = 0, className }) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay, ease: [0.22, 1, 0.36, 1] }}
      className={`card card-hover flex flex-col ${className ?? ""}`}
    >
      <header className="card-head">
        <div className="min-w-0">
          <h2 className="card-title truncate">{title}</h2>
          {subtitle ? (
            <p className="mt-0.5 truncate text-xs text-fg-subtle">{subtitle}</p>
          ) : null}
        </div>
        {action}
      </header>
      <div className="min-h-0 flex-1 px-2 pb-3">{children}</div>
    </motion.section>
  );
}

export default function App() {
  const [horizon, setHorizon] = useState(24);
  const [selectedCity, setSelectedCity] = useState(null);
  const [resetSignal, setResetSignal] = useState(0);
  const [bandFilter, setBandFilter] = useState(null);
  const { theme, toggle: toggleTheme, isDark } = useTheme();

  const health = useApi(() => api.health(), []);
  const modelInfo = useApi(() => api.modelInfo(), []);
  const cities = useApi(() => api.cities(), []);
  const legend = useApi(() => api.legend(), []);
  const stats = useApi(() => api.stats(), []);
  const forecast = useApi(() => api.forecast(horizon), [horizon]);

  const history = useApi(() => api.history(selectedCity, 7), [selectedCity], {
    enabled: Boolean(selectedCity),
  });

  usePolling(() => {
    health.refetch();
    stats.refetch();
  }, 300000);

  const refreshAll = useCallback(() => {
    health.refetch();
    stats.refetch();
    forecast.refetch();
    if (selectedCity) history.refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCity]);

  // Memoised so the empty-array fallback is not a new array on every
  // render, which would defeat every downstream useMemo.
  const features = useMemo(
    () => forecast.data?.features ?? [],
    [forecast.data],
  );

  // Clicking a category in the KPI spread narrows the map to that band.
  // The band is recomputed here rather than read from the API field, so
  // the filter can never disagree with the colour the marker is drawn
  // in -- both come from the same breakpoint table.
  const visibleFeatures = useMemo(() => {
    if (!bandFilter) return features;
    return features.filter((f) => aqiCategory(f.aqi_us)?.name === bandFilter);
  }, [features, bandFilter]);

  // Only treat the API as down when the two cheapest calls BOTH fail.
  // One slow endpoint should degrade one panel, not blank the page.
  const apiDown = Boolean(health.error) && Boolean(cities.error);

  const selectedCityName = useMemo(
    () =>
      cities.data?.cities?.find((c) => c.city_id === selectedCity)?.city_name ??
      null,
    [cities.data, selectedCity],
  );

  if (apiDown) {
    return (
      <div className="flex min-h-screen flex-col">
        <Header
          health={null}
          modelInfo={null}
          onRefresh={refreshAll}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
        <main className="flex flex-1 items-center justify-center p-6">
          <div className="card w-full max-w-lg">
            <ErrorState error={health.error} onRetry={refreshAll} />
            <div className="space-y-3 px-6 pb-6 text-xs leading-relaxed text-fg-subtle">
              <div className="divider" />
              <p className="pt-2 font-medium text-fg-muted">Start the API:</p>
              <pre className="overflow-x-auto rounded-lg bg-sunken p-3 font-mono text-[11px] text-accent">
                {`conda activate airwatch
python -m src.serving.app`}
              </pre>
              <p>
                It should print{" "}
                <span className="font-mono text-fg-muted">
                  Running on http://127.0.0.1:5001
                </span>
                . If another program owns that port, change{" "}
                <span className="font-mono text-fg-muted">API_PORT</span> in{" "}
                <span className="font-mono text-fg-muted">.env</span> — the
                frontend proxy reads the same value.
              </p>
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <Header
        health={health.data}
        modelInfo={modelInfo.data}
        onRefresh={refreshAll}
        refreshing={forecast.loading || stats.loading}
        theme={theme}
        onToggleTheme={toggleTheme}
      />

      <main className="mx-auto w-full max-w-[1680px] flex-1 space-y-4 px-4 py-5 sm:px-6 lg:py-6">
        <DataSourceBanner health={health.data} />

        <StatTiles stats={stats.data} loading={stats.loading} isDark={isDark} />

        {/* ── map: the hero ── */}
        <motion.section
          variants={fadeUp}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_370px]"
        >
          {/* Map controls sit ON the map rather than in a toolbar above
              it, so the hero keeps its full frame. */}
          <div className="card card-hover overflow-hidden p-1.5">
            <div className="h-[clamp(480px,66vh,820px)] w-full">
              {forecast.error ? (
                <ErrorState error={forecast.error} onRetry={forecast.refetch} />
              ) : (
                <MapView
                  features={visibleFeatures}
                  loading={forecast.loading}
                  selectedCity={selectedCity}
                  onSelectCity={setSelectedCity}
                  resetSignal={resetSignal}
                  onReset={() => {
                    setSelectedCity(null);
                    setBandFilter(null);
                    setResetSignal((n) => n + 1);
                  }}
                  theme={theme}
                  horizon={horizon}
                />
              )}
            </div>
          </div>

          <div className="flex min-h-0 flex-col gap-4">
            <motion.div
              variants={fadeUp}
              className="card flex flex-col gap-3.5 p-4"
            >
              <div>
                <span className="eyebrow">Forecast horizon</span>
                <div className="mt-2">
                  <HorizonSelector
                    horizons={HORIZONS}
                    value={horizon}
                    onChange={setHorizon}
                    disabled={forecast.loading}
                  />
                </div>
              </div>

              <div className="divider" />

              {/* Only shown while a category filter is active, and it is
                  the control that clears it: a map quietly showing 22 of
                  134 cities with no visible reason is a bug report. */}
              {bandFilter ? (
                <>
                  <div>
                    <span className="eyebrow">Showing category</span>
                    <button
                      type="button"
                      onClick={() => setBandFilter(null)}
                      className="btn btn-accent mt-2 w-full justify-between"
                      title="Clear the filter and show every city"
                    >
                      <span className="truncate">{bandFilter}</span>
                      <span className="shrink-0 font-mono">
                        {visibleFeatures.length} &times;
                      </span>
                    </button>
                  </div>
                  <div className="divider" />
                </>
              ) : null}

              <div>
                <span className="eyebrow">Find a city</span>
                <div className="mt-2">
                  <CitySearch
                    cities={cities.data?.cities}
                    onSelect={setSelectedCity}
                    selectedCity={selectedCity}
                    fullWidth
                  />
                </div>
                {selectedCityName ? (
                  <p className="mt-2 text-xs text-fg-muted">
                    Showing{" "}
                    <span className="font-medium text-accent">
                      {selectedCityName}
                    </span>
                  </p>
                ) : null}
              </div>
            </motion.div>

            {selectedCity ? (
              <CityPanel
                cityId={selectedCity}
                data={history.data}
                loading={history.loading}
                error={history.error}
                onClose={() => setSelectedCity(null)}
                onRetry={history.refetch}
                theme={theme}
              />
            ) : (
              <motion.div variants={fadeUp} className="card">
                <header className="card-head">
                  <h2 className="card-title">Air quality scale</h2>
                </header>
                <Legend
                  bands={legend.data?.bands}
                  standard={legend.data?.standard}
                />
              </motion.div>
            )}
          </div>
        </motion.section>

        {/* ── analytics ── */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Card
            title="Most polluted cities"
            subtitle={`Forecast +${horizon}h · click a bar to inspect`}
            delay={0.05}
          >
            {forecast.loading ? (
              <Skeleton className="m-2 h-72" />
            ) : (
              <TopCitiesChart
                features={features}
                topN={12}
                height={330}
                onSelect={setSelectedCity}
                theme={theme}
              />
            )}
          </Card>

          <Card
            title="Average by province"
            subtitle="All seven administrative units"
            delay={0.1}
          >
            {forecast.loading ? (
              <Skeleton className="m-2 h-72" />
            ) : (
              <ProvinceChart features={features} height={330} theme={theme} />
            )}
          </Card>

          <Card
            title="Distribution"
            subtitle={`${features.length} cities by EPA category`}
            delay={0.15}
          >
            {forecast.loading ? (
              <Skeleton className="m-2 h-72" />
            ) : (
              <DistributionChart
                features={features}
                height={330}
                theme={theme}
              />
            )}
          </Card>
        </div>

        {/* ── relationships: what the bar charts cannot show ── */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card
            title="Does city size drive pollution?"
            subtitle="Population versus forecast PM2.5 · log scale · click a point"
            delay={0.2}
          >
            {forecast.loading ? (
              <Skeleton className="m-2 h-72" />
            ) : (
              <PopulationScatter
                features={features}
                height={330}
                onSelect={setSelectedCity}
                theme={theme}
              />
            )}
          </Card>

          <Card
            title="Altitude and air quality"
            subtitle="Highland cities sit in thinner, better-ventilated air"
            delay={0.25}
          >
            {forecast.loading ? (
              <Skeleton className="m-2 h-72" />
            ) : (
              <ElevationScatter
                features={features}
                height={330}
                onSelect={setSelectedCity}
                theme={theme}
              />
            )}
          </Card>
        </div>
      </main>

      <Footer modelInfo={modelInfo.data} />
    </div>
  );
}
