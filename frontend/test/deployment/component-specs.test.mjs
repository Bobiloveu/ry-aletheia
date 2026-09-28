import { strict as assert } from "node:assert";
import test from "node:test";

import {
  COMPONENT_SPECS,
  componentName,
  protocolOptions,
  protocolTitle,
} from "../../../autodrive_console/web/deployment/component-specs.js";

test("component definitions preserve deployment labels and fallback labels", () => {
  assert.equal(componentName({ kind: "elevator" }), "电梯");
  assert.equal(componentName({ kind: "building_entrance" }), "楼栋入口");
  assert.equal(componentName({ kind: "unknown", label: "自定义组件" }), "自定义组件");
  assert.equal(componentName({ kind: "unknown" }), "unknown");
});

test("target points expose only the two runtime behavior-tree actions", () => {
  const field = COMPONENT_SPECS.target.fields.find((item) => item.key === "arrival_action");
  assert.deepEqual(field, {
    key: "arrival_action",
    label: "到达动作",
    type: "select",
    options: [["place_water", "泄水"], ["auto_cargo", "卸货"]],
    default: "place_water",
  });
});

test("protocol options use project templates before the MQTT and LORA lift defaults", () => {
  assert.deepEqual(
    protocolOptions(
      { component_templates: { elevator_protocols: [{ id: "mqtt", label: "MQTT" }] } },
      "elevator_protocols",
    ),
    [["mqtt", "MQTT"]],
  );
  assert.deepEqual(protocolOptions({}, "elevator_protocols"), [
    ["mqtt", "MQTT"],
    ["lora", "LORA"],
  ]);
});

test("protocol title follows the selected project template and preserves unknown ids", () => {
  const project = {
    component_templates: { elevator_protocols: [{ id: "mqtt", label: "MQTT" }] },
  };
  assert.equal(protocolTitle(project, "mqtt"), "MQTT");
  assert.equal(protocolTitle({}, "mqtt"), "MQTT");
  assert.equal(protocolTitle(project, "private"), "private");
  assert.equal(protocolTitle(project, ""), "未配置");
});

test("access components expose a numeric controller device property after placement", () => {
  for (const kind of ["gate", "auto_door"]) {
    const field = COMPONENT_SPECS[kind].fields.find((item) => item.key === "controller_device_id");
    assert.deepEqual(field, {
      key: "controller_device_id",
      label: "控制设备号",
      type: "text",
      inputMode: "numeric",
      pattern: "[1-9][0-9]*",
      placeholder: "例如：10044",
      default: "",
    });
  }
});

test("access components leave speed profiles to the shared template instead of a selectable field", () => {
  for (const kind of ["gate", "auto_door"]) {
    assert.equal(
      COMPONENT_SPECS[kind].fields.some((item) => item.key === "speed_profile"),
      false,
    );
  }
});

test("access components expose independent before-open and after-open clearances", () => {
  for (const kind of ["gate", "auto_door"]) {
    const fields = COMPONENT_SPECS[kind].fields;
    assert.deepEqual(fields.find((item) => item.key === "pre_open_distance_m"), {
      key: "pre_open_distance_m", label: "开门前距离（m）", type: "number",
      min: "0.5", max: "5", step: "0.1", default: 1.5,
    });
    assert.deepEqual(fields.find((item) => item.key === "post_open_distance_m"), {
      key: "post_open_distance_m", label: "开门后停靠距离（m）", type: "number",
      min: "0.5", max: "5", step: "0.1", default: 1.5,
    });
  }
});
