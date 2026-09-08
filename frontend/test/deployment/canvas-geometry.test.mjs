import { strict as assert } from "node:assert";
import test from "node:test";

import {
  canvasPointToMap,
  componentDimensions,
  componentLocalPoint,
  isComponentHit,
  isPointOnMap,
  isResizeHandleHit,
  isRotateHandleHit,
  mapPointToCanvas,
  zoomAt,
} from "../../../autodrive_console/web/deployment/canvas-geometry.js";
import { drawDeploymentCanvas } from "../../../autodrive_console/web/deployment/canvas-renderer.js";

const map = { origin: [10, 20], width: 100, height: 80, resolution_m: 0.05 };
const view = { scale: 40, x: 12, y: 24 };
const assertClose = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9);

test("map and canvas coordinates remain inverse across the inverted map Y axis", () => {
  const worldPoint = { x: 11.5, y: 22 };
  assert.deepEqual(mapPointToCanvas(worldPoint, map, view), { x: 72, y: 104 });
  assert.deepEqual(canvasPointToMap({ x: 72, y: 104 }, map, view), worldPoint);
});

test("map bounds include the edge and reject a point beyond the physical extent", () => {
  assert.equal(isPointOnMap({ x: 10, y: 20 }, map), true);
  assert.equal(isPointOnMap({ x: 15, y: 24 }, map), true);
  assert.equal(isPointOnMap({ x: 15.001, y: 24 }, map), false);
});

test("rotated components use their local axes for hit and handle detection", () => {
  const component = {
    x: 11,
    y: 21,
    yaw: Math.PI / 2,
    attributes: { width_m: 1, height_m: 2 },
  };
  const center = mapPointToCanvas(component, map, view);
  assert.deepEqual(componentDimensions(component, view.scale), { width: 40, height: 80 });
  const localPoint = componentLocalPoint(component, { x: center.x + 20, y: center.y }, map, view);
  assertClose(localPoint.x, 0);
  assertClose(localPoint.y, 20);
  assert.equal(isComponentHit(component, { x: center.x + 20, y: center.y }, map, view), true);
  assert.equal(isComponentHit(component, { x: center.x, y: center.y + 21 }, map, view), false);
  assert.equal(isResizeHandleHit(component, { x: center.x + 49, y: center.y - 29 }, map, view), true);
  assert.equal(isRotateHandleHit(component, { x: center.x + 49, y: center.y - 49 }, map, view), true);
});

test("zoom clamps scale while anchoring the world point below the pointer", () => {
  const pointer = { x: 172, y: 144 };
  const before = canvasPointToMap(pointer, map, view);
  const zoomed = zoomAt(view, pointer, -1);
  assertClose(zoomed.scale, 44.8);
  assert.deepEqual(canvasPointToMap(pointer, map, zoomed), before);
  assert.equal(zoomAt({ ...view, scale: 499 }, pointer, -1).scale, 500);
  assert.equal(zoomAt({ ...view, scale: 5 }, pointer, 1).scale, 5);
});

test("deployment canvas renderer exposes a snapshot-based drawing boundary", () => {
  assert.equal(typeof drawDeploymentCanvas, "function");
});
