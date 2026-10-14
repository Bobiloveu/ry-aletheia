import assert from "node:assert/strict";
import test from "node:test";

import { applyLiveLogWindowAction, liveLogWindowLayout } from "../../../autodrive_console/web/platform/live-log-window.js";

test("maximizing one live log gives it the workspace without closing the other streams", () => {
  const logs = [
    { id: "lidar", minimized: false },
    { id: "chassis", minimized: false },
    { id: "lightning", minimized: true },
  ];

  const next = applyLiveLogWindowAction(logs, null, { type: "maximize", id: "chassis" });

  assert.equal(next.focusedId, "chassis");
  assert.deepEqual(next.logs, logs);
  assert.deepEqual(liveLogWindowLayout(next.logs, next.focusedId), {
    focusedId: "chassis",
    visibleIds: ["lidar", "chassis"],
    minimizedIds: ["lightning"],
  });
});

test("minimizing the focused live log exits focus instead of leaving a blank workspace", () => {
  const logs = [
    { id: "lidar", minimized: false },
    { id: "chassis", minimized: false },
  ];

  const next = applyLiveLogWindowAction(logs, "chassis", { type: "minimize", id: "chassis" });

  assert.equal(next.focusedId, null);
  assert.deepEqual(next.logs, [
    { id: "lidar", minimized: false },
    { id: "chassis", minimized: true },
  ]);
  assert.deepEqual(liveLogWindowLayout(next.logs, next.focusedId), {
    focusedId: null,
    visibleIds: ["lidar"],
    minimizedIds: ["chassis"],
  });
});
