import { strict as assert } from "node:assert";
import test from "node:test";

import {
  componentName,
  protocolOptions,
  protocolTitle,
} from "../../../autodrive_console/web/deployment/component-specs.js";

test("component definitions preserve deployment labels and fallback labels", () => {
  assert.equal(componentName({ kind: "elevator" }), "电梯");
  assert.equal(componentName({ kind: "unknown", label: "自定义组件" }), "自定义组件");
  assert.equal(componentName({ kind: "unknown" }), "unknown");
});

test("protocol options use project templates before the existing defaults", () => {
  assert.deepEqual(
    protocolOptions(
      { component_templates: { elevator_protocols: [{ id: "mqtt", label: "MQTT" }] } },
      "elevator_protocols",
    ),
    [["mqtt", "MQTT"]],
  );
  assert.deepEqual(protocolOptions({}, "elevator_protocols"), [
    ["bluetooth", "蓝牙"],
    ["4g", "4G"],
  ]);
});

test("protocol title follows the selected project template and preserves unknown ids", () => {
  const project = {
    component_templates: { elevator_protocols: [{ id: "mqtt", label: "MQTT" }] },
  };
  assert.equal(protocolTitle(project, "mqtt"), "MQTT");
  assert.equal(protocolTitle({}, "bluetooth"), "蓝牙");
  assert.equal(protocolTitle(project, "private"), "private");
  assert.equal(protocolTitle(project, ""), "未配置");
});
