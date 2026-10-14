import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import * as geometry from "../../../autodrive_console/web/deployment/canvas-geometry.js";

const source = readFileSync(new URL("../../../autodrive_console/web/deployment.js", import.meta.url), "utf8");
const functionSource = name => {
  const start = source.indexOf(`function ${name}(`);
  return source.slice(start, source.indexOf("\n}", start) + 2);
};
const downStart = source.indexOf("  if (rotateHandleAt(event)) {");
const downEnd = source.indexOf("  if (resizeHandleAt(event)) {", downStart);
const moveStart = source.indexOf('canvas.addEventListener("pointermove"');
const rotateStart = source.indexOf("    if (componentRotate) {", moveStart);
const rotateEnd = source.indexOf("    if (!drag) {", rotateStart);
const radians = degrees => degrees * Math.PI / 180;
const pointerAt = degrees => ({ x: 100 + 100 * Math.cos(radians(degrees)), y: 100 - 100 * Math.sin(radians(degrees)) });

function editor(mode, yaw, initialPointer) {
  const item = { id: "marker", x: 1, y: 2, yaw: radians(yaw) };
  const state = {
    ...geometry,
    selectedProject: { id: "p" }, deploymentProjectGeneration: 1,
    selectedComponent: mode === "componentRotate" ? item : null,
    selectedWaypoint: mode === "waypointRotate" ? item : null,
    componentRotate: null, waypointRotate: null, annotationGesture: null,
    pendingComponentYaw: null, pendingWaypointYaw: null,
    canvas: { style: {}, setPointerCapture() {} }, activeTool: "pan",
    rotateHandleAt: () => mode === "componentRotate",
    transitionRotateHandleAt: () => mode === "waypointRotate",
    canvasPointFromEvent: event => event.point,
    componentCanvasPoint: () => ({ x: 100, y: 100 }),
    worldCanvasPoint: () => ({ x: 100, y: 100 }),
    scheduleMapDraw() { state.paintedYaw = item.yaw; },
  };
  runInNewContext([
    functionSource("beginAnnotationGesture"),
    `function down(event) { ${source.slice(downStart, downEnd)} }`,
    `function move(event) { ${source.slice(rotateStart, rotateEnd)} }`,
  ].join("\n"), state);
  state.down({ pointerId: 1, point: initialPointer });
  return { item, move(point) { state.move({ pointerId: 1, point }); return state.paintedYaw * 180 / Math.PI; } };
}

for (const mode of ["componentRotate", "waypointRotate"]) {
  for (const [name, yaw, start, positions, expected] of [
    ["stationary off-axis handle does not jump", 0, -55, [-55], [0]],
    ["counterclockwise drag starts from the pressed handle", 0, -55, [-53, -45, -35], [0, 10, 20]],
    ["clockwise drag follows the pointer", 0, -55, [-65, -75], [-10, -20]],
    ["already rotated component retains its starting yaw", 70, 15, [15, 25, 5], [70, 80, 60]],
    ["unsnapped starting yaw does not jump", 23, -32, [-32, -22], [23, 33]],
    ["pointer angle crosses the atan2 boundary smoothly", -130, 175, [-175, -165], [-120, -110]],
    ["yaw wraps through positive 180 degrees", 170, 115, [125, 135, 145], [180, -170, -160]],
    ["yaw wraps through negative 180 degrees", -170, 135, [125, 115, 105], [-180, 170, 160]],
    ["dragging back restores the original angle", 0, -55, [-35, -55], [20, 0]],
  ]) {
    test(`${mode}: ${name}`, () => {
      const f = editor(mode, yaw, pointerAt(start));
      for (const [index, position] of positions.entries()) {
        assert.ok(Math.abs(f.move(pointerAt(position)) - expected[index]) < 1e-8,
          `pointer ${position}° must paint yaw ${expected[index]}°, got ${f.item.yaw * 180 / Math.PI}°`);
      }
    });
  }
}
