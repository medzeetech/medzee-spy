// Rasterize frontend/src/assets/logo-medzee-spy.svg → public/icons/icon-{16,48,128}.png
// Uses sharp. Idempotent: skips generation if all icons already exist.
import { mkdirSync, existsSync, readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import sharp from "sharp";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const sourceSvg = resolve(root, "..", "frontend", "src", "assets", "logo-medzee-spy.svg");
const outDir = resolve(root, "public", "icons");
mkdirSync(outDir, { recursive: true });

const sizes = [16, 48, 128];
const outPaths = sizes.map((size) => resolve(outDir, `icon-${size}.png`));

if (outPaths.every((p) => existsSync(p))) {
  console.log("✓ icons already present — skipping rasterization");
  console.log("  (delete public/icons/ to force a rebuild)");
  process.exit(0);
}

if (!existsSync(sourceSvg)) {
  console.error("✗ source SVG not found:", sourceSvg);
  process.exit(1);
}

const buf = readFileSync(sourceSvg);
for (const size of sizes) {
  const outPath = resolve(outDir, `icon-${size}.png`);
  await sharp(buf, { density: 300 })
    .resize(size, size, {
      fit: "contain",
      background: { r: 0, g: 0, b: 0, alpha: 0 },
    })
    .png()
    .toFile(outPath);
  console.log("✓", outPath);
}
