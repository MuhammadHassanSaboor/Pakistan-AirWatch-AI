import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The browser talks only to our Flask API, never to Open-Meteo
    // directly. That keeps upstream rate limits under our control and
    // means no third-party key could ever reach the client.
    proxy: {
      "/api": { target: "http://localhost:5000", changeOrigin: true },
      "/predict": { target: "http://localhost:5000", changeOrigin: true },
      "/health": { target: "http://localhost:5000", changeOrigin: true },
      "/model-info": { target: "http://localhost:5000", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 4000, // plotly is large by nature
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
});
