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

test("desktop localization overlay can disclose normalized state, error, and freshness", () => {
  const source = readFileSync(observationPath, "utf8");
  const page = readFileSync(pagePath, "utf8");
  const stylesheet = readFileSync(stylesheetPath, "utf8");

  assert.match(page, /id="localizationStatusToggle"/);
  assert.match(page, /id="localizationStatusPanel"/);
  assert.match(page, /id="localizationStateSummary"/);
  assert.match(page, /id="localizationIssueSummary"/);
  assert.match(page, /id="localizationFreshness"/);
  assert.match(source, /function formatLocalizationFreshness\(/);
  assert.match(source, /snapshot\?\.error_retained/);
  assert.doesNotMatch(page, /错误码|状态码/);
  assert.match(source, /function setupLocalizationStatusOverlay\(\)/);
  assert.match(stylesheet, /\.localization-status-toggle/);
  assert.match(stylesheet, /\.localization-status-panel\[hidden\]/);
  assert.match(stylesheet, /\.theme-light \.localization-status-panel dd\s*\{[^}]*color:\s*#1f3446/);
});

test("desktop map overlays share one translucent surface in each theme", () => {
  const stylesheet = readFileSync(stylesheetPath, "utf8");

  assert.match(stylesheet, /--map-overlay-surface:\s*rgb\(255 255 255 \/ 46%\)/);
  assert.match(stylesheet, /html:not\(\.mobile-console\) body\.theme-light[\s\S]*?\.map-scale/);
  assert.match(stylesheet, /\.map-layers-control,[\s\S]*?\.localization-status,[\s\S]*?\.map-diagnostics,[\s\S]*?\.map-scale\s*\{[\s\S]*?background:\s*var\(--map-overlay-surface\)/);
  assert.match(stylesheet, /\.map-scale strong\s*\{[\s\S]*?color:\s*var\(--map-overlay-ink\)/);
  assert.match(stylesheet, /\.localization-status-toggle,[\s\S]*?background:\s*transparent !important;[\s\S]*?color:\s*inherit !important;/);
});

test("bottom map diagnostics stays above the vehicle layer", () => {
  const stylesheet = readFileSync(stylesheetPath, "utf8");

  assert.match(stylesheet, /#vehicleLayer\s*\{[^}]*z-index:\s*3;/);
  assert.match(stylesheet, /\.map-diagnostics\s*\{[^}]*z-index:\s*6;/);
});

test("desktop live map keeps a deeper work viewport without changing the narrow-screen fallback", () => {
  const stylesheet = readFileSync(stylesheetPath, "utf8");
  const desktopStart = stylesheet.indexOf("@media (min-width: 1100px)");
  const desktopRules = stylesheet.slice(
    desktopStart,
    stylesheet.indexOf("html.mobile-console", desktopStart),
  );

  assert.match(
    desktopRules,
    /\.local-viewer-workspace\s*\{[\s\S]*?min-height:\s*min\(78vh,\s*920px\);/,
  );
  assert.match(
    stylesheet,
    /@media \(max-width: 760px\)\s*\{[\s\S]*?\.local-viewer-workspace\s*\{[\s\S]*?min-height:\s*max\(460px,\s*calc\(100svh - 120px\)\);/,
  );
});

test("desktop map layers use a collapsible accessible panel while preserving the costmap control", () => {
  const source = readFileSync(observationPath, "utf8");
  const page = readFileSync(pagePath, "utf8");
  const stylesheet = readFileSync(stylesheetPath, "utf8");

  assert.match(
    page,
    /<button[^>]*id="mapLayersToggle"[^>]*aria-expanded="false"[^>]*aria-controls="mapLayersPanel"/,
  );
  assert.match(page, /<section[^>]*id="mapLayersPanel"[^>]*hidden/);
  assert.match(page, /id="costmapVisible" type="checkbox" checked/);
  assert.match(source, /function setupMapLayersPanel\(\)/);
  assert.match(source, /toggle\.setAttribute\("aria-expanded", String\(expanded\)\)/);
  assert.match(stylesheet, /\.map-layers-panel\[hidden\]\s*\{\s*display:\s*none;/);
  assert.match(stylesheet, /html\.mobile-console \.map-layers-control\s*\{\s*display:\s*none;/);
});

test("expanded map layers render as one continuous floating surface", () => {
  const stylesheet = readFileSync(stylesheetPath, "utf8");
  const control = stylesheet.match(/\.map-layers-control\s*\{([^}]*)\}/)?.[1] || "";
  const expanded = stylesheet.match(/\.map-layers-control:has\([^)]*\)\s*\{([^}]*)\}/)?.[1] || "";
  const panel = stylesheet.match(/\.map-layers-panel\s*\{([^}]*)\}/)?.[1] || "";

  assert.match(control, /overflow:\s*hidden;/);
  assert.match(expanded, /border-radius:\s*0 12px 12px 0;/);
  assert.match(panel, /width:\s*100%;/);
  assert.match(panel, /margin:\s*0;/);
  assert.match(panel, /border:\s*0;/);
  assert.match(panel, /box-shadow:\s*none;/);
});

test("collapsed map layers remain a compact low-emphasis map tool", () => {
  const stylesheet = readFileSync(stylesheetPath, "utf8");
  const control = stylesheet.match(/\.map-layers-control\s*\{([^}]*)\}/)?.[1] || "";
  const toggle = stylesheet.match(/\.map-layers-toggle\s*\{([^}]*)\}/)?.[1] || "";

  assert.match(control, /width:\s*36px;/);
  assert.match(control, /left:\s*0;/);
  assert.match(control, /border-radius:\s*0 10px 10px 0;/);
  assert.match(control, /box-shadow:\s*none;/);
  assert.doesNotMatch(control, /transition:\s*width/);
  assert.match(toggle, /min-height:\s*32px;/);
  assert.match(toggle, /margin:\s*0;/);
  assert.match(stylesheet, /\.map-layers-control:has\(\.map-layers-toggle\[aria-expanded="true"\]\)/);
});

test("map overlays use translucent surfaces, an edge-reveal layer handle, and exclusive panels", () => {
  const source = readFileSync(observationPath, "utf8");
  const stylesheet = readFileSync(stylesheetPath, "utf8");
  const control = stylesheet.match(/\.map-layers-control\s*\{([^}]*)\}/)?.[1] || "";

  assert.match(control, /left:\s*0;/);
  assert.match(control, /width:\s*36px;/);
  assert.match(control, /background:\s*rgb\(13 25 36 \/ 52%\)/);
  assert.match(stylesheet, /\.map-layers-toggle span\s*\{[^}]*opacity:\s*0;/);
  assert.match(stylesheet, /\.relocalization-control\s*\{[^}]*background:\s*rgb\(13 25 36 \/ 58%\)/);
  assert.match(stylesheet, /\.localization-status\s*\{[^}]*background:\s*rgb\(9 22 35 \/ 72%\)/);
  assert.match(stylesheet, /\.map-diagnostics\s*\{[^}]*background:\s*rgb\(8 21 34 \/ 72%\)/);
  assert.match(stylesheet, /\.map-layers-control:has\([^)]*aria-expanded="true"[^)]*\)\s*~\s*\.relocalization-control\s*\{[^}]*left:\s*210px;/);
  assert.match(source, /MAP_OVERLAY_OPEN_EVENT/);
  assert.match(source, /announceMapOverlayOpen\("layers"\)/);
  assert.match(source, /announceMapOverlayOpen\("relocalization"\)/);
});

test("desktop observation exposes a server-controlled manual relocalization flow", () => {
  const source = readFileSync(observationPath, "utf8");
  const page = readFileSync(pagePath, "utf8");

  assert.match(page, /id="relocalizationToggle"/);
  assert.match(page, /id="relocalizationPanel"/);
  assert.match(page, /id="relocalizationApply"/);
  assert.match(source, /function setupRelocalizationControl\(\)/);
  assert.match(source, /"\/api\/observation\/relocalization"/);
  assert.match(source, /"\/api\/observation\/relocalization\/begin"/);
  assert.match(source, /"\/api\/observation\/relocalization\/apply"/);
  assert.match(source, /"\/api\/observation\/relocalization\/recover-navigation"/);
  assert.match(readFileSync(stylesheetPath, "utf8"), /html\.mobile-console \.relocalization-control/);
});

test("map marker navigation renders its backend-owned route with a default-on layer toggle", () => {
  const source = readFileSync(observationPath, "utf8");
  const page = readFileSync(pagePath, "utf8");
  const stylesheet = readFileSync(stylesheetPath, "utf8");

  assert.match(page, /id="navigationRouteVisible" type="checkbox" checked/);
  assert.match(page, />规划路线</);
  assert.match(source, /let navigationRouteVisible = true;/);
  assert.match(source, /let pixiNavigationRouteLayer;/);
  assert.match(source, /function renderNavigationRoute\(\)/);
  assert.match(source, /renderVirtualWalls\(\);\s*renderNavigationRoute\(\);\s*renderMapMarkers\(\);/);
  assert.match(source, /Math\.PI\s*\/\s*180/);
  assert.match(page, /yaw（角度）/);
  assert.match(stylesheet, /html\[data-theme="light"\] \.map-marker-control/);
  assert.match(stylesheet, /html\[data-theme="light"\] \.map-marker-toggle\s*\{[^}]*color:\s*#203044/);
});

test("manual relocalization preview moves point cloud and costmap with one rigid transform", () => {
  const source = readFileSync(observationPath, "utf8");

  assert.match(source, /function relocalizationPreviewTransform\(\)/);
  assert.match(source, /const source = relocalizationCandidateFromLivePose\(\);/);
  assert.match(source, /function transformRelocalizationPoint\(point, transform/);
  assert.match(source, /const previewOrigin = transformRelocalizationPoint\(origin, transform\)/);
  assert.match(source, /const previewPoint = transformRelocalizationPoint\(/);
  assert.match(source, /syncVehicleLayer\(previewVehiclePose\(layout\.vehicle\), layout\)/);
  assert.match(source, /const vehicle = previewVehiclePose\(renderedVehiclePoseInMap\(\)\);\s*if \(vehicle\?\.position\) syncVehicleLayer\(vehicle, lastMapLayout\)/);
  assert.match(source, /relocalizationDrag/);
});

test("manual relocalization keeps pose editing on the map instead of a numeric panel", () => {
  const source = readFileSync(observationPath, "utf8");
  const page = readFileSync(pagePath, "utf8");
  const css = readFileSync(stylesheetPath, "utf8");

  assert.doesNotMatch(page, /id="relocalizationX"/);
  assert.doesNotMatch(page, /id="relocalizationYawInput"/);
  assert.match(source, /mode: event\.button === 2 \? "rotate" : "move"/);
  assert.match(source, /relocalizationDrag\.mode === "rotate"/);
  assert.match(source, /Math\.atan2\(point\.y - relocalizationPreview\.y, point\.x - relocalizationPreview\.x\)/);
  assert.match(source, /addEventListener\("contextmenu"/);
  assert.match(css, /\.relocalization-toggle span \{[^}]*white-space:\s*nowrap/);
  assert.match(source, /replaceAll\("校准定位", "手动重定位"\)/);
});

test("manual relocalization submits only a finite preview pose and keeps its action feedback visible", () => {
  const source = readFileSync(observationPath, "utf8");

  assert.match(source, /function hasFiniteRelocalizationCandidate\(candidate\)/);
  assert.match(
    source,
    /const canApply = canSubmitRelocalization\(\);/,
  );
  assert.match(source, /if \(!hasFiniteRelocalizationCandidate\(candidate\)\) \{/);
  assert.match(source, /let relocalizationActionPending = false;/);
  assert.match(source, /relocalizationActionPending = true;/);
  assert.match(source, /relocalizationActionNotice = error\.message/);
});

test("manual relocalization freezes the current map framing before submitting a discontinuous pose", () => {
  const source = readFileSync(observationPath, "utf8");
  const submitAction = source.slice(
    source.indexOf("async function postRelocalizationAction"),
    source.indexOf("function setupRelocalizationControl"),
  );

  assert.match(source, /import \{ freezeMapViewportForRelocalization \} from "\.\/mapViewportLock\.js"/);
  assert.match(
    submitAction,
    /if \(isApply\) \{[\s\S]*?freezeMapViewportForRelocalization\(mapView, lastMapLayout\);[\s\S]*?overviewUntilMovement = false;[\s\S]*?scheduleMapDraw\(true\);/,
  );
});

test("map marker navigation keeps cancellation feedback read-only until the backend reports a terminal state", () => {
  const source = readFileSync(observationPath, "utf8");
  const menu = source.slice(
    source.indexOf("function renderMapMarkerMenu"),
    source.indexOf("function openMapMarkerMenu"),
  );
  const polling = source.slice(
    source.indexOf("function updateMapMarkerNavigationPolling"),
    source.indexOf("async function refreshMapMarkerNavigationStatus"),
  );

  assert.match(menu, /phase === "cancelling" \|\| phase === "cancellation_unconfirmed"/);
  assert.match(menu, /action\.disabled = stopping/);
  assert.match(polling, /"cancellation_unconfirmed"/);
  assert.match(source, /if \(\["cancelling", "cancellation_unconfirmed"\]\.includes\(mapMarkerNavigationStatus\?\.phase\)\) return;/);
});

test("live map retries virtual-wall resolution without reloading the base map", () => {
  const source = readFileSync(observationPath, "utf8");

  assert.match(source, /function requestLiveWallCompensation\(/);
  assert.match(source, /function clearLiveWallCompensation\(/);
  assert.match(source, /"\/api\/observation\/live-layers"/);
  assert.match(
    source,
    /renderVirtualWalls\(\);[\s\S]*?updateDiagnostics\(\);\s*scheduleMapDraw\(\);/,
  );
});

test("live map keeps confirmed virtual walls until a replacement map is confirmed", () => {
  const source = readFileSync(observationPath, "utf8");
  const refresh = source.slice(
    source.indexOf("async function refreshActiveMap"),
    source.indexOf("function liveWallSignature"),
  );
  const compensation = source.slice(
    source.indexOf("function scheduleLiveWallCompensation"),
    source.indexOf("function loadCachedMap"),
  );

  assert.match(refresh, /const incomingWalls = Array\.isArray\(layers\.virtual_walls\)/);
  assert.match(refresh, /if \(incomingWalls\.length \|\| !virtualWalls\.length\)\s*virtualWalls = incomingWalls/);
  assert.doesNotMatch(refresh, /virtualWalls\s*=\s*\[\]/);
  assert.doesNotMatch(compensation, /\|\| virtualWalls\.length/);
  assert.match(compensation, /const incomingWalls = Array\.isArray\(result\.virtual_walls\)/);
  assert.match(compensation, /if \(incomingWalls\.length \|\| !virtualWalls\.length\)\s*virtualWalls = incomingWalls/);
  assert.doesNotMatch(compensation, /virtualWalls\s*=\s*Array\.isArray\(result\.virtual_walls\)/);
  assert.match(compensation, /renderVirtualWalls\(\);[\s\S]*?refreshMapMarkers\(\);[\s\S]*?updateDiagnostics\(\);/);
});

test("desktop map uses an on-demand manual marker layer", () => {
  const page = readFileSync(pagePath, "utf8");
  const source = readFileSync(observationPath, "utf8");
  const stylesheet = readFileSync(stylesheetPath, "utf8");

  assert.match(page, /id="mapMarkersVisible" type="checkbox" checked/);
  assert.match(page, />地图标记</);
  assert.match(page, /id="mapMarkerCreateToggle"/);
  assert.match(page, /id="mapMarkerAlias"/);
  assert.match(source, /function renderMapMarkers\(/);
  assert.match(source, /const headingX\s*=\s*Math\.cos\(Number\(point\.yaw\)\)/);
  assert.match(source, /const headingY\s*=\s*-Math\.sin\(Number\(point\.yaw\)\)/);
  assert.match(source, /const arrowTip\s*=\s*radius\s*\*\s*1\.05/);
  assert.match(source, /function openMapMarkerMenu\(/);
  assert.match(source, /contextmenu/);
  assert.match(source, /"\/api\/observation\/map-markers"/);
  assert.match(source, /map-marker-navigation\/begin/);
  assert.doesNotMatch(source, /task-points|task-point-navigation/);
  assert.doesNotMatch(source, /setInterval\(\s*refreshMapMarkers/);
  assert.match(stylesheet, /\.map-marker-menu/);
  assert.match(stylesheet, /\.map-marker-form/);
  assert.match(stylesheet, /prefers-reduced-motion/);
});
