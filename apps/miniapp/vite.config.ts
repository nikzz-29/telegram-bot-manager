import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * The locales the bot uses, reachable from the panel.
 *
 * DECISION: the `.ftl` files are imported from `packages/i18n` rather than
 * copied into the app. The spec asks for one set of locales read by both
 * runtimes, and a copy would drift the moment someone fixes a typo on one side
 * — the panel would then say something the bot does not.
 */
const LOCALES = resolve(__dirname, "../../packages/i18n/locales");

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@locales": LOCALES,
    },
  },
  server: {
    // A Mini App must be served over HTTPS, so local development runs behind a
    // tunnel; the API is proxied so the panel calls same-origin `/api` paths and
    // never trips CORS or a mixed-content block.
    allowedHosts: [".trycloudflare.com"],
    // Vite refuses to serve files outside the project root by default, and the
    // locales live one package over.
    fs: { allow: [resolve(__dirname, ".."), LOCALES] },
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
