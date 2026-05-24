import { defineConfig } from "vite";
import { resolve } from "path";

// Standalone build for the page-world script (`wa-collector`).
//
// Why a separate config:
//   CRXJS owns rollupOptions during the main `vite build` and treats every
//   manifest reference (content_scripts, service_worker, popup,
//   web_accessible_resources) as a CRXJS-managed entry. The page-world
//   script must be bundled with all its deps inlined (`@wppconnect/wa-js`,
//   `../lib/chunker`) and end up at a stable, unhashed path so the
//   content-script (T15) can `chrome.runtime.getURL('wa-collector.js')`.
//
// Build order:
//   This runs BEFORE the CRXJS build, dropping the bundled IIFE into
//   `public/wa-collector.js`. CRXJS then (a) validates the manifest
//   reference `wa-collector.js` against the public dir and (b) copies
//   the file straight into `dist/wa-collector.js` as a static asset.
//   That keeps the path stable, unhashed, and predictable for
//   `chrome.runtime.getURL('wa-collector.js')` from the content-script (T15).
export default defineConfig({
  build: {
    // Output into `public/` so CRXJS can find it as a static manifest asset
    // and copy it to `dist/wa-collector.js` during the main build.
    outDir: "public",
    // Critical: do NOT empty publicDir — it also contains icons/.
    emptyOutDir: false,
    sourcemap: false,
    target: "chrome102",
    // Bundle wa-js inline; no code splitting; flat output path.
    lib: {
      entry: resolve(__dirname, "src/page-world/wa-collector.ts"),
      name: "MedzeeWaCollector",
      formats: ["iife"],
      fileName: () => "wa-collector.js",
    },
    rollupOptions: {
      // No externals — everything (wa-js + chunker) gets inlined.
      external: [],
      output: {
        // Lib mode + IIFE = single self-contained file.
        inlineDynamicImports: true,
        extend: true,
      },
    },
  },
});
