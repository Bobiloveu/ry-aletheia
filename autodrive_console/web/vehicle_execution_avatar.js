import { BotEngine } from "./vendor/bloub/engine.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const PAPER = "#f8fafc";
const INK = "#10192c";
const DEFAULT_THEME = Object.freeze({ ink: INK, notification: "#3b82f6", monochrome: false });
const EMERGENCY_THEME = Object.freeze({ ink: "#dc2626", notification: "#dc2626", monochrome: true });
const VIEWBOX_RADIUS = 150;
const ENGINE_RADIUS = 100;
const MASK_ID = "vehicle-execution-avatar-mask";

// These are display-only choices. The vehicle phase remains the source of
// truth; this table only selects the most readable upstream expression.
const BLOUB_STATE_BY_EXECUTION_PHASE = Object.freeze({
  idle: "idle",
  emergency_stop: "alert",
  manual_control: "hexagon",
  task: "play",
  calling_elevator: "notify",
  entering_elevator: "comet",
  riding_elevator: "egg",
  exiting_elevator: "burst",
  opening_gate: "wide",
  closing_gate: "exclaim",
  opening_access_door: "wide",
  closing_access_door: "sleep",
  closing_elevator_door: "wink",
  draining_or_unloading: "thinking",
  completed: "orbit",
  restarting_nodes: "swirl",
  unavailable: "idle",
});

export function avatarStateForExecutionPhase(phase) {
  return BLOUB_STATE_BY_EXECUTION_PHASE[phase] || "idle";
}

export function avatarThemeForExecutionPhase(phase) {
  return phase === "emergency_stop" ? EMERGENCY_THEME : DEFAULT_THEME;
}

export function shouldAnimateExecutionAvatar(phase, motionAllowed) {
  return Boolean(motionAllowed) && phase !== "unavailable" && phase !== "idle";
}

function svgElement(name) {
  return document.createElementNS(SVG_NS, name);
}

function setAttributes(element, attributes) {
  for (const [name, value] of Object.entries(attributes)) {
    if (value !== undefined && value !== null) element.setAttribute(name, String(value));
  }
  return element;
}

function appendDot(container, dot, theme) {
  const element = svgElement(dot.d ? "path" : "circle");
  const color = theme.monochrome ? theme.ink : dot.color || theme.ink;
  if (dot.d) {
    setAttributes(element, {
      d: dot.d,
      transform: `translate(${dot.x} ${dot.y}) rotate(${dot.rot || 0}) scale(${ENGINE_RADIUS})`,
      fill: color,
      opacity: dot.opacity,
    });
  } else {
    setAttributes(element, {
      cx: dot.x,
      cy: dot.y,
      r: dot.r,
      fill: color,
      opacity: dot.opacity,
    });
  }
  container.append(element);
}

function appendArcGradients(definitions, arcs, theme) {
  for (const arc of arcs) {
    const gradient = setAttributes(svgElement("linearGradient"), {
      id: `${MASK_ID}-${arc.id}`,
      gradientUnits: "userSpaceOnUse",
      x1: arc.grad.x1,
      y1: arc.grad.y1,
      x2: arc.grad.x2,
      y2: arc.grad.y2,
    });
    const colors = theme.monochrome ? arc.grad.stops.map(() => theme.ink) : arc.grad.stops;
    colors.forEach((color, index) => {
      gradient.append(
        setAttributes(svgElement("stop"), {
          offset: index / Math.max(1, arc.grad.stops.length - 1),
          "stop-color": color,
        }),
      );
    });
    definitions.append(gradient);
  }
}

function appendArcs(container, arcs, half) {
  for (const arc of arcs) {
    const path = arc[half];
    if (!path) continue;
    container.append(
      setAttributes(svgElement("path"), {
        d: path,
        stroke: `url(#${MASK_ID}-${arc.id})`,
        "stroke-width": arc.width,
        opacity: arc.opacity,
        fill: "none",
        "stroke-linecap": "round",
      }),
    );
  }
}

/**
 * Thin DOM adapter around the vendored Bloub engine. It intentionally knows
 * nothing about vehicle data or polling; callers provide only an execution
 * phase and this adapter owns a single requestAnimationFrame lifecycle.
 */
export class VehicleExecutionAvatar {
  constructor(host, { reducedMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches } = {}) {
    this.host = host;
    this.motionAllowed = !reducedMotion;
    this.engine = new BotEngine(ENGINE_RADIUS, "idle");
    this.phase = "idle";
    this.clock = 0;
    this.lastTimestamp = 0;
    this.frameRequest = 0;
    this.svg = setAttributes(svgElement("svg"), {
      class: "execution-avatar",
      viewBox: `${-VIEWBOX_RADIUS} ${-VIEWBOX_RADIUS} ${VIEWBOX_RADIUS * 2} ${VIEWBOX_RADIUS * 2}`,
      focusable: "false",
      "aria-hidden": "true",
    });
    this.host.replaceChildren(this.svg);
    this.render();
  }

  setPhase(phase) {
    if (phase === this.phase) return;
    this.phase = phase;
    const state = avatarStateForExecutionPhase(phase);
    if (phase === "unavailable" || !this.motionAllowed) this.engine.reset(state, this.clock);
    else this.engine.setState(state, this.clock);
    this.render();
    if (shouldAnimateExecutionAvatar(phase, this.motionAllowed)) this.start();
    else this.stop();
  }

  start() {
    if (this.frameRequest) return;
    this.lastTimestamp = 0;
    this.frameRequest = globalThis.requestAnimationFrame((timestamp) => this.tick(timestamp));
  }

  stop() {
    if (!this.frameRequest) return;
    globalThis.cancelAnimationFrame(this.frameRequest);
    this.frameRequest = 0;
    this.lastTimestamp = 0;
  }

  destroy() {
    this.stop();
    this.host.replaceChildren();
  }

  tick(timestamp) {
    const elapsed = this.lastTimestamp ? Math.min((timestamp - this.lastTimestamp) / 1000, 0.064) : 0;
    this.lastTimestamp = timestamp;
    this.clock += elapsed;
    this.render();
    this.frameRequest = globalThis.requestAnimationFrame((nextTimestamp) => this.tick(nextTimestamp));
  }

  render() {
    const frame = this.engine.sample(this.clock);
    const theme = avatarThemeForExecutionPhase(this.phase);
    const definitions = svgElement("defs");
    const mask = setAttributes(svgElement("mask"), {
      id: MASK_ID,
      maskUnits: "userSpaceOnUse",
      x: -VIEWBOX_RADIUS,
      y: -VIEWBOX_RADIUS,
      width: VIEWBOX_RADIUS * 2,
      height: VIEWBOX_RADIUS * 2,
    });
    mask.append(setAttributes(svgElement("path"), { d: frame.bodyPath, fill: "#fff" }));
    for (const eye of frame.eyes) {
      mask.append(setAttributes(svgElement("path"), {
        d: eye.d,
        transform: eye.matrix,
        opacity: eye.alpha,
        fill: "#000",
      }));
    }
    if (frame.notch) {
      mask.append(setAttributes(svgElement("circle"), {
        cx: frame.notch.x,
        cy: frame.notch.y,
        r: frame.notch.r,
        fill: "#000",
      }));
    }
    definitions.append(mask);
    appendArcGradients(definitions, frame.arcs, theme);

    const arcsBehind = svgElement("g");
    appendArcs(arcsBehind, frame.arcs, "back");

    const dotsBehind = svgElement("g");
    if (frame.dotsBehind) frame.dots.forEach((dot) => appendDot(dotsBehind, dot, theme));

    const body = setAttributes(svgElement("g"), { opacity: frame.bodyAlpha });
    body.append(setAttributes(svgElement("path"), { d: frame.bodyPath, fill: PAPER }));
    const ink = setAttributes(svgElement("g"), { mask: `url(#${MASK_ID})` });
    ink.append(setAttributes(svgElement("rect"), {
      x: -VIEWBOX_RADIUS,
      y: -VIEWBOX_RADIUS,
      width: VIEWBOX_RADIUS * 2,
      height: VIEWBOX_RADIUS * 2,
      fill: theme.ink,
    }));
    body.append(ink);

    const dotsFront = svgElement("g");
    if (!frame.dotsBehind) frame.dots.forEach((dot) => appendDot(dotsFront, dot, theme));

    const arcsFront = svgElement("g");
    appendArcs(arcsFront, frame.arcs, "front");

    const nodes = [definitions, arcsBehind, dotsBehind, body, dotsFront];
    if (frame.notif) {
      nodes.push(setAttributes(svgElement("circle"), {
        cx: frame.notif.x,
        cy: frame.notif.y,
        r: frame.notif.r,
        fill: theme.notification,
      }));
    }
    nodes.push(arcsFront);
    this.svg.replaceChildren(...nodes);
  }
}
