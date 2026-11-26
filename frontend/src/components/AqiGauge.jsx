import { useEffect, useState } from "react";
import { motion } from "framer-motion";

import { AQI_BANDS, AQI_MAX, aqiCategory } from "../lib/aqi";

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

export default function AqiGauge({ aqi, size = 184, stroke = 13 }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const value = Math.max(0, Math.min(aqi ?? 0, AQI_MAX));
  const band = aqiCategory(value);

  const cx = size / 2;
  const cy = size / 2;
  const r = (size - stroke) / 2 - 2;

  // Each band occupies a slice proportional to its AQI width.
  const segments = AQI_BANDS.map((b) => {
    const from = START_ANGLE + (b.lower / AQI_MAX) * SWEEP;
    const to = START_ANGLE + ((b.upper + 1) / AQI_MAX) * SWEEP;
    return { band: b, from, to };
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
        {/* track */}
        <path
          d={arcPath(cx, cy, r, START_ANGLE, START_ANGLE + SWEEP)}
          fill="none"
          stroke="rgb(var(--c-sunken))"
          strokeWidth={stroke}
          strokeLinecap="round"
        />

        {/* band segments — dim until the needle reaches them, so the
            dial reads as "how far along the scale are we" */}
        {segments.map(({ band: b, from, to }) => {
          const reached = value >= b.lower;
          return (
            <motion.path
              key={b.name}
              d={arcPath(cx, cy, r, from, to)}
              fill="none"
              stroke={b.color}
              strokeWidth={stroke}
              strokeLinecap="butt"
              initial={{ opacity: 0 }}
              animate={{ opacity: reached ? 0.95 : 0.22 }}
              transition={{ duration: 0.6, delay: 0.1 }}
            />
          );
        })}

        {/* needle */}
        <motion.line
          x1={needleInner.x}
          y1={needleInner.y}
          x2={needleOuter.x}
          y2={needleOuter.y}
          stroke="rgb(var(--c-fg))"
          strokeWidth={3}
          strokeLinecap="round"
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: mounted ? 1 : 0, scale: 1 }}
          style={{ transformOrigin: `${cx}px ${cy}px` }}
          transition={{ type: "spring", stiffness: 90, damping: 14, delay: 0.3 }}
        />
        <circle cx={cx} cy={cy} r={4} fill="rgb(var(--c-fg))" />
      </svg>

      {/* centred readout */}
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="eyebrow mb-0.5">AQI</span>
        <motion.span
          key={Math.round(value)}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="metric text-[2.6rem]"
          style={{ color: band?.color }}
        >
          {Math.round(value)}
        </motion.span>
        <span
          className="mt-1 max-w-[7.5rem] text-center text-[10px] font-semibold leading-tight"
          style={{ color: band?.color }}
        >
          {band?.abbr === "USG" ? "Unhealthy for Sensitive" : band?.name}
        </span>
      </div>
    </div>
  );
}
