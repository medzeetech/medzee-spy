import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { crx } from "@crxjs/vite-plugin";
import manifest from "./manifest.json" with { type: "json" };

// CRXJS handles MV3 manifest references, content-script bundling,
// HMR for popup, and rewrites src/... paths to built JS at build time.
// If CRXJS proves brittle on this React 19 + Vite 6 stack, fall back to
// a manual rollupOptions.input multi-entry config (see README).
export default defineConfig({
  plugins: [
    react(),
    crx({ manifest: manifest as any }),
  ],
  build: {
    target: "chrome102",
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    port: 5174,
    strictPort: true,
    hmr: { port: 5174 },
  },
});
