import { useMemo } from "react";

import { AqiSceneChip } from "./AqiScene";
import { bandForPm25, textOn } from "../lib/aqi";
import { UNIT, fmtPopulation } from "../lib/format";

/**
 * A continuously scrolling row of city forecasts beneath the map.
 *
 * This replaced per-marker Leaflet tooltips, and before that a single
 * static inspector. Tooltips could not work: they open on mouseover
 * and close on mouseout, but when the forecast reloads every marker is
 * rebuilt under a stationary cursor, so the new one opens while the
 * old one is destroyed before it can close — leaving a scatter of
 * cards stranded across the map that each needed a click to dismiss.
 *
 * A ticker is better than the static strip it also replaces: the strip
 * showed one city only when you were already pointing at it, so it
 * told you nothing while you were reading the map. This shows the
 * country continuously, and the worst air first.
 *
 * How the loop is seamless
 * ------------------------
 * The track holds the list twice and translates by exactly -50%. At
 * the end of the animation the second copy sits precisely where the
 * first began, so the restart is invisible — no snap, no gap, and no
 * JavaScript watching scroll position.
 *
 * The spacing is a margin on each card, not a flex `gap`, and the
 * track has no padding. Both matter: with 2N cards a flex gap puts
 * 2N-1 gaps in the track, so the two halves differ by exactly one gap
 * and -50% lands slightly off, which shows up as a small jump once per
 * cycle. A per-card margin makes every copy exactly N*(card+margin)
 * wide, and half of that is exact.
 *
 * The whole thing is one CSS keyframe on one element. Animating 40
 * cards individually, or driving the offset from JavaScript, would put
 * work on the main thread every frame; a single composited transform
 * costs nothing after the first frame, which matters because this
 * animates forever while people scroll past it.
 */

/** Enough to fill any screen twice over without rendering all 134. */
const MAX_CARDS = 18;

export default function CityTicker({ features, horizon, onSelect, loading }) {
  const cards = useMemo(() => {
    const rows = (features ?? [])
      .filter((f) => f.pm2_5_pred != null)
      // Worst first: the cities that matter lead the row rather than
      // whichever happened to come back first from the API.
      .sort((a, b) => b.pm2_5_pred - a.pm2_5_pred)
      .slice(0, MAX_CARDS);
    return rows;
  }, [features]);

  if (loading && cards.length === 0) {
    return (
      <div className="flex h-[74px] items-center gap-3 overflow-hidden border-t border-line bg-surface px-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="skeleton h-[54px] w-56 shrink-0 rounded-xl" />
        ))}
      </div>
    );
  }

  if (cards.length === 0) return null;

  // Rendered twice; the second copy is what the -50% translate lands on.
  const track = [...cards, ...cards];

  return (
    <div
      className="group relative h-[74px] overflow-hidden border-t border-line bg-surface"
      // The row never stops being a list of links, so it is labelled as
      // one for anyone not seeing it move.
      aria-label="Forecast by city"
    >
      {/* Edge fades, so cards enter and leave instead of being cut off
          mid-word at the container edge. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-y-0 left-0 z-10 w-10"
        style={{
          background:
            "linear-gradient(to right, rgb(var(--c-surface)), transparent)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-y-0 right-0 z-10 w-10"
        style={{
          background:
            "linear-gradient(to left, rgb(var(--c-surface)), transparent)",
        }}
      />

      <div
        className="ticker-track flex h-full w-max items-center
                   group-hover:[animation-play-state:paused]"
        style={{ animationDuration: `${cards.length * 3.2}s` }}
      >
        {track.map((city, i) => (
          <TickerCard
            key={`${city.city_id}-${i}`}
            city={city}
            horizon={horizon}
            onSelect={onSelect}
            // The duplicates are decorative; only the first pass is
            // announced, or every city is read out twice.
            hidden={i >= cards.length}
          />
        ))}
      </div>
    </div>
  );
}

function TickerCard({ city, horizon, onSelect, hidden }) {
  const band = bandForPm25(city.pm2_5_pred);

  return (
    <button
      type="button"
      onClick={() => onSelect?.(city.city_id)}
      aria-hidden={hidden || undefined}
      tabIndex={hidden ? -1 : 0}
      title={`${city.city_name} · ${band?.name} · click to open`}
      className="mr-2.5 flex h-[54px] shrink-0 items-center gap-2.5 rounded-xl
                 border border-line bg-raised px-2.5 text-left transition-all
                 duration-200 hover:-translate-y-0.5 hover:border-accent/40
                 hover:shadow-float active:scale-[0.98]"
    >
      <AqiSceneChip aqi={city.aqi_us} size={30} />

      <span className="min-w-0">
        <span className="block truncate text-[13px] font-semibold leading-tight text-fg">
          {city.city_name ?? city.city_id}
        </span>
        <span className="block truncate text-2xs leading-tight text-fg-subtle">
          {city.province}
        </span>
      </span>

      <span className="flex items-baseline gap-0.5 pl-1">
        <span className="metric text-lg text-fg">
          {city.pm2_5_pred?.toFixed(0)}
        </span>
        <span className="text-[9px] text-fg-faint">{UNIT}</span>
      </span>

      <span className="flex flex-col items-end gap-1 pl-1">
        <span
          className="whitespace-nowrap rounded-md px-1.5 py-px text-[10px] font-bold"
          style={{ background: band?.color, color: textOn(band?.color) }}
        >
          {band?.abbr}
        </span>
        <span className="whitespace-nowrap font-mono text-[10px] text-fg-subtle">
          AQI {city.aqi_us} · +{horizon}h
        </span>
      </span>

      <span className="hidden whitespace-nowrap border-l border-line pl-2.5 text-2xs text-fg-faint xl:block">
        {fmtPopulation(city.population)}
      </span>
    </button>
  );
}
