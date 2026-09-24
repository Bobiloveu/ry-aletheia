import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { activeAcceptancePlanSelection, multiAcceptanceOptions } from "../../autodrive_console/web/acceptance_preparation.js";

const html = readFileSync(fileURLToPath(new URL("../../autodrive_console/web/acceptance-test.html", import.meta.url)), "utf8");
const css = readFileSync(fileURLToPath(new URL("../../autodrive_console/web/acceptance_test.css", import.meta.url)), "utf8");
const controller = readFileSync(fileURLToPath(new URL("../../autodrive_console/web/acceptance_test.js", import.meta.url)), "utf8");

test("active R6B plan freezes the mode together with scope", () => {
  assert.equal(activeAcceptancePlanSelection({ status: "running", execution_mode: "multi_r6b", scope_type: "community", community: "数创大厦", mode: "full" }).executionMode, "multi_r6b");
});

test("multi destination payload leaves destination generation to the backend", () => {
  const options = multiAcceptanceOptions({
    chainMode: "chain",
    maxPointsPerTask: 7,
    floorRanges: [{ building: 6, unit: 1, min_floor: 3, max_floor: 25 }],
  });
  assert.deepEqual(options, {
    out_eguard: false,
    return_origin: false,
    chain_mode: "chain",
    max_points_per_task: 7,
    floor_ranges: [{ building: 6, unit: 1, min_floor: 3, max_floor: 25 }],
  });
});

test("R6B template ranges are operator-configured in the acceptance scope", () => {
  assert.match(html, /id="multiFloorRanges"/);
  assert.match(html, /id="multiFloorRangeRows"/);
  assert.match(controller, /floorRanges: readFloorRanges\(\)/);
  assert.match(controller, /自动排除 0 层/);
});

test("R6B random chain size is configured independently from the sampled task count", () => {
  assert.match(html, /id="multiMaxPoints"[^>]*type="number"[^>]*min="1"[^>]*max="10"/);
  assert.match(controller, /const maxPointsPerTask = Number\(\$\('multiMaxPoints'\)\.value\)/);
  assert.match(controller, /每条任务随机 1～/);
  assert.match(controller, /单任务最多配送点必须是 1 到 10 的整数/);
});

test("multi-point coverage summary distinguishes tasks from delivery points", () => {
  assert.match(controller, /summary\.delivery_points/);
  assert.match(controller, /条任务/);
  assert.match(controller, /个配送点/);
});

test("R6B options keep the chain control visible and follow the light theme", () => {
  assert.doesNotMatch(html, /#multiTaskOptions > \.form-grid > label:last-child/);
  assert.match(css, /\.multi-task-options \.form-grid/);
  assert.match(css, /body\.theme-light \.multi-task-options/);
});

test("plan rows keep the ROS task preview collapsed by default", () => {
  assert.match(controller, /className = 'task-preview'/);
  assert.match(controller, /summary\.textContent = '查看指令'/);
  assert.match(css, /\.task-preview/);
});

test("plan rows summarize destinations without leaking long identifiers into the layout", () => {
  assert.match(controller, /className = 'plan-destination-row'/);
  assert.match(controller, /destination-summary-list/);
  assert.match(css, /\.plan-destination-row/);
  assert.match(css, /\.acceptance-card > \.table-wrap table\s*\{[^}]*table-layout:\s*fixed/s);
});

test("task previews stay in the table flow instead of being clipped by the scrolling wrapper", () => {
  assert.match(css, /\.task-preview-content\s*\{[^}]*position:\s*static/s);
  assert.doesNotMatch(css, /\.task-preview-content\s*\{[^}]*position:\s*absolute/s);
});

test("task preview content gets a full-width row instead of the narrow command cell", () => {
  assert.match(controller, /className = 'task-preview-trigger'/);
  assert.match(controller, /className = 'task-preview-row'/);
  assert.match(css, /\.task-preview-row td/);
});

test("task preview keeps readable surfaces in the light theme", () => {
  assert.match(css, /body\.theme-light \.task-preview-content\s*\{[^}]*background:\s*#fff/s);
  assert.match(css, /body\.theme-light \.task-preview-row td/);
  assert.match(css, /body\.theme-light \.plan-destination-row td/);
});

test("plan polling preserves the open task preview across table rerenders", () => {
  assert.match(controller, /openTaskPreviews:\s*new Set\(\)/);
  assert.match(controller, /const previewKey = `\$\{plan\?\.plan_id/);
  assert.match(controller, /state\.openTaskPreviews\.has\(previewKey\)/);
  assert.match(controller, /state\.openTaskPreviews\.(?:add|delete)\(previewKey\)/);
});
