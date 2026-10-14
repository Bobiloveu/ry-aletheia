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
const bagRecordingConfigPagePath = new URL("autodrive_console/web/bag-recording-config.html", repoRoot);
const bagRecordingsPagePath = new URL("autodrive_console/web/bag-recordings.html", repoRoot);
const bagRecordingsAppPath = new URL("autodrive_console/web/bag_recordings.js", repoRoot);
const dashboardStylesPath = new URL("autodrive_console/web/refinement.css", repoRoot);
const dashboardAppPath = new URL("autodrive_console/web/app.js", repoRoot);
const bagRecordingSelectionPath = new URL("autodrive_console/web/bag-recording-selection.js", repoRoot);
const appShellStylesPath = new URL("autodrive_console/web/app_shell.css", repoRoot);
const runtimeSettingsAppPath = new URL("frontend/src/main.js", repoRoot);
const runtimeSettingsStylesPath = new URL("frontend/src/runtimeSettings.css", repoRoot);

test("task dashboard controller parses as an ES module before it reaches the DOM", async () => {
  const directory = await mkdtemp(join(tmpdir(), "ry-aletheia-dashboard-module-"));
  try {
    const appSource = await readFile(new URL("autodrive_console/web/app.js", repoRoot), "utf8");
    const httpSource = await readFile(new URL("autodrive_console/web/platform/http.js", repoRoot), "utf8");
    const syncSource = await readFile(new URL("autodrive_console/web/task_dashboard_sync.js", repoRoot), "utf8");
    const trajectoryHoverSource = await readFile(new URL("autodrive_console/web/trajectory-hover.js", repoRoot), "utf8");
    const bagRecordingSource = await readFile(new URL("autodrive_console/web/bag-recording-form.js", repoRoot), "utf8");
    const bagRecordingSelectionSource = await readFile(new URL("autodrive_console/web/bag-recording-selection.js", repoRoot), "utf8");
    await writeFile(join(directory, "app.mjs"), appSource.replace('"./platform/http.js"', '"./http.mjs"'));
    await writeFile(join(directory, "http.mjs"), httpSource);
    await writeFile(join(directory, "task_dashboard_sync.js"), syncSource);
    await writeFile(join(directory, "trajectory-hover.js"), trajectoryHoverSource);
    await writeFile(join(directory, "bag-recording-form.js"), bagRecordingSource);
    await writeFile(join(directory, "bag-recording-selection.js"), bagRecordingSelectionSource);

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

test("diagnostic recording configuration survives navigation away from the task dashboard", async () => {
  const { loadBagRecordingDraft, saveBagRecordingDraft } = await import(bagRecordingSelectionPath);
  const values = new Map();
  const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };

  saveBagRecordingDraft(storage, { attemptIndex: 3, topics: ["/odom", "/task_status"] });

  assert.deepEqual(loadBagRecordingDraft(storage), { attemptIndex: 3, topics: ["/odom", "/task_status"] });
});

test("manual diagnostic recording configuration survives navigation before it starts", async () => {
  const { loadManualBagRecordingDraft, saveManualBagRecordingDraft } = await import(bagRecordingSelectionPath);
  const values = new Map();
  const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };

  saveManualBagRecordingDraft(storage, { topics: ["/odom"], durationMinutes: 15, label: "遥控复现" });

  assert.deepEqual(loadManualBagRecordingDraft(storage), { topics: ["/odom"], durationMinutes: 15, label: "遥控复现" });
});

test("task dashboard keeps diagnostic capture compact and links to its dedicated configuration page", () => {
  const page = readFileSync(dashboardPagePath, "utf8");
  const app = readFileSync(dashboardAppPath, "utf8");

  assert.match(page, /id="configureBagRecording"/);
  assert.match(page, /href="\/bag-recording-config\.html"/);
  assert.doesNotMatch(page, /id="bagTopicList"/);
  assert.doesNotMatch(page, /id="bagTopicFilter"/);
  assert.match(app, /diagnosticRecording[\s\S]{0,40}ready/);
  assert.match(app, /history\.replaceState/);
});

test("diagnostic recording configuration explains that it captures one chosen test round", () => {
  const page = readFileSync(bagRecordingConfigPagePath, "utf8");

  assert.match(page, /在第几轮录制/);
  assert.match(page, /只录制这一轮；例如填 3 表示仅在第 3 轮录制。/);
});

test("diagnostic recordings offer a page-independent manual scene capture without a test round", () => {
  const page = readFileSync(bagRecordingsPagePath, "utf8");
  const config = readFileSync(bagRecordingConfigPagePath, "utf8");
  const app = readFileSync(bagRecordingsAppPath, "utf8");

  assert.match(page, /id="configureManualBagRecording"/);
  assert.match(page, /手动场景录制/);
  assert.match(config, /manual/);
  assert.match(config, /id="durationMinutes"/);
  assert.match(config, /value="20">20 分钟/);
  assert.doesNotMatch(config, /value="30">30 分钟/);
  assert.match(config, /id="sceneLabel"/);
  assert.match(app, /\/api\/bag-recordings\/manual/);
  assert.match(app, /\/api\/bag-recordings\/manual\/stop/);
  assert.match(app, /手动场景录制正在进行/);
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

test("preflight metric animates three waiting dots only while preparing", () => {
  const page = readFileSync(dashboardPagePath, "utf8");
  const styles = readFileSync(dashboardStylesPath, "utf8");
  const app = readFileSync(dashboardAppPath, "utf8");

  assert.match(page, /class="run-status-metric"/);
  assert.match(page, /id="runStatusMotion"[^>]*hidden/);
  assert.match(page, /aria-label="正在执行前置条件检查"/);
  assert.equal((page.match(/class="run-status-motion-dot"/g) || []).length, 3);
  assert.match(styles, /\.run-status-motion/);
  assert.match(styles, /\.run-status-motion-dot:nth-child\(3\)/);
  assert.match(styles, /@keyframes run-status-orbit/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.run-status-motion/);
  assert.match(app, /const preflightPending = run\?\.status === 'preparing';/);
  assert.match(app, /\$\('runStatusMotion'\)\.hidden = !preflightPending/);
});

test("task dashboard explains recovered power-loss runs without blocking a new test", () => {
  const app = readFileSync(dashboardAppPath, "utf8");

  assert.match(app, /interrupted:\s*'意外断电中断'/);
  assert.match(app, /unknown_after_power_loss:\s*'结果未知（断电）'/);
  assert.match(app, /summary\.unknown/);
  assert.match(app, /历史记录，可直接开始新的测试/);
  assert.doesNotMatch(app, /\['running', 'queued', 'preparing', 'awaiting_recovery', 'recovering', 'cancelling', 'interrupted'\]/);
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

test("desktop brand retains its horizontal layout while base styles load", () => {
  const styles = readFileSync(appShellStylesPath, "utf8");

  assert.match(styles, /\.brand\s*\{[\s\S]*?display:\s*flex;[\s\S]*?align-items:\s*center;/);
  assert.match(styles, /\.mark\s*\{[\s\S]*?flex:\s*0 0 34px;/);
});

test("upgrade safety remains attached to the offline upgrade operation", () => {
  const app = readFileSync(runtimeSettingsAppPath, "utf8");
  const styles = readFileSync(runtimeSettingsStylesPath, "utf8");

  assert.match(
    app,
    /<article class="panel span-7 upgrade-panel">[\s\S]*?class="upgrade-safety-note"[\s\S]*?UPGRADE SAFETY/,
  );
  assert.doesNotMatch(
    app,
    /<article class="panel span-5"><p class="eyebrow">UPGRADE SAFETY<\/p>/,
  );
  assert.match(styles, /\.upgrade-safety-note/);
  assert.doesNotMatch(styles, /\.page-grid > \.panel:last-child/);
});

test("upgrade panel surfaces a scenario recovery lock before an upload is selected", () => {
  const app = readFileSync(runtimeSettingsAppPath, "utf8");
  const styles = readFileSync(runtimeSettingsStylesPath, "utf8");

  assert.match(app, /const upgradeBlocker = computed/);
  assert.match(app, /availability\?\.ready === false/);
  assert.match(app, /class="upgrade-blocker" v-if="upgradeBlocker"/);
  assert.match(app, /upgradeBlocker\.action_label/);
  assert.match(app, /:disabled="!canUpgrade"/);
  assert.match(styles, /\.upgrade-blocker/);
});

test("trajectory hover resolves the nearest transformed sample, magnetic cursor state, and Beijing time", async () => {
  const page = readFileSync(dashboardPagePath, "utf8");
  const styles = readFileSync(dashboardStylesPath, "utf8");
  const app = readFileSync(dashboardAppPath, "utf8");
  assert.match(page, /id="trajectoryTooltip"/);
  assert.match(page, /id="trajectoryCursor"/);
  assert.match(page, />采样点 <span data-trajectory-counter="index">/);
  assert.doesNotMatch(page, /磁吸采样点/);
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

test("trajectory hover uses the rendered legend height when a relocalization marker is present", async () => {
  const app = readFileSync(dashboardAppPath, "utf8");
  const { mapPointToScreen, trajectoryEvidenceHeight } = await import(
    new URL("autodrive_console/web/trajectory-hover.js", repoRoot),
  );
  const map = { resolution: 1, width: 100, height: 80, origin: [0, 0] };
  const evidenceHeight = trajectoryEvidenceHeight(1, true);

  assert.match(app, /const hasRelocalizationEvidence = \(trajectoryHover\.attempt\.trajectory\?\.relocalizations \|\| \[\]\)\.some\(/);
  assert.match(app, /evidenceHeight: trajectoryEvidenceHeight\(paths\.length, hasRelocalizationEvidence\)/);
  assert.equal(evidenceHeight, 110, "must match trajectory_render.py for one path plus relocalization evidence");
  assert.deepEqual(
    mapPointToScreen(
      { x: 20, y: 20 },
      map,
      {
        canvasWidth: 200,
        canvasHeight: 190,
        imageWidth: 100,
        imageHeight: 190,
        evidenceHeight,
        scale: 1,
        offsetX: 0,
        offsetY: 0,
      },
    ),
    { x: 70, y: 170 },
    "the magnetic cursor must land on the rendered horizontal trajectory, not 17 px above it",
  );
});

test("deployment renderer draws a map-origin callback before localization markers", () => {
  const source = readFileSync(deploymentRendererPath, "utf8");
  assert.match(source, /drawMapOrigin\?\.\(\)/);
  assert.match(source, /drawMapOrigin\?\.\(\)[\s\S]*drawLocalizationMarkers\?\.\(\)/);
});

test("deployment route review requests backend derivation and keeps route facts read-only", () => {
  const deploymentPath = new URL("autodrive_console/web/deployment.js", repoRoot);
  const source = readFileSync(deploymentPath, "utf8");
  assert.match(source, /\/localization-routes\/derive/);
  assert.match(source, /系统按创建项目时的场景地图顺序/);
  assert.match(source, /可通行区域（含虚拟墙约束）/);
  assert.match(source, /返程严格反向/);
  assert.doesNotMatch(source, /data-route-node-move/);
  assert.doesNotMatch(source, /data-route-include/);
  assert.doesNotMatch(source, /localizationGoX|localizationReturnX/);
});

test("automatic route bindings preserve backend scene order", async () => {
  const { automaticRouteBindings } = await import(
    new URL("autodrive_console/web/deployment/localization-route.js", repoRoot),
  );
  const bindings = [
    { id: "lobby" },
    { id: "floor" },
    { id: "unrelated" },
  ];

  assert.deepEqual(
    automaticRouteBindings({ binding_ids: ["floor", "lobby"] }, bindings).map((item) => item.id),
    ["floor", "lobby"],
  );
  assert.deepEqual(automaticRouteBindings({ binding_ids: ["missing"] }, bindings), []);
});

test("automatic route nodes retain only executable transition and component references", async () => {
  const { automaticExecutionNodes } = await import(
    new URL("autodrive_console/web/deployment/localization-route.js", repoRoot),
  );

  assert.deepEqual(
    automaticExecutionNodes({
      execution_nodes: [{
        binding_id: "floor",
        node_refs: [
          { kind: "transition", id: "waypoint-1" },
          { kind: "component", id: "slow-zone-1" },
          { kind: "unsupported", id: "ignore" },
        ],
      }],
    }, "floor"),
    [
      { kind: "transition", id: "waypoint-1" },
      { kind: "component", id: "slow-zone-1" },
    ],
  );
});

test("diagnostic bag payload is absent while disabled and preserves one selected round", async () => {
  const { buildBagRecordingPayload } = await import(new URL("autodrive_console/web/bag-recording-form.js", repoRoot));
  assert.equal(buildBagRecordingPayload({ enabled: false, attemptIndex: 2, topics: ["/odom"] }), null);
  assert.deepEqual(buildBagRecordingPayload({ enabled: true, attemptIndex: 2, topics: ["/odom"] }), {
    attemptIndex: 2, topics: ["/odom"],
  });
  assert.equal(buildBagRecordingPayload({ enabled: true, attemptIndex: 0, topics: [] }), null);
});

test("diagnostic archive page resumes one fresh status request after returning to the tab", () => {
  const page = readFileSync(bagRecordingsPagePath, "utf8");
  const app = readFileSync(bagRecordingsAppPath, "utf8");

  assert.match(page, /<script src="\/theme_bootstrap\.js"><\/script>/);
  assert.match(app, /document\.addEventListener\('visibilitychange'/);
  assert.match(app, /if \(document\.visibilityState === 'visible'\)/);
  assert.match(app, /let loadInFlight = false/);
  assert.match(app, /if \(loadInFlight\) return/);
});

test("scenario activation panel stays absent until an activation exists", () => {
  const page = readFileSync(new URL("autodrive_console/web/scenario-setup.html", repoRoot), "utf8");
  const styles = readFileSync(new URL("autodrive_console/web/scenario_setup.css", repoRoot), "utf8");

  assert.match(page, /id="activationState"[^>]*hidden/);
  assert.match(styles, /\.scenario-activation\[hidden\]\s*\{\s*display:\s*none/);
});

test("software inventory is a Desktop system tool with a guarded editable version matrix", () => {
  const appShell = readFileSync(new URL("autodrive_console/web/app_shell.js", repoRoot), "utf8");
  const page = readFileSync(new URL("autodrive_console/web/software-inventory.html", repoRoot), "utf8");
  const script = readFileSync(new URL("autodrive_console/web/software_inventory.js", repoRoot), "utf8");

  assert.match(appShell, /software-inventory\.html/);
  assert.match(page, /车架号/);
  assert.match(page, /id="saveInventory"/);
  assert.match(page, /id="exportInventory"[^>]*disabled/);
  assert.match(page, /aria-live="polite"/);
  assert.match(script, /\/api\/software-inventory/);
  assert.match(script, /requestSequence/);
  assert.match(script, /lastSuccessfulSnapshot/);
  assert.match(script, /package_name/);
  assert.match(script, /saveInventory\.disabled/);
});

test("software inventory export uses only the displayed snapshot and native Canvas PNG downloads", () => {
  const script = readFileSync(new URL("autodrive_console/web/software_inventory.js", repoRoot), "utf8");
  const renderer = readFileSync(new URL("autodrive_console/web/software-inventory-export.js", repoRoot), "utf8");

  assert.match(script, /canvas\.toBlob/);
  assert.match(script, /Asia\/Shanghai/);
  assert.match(renderer, /数据来源：本机已安装/);
  assert.match(script, /lastSuccessfulSnapshot/);
  assert.match(script, /pageIndex/);
  assert.match(script, /sanitizeFilenameSegment/);
});
