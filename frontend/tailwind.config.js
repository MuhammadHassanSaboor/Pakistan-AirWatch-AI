/** @type {import('tailwindcss').Config} */

// Colours are CSS custom properties so a single `data-theme` swap
// restyles the whole app. Components use one set of semantic class
// names (bg-surface, text-fg, border-line) rather than doubling every
// rule with a `dark:` variant, which is what keeps a two-theme UI
// maintainable rather than a chore.
const withAlpha = (variable) => `rgb(var(${variable}) / <alpha-value>)`;

export default {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },

      colors: {
        // ── semantic surfaces ──
        canvas: withAlpha("--c-canvas"),
        surface: withAlpha("--c-surface"),
        raised: withAlpha("--c-raised"),
        sunken: withAlpha("--c-sunken"),
        line: withAlpha("--c-line"),
        "line-strong": withAlpha("--c-line-strong"),

        // ── semantic text ──
        fg: withAlpha("--c-fg"),
        "fg-muted": withAlpha("--c-fg-muted"),
        "fg-subtle": withAlpha("--c-fg-subtle"),
        "fg-faint": withAlpha("--c-fg-faint"),

        // ── brand ──
        accent: {
          DEFAULT: withAlpha("--c-accent"),
          soft: withAlpha("--c-accent-soft"),
          strong: withAlpha("--c-accent-strong"),
        },

        // ── AQI scale (identical in both themes: these encode
        //    a published standard, not a design preference) ──
        aqi: {
          good: "#00B050",
          moderate: "#E8B600",
          sensitive: "#FF7E00",
          unhealthy: "#F03B36",
          very: "#8F3F97",
          hazardous: "#7E0023",
        },

        ok: withAlpha("--c-ok"),
        warn: withAlpha("--c-warn"),
        danger: withAlpha("--c-danger"),
      },

      // A readable type scale. The previous UI sat at 10–11px almost
      // everywhere, which is why the page was hard to read.
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }], // 11px — labels only
        xs: ["0.75rem", { lineHeight: "1.125rem" }], // 12px
        sm: ["0.8125rem", { lineHeight: "1.25rem" }], // 13px — body
        base: ["0.9375rem", { lineHeight: "1.5rem" }], // 15px
        lg: ["1.0625rem", { lineHeight: "1.625rem" }],
        xl: ["1.25rem", { lineHeight: "1.75rem" }],
        "2xl": ["1.5rem", { lineHeight: "2rem" }],
        "3xl": ["1.875rem", { lineHeight: "2.25rem" }],
        "4xl": ["2.375rem", { lineHeight: "2.5rem" }],
        "5xl": ["3rem", { lineHeight: "1" }],
      },

      // Tailwind's default opacity scale jumps 10 -> 20, which is too
      // coarse for tinted surfaces: an accent fill at 20% reads as a
      // solid button, at 10% it disappears on light backgrounds. These
      // fill in the steps the design actually uses.
      opacity: {
        12: "0.12",
        15: "0.15",
        35: "0.35",
        85: "0.85",
        88: "0.88",
        92: "0.92",
      },

      borderRadius: {
        card: "0.875rem",
      },

      boxShadow: {
        card: "var(--shadow-card)",
        float: "var(--shadow-float)",
        // Kept as an alias: several components still reference it and
        // it should mean the same elevation as `float`.
        raised: "var(--shadow-float)",
        glow: "0 0 0 1px rgb(var(--c-accent) / 0.3), 0 0 24px -8px rgb(var(--c-accent) / 0.45)",
      },

      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "pulse-ring": {
          "0%": { transform: "scale(.85)", opacity: "0.6" },
          "70%,100%": { transform: "scale(1.7)", opacity: "0" },
        },
      },
      animation: {
        shimmer: "shimmer 1.8s infinite",
        "pulse-ring": "pulse-ring 2.4s cubic-bezier(.24,.6,.35,1) infinite",
      },
    },
  },
  plugins: [],
};
