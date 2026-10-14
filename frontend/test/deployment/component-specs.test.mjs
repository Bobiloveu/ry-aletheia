import { strict as assert } from "node:assert";
import test from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

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

test("target quick editing keeps location properties and directs cargo configuration to task lines", () => {
  const source = readFileSync(new URL("../../../autodrive_console/web/deployment.js", import.meta.url), "utf8");
  const render = source.match(/function renderComponentAttributes\(component\) \{[\s\S]*?\n\}/)[0];
  for (const project of [{id:"legacy"}, {id:"fixed",task_lines:[]}]) {
    const elements = new Map();
    const state = {
      COMPONENT_SPECS,componentName,protocolOptions,protocolTitle,selectedProject:project,
      componentSpeedDefaults:{},physicalElevatorFor:()=>null,mapInstanceFor:()=>null,esc:String,
      $:id=>{if(!elements.has(id))elements.set(id,{classList:{toggle(){}},innerHTML:""});return elements.get(id);},
    };
    const component={kind:"target",attributes:{door:"1509",arrival_action:"auto_cargo"}};
    runInNewContext(render,state);state.renderComponentAttributes(component);
    const html=elements.get("componentAttributeFields").innerHTML;
    assert.match(html,/data-component-attribute="door"/);
    assert.match(html,/value="1509"/);
    assert.doesNotMatch(html,/data-component-attribute="arrival_action"/);
    assert.match(html,/任务线路/);
    assert.equal(component.attributes.arrival_action,"auto_cargo");
  }
});

test("saving target geometry preserves historical actions without creating a per-location cargo policy", async () => {
  const source = readFileSync(new URL("../../../autodrive_console/web/deployment.js", import.meta.url), "utf8");
  const handler=source.match(/\$\("saveComponent"\)\.addEventListener\("click", async \(\) => \{([\s\S]*?)\n\}\);/)[1];
  let payload;
  const selectedComponent={id:"target",kind:"target",map_asset_id:"m",x:2,y:3,attributes:{door:"1509",arrival_action:"auto_cargo",width_m:.8,height_m:.8}};
  const state={selectedComponent,selectedWaypoint:null,selectedProject:{id:"p",components:[selectedComponent]},activeMap:{id:"m"},deploymentProjectGeneration:1,annotationSavePending:false,updateMapBeautyControls(){},$:()=>({value:"1.2"}),
    document:{querySelectorAll:()=>[{dataset:{componentAttribute:"door"},type:"text",value:"1510"}]},
    request:async(url,options)=>{payload=JSON.parse(options.body);return {project:{components:[selectedComponent]}};},
    renderProject(){},selectComponent(){},keepMapAnnotationOpen:()=>true,completeDeploymentEdit(){},note(){},
  };
  const helper=source.match(/async function saveMapAnnotation\([\s\S]*?\n\}/)[0];
  runInNewContext(`${helper}\nasync function save(){${handler}\n}`,state);await state.save();
  assert.deepEqual(payload,{x:2,y:3,yaw:"1.2",attributes:{door:"1510",arrival_action:"auto_cargo",width_m:.8,height_m:.8}});
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
