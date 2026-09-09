import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const repoRoot = new URL("../..", import.meta.url);

test("task dashboard controller parses as an ES module before it reaches the DOM", async () => {
  const directory = await mkdtemp(join(tmpdir(), "ry-aletheia-dashboard-module-"));
  try {
    const appSource = await readFile(new URL("autodrive_console/web/app.js", repoRoot), "utf8");
    const httpSource = await readFile(new URL("autodrive_console/web/platform/http.js", repoRoot), "utf8");
    await writeFile(join(directory, "app.mjs"), appSource.replace('"./platform/http.js"', '"./http.mjs"'));
    await writeFile(join(directory, "http.mjs"), httpSource);

    await assert.rejects(
      import(`${pathToFileURL(join(directory, "app.mjs")).href}?${Date.now()}`),
      (error) => {
        assert.notEqual(error.name, "SyntaxError", `dashboard module must parse before it accesses the DOM: ${error.message}`);
        return error instanceof ReferenceError;
      },
    );
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
