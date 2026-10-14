import assert from "node:assert/strict";
import test from "node:test";

import { freezeMapViewportForRelocalization } from "../src/mapViewportLock.js";

test("freezing for relocalization preserves the visible map center and disables vehicle following", () => {
  const mapView = {
    pixelsPerMeter: 42,
    followVehicle: true,
    followOffset: { x: 1.4, y: -0.6 },
    center: { x: -28.52, y: 5.76 },
  };

  freezeMapViewportForRelocalization(mapView, { center: { x: 83, y: 21 } });

  assert.equal(mapView.followVehicle, false);
  assert.deepEqual(mapView.center, { x: -28.52, y: 5.76 });
  assert.deepEqual(mapView.followOffset, { x: 0, y: 0 });
  assert.equal(mapView.pixelsPerMeter, 42);
});

test("freezing before the first explicit center uses the displayed layout center", () => {
  const mapView = {
    pixelsPerMeter: 24,
    followVehicle: true,
    followOffset: { x: 0, y: 0 },
    center: undefined,
  };

  freezeMapViewportForRelocalization(mapView, { center: { x: 3.5, y: -7.25 } });

  assert.deepEqual(mapView.center, { x: 3.5, y: -7.25 });
  assert.equal(mapView.followVehicle, false);
});
