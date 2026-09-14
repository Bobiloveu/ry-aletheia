import assert from "node:assert/strict";
import test from "node:test";

import {
  isCurrentExecutionStatusRequest,
  normalizeExecutionStatus,
  shouldRenderExecutionStatus,
} from "../../autodrive_console/web/vehicle_execution_status.js";
import {
  avatarStateForExecutionPhase,
  avatarThemeForExecutionPhase,
  shouldAnimateExecutionAvatar,
} from "../../autodrive_console/web/vehicle_execution_avatar.js";

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

test("execution status accepts emergency and confirmed manual display phases", () => {
  assert.deepEqual(normalizeExecutionStatus({ phase: "idle", label: "空闲中" }), {
    phase: "idle",
    label: "空闲中",
  });
  assert.deepEqual(normalizeExecutionStatus({ phase: "emergency_stop", label: "急停已触发" }), {
    phase: "emergency_stop",
    label: "急停已触发",
  });
  assert.deepEqual(normalizeExecutionStatus({ phase: "manual_control", label: "手动控制中" }), {
    phase: "manual_control",
    label: "手动控制中",
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

test("execution phases use distinct Bloub expressions for the major vehicle behaviours", () => {
  assert.equal(avatarStateForExecutionPhase("idle"), "idle");
  assert.equal(avatarStateForExecutionPhase("emergency_stop"), "alert");
  assert.equal(avatarStateForExecutionPhase("manual_control"), "hexagon");
  assert.equal(avatarStateForExecutionPhase("task"), "play");
  assert.equal(avatarStateForExecutionPhase("calling_elevator"), "notify");
  assert.equal(avatarStateForExecutionPhase("entering_elevator"), "comet");
  assert.equal(avatarStateForExecutionPhase("riding_elevator"), "egg");
  assert.equal(avatarStateForExecutionPhase("exiting_elevator"), "burst");
  assert.equal(avatarStateForExecutionPhase("opening_gate"), "wide");
  assert.equal(avatarStateForExecutionPhase("closing_gate"), "exclaim");
  assert.equal(avatarStateForExecutionPhase("opening_access_door"), "wide");
  assert.equal(avatarStateForExecutionPhase("closing_access_door"), "sleep");
  assert.equal(avatarStateForExecutionPhase("closing_elevator_door"), "wink");
  assert.equal(avatarStateForExecutionPhase("draining_or_unloading"), "thinking");
  assert.equal(avatarStateForExecutionPhase("completed"), "orbit");
  assert.equal(avatarStateForExecutionPhase("restarting_nodes"), "swirl");
  assert.equal(avatarStateForExecutionPhase("unavailable"), "idle");
  assert.equal(avatarStateForExecutionPhase("not-a-real-phase"), "idle");
  assert.equal(shouldAnimateExecutionAvatar("riding_elevator", true), true);
  assert.equal(shouldAnimateExecutionAvatar("task", true), true);
  assert.equal(shouldAnimateExecutionAvatar("unavailable", true), false);
  assert.equal(shouldAnimateExecutionAvatar("idle", true), false);
  assert.equal(shouldAnimateExecutionAvatar("riding_elevator", false), false);
});

test("emergency execution state uses the red alert avatar theme", () => {
  assert.deepEqual(avatarThemeForExecutionPhase("emergency_stop"), {
    ink: "#dc2626",
    notification: "#dc2626",
    monochrome: true,
  });
  assert.notDeepEqual(avatarThemeForExecutionPhase("task"), avatarThemeForExecutionPhase("emergency_stop"));
});
