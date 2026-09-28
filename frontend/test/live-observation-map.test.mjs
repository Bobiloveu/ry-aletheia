import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const repoRoot = new URL("../..", import.meta.url);
const observationPath = new URL("frontend/src/liveObservation.js", repoRoot);
const pagePath = new URL("frontend/live-observation.html", repoRoot);

test("desktop live map projects the detailed vehicle and metric aids in map scale", () => {
  const source = readFileSync(observationPath, "utf8");
  const page = readFileSync(pagePath, "utf8");
  const scaleRenderer = source.slice(
    source.indexOf("function updateMapScale"),
    source.indexOf("function drawMap"),
  );

  assert.match(page, /id="vehicleLayer"[\s\S]*?<svg[\s\S]*?class="vehicle-illustration"/);
  assert.match(page, /vehicle-led--front/);
  assert.match(page, /vehicle-lidar/);
  assert.match(
    page,
    /vehicle-sensor--front" cx="34" cy="24"[\s\S]*?vehicle-sensor--rear" cx="34" cy="76"/,
  );
  assert.match(page, /vehicle-led--rear" d="M18 87H50"/);
  assert.match(
    source,
    /projectVehicleFootprint\(\s*vehicleModel,\s*layout\.pixelsPerMeter,\s*\)/,
  );
  assert.match(source, /renderMetricGrid\(layout\)/);
  assert.doesNotMatch(scaleRenderer, /if \(!mobileConsoleEnabled\(\)\)/);
  assert.match(scaleRenderer, /const palette = mobileConsoleEnabled\(\) \? MAP_PALETTE : DESKTOP_MAP_PALETTE/);
});
