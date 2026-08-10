import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // A Mini App must be served over HTTPS, so local development runs behind a
    // tunnel; the API is proxied so the panel calls same-origin `/api` paths and
    // never trips CORS or a mixed-content block.
    allowedHosts: [".trycloudflare.com"],
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
