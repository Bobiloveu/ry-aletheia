import assert from "node:assert/strict";
import test from "node:test";

import {
  isCurrentExecutionStatusRequest,
  normalizeExecutionStatus,
  shouldRenderExecutionStatus,
} from "../../autodrive_console/web/vehicle_execution_status.js";

test("execution status accepts only a complete approved response tuple", () => {
  assert.deepEqual(
    normalizeExecutionStatus({ phase: "riding_elevator", label: "乘梯中" }),
    { phase: "riding_elevator", label: "乘梯中" },
  );
  assert.deepEqual(normalizeExecutionStatus({ phase: "riding_elevator" }), {
    phase: "unavailable",
    label: "状态暂不可用",
  });
  assert.deepEqual(normalizeExecutionStatus({ phase: "unknown", label: "未知" }), {
    phase: "unavailable",
    label: "状态暂不可用",
  });
});

test("execution status does not reset animation for an unchanged state", () => {
  assert.equal(
    shouldRenderExecutionStatus(
      { phase: "riding_elevator", label: "乘梯中" },
      { phase: "riding_elevator", label: "乘梯中" },
    ),
    false,
  );
  assert.equal(
    shouldRenderExecutionStatus(
      { phase: "riding_elevator", label: "乘梯中" },
      { phase: "entering_elevator", label: "进梯中" },
    ),
    true,
  );
});

test("a late polling response cannot replace a newer status", () => {
  assert.equal(isCurrentExecutionStatusRequest(2, 2), true);
  assert.equal(isCurrentExecutionStatusRequest(1, 2), false);
});
