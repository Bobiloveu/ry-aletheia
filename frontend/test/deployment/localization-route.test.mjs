import assert from "node:assert/strict";
import test from "node:test";
import {
  automaticExecutionNodes,
  automaticRouteBindings,
  automaticRouteStatus,
} from "../../../autodrive_console/web/deployment/localization-route.js";

const bindings = [
  { id: "outside", type: "outdoor" },
  { id: "ferry", type: "ferry" },
  { id: "floor-a", type: "floor", floor_template: "a" },
  { id: "foreign", type: "floor" },
];

test("automatic route bindings follow the backend scene sequence and omit stale ids", () => {
  const route = { binding_ids: ["outside", "ferry", "floor-a", "missing"] };

  assert.deepEqual(
    automaticRouteBindings(route, bindings).map((item) => item.id),
    ["outside", "ferry", "floor-a"],
  );
  assert.deepEqual(automaticRouteBindings(null, bindings), []);
});

test("automatic execution nodes retain only valid generated task references", () => {
  const route = {
    execution_nodes: [{
      binding_id: "ferry",
      node_refs: [
        { kind: "transition", id: "transfer" },
        { kind: "component", id: "gate-east" },
        { kind: "start", id: "ignored" },
        { kind: "component" },
      ],
    }],
  };

  assert.deepEqual(automaticExecutionNodes(route, "ferry"), [
    { kind: "transition", id: "transfer" },
    { kind: "component", id: "gate-east" },
  ]);
  assert.deepEqual(automaticExecutionNodes(route, "floor-a"), []);
});

test("automatic route status requires a user-floor endpoint", () => {
  const ready = {
    binding_ids: ["outside", "ferry", "floor-a"],
    execution_nodes: [{ binding_id: "ferry", node_refs: [{ kind: "component", id: "gate-east" }] }],
  };
  assert.deepEqual(automaticRouteStatus(ready, bindings), {
    ready: true,
    mapCount: 3,
    nodeCount: 1,
  });
  assert.deepEqual(
    automaticRouteStatus({ binding_ids: ["outside", "ferry"] }, bindings),
    { ready: false, reason: "场景流程必须以用户楼层结束" },
  );
});
