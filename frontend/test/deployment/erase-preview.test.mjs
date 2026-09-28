import { strict as assert } from "node:assert";
import test from "node:test";

import { eraseEditsForRender } from "../../../autodrive_console/web/deployment/erase-preview.js";

test("releasing a brush stroke keeps its local erase preview visible until the saved map edit arrives", () => {
  const savedEdit = { id: "saved-1", map_asset_id: "map-a", kind: "brush_erase", points: [{ x: 1, y: 1 }] };
  const releasedStroke = { kind: "brush_erase", radius_m: 0.4, points: [{ x: 2, y: 2 }] };

  assert.deepEqual(
    eraseEditsForRender({
      savedEdits: [savedEdit],
      activeMapId: "map-a",
      activeStroke: null,
      pendingStroke: releasedStroke,
    }),
    [savedEdit, releasedStroke],
  );
});
