import assert from "node:assert/strict";
import test from "node:test";

import {
  commandForKeyboardCode,
  DEFAULT_KEYBOARD_BINDINGS,
  normalizeKeyboardBindings,
  vectorForActiveCommands,
} from "../../autodrive_console/web/manual_control_input.js";

test("keyboard command combinations produce bounded arc-motion vectors", () => {
  assert.deepEqual(vectorForActiveCommands(new Set(["forward", "left"])), {
    linearRatio: 1,
    angularRatio: 1,
  });
  assert.deepEqual(vectorForActiveCommands(new Set(["backward", "right"])), {
    linearRatio: -1,
    angularRatio: -1,
  });
});

test("opposite held directions cancel only their own axis", () => {
  assert.deepEqual(vectorForActiveCommands(new Set(["forward", "backward", "left"])), {
    linearRatio: 0,
    angularRatio: 1,
  });
  assert.deepEqual(vectorForActiveCommands(new Set()), {
    linearRatio: 0,
    angularRatio: 0,
  });
});

test("a complete custom key map drives the direction selected by its physical key", () => {
  const bindings = normalizeKeyboardBindings({
    forward: "KeyW",
    backward: "KeyS",
    left: "KeyA",
    right: "KeyD",
  });

  assert.equal(commandForKeyboardCode("KeyW", bindings), "forward");
  assert.equal(commandForKeyboardCode("KeyA", bindings), "left");
  assert.equal(commandForKeyboardCode("KeyI", bindings), null);
});

test("a malformed or duplicate custom key map falls back to the safe defaults", () => {
  assert.deepEqual(normalizeKeyboardBindings({
    forward: "KeyW",
    backward: "KeyS",
    left: "KeyW",
    right: "Escape",
  }), DEFAULT_KEYBOARD_BINDINGS);
});
