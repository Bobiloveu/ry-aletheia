import assert from "node:assert/strict";
import test from "node:test";

import { createCanvasDrawScheduler } from "../../../autodrive_console/web/deployment/canvas-scheduler.js";

test("high-frequency map interactions coalesce redraws to one animation frame", () => {
  let queued = null;
  let draws = 0;
  const schedule = createCanvasDrawScheduler(
    () => { draws += 1; },
    (callback) => { queued = callback; return 1; },
  );

  schedule();
  schedule();
  schedule();

  assert.equal(draws, 0);
  assert.ok(queued);
  queued();
  assert.equal(draws, 1);
  schedule();
  queued();
  assert.equal(draws, 2);
});
