import { useCallback, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { BarChart3, Layers3, ListOrdered, Map as MapIcon } from "lucide-react";

import Header from "./components/Header";
import StatTiles from "./components/StatTiles";
import MapView from "./components/MapView";
import CityPanel from "./components/CityPanel";
import { CitySearch, HorizonSelector, LayerControls, Legend } from "./components/Controls";
import { DistributionChart, ProvinceChart, TopCitiesChart } from "./components/charts";
import { ErrorState, Panel, PanelHead, Skeleton } from "./components/primitives";
import Footer from "./components/Footer";

import { api } from "./api/client";
import { useApi, usePolling } from "./hooks/useApi";

const HORIZONS = [1, 6, 12, 24];

export default function App() {
  const [horizon, setHorizon] = useState(24);
  const [selectedCity, setSelectedCity] = useState(null);
  const [showLabels, setShowLabels] = useState(true);
  const [resetSignal, setResetSignal] = useState(0);

  const health = useApi(() => api.health(), []);
  const modelInfo = useApi(() => api.modelInfo(), []);
  const cities = useApi(() => api.cities(), []);
  const legend = useApi(() => api.legend(), []);
  const stats = useApi(() => api.stats(), []);
  const forecast = useApi(() => api.forecast(horizon), [horizon]);

  const history = useApi(
    () => api.history(selectedCity, 7),
    [selectedCity],
    { enabled: Boolean(selectedCity) },
  );

  // The upstream feed updates hourly, so a 5-minute poll keeps the
  // status chip honest without hammering our own API.
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

  const features = forecast.data?.features ?? [];
  const apiDown = health.error && cities.error;

  const selectedCityName = useMemo(
    () =>
      cities.data?.cities?.find((c) => c.city_id === selectedCity)?.city_name ??
      null,
    [cities.data, selectedCity],
  );

  if (apiDown) {
    return (
      <div className="flex min-h-screen flex-col">
        <Header health={null} modelInfo={null} onRefresh={refreshAll} />
        <main className="flex flex-1 items-center justify-center p-6">
          <Panel className="max-w-md">
            <ErrorState
              error={health.error}
              onRetry={refreshAll}
            />
            <div className="border-t border-white/[0.06] px-6 py-4 text-xs leading-relaxed text-ink-400">
              <p className="mb-2 font-medium text-ink-300">Start the API:</p>
              <pre className="overflow-x-auto rounded-lg bg-ink-950 p-3 font-mono text-[11px] text-accent-soft">
{`conda activate airwatch
python -m src.serving.app`}
              </pre>
            </div>
          </Panel>
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
      />

      <main className="mx-auto w-full max-w-[1800px] flex-1 space-y-4 px-4 py-4 sm:px-6">
        <StatTiles stats={stats.data} loading={stats.loading} />

        {/* ── map + side panel ── */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_360px]">
          <Panel className="overflow-hidden" delay={0.05}>
            <PanelHead title="National forecast map" icon={MapIcon}>
              <HorizonSelector
                horizons={HORIZONS}
                value={horizon}
                onChange={setHorizon}
                disabled={forecast.loading}
              />
            </PanelHead>

            <div className="flex flex-wrap items-center gap-2 border-b border-white/[0.06] px-4 py-2">
              <CitySearch
                cities={cities.data?.cities}
                onSelect={setSelectedCity}
                selectedCity={selectedCity}
              />
              <LayerControls
                showLabels={showLabels}
                onToggleLabels={() => setShowLabels((v) => !v)}
                onResetView={() => {
                  setSelectedCity(null);
                  setResetSignal((n) => n + 1);
                }}
              />
              {selectedCityName ? (
                <motion.span
                  initial={{ opacity: 0, scale: 0.94 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="chip !border-accent/35 !bg-accent/12 !text-accent-soft"
                >
                  {selectedCityName}
                </motion.span>
              ) : null}
            </div>

            <div className="h-[clamp(380px,56vh,680px)]">
              {forecast.error ? (
                <ErrorState error={forecast.error} onRetry={forecast.refetch} />
              ) : (
                <MapView
                  features={features}
                  loading={forecast.loading}
                  selectedCity={selectedCity}
                  onSelectCity={setSelectedCity}
                  showLabels={showLabels}
                  resetSignal={resetSignal}
                />
              )}
            </div>
          </Panel>

          <div className="flex min-h-0 flex-col gap-4">
            {selectedCity ? (
              <CityPanel
                cityId={selectedCity}
                data={history.data}
                loading={history.loading}
                error={history.error}
                onClose={() => setSelectedCity(null)}
                onRetry={history.refetch}
              />
            ) : (
              <Panel delay={0.1}>
                <PanelHead title="AQI scale" icon={Layers3} />
                <Legend
                  bands={legend.data?.bands}
                  standard={legend.data?.standard}
                />
                <div className="border-t border-white/[0.06] px-4 py-3">
                  <p className="text-[11px] leading-relaxed text-ink-400">
                    Click any city on the map to see its recent history, the
                    provider&rsquo;s forecast and our model&rsquo;s prediction
                    side by side.
                  </p>
                </div>
              </Panel>
            )}

            <Panel delay={0.15}>
              <PanelHead title="Average by province" icon={BarChart3} />
              <div className="px-2 pb-2">
                {forecast.loading ? (
                  <Skeleton className="m-2 h-48" />
                ) : (
                  <ProvinceChart features={features} height={240} />
                )}
              </div>
            </Panel>
          </div>
        </div>

        {/* ── analytics row ── */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel delay={0.2}>
            <PanelHead title={`Most polluted cities · +${horizon}h`} icon={ListOrdered}>
              <span className="chip">click a bar to inspect</span>
            </PanelHead>
            <div className="px-2 pb-2">
              {forecast.loading ? (
                <Skeleton className="m-2 h-64" />
              ) : (
                <TopCitiesChart
                  features={features}
                  topN={12}
                  height={300}
                  onSelect={setSelectedCity}
                />
              )}
            </div>
          </Panel>

          <Panel delay={0.25}>
            <PanelHead title="Distribution across cities" icon={BarChart3} />
            <div className="px-2 pb-2">
              {forecast.loading ? (
                <Skeleton className="m-2 h-64" />
              ) : (
                <DistributionChart features={features} height={300} />
              )}
            </div>
          </Panel>
        </div>
      </main>

      <Footer modelInfo={modelInfo.data} />
    </div>
  );
}
