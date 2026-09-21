import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import {
  deriveDeploymentWorkflow,
  isDeploymentStageUnlocked,
  resolveDeploymentViewStage,
} from "../../autodrive_console/web/deployment/workflow.js";

const deploymentPage = readFileSync(new URL("../../autodrive_console/web/deployment.html", import.meta.url), "utf8");
const deploymentSource = readFileSync(new URL("../../autodrive_console/web/deployment.js", import.meta.url), "utf8");
const deploymentStyles = readFileSync(new URL("../../autodrive_console/web/deployment.css", import.meta.url), "utf8");
const appShellStyles = readFileSync(new URL("../../autodrive_console/web/app_shell.css", import.meta.url), "utf8");
const mappingWorkbenchSource = readFileSync(new URL("../../autodrive_console/web/mapping_workbench.js", import.meta.url), "utf8");
const flowEditorSource = readFileSync(new URL("../../autodrive_console/web/deployment/flow-editor.js", import.meta.url), "utf8");
import { reorderFlow, validateFlow } from "../../autodrive_console/web/deployment/flow-editor.js";

const baseProject = {
  id: "site-demo",
  name: "高科一号",
  scene_model: "indoor_outdoor",
  map_assets: [],
  map_instances: [],
  waypoints: [],
  components: [],
  localization_bindings: [],
  localization_routes: [],
};

test("deployment workflow starts with project setup and exposes one next action", () => {
  const workflow = deriveDeploymentWorkflow(null, null, null);

  assert.equal(workflow.current.id, "project");
  assert.equal(workflow.next.label, "填写项目名称");
  assert.equal(workflow.steps[0].status, "current");
  assert.equal(workflow.steps[1].status, "locked");
});

test("deployment project list exposes a themed delete action", () => {
  assert.match(deploymentPage, /id=["']projectList["']/);
  assert.match(deploymentSource, /delete-project/);
  assert.match(deploymentSource, /method:\s*["']DELETE["']/);
  assert.match(deploymentSource, /确认删除部署项目/);
  assert.match(deploymentStyles, /\.project-delete-button/);
  assert.match(deploymentStyles, /\.project-delete-button:hover/);
});

test("workflow advances to map preparation only after the scene model is saved", () => {
  const workflow = deriveDeploymentWorkflow({ ...baseProject, scene_model: "" }, null, null);

  assert.equal(workflow.current.id, "project");
  assert.equal(workflow.next.label, "配置部署流程");
  assert.equal(workflow.current.reason, "先配置部署流程，工具才能确定地图阶段和经过顺序。");
});

test("workflow explains missing map stage bindings instead of presenting a dead canvas", () => {
  const project = { ...baseProject, map_assets: [{ id: "map-1", label: "室外" }] };
  const workflow = deriveDeploymentWorkflow(project, {
    valid: false,
    stages: [{ stage: "outdoor", label: "室外 / 起点", map_asset_id: null }],
  }, null);

  assert.equal(workflow.current.id, "maps");
  assert.equal(workflow.next.label, "完善地图阶段");
  assert.match(workflow.current.reason, /绑定/);
});

test("workflow reaches localization only after each map has a waypoint", () => {
  const project = {
    ...baseProject,
    map_assets: [{ id: "map-1", label: "室外" }, { id: "map-2", label: "楼层" }],
    waypoints: [{ id: "start", map_asset_id: "map-1", kind: "start" }],
  };
  const topology = {
    valid: true,
    stages: [
      { stage: "outdoor", label: "室外 / 起点", map_asset_id: "map-1" },
      { stage: "target_floor", label: "目标楼层", map_asset_id: "map-2" },
    ],
  };
  const workflow = deriveDeploymentWorkflow(project, topology, null);

  assert.equal(workflow.current.id, "annotations");
  assert.equal(workflow.next.label, "标记楼层地图");
  assert.equal(workflow.next.targetMapId, "map-2");
  assert.match(workflow.current.reason, /map-2|楼层/);
});

test("missing manual map transitions do not block the localization workflow", () => {
  const project = {
    ...baseProject,
    map_assets: [{ id: "map-1", label: "大厅" }, { id: "map-2", label: "楼层" }],
    waypoints: [
      { id: "start", map_asset_id: "map-1", kind: "start" },
      { id: "target", map_asset_id: "map-2", kind: "target" },
      { id: "return", map_asset_id: "map-2", kind: "return" },
    ],
    localization_bindings: [
      { id: "binding-1", map_asset_id: "map-1", type: "indoor" },
      { id: "binding-2", map_asset_id: "map-2", type: "floor" },
    ],
    localization_routes: [{ id: "route-1", binding_ids: ["binding-1", "binding-2"], task_start_waypoint_id: "start", task_target_waypoint_id: "target", task_return_waypoint_id: "return" }],
    task_compiler: { identity: { community: "高科一号" } },
  };
  const workflow = deriveDeploymentWorkflow(project, {
    valid: false,
    errors: ["大厅 / 首层至目标楼层缺少唯一 Transition"],
    stages: [
      { stage: "lobby", label: "大厅 / 首层", map_asset_id: "map-1" },
      { stage: "target_floor", label: "目标楼层", map_asset_id: "map-2" },
    ],
  }, { status: "blocked" });

  assert.equal(workflow.steps.find((item) => item.id === "maps").status, "complete");
  assert.equal(workflow.current.id, "export");
  assert.equal(workflow.next.label, "生成实验预览");
  assert.doesNotMatch(workflow.current.reason, /Transition/);
  assert.equal(workflow.steps.find((item) => item.id === "localization").status, "complete");
});

test("workflow marks export ready only after server preview succeeds", () => {
  const project = {
    ...baseProject,
    map_assets: [{ id: "map-1", label: "室外" }],
    waypoints: [
      { id: "start", map_asset_id: "map-1", kind: "start" },
      { id: "target", map_asset_id: "map-1", kind: "target" },
      { id: "return", map_asset_id: "map-1", kind: "return" },
    ],
    localization_bindings: [{ id: "binding-1", map_asset_id: "map-1", type: "outdoor" }],
    localization_routes: [{ id: "route-1", binding_ids: ["binding-1"], task_start_waypoint_id: "start", task_target_waypoint_id: "target", task_return_waypoint_id: "return" }],
    task_compiler: { identity: { community: "高科一号" } },
  };
  const topology = {
    valid: true,
    stages: [{ stage: "outdoor", label: "室外 / 起点", map_asset_id: "map-1" }],
  };

  const blocked = deriveDeploymentWorkflow(project, topology, { status: "blocked" });
  assert.equal(blocked.current.id, "export");
  assert.equal(blocked.next.label, "生成实验预览");

  const ready = deriveDeploymentWorkflow(project, topology, { status: "ready" });
  assert.equal(ready.current.id, "export");
  assert.equal(ready.next.label, "导出部署包");
  assert.equal(ready.steps.at(-1).status, "complete");
});

test("deployment page exposes a guided next-action surface", () => {
  for (const id of [
    "deploymentGuide",
    "deploymentGuideSteps",
    "deploymentGuideCurrent",
    "deploymentGuideNext",
    "deploymentGuideChecklist",
  ]) {
    assert.match(deploymentPage, new RegExp(`id=["']${id}["']`));
  }
  assert.match(deploymentPage, /type="module" src="\/deployment\.js"/);
});

test("mapping sessions leave deployment roles to the topology editor", () => {
  assert.doesNotMatch(deploymentPage, /id=["']mappingKind["']/);
  assert.match(deploymentPage, /地图角色将在“部署拓扑位置”中设置/);
  assert.match(deploymentSource, /kind:\s*"custom"/);
  assert.doesNotMatch(deploymentSource, /\$\("mappingKind"\)/);
  assert.match(mappingWorkbenchSource, /车端建图会话/);
  assert.doesNotMatch(mappingWorkbenchSource, /\$\("mappingSubtitle"\)\.textContent\s*=\s*session\s*\?\s*`\$\{session\.kind\}/);
});

test("deployment setup exposes a configurable visual flow instead of a fixed scene select", () => {
  assert.match(deploymentPage, /id=["']deploymentFlowEditor["']/);
  assert.match(deploymentPage, /id=["']deploymentFlowPalette["']/);
  assert.match(deploymentPage, /id=["']saveDeploymentFlow["']/);
  assert.doesNotMatch(deploymentPage, /id=["']sceneModel["']/);
  assert.match(deploymentSource, /deployment-flow/);
  assert.match(flowEditorSource, /renderDeploymentFlow/);
});

test("visual flow validation allows ferry stages in different positions", () => {
  const valid = validateFlow([
    { id: "ferry-1", type: "ferry" },
    { id: "outdoor", type: "outdoor" },
    { id: "lobby", type: "lobby" },
    { id: "target_floor", type: "target_floor" },
  ]);
  assert.equal(valid.valid, true);
  assert.equal(validateFlow([
    { id: "lobby", type: "lobby" },
    { id: "target_floor", type: "target_floor" },
    { id: "ferry-1", type: "ferry" },
  ]).valid, false);
});

test("deployment flow cards reorder by drag semantics and keep the target floor last", () => {
  const flow = [
    { id: "outdoor", type: "outdoor" },
    { id: "lobby", type: "lobby" },
    { id: "target_floor", type: "target_floor" },
  ];
  assert.deepEqual(reorderFlow(flow, 0, 1).map((node) => node.id), ["outdoor", "lobby", "target_floor"]);
  assert.deepEqual(reorderFlow(flow, 0, 2).map((node) => node.id), ["lobby", "outdoor", "target_floor"]);
  assert.deepEqual(reorderFlow(flow, 2, 0).map((node) => node.id), ["outdoor", "lobby", "target_floor"]);
  assert.match(flowEditorSource, /draggable="true"/);
  assert.match(flowEditorSource, /data-flow-drag-index/);
  assert.match(flowEditorSource, /onpointerdown/);
  assert.match(flowEditorSource, /onpointermove/);
  assert.match(flowEditorSource, /onpointerup/);
  assert.match(flowEditorSource, /deployment-flow-drop-zone/);
  assert.match(flowEditorSource, /data-flow-drop-index/);
  assert.match(flowEditorSource, /elementFromPoint/);
  assert.match(flowEditorSource, /flowDropIndex/);
  assert.match(flowEditorSource, /const cards = \[\.\.\.container\.querySelectorAll\("\[data-flow-drag-index\]"\)\]/);
  assert.match(flowEditorSource, /animate\(/);
  assert.match(flowEditorSource, /container\.classList\.remove\("is-dragging"\);\n  const previousRects/);
  assert.doesNotMatch(flowEditorSource, />上移</);
  assert.doesNotMatch(flowEditorSource, />下移</);
  assert.match(deploymentStyles, /deployment-flow-remove-action/);
  assert.match(deploymentStyles, /deployment-flow-node:hover \.deployment-flow-remove-action/);
  assert.match(deploymentSource, /reorderFlow/);
});

test("deployment page marks later panels for progressive disclosure", () => {
  for (const stage of ["maps", "annotations", "localization", "export"]) {
    assert.match(deploymentPage, new RegExp(`data-deployment-stage=["']${stage}["']`));
  }
  assert.doesNotMatch(deploymentPage, /data-waypoint-kind=["']transition_link["']/);
  assert.doesNotMatch(deploymentPage, />地图衔接</);
  assert.match(deploymentSource, /mapPointToCanvas\(\{ x: 0, y: 0 \}/);
  assert.match(deploymentSource, /fillText\("\(0, 0\)"/);
  assert.match(deploymentSource, /data-guide-action="return-current"/);
  assert.match(deploymentSource, /reviewed/);
  assert.match(deploymentPage, /data-deployment-stages=["']maps annotations localization["']/);
  assert.match(deploymentPage, /id=["']mapList["'][\s\S]*data-deployment-stages=["']maps annotations localization["']/);
  assert.match(deploymentPage, /id=["']mapFolderManifest["']/);
  assert.equal(isDeploymentStageUnlocked("maps", "localization"), false);
  assert.equal(isDeploymentStageUnlocked("annotations", "maps"), true);
  assert.equal(isDeploymentStageUnlocked("export", "localization"), true);
  assert.equal(resolveDeploymentViewStage("maps", "project"), "project");
  assert.equal(resolveDeploymentViewStage("maps", "localization"), "maps");
  assert.equal(resolveDeploymentViewStage("localization", "maps"), "maps");
});

test("desktop workbench keeps the mounted map surface in the center column", () => {
  assert.match(
    deploymentStyles,
    /body:has\(#mapWorkspace\)\[data-deployment-stage="localization"\][^{}]*\.page-grid\s*>\s*\.panel\[data-deployment-stages\][^{}]*\{[^}]*grid-column:\s*2\s*!important/s,
    "the high-specificity localization override must keep the map panel out of the left rail",
  );
  assert.match(
    deploymentStyles,
    /body:has\(#mapWorkspace\)\[data-deployment-stage\].*\.deployment-map\s*\{[^}]*max-width:\s*100%/s,
    "context rail map rows must stay inside the narrow rail",
  );
  assert.match(
    deploymentStyles,
    /@media \(min-width:\s*960px\) and \(max-width:\s*1380px\)[\s\S]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/,
    "the compact toolbar must keep labels readable at laptop and medium desktop widths",
  );
});

test("export review uses a centered single-column surface", () => {
  assert.match(
    deploymentStyles,
    /body:has\(#mapWorkspace\)\[data-deployment-stage="export"\] \.page-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*980px\)\s*!important/s,
    "export review should not leave a large unused canvas column",
  );
  assert.match(
    deploymentStyles,
    /body:has\(#mapWorkspace\)\[data-deployment-stage="export"\] \.deployment-inspector-rail\s*\{[^}]*grid-column:\s*1\s*!important[^}]*width:\s*100%/s,
    "the compiler rail should align with the centered export surface",
  );
});

test("successful compiler preview exposes a focused full-window map surface", () => {
  const html = deploymentPage;
  const script = deploymentSource;
  const css = deploymentStyles;

  assert.match(html, /id="taskPreviewOverlay"/);
  assert.match(html, /id="taskPreviewMapMount"/);
  assert.match(html, /id="closeTaskPreview"/);
  assert.match(script, /taskPreviewOverlay/);
  assert.match(script, /openTaskPreview/);
  assert.match(css, /body\.task-preview-open[^{]*\{/);
  assert.match(css, /\.task-preview-overlay[^{]*\{/);
});

test("localization template keeps its selected-file state after upload", () => {
  assert.match(deploymentPage, /id="localizationTemplateFile"[^>]*aria-describedby="localizationTemplateMessage"/);
  assert.match(deploymentSource, /当前模板：\$\{localizationTemplate\.name/);
  assert.doesNotMatch(
    deploymentSource,
    /\$\("localizationTemplateFile"\)\.value\s*=\s*""/,
    "a successful upload must not clear the native file picker while the template is active",
  );
});

test("project setup shares the guide reading measure", () => {
  assert.match(
    deploymentStyles,
    /body\[data-deployment-stage="project"\]\s+main\.page-main\s*>\s*\.page-grid\s*\{[^}]*width:\s*min\(100%,\s*1180px\)/s,
    "project cards should align with the guide and page header instead of growing wider",
  );
});

test("first-run project setup keeps its workspace on the guide alignment line", () => {
  assert.match(
    deploymentStyles,
    /body:has\(\.deployment-setup-project\.deployment-stage-visible\)\s+main\.page-main\s*>\s*\.page-grid\s*\{[^}]*width:\s*min\(100%,\s*1180px\)\s*!important/s,
    "the empty-project view must not fall back to the global full-width grid while its stage state is settling",
  );
});

test("global navigation selection avoids the decorative accent rail", () => {
  assert.match(
    appShellStyles,
    /nav a\.active\s*\{[^}]*box-shadow:\s*inset\s+0\s+0\s+0\s+1px/s,
    "selected navigation should use a quiet surface outline instead of a left neon rail",
  );
  assert.doesNotMatch(
    appShellStyles,
    /nav a\.active\s*\{[^}]*inset\s+2px\s+0/s,
    "the global selected state must not reintroduce the AI-style edge marker",
  );
});

test("route endpoint controls distinguish an empty binding from a selected waypoint", () => {
  assert.match(deploymentSource, /未选择：首张地图任务起点/);
  assert.match(deploymentSource, /未选择：选择交付目标点/);
  assert.match(deploymentSource, /返程子任务目标自动使用目标层电梯门前呼梯点/);
  assert.match(deploymentSource, /待补齐：/);
  assert.doesNotMatch(deploymentSource, /选择首图 start 航点/);
  assert.doesNotMatch(deploymentSource, /选择末图 target 航点/);
});

test("map editing stages align the header and guide with the workbench", () => {
  assert.match(
    deploymentStyles,
    /body\[data-deployment-stage="maps"\]\s+main\.page-main\s*>\s*\.page-header[\s\S]*?body\[data-deployment-stage="localization"\]\s+\.deployment-guide[\s\S]*?max-width:\s*none/s,
    "map stages should share one left and right edge across the header, guide, and workbench",
  );
});

test("medium desktop keeps the map canvas wide and moves inspection below", () => {
  assert.match(
    deploymentStyles,
    /@media \(min-width:\s*960px\) and \(max-width:\s*1380px\)[\s\S]*body:has\(#mapWorkspace\)\[data-deployment-stage="maps"\] \.page-grid[\s\S]*grid-template-columns:\s*minmax\(220px,\s*240px\) minmax\(0,\s*1fr\)\s*!important/s,
    "medium desktop should reserve the second column for the map canvas",
  );
  assert.match(
    deploymentStyles,
    /body:has\(#mapWorkspace\)\[data-deployment-stage="localization"\] \.deployment-inspector-rail[\s\S]*grid-column:\s*1 \/ -1\s*!important/s,
    "inspection panels should move below the map instead of squeezing it",
  );
});

test("wide map stages use the full content measure instead of a centered max-width island", () => {
  assert.match(
    deploymentStyles,
    /body\[data-deployment-stage="maps"\]\s+main\.page-main\s*>\s*\.page-grid[\s\S]*?width:\s*100%[\s\S]*?max-width:\s*none/s,
    "the map workbench should expand with the page content on wide screens",
  );
});

test("light theme overrides deployment-specific dark surfaces", () => {
  assert.match(
    deploymentStyles,
    /body\.theme-light \.deployment-guide-steps[\s\S]*background:\s*var\(--surface\)\s*!important/s,
    "the step rail must follow the light theme surface",
  );
  assert.match(
    deploymentStyles,
    /body\.theme-light \.deployment-guide-current[\s\S]*background:\s*var\(--surface\)\s*!important/s,
    "the current-step card must follow the light theme surface",
  );
  assert.match(
    deploymentStyles,
    /body\.theme-light \.map-folder-manifest[\s\S]*background:\s*var\(--surface-sunken\)\s*!important/s,
    "the map manifest must not remain a dark block in light mode",
  );
});

test("export compiler shares the guide reading measure", () => {
  assert.match(
    deploymentStyles,
    /body\[data-deployment-stage="export"\]\s+main\.page-main\s*>\s*\.page-grid\s*\{[^}]*width:\s*min\(100%,\s*1180px\)/s,
    "export should begin on the same left edge as the guide",
  );
  assert.match(
    deploymentStyles,
    /body:has\(#mapWorkspace\)\[data-deployment-stage="export"\] \.page-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*!important/s,
    "export should fill its reading measure instead of leaving an inner gutter",
  );
});
