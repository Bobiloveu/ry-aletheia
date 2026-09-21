const DIRECTION_AXES = Object.freeze({
  forward: Object.freeze({ linear: 1, angular: 0 }),
  backward: Object.freeze({ linear: -1, angular: 0 }),
  left: Object.freeze({ linear: 0, angular: 1 }),
  right: Object.freeze({ linear: 0, angular: -1 }),
});

const KEYBOARD_COMMANDS = Object.freeze(["forward", "backward", "left", "right"]);
const VALID_KEYBOARD_CODES = /^(?:Key[A-Z]|Digit[0-9]|Numpad[0-9]|Arrow(?:Up|Down|Left|Right))$/;

export const DEFAULT_KEYBOARD_BINDINGS = Object.freeze({
  forward: "KeyI",
  backward: "KeyK",
  left: "KeyJ",
  right: "KeyL",
});

/**
 * Keep browser-stored key preferences within the safe movement-key subset.
 * Every direction must have one distinct physical key so a corrupt preference
 * can never create ambiguous or unreachable manual input.
 */
export function normalizeKeyboardBindings(candidate) {
  if (!candidate || typeof candidate !== "object") return { ...DEFAULT_KEYBOARD_BINDINGS };
  const bindings = {};
  const assignedCodes = new Set();
  for (const command of KEYBOARD_COMMANDS) {
    const code = candidate[command];
    if (typeof code !== "string" || !VALID_KEYBOARD_CODES.test(code) || assignedCodes.has(code)) {
      return { ...DEFAULT_KEYBOARD_BINDINGS };
    }
    assignedCodes.add(code);
    bindings[command] = code;
  }
  return bindings;
}

export function commandForKeyboardCode(code, bindings) {
  const normalized = normalizeKeyboardBindings(bindings);
  return KEYBOARD_COMMANDS.find((command) => normalized[command] === code) || null;
}

export function isBindableKeyboardCode(code) {
  return typeof code === "string" && VALID_KEYBOARD_CODES.test(code);
}

export function keyboardCodeLabel(code) {
  const arrowLabels = {
    ArrowUp: "↑",
    ArrowDown: "↓",
    ArrowLeft: "←",
    ArrowRight: "→",
  };
  if (arrowLabels[code]) return arrowLabels[code];
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  if (/^Numpad[0-9]$/.test(code)) return `数字键盘 ${code.slice(6)}`;
  return "—";
}

/**
 * Convert concurrently held directions into a bounded velocity vector.
 *
 * The vehicle only supports forward/backward velocity plus yaw, not lateral
 * translation.  A forward/left pair therefore means a forward-left arc.
 */
export function vectorForActiveCommands(commands) {
  let linearRatio = 0;
  let angularRatio = 0;
  for (const command of commands) {
    const axis = DIRECTION_AXES[command];
    if (!axis) continue;
    linearRatio += axis.linear;
    angularRatio += axis.angular;
  }
  return {
    linearRatio: Math.max(-1, Math.min(1, linearRatio)),
    angularRatio: Math.max(-1, Math.min(1, angularRatio)),
  };
}

export function vectorsEqual(first, second) {
  return first.linearRatio === second.linearRatio && first.angularRatio === second.angularRatio;
}
