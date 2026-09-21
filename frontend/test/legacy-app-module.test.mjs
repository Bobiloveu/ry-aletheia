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
const dashboardPagePath = new URL("autodrive_console/web/index.html", repoRoot);
const dashboardStylesPath = new URL("autodrive_console/web/refinement.css", repoRoot);
const dashboardAppPath = new URL("autodrive_console/web/app.js", repoRoot);
const runtimeSettingsAppPath = new URL("frontend/src/main.js", repoRoot);
const runtimeSettingsStylesPath = new URL("frontend/src/runtimeSettings.css", repoRoot);

test("task dashboard controller parses as an ES module before it reaches the DOM", async () => {
  const directory = await mkdtemp(join(tmpdir(), "ry-aletheia-dashboard-module-"));
  try {
    const appSource = await readFile(new URL("autodrive_console/web/app.js", repoRoot), "utf8");
    const httpSource = await readFile(new URL("autodrive_console/web/platform/http.js", repoRoot), "utf8");
    const syncSource = await readFile(new URL("autodrive_console/web/task_dashboard_sync.js", repoRoot), "utf8");
    const trajectoryHoverSource = await readFile(new URL("autodrive_console/web/trajectory-hover.js", repoRoot), "utf8");
    await writeFile(join(directory, "app.mjs"), appSource.replace('"./platform/http.js"', '"./http.mjs"'));
    await writeFile(join(directory, "http.mjs"), httpSource);
    await writeFile(join(directory, "task_dashboard_sync.js"), syncSource);
    await writeFile(join(directory, "trajectory-hover.js"), trajectoryHoverSource);

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

test("safe shutdown uses a guarded pinball control without changing the shutdown API", () => {
  const page = readFileSync(dashboardPagePath, "utf8");
  const styles = readFileSync(dashboardStylesPath, "utf8");
  const app = readFileSync(dashboardAppPath, "utf8");

  assert.match(page, /class="shutdown-control"/);
  assert.match(page, /id="shutdownToggle"/);
  assert.match(page, /for="shutdownToggle"/);
  assert.match(page, />运行中</);
  assert.match(page, /右拨关闭/);
  assert.match(styles, /\.shutdown-control/);
  assert.match(styles, /\.shutdown-toggle-input:checked/);
  assert.match(
    styles,
    /\.shutdown-toggle-input:checked ~ \.pinball-track \.pinball-core\s*\{[^}]*transform:\s*translateX\(55px\)[^}]*animation:/,
    "a checked shutdown toggle must have a static right-side position when motion is unavailable",
  );
  assert.doesNotMatch(styles, /\.shutdown-toggle-input:(?:focus-visible|checked|not\(:checked\)) \+ \.pinball-track/);
  assert.match(app, /shutdownToggle/);
  assert.match(app, /shutdownReleaseTimer/);
  assert.match(app, /SHUTDOWN_ARM_DELAY\s*=\s*1000/);
  assert.match(app, /confirmAction\(\{ eyebrow: 'SAFE SHUTDOWN'/);
  assert.match(app, /fetch\('\/api\/system\/shutdown', \{ method: 'POST' \}\)/);
});

test("execution ledger does not expose opaque internal run identifiers", () => {
  const page = readFileSync(dashboardPagePath, "utf8");
  const app = readFileSync(dashboardAppPath, "utf8");

  assert.doesNotMatch(page, /id=["']runId["']/);
  assert.doesNotMatch(app, /`RUN \/ \$\{run\.id\}`/);
});

test("runtime settings exposes an optional styled console autostart control", () => {
  const app = readFileSync(runtimeSettingsAppPath, "utf8");
  const styles = readFileSync(runtimeSettingsStylesPath, "utf8");

  assert.match(app, /id="autostartEnabled"/);
  assert.match(app, /autostart_enabled/);
  assert.match(app, /data\.autostart/);
  assert.doesNotMatch(app, /只启动 RY Aletheia 控制台，不会启动或重启机器人节点/);
  assert.match(styles, /\.autostart-rocker/);
  assert.match(styles, /\.switch-left/);
  assert.match(styles, /#29d7d0|var\(--accent\)/);
});

test("trajectory hover resolves the nearest transformed sample, magnetic cursor state, and Beijing time", async () => {
  const page = readFileSync(dashboardPagePath, "utf8");
  const styles = readFileSync(dashboardStylesPath, "utf8");
  const app = readFileSync(dashboardAppPath, "utf8");
  assert.match(page, /id="trajectoryTooltip"/);
  assert.match(page, /id="trajectoryCursor"/);
  assert.match(page, /data-trajectory-counter="timestamp"/);
  assert.doesNotMatch(page, /data-trajectory-counter="distance"/);
  assert.match(styles, /\.trajectory-tooltip/);
  assert.match(styles, /\.trajectory-cursor/);
  assert.match(app, /findMagneticTrajectoryPoint/);
  assert.match(app, /formatBeijingTime/);
  assert.match(app, /animateTrajectoryCounters/);
  assert.doesNotMatch(app, /distancePx \/ trajectoryView\.scale/);
  const { findNearestTrajectoryPoint, findMagneticTrajectoryPoint, formatBeijingTime, interpolateCounterValue } = await import(
    new URL("autodrive_console/web/trajectory-hover.js", repoRoot),
  );
  const map = { resolution: 1, width: 100, height: 80, origin: [0, 0] };
  const point = { timestamp_ns: Date.UTC(2026, 8, 20, 8, 0, 0) * 1_000_000, x: 10, y: 20, route_name: "去程" };
  const nearest = findNearestTrajectoryPoint(
    [point],
    map,
    { canvasWidth: 200, canvasHeight: 200, imageWidth: 100, imageHeight: 90, evidenceHeight: 10, scale: 1, offsetX: 0, offsetY: 0 },
    { x: 61, y: 124 },
  );

  assert.equal(nearest.point, point);
  assert.equal(nearest.distancePx.toFixed(2), "1.41");
  const magnetic = findMagneticTrajectoryPoint(
    [point],
    map,
    { canvasWidth: 200, canvasHeight: 200, imageWidth: 100, imageHeight: 90, evidenceHeight: 10, scale: 1, offsetX: 0, offsetY: 0 },
    { x: 61, y: 165 },
    { verticalWeight: 0.38, maxDistancePx: 100 },
  );
  assert.equal(magnetic.point, point);
  assert.equal(magnetic.distancePx.toFixed(2), "40.01");
  assert.equal(formatBeijingTime(point.timestamp_ns), "2026-09-20 16:00:00");
  assert.equal(interpolateCounterValue(0, 100, 0.35), 35);
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
