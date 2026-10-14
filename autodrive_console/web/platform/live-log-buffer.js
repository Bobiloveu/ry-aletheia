export const MAX_LIVE_PENDING_CHARS = 16 * 1024;
export const MAX_LIVE_LINE_CHARS = 4 * 1024;

function segmentLine(value) {
  const text = String(value ?? "");
  if (!text) return [""];
  const segments = [];
  for (let offset = 0; offset < text.length; offset += MAX_LIVE_LINE_CHARS)
    segments.push(text.slice(offset, offset + MAX_LIVE_LINE_CHARS));
  return segments;
}

/**
 * Convert one decoded stdout chunk into complete display lines. Oversized lines
 * are split into consecutive display rows, never truncated. The unfinished
 * tail remains bounded so a producer that never sends `\n` cannot retain an
 * ever-growing JavaScript string in the browser.
 */
export function splitLiveLogText(pending, chunk) {
  const fragments = `${String(pending ?? "")}${String(chunk ?? "")}`.split("\n");
  let nextPending = fragments.pop() || "";
  const lines = fragments.flatMap(segmentLine);
  while (nextPending.length > MAX_LIVE_PENDING_CHARS) {
    lines.push(nextPending.slice(0, MAX_LIVE_LINE_CHARS));
    nextPending = nextPending.slice(MAX_LIVE_LINE_CHARS);
  }
  return { lines, pending: nextPending };
}

/** Preserve every decoded line until the renderer consumes it. */
export function appendLiveLogLines(queue, lines) {
  if (!Array.isArray(queue)) throw new TypeError("queue 必须是数组");
  if (Array.isArray(lines) && lines.length) queue.push(...lines);
  return queue.length;
}
