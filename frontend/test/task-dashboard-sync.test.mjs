import assert from "node:assert/strict";
import test from "node:test";

import { taskDashboardRefreshDelay } from "../../autodrive_console/web/task_dashboard_sync.js";

test("task dashboard continues a low-rate poll while idle so externally created runs appear", () => {
  assert.equal(taskDashboardRefreshDelay(null), 3000);
});

test("task dashboard uses the active cadence while a run is executing", () => {
  assert.equal(taskDashboardRefreshDelay({ status: "running" }), 1000);
});
