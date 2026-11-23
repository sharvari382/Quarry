// Copies ../sample_data/*.csv into public/samples so the "Load sample data" button works in dev and builds.
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "..", "sample_data");
const dest = join(here, "..", "public", "samples");
if (existsSync(src)) {
  mkdirSync(dest, { recursive: true });
  for (const f of ["sales.csv", "customers.csv", "products.csv"]) cpSync(join(src, f), join(dest, f));
}
