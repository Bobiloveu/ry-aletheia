import assert from "node:assert/strict";
import test from "node:test";

import { formatFileSize, formatUnixSeconds } from "../../../autodrive_console/web/platform/format.js";

test("formatFileSize preserves Robot Logs binary units", () => {
  assert.equal(formatFileSize(0), "0 B");
  assert.equal(formatFileSize(1023), "1023 B");
  assert.equal(formatFileSize(1024), "1.0 KiB");
  assert.equal(formatFileSize(1024 * 1024), "1.00 MiB");
});

test("formatFileSize treats invalid input as zero", () => {
  assert.equal(formatFileSize(Number.NaN), "0 B");
  assert.equal(formatFileSize("not-a-size"), "0 B");
});

test("formatUnixSeconds forwards a valid Unix second value to localized time", () => {
  const seconds = 1_700_000_000;
  assert.equal(
    formatUnixSeconds(seconds, "en-CA"),
    new Date(seconds * 1000).toLocaleString("en-CA", { hour12: false }),
  );
});

test("formatUnixSeconds labels invalid timestamps", () => {
  assert.equal(formatUnixSeconds("not-a-time"), "未知时间");
});
