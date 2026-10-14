import assert from "node:assert/strict";
import test from "node:test";

import { appendLiveLogLines, splitLiveLogText } from "../../../autodrive_console/web/platform/live-log-buffer.js";

test("a never-terminated stdout fragment is segmented without losing bytes or retaining an unbounded pending string", () => {
  const source = "x".repeat(32_768);
  const parsed = splitLiveLogText("", source);

  assert.equal([...parsed.lines, parsed.pending].join(""), source);
  assert.ok(parsed.pending.length <= 16_384);
  assert.ok(parsed.lines.every((line) => line.length <= 4_096));
});

test("a busy stdout queue retains every pending line until the renderer consumes it", () => {
  const queued = Array.from({ length: 256 }, (_, index) => `old-${index}`);
  appendLiveLogLines(queued, ["new-1", "new-2", "new-3"]);

  assert.equal(queued.length, 259);
  assert.equal(queued[0], "old-0");
  assert.deepEqual(queued.slice(-3), ["new-1", "new-2", "new-3"]);
});
