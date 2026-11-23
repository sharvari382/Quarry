import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// In development the Vite server proxies /api to the FastAPI app, so the browser
// sees a single origin and SameSite=Strict cookies work exactly like production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: false } },
  },
  build: { sourcemap: false, chunkSizeWarningLimit: 900 },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
