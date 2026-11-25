import { useCallback, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  BarChart3,
  Layers3,
  ListOrdered,
  Map as MapIcon,
  SlidersHorizontal,
} from "lucide-react";

import Header from "./components/Header";
import StatTiles from "./components/StatTiles";
import MapView from "./components/MapView";
import CityPanel from "./components/CityPanel";
import DataSourceBanner from "./components/DataSourceBanner";
import {
  CitySearch,
  HorizonSelector,
  LayerControls,
  Legend,
} from "./components/Controls";
import {
  DistributionChart,
  ProvinceChart,
  TopCitiesChart,
} from "./components/charts";
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

  const history = useApi(() => api.history(selectedCity, 7), [selectedCity], {
    enabled: Boolean(selectedCity),
  });

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

  // Only treat the API as down when the two cheapest, most reliable
  // calls BOTH fail. A single slow endpoint should degrade one panel,
  // not blank the whole dashboard.
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
        <Header health={null} modelInfo={null} onRefresh={refreshAll} />
        <main className="flex flex-1 items-center justify-center p-6">
          <Panel className="w-full max-w-lg">
            <ErrorState error={health.error} onRetry={refreshAll} />
            <div className="space-y-3 border-t border-white/[0.06] px-6 py-5 text-xs leading-relaxed text-ink-400">
              <p className="font-medium text-ink-300">Start the API:</p>
              <pre className="overflow-x-auto rounded-lg bg-ink-950 p-3 font-mono text-[11px] text-accent-soft">
                {`conda activate airwatch
python -m src.serving.app`}
              </pre>
              <p>
                It should print{" "}
                <span className="font-mono text-ink-300">
                  Running on http://127.0.0.1:5001
                </span>
                . If another program already owns that port, change{" "}
                <span className="font-mono text-ink-300">API_PORT</span> in{" "}
                <span className="font-mono text-ink-300">.env</span> — the
                frontend proxy reads the same value.
              </p>
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

      <main className="mx-auto w-full max-w-[1800px] flex-1 space-y-4 px-4 py-5 sm:px-6">
        <DataSourceBanner health={health.data} />

        <StatTiles stats={stats.data} loading={stats.loading} />

        {/* ── map + side rail ── */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <Panel className="flex flex-col overflow-hidden" delay={0.05}>
            <PanelHead title="National forecast map" icon={MapIcon}>
              <HorizonSelector
                horizons={HORIZONS}
                value={horizon}
                onChange={setHorizon}
                disabled={forecast.loading}
              />
            </PanelHead>

            <div className="flex flex-wrap items-center gap-2 border-b border-white/[0.06] px-4 py-2.5">
              <SlidersHorizontal size={13} className="text-ink-600" />
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
              <span className="ml-auto hidden text-[11px] text-ink-600 lg:inline">
                click any city for detail
              </span>
            </div>

            {/* A fixed-ratio box, not a percentage of the viewport.
                Leaflet measures its container once on init; a height
                that depends on content can still be settling at that
                moment, which is how maps end up rendering grey. */}
            <div className="h-[clamp(440px,60vh,720px)] w-full">
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
                <PanelHead title="Air quality scale" icon={Layers3} />
                <Legend
                  bands={legend.data?.bands}
                  standard={legend.data?.standard}
                />
                <div className="border-t border-white/[0.06] px-4 py-3">
                  <p className="text-[11px] leading-relaxed text-ink-400">
                    Select a city on the map to compare its recent history, the
                    provider&rsquo;s own forecast and our model&rsquo;s
                    prediction side by side.
                  </p>
                </div>
              </Panel>
            )}

            <Panel delay={0.15}>
              <PanelHead title="Average by province" icon={BarChart3} />
              <div className="px-2 pb-3 pt-1">
                {forecast.loading ? (
                  <Skeleton className="m-2 h-52" />
                ) : (
                  <ProvinceChart features={features} height={250} />
                )}
              </div>
            </Panel>
          </div>
        </div>

        {/* ── analytics ── */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel delay={0.2}>
            <PanelHead
              title={`Most polluted · +${horizon}h forecast`}
              icon={ListOrdered}
            >
              <span className="chip">click a bar to inspect</span>
            </PanelHead>
            <div className="px-2 pb-3 pt-1">
              {forecast.loading ? (
                <Skeleton className="m-2 h-64" />
              ) : (
                <TopCitiesChart
                  features={features}
                  topN={12}
                  height={310}
                  onSelect={setSelectedCity}
                />
              )}
            </div>
          </Panel>

          <Panel delay={0.25}>
            <PanelHead title="Distribution across cities" icon={BarChart3}>
              <span className="chip">{features.length} cities</span>
            </PanelHead>
            <div className="px-2 pb-3 pt-1">
              {forecast.loading ? (
                <Skeleton className="m-2 h-64" />
              ) : (
                <DistributionChart features={features} height={310} />
              )}
            </div>
          </Panel>
        </div>
      </main>

      <Footer modelInfo={modelInfo.data} />
    </div>
  );
}
