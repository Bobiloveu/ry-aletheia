import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import {
  deriveDeploymentEditImpact,
  deriveDeploymentTask,
  deriveDeploymentWorkflow,
  deriveLocalizationGuidance,
  deriveMapImportGuidance,
  isDeploymentStageUnlocked,
  nextMapImportDraft,
  resolveDeploymentViewStage,
} from "../../autodrive_console/web/deployment/workflow.js";
import {
  createTaskActionGate,
  taskConsoleMarkup,
} from "../../autodrive_console/web/deployment/task-console.js";

const deploymentPage = readFileSync(new URL("../../autodrive_console/web/deployment.html", import.meta.url), "utf8");
const deploymentSource = readFileSync(new URL("../../autodrive_console/web/deployment.js", import.meta.url), "utf8");
const deploymentStyles = readFileSync(new URL("../../autodrive_console/web/deployment.css", import.meta.url), "utf8");
const deploymentSessionSource = readFileSync(new URL("../../autodrive_console/web/deployment/session-state.js", import.meta.url), "utf8");
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

test("map preparation begins with one source-selection task", () => {
  const project = {
    ...baseProject,
    deployment_flow: [
      { id: "lobby", type: "lobby", label: "电梯大厅" },
      { id: "target", type: "target_floor", label: "用户楼层" },
    ],
  };
  const topology = {
    stages: [
      { stage: "lobby", label: "电梯大厅", map_asset_id: null },
      { stage: "target", label: "用户楼层", map_asset_id: null },
    ],
  };
  const workflow = deriveDeploymentWorkflow(project, topology, null);
  const task = deriveDeploymentTask({ workflow, project, topology, mappingSession: null, draft: {} });

  assert.equal(task.id, "maps.source");
  assert.equal(task.primaryAction.id, "choose-map-source");
  assert.equal(task.targetStageId, "lobby");
  assert.equal(task.progressItems.filter((item) => item.status === "current").length, 1);
});

test("bound indoor maps stay in map preparation until the lobby has its deployment instance", () => {
  const project = {
    ...baseProject,
    deployment_flow: [
      { id: "lobby", type: "lobby", label: "电梯大厅" },
      { id: "target_floor", type: "target_floor", label: "用户楼层" },
    ],
    map_assets: [
      { id: "lobby-map", label: "电梯大厅" },
      { id: "floor-map", label: "1509" },
    ],
  };
  const topology = {
    stages: [
      { stage: "lobby", label: "电梯大厅", map_asset_id: "lobby-map" },
      { stage: "target_floor", label: "用户楼层", map_asset_id: "floor-map" },
    ],
  };
  const workflow = deriveDeploymentWorkflow(project, topology, null);
  const task = deriveDeploymentTask({ workflow, project, topology, mappingSession: null });

  assert.equal(workflow.current.id, "maps");
  assert.equal(workflow.steps.find((step) => step.id === "annotations").status, "locked");
  assert.equal(task.id, "maps.instance");
  assert.equal(task.targetMapId, "lobby-map");
  assert.equal(task.instanceRole, "lobby");
  assert.equal(task.primaryAction.target, "instanceControls");
});

test("after the lobby instance is saved, map preparation requires the target-floor instance", () => {
  const project = {
    ...baseProject,
    deployment_flow: [
      { id: "lobby", type: "lobby", label: "电梯大厅" },
      { id: "target_floor", type: "target_floor", label: "用户楼层" },
    ],
    map_assets: [
      { id: "lobby-map", label: "电梯大厅" },
      { id: "floor-map", label: "1509" },
    ],
    map_instances: [
      { map_asset_id: "lobby-map", role: "lobby", building: "1", unit: "1", floor: 1 },
    ],
  };
  const topology = {
    stages: [
      { stage: "lobby", label: "电梯大厅", map_asset_id: "lobby-map" },
      { stage: "target_floor", label: "用户楼层", map_asset_id: "floor-map" },
    ],
  };
  const workflow = deriveDeploymentWorkflow(project, topology, null);
  const task = deriveDeploymentTask({ workflow, project, topology, mappingSession: null });

  assert.equal(workflow.current.id, "maps");
  assert.equal(task.id, "maps.instance");
  assert.equal(task.targetMapId, "floor-map");
  assert.equal(task.instanceRole, "typical_floor");
});

test("valid selected files advance the local map task to naming and checking", () => {
  const project = {
    ...baseProject,
    deployment_flow: [{ id: "lobby", type: "lobby", label: "电梯大厅" }],
  };
  const topology = {
    stages: [{ stage: "lobby", label: "电梯大厅", map_asset_id: null }],
  };
  const workflow = deriveDeploymentWorkflow(project, topology, null);
  const task = deriveDeploymentTask({
    workflow,
    project,
    topology,
    mappingSession: null,
    draft: {
      mapSource: "import",
      fileSummary: {
        yamlCount: 1,
        pgmCount: 1,
        pcdCount: 1,
        indexCount: 0,
        valid: true,
      },
      mapLabel: "电梯大厅",
    },
  });

  assert.equal(task.id, "maps.describe");
  assert.equal(task.primaryAction.id, "import-map");
  assert.equal(task.primaryAction.label, "导入并继续");
  assert.equal(task.nextTaskLabel, "绑定地图阶段");
});

test("map import guidance names the next unbound stage before files are chosen", () => {
  const guidance = deriveMapImportGuidance({
    stages: [
      { stage: "lobby", label: "电梯大厅", map_asset_id: "lobby-map" },
      { stage: "target_floor", label: "用户楼层", map_asset_id: null },
    ],
  }, "target_floor");

  assert.deepEqual(guidance, {
    state: "target",
    stageLabel: "用户楼层",
    position: "第 2 / 2 张",
    title: "本次请导入：用户楼层地图",
    detail: "电梯大厅已完成；导入后会自动绑定到“用户楼层”。",
    fileLabel: "选择“用户楼层”地图文件",
    nameLabel: "显示名称（用户楼层）",
    namePlaceholder: "例如：用户楼层",
  });
});

test("map import guidance ignores a completed stale stage target", () => {
  const guidance = deriveMapImportGuidance({
    stages: [
      { stage: "lobby", label: "电梯大厅", map_asset_id: "lobby-map" },
      { stage: "target_floor", label: "用户楼层", map_asset_id: null },
    ],
  }, "lobby");

  assert.equal(guidance.stageLabel, "用户楼层");
  assert.equal(guidance.position, "第 2 / 2 张");
  assert.equal(guidance.title, "本次请导入：用户楼层地图");
  assert.equal(guidance.fileLabel, "选择“用户楼层”地图文件");
});

test("map import guidance falls back when a saved target no longer exists", () => {
  const guidance = deriveMapImportGuidance({
    stages: [
      { stage: "lobby", label: "电梯大厅", map_asset_id: "lobby-map" },
      { stage: "target_floor", label: "用户楼层", map_asset_id: null },
    ],
  }, "removed-stage");

  assert.equal(guidance.stageLabel, "用户楼层");
  assert.equal(guidance.position, "第 2 / 2 张");
  assert.equal(guidance.title, "本次请导入：用户楼层地图");
});

test("map import guidance completes only after every deployment stage has a map", () => {
  const guidance = deriveMapImportGuidance({
    stages: [
      { stage: "lobby", label: "电梯大厅", map_asset_id: "lobby-map" },
      { stage: "target_floor", label: "用户楼层", map_asset_id: "floor-map" },
    ],
  }, "lobby");

  assert.equal(guidance.state, "complete");
  assert.equal(guidance.title, "地图阶段已齐全");
});

test("a reset draft asks for the user-floor source after the lobby is bound", () => {
  const project = {
    ...baseProject,
    map_assets: [{ id: "lobby-map", label: "电梯大厅" }],
    map_instances: [
      { map_asset_id: "lobby-map", role: "lobby", building: "1", unit: "1", floor: 1 },
    ],
  };
  const topology = {
    stages: [
      { stage: "lobby", label: "电梯大厅", map_asset_id: "lobby-map" },
      { stage: "target_floor", label: "用户楼层", map_asset_id: null },
    ],
  };
  const task = deriveDeploymentTask({
    workflow: deriveDeploymentWorkflow(project, topology, null),
    project,
    topology,
    mappingSession: null,
    draft: nextMapImportDraft(),
  });

  assert.equal(task.id, "maps.source");
  assert.equal(task.title, "选择“用户楼层”地图来源");
  assert.equal(task.targetStageId, "target_floor");
});

test("localization guidance tells the operator to set the current map role before configuring a route", () => {
  const project = {
    ...baseProject,
    map_assets: [
      { id: "lobby-map", label: "电梯大厅" },
      { id: "floor-map", label: "1509" },
    ],
    localization_bindings: [
      { id: "binding-lobby", map_asset_id: "lobby-map", building: "1", unit: "1", type: "indoor" },
    ],
  };

  const guidance = deriveLocalizationGuidance(project, "floor-map");

  assert.equal(guidance.state, "needs_role");
  assert.equal(guidance.currentMapLabel, "1509");
  assert.equal(guidance.primaryAction.label, "设置 1509 的运行角色");
  assert.equal(guidance.route.available, false);
  assert.match(guidance.detail, /先确定这张地图承担的运行角色/);
});

test("an existing unbound map advances directly to stage binding", () => {
  const project = {
    ...baseProject,
    deployment_flow: [{ id: "lobby", type: "lobby", label: "电梯大厅" }],
    map_assets: [{ id: "map-1", label: "电梯大厅" }],
  };
  const topology = {
    stages: [{ stage: "lobby", label: "电梯大厅", map_asset_id: null }],
  };
  const workflow = deriveDeploymentWorkflow(project, topology, null);
  const task = deriveDeploymentTask({
    workflow,
    project,
    topology,
    mappingSession: null,
    draft: { latestCreatedMapId: "map-1" },
  });

  assert.equal(task.id, "maps.assign");
  assert.equal(task.targetMapId, "map-1");
  assert.equal(task.targetStageId, "lobby");
  assert.equal(task.primaryAction.id, "assign-map-stage");
});

test("an imported map already auto-bound by the server advances to the next map source", () => {
  const project = {
    ...baseProject,
    map_assets: [{ id: "lobby-map", label: "电梯大厅" }],
    map_instances: [
      { map_asset_id: "lobby-map", role: "lobby", building: "1", unit: "1", floor: 1 },
    ],
  };
  const topology = {
    valid: false,
    stages: [
      { stage: "lobby", label: "电梯大厅", map_asset_id: "lobby-map" },
      { stage: "target_floor", label: "用户楼层", map_asset_id: null },
    ],
  };

  const task = deriveDeploymentTask({
    workflow: deriveDeploymentWorkflow(project, topology, null),
    project,
    topology,
    mappingSession: null,
    draft: {
      latestCreatedMapId: "lobby-map",
      mapSource: "import",
      fileSummary: { valid: true },
    },
  });

  assert.equal(task.id, "maps.source");
  assert.equal(task.primaryAction.id, "choose-map-source");
  assert.equal(task.targetStageId, "target_floor");
});

test("finishing the last map mark waits for explicit confirmation before leaving annotation", () => {
  const project = {
    ...baseProject,
    deployment_flow: [
      { id: "lobby", type: "lobby", label: "电梯大厅" },
      { id: "target_floor", type: "target_floor", label: "用户楼层" },
    ],
    map_assets: [
      { id: "lobby-map", label: "电梯大厅" },
      { id: "floor-map", label: "1509" },
    ],
    map_instances: [
      { map_asset_id: "lobby-map", role: "lobby", building: "1", unit: "1", floor: 1 },
      { map_asset_id: "floor-map", role: "typical_floor", building: "1", unit: "1", floor: 15 },
    ],
    waypoints: [
      { id: "lobby-elevator-enter", map_asset_id: "lobby-map", kind: "elevator_enter" },
      { id: "floor-elevator-enter", map_asset_id: "floor-map", kind: "elevator_enter" },
    ],
  };
  const topology = {
    stages: [
      { stage: "lobby", label: "电梯大厅", map_asset_id: "lobby-map" },
      { stage: "target_floor", label: "用户楼层", map_asset_id: "floor-map" },
    ],
  };
  const workflow = deriveDeploymentWorkflow(project, topology, null);

  assert.equal(workflow.current.id, "localization");
  const task = deriveDeploymentTask({
    workflow,
    project,
    topology,
    mappingSession: null,
    viewedStage: "annotations",
    editingStage: "annotations",
  });

  assert.equal(task.id, "annotations.edit");
  assert.equal(task.readOnly, false);
  assert.equal(task.primaryAction.label, "确认标记完成，进入定位路线");
});

test("a completed import clears stale source and map identity before the next import", () => {
  assert.deepEqual(nextMapImportDraft(), {
    mapSource: null,
    fileSummary: null,
    mapLabel: "",
    latestCreatedMapId: null,
    receipt: null,
  });
});

test("a mapping session owned by another project becomes a non-mutating conflict task", () => {
  const project = {
    ...baseProject,
    deployment_flow: [{ id: "lobby", type: "lobby", label: "电梯大厅" }],
  };
  const topology = {
    stages: [{ stage: "lobby", label: "电梯大厅", map_asset_id: null }],
  };
  const workflow = deriveDeploymentWorkflow(project, topology, null);
  const task = deriveDeploymentTask({
    workflow,
    project,
    topology,
    mappingSession: { project_id: "another-site", state: "running" },
    draft: { mapSource: "mapping" },
  });

  assert.equal(task.id, "maps.mapping_blocked");
  assert.equal(task.primaryAction.id, "focus-mapping-conflict");
});

test("completed-stage editing reports conservative downstream impact", () => {
  assert.deepEqual(deriveDeploymentEditImpact("project", "localization"), {
    stageId: "project",
    returnStageId: "project",
    items: [
      { stageId: "maps", label: "准备地图", status: "reconfirm" },
      { stageId: "annotations", label: "标记地图", status: "invalid" },
      { stageId: "localization", label: "配置定位路线", status: "invalid" },
      { stageId: "export", label: "校验并导出", status: "locked" },
    ],
  });
});

test("task console renderer exposes one primary action and read-only progress", () => {
  const markup = taskConsoleMarkup({
    id: "maps.source",
    stageId: "maps",
    title: "选择地图来源",
    detail: "选择导入或建图。",
    completionCriterion: "已明确来源",
    primaryAction: { id: "choose-map-source", label: "选择地图来源" },
    nextTaskLabel: "读取并校验地图文件",
    progressItems: [
      { id: "source", label: "选择地图来源", status: "current" },
    ],
  });

  assert.match(markup.summaryHtml, /id="deploymentTaskPrimary"/);
  assert.equal((markup.summaryHtml.match(/data-task-action=/g) || []).length, 1);
  assert.match(markup.progressHtml, /本阶段进度/);
  assert.doesNotMatch(markup.progressHtml, /<(button|input|select)\b/);
  assert.match(markup.afterHtml, /读取并校验地图文件/);
});

test("deployment page exposes one task console instead of editable side rails", () => {
  for (const id of [
    "deploymentTaskConsole",
    "deploymentTaskWorkspace",
    "deploymentTaskProgress",
    "deploymentTaskPrimary",
  ]) {
    assert.match(deploymentPage, new RegExp(`id=["']${id}["']`));
  }
  assert.doesNotMatch(deploymentPage, /class=["'][^"']*deployment-left-rail/);
  assert.doesNotMatch(deploymentPage, /class=["'][^"']*deployment-inspector-rail/);
});

test("single-task console keeps a readable desktop measure and a quiet progress rail", () => {
  assert.match(
    deploymentStyles,
    /\.deployment-guide,\s*\.deployment-task-console\s*\{[^}]*width:\s*min\(100%,\s*1480px\)/s,
  );
  assert.match(
    deploymentStyles,
    /\.deployment-task-console\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+292px/s,
  );
  assert.match(
    deploymentStyles,
    /\.deployment-task-workspace\s+\.page-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s,
  );
  assert.match(deploymentStyles, /@media \(max-width:\s*1040px\)[\s\S]*\.deployment-task-console/);
});

test("deployment guide and task console share the same outer alignment measure", () => {
  assert.match(
    deploymentStyles,
    /body:has\(#deploymentTaskConsole\)\[data-deployment-stage\]\s+main\.page-main\s*>\s*\.page-header,\s*body:has\(#deploymentTaskConsole\)\[data-deployment-stage\]\s+#deploymentGuide,\s*body:has\(#deploymentTaskConsole\)\[data-deployment-stage\]\s+#deploymentTaskConsole\s*\{[^}]*width:\s*min\(100%,\s*1480px\)\s*!important[^}]*max-width:\s*1480px\s*!important/s,
    "the page header, guide, and task console must resolve to one centered outer width in every stage",
  );
  assert.match(
    deploymentStyles,
    /body:has\(#deploymentTaskConsole\)\[data-deployment-stage\]\s+#deploymentGuide\s*\{[^}]*padding:\s*16px\s+0/s,
    "the guide must not add a horizontal inset that shifts its visible step rail away from the task console",
  );
});

test("deployment controller renders one derived task and gates panels by task", () => {
  assert.match(deploymentSource, /deriveDeploymentTask/);
  assert.match(deploymentSource, /renderDeploymentTaskConsole/);
  assert.match(deploymentSource, /applyDeploymentTaskGating/);
  assert.match(deploymentSource, /data-deployment-task/);
  assert.doesNotMatch(deploymentSource, /focusGuideTarget\(guideTargetForStep\(stepId\)\)/);
});

test("map assignment submits the task-derived map and stage rather than stale canvas state", () => {
  assert.match(deploymentSource, /const targetMapId\s*=\s*deploymentTask\?\.targetMapId/);
  assert.match(deploymentSource, /map_asset_id:\s*targetMapId/);
  assert.match(deploymentSource, /stage:\s*targetStageId/);
  assert.doesNotMatch(
    deploymentSource,
    /async function assignCurrentMapStage\(\)[\s\S]*?map_asset_id:\s*activeMap\.id/,
  );
  assert.match(deploymentSource, /synchronizeTaskWorkspace/);
  assert.match(deploymentSource, /stageSelect\.value\s*=\s*deploymentTask\.targetStageId/);
  assert.match(deploymentSource, /stageSelect\.disabled\s*=\s*true/);
});

test("completed map review exposes map editors and successful saves leave edit mode", () => {
  assert.match(deploymentPage, /data-deployment-tasks="[^"]*maps\.edit[^"]*"/);
  assert.match(deploymentSource, /function completeDeploymentEdit/);
  assert.match(
    deploymentSource,
    /function completeDeploymentEdit[\s\S]*editingDeploymentStage\s*=\s*null[\s\S]*viewedDeploymentStage\s*=\s*null/,
  );
  assert.match(
    deploymentSource,
    /async function saveCurrentDeploymentFlow[\s\S]*completeDeploymentEdit/,
  );
  assert.match(
    deploymentStyles,
    /body\[data-deployment-task\$="\.edit"\] #deploymentTaskWorkspace \.page-top-action\s*\{[^}]*background:\s*transparent/,
  );
});

test("map upload fails closed on timeout or malformed responses", () => {
  assert.match(deploymentSource, /upload\.timeout\s*=\s*\d+/);
  assert.match(deploymentSource, /upload\.ontimeout\s*=/);
  assert.match(deploymentSource, /地图导入返回了无法解析的数据/);
});

test("canvas mutations retain the annotation workspace until the operator confirms completion", () => {
  const canvasMutationSource = deploymentSource.slice(
    deploymentSource.indexOf('canvas.addEventListener("pointerdown"'),
    deploymentSource.indexOf('canvas.addEventListener(\n  "wheel"'),
  );
  assert.match(deploymentSource, /function keepMapAnnotationOpen/);
  assert.match(canvasMutationSource, /已标记[\s\S]*任务过渡点[\s\S]*keepMapAnnotationOpen/);
  assert.match(canvasMutationSource, /已放置\$\{componentName\(data\.component\)\}[\s\S]*keepMapAnnotationOpen/);
  assert.match(canvasMutationSource, /组件朝向已保存[\s\S]*keepMapAnnotationOpen/);
  assert.match(canvasMutationSource, /组件尺寸已保存[\s\S]*keepMapAnnotationOpen/);
  assert.match(canvasMutationSource, /componentDrag[\s\S]*keepMapAnnotationOpen/);
});

test("task transitions expose a persisted speed choice, a visible heading, and localization reuses topology identity", () => {
  assert.match(deploymentPage, /id="waypointTransitionSpeed"/);
  assert.match(deploymentPage, /id="waypointTransitionYaw"/);
  assert.match(deploymentPage, /id="saveWaypointTransitionSpeed"/);
  assert.match(deploymentPage, /id="localizationTopologySummary"/);
  assert.match(deploymentPage, /楼层布局模板（不是实际楼层）/);
  assert.match(deploymentSource, /speed_mode:\s*"single_point"/);
  assert.match(deploymentSource, /const isTargetFloorMap/);
  assert.match(deploymentSource, /const taskTransitionRole/);
  assert.match(deploymentSource, /任务过渡点会按创建顺序插入去程任务；返程按相反顺序经过/);
  assert.match(deploymentSource, /yaw:\s*yawDegrees\s*\*\s*Math\.PI\s*\/\s*180/);
  assert.match(deploymentSource, /function drawWaypointSymbol/);
  assert.match(deploymentSource, /drawWaypointSymbol,/);
  assert.match(deploymentSource, /function transitionRotateHandleAt/);
  assert.match(deploymentSource, /let waypointRotate = null;/);
  assert.match(deploymentSource, /拖动蓝色圆形方向手柄/);
  assert.match(deploymentSource, /body:\s*JSON\.stringify\(\{ yaw: waypointRotate\.yaw \}\)/);
  assert.match(deploymentSource, /当前实验任务只会编译用户楼层地图上的任务过渡点/);
  assert.match(deploymentSource, /building:\s*instance\.building\s*\|\|/);
});

test("session state persists view and drafts but never completed stages", () => {
  assert.match(deploymentSessionSource, /viewedDeploymentStage/);
  assert.match(deploymentSessionSource, /deploymentTaskDraft/);
  assert.doesNotMatch(deploymentSessionSource, /completedStages|workflowStatus|stageComplete/);
});

test("task action gate ignores a duplicate action while the first request is pending", async () => {
  const gate = createTaskActionGate();
  let calls = 0;
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const first = gate.run("maps.describe", async () => { calls += 1; await pending; return "ok"; });
  const second = gate.run("maps.describe", async () => { calls += 1; return "duplicate"; });
  assert.equal(await second, undefined);
  release();
  assert.equal(await first, "ok");
  assert.equal(calls, 1);
});

test("map import success refreshes facts before selecting the next task", () => {
  assert.match(deploymentSource, /await refreshTopology\(\)/);
  assert.match(deploymentSource, /deploymentTaskDraft\s*=\s*nextMapImportDraft\(\)/);
  assert.match(deploymentSource, /receipt:\s*\{\s*taskId:/s);
  assert.doesNotMatch(deploymentSource, /可继续选择下一张地图/);
});

test("completed stage review is read-only until edit impact is confirmed", () => {
  assert.match(deploymentSource, /editingDeploymentStage/);
  assert.match(deploymentSource, /deriveDeploymentEditImpact/);
  assert.match(deploymentSource, /openDeploymentEditImpact/);
  assert.match(deploymentSource, /confirmDeploymentStageEdit/);
  assert.match(deploymentPage, /id="deploymentEditImpactDialog"[^]*aria-modal="true"/s);
  assert.match(deploymentStyles, /\.deployment-review-readonly/);
});

test("entering edit mode does not send a rollback request", () => {
  assert.doesNotMatch(deploymentSource, /api\/deployments[^\n]*rollback/);
  assert.match(deploymentSource, /editingDeploymentStage\s*=\s*pendingEditStage/);
});

test("single-task console has explicit responsive and light-theme rules", () => {
  assert.match(deploymentStyles, /\.deployment-task-console\s*\{[^}]*max-width:\s*1480px/s);
  assert.match(deploymentStyles, /@media\s*\(max-width:\s*1040px\)[^]*\.deployment-task-console/s);
  assert.match(deploymentStyles, /@media\s*\(max-width:\s*760px\)[^]*\.deployment-guide-steps/s);
  assert.match(deploymentStyles, /body\.theme-light[^]*\.deployment-task-card/s);
  assert.match(deploymentStyles, /\.deployment-edit-impact[^]*:focus-visible/s);
  assert.match(deploymentStyles, /\.deployment-edit-impact\.deployment-hidden\s*\{[^}]*display:\s*none\s*!important/);
  assert.doesNotMatch(
    deploymentStyles,
    /@media\s*\(max-width:\s*1040px\)[\s\S]*?\.deployment-task-progress\s*\{[^}]*order:\s*-1/,
  );
  assert.match(
    deploymentStyles,
    /@media\s*\(max-width:\s*760px\)[\s\S]*?\.deployment-task-card\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/,
  );
});

test("task changes announce status and move focus to the task heading", () => {
  assert.match(deploymentPage, /id="deploymentTaskReceipt"[^]*role="status"/s);
  assert.match(deploymentSource, /focusCurrentTaskHeading/);
  assert.match(deploymentSource, /prefers-reduced-motion|matchMedia/);
});

test("deployment project list exposes a themed delete action", () => {
  assert.match(deploymentPage, /id=["']projectList["']/);
  assert.match(deploymentSource, /delete-project/);
  assert.match(deploymentSource, /aria-label="删除部署项目/);
  assert.doesNotMatch(deploymentSource, /title="删除部署项目"/);
  assert.match(deploymentSource, /method:\s*["']DELETE["']/);
  assert.match(deploymentSource, /确认删除部署项目/);
  assert.match(deploymentStyles, /\.project-delete-button/);
  assert.match(deploymentStyles, /\.project-delete-button:hover/);
});

test("project actions keep a stable reserved action area without hover reflow", () => {
  assert.match(deploymentSource, /project-delete-slot/);
  assert.match(
    deploymentStyles,
    /\.project-delete-slot\s*\{[^}]*width:\s*82px/s,
  );
  assert.match(
    deploymentStyles,
    /\.project-delete-button\s*\{[^}]*margin:\s*0/s,
  );
  assert.match(
    deploymentStyles,
    /\.project-row-actions\s*\{[^}]*grid-template-columns:\s*auto\s+82px/s,
  );
  assert.match(
    deploymentStyles,
    /\.project-delete-button\s*\{[^}]*width:\s*82px/s,
  );
  assert.doesNotMatch(deploymentStyles, /\.project-delete-button:hover,[^\{]*\{[^}]*width:/s);
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
    map_instances: [{ map_asset_id: "map-2", role: "typical_floor", building: "1", unit: "1", floor: 15 }],
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
    map_instances: [
      { map_asset_id: "map-1", role: "lobby", building: "1", unit: "1", floor: 1 },
      { map_asset_id: "map-2", role: "typical_floor", building: "1", unit: "1", floor: 15 },
    ],
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
    "deploymentTaskCard",
    "deploymentTaskPrimary",
    "deploymentTaskProgress",
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
  assert.match(deploymentSource, /focusCurrentTaskHeading/);
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
  assert.match(deploymentSource, /当前使用：\$\{localizationTemplate\.name/);
  assert.doesNotMatch(
    deploymentSource,
    /\$\("localizationTemplateFile"\)\.value\s*=\s*""/,
    "a successful upload must not clear the native file picker while the template is active",
  );
});

test("closed localization route editor remains hidden until the operator opens it", () => {
  assert.match(
    deploymentStyles,
    /\.localization-route-dialog\.deployment-hidden\s*\{\s*display:\s*none(?:\s*!important)?;/,
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
