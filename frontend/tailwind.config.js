/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        ink: {
          950: "#070B14",
          900: "#0B1120",
          850: "#0F172A",
          800: "#131C31",
          700: "#1E293B",
          600: "#334155",
          500: "#475569",
          400: "#64748B",
          300: "#94A3B8",
          200: "#CBD5E1",
          100: "#E2E8F0",
        },
        accent: {
          DEFAULT: "#14B8A6",
          soft: "#2DD4BF",
          deep: "#0F766E",
        },
        aqi: {
          good: "#00E400",
          moderate: "#FFD400",
          sensitive: "#FF7E00",
          unhealthy: "#FF3B30",
          very: "#8F3F97",
          hazardous: "#7E0023",
        },
      },
      boxShadow: {
        panel: "0 1px 2px rgba(0,0,0,.28), 0 12px 32px -12px rgba(0,0,0,.6)",
        glow: "0 0 0 1px rgba(20,184,166,.25), 0 0 28px -6px rgba(20,184,166,.35)",
      },
      keyframes: {
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "pulse-ring": {
          "0%": { transform: "scale(.85)", opacity: "0.7" },
          "70%": { transform: "scale(1.6)", opacity: "0" },
          "100%": { transform: "scale(1.6)", opacity: "0" },
        },
        "fade-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.8s infinite",
        "pulse-ring": "pulse-ring 2.4s cubic-bezier(.24,.6,.35,1) infinite",
        "fade-up": "fade-up .45s cubic-bezier(.22,1,.36,1) both",
      },
    },
  },
  plugins: [],
};
