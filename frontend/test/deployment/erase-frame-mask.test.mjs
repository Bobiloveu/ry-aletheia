import { strict as assert } from "node:assert";
import test from "node:test";

import { createEraseFrameMask } from "../../../autodrive_console/web/deployment/erase-frame-mask.js";

test("erase frame mask stays above redraws until one completed replacement frame", () => {
  const events = [];
  const frames = [];
  const mask = createEraseFrameMask({
    capture: () => events.push("capture"),
    show: () => events.push("show"),
    hide: () => events.push("hide"),
    requestFrame: (callback) => { frames.push(callback); return frames.length; },
  });

  mask.cover();
  mask.revealAfterPaint();

  assert.deepEqual(events, ["capture", "show"]);
  assert.equal(frames.length, 1);
  frames.shift()();
  assert.deepEqual(events, ["capture", "show"]);
  assert.equal(frames.length, 1);
  frames.shift()();
  assert.deepEqual(events, ["capture", "show", "hide"]);
});
