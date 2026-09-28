import { strict as assert } from "node:assert";
import test from "node:test";

import {
  executionNodeLabel,
  executionNodeRoleLabel,
  executionNodeSpeedLabel,
} from "../../../autodrive_console/web/deployment/execution-chain-view.js";

test("execution-chain display uses operator names instead of opaque node identifiers", () => {
  const project = {
    components: [{ id: "component-75376a39f52d", kind: "gate", label: "东侧闸机" }],
    waypoints: [{ id: "waypoint-3d1448c8878", kind: "transition", label: "过渡点" }],
  };

  assert.equal(
    executionNodeLabel({ source_kind: "component", source_id: "component-75376a39f52d" }, project),
    "闸机 · 东侧闸机",
  );
  assert.equal(
    executionNodeLabel({ source_kind: "transition", source_id: "waypoint-3d1448c8878" }, project),
    "过渡点",
  );
  assert.equal(executionNodeRoleLabel("entry"), "进入");
  assert.equal(executionNodeSpeedLabel("slow_point"), "减速");
});

test("execution-chain display never falls back to an opaque identifier", () => {
  assert.equal(
    executionNodeLabel({ source_kind: "component", source_id: "component-75376a39f52d" }, {}),
    "组件",
  );
});
