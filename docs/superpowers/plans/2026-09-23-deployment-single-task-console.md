# Deployment Single-Task Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the deployment page's competing left/center/right editing surfaces with one fact-derived current task, one primary action, a contextual workspace, and a read-only progress rail.

**Architecture:** Keep `deriveDeploymentWorkflow()` as the authoritative five-stage projection of Backend facts. Add pure task and edit-impact derivation in `deployment/workflow.js`, pure task-console markup helpers in a focused `deployment/task-console.js`, and leave request orchestration in `deployment.js`; no second persisted workflow state and no API changes.

**Tech Stack:** Browser-native ES modules, HTML/CSS, Node.js `node:test`, existing Python Backend APIs, agent-browser visual verification.

**Spec:** `docs/superpowers/specs/2026-09-23-deployment-single-task-console-design.md`

## Global Constraints

- Preserve existing Backend APIs, ROS/Supervisor ownership, map formats, deployment contracts, URL paths, and existing DOM ids used by controllers.
- Backend project snapshots, topology, mapping-session responses, and compiler preview remain authoritative; browser state may hold only view state and unsubmitted drafts.
- Desktop workbench maximum width is approximately `1480px`; read-only progress rail is approximately `292px`; normal body copy is at least `14px`, except genuinely secondary metadata at `11px` or above.
- A rendered task state has exactly one primary action; the progress rail contains no mutation controls.
- Completed-stage review is read-only until the operator explicitly confirms edit mode.
- Safe successful writes auto-advance only after the server response is accepted and authoritative facts are refreshed; failures remain on the same task.
- Do not modify `shared/contracts/deployment.md` or Mobile because this plan changes no shared data, endpoint, or cross-client behavior.
- Preserve all unrelated uncommitted changes in the dirty worktree; never reset, discard, or reformat files outside this plan.
- Use `apply_patch` for manual file edits and commit only the files listed by each task.

---

### Task 1: Derive one current task and edit-impact model from existing facts

**Files:**
- Modify: `autodrive_console/web/deployment/workflow.js:1-180`
- Test: `frontend/test/deployment-workflow.test.mjs`

**Interfaces:**
- Consumes: existing `deriveDeploymentWorkflow(project, topology, preview)` result and existing `SiteProject`, topology, mapping-session, and local draft objects.
- Produces: `deriveDeploymentTask(context): DeploymentTask`, `deriveDeploymentEditImpact(stageId, currentStageId): DeploymentEditImpact`, and exported task/status constants used by later tasks.

`DeploymentTask` must have this exact shape:

```js
{
  id: "maps.source",
  stageId: "maps",
  title: "选择地图来源",
  detail: "选择导入已有地图或车端实时建图。",
  completionCriterion: "已明确当前地图的来源",
  primaryAction: { id: "choose-map-source", label: "选择地图来源", target: "mapSourceChoices" },
  nextTaskLabel: "读取并校验地图文件",
  progressItems: [{ id: "source", label: "选择地图来源", status: "current" }],
  targetMapId: null,
  targetStageId: "lobby",
  readOnly: false,
}
```

`context.draft` uses only these transient keys:

```js
{
  mapSource: null | "import" | "mapping",
  fileSummary: null | { yamlCount, pgmCount, pcdCount, indexCount, valid },
  mapLabel: "",
  latestCreatedMapId: null,
  receipt: null | { taskId, message },
}
```

- [ ] **Step 1: Add failing task-derivation tests**

Append focused tests that prove map work is sequential and that non-map stages reuse the existing next action:

```js
import {
  deriveDeploymentEditImpact,
  deriveDeploymentTask,
  deriveDeploymentWorkflow,
} from "../../autodrive_console/web/deployment/workflow.js";

test("map preparation begins with one source-selection task", () => {
  const project = { ...baseProject, deployment_flow: [
    { id: "lobby", type: "lobby", label: "电梯大厅" },
    { id: "target", type: "target_floor", label: "用户楼层" },
  ] };
  const topology = { stages: [
    { stage: "lobby", label: "电梯大厅", map_asset_id: null },
    { stage: "target", label: "用户楼层", map_asset_id: null },
  ] };
  const workflow = deriveDeploymentWorkflow(project, topology, null);
  const task = deriveDeploymentTask({ workflow, project, topology, mappingSession: null, draft: {} });

  assert.equal(task.id, "maps.source");
  assert.equal(task.primaryAction.id, "choose-map-source");
  assert.equal(task.targetStageId, "lobby");
  assert.equal(task.progressItems.filter((item) => item.status === "current").length, 1);
});

test("valid selected files advance the local map task to naming and checking", () => {
  const project = { ...baseProject, deployment_flow: [{ id: "lobby", type: "lobby", label: "电梯大厅" }] };
  const topology = { stages: [{ stage: "lobby", label: "电梯大厅", map_asset_id: null }] };
  const workflow = deriveDeploymentWorkflow(project, topology, null);
  const task = deriveDeploymentTask({
    workflow,
    project,
    topology,
    mappingSession: null,
    draft: {
      mapSource: "import",
      fileSummary: { yamlCount: 1, pgmCount: 1, pcdCount: 1, indexCount: 0, valid: true },
      mapLabel: "电梯大厅",
    },
  });

  assert.equal(task.id, "maps.describe");
  assert.equal(task.primaryAction.id, "import-map");
  assert.equal(task.primaryAction.label, "导入并继续");
  assert.equal(task.nextTaskLabel, "绑定地图阶段");
});

test("an existing unbound map advances directly to stage binding", () => {
  const project = { ...baseProject, deployment_flow: [{ id: "lobby", type: "lobby", label: "电梯大厅" }], map_assets: [{ id: "map-1", label: "电梯大厅" }] };
  const topology = { stages: [{ stage: "lobby", label: "电梯大厅", map_asset_id: null }] };
  const workflow = deriveDeploymentWorkflow(project, topology, null);
  const task = deriveDeploymentTask({ workflow, project, topology, mappingSession: null, draft: { latestCreatedMapId: "map-1" } });

  assert.equal(task.id, "maps.assign");
  assert.equal(task.targetMapId, "map-1");
  assert.equal(task.targetStageId, "lobby");
  assert.equal(task.primaryAction.id, "assign-map-stage");
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
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
pixi run node --test --test-name-pattern="map preparation|valid selected files|existing unbound map|completed-stage editing" frontend/test/deployment-workflow.test.mjs
```

Expected: FAIL because `deriveDeploymentTask` and `deriveDeploymentEditImpact` are not exported.

- [ ] **Step 3: Implement the pure task and impact derivation**

Add stable task ids and a factory; do not inspect the DOM:

```js
export const DEPLOYMENT_TASK_IDS = Object.freeze({
  MAP_SOURCE: "maps.source",
  MAP_IMPORT: "maps.import",
  MAP_DESCRIBE: "maps.describe",
  MAP_ASSIGN: "maps.assign",
});

const MAP_PROGRESS = [
  ["source", "选择地图来源"],
  ["import", "读取并校验地图"],
  ["describe", "命名并检查"],
  ["assign", "绑定地图阶段"],
  ["confirm", "确认当前地图"],
];

function mapProgress(current, completed = []) {
  return MAP_PROGRESS.map(([id, label]) => ({
    id,
    label,
    status: completed.includes(id) ? "complete" : id === current ? "current" : "pending",
  }));
}

function deploymentTask({ id, stageId, title, detail, completionCriterion, primaryAction, nextTaskLabel, progressItems, targetMapId = null, targetStageId = null, readOnly = false }) {
  return { id, stageId, title, detail, completionCriterion, primaryAction, nextTaskLabel, progressItems, targetMapId, targetStageId, readOnly };
}

export function deriveDeploymentTask({ workflow, project, topology, mappingSession = null, draft = {}, viewedStage = null }) {
  const stageId = viewedStage || workflow.current.id;
  if (viewedStage && viewedStage !== workflow.current.id) {
    const reviewed = workflow.steps.find((item) => item.id === viewedStage);
    return deploymentTask({
      id: `${viewedStage}.review`,
      stageId: viewedStage,
      title: reviewed.label,
      detail: "正在只读回看已完成阶段。",
      completionCriterion: reviewed.detail,
      primaryAction: { id: "return-current", label: "返回当前任务", target: "deploymentTaskTitle" },
      nextTaskLabel: workflow.next.label,
      progressItems: workflow.steps.map((item) => ({ id: item.id, label: item.label, status: item.status })),
      readOnly: true,
    });
  }
  if (stageId !== "maps") {
    return deploymentTask({
      id: `${stageId}.${workflow.next.id}`,
      stageId,
      title: workflow.next.label,
      detail: workflow.next.detail || workflow.current.reason || workflow.current.detail,
      completionCriterion: workflow.current.detail,
      primaryAction: { id: workflow.next.id, label: workflow.next.label, target: workflow.next.target },
      nextTaskLabel: workflow.steps[workflow.steps.findIndex((item) => item.id === stageId) + 1]?.label || "完成部署",
      progressItems: workflow.checklist.map((item, index) => ({ id: String(index), label: item.label, status: item.done ? "complete" : "pending" })),
      targetMapId: workflow.next.targetMapId || null,
    });
  }
  const stages = list(topology?.stages);
  const nextStage = stages.find((item) => !item.map_asset_id) || null;
  const assignedMapIds = new Set(stages.map((item) => item.map_asset_id).filter(Boolean));
  const maps = list(project?.map_assets);
  const unboundMap = maps.find((item) => item.id === draft.latestCreatedMapId)
    || maps.find((item) => !assignedMapIds.has(item.id))
    || null;
  if (unboundMap && nextStage) {
    return deploymentTask({
      id: DEPLOYMENT_TASK_IDS.MAP_ASSIGN,
      stageId,
      title: `绑定“${unboundMap.label || unboundMap.id}”的地图阶段`,
      detail: `将当前地图绑定到“${nextStage.label}”。`,
      completionCriterion: "地图已保存到正确的部署阶段",
      primaryAction: { id: "assign-map-stage", label: "保存绑定并继续", target: "mapStageAssignment" },
      nextTaskLabel: stages.filter((item) => !item.map_asset_id).length > 1 ? "准备下一张地图" : "标记地图",
      progressItems: mapProgress("assign", ["source", "import", "describe"]),
      targetMapId: unboundMap.id,
      targetStageId: nextStage.stage,
    });
  }
  if (!draft.mapSource) {
    return deploymentTask({
      id: DEPLOYMENT_TASK_IDS.MAP_SOURCE,
      stageId,
      title: "选择地图来源",
      detail: "选择导入已有地图或车端实时建图。",
      completionCriterion: "已明确当前地图的来源",
      primaryAction: { id: "choose-map-source", label: "选择地图来源", target: "mapSourceChoices" },
      nextTaskLabel: "读取并校验地图文件",
      progressItems: mapProgress("source"),
      targetStageId: nextStage?.stage || null,
    });
  }
  if (draft.mapSource === "mapping") {
    const activeSession = mappingSession && ["prepared", "running", "stopping"].includes(mappingSession.state);
    return deploymentTask({
      id: activeSession ? "maps.mapping_continue" : "maps.mapping_prepare",
      stageId,
      title: activeSession ? "继续车端实时建图" : "准备车端实时建图",
      detail: activeSession ? "返回当前建图会话，保存结果后继续绑定地图阶段。" : "选择建图模板和地图名称，准备受控建图会话。",
      completionCriterion: "建图结果已保存为当前项目地图快照",
      primaryAction: activeSession
        ? { id: "open-mapping-workbench", label: "进入建图工作台", target: "openMappingWorkbench" }
        : { id: "prepare-mapping", label: "准备建图会话", target: "prepareMapping" },
      nextTaskLabel: "命名并检查地图",
      progressItems: mapProgress("import", ["source"]),
      targetStageId: nextStage?.stage || null,
    });
  }
  if (!draft.fileSummary?.valid) {
    return deploymentTask({
      id: DEPLOYMENT_TASK_IDS.MAP_IMPORT,
      stageId,
      title: "读取并校验地图文件",
      detail: "选择 YAML、PGM、可选 PCD 和兼容索引文件。",
      completionCriterion: "文件组合通过浏览器预检查",
      primaryAction: { id: "select-map-files", label: "选择地图文件", target: "mapFolder" },
      nextTaskLabel: "命名并检查地图",
      progressItems: mapProgress("import", ["source"]),
      targetStageId: nextStage?.stage || null,
    });
  }
  return deploymentTask({
    id: DEPLOYMENT_TASK_IDS.MAP_DESCRIBE,
    stageId,
    title: "命名并检查地图",
    detail: "填写现场可识别名称，并确认文件清单后导入项目快照。",
    completionCriterion: "名称清晰且地图文件信息无误",
    primaryAction: { id: "import-map", label: "导入并继续", target: "importMap" },
    nextTaskLabel: "绑定地图阶段",
    progressItems: mapProgress("describe", ["source", "import"]),
    targetStageId: nextStage?.stage || null,
  });
}

export function deriveDeploymentEditImpact(stageId, currentStageId) {
  const order = ["project", "maps", "annotations", "localization", "export"];
  const labels = { project: "创建项目", maps: "准备地图", annotations: "标记地图", localization: "配置定位路线", export: "校验并导出" };
  const currentIndex = order.indexOf(currentStageId);
  const startIndex = order.indexOf(stageId) + 1;
  const items = order.slice(startIndex, currentIndex + 2).map((item, index) => ({
    stageId: item,
    label: labels[item],
    status: index === 0 ? "reconfirm" : item === "export" ? "locked" : "invalid",
  }));
  return { stageId, returnStageId: stageId, items };
}
```

Treat file selection as local preparation: because the existing upload endpoint receives files and `label` together, `maps.describe` performs the actual upload without adding a rename endpoint.

- [ ] **Step 4: Run all workflow tests**

Run:

```bash
pixi run node --test frontend/test/deployment-workflow.test.mjs
```

Expected: PASS; existing global-stage tests remain unchanged.

- [ ] **Step 5: Commit the pure workflow model**

```bash
git add autodrive_console/web/deployment/workflow.js frontend/test/deployment-workflow.test.mjs
git commit -m "feat: derive deployment console tasks"
```

---

### Task 2: Build the semantic single-task console shell

**Files:**
- Create: `autodrive_console/web/deployment/task-console.js`
- Modify: `autodrive_console/web/deployment.html:48-600`
- Modify: `autodrive_console/web/deployment.css:324-610,1472-2070`
- Test: `frontend/test/deployment-workflow.test.mjs`

**Interfaces:**
- Consumes: `DeploymentTask` and existing five-stage `workflow` objects.
- Produces: `taskConsoleMarkup(task, workflow, options, escapeHtml): { summaryHtml, progressHtml, afterHtml }` and stable shell ids used by `deployment.js` in Task 3.

Stable shell ids:

```text
deploymentGuideSteps
deploymentTaskConsole
deploymentTaskReceipt
deploymentTaskCard
deploymentTaskTitle
deploymentTaskDetail
deploymentTaskCriterion
deploymentTaskPrimary
deploymentTaskWorkspace
deploymentTaskProgress
deploymentEditImpactDialog
```

- [ ] **Step 1: Add failing structural tests**

```js
import { taskConsoleMarkup } from "../../autodrive_console/web/deployment/task-console.js";

test("deployment page exposes one task console instead of editable side rails", () => {
  for (const id of ["deploymentTaskConsole", "deploymentTaskWorkspace", "deploymentTaskProgress", "deploymentTaskPrimary"]) {
    assert.match(deploymentPage, new RegExp(`id=["']${id}["']`));
  }
  assert.doesNotMatch(deploymentPage, /class=["'][^"']*deployment-left-rail/);
  assert.doesNotMatch(deploymentPage, /class=["'][^"']*deployment-inspector-rail/);
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
    progressItems: [{ id: "source", label: "选择地图来源", status: "current" }],
  }, { steps: [] });
  assert.match(markup.summaryHtml, /id="deploymentTaskPrimary"/);
  assert.match(markup.progressHtml, /本阶段进度/);
  assert.doesNotMatch(markup.progressHtml, /<(button|input|select)\b/);
});
```

- [ ] **Step 2: Run the structural tests and verify they fail**

Run:

```bash
pixi run node --test --test-name-pattern="one task console|one primary action" frontend/test/deployment-workflow.test.mjs
```

Expected: FAIL because the new module and shell do not exist.

- [ ] **Step 3: Add the pure markup helper**

Create `task-console.js` with HTML generation only:

```js
export function taskConsoleMarkup(task, workflow, { pending = false, receipt = null } = {}, esc = String) {
  const progress = task.progressItems.map((item, index) => `
    <div class="deployment-task-progress-item ${esc(item.status)}">
      <span>${item.status === "complete" ? "✓" : index + 1}</span>
      <div><b>${esc(item.label)}</b><small>${esc(item.status === "current" ? "正在进行" : item.status === "complete" ? "已完成" : "待完成")}</small></div>
    </div>`).join("");
  return {
    summaryHtml: `${receipt ? `<div id="deploymentTaskReceipt" class="deployment-task-receipt" role="status">${esc(receipt.message)}</div>` : `<div id="deploymentTaskReceipt" class="deployment-task-receipt deployment-hidden" role="status"></div>`}
    <section id="deploymentTaskCard" class="deployment-task-card" aria-labelledby="deploymentTaskTitle">
      <div><span class="deployment-task-sequence">当前任务 · ${esc(task.stageId)}</span><h2 id="deploymentTaskTitle" tabindex="-1">${esc(task.title)}</h2><p id="deploymentTaskDetail">${esc(task.detail)}</p><p id="deploymentTaskCriterion"><span>完成标准</span>${esc(task.completionCriterion)}</p></div>
      <div class="deployment-task-action"><button id="deploymentTaskPrimary" class="page-top-action" type="button" data-task-action="${esc(task.primaryAction.id)}" ${pending ? "disabled aria-busy=\"true\"" : ""}>${esc(pending ? "正在处理…" : task.primaryAction.label)}</button></div>
    </section>`,
    progressHtml: `<h2>本阶段进度</h2>${progress}`,
    afterHtml: `<b>成功后：</b>${esc(task.nextTaskLabel)}`,
  };
}
```

The module must not import `deployment.js`, issue requests, read globals, or mutate DOM.

- [ ] **Step 4: Restructure the HTML without duplicating existing controls**

Keep the existing five-step container and all existing form/canvas ids. Replace the current guide body and three-column rail wrappers with this skeleton:

```html
<section id="deploymentGuide" class="deployment-guide" aria-labelledby="deploymentGuideTitle">
  <div class="deployment-guide-project">
    <div><h2 id="deploymentGuideTitle">按顺序完成部署</h2><p class="deployment-guide-intro">系统会根据当前项目事实给出唯一下一步。</p></div>
    <div class="deployment-guide-progress" aria-label="部署完成进度"><strong id="deploymentGuideProgressValue">0%</strong><span id="deploymentGuideProgressMeta">0 / 5 步已完成</span></div>
  </div>
  <div id="deploymentGuideSteps" class="deployment-guide-steps" role="list" aria-label="部署步骤"></div>
</section>
<section id="deploymentTaskConsole" class="deployment-task-console">
  <div class="deployment-task-main">
    <div id="deploymentTaskSummary"><div id="deploymentTaskReceipt" class="deployment-task-receipt deployment-hidden" role="status"></div><section id="deploymentTaskCard" class="deployment-task-card"><div><h2 id="deploymentTaskTitle" tabindex="-1">正在读取项目状态…</h2><p id="deploymentTaskDetail">项目加载后显示当前任务。</p></div><button id="deploymentTaskPrimary" class="page-top-action" type="button" disabled>读取下一步</button></section></div>
    <main id="deploymentTaskWorkspace" class="deployment-task-workspace">
      <section id="deploymentTaskPanels" class="page-grid"></section>
    </main>
    <div id="deploymentTaskAfter" class="deployment-task-after" aria-live="polite"></div>
  </div>
  <aside id="deploymentTaskProgress" class="deployment-task-progress" aria-label="本阶段进度"></aside>
</section>
<section id="deploymentEditImpactDialog" class="deployment-edit-impact deployment-hidden" role="dialog" aria-modal="true" aria-labelledby="deploymentEditImpactTitle"></section>
```

Move the existing panel articles currently inside `deployment.html:82-600` into `deploymentTaskPanels` in their existing source order, removing only the `deployment-left-rail`, `deployment-setup-rail`, and `deployment-inspector-rail` wrapper elements. Do not rename or duplicate `projectName`, `deploymentFlowEditor`, `mapFolder`, `mapLabel`, `importMap`, `mappingControls`, `mapWorkspace`, `mapStageAssignment`, `assignMapStage`, localization ids, or compiler ids.

- [ ] **Step 5: Replace three-column desktop rules with console layout rules**

Implement these layout contracts in `deployment.css` and delete/override the legacy `deployment-left-rail` / `deployment-inspector-rail` grid rules:

```css
.deployment-guide,
.deployment-task-console { width: min(100%, 1480px); margin-inline: auto; }
.deployment-task-console { display: grid; grid-template-columns: minmax(0, 1fr) 292px; gap: 18px; }
.deployment-task-main { display: grid; min-width: 0; gap: 14px; }
.deployment-task-card { display: grid; grid-template-columns: minmax(0, 1fr) 206px; gap: 28px; align-items: center; }
.deployment-task-workspace { min-width: 0; }
.deployment-task-progress { align-self: start; }
.deployment-task-progress button,
.deployment-task-progress input,
.deployment-task-progress select { display: none !important; }
@media (max-width: 1040px) {
  .deployment-task-console { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 760px) {
  .deployment-task-card { grid-template-columns: minmax(0, 1fr); }
  .deployment-guide-steps { grid-template-columns: repeat(5, minmax(154px, 1fr)); overflow-x: auto; }
}
```

- [ ] **Step 6: Run the structural tests**

Run:

```bash
pixi run node --test frontend/test/deployment-workflow.test.mjs
```

Expected: PASS; the page contains every existing controller id exactly once.

- [ ] **Step 7: Commit the shell**

```bash
git add autodrive_console/web/deployment/task-console.js autodrive_console/web/deployment.html autodrive_console/web/deployment.css frontend/test/deployment-workflow.test.mjs
git commit -m "refactor: add deployment single-task shell"
```

---

### Task 3: Render the current task and gate the workspace from one model

**Files:**
- Modify: `autodrive_console/web/deployment/task-console.js`
- Modify: `autodrive_console/web/deployment.js:440-570`
- Modify: `autodrive_console/web/deployment/session-state.js`
- Test: `frontend/test/deployment-workflow.test.mjs`

**Interfaces:**
- Consumes: `deriveDeploymentTask()`, `taskConsoleMarkup()`, existing `selectedProject`, `topology`, `mappingSession`, `taskCompilerPreview`, and `viewedDeploymentStage`.
- Produces: `renderDeploymentTaskConsole()`, `applyDeploymentTaskGating()`, and transient `deploymentTaskDraft`/`editingDeploymentStage` state.

- [ ] **Step 1: Add failing controller contract tests**

```js
test("deployment controller renders one derived task and gates panels by task", () => {
  assert.match(deploymentSource, /deriveDeploymentTask/);
  assert.match(deploymentSource, /renderDeploymentTaskConsole/);
  assert.match(deploymentSource, /applyDeploymentTaskGating/);
  assert.match(deploymentSource, /data-deployment-task/);
  assert.doesNotMatch(deploymentSource, /focusGuideTarget\(guideTargetForStep\(stepId\)\)/);
});

test("session state persists view and drafts but never completed stages", () => {
  const sessionSource = readFileSync(new URL("../../autodrive_console/web/deployment/session-state.js", import.meta.url), "utf8");
  assert.match(sessionSource, /viewedDeploymentStage/);
  assert.match(sessionSource, /deploymentTaskDraft/);
  assert.doesNotMatch(sessionSource, /completedStages|workflowStatus|stageComplete/);
});
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
pixi run node --test --test-name-pattern="renders one derived task|persists view and drafts" frontend/test/deployment-workflow.test.mjs
```

Expected: FAIL because the task model is not wired to the controller.

- [ ] **Step 3: Add transient controller state and rendering**

Import the new helpers and replace the old guide-current/checklist renderer:

```js
import { deriveDeploymentTask, deriveDeploymentEditImpact, deriveDeploymentWorkflow } from "./deployment/workflow.js";
import { taskConsoleMarkup } from "./deployment/task-console.js";

let deploymentTask;
let deploymentTaskPending = null;
let deploymentTaskDraft = { mapSource: null, fileSummary: null, mapLabel: "", latestCreatedMapId: null, receipt: null };
let editingDeploymentStage = null;

function renderDeploymentTaskConsole() {
  deploymentWorkflow = deriveDeploymentWorkflow(selectedProject, topology, taskCompilerPreview);
  deploymentTask = deriveDeploymentTask({
    workflow: deploymentWorkflow,
    project: selectedProject,
    topology,
    mappingSession,
    draft: deploymentTaskDraft,
    viewedStage: editingDeploymentStage || viewedDeploymentStage,
  });
  const markup = taskConsoleMarkup(
    deploymentTask,
    deploymentWorkflow,
    { pending: deploymentTaskPending === deploymentTask.id, receipt: deploymentTaskDraft.receipt },
    esc,
  );
  $("deploymentTaskSummary").innerHTML = markup.summaryHtml;
  $("deploymentTaskProgress").innerHTML = markup.progressHtml;
  $("deploymentTaskAfter").innerHTML = markup.afterHtml;
  applyDeploymentTaskGating();
}
```

Call this renderer after project, topology, mapping-session, preview, active-map, and viewed-stage changes. Existing `renderDeploymentGuide()` may keep rendering the five global stage buttons, but it must not render a second current-task card or editable checklist.

- [ ] **Step 4: Gate existing panels by current task**

Add `data-deployment-task` / `data-deployment-tasks` to existing panels and implement one visibility function:

```js
function applyDeploymentTaskGating() {
  const taskId = deploymentTask?.id || "project.createProject";
  document.body.dataset.deploymentStage = deploymentTask?.stageId || "project";
  document.body.dataset.deploymentTask = taskId;
  document.querySelectorAll("[data-deployment-task], [data-deployment-tasks]").forEach((panel) => {
    const tasks = (panel.dataset.deploymentTasks || panel.dataset.deploymentTask || "").split(/\s+/).filter(Boolean);
    const visible = tasks.includes(taskId) || tasks.includes(`${deploymentTask.stageId}.*`);
    panel.classList.toggle("deployment-task-hidden", !visible);
    panel.setAttribute("aria-hidden", String(!visible));
  });
}
```

Use this exact panel-to-task mapping:

| Existing panel | `data-deployment-tasks` |
| --- | --- |
| Project creation and deployment-flow panels | `project.*` |
| Map import panel | `maps.source maps.import maps.describe` |
| Mapping-session panel | `maps.source maps.mapping_prepare maps.mapping_continue` |
| Map asset list | `maps.assign annotations.* localization.*` |
| Map canvas and annotation tools | `annotations.* localization.*` |
| Map-stage assignment panel | `maps.assign` |
| Localization binding/route panel | `localization.*` |
| Task compiler panel | `export.*` |

The wildcard is a literal value interpreted by `applyDeploymentTaskGating()` through `tasks.includes(`${deploymentTask.stageId}.*`)`. Import, mapping, assignment, annotation, localization, and export editors must never be simultaneously visible unless the table explicitly shares them.

Persist only `viewedDeploymentStage`, `mapSource`, and `mapLabel`. Keep `editingDeploymentStage`, receipts, `File`, `FileList`, upload progress, `fileSummary`, and all completion status in memory only. A browser refresh intentionally exits edit mode, clears stale success messages, and requires reselecting local files while retaining the last server-confirmed project state.

- [ ] **Step 5: Make stage review focus the task heading, not hidden editors**

Update `focusGuideStep()` and return-current handling:

```js
function focusCurrentTaskHeading() {
  requestAnimationFrame(() => $("deploymentTaskTitle")?.focus({ preventScroll: false }));
}

function focusGuideStep(stepId) {
  if (!deploymentWorkflow || !isDeploymentStageUnlocked(deploymentWorkflow.current.id, stepId)) return;
  viewedDeploymentStage = stepId;
  editingDeploymentStage = null;
  persistDeploymentSession();
  renderDeploymentGuide();
  renderDeploymentTaskConsole();
  focusCurrentTaskHeading();
}
```

- [ ] **Step 6: Run the deployment workflow tests**

Run:

```bash
pixi run node --test frontend/test/deployment-workflow.test.mjs
```

Expected: PASS.

- [ ] **Step 7: Commit the controller integration**

```bash
git add autodrive_console/web/deployment/task-console.js autodrive_console/web/deployment.js autodrive_console/web/deployment/session-state.js autodrive_console/web/deployment.html frontend/test/deployment-workflow.test.mjs
git commit -m "feat: drive deployment workspace from current task"
```

---

### Task 4: Make map preparation sequential, single-flight, and auto-advancing

**Files:**
- Modify: `autodrive_console/web/deployment/task-console.js`
- Modify: `autodrive_console/web/deployment.js:1727-1818`
- Modify: `autodrive_console/web/deployment.html:144-187,524-536`
- Test: `frontend/test/deployment-workflow.test.mjs`

**Interfaces:**
- Consumes: existing file manifest logic, `/maps/upload`, stage assignment endpoint, mapping-session controls, and task ids from Task 1.
- Produces: one delegated task-action handler, `runDeploymentTaskActionOnce(taskId, work)`, and automatic refresh/advance after safe success.

- [ ] **Step 1: Add failing single-flight and sequential-map tests**

```js
import { createTaskActionGate } from "../../autodrive_console/web/deployment/task-console.js";

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
  assert.match(deploymentSource, /latestCreatedMapId\s*=\s*data\.map\.id/);
  assert.match(deploymentSource, /receipt:\s*\{\s*taskId:/s);
  assert.doesNotMatch(deploymentSource, /可继续选择下一张地图/);
});
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
pixi run node --test --test-name-pattern="task action gate|map import success" frontend/test/deployment-workflow.test.mjs
```

Expected: FAIL because duplicate actions are not centrally gated and the old success copy returns users to manual navigation.

- [ ] **Step 3: Implement the reusable single-flight gate**

```js
export function createTaskActionGate() {
  let active = null;
  return {
    get active() { return active; },
    async run(id, work) {
      if (active) return undefined;
      active = id;
      try { return await work(); }
      finally { active = null; }
    },
  };
}
```

Instantiate one gate in `deployment.js`. Every task primary action must use it; legacy control handlers called by the task action must not start a second request.

- [ ] **Step 4: Split file selection from upload without changing the API**

Keep `renderMapFolderSelection(files)` as the local manifest validator. On file selection, write its counts plus `valid` into `deploymentTaskDraft.fileSummary`, copy the suggested label into `deploymentTaskDraft.mapLabel`, and rerender. The visible task sequence is:

```text
maps.source -> maps.import (choose/read files) -> maps.describe (name/check and POST upload) -> maps.assign -> next stage or annotations
```

The POST remains exactly:

```js
payload.append("map_yaml", candidates[0].webkitRelativePath || candidates[0].name);
payload.append("label", $("mapLabel").value);
payload.append("kind", "custom");
files.forEach((file) => payload.append("files", file, file.webkitRelativePath || file.name));
```

No rename route is added.

Add a source-choice group inside the existing map import panel:

```html
<fieldset id="mapSourceChoices" class="deployment-map-source-choices">
  <legend>这张地图从哪里获得？</legend>
  <label><input type="radio" name="mapSource" value="import" data-map-source="import">导入已有地图</label>
  <label><input type="radio" name="mapSource" value="mapping" data-map-source="mapping">车端实时建图</label>
</fieldset>
```

Wire it without a request:

```js
$("mapSourceChoices").addEventListener("change", (event) => {
  const source = event.target.closest("[data-map-source]")?.dataset.mapSource;
  if (!source) return;
  deploymentTaskDraft = { ...deploymentTaskDraft, mapSource: source, fileSummary: null, latestCreatedMapId: null };
  persistDeploymentSession();
  renderDeploymentTaskConsole();
  focusCurrentTaskHeading();
});
```

- [ ] **Step 5: Route one primary action through existing controls**

Use event delegation on `deploymentTaskConsole`:

```js
$("deploymentTaskConsole").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-task-action]");
  if (!button) return;
  const actionId = button.dataset.taskAction;
  await taskActionGate.run(deploymentTask.id, async () => {
    deploymentTaskPending = deploymentTask.id;
    renderDeploymentTaskConsole();
    try { await runDeploymentTaskAction(actionId); }
    finally { deploymentTaskPending = null; renderDeploymentTaskConsole(); }
  });
});
```

`runDeploymentTaskAction()` must either focus the source/file control, call the factored existing upload/assignment/save function, or delegate to an existing safe controller action. It must not synthesize success.

Implement the routing table explicitly:

```js
async function runDeploymentTaskAction(actionId) {
  if (actionId === "choose-map-source") return focusGuideTarget("mapSourceChoices");
  if (actionId === "select-map-files") return $("mapFolder").click();
  if (actionId === "import-map") return importSelectedMap();
  if (actionId === "prepare-mapping") return prepareMappingSession();
  if (actionId === "open-mapping-workbench") return $("openMappingWorkbench").click();
  if (actionId === "assign-map-stage") return assignCurrentMapStage();
  return runDeploymentGuideAction(actionId);
}
```

Factor `importSelectedMap()`, `prepareMappingSession()`, and `assignCurrentMapStage()` out of their existing click listeners. The legacy buttons and the task primary button call the same functions so one business operation has one implementation.

- [ ] **Step 6: Auto-advance only after authoritative refresh**

After upload success:

```js
renderProject(data.project);
deploymentTaskDraft.latestCreatedMapId = data.map.id;
await refreshTopology();
deploymentTaskDraft.receipt = { taskId: "maps.describe", message: `${data.map.label}已导入并通过校验。` };
renderDeploymentTaskConsole();
focusCurrentTaskHeading();
```

After stage assignment success, clear the map draft except for a receipt, refresh project/topology, and let `deriveDeploymentTask()` select the next unbound stage. If every stage is bound, the existing global workflow advances to annotations.

In every catch block, preserve the draft, set an inline error, and keep the same `deploymentTask.id`.

- [ ] **Step 7: Run the focused and full deployment workflow tests**

Run:

```bash
pixi run node --test frontend/test/deployment-workflow.test.mjs
```

Expected: PASS; duplicate invocations call the worker once, failures do not advance, and old “choose the next map yourself” copy is gone.

- [ ] **Step 8: Commit sequential map preparation**

```bash
git add autodrive_console/web/deployment/task-console.js autodrive_console/web/deployment.js autodrive_console/web/deployment.html frontend/test/deployment-workflow.test.mjs
git commit -m "feat: guide maps through sequential preparation"
```

---

### Task 5: Add read-only completed-stage review and protected edit entry

**Files:**
- Modify: `autodrive_console/web/deployment/task-console.js`
- Modify: `autodrive_console/web/deployment.js:460-570`
- Modify: `autodrive_console/web/deployment.html`
- Modify: `autodrive_console/web/deployment.css`
- Test: `frontend/test/deployment-workflow.test.mjs`

**Interfaces:**
- Consumes: `deriveDeploymentEditImpact()`, `viewedDeploymentStage`, current server-derived workflow, and existing stage save handlers.
- Produces: read-only review markup, explicit edit-impact dialog, local `editingDeploymentStage`, and focus-safe cancel/confirm behavior.

- [ ] **Step 1: Add failing review-safety tests**

```js
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
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
pixi run node --test --test-name-pattern="review is read-only|does not send a rollback" frontend/test/deployment-workflow.test.mjs
```

Expected: FAIL because completed-stage review still points at editable controls.

- [ ] **Step 3: Render completed facts as a read-only review**

When `task.readOnly` is true, render a summary with no form inputs and two secondary actions only: `return-current` and `request-stage-edit`. The latter opens the protected dialog; it is not a save action.

```js
export function completedStageReviewMarkup(task, facts, esc = String) {
  return `<section class="deployment-review-readonly" aria-labelledby="deploymentTaskTitle">
    <div><span class="deployment-review-state">已完成</span><h2 id="deploymentTaskTitle" tabindex="-1">${esc(task.title)}</h2><p>以下内容默认只读，回看不会改变当前流程进度。</p></div>
    <dl>${facts.map(({ label, value }) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl>
    <div class="deployment-review-actions"><button type="button" data-task-action="return-current">返回当前任务</button><button type="button" data-task-action="request-stage-edit">修改此步骤</button></div>
  </section>`;
}
```

Facts must come from the already loaded project/workflow; do not issue a review mutation request.

- [ ] **Step 4: Implement the edit-impact confirmation layer**

`openDeploymentEditImpact(stageId)` stores `pendingEditStage`, renders exact impact items from `deriveDeploymentEditImpact()`, removes `deployment-hidden`, traps focus inside the dialog, and focuses Cancel. Copy must distinguish `reconfirm`, `invalid`, and `locked`.

On cancel: hide dialog, clear `pendingEditStage`, and return focus to “修改此步骤”.

On confirm:

```js
function confirmDeploymentStageEdit() {
  editingDeploymentStage = pendingEditStage;
  viewedDeploymentStage = pendingEditStage;
  pendingEditStage = null;
  closeDeploymentEditImpact();
  renderDeploymentGuide();
  renderDeploymentTaskConsole();
  focusGuideTarget(guideTargetForStep(editingDeploymentStage));
}
```

This function sends no request. Existing save handlers remain the only mutation points; after a save response, clear `editingDeploymentStage`, refresh facts, and rederive workflow. On save failure, keep the original authoritative stage and show the error.

- [ ] **Step 5: Add keyboard/focus behavior**

Add an `Escape` handler active only while the dialog is open, Tab/Shift+Tab focus containment, and focus restoration. Do not allow the stage rail behind the dialog to receive focus while `aria-modal="true"` is active.

- [ ] **Step 6: Run the deployment workflow tests**

Run:

```bash
pixi run node --test frontend/test/deployment-workflow.test.mjs
```

Expected: PASS.

- [ ] **Step 7: Commit safe completed-stage editing**

```bash
git add autodrive_console/web/deployment/task-console.js autodrive_console/web/deployment.js autodrive_console/web/deployment.html autodrive_console/web/deployment.css frontend/test/deployment-workflow.test.mjs
git commit -m "feat: protect completed deployment stage edits"
```

---

### Task 6: Harden themes, responsive behavior, accessibility, and full verification

**Files:**
- Modify: `autodrive_console/web/deployment.css`
- Modify: `autodrive_console/web/deployment.js`
- Modify: `frontend/test/deployment-workflow.test.mjs`
- Reference only: `shared/contracts/deployment.md`

**Interfaces:**
- Consumes: completed task console from Tasks 1-5.
- Produces: release-ready PC Web behavior with no shared-contract changes.

- [ ] **Step 1: Add failing hardening assertions**

```js
test("single-task console has explicit responsive and light-theme rules", () => {
  assert.match(deploymentStyles, /\.deployment-task-console\s*\{[^}]*max-width:\s*1480px/s);
  assert.match(deploymentStyles, /@media\s*\(max-width:\s*1040px\)[^]*\.deployment-task-console/s);
  assert.match(deploymentStyles, /@media\s*\(max-width:\s*760px\)[^]*\.deployment-guide-steps/s);
  assert.match(deploymentStyles, /body\.theme-light[^]*\.deployment-task-card/s);
  assert.match(deploymentStyles, /\.deployment-edit-impact[^]*:focus-visible/s);
});

test("task changes announce status and move focus to the task heading", () => {
  assert.match(deploymentPage, /id="deploymentTaskReceipt"[^]*role="status"/s);
  assert.match(deploymentSource, /focusCurrentTaskHeading/);
  assert.match(deploymentSource, /prefers-reduced-motion|matchMedia/);
});
```

- [ ] **Step 2: Run the hardening tests and verify any missing rules fail**

Run:

```bash
pixi run node --test --test-name-pattern="responsive and light-theme|announce status" frontend/test/deployment-workflow.test.mjs
```

Expected: FAIL for any missing breakpoint, theme, focus, or announcement contract.

- [ ] **Step 3: Complete layout and theme hardening in one CSS pass**

Ensure:

```css
.deployment-task-console { width: min(100%, 1480px); max-width: 1480px; }
.deployment-task-card p { max-width: 70ch; font-size: 14px; line-height: 1.6; overflow-wrap: anywhere; }
.deployment-task-primary { min-height: 44px; }
.deployment-task-progress { width: 100%; min-width: 0; }
body.theme-light .deployment-task-card,
body.theme-light .deployment-task-workspace,
body.theme-light .deployment-task-progress { color: var(--ink); background: #fff; border-color: var(--line); }
@media (prefers-reduced-motion: reduce) {
  .deployment-task-receipt,
  .deployment-edit-impact { transition: none !important; }
}
```

Remove obsolete three-column rail rules instead of retaining contradictory selectors. Verify long text wraps, native controls have readable light-theme colors, and task inputs are at least `16px` below `760px`.

- [ ] **Step 4: Run the complete Web test suite**

Run:

```bash
pixi run frontend-check
./scripts/test-web.sh
```

Expected: PASS with no existing deployment, frontend, or contract consumer regression.

- [ ] **Step 5: Start or reuse the Vue preview and run browser QA**

Keep the user's approved visual companion running separately. Start the actual app preview only if it is not already available:

```bash
./run_vue_preview.sh
```

Use agent-browser against the actual deployment route at these viewports:

```text
1366 × 768
1600 × 900
1920 × 1080
```

For each viewport verify:

1. Exactly one task card and one primary action are visible.
2. Progress rail is read-only and does not create a second editing path.
3. Map source → file validation → name/check → stage binding proceeds in order.
4. A failed upload remains on the same task and preserves selected metadata.
5. A successful save shows a receipt and moves focus to the next task.
6. Completed-stage review contains no editable fields before confirmation.
7. The edit-impact dialog cancels with Escape and restores focus.
8. Light and dark themes retain readable controls and status colors.
9. Browser 200% zoom produces no horizontal page overflow; the stage rail may scroll within itself.

- [ ] **Step 6: Inspect console errors and regression boundaries**

Use agent-browser to confirm no uncaught errors during the above flows. Re-open `shared/contracts/deployment.md` and verify the implementation added no endpoint, request field, response field, runtime path, ROS call, or Mobile consumer.

- [ ] **Step 7: Commit the hardening pass**

```bash
git add autodrive_console/web/deployment.css autodrive_console/web/deployment.js frontend/test/deployment-workflow.test.mjs
git commit -m "fix: harden deployment task console"
```

- [ ] **Step 8: Final evidence check**

Run:

```bash
git status --short
git log -6 --oneline
```

Expected: only pre-existing unrelated worktree changes remain; the six task commits are visible and no build output, `.vite/`, logs, screenshots, or `.superpowers/` artifacts were committed.
