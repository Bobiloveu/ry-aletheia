import { strict as assert } from "node:assert";
import test from "node:test";

import {
  isDirectionalTaskAnchor,
  startDirectionGeometry,
} from "../../../autodrive_console/web/deployment/start-direction.js";

test("both task anchors retain a visible heading while facilities remain geometrically neutral", () => {
  assert.equal(isDirectionalTaskAnchor("start"), true);
  assert.equal(isDirectionalTaskAnchor("target"), true);
  assert.equal(isDirectionalTaskAnchor("elevator"), false);
  assert.equal(isDirectionalTaskAnchor("auto_door"), false);
  assert.equal(isDirectionalTaskAnchor("gate"), false);
  assert.equal(isDirectionalTaskAnchor("slow_zone"), false);
  assert.equal(isDirectionalTaskAnchor("narrow_passage"), false);
});

test("start direction marker stays outside the start marker and follows map yaw", () => {
  const east = startDirectionGeometry({ x: 100, y: 80, yaw: 0, radius: 24 });
  assert.deepEqual(east, {
    lineStart: { x: 128, y: 80 },
    tip: { x: 148, y: 80 },
    leftWing: { x: 140, y: 75 },
    rightWing: { x: 140, y: 85 },
  });

  const north = startDirectionGeometry({ x: 100, y: 80, yaw: Math.PI / 2, radius: 24 });
  assert.deepEqual(north, {
    lineStart: { x: 100, y: 52 },
    tip: { x: 100, y: 32 },
    leftWing: { x: 95, y: 40 },
    rightWing: { x: 105, y: 40 },
  });
});
