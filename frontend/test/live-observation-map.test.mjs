import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const repoRoot = new URL("../..", import.meta.url);
const observationPath = new URL("frontend/src/liveObservation.js", repoRoot);
const pagePath = new URL("frontend/live-observation.html", repoRoot);
const stylesheetPath = new URL("frontend/src/liveObservation.css", repoRoot);

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

test("desktop live map presents a compact readable localization health overlay", () => {
  const source = readFileSync(observationPath, "utf8");
  const page = readFileSync(pagePath, "utf8");
  const stylesheet = readFileSync(stylesheetPath, "utf8");

  assert.match(page, /id="localizationStatus"/);
  assert.match(page, /id="localizationStatusLabel"/);
  assert.match(page, /id="localizationStatusDetail"/);
  assert.match(page, /aria-live="polite"/);
  assert.match(source, /function applyLocalizationStatus\(snapshot\)/);
  assert.match(source, /request\("\/api\/observation\/localization-status"\)/);
  assert.match(source, /LOCALIZATION_STATUS_REFRESH_MS/);
  const localizationStartup = source.slice(
    source.indexOf('if (!settings.live_observation?.enabled)'),
    source.indexOf("const models =", source.indexOf('if (!settings.live_observation?.enabled)')),
  );
  assert.match(
    localizationStartup,
    /if \(!mobileConsoleEnabled\(\)\) \{\s*refreshLocalizationStatus\(\);[\s\S]*?window\.setInterval\(/,
  );
  assert.match(stylesheet, /\.localization-status\[data-phase="relocalizing"\]/);
  assert.match(stylesheet, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(stylesheet, /html\.mobile-console \.localization-status\s*\{\s*display:\s*none;/);
});
