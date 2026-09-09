import { requestJson } from "./platform/http.js";

const UNAVAILABLE_STATUS = Object.freeze({ phase: "unavailable", label: "状态暂不可用" });
const ALLOWED_PHASES = new Set([
  "task",
  "calling_elevator",
  "entering_elevator",
  "riding_elevator",
  "exiting_elevator",
  "closing_elevator_door",
  "opening_gate",
  "closing_gate",
  "opening_access_door",
  "closing_access_door",
  "draining_or_unloading",
  "completed",
  "restarting_nodes",
  "unavailable",
]);

export function normalizeExecutionStatus(payload) {
  const phase = typeof payload?.phase === "string" ? payload.phase : "";
  const label = typeof payload?.label === "string" ? payload.label.trim() : "";
  return ALLOWED_PHASES.has(phase) && label ? { phase, label } : { ...UNAVAILABLE_STATUS };
}

export function shouldRenderExecutionStatus(previous, next) {
  return previous?.phase !== next.phase || previous?.label !== next.label;
}

export function isCurrentExecutionStatusRequest(requestGeneration, currentGeneration) {
  return requestGeneration === currentGeneration;
}

export function startExecutionStatusPolling({
  documentRef = document,
  requestStatus = () => requestJson("/api/vehicle-execution-status", {}, { errorMessage: "状态暂不可用" }),
  intervalMs = 1000,
} = {}) {
  const label = documentRef.getElementById("vehicleExecutionLabel");
  if (!label) return () => {};

  let rendered = null;
  let requestGeneration = 0;
  const render = (next) => {
    if (!shouldRenderExecutionStatus(rendered, next)) return;
    rendered = next;
    documentRef.body.dataset.phase = next.phase;
    label.textContent = next.label;
  };
  const refresh = async () => {
    const thisRequest = ++requestGeneration;
    let next = UNAVAILABLE_STATUS;
    try {
      next = normalizeExecutionStatus(await requestStatus());
    } catch (_) {
      next = UNAVAILABLE_STATUS;
    }
    if (isCurrentExecutionStatusRequest(thisRequest, requestGeneration)) render(next);
  };

  refresh();
  const timer = globalThis.setInterval(refresh, intervalMs);
  return () => globalThis.clearInterval(timer);
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => startExecutionStatusPolling(), { once: true });
}
