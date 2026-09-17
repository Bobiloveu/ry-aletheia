import assert from "node:assert/strict";
import test from "node:test";
import * as routeEditor from "../../../autodrive_console/web/deployment/localization-route.js";

const bindings = [
  { id: "outside", building: "1", unit: "1", type: "outdoor" },
  { id: "ferry", building: "1", unit: "1", type: "ferry" },
  { id: "floor-a", building: "1", unit: "1", type: "floor", floor_template: "a" },
  { id: "floor-b", building: "1", unit: "1", type: "floor", floor_template: "b" },
  { id: "foreign", building: "2", unit: "1", type: "floor" },
];
const draft = () => ({
  id: "saved-route", building: "1", unit: "1", binding_ids: ["outside", "ferry", "floor-a"],
  task_start_waypoint_id: "start", task_target_waypoint_id: "target-a",
  links: [
    { from_binding_id: "outside", to_binding_id: "ferry", anchor: { kind: "waypoint", waypoint_id: "transfer" } },
    { from_binding_id: "ferry", to_binding_id: "floor-a", anchor: { kind: "component_center", component_id: "door" } },
  ],
});

test("route choices keep alternative templates optional and hide foreign identities", () => {
  const choices = routeEditor.routeBindingChoices(bindings, "1", "1", ["outside", "floor-a"]);
  assert.deepEqual(choices.map(({ id, included }) => [id, included]), [
    ["outside", true], ["ferry", false], ["floor-a", true], ["floor-b", false],
  ]);
});

test("excluding a middle map retains endpoints and rebuilds only its affected links", () => {
  const original = draft();
  const changed = routeEditor.setRouteBindingIncluded(original, bindings, "ferry", false);
  assert.deepEqual(changed.binding_ids, ["outside", "floor-a"]);
  assert.equal(changed.task_start_waypoint_id, "start");
  assert.equal(changed.task_target_waypoint_id, "target-a");
  assert.deepEqual(changed.links, [{ from_binding_id: "outside", to_binding_id: "floor-a", anchor: null }]);
  assert.deepEqual(original, draft(), "unsaved editing cannot mutate the persisted route snapshot");
});

test("replacing the final floor resets its target and makes a new template selectable", () => {
  const withoutFloor = routeEditor.setRouteBindingIncluded(draft(), bindings, "floor-a", false);
  const changed = routeEditor.setRouteBindingIncluded(withoutFloor, bindings, "floor-b", true);
  assert.deepEqual(changed.binding_ids, ["outside", "ferry", "floor-b"]);
  assert.equal(changed.task_start_waypoint_id, "start");
  assert.equal(changed.task_target_waypoint_id, "");
  assert.deepEqual(changed.links[0], draft().links[0]);
  assert.deepEqual(changed.links[1], { from_binding_id: "ferry", to_binding_id: "floor-b", anchor: null });
  assert.deepEqual(routeEditor.setRouteBindingIncluded(changed, bindings, "foreign", true), changed);
});

test("resetting an edit clears only the draft and keeps the saved route id for explicit replacement", () => {
  const original = draft();
  assert.deepEqual(routeEditor.resetRouteDraft(original), {
    id: "saved-route", building: "1", unit: "1", binding_ids: [],
    task_start_waypoint_id: "", task_target_waypoint_id: "", links: [],
  });
  assert.deepEqual(original, draft());
});
