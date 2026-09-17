import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const repoRoot = new URL("../..", import.meta.url);
const deploymentRendererPath = new URL(
  "autodrive_console/web/deployment/canvas-renderer.js",
  repoRoot,
);

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

test("deployment renderer draws a map-origin callback before localization markers", () => {
  const source = readFileSync(deploymentRendererPath, "utf8");
  assert.match(source, /drawMapOrigin\?\.\(\)/);
  assert.match(source, /drawMapOrigin\?\.\(\)[\s\S]*drawLocalizationMarkers\?\.\(\)/);
});

test("deployment route editor uses controlled route endpoints and no raw pose fields", () => {
  const deploymentPath = new URL("autodrive_console/web/deployment.js", repoRoot);
  const source = readFileSync(deploymentPath, "utf8");
  assert.match(source, /\/localization-routes/);
  assert.match(source, /component_center/);
  assert.match(source, /task_start_waypoint_id/);
  assert.doesNotMatch(source, /localizationGoX|localizationReturnX/);
});

test("route editor preserves saved membership and exposes new same-identity choices", async () => {
  const { orderedRouteBindingIds } = await import(
    new URL("autodrive_console/web/deployment/localization-route.js", repoRoot),
  );
  const bindings = [
    { id: "A", building: "1", unit: "1" },
    { id: "B", building: "1", unit: "1" },
    { id: "C", building: "1", unit: "1" },
    { id: "D", building: "2", unit: "1" },
  ];

  assert.deepEqual(orderedRouteBindingIds(["A", "B"], bindings, "1", "1"), [
    "A",
    "B",
  ]);
  assert.deepEqual(orderedRouteBindingIds(undefined, bindings, "1", "1"), ["A", "B", "C"]);
});

test("single-map route exposes both controlled task endpoints", async () => {
  const { routeEndpointFields } = await import(
    new URL("autodrive_console/web/deployment/localization-route.js", repoRoot),
  );

  assert.deepEqual(routeEndpointFields(true, true), ["start", "target"]);
});
