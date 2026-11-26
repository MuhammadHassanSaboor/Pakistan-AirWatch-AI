import { useEffect, useState } from "react";
import { motion } from "framer-motion";

import { AQI_BANDS, AQI_MAX, aqiCategory, textOn } from "../lib/aqi";

/**
 * Radial AQI gauge.
 *
 * A bare number tells you "61". A gauge tells you "61, which is two
 * bands up a six-band scale that runs to 500" — position and severity
 * in one glance, without reading a legend.
 *
 * The arc is segmented by the real AQI bands rather than drawn as a
 * smooth gradient, so the geometry encodes the standard instead of
 * merely decorating it. Band widths are proportional to their actual
 * AQI ranges, which is why Good (50 wide) is visibly narrower than
 * Hazardous (200 wide).
 */

const START_ANGLE = 135; // degrees, measured clockwise from 3 o'clock
const SWEEP = 270; // a 270° dial leaves room for the value beneath

function polar(cx, cy, r, angleDeg) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function arcPath(cx, cy, r, startDeg, endDeg) {
  const start = polar(cx, cy, r, endDeg);
  const end = polar(cx, cy, r, startDeg);
  const largeArc = endDeg - startDeg <= 180 ? 0 : 1;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 0 ${end.x} ${end.y}`;
}

export default function AqiGauge({ aqi, size = 184, stroke = 14 }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const value = Math.max(0, Math.min(aqi ?? 0, AQI_MAX));
  const band = aqiCategory(value);

  const cx = size / 2;
  const cy = size / 2;
  const r = (size - stroke) / 2 - 2;

  // Each band occupies a slice proportional to its AQI width. A small
  // gap between slices keeps adjacent colours from blending into one
  // smear, which is what made the scale hard to count.
  const GAP = 1.4;
  const segments = AQI_BANDS.map((b) => {
    const from = START_ANGLE + (b.lower / AQI_MAX) * SWEEP;
    const to = START_ANGLE + ((b.upper + 1) / AQI_MAX) * SWEEP;
    return { band: b, from: from + GAP / 2, to: to - GAP / 2 };
  });

  const needleAngle = START_ANGLE + (value / AQI_MAX) * SWEEP;
  const needleOuter = polar(cx, cy, r + stroke / 2 + 3, needleAngle);
  const needleInner = polar(cx, cy, r - stroke / 2 - 3, needleAngle);

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={`Air quality index ${Math.round(value)}, ${band?.name}`}
      >
        {/* Track. Drawn in a line colour rather than the sunken surface
            so the dial has a visible body on a photograph, where the
            card's own background is not behind it. */}
        <path
          d={arcPath(cx, cy, r, START_ANGLE, START_ANGLE + SWEEP)}
          fill="none"
          stroke="rgb(var(--c-line-strong) / 0.5)"
          strokeWidth={stroke}
          strokeLinecap="round"
        />

        {/* Band segments.
            Progress used to be shown by fading unreached bands to 22%
            opacity, which fails in opposite ways per theme: on dark
            they sink into the background, on light they look like a
            printing error. Thickness carries it instead -- unreached
            bands are drawn thin, reached bands full width -- so every
            colour stays fully saturated and fully visible in both
            themes, and the dial still reads as "how far along are we". */}
        {segments.map(({ band: b, from, to }) => {
          const reached = value >= b.lower;
          return (
            <motion.path
              key={b.name}
              d={arcPath(cx, cy, r, from, to)}
              fill="none"
              stroke={b.color}
              strokeLinecap="butt"
              initial={{ opacity: 0, strokeWidth: stroke * 0.45 }}
              animate={{
                opacity: 1,
                strokeWidth: reached ? stroke : stroke * 0.45,
              }}
              transition={{ duration: 0.6, delay: 0.1 + b.lower / 1200 }}
            />
          );
        })}

        {/* Needle, with a halo behind it. The needle always lands ON a
            band colour, and a bare foreground-coloured line is lost
            against Hazardous maroon in dark or Moderate yellow in
            light; the halo guarantees it separates from both. */}
        <motion.line
          x1={needleInner.x}
          y1={needleInner.y}
          x2={needleOuter.x}
          y2={needleOuter.y}
          stroke="rgb(var(--c-surface))"
          strokeWidth={6.5}
          strokeLinecap="butt"
          initial={{ opacity: 0 }}
          animate={{ opacity: mounted ? 0.95 : 0 }}
          transition={{ duration: 0.4, delay: 0.3 }}
        />
        <motion.line
          x1={needleInner.x}
          y1={needleInner.y}
          x2={needleOuter.x}
          y2={needleOuter.y}
          stroke="rgb(var(--c-fg))"
          strokeWidth={3}
          strokeLinecap="butt"
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: mounted ? 1 : 0, scale: 1 }}
          style={{ transformOrigin: `${cx}px ${cy}px` }}
          transition={{
            type: "spring",
            stiffness: 90,
            damping: 14,
            delay: 0.3,
          }}
        />
        {/* No hub. A pivot dot belongs on a dial whose needle sweeps
            from the centre; this needle is a tick at the rim, so the
            dot was just two circles parked behind the AQI numeral. */}
      </svg>

      {/* centred readout */}
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="eyebrow mb-0.5">AQI</span>
        {/* Foreground, not band colour: as text, Moderate is 1.89:1 on
            white and Hazardous 1.70:1 on dark, so the readout vanished
            at one end of the scale or the other. The band is named on
            the filled chip below, which reads at every step. */}
        <motion.span
          key={Math.round(value)}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="metric text-[2.6rem] text-fg"
        >
          {Math.round(value)}
        </motion.span>
        <span
          className="mt-2 max-w-[8.5rem] rounded-lg px-2 py-1 text-center
                     text-xs font-bold leading-tight shadow-sm"
          style={{ background: band?.color, color: textOn(band?.color) }}
        >
          {band?.abbr === "USG" ? "Sensitive groups" : band?.name}
        </span>
      </div>
    </div>
  );
}
