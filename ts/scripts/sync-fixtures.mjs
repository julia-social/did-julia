/**
 * Copy the repository's language-neutral fixtures into this package so the
 * TypeScript suite replays exactly the recordings the Python reference suite
 * replays — and so the package stays self-contained when it is vendored into
 * another repository.
 *
 * `src/__tests__/fixtures.sync.test.ts` fails if the copies drift.
 */
import { copyFileSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, "..", "..", "tests", "fixtures");
const target = join(here, "..", "src", "__tests__", "fixtures");

mkdirSync(target, { recursive: true });
for (const name of readdirSync(source)) {
  if (!name.endsWith(".json")) continue;
  copyFileSync(join(source, name), join(target, name));
  console.log(`synced ${name}`);
}
