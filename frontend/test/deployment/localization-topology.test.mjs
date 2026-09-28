import assert from "node:assert/strict";
import test from "node:test";

import { bindingOwnedByTopology } from "../../../autodrive_console/web/deployment/localization-topology.js";

test("topology-owned map bindings derive role and identity without duplicate operator input", () => {
  assert.deepEqual(
    bindingOwnedByTopology({ role: "lobby", building: "5", unit: "2" }),
    { type: "indoor", building: "5", unit: "2" },
  );
  assert.deepEqual(
    bindingOwnedByTopology({ role: "typical_floor", building: "5", unit: "2" }),
    { type: "floor", building: "5", unit: "2" },
  );
  assert.deepEqual(
    bindingOwnedByTopology({ role: "ferry", building: "5", unit: "2" }),
    { type: "ferry", building: "", unit: "" },
  );
  assert.equal(bindingOwnedByTopology({ role: "unknown", building: "5", unit: "2" }), null);
});
