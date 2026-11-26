import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  // Read the repo-root .env too, so the frontend proxy and the Flask
  // app cannot drift apart. Setting API_PORT in one place moves both.
  const env = loadEnv(mode, process.cwd(), "");
  const rootEnv = loadEnv(mode, `${process.cwd()}/..`, "");

  const apiPort = env.VITE_API_PORT || rootEnv.API_PORT || "5001";
  const target = env.VITE_API_TARGET || `http://localhost:${apiPort}`;

  // Port 5000 is contested on Windows and macOS. When something else
  // owns it the failure is deceptive: the proxy connects, /health
  // answers, and every real route 404s — which looks like a broken
  // frontend rather than a port clash. Printing the target makes the
  // mistake obvious on startup.
  console.log(`\n  [airwatch] API proxy -> ${target}\n`);

  const proxy = Object.fromEntries(
    ["/api", "/predict", "/health", "/model-info", "/metrics"].map((path) => [
      path,
      {
        target,
        changeOrigin: true,
        // Surface proxy failures instead of returning an opaque 500.
        configure: (p) => {
          p.on("error", (err) => {
            console.error(
              `  [airwatch] proxy error -> ${target}: ${err.message}\n` +
                `  Is the API running?  conda activate airwatch && python -m src.serving.app`,
            );
          });
        },
      },
    ]),
  );

  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: false,
      // The browser talks only to our Flask API, never to Open-Meteo
      // directly. That keeps upstream rate limits under our control
      // and means no third-party key could ever reach the client.
      proxy,
    },
    // `vite preview` serves the built bundle, and it needs the same
    // proxy or every API route 404s. It is worth having: the dev
    // server ships unminified modules one request at a time and runs
    // React in development mode, where every component does extra
    // bookkeeping on each render. Judging how the app performs from
    // `npm run dev` measures the dev server, not the app.
    preview: {
      port: 4173,
      strictPort: false,
      proxy,
    },
    build: {
      outDir: "dist",
      sourcemap: false,
      chunkSizeWarningLimit: 1500,
      rollupOptions: {
        output: {
          manualChunks: {
            plotly: ["plotly.js-basic-dist-min"],
            leaflet: ["leaflet", "react-leaflet"],
            motion: ["framer-motion"],
          },
        },
      },
    },
  };
});
