import { useEffect, useMemo, useState } from "react";

import { aqiCategory } from "../lib/aqi";

/**
 * Animated AQI condition scene.
 *
 * Weather apps lean on illustration because a glyph communicates
 * "stormy" faster than the word does. The same applies to air quality,
 * which has no everyday visual vocabulary: most people cannot picture
 * what 180 µg/m³ looks like, but they immediately read a dimmed sun
 * behind thickening haze.
 *
 * Built as inline SVG rather than photography on purpose:
 *   - crisp at any size, where a bitmap would need several exports
 *   - tints to the active theme instead of fighting it
 *   - animates per-layer (drifting haze, rising particles, pulsing sun)
 *   - no network request, no licence, no attribution burden
 *
 * Each of the six EPA bands gets its own composition. The visual
 * language is consistent and monotonic, so severity is legible even
 * without the number: as AQI climbs the sun dims and sinks behind more
 * haze layers, particle count and size rise, and the palette shifts
 * from clear blue through amber to deep maroon.
 *
 * Performance
 * -----------
 * Two rules keep a page full of these cheap, and both were learned
 * from this one being the main cause of a janky page:
 *
 *  1. Every loop is a CSS keyframe, never a JS-driven one. Framer
 *     Motion animates by writing styles from a rAF callback, so nine
 *     scenes with thirty particles apiece meant hundreds of elements
 *     being restyled from JavaScript every frame, on the same thread
 *     that handles scrolling. CSS animations run on the compositor and
 *     cost the main thread nothing once started.
 *
 *  2. Detail scales with rendered size. A 20px legend chip was drawing
 *     thirty animated particles that occupy a fraction of a pixel
 *     each. Below 44px the scene is drawn static, and the result is
 *     indistinguishable -- there is nothing there to see moving.
 */

/* Per-band scene parameters. Every value moves in one direction as
   severity increases, so the series reads as a progression. */
const SCENES = {
  Good: {
    sky: ["#0EA5E9", "#7DD3FC"],
    skyDark: ["#075985", "#0C4A6E"],
    sun: "#FDE047",
    sunY: 30,
    sunGlow: 1,
    haze: 0,
    particles: 4,
    particleSize: 1.3,
    particleColor: "#BAE6FD",
  },
  Moderate: {
    sky: ["#38BDF8", "#FDE68A"],
    skyDark: ["#0C4A6E", "#78350F"],
    sun: "#FACC15",
    sunY: 32,
    sunGlow: 0.85,
    haze: 1,
    particles: 7,
    particleSize: 1.6,
    particleColor: "#FDE68A",
  },
  "Unhealthy for Sensitive Groups": {
    sky: ["#FBBF24", "#FB923C"],
    skyDark: ["#78350F", "#7C2D12"],
    sun: "#FB923C",
    sunY: 36,
    sunGlow: 0.6,
    haze: 2,
    particles: 10,
    particleSize: 1.9,
    particleColor: "#FED7AA",
  },
  Unhealthy: {
    sky: ["#F87171", "#EF4444"],
    skyDark: ["#7F1D1D", "#881337"],
    sun: "#F87171",
    sunY: 40,
    sunGlow: 0.42,
    haze: 3,
    particles: 13,
    particleSize: 2.2,
    particleColor: "#FECACA",
  },
  "Very Unhealthy": {
    sky: ["#A855F7", "#7E22CE"],
    skyDark: ["#4C1D95", "#581C87"],
    sun: "#C084FC",
    sunY: 45,
    sunGlow: 0.26,
    haze: 4,
    particles: 16,
    particleSize: 2.5,
    particleColor: "#E9D5FF",
  },
  Hazardous: {
    sky: ["#881337", "#4C0519"],
    skyDark: ["#4C0519", "#27060F"],
    sun: "#9F1239",
    sunY: 52,
    sunGlow: 0.12,
    haze: 5,
    particles: 18,
    particleSize: 2.9,
    particleColor: "#FDA4AF",
  },
};

/** Below this the scene is drawn static: there is nothing visible to
 *  animate at chip size, and the cost is the same as at full size. */
const ANIMATE_ABOVE = 44;

/** Deterministic pseudo-random so particles don't re-scatter on every
 *  render — a jittering scene reads as a glitch, not as motion. */
function seeded(i, salt = 1) {
  const x = Math.sin(i * 12.9898 * salt) * 43758.5453;
  return x - Math.floor(x);
}

/**
 * Read the live theme straight from the <html data-theme> attribute.
 *
 * The scenes are drawn with their own palette rather than CSS tokens,
 * so they cannot inherit the theme automatically. Threading an isDark
 * prop down to every call site is exactly the kind of plumbing that
 * gets forgotten and leaves one component stuck in the wrong palette,
 * so each scene observes the attribute instead and is always correct.
 */
function useIsDark(override) {
  const [dark, setDark] = useState(() => {
    if (typeof document === "undefined") return true;
    return document.documentElement.dataset.theme !== "light";
  });

  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const el = document.documentElement;
    const read = () => setDark(el.dataset.theme !== "light");
    read();
    const obs = new MutationObserver(read);
    obs.observe(el, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);

  return typeof override === "boolean" ? override : dark;
}

export default function AqiScene({ aqi, size = 128, isDark: isDarkProp }) {
  const isDark = useIsDark(isDarkProp);
  const band = aqiCategory(aqi ?? 0);
  const scene = SCENES[band?.name] ?? SCENES.Good;
  const animate = size >= ANIMATE_ABOVE;

  const particles = useMemo(() => {
    if (!animate) {
      // Static scenes still show particulate, just fewer of it and
      // without motion: it is texture at this size, not information.
      return Array.from({ length: Math.min(5, scene.particles) }, (_, i) => ({
        id: i,
        x: 12 + seeded(i, 1) * 76,
        y: 58 + seeded(i, 2) * 34,
        r: scene.particleSize * 0.9,
      }));
    }
    return Array.from({ length: scene.particles }, (_, i) => ({
      id: i,
      x: 8 + seeded(i, 1) * 84,
      y: 55 + seeded(i, 2) * 42,
      r: scene.particleSize * (0.6 + seeded(i, 3) * 0.8),
      delay: -seeded(i, 4) * 8,
      duration: 5 + seeded(i, 5) * 5,
    }));
  }, [scene, animate]);

  const hazeBands = useMemo(
    () =>
      Array.from({ length: scene.haze }, (_, i) => ({
        id: i,
        y: 52 + i * 9,
        opacity: 0.12 + i * 0.07,
        duration: 9 + i * 2.5,
        delay: -i * 1.4,
      })),
    [scene],
  );

  const [skyTop, skyBottom] = isDark ? scene.skyDark : scene.sky;
  const uid = `aqi-${band?.name?.replace(/\s+/g, "-") ?? "none"}-${isDark ? "d" : "l"}`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      role="img"
      aria-label={`Air quality condition: ${band?.name}`}
      className="select-none"
    >
      <defs>
        <linearGradient id={`${uid}-sky`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={skyTop} />
          <stop offset="100%" stopColor={skyBottom} />
        </linearGradient>

        <radialGradient id={`${uid}-sunglow`}>
          <stop offset="0%" stopColor={scene.sun} stopOpacity={scene.sunGlow} />
          <stop offset="70%" stopColor={scene.sun} stopOpacity={0} />
        </radialGradient>

        <linearGradient id={`${uid}-ground`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={skyBottom} stopOpacity="0" />
          <stop offset="100%" stopColor={skyBottom} stopOpacity="0.65" />
        </linearGradient>

        <clipPath id={`${uid}-clip`}>
          <circle cx="50" cy="50" r="48" />
        </clipPath>
      </defs>

      <g clipPath={`url(#${uid}-clip)`}>
        <rect width="100" height="100" fill={`url(#${uid}-sky)`} />

        {/* sun: glow, disc, and rays that only appear in clean air */}
        <circle
          cx="50"
          cy={scene.sunY}
          r="30"
          fill={`url(#${uid}-sunglow)`}
          className={animate ? "aqi-breathe" : undefined}
          style={
            animate ? { transformOrigin: `50px ${scene.sunY}px` } : undefined
          }
        />

        {scene.sunGlow > 0.5 ? (
          <g
            className={animate ? "aqi-spin" : undefined}
            style={
              animate ? { transformOrigin: `50px ${scene.sunY}px` } : undefined
            }
          >
            {Array.from({ length: 8 }, (_, i) => {
              const a = (i * Math.PI) / 4;
              return (
                <line
                  key={i}
                  x1={50 + Math.cos(a) * 15}
                  y1={scene.sunY + Math.sin(a) * 15}
                  x2={50 + Math.cos(a) * 20}
                  y2={scene.sunY + Math.sin(a) * 20}
                  stroke={scene.sun}
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  opacity={scene.sunGlow * 0.8}
                />
              );
            })}
          </g>
        ) : null}

        <circle cx="50" cy={scene.sunY} r="11" fill={scene.sun} />

        {/* haze layers drifting across, more of them as air worsens */}
        {hazeBands.map((h) => (
          <ellipse
            key={h.id}
            cx="50"
            cy={h.y}
            rx="62"
            ry={5 + h.id * 1.2}
            fill={isDark ? "#0F172A" : "#FFFFFF"}
            opacity={h.opacity}
            className={animate ? "aqi-drift" : undefined}
            style={
              animate
                ? {
                    animationDuration: `${h.duration}s`,
                    animationDelay: `${h.delay}s`,
                  }
                : undefined
            }
          />
        ))}

        {/* suspended particulate: the thing actually being measured */}
        {particles.map((p) => (
          <circle
            key={p.id}
            cx={p.x}
            cy={p.y}
            r={p.r}
            fill={scene.particleColor}
            opacity={animate ? undefined : 0.55}
            className={animate ? "aqi-rise" : undefined}
            style={
              animate
                ? {
                    animationDuration: `${p.duration}s`,
                    animationDelay: `${p.delay}s`,
                  }
                : undefined
            }
          />
        ))}

        {/* a skyline, so the scene reads as a city rather than weather */}
        <g opacity={isDark ? 0.55 : 0.4}>
          <path
            d="M0 100 L0 86 L8 86 L8 79 L16 79 L16 88 L24 88 L24 74 L31 74 L31 83
               L38 83 L38 77 L46 77 L46 90 L54 90 L54 72 L62 72 L62 84 L70 84
               L70 80 L78 80 L78 87 L86 87 L86 76 L94 76 L94 89 L100 89 L100 100 Z"
            fill={isDark ? "#020617" : "#1E293B"}
          />
        </g>

        <rect y="60" width="100" height="40" fill={`url(#${uid}-ground)`} />
      </g>

      {/* rim */}
      <circle
        cx="50"
        cy="50"
        r="48"
        fill="none"
        stroke={band?.color}
        strokeWidth="1.4"
        opacity="0.5"
      />
    </svg>
  );
}

/** Small inline variant for list rows and cards. */
export function AqiSceneChip({ aqi, size = 36, isDark }) {
  return (
    <span
      className="inline-flex shrink-0 overflow-hidden rounded-full"
      style={{ width: size, height: size }}
    >
      <AqiScene aqi={aqi} size={size} isDark={isDark} />
    </span>
  );
}
