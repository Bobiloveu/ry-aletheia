import {
  COMPONENT_SPECS,
  componentName,
  protocolOptions,
  protocolTitle,
} from "./deployment/component-specs.js";
import {
  canvasPointToMap,
  componentDimensions as getComponentDimensions,
  componentLocalPoint as getComponentLocalPoint,
  isComponentHit,
  isPointOnMap,
  isResizeHandleHit,
  isRotateHandleHit,
  mapPointToCanvas,
  zoomAt,
} from "./deployment/canvas-geometry.js";
import { drawDeploymentCanvas } from "./deployment/canvas-renderer.js";
import { createCanvasDrawScheduler } from "./deployment/canvas-scheduler.js";
import { createEraseFrameMask } from "./deployment/erase-frame-mask.js";
import { eraseEditsForRender } from "./deployment/erase-preview.js";
import {
  executionNodeLabel,
  executionNodeRoleLabel,
  executionNodeSpeedLabel,
} from "./deployment/execution-chain-view.js";
import { isDirectionalTaskAnchor, startDirectionGeometry } from "./deployment/start-direction.js";
import { bindingOwnedByTopology } from "./deployment/localization-topology.js";
import {
  moveWallEndpoint,
  moveWallVertex,
  translateWall,
  wallHitTest,
  wallsForDisplay,
} from "./deployment/virtual-walls.js";
import {
  deriveDeploymentEditImpact,
  deriveDeploymentTask,
  deriveDeploymentWorkflow,
  deriveLocalizationGuidance,
  deriveMapImportGuidance,
  isDeploymentStageUnlocked,
  nextMapImportDraft,
} from "./deployment/workflow.js";
import { synchronizeMapSourceChoice } from "./deployment/map-source-choice.js";
import {
  createTaskActionGate,
  taskConsoleMarkup,
} from "./deployment/task-console.js";
import {
  clampDeploymentStage,
  clearDeploymentSession,
  readDeploymentSession,
  shouldRestoreNewProjectDraft,
  writeDeploymentSession,
} from "./deployment/session-state.js";
import {
  hasPersistedPreview,
  isActivePreviewRequest,
  previewMatchesProject,
  projectWithPreviewHash,
} from "./deployment/task-compiler-preview.js";
import {
  createFlowNode,
  flowForProject,
  reorderFlow,
  renderDeploymentFlow,
  validateFlow,
} from "./deployment/flow-editor.js";
import { deleteDeploymentAnnotation } from "./deployment/annotation-delete.js";
import { requestJson } from "./platform/http.js";

const $ = (id) => document.getElementById(id);
const esc = (value) => {
  const node = document.createElement("span");
  node.textContent = value ?? "";
  return node.innerHTML;
};
let selectedProject = null;
let componentSpeedDefaults = {};
let deploymentFlow = [];
let activeMap = null;
let mapImage = null;
let mapNeedsFit = false;
let activeTool = "pan";
let selectedComponent = null;
let selectedWaypoint = null;
let selectedVirtualWall = null;
let virtualWallDraft = null;
let virtualWallDrag = null;
let virtualWallPlacementPending = false;
let mappingSession = null;
let mappingRuntime = null;
let mappingTemplate = null;
let liveMapImage = null;
let lastLivePreviewRevision = 0;
let mappingPollTimer = null;
let eraserDiameterM = 0.8;
let eraserShape = "circle";
let eraserStroke = null;
let pendingEraserStroke = null;
let eraserCommitPending = false;
let polygonEraseDraft = [];
let eraserHoverPoint = null;
let spacePanActive = false;
let topology = null;
let routeDraft = [];
let taskCompilerPreview = null;
let taskCompilerProjectId = null;
let deploymentWorkflow = null;
let deploymentTask = null;
let deploymentTaskPending = null;
let deploymentTaskDraft = {
  mapSource: null,
  fileSummary: null,
  mapLabel: "",
  latestCreatedMapId: null,
  receipt: null,
};
let viewedDeploymentStage = null;
let editingDeploymentStage = null;
let creatingAnotherProject = false;
let pendingEditStage = null;
let deploymentEditReturnFocus = null;
let annotationDeleteInFlight = false;
const taskActionGate = createTaskActionGate();
let elevatorLandingDraft = null;
let localizationBindingDraft = null;
let localizationRouteDraft = null;
const mapView = { scale: 40, x: 0, y: 0 };
const canvas = $("mapCanvas");
const context = canvas.getContext("2d");
const eraseFrameMaskCanvas = $("mapEraseFrameMask");
const eraseFrameMaskContext = eraseFrameMaskCanvas.getContext("2d");
const eraseFrameMask = createEraseFrameMask({
  capture: () => {
    eraseFrameMaskCanvas.width = canvas.width;
    eraseFrameMaskCanvas.height = canvas.height;
    eraseFrameMaskContext.clearRect(
      0,
      0,
      eraseFrameMaskCanvas.width,
      eraseFrameMaskCanvas.height,
    );
    eraseFrameMaskContext.drawImage(canvas, 0, 0);
  },
  show: () => { eraseFrameMaskCanvas.hidden = false; },
  hide: () => { eraseFrameMaskCanvas.hidden = true; },
});
const mapWorkspace = $("mapWorkspace");
const taskPreviewOverlay = $("taskPreviewOverlay");
const taskPreviewMapMount = $("taskPreviewMapMount");
let taskPreviewOpen = false;
let taskPreviewOriginMapId = null;
let taskPreviewWorkspaceParent = null;
let taskPreviewWorkspaceBefore = null;
let canvasResizeFrame = null;
let scheduleMapDraw = null;
let pendingComponentSizeReadout = null;
let pendingComponentYaw = null;
let pendingWaypointYaw = null;
document.body.classList.add("deployment-no-project", "deployment-no-map");
const physicalElevators = () =>
  Array.isArray(selectedProject?.physical_elevators)
    ? selectedProject.physical_elevators
    : [];
const physicalElevatorFor = (component) =>
  physicalElevators().find(
    (item) => item.id === component?.attributes?.physical_elevator_id,
  );
const mapInstanceFor = (mapId) =>
  (selectedProject?.map_instances || []).find(
    (item) => item.map_asset_id === mapId,
  );
const taskTransitionRole = (mapId) => {
  const flowById = new Map(flowForProject(selectedProject).map((item) => [item.id, item.type]));
  const stage = (topology?.stages || []).find((item) => item.map_asset_id === mapId)?.stage
    || (selectedProject?.map_stage_assignments || []).find((item) => item.map_asset_id === mapId)?.stage;
  const type = flowById.get(stage) || stage;
  if (type === "lobby" || type === "target_floor") return type;
  const instanceRole = mapInstanceFor(mapId)?.role;
  return instanceRole === "lobby" ? "lobby" : ["typical_floor", "floor_override"].includes(instanceRole) ? "target_floor" : null;
};
const isTargetFloorMap = (mapId) => taskTransitionRole(mapId) === "target_floor";
const request = (url, options) => requestJson(url, options);
function note(id, text, error = false) {
  const target = $(id);
  target.textContent = text;
  target.style.color = error ? "#ff899a" : "#35d69c";
}
function persistDeploymentSession() {
  if (!selectedProject) return;
  writeDeploymentSession(localStorage, {
    projectId: selectedProject.id,
    mapId: activeMap?.id || null,
    viewedDeploymentStage: viewedDeploymentStage || deploymentWorkflow?.current?.id || null,
    creatingAnotherProject,
    deploymentTaskDraft: {
      mapSource: deploymentTaskDraft.mapSource,
      mapLabel: deploymentTaskDraft.mapLabel,
    },
  });
}
function taskCompilerMessage(text, error = false) {
  const target = $("taskCompilerStatus");
  target.textContent = text;
  target.classList.toggle("error", error);
}
function compilerRecovery(error) {
  return `${error}。请检查小区名称、地图阶段、组件属性和机器人地图来源后重试。`;
}
function renderExecutionChainTrace(executionChain) {
  if (!executionChain || typeof executionChain !== "object") return "";
  const maps = [
    ["lobby", "电梯大厅"],
    ["target", "用户楼层"],
  ];
  const renderLeg = (title, nodes) => {
    if (!Array.isArray(nodes) || !nodes.length) {
      return `<div class="compiler-execution-empty">${esc(title)}：没有中间执行节点</div>`;
    }
    return `<section class="compiler-execution-leg"><b>${esc(title)}</b><ol>${nodes.map((node, index) => {
      const source = executionNodeLabel(node, selectedProject || {});
      const details = [
        node?.role ? `节点：${executionNodeRoleLabel(node.role)}` : "",
        node?.incoming_speed_mode ? `入站速度：${executionNodeSpeedLabel(node.incoming_speed_mode)}` : "",
        node?.behavior_tree ? `行为树：${node.behavior_tree}` : "",
        node?.controller_device_id ? `设备号：${node.controller_device_id}` : "",
      ].filter(Boolean).join(" · ");
      return `<li><span>${index + 1}</span><div><strong>${esc(source)}</strong><small>${esc(details || "纯导航节点")}</small></div></li>`;
    }).join("")}</ol></section>`;
  };
  const sections = maps.map(([key, label]) => {
    const map = executionChain[key];
    if (!map || typeof map !== "object") return "";
    return `<section class="compiler-execution-map"><header><b>${esc(label)}</b><small>系统自动关联</small></header>${renderLeg("去程", map.outbound)}${renderLeg("返程", map.return)}</section>`;
  }).filter(Boolean);
  if (!sections.length) return "";
  return `<section class="compiler-execution-trace"><header><b>组件执行链核验</b><small>以下为服务端实际编译的去返程节点；速度作用于到达该节点前的一段路径。</small></header>${sections.join("")}</section>`;
}
function renderTaskCompilerPreview(preview) {
  const holder = $("taskCompilerPreview");
  const download = $("downloadTaskCompilerBundle");
  download.disabled = true;
  if (!selectedProject) {
    holder.className = "compiler-empty";
    holder.textContent = "先打开部署项目，再保存任务信息。";
    renderDeploymentGuide();
    return;
  }
  if (!preview) {
    holder.className = "compiler-empty";
    holder.textContent = "保存后可生成只读预览；由服务端检查当前地图、组件与来源文件。";
    renderDeploymentGuide();
    return;
  }
  const errors = Array.isArray(preview.errors) ? preview.errors : [];
  const warnings = Array.isArray(preview.warnings) ? preview.warnings : [];
  if (preview.status !== "ready" || errors.length) {
    holder.className = "compiler-blocking-errors";
    holder.innerHTML = `<b>暂不能生成实验包</b><ul>${errors.map((item) => `<li>${esc(item)}</li>`).join("") || `<li>${esc(preview.status || "服务端未确认预览状态")}</li>`}</ul><p>${esc(preview.recovery || "请补齐上述信息后重新生成；不会写入机器人运行目录。")}</p>`;
    taskCompilerMessage("预览未通过服务端校验。", true);
    renderDeploymentGuide();
    return;
  }
  const subtasks = Array.isArray(preview.task_json?.subtasks)
    ? preview.task_json.subtasks
    : [];
  const routeFamilies = Array.isArray(preview.route_families)
    ? preview.route_families
    : Array.isArray(preview.task_json?.route_families)
      ? preview.task_json.route_families
    : [];
  const steps = subtasks.map((subtask, index) => {
    const waypoints = Array.isArray(subtask.waypoints) ? subtask.waypoints : [];
    return `<li class="compiler-step"><span>${index + 1}</span><div><b>${esc(subtask.subtask_name || `子任务 ${index + 1}`)}</b><small>${waypoints.length} 个路点 · ${esc(subtask.map_url || "地图来源由服务端确认")}</small></div></li>`;
  });
  holder.className = "compiler-preview-ready";
  holder.innerHTML = [
    `<p class="compiler-ready-label">服务端已生成实验预览</p>`,
    `<p class="compiler-output-note">实验产物，尚未安装到机器人</p>`,
    steps.length
      ? `<ol class="compiler-timeline">${steps.join("")}</ol>`
      : routeFamilies.length
        ? `<ol class="compiler-timeline">${routeFamilies.map((family, index) => {
            const targets = Array.isArray(family.targets) ? family.targets : [];
            const destinations = targets.map((target) => {
              const floor = target.button_floor ?? target.physical_floor ?? target.floor;
              const door = target.door;
              return floor !== undefined && door ? `${floor} 楼 ${door} 户` : "尚未标记";
            }).join("、") || "尚未标记";
            const sharedSegments = Array.isArray(family.required_outputs)
              ? family.required_outputs.filter((item) => item !== "floor").length
              : 1;
            return `<li class="compiler-step"><span>${index + 1}</span><div><b>${esc(`${family.building} 栋 ${family.unit} 单元`)}</b><small>${sharedSegments} 段公共路线 + ${targets.length} 个用户楼层去返段（${esc(destinations)}）</small></div></li>`;
          }).join("")}</ol>`
      : '<div class="compiler-empty">预览没有返回可展示的子任务。</div>',
    renderExecutionChainTrace(preview.manifest?.execution_chain),
    warnings.length
      ? `<ul class="compiler-warning-list">${warnings.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`
      : "",
    `<p class="compiler-artifact-meta">${Array.isArray(preview.artifacts) ? preview.artifacts.length : 0} 个实验文件</p>`,
  ].join("");
  download.disabled = false;
  taskCompilerMessage("服务端校验完成；可下载到当前浏览器所在电脑。");
  renderDeploymentGuide();
}
function previewMapAssets() {
  return Array.isArray(selectedProject?.map_assets) ? selectedProject.map_assets : [];
}
function renderTaskPreviewOverlay(preview) {
  if (!taskPreviewOverlay || !preview) return;
  const switcher = $("taskPreviewMapSwitcher");
  const maps = previewMapAssets();
  switcher.innerHTML = maps.map((map) => {
    const isActive = activeMap?.id === map.id;
    return `<button class="task-preview-map-tab${isActive ? " is-active" : ""}" data-task-preview-map="${esc(map.id)}" role="tab" aria-selected="${isActive}">${esc(map.label || map.id)}</button>`;
  }).join("");
  const subtasks = Array.isArray(preview.task_json?.subtasks) ? preview.task_json.subtasks : [];
  const routeFamilies = Array.isArray(preview.route_families)
    ? preview.route_families
    : Array.isArray(preview.task_json?.route_families) ? preview.task_json.route_families : [];
  $("taskPreviewStepCount").textContent = subtasks.length
    ? `${subtasks.length} 个子任务`
    : `${routeFamilies.reduce((count, family) => count + (family.targets?.length || 0), 0)} 个用户楼层任务`;
  $("taskPreviewTaskList").innerHTML = (subtasks.length ? subtasks.map((subtask, index) => {
    const points = Array.isArray(subtask.waypoints) ? subtask.waypoints : [];
    return `<li class="task-preview-task-item${index === 0 ? " is-active" : ""}"><span class="task-preview-task-index">${index + 1}</span><div><strong>${esc(subtask.subtask_name || `子任务 ${index + 1}`)}</strong><small>${points.length} 个路点</small></div></li>`;
  }).join("") : routeFamilies.map((family, index) => {
    const targets = Array.isArray(family.targets) ? family.targets : [];
    return `<li class="task-preview-task-item${index === 0 ? " is-active" : ""}"><span class="task-preview-task-index">${index + 1}</span><div><strong>${esc(`${family.building} 栋 ${family.unit} 单元`)}</strong><small>已拆分 ${targets.length} 个楼层去返任务</small></div></li>`;
  }).join("")) || '<li class="task-preview-task-empty">预览没有返回任务步骤。</li>';
  $("taskPreviewActiveMap").textContent = activeMap?.label || "当前地图";
  $("taskPreviewOverlayMeta").textContent = `${selectedProject?.name || "部署项目"} · 只读地图核验，尚未写入机器人`;
}
function openTaskPreview(preview) {
  if (!preview || preview.status !== "ready" || !selectedProject || !taskPreviewOverlay) return;
  if (taskPreviewOpen) {
    renderTaskPreviewOverlay(preview);
    return;
  }
  taskPreviewOriginMapId = activeMap?.id || null;
  taskPreviewWorkspaceParent = mapWorkspace.parentElement;
  taskPreviewWorkspaceBefore = mapWorkspace.nextSibling;
  const map = activeMap || previewMapAssets()[0];
  taskPreviewOpen = true;
  activeTool = "pan";
  closeComponentPopover();
  closeWaypointPopover();
  taskPreviewOverlay.classList.remove("deployment-hidden");
  taskPreviewOverlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("task-preview-open");
  document.querySelector("main")?.setAttribute("inert", "");
  document.querySelector("aside")?.setAttribute("inert", "");
  taskPreviewMapMount.append(mapWorkspace);
  if (map && activeMap?.id !== map.id) selectMap(map, { persist: false });
  renderTaskPreviewOverlay(preview);
  requestAnimationFrame(() => {
    scheduleCanvasResize();
    fitMap();
  });
  $("closeTaskPreview").focus();
}
function closeTaskPreview() {
  if (!taskPreviewOpen) return;
  taskPreviewOpen = false;
  document.body.classList.remove("task-preview-open");
  taskPreviewOverlay.classList.add("deployment-hidden");
  taskPreviewOverlay.setAttribute("aria-hidden", "true");
  document.querySelector("main")?.removeAttribute("inert");
  document.querySelector("aside")?.removeAttribute("inert");
  if (taskPreviewWorkspaceParent) {
    if (taskPreviewWorkspaceBefore?.parentNode === taskPreviewWorkspaceParent) {
      taskPreviewWorkspaceParent.insertBefore(mapWorkspace, taskPreviewWorkspaceBefore);
    } else {
      taskPreviewWorkspaceParent.append(mapWorkspace);
    }
  }
  const origin = previewMapAssets().find((map) => map.id === taskPreviewOriginMapId);
  taskPreviewMapMount.replaceChildren();
  if (origin && activeMap?.id !== origin.id) selectMap(origin, { persist: false });
  taskPreviewOriginMapId = null;
  taskPreviewWorkspaceParent = null;
  taskPreviewWorkspaceBefore = null;
  requestAnimationFrame(() => {
    scheduleCanvasResize();
    drawMap();
  });
  $("generateTaskCompilerPreview")?.focus();
}
function renderTaskCompilerCompletionAction() {
  const completedPreview = taskCompilerPreview?.status === "ready";
  $("startAnotherDeployment").classList.toggle("deployment-hidden", !completedPreview);
  $("startAnotherDeployment").disabled = !completedPreview;
}
function renderTaskCompilerState(project) {
  const compiler = project?.task_compiler || {};
  const identity = compiler.identity || {};
  const community = identity.community || "";
  $("taskCompilerCommunity").value = community;
  const localizationTemplate = project?.localization_template;
  const localizationTemplateMessage = $("localizationTemplateMessage");
  localizationTemplateMessage.classList.remove("error");
  localizationTemplateMessage.textContent = localizationTemplate
    ? `当前使用：${localizationTemplate.name || "localization-template.yaml"}。仅在现场需要替换定位配置时才需重新选择文件。`
    : "当前沿用项目默认模板；仅在现场需要替换定位配置时才选择文件。";
  $("saveTaskCompilerConfig").disabled = !project;
  $("generateTaskCompilerPreview").disabled = !project || !community;
  const persistedPreviewHash = identity.last_preview_input_sha256 || null;
  if (
    taskCompilerProjectId !== project?.id ||
    (taskCompilerPreview && taskCompilerPreview.input_sha256 !== persistedPreviewHash)
  ) {
    taskCompilerPreview = null;
    taskCompilerProjectId = project?.id || null;
  }
  renderTaskCompilerCompletionAction();
  renderTaskCompilerPreview(taskCompilerPreview);
  renderDeploymentGuide();
  if (project && !taskCompilerPreview) {
    taskCompilerMessage(
      community
        ? "任务信息已保存；可生成实验预览。"
        : "填写并保存小区名称后，才可请求服务端预览。",
    );
  }
}
async function restoreTaskCompilerPreview(projectId) {
  const project = selectedProject;
  if (!project || project.id !== projectId || !hasPersistedPreview(project)) return;
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(projectId)}/task-compiler/preview`,
    );
    if (selectedProject?.id !== projectId || data.preview?.status !== "ready") return;
    selectedProject = projectWithPreviewHash(selectedProject, data.preview);
    if (!previewMatchesProject(selectedProject, data.preview)) return;
    taskCompilerPreview = data.preview;
    taskCompilerProjectId = projectId;
    renderTaskCompilerState(selectedProject);
  } catch (error) {
    taskCompilerMessage("已保存的实验预览暂时无法恢复；可重新生成预览后继续。", true);
  }
}
async function saveTaskCompilerConfig() {
  if (!selectedProject) return;
  const button = $("saveTaskCompilerConfig");
  button.disabled = true;
  taskCompilerMessage("正在保存任务信息…");
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/task-compiler/config`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ community: $("taskCompilerCommunity").value }),
      },
    );
    selectedProject = {
      ...selectedProject,
      task_compiler: data.task_compiler,
    };
    taskCompilerPreview = null;
    taskCompilerProjectId = selectedProject.id;
    renderTaskCompilerState(selectedProject);
    taskCompilerMessage("任务信息已保存；现在可生成实验预览。");
    completeDeploymentTask("任务信息已保存；下一步可以生成实验预览。");
  } catch (error) {
    taskCompilerMessage(compilerRecovery(error.message), true);
  } finally {
    button.disabled = !selectedProject;
  }
}
async function refreshTaskCompilerPreview() {
  if (!selectedProject) return;
  const projectId = selectedProject.id;
  const button = $("generateTaskCompilerPreview");
  button.disabled = true;
  taskCompilerMessage("正在由服务端校验组件并生成实验预览…");
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(projectId)}/task-compiler/preview`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      },
    );
    if (!isActivePreviewRequest(projectId, selectedProject)) return;
    taskCompilerPreview = data.preview;
    taskCompilerProjectId = projectId;
    selectedProject = projectWithPreviewHash(selectedProject, data.preview);
    renderTaskCompilerPreview(data.preview);
    renderTaskCompilerCompletionAction();
    renderDeploymentGuide();
    openTaskPreview(data.preview);
  } catch (error) {
    if (!isActivePreviewRequest(projectId, selectedProject)) return;
    taskCompilerPreview = {
      status: "blocked",
      errors: [error.message],
      recovery: "请检查小区名称、地图阶段、组件属性和机器人地图来源后重试。",
    };
    renderTaskCompilerPreview(taskCompilerPreview);
    renderTaskCompilerCompletionAction();
    renderDeploymentGuide();
  } finally {
    if (isActivePreviewRequest(projectId, selectedProject)) {
      button.disabled = !selectedProject.task_compiler?.identity?.community;
    }
  }
}
async function downloadTaskCompilerBundle() {
  if (!selectedProject || !taskCompilerPreview || $("downloadTaskCompilerBundle").disabled) return;
  const button = $("downloadTaskCompilerBundle");
  button.disabled = true;
  taskCompilerMessage("正在准备实验包下载…");
  try {
    const response = await fetch(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/task-compiler/download`,
      { cache: "no-store" },
    );
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || `实验包下载失败（HTTP ${response.status}）`);
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const disposition = response.headers.get("Content-Disposition") || "";
    const name = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
    link.href = objectUrl;
    link.download = name ? decodeURIComponent(name) : "task-compiler-experimental.zip";
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
    taskCompilerMessage("实验包已交给浏览器下载；保存位置由浏览器设置决定。");
  } catch (error) {
    taskCompilerMessage(compilerRecovery(error.message), true);
  } finally {
    button.disabled = taskCompilerPreview?.status !== "ready";
  }
}
function renderMapStages() {
  if (!selectedProject) return;
  const fallback = flowForProject(selectedProject).map((node) => node.label);
  const stages = topology?.stages?.length
    ? topology.stages
    : fallback.map((label, index) => ({ stage: String(index), label, status: "missing" }));
  const guidance = deriveMapImportGuidance(
    { stages },
    deploymentTask?.stageId === "maps" ? deploymentTask.targetStageId : null,
  );
  $("mapStageSummary").innerHTML = `<div id="mapImportTarget" class="map-stage-target ${guidance.state}" role="status">
      <strong>${esc(guidance.title)}</strong>
      <span>${esc(guidance.detail)}</span>
      ${guidance.position ? `<small>${esc(guidance.position)}</small>` : ""}
    </div>${stages
    .map((stage, index) => {
      const bound = Boolean(stage.map_asset_id);
      const count = Number(stage.map_count || 0);
      const summary = count > 1 ? `${stage.label} · 已配置 ${count} 张地图` : (stage.map_label || stage.label);
      return `<span class="${bound ? "done" : stage.status === "editing" ? "active" : ""}"><b>${bound ? "✓" : index + 1}</b>${esc(summary)}</span>`;
    })
    .join("")}`;
  $("mapFolderLabel").textContent = guidance.fileLabel;
  $("mapLabelText").textContent = guidance.nameLabel;
  $("mapLabel").placeholder = guidance.namePlaceholder;
  const current = stages.find((stage) => !stage.map_asset_id);
  $("importMessage").textContent = current
    ? `${guidance.title}（${guidance.position}）。可导入既有地图或使用下方车端建图。`
    : "地图阶段已齐全；继续标记实际组件，任务编译器会自动推导路点与切图依据。";
}

function renderDeploymentFlowEditor() {
  const editor = $("deploymentFlowEditor");
  const canvas = $("deploymentFlowCanvas");
  const save = $("saveDeploymentFlow");
  if (!editor || !canvas || !save) return;
  const validation = validateFlow(deploymentFlow);
  renderDeploymentFlow(canvas, deploymentFlow, {
    onAction(action, payload) {
      if (action === "remove" && Number.isInteger(payload)) deploymentFlow.splice(payload, 1);
      if (action === "reorder" && payload && Number.isInteger(payload.from) && Number.isInteger(payload.to)) {
        deploymentFlow = reorderFlow(deploymentFlow, payload.from, payload.to);
      }
      renderDeploymentFlowEditor();
    },
  });
  $("deploymentFlowMessage").textContent = validation.message;
  $("deploymentFlowMessage").classList.toggle("error", !validation.valid);
  save.disabled = !selectedProject || !validation.valid;
}

function renderTopology() {
  const holder = $("topologyPreview");
  const state = $("topologyState");
  const stageSelect = $("mapStageAssignment");
  const assignmentControls = $("stageAssignmentControls");
  if (!selectedProject || !topology) {
    if (state) {
      state.textContent = "等待项目";
      state.className = "badge muted";
    }
    if (holder) holder.innerHTML = '<div class="page-empty">等待地图阶段信息。</div>';
    assignmentControls.classList.add("deployment-hidden");
    return;
  }
  if (state) {
    state.textContent = topology.valid ? "拓扑完整" : "需完善";
    state.className = `badge ${topology.valid ? "success" : "muted"}`;
  }
  const stages = topology.stages || [];
  if (holder) {
    holder.innerHTML = stages
      .map((stage) => {
        const count = Number(stage.map_count || 0);
        const summary = count > 1 ? `已配置 ${count} 张地图` : (stage.map_label || "尚未绑定地图");
        return `<div class="topology-stage ${esc(stage.status)}"><span>${stage.status === "complete" ? "✓" : stage.status === "editing" ? "•" : "—"}</span><div><b>${esc(stage.label)}</b><small>${esc(summary)}</small></div></div>`;
      })
      .join("");
  }
  const mapStage = stages.find((stage) => stage.map_asset_id === activeMap?.id)?.stage;
  assignmentControls.classList.toggle("deployment-hidden", !activeMap || !stages.length);
  stageSelect.innerHTML = stages.map((stage) => `<option value="${esc(stage.stage)}" ${stage.stage === mapStage ? "selected" : ""}>${esc(stage.label)}</option>`).join("");
  $("stageAssignmentMessage").textContent = activeMap
    ? `${activeMap.label}${mapStage ? ` 当前属于：${stages.find((stage) => stage.stage === mapStage)?.label}` : " 尚未绑定地图阶段"}。`
    : "选择地图后可检查其阶段归属。";
}

const GUIDE_STATUS_LABELS = {
  complete: "已完成",
  current: "当前步骤",
  locked: "待前置",
};

function guideTargetForStep(stepId) {
  return {
    project: selectedProject ? "deploymentFlowEditor" : "projectName",
    maps: deploymentTask?.id === "maps.instance"
      ? "instanceControls"
      : topology?.stages?.length && topology.stages.every((stage) => stage.map_asset_id)
        ? "mapWorkspace"
        : topology?.stages?.length
          ? "mapStageAssignment"
          : "mapFolder",
    annotations: "mapWorkspace",
    localization: localizationBindings().length ? "localizationRouteList" : "openLocalizationBinding",
    export: taskCompilerPreview?.status === "ready" ? "downloadTaskCompilerBundle" : "generateTaskCompilerPreview",
  }[stepId];
}

function renderDeploymentGuide() {
  const guide = $("deploymentGuide");
  if (!guide) return;
  const workflowProject = creatingAnotherProject ? null : selectedProject;
  const workflowTopology = creatingAnotherProject ? null : topology;
  const workflowPreview = creatingAnotherProject ? null : taskCompilerPreview;
  deploymentWorkflow = deriveDeploymentWorkflow(workflowProject, workflowTopology, workflowPreview);
  const { steps, current, completed, total, percent } = deploymentWorkflow;
  if (viewedDeploymentStage && (topology || !(selectedProject?.map_assets || []).length)) {
    viewedDeploymentStage = clampDeploymentStage(current.id, viewedDeploymentStage);
  }
  const activeStage = viewedDeploymentStage || current.id;
  const activeStep = steps.find((item) => item.id === activeStage) || current;
  const reviewingCompletedStage = activeStep.id !== current.id;
  $("deploymentGuideProgressValue").textContent = `${percent}%`;
  $("deploymentGuideProgressMeta").textContent = `${completed} / ${total} 步已完成`;
  $("deploymentGuideSteps").innerHTML = steps
    .map(
      (item, index) => `<button class="deployment-guide-step ${item.id === activeStep.id ? (reviewingCompletedStage ? "reviewed" : "current") : item.status}" type="button" data-guide-step="${esc(item.id)}" aria-current="${item.id === activeStep.id ? "step" : "false"}"${item.status === "locked" ? " disabled" : ""}>
        <span class="deployment-guide-step-index">${index + 1}</span>
        <span class="deployment-guide-step-copy"><b>${esc(item.label)}</b><small>${esc(GUIDE_STATUS_LABELS[item.status])}</small></span>
      </button>`,
    )
    .join("");
  renderDeploymentTaskConsole();
  persistDeploymentSession();
}

function deploymentReviewFacts(stageId) {
  const maps = selectedProject?.map_assets || [];
  const stages = topology?.stages || [];
  return {
    project: [
      { label: "项目", value: selectedProject?.name || "尚未创建" },
      { label: "部署阶段", value: `${selectedProject?.deployment_flow?.length || 0} 个` },
    ],
    maps: [
      { label: "地图资产", value: `${maps.length} 张` },
      { label: "阶段绑定", value: `${stages.filter((item) => item.map_asset_id).length} / ${stages.length}` },
    ],
    annotations: [
      { label: "地图标记", value: `${selectedProject?.waypoints?.length || 0} 个` },
      { label: "现场组件", value: `${selectedProject?.components?.length || 0} 个` },
    ],
    localization: [
      { label: "定位绑定", value: `${selectedProject?.localization_bindings?.length || 0} 项` },
      { label: "定位路线", value: `${selectedProject?.localization_routes?.length || 0} 条` },
    ],
    export: [
      { label: "校验状态", value: taskCompilerPreview?.status === "ready" ? "已通过" : "待重新校验" },
      { label: "实验文件", value: `${taskCompilerPreview?.artifacts?.length || 0} 个` },
    ],
  }[stageId] || [];
}

function renderDeploymentTaskConsole() {
  if (!deploymentWorkflow) {
    // The first paint occurs while projects are still loading.  Apply the
    // default project task gate here as well, otherwise every later workflow
    // panel flashes at once and the field guide loses its one-step focus.
    applyDeploymentTaskGating();
    return;
  }
  const workflowProject = creatingAnotherProject ? null : selectedProject;
  const workflowTopology = creatingAnotherProject ? null : topology;
  deploymentTask = deriveDeploymentTask({
    workflow: deploymentWorkflow,
    project: workflowProject,
    topology: workflowTopology,
    mappingSession,
    draft: deploymentTaskDraft,
    viewedStage: viewedDeploymentStage,
    editingStage: editingDeploymentStage,
  });
  if (synchronizeTaskWorkspace()) return;
  if (editingDeploymentStage && deploymentTask.readOnly) {
    deploymentTask = {
      ...deploymentTask,
      id: `${editingDeploymentStage}.edit`,
      title: `修改${deploymentTask.title}`,
      detail: "编辑仅在现有保存按钮提交后生效；未保存离开不会改变项目事实。",
      completionCriterion: "保存必要修改，并返回当前任务重新确认后续阶段",
      primaryAction: { id: "return-current", label: "结束修改并返回", target: "deploymentTaskTitle" },
      readOnly: false,
    };
  }
  const markup = taskConsoleMarkup(
    deploymentTask,
    {
      pending: deploymentTaskPending === deploymentTask.id,
      receipt: deploymentTaskDraft.receipt,
      facts: deploymentReviewFacts(deploymentTask.stageId),
    },
    esc,
  );
  $("deploymentTaskSummary").innerHTML = markup.summaryHtml;
  $("deploymentTaskProgress").innerHTML = markup.progressHtml;
  $("deploymentTaskAfter").innerHTML = markup.afterHtml;
  $("deploymentTaskWorkspace").classList.toggle("deployment-hidden", deploymentTask.readOnly);
  applyDeploymentTaskGating();
  synchronizeMapSourceChoice(document, deploymentTaskDraft.mapSource);
  synchronizeTaskWorkspace();
}

function synchronizeTaskWorkspace() {
  const stageSelect = $("mapStageAssignment");
  if (!stageSelect) return false;
  if (!["maps.assign", "maps.instance"].includes(deploymentTask?.id)) {
    stageSelect.disabled = false;
    return false;
  }
  const targetMap = (selectedProject?.map_assets || []).find(
    (item) => item.id === deploymentTask.targetMapId,
  );
  if (targetMap && activeMap?.id !== targetMap.id) {
    selectMap(targetMap);
    return true;
  }
  if (deploymentTask.id === "maps.instance") {
    $("instanceRole").value = deploymentTask.instanceRole || "typical_floor";
    $("instanceMessage").textContent = `当前任务：为“${targetMap?.label || "当前地图"}”设置部署拓扑位置。请核对用途并填写实际楼栋、单元；物理楼层由稍后标记的电梯组件自动推导。`;
    return false;
  }
  if (deploymentTask.targetStageId) {
    stageSelect.value = deploymentTask.targetStageId;
    stageSelect.disabled = true;
    const stageLabel = (topology?.stages || []).find(
      (item) => item.stage === deploymentTask.targetStageId,
    )?.label || deploymentTask.targetStageId;
    $("stageAssignmentMessage").textContent = `${targetMap?.label || deploymentTask.targetMapId} 将绑定到“${stageLabel}”；该目标由当前任务锁定。`;
  }
  return false;
}

function applyDeploymentTaskGating() {
  const taskId = deploymentTask?.id || "project.createProject";
  const activeStage = deploymentTask?.stageId || "project";
  if (activeStage === "maps" && activeTool !== "pan") setTool("pan");
  document.body.dataset.deploymentStage = activeStage;
  document.body.dataset.deploymentTask = taskId;
  document.querySelectorAll("[data-deployment-task], [data-deployment-tasks]").forEach((panel) => {
    const requiredTasks = (panel.dataset.deploymentTasks || panel.dataset.deploymentTask || "")
      .split(/\s+/)
      .filter(Boolean);
    const visible = requiredTasks.includes(taskId) || requiredTasks.includes(`${activeStage}.*`);
    panel.classList.toggle("deployment-task-hidden", !visible);
    panel.classList.toggle("deployment-task-visible", visible);
    panel.setAttribute("aria-hidden", String(!visible));
  });
}

function focusGuideTarget(targetId) {
  const target = targetId ? $(targetId) : null;
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  if (typeof target.focus === "function") target.focus({ preventScroll: true });
}

function runDeploymentGuideAction(actionId) {
  if (actionId === "return-current") {
    viewedDeploymentStage = null;
    editingDeploymentStage = null;
    persistDeploymentSession();
    renderDeploymentGuide();
    focusCurrentTaskHeading();
    return;
  }
  const next = deploymentWorkflow?.next;
  if (!next || next.id !== actionId) return;
  viewedDeploymentStage = deploymentWorkflow.current.id;
  persistDeploymentSession();
  if (actionId === "annotate" && next.targetMapId) {
    const map = (selectedProject?.map_assets || []).find((item) => item.id === next.targetMapId);
    if (map) selectMap(map);
  }
  if (actionId === "editRoute") {
    const routeButton = $("openLocalizationRoute");
    if (routeButton && !routeButton.disabled) {
      routeButton.click();
      return;
    }
  }
  if (["preview", "export"].includes(actionId)) {
    const target = $(next.target);
    if (target && !target.disabled) {
      target.click();
      return;
    }
  }
  focusGuideTarget(next.target || guideTargetForStep(deploymentWorkflow.current.id));
}

function focusGuideStep(stepId) {
  if (!deploymentWorkflow || !isDeploymentStageUnlocked(deploymentWorkflow.current.id, stepId)) return;
  viewedDeploymentStage = stepId;
  editingDeploymentStage = null;
  persistDeploymentSession();
  renderDeploymentGuide();
  if (stepId === "annotations" && deploymentWorkflow?.next?.targetMapId) {
    const map = (selectedProject?.map_assets || []).find((item) => item.id === deploymentWorkflow.next.targetMapId);
    if (map) selectMap(map);
  }
  focusCurrentTaskHeading();
}

function focusCurrentTaskHeading() {
  requestAnimationFrame(() => {
    const heading = $("deploymentTaskTitle");
    if (!heading) return;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    heading.focus({ preventScroll: true });
    heading.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
  });
}

const EDIT_IMPACT_COPY = {
  reconfirm: "需要重新确认",
  invalid: "现有结果可能失效",
  locked: "完成前置确认前将保持锁定",
};

function openDeploymentEditImpact(stageId, returnFocus = document.activeElement) {
  if (!stageId || !deploymentWorkflow) return;
  pendingEditStage = stageId;
  deploymentEditReturnFocus = returnFocus;
  const impact = deriveDeploymentEditImpact(stageId, deploymentWorkflow.current.id);
  const dialog = $("deploymentEditImpactDialog");
  dialog.innerHTML = `<div class="deployment-edit-impact-card">
    <span class="deployment-review-state">受保护的修改</span>
    <h2 id="deploymentEditImpactTitle">修改此步骤会影响后续内容</h2>
    <p>这里只进入本地编辑模式，不会自动回滚或写入机器人。只有你随后明确保存的内容才会提交。</p>
    <ul>${impact.items.map((item) => `<li class="${esc(item.status)}"><b>${esc(item.label)}</b><span>${esc(EDIT_IMPACT_COPY[item.status])}</span></li>`).join("") || "<li><b>当前步骤</b><span>修改后请重新核对</span></li>"}</ul>
    <div class="deployment-edit-impact-actions">
      <button id="cancelDeploymentStageEdit" class="compact-action" type="button">取消</button>
      <button id="confirmDeploymentStageEdit" class="page-top-action" type="button">确认进入修改</button>
    </div>
  </div>`;
  dialog.classList.remove("deployment-hidden");
  document.body.classList.add("deployment-edit-impact-open");
  requestAnimationFrame(() => $("cancelDeploymentStageEdit")?.focus());
}

function closeDeploymentEditImpact({ restoreFocus = true } = {}) {
  const dialog = $("deploymentEditImpactDialog");
  dialog.classList.add("deployment-hidden");
  dialog.innerHTML = "";
  document.body.classList.remove("deployment-edit-impact-open");
  pendingEditStage = null;
  if (restoreFocus) {
    const target = deploymentEditReturnFocus?.isConnected && deploymentEditReturnFocus !== document.body
      ? deploymentEditReturnFocus
      : document.querySelector('[data-task-action="request-stage-edit"]');
    requestAnimationFrame(() => target?.focus());
  }
  deploymentEditReturnFocus = null;
}

function confirmDeploymentStageEdit() {
  if (!pendingEditStage) return;
  editingDeploymentStage = pendingEditStage;
  viewedDeploymentStage = pendingEditStage;
  const stageId = pendingEditStage;
  closeDeploymentEditImpact({ restoreFocus: false });
  persistDeploymentSession();
  renderDeploymentGuide();
  focusGuideTarget(guideTargetForStep(stageId));
}

function completeDeploymentEdit(message) {
  if (!editingDeploymentStage) return false;
  const completedTaskId = deploymentTask?.id || editingDeploymentStage;
  editingDeploymentStage = null;
  viewedDeploymentStage = null;
  deploymentTaskDraft.receipt = { taskId: completedTaskId, message };
  persistDeploymentSession();
  renderDeploymentGuide();
  focusCurrentTaskHeading();
  return true;
}

function isMapAnnotationWorkspaceActive() {
  return editingDeploymentStage === "annotations" ||
    viewedDeploymentStage === "annotations" ||
    deploymentTask?.stageId === "annotations" ||
    deploymentWorkflow?.current?.id === "annotations";
}

function keepMapAnnotationOpen(message, { force = false } = {}) {
  const isAnnotating = force || isMapAnnotationWorkspaceActive();
  if (!isAnnotating) return false;
  editingDeploymentStage = "annotations";
  viewedDeploymentStage = "annotations";
  deploymentTaskDraft.receipt = { taskId: "annotations.edit", message };
  persistDeploymentSession();
  renderDeploymentGuide();
  return true;
}

function completeDeploymentTask(message) {
  if (completeDeploymentEdit(message)) return;
  viewedDeploymentStage = null;
  deploymentTaskDraft.receipt = {
    taskId: deploymentTask?.id || deploymentWorkflow?.current?.id || "deployment",
    message,
  };
  persistDeploymentSession();
  renderDeploymentGuide();
  focusCurrentTaskHeading();
}

async function refreshTopology() {
  if (!selectedProject) return;
  try {
    const data = await request(`/api/deployments/${encodeURIComponent(selectedProject.id)}/topology`);
    topology = data.topology;
    renderMapStages();
    renderTopology();
    renderDeploymentGuide();
    drawMap();
  } catch (error) {
    topology = null;
    renderTopology();
    renderDeploymentGuide();
    note("stageAssignmentMessage", error.message, true);
  }
}
function renderMappingStatus() {
  const session = mappingSession;
  const available = mappingRuntime?.available;
  $("mappingRuntimeBadge").textContent = available ? "Lightning 就绪" : "运行时待升级";
  $("mappingRuntimeBadge").className = `badge ${available ? "success" : "muted"}`;
  const hasProject = Boolean(selectedProject);
  const hasActiveSession = Boolean(session && ["prepared", "running", "stopping"].includes(session.state));
  const belongsToCurrentProject = !session || !hasProject || session.project_id === selectedProject.id;
  $("mappingControls").classList.toggle("deployment-hidden", !hasProject);
  $("prepareMapping").disabled = !hasProject || !mappingTemplate?.id || hasActiveSession;
  $("openMappingWorkbench").disabled = !session || !belongsToCurrentProject || !["prepared", "running"].includes(session.state) || !available;
  $("discardMapping").disabled = !session || ["running", "stopping"].includes(session.state);
  if (!hasProject) return;
  if (session && !belongsToCurrentProject) {
    $("mappingMessage").textContent = `项目“${session.project_id}”有一个${session.state === "prepared" ? "已准备" : session.state}的建图会话“${session.label}”。请继续该会话，或放弃后再为当前项目准备。`;
    return;
  }
  if (session?.state === "running") {
    if (session.preview?.state === "waiting") {
      $("mappingMessage").textContent = "SLAM 已启动，正在等待 Lightning 的第一帧栅格。请确认建图 YAML 已设置 with_g2p5: true，并检查雷达数据是否正常进入车端 ROS2。";
    } else if (session.preview?.state === "streaming") {
      $("mappingMessage").textContent = `正在建图：实时栅格已更新 ${session.preview?.revision || 0} 次。请在建图工作台中观察地图并安全移动小车。`;
    } else {
      $("mappingMessage").textContent = "SLAM 正在初始化实时栅格预览。";
    }
  } else if (session?.state === "prepared") {
    $("mappingMessage").textContent = available ? "会话配置已就绪；进入建图工作台后确认车辆周边安全，再开始实时建图。" : (mappingRuntime?.reason || "在线建图运行时尚不可用。");
  } else if (session?.error) {
    $("mappingMessage").textContent = session.error;
  } else {
    $("mappingMessage").textContent = mappingRuntime?.reason || "选择模板后准备车端建图会话。";
  }
}
async function refreshMappingStatus() {
  try {
    const data = await request("/api/mapping");
    mappingRuntime = data;
    mappingSession = data.session || null;
    renderMappingStatus();
    renderDeploymentTaskConsole();
    updateLivePreview();
    if (mappingSession?.state === "running" && !mappingPollTimer) {
      mappingPollTimer = window.setInterval(refreshMappingStatus, 900);
    }
    if (mappingSession?.state !== "running" && mappingPollTimer) {
      window.clearInterval(mappingPollTimer);
      mappingPollTimer = null;
    }
  } catch (error) {
    $("mappingRuntimeBadge").textContent = "无法检查";
    $("mappingMessage").textContent = error.message;
  }
}
function updateLivePreview() {
  const preview = mappingSession?.preview;
  if (!preview?.revision || preview.revision === lastLivePreviewRevision) return;
  lastLivePreviewRevision = preview.revision;
  liveMapImage = new Image();
  liveMapImage.onload = () => {
    $("mapCanvasEmpty").classList.add("hidden");
    drawMap();
  };
  liveMapImage.src = `/api/mapping/sessions/${encodeURIComponent(mappingSession.id)}/preview.png?revision=${preview.revision}`;
}
function renderProject(project, { restoringSession = false } = {}) {
  // A save can make the workflow facts sufficient for the next stage. Keep the
  // operator in map marking until they explicitly confirm completion instead
  // of letting that refresh turn a mouse-up into a workflow transition.
  const retainAnnotationWorkspace = isMapAnnotationWorkspaceActive();
  const projectChanged = selectedProject?.id !== project?.id;
  selectedProject = project;
  if (projectChanged) {
    activeMap = null;
    mapImage = null;
    selectedWaypoint = null;
    selectedVirtualWall = null;
    virtualWallDraft = null;
    $("waypointPopover").classList.add("deployment-hidden");
    const session = readDeploymentSession();
    const canRestore = session?.projectId === project.id;
    creatingAnotherProject = shouldRestoreNewProjectDraft(
      session,
      project.id,
      restoringSession,
    );
    viewedDeploymentStage = creatingAnotherProject
      ? null
      : canRestore
        ? session.viewedDeploymentStage
        : null;
    deploymentTaskDraft = {
      mapSource: canRestore ? session.deploymentTaskDraft?.mapSource || null : null,
      mapLabel: canRestore ? session.deploymentTaskDraft?.mapLabel || "" : "",
      fileSummary: null,
      latestCreatedMapId: null,
      receipt: null,
    };
    editingDeploymentStage = null;
  }
  if (retainAnnotationWorkspace && !projectChanged) {
    editingDeploymentStage = "annotations";
    viewedDeploymentStage = "annotations";
  }
  document.body.classList.remove("deployment-no-project");
  document.body.classList.toggle(
    "deployment-no-map",
    !(project.map_assets || []).length,
  );
  const maps = project.map_assets || [];
  $("newProjectForm").classList.add("deployment-hidden");
  $("currentProjectCard").classList.remove("deployment-hidden");
  $("currentProjectName").textContent = project.name;
  const taskModeLabel = project.task_mode === "multi" ? "多任务点模式" : "单任务点模式";
  $("currentProjectMeta").textContent = `已固定为${taskModeLabel} · 已导入 ${maps.length} 张地图`;
  $("selectedProjectTitle").textContent = project.name;
  $("deploymentFlowEditor").classList.remove("deployment-hidden");
  deploymentFlow = flowForProject(project);
  renderDeploymentFlowEditor();
  $("importControls").classList.remove("deployment-hidden");
  if (deploymentTaskDraft.mapLabel && !$("mapLabel").value) {
    $("mapLabel").value = deploymentTaskDraft.mapLabel;
  }
  $("importMessage").textContent =
    "地图只会复制到部署项目快照；不会修改机器人原目录。";
  $("mapList").innerHTML = maps.length
    ? maps
        .map(
          (map) =>
            `<article class="deployment-map ${activeMap?.id === map.id ? "selected" : ""}" data-map-id="${esc(map.id)}"><div><b>${esc(map.label)}</b><small>${esc(map.kind)} · ${map.width} × ${map.height} · ${map.resolution_m} m/px</small><small>${map.files.pcd_count || 0} 个 PCD · 虚拟墙 ${map.files.walls ? "已导入" : "无"}</small></div><span>${activeMap?.id === map.id ? "正在编辑" : "打开地图"}</span></article>`,
        )
        .join("")
    : '<div class="page-empty">尚未导入地图。先选择一个现有 map.yaml 作为项目快照。</div>';
  renderInstances();
  renderLocalizationBindings();
  renderComponentTemplates();
  renderMapStages();
  renderTopology();
  renderTaskCompilerState(project);
  renderMappingStatus();
  renderDeploymentGuide();
  if (!activeMap && maps.length) {
    const session = readDeploymentSession();
    const restoredMap = session?.projectId === project.id
      ? maps.find((map) => map.id === session.mapId)
      : null;
    selectMap(restoredMap || maps[0]);
  }
  else drawMap();
  if (creatingAnotherProject) revealNewProjectForm();
}
function localizationBindings() {
  return Array.isArray(selectedProject?.localization_bindings)
    ? selectedProject.localization_bindings
    : [];
}
const LOCALIZATION_ROLE_LABELS = {
  indoor: "室内大厅（任务起点 / 进梯前）",
  floor: "用户楼层（交付终点）",
  outdoor: "户外（室外起点）",
  ferry: "摆渡层（中途经过）",
};
function localizationRoleLabel(binding) {
  if (binding?.type === "floor") {
    return `用户楼层（交付终点）· 模板 ${binding.floor_template || "未填写"}`;
  }
  return LOCALIZATION_ROLE_LABELS[binding?.type] || binding?.type || "未设置";
}
function localizationRoutes() {
  return Array.isArray(selectedProject?.localization_routes)
    ? selectedProject.localization_routes
    : [];
}
function mapForId(mapAssetId) {
  return (selectedProject?.map_assets || []).find((item) => item.id === mapAssetId);
}
function renderLocalizationBindings() {
  const holder = $("localizationBindingList");
  const open = $("openLocalizationBinding");
  const routeOpen = $("openLocalizationRoute");
  const guidance = deriveLocalizationGuidance(selectedProject, activeMap?.id);
  const currentLabel = guidance.currentMapLabel || "当前地图";
  open.disabled = !selectedProject || !activeMap;
  open.textContent = activeMap
    ? (guidance.state === "needs_role" ? guidance.primaryAction.label : "修改 " + currentLabel + " 的定位配置")
    : "先选择一张地图";
  $("localizationPurpose").textContent = "完成后，部署包会自动生成定位清单、地图切换顺序和受控路径；无需手工维护切图文件。";
  $("localizationRoleMessage").textContent = guidance.detail;
  $("localizationRoleProgress").textContent = guidance.roles.configured + " / " + guidance.roles.total + " 张已完成";
  $("localizationRoutePurpose").textContent = guidance.route.available
    ? "场景地图顺序、切图锚点与中间节点均由系统自动推导；打开后仅核验结果。"
    : "先确认每张地图的定位配置。系统随后会根据场景模型和地图标记自动推导路线。";
  $("localizationRouteProgress").textContent = guidance.route.available
    ? (guidance.route.configured ? "路线已自动派生" : "可生成系统路线")
    : "等待地图定位配置完成";
  const routeStep = routeOpen.closest(".localization-flow-step");
  routeStep?.classList.toggle("is-waiting", !guidance.route.available);
  routeStep?.setAttribute("aria-disabled", guidance.route.available ? "false" : "true");
  routeOpen.disabled = !guidance.route.available;
  routeOpen.textContent = guidance.route.available ? "查看系统推导结果" : "先确认地图定位配置";
  const bindings = localizationBindings().filter((item) => item.map_asset_id === activeMap?.id);
  holder.innerHTML = bindings.length
    ? bindings.map((item) => [
      '<div class="localization-binding-row active"><div><b>',
      esc(localizationRoleLabel(item)),
      '</b><small>',
      esc(item.building),
      ' 栋 ',
      esc(item.unit),
      ' 单元 · ',
      esc(currentLabel),
      '</small></div><div class="localization-binding-actions"><button class="compact-action edit-localization-binding" data-binding-id="',
      esc(item.id),
      '" type="button">修改配置</button></div></div>',
    ].join("")).join("")
    : '<div class="page-empty">“' + esc(currentLabel) + '”尚未确认定位配置。确认后系统才会自动推导路线。</div>';
  renderLocalizationRoutes(guidance);
}
function localizationTypeChanged() {
  const floor = $("localizationBindingType").value === "floor";
  $("localizationFloorTemplateLabel").classList.toggle("deployment-hidden", !floor);
  $("localizationFloorTemplate").required = floor;
}
function openLocalizationBinding(binding = null) {
  if (!selectedProject || !activeMap) return;
  const instance = mapInstanceFor(activeMap.id) || {};
  const topologyBinding = bindingOwnedByTopology(instance);
  const topologyOwnsBinding = Boolean(topologyBinding);
  localizationBindingDraft = binding || {
    map_asset_id: activeMap.id,
    ...topologyBinding,
    building: topologyBinding?.building || "",
    unit: topologyBinding?.unit || "",
    type: topologyBinding?.type || "indoor",
  };
  $("localizationBindingType").value = topologyBinding?.type || localizationBindingDraft.type;
  $("localizationBuilding").value = topologyBinding?.building || localizationBindingDraft.building || "";
  $("localizationUnit").value = topologyBinding?.unit || localizationBindingDraft.unit || "";
  $("localizationFloorTemplate").value = localizationBindingDraft.floor_template || "";
  $("localizationBindingTypeLabel").classList.toggle("deployment-hidden", topologyOwnsBinding);
  $("localizationIdentityFields").classList.toggle("deployment-hidden", topologyOwnsBinding);
  $("localizationTopologySummary").textContent = topologyOwnsBinding
    ? topologyBinding.type === "ferry"
      ? "部署拓扑已确定为全局摆渡层；运行角色和归属范围由系统复用，无需重复填写。"
      : "部署拓扑已确定：" + topologyBinding.building + " 栋 " + topologyBinding.unit + " 单元。运行角色、楼栋和单元由此复用；物理楼层由电梯落点自动推导，无需重复填写。"
    : "该地图尚无可复用的楼栋、单元部署位置；请在这里补充定位归属。";
  $("localizationBindingDialogTitle").textContent = binding
    ? "修改“" + (activeMap.label || activeMap.id) + "”的定位配置"
    : "确认“" + (activeMap.label || activeMap.id) + "”的定位配置";
  $("localizationBindingDialogDescription").textContent = topologyOwnsBinding
    ? "运行角色和归属已由部署拓扑确定；保存后系统将自动推导路线。"
    : "选择机器人进入当前地图时使用的定位角色；保存后系统将自动推导路线。";
  $("deleteLocalizationBinding").classList.toggle("deployment-hidden", !binding?.id);
  $("localizationBindingDialog").classList.remove("deployment-hidden");
  localizationTypeChanged();
  (topologyBinding?.type === "floor" ? $("localizationFloorTemplate") : $("localizationBindingType")).focus();
}
function openSuggestedLocalizationRoute() {
  const guidance = deriveLocalizationGuidance(selectedProject, activeMap?.id);
  if (!guidance.route.available) return;
  openLocalizationRoute();
}
// The route review is intentionally read-only: route membership, fixed
// anchors and component order are all derived from the scene and map facts.
function automaticRouteNodeLabel(ref) {
  if (ref.kind === "transition") {
    const point = (selectedProject?.waypoints || []).find((item) => item.id === ref.id);
    return `过渡点 · ${point?.label || ref.id} · ${point?.speed_mode || "single_point"}`;
  }
  const component = (selectedProject?.components || []).find((item) => item.id === ref.id);
  return component ? `${componentName(component)} · ${component.label || ref.id}` : `已失效组件 · ${ref.id}`;
}
function renderAutomaticRouteNodes(route, binding) {
  const entry = (route.execution_nodes || []).find((item) => item.binding_id === binding.id);
  const refs = entry?.node_refs || [];
  if (!refs.length) return '<p class="route-execution-empty">该地图固定锚点之间没有中间标记。</p>';
  return `<ol class="route-execution-list">${refs.map((ref, index) => `<li><span><b>${index + 1}. ${esc(automaticRouteNodeLabel(ref))}</b><small>${ref.kind === "transition" ? "路径位置、朝向和速度来自该过渡点；返程由系统反向投影。" : "组件会按路径方向生成导航区间或受控动作。"}</small></span></li>`).join("")}</ol>`;
}
async function refreshAutomaticLocalizationRoutes() {
  if (!selectedProject) return;
  const button = $("saveLocalizationRoute");
  button.disabled = true;
  note("localizationRouteMessage", "正在根据项目场景、地图标记和可通行区域（含虚拟墙约束）推导路线…");
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/localization-routes/derive`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
    );
    renderProject(data.project);
    renderLocalizationRouteDialog();
    note("localizationRouteMessage", "自动路线已更新。若结果异常，请回到对应地图调整标记或组件朝向。", false);
  } catch (error) {
    note("localizationRouteMessage", `${error.message} 请回到地图标记修正后再试。`, true);
    $("localizationRouteLinks").innerHTML = '<div class="route-blocker">系统未生成路线：请按上方提示回到地图补齐或修正标记。路线顺序不能手动编辑。</div>';
  } finally {
    button.disabled = false;
  }
}
function openLocalizationRoute() {
  localizationRouteDraft = null;
  $("localizationRouteDialog").classList.remove("deployment-hidden");
  $("localizationRouteLinks").focus?.();
  refreshAutomaticLocalizationRoutes();
}
function closeLocalizationRoute() {
  localizationRouteDraft = null;
  $("localizationRouteDialog").classList.add("deployment-hidden");
}
function renderLocalizationRouteDialog() {
  const route = localizationRoutes()[0];
  const holder = $("localizationRouteLinks");
  $("localizationRouteIdentity").textContent = "系统按创建项目时的场景地图顺序、核心地图标记和可通行路径生成；所有顺序均只读。";
  if (!route) {
    holder.innerHTML = '<div class="page-empty">尚未生成路线。系统会检查每个阶段的地图绑定、唯一的起点/目标/电梯和中间设施标记。</div>';
    $("localizationRouteSummary").textContent = "请完成地图标记后重新派生；不需要手动选择地图、端点或顺序。";
    return;
  }
  const bindings = (route.binding_ids || []).map((id) => localizationBindings().find((item) => item.id === id)).filter(Boolean);
  holder.innerHTML = bindings.map((binding, index) => {
    const map = mapForId(binding.map_asset_id) || {};
    const first = index === 0;
    const last = index === bindings.length - 1;
    const link = route.links?.[index];
    const enter = first ? "起点标记" : "电梯中心坐标 0,0";
    const leave = last ? "目标标记；返程由本图末个节点反向开始" : `已标记电梯：${link?.anchor?.component_id || "待核验"}`;
    return `<article class="localization-route-card"><header><div><b>${index + 1}. ${esc(map.label || binding.map_asset_id)}</b><small>${esc(binding.type === "floor" ? `用户楼层 · 模板 ${binding.floor_template}` : binding.type)}</small></div><span class="route-auto-note">系统排序</span></header><div class="route-derived"><span>进入：${esc(enter)}</span><span>离开/返回：${esc(leave)}</span></div><section class="route-execution-chain"><header><b>自动经过节点</b><small>按地图可通行路径的弧长排序；返程严格反向，并保留方向、速度和受控动作。</small></header>${renderAutomaticRouteNodes(route, binding)}</section></article>`;
  }).join("");
  $("localizationRouteSummary").innerHTML = `<b>自动派生完成</b><span>已按 ${bindings.length} 张场景地图生成可审计执行链；将用于 <code>loc_yaml_path.json</code>、任务 JSON 和行为树预览。</span>`;
}
async function saveLocalizationRoute() {
  await refreshAutomaticLocalizationRoutes();
}
function renderLocalizationRoutes(guidance = deriveLocalizationGuidance(selectedProject, activeMap?.id)) {
  const holder = $("localizationRouteList");
  const routes = localizationRoutes();
  if (!guidance.route.available) {
    holder.innerHTML = `<div class="page-empty">${esc(`还需完成 ${guidance.roles.total - guidance.roles.configured} 张地图的运行角色，系统随后会自动推导路线。`)}</div>`;
    return;
  }
  holder.innerHTML = routes.length
    ? routes.map((route) => `<div class="localization-route-row"><div><b>${esc(route.building)} 栋 ${esc(route.unit)} 单元 · 系统已派生 ${route.binding_ids.length} 张地图</b><small>场景顺序、切图锚点和中间组件顺序均由地图标记与可通行路径自动计算。</small></div><button class="compact-action edit-localization-route" type="button">查看系统推导</button></div>`).join("")
    : '<div class="page-empty">地图角色已完成。打开“查看系统推导结果”后，系统会自动计算路线。</div>';
}
function closeLocalizationBinding() {
  localizationBindingDraft = null;
  $("localizationBindingDialog").classList.add("deployment-hidden");
}
async function saveLocalizationBinding() {
  if (!selectedProject || !activeMap) return;
  const instance = mapInstanceFor(activeMap.id) || {};
  const topologyBinding = bindingOwnedByTopology(instance);
  const payload = topologyBinding
    ? { map_asset_id: activeMap.id }
    : {
      map_asset_id: activeMap.id,
      building: $("localizationBuilding").value,
      unit: $("localizationUnit").value,
      type: $("localizationBindingType").value,
    };
  const type = topologyBinding?.type || payload.type;
  if (type === "floor") payload.floor_template = $("localizationFloorTemplate").value;
  const id = localizationBindingDraft?.id;
  try {
    const data = await request(`/api/deployments/${encodeURIComponent(selectedProject.id)}/localization-bindings${id ? `/${encodeURIComponent(id)}` : ""}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    renderProject(data.project);
    closeLocalizationBinding();
    note("mapToolHint", "地图运行角色已保存；完成每张地图角色后，系统会自动推导机器人经过顺序。");
    completeDeploymentEdit("定位绑定已保存，已返回当前任务。");
  } catch (error) { note("localizationBindingMessage", error.message, true); }
}
async function deleteLocalizationBinding() {
  if (!selectedProject || !localizationBindingDraft?.id) return;
  try {
    await request(`/api/deployments/${encodeURIComponent(selectedProject.id)}/localization-bindings/${encodeURIComponent(localizationBindingDraft.id)}`, { method: "DELETE" });
    await openProject(selectedProject.id);
    closeLocalizationBinding();
    completeDeploymentEdit("定位绑定已删除，已返回当前任务。");
  } catch (error) { note("localizationBindingMessage", error.message, true); }
}
function renderInstances() {
  const items = selectedProject?.map_instances || [];
  $("instanceList").innerHTML = items.length
    ? items
        .map((item) => {
          const identity = item.building
            ? `${esc(item.building)} 栋 ${esc(item.unit)} 单元${item.floor === null || item.floor === undefined ? " · 物理楼层待电梯组件推导" : ` · 旧项目楼层 ${esc(item.floor)}F`}`
            : "园区室外";
          return `<div class="asset-row"><div><b>${esc(item.label)}</b><small>${esc(item.role)} · ${identity}</small></div></div>`;
        })
        .join("")
    : '<div class="page-empty">尚未建立部署拓扑位置。</div>';
}
function renderWaypoints() {
  const items = (selectedProject?.waypoints || []).filter(
    (item) => item.map_asset_id === activeMap?.id,
  );
  $("waypointList").innerHTML = activeMap
    ? items.length
      ? items
          .map(
            (item) =>
              `<div class="asset-row waypoint-row"><div><b>${esc(item.label)}</b><small>${esc(item.kind)} · x ${item.x.toFixed(2)} · y ${item.y.toFixed(2)} · yaw ${item.yaw.toFixed(2)}</small></div><button class="compact-action delete-waypoint" data-id="${esc(item.id)}" type="button">删除</button></div>`,
          )
          .join("")
      : '<div class="page-empty">当前地图没有标记。选择“＋ Waypoint / 起点 / 目标点”后点击画布放置。</div>'
    : '<div class="page-empty">选择地图后可放置 Waypoint。</div>';
}
function renderComponentTemplates() {
  const holder = $("componentTemplateConfig");
  if (!selectedProject) {
    holder.classList.add("deployment-hidden");
    return;
  }
  holder.classList.remove("deployment-hidden");
  const categories = [
    ["access_protocols", "门禁 / 闸机 / 自动门"],
    ["elevator_protocols", "梯控"],
  ];
  $("protocolTemplateList").innerHTML = categories
    .map(
      ([category, title]) =>
        `<div class="protocol-template-group"><b>${title}</b><div>${protocolOptions(
          selectedProject,
          category,
        )
          .map(
            ([id, label]) =>
              `<span class="protocol-chip">${esc(label)}<button class="delete-protocol" data-category="${esc(category)}" data-protocol-id="${esc(id)}" type="button" aria-label="移除 ${esc(label)} 协议">×</button></span>`,
          )
          .join("")}</div></div>`,
    )
    .join("");
}
function resizeCanvas() {
  const box = canvas.getBoundingClientRect();
  if (!box.width || !box.height) return;
  const ratio = window.devicePixelRatio || 1;
  const width = Math.round(box.width * ratio);
  const height = Math.round(box.height * ratio);
  if (canvas.width === width && canvas.height === height) return;
  canvas.width = width;
  canvas.height = height;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  if (mapNeedsFit && mapImage) {
    fitMap();
  } else {
    drawMap();
  }
}
function scheduleCanvasResize() {
  if (canvasResizeFrame) cancelAnimationFrame(canvasResizeFrame);
  canvasResizeFrame = requestAnimationFrame(() => {
    canvasResizeFrame = null;
    resizeCanvas();
  });
}
function fitMap() {
  if (!activeMap) {
    drawMap();
    return;
  }
  const box = canvas.getBoundingClientRect();
  if (!box.width || !box.height) {
    mapNeedsFit = true;
    return;
  }
  mapNeedsFit = false;
  const worldWidth = activeMap.width * activeMap.resolution_m;
  const worldHeight = activeMap.height * activeMap.resolution_m;
  mapView.scale = Math.min(
    (box.width - 56) / worldWidth,
    (box.height - 56) / worldHeight,
  );
  mapView.x = (box.width - worldWidth * mapView.scale) / 2;
  mapView.y = (box.height - worldHeight * mapView.scale) / 2;
  drawMap();
}
function drawGrid(width, height) {
  const scale = mapView.scale;
  const step = scale < 18 ? 5 : scale < 42 ? 2 : 1;
  context.save();
  context.strokeStyle = "#344348";
  context.lineWidth = 1;
  const startX = ((mapView.x % (step * scale)) + step * scale) % (step * scale);
  const startY = ((mapView.y % (step * scale)) + step * scale) % (step * scale);
  for (let x = startX; x < width; x += step * scale) {
    context.beginPath();
    context.moveTo(x, 0);
    context.lineTo(x, height);
    context.stroke();
  }
  for (let y = startY; y < height; y += step * scale) {
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(width, y);
    context.stroke();
  }
  context.restore();
}
function componentDimensions(item) {
  return getComponentDimensions(item, mapView.scale);
}
function componentCanvasPoint(item) {
  return mapPointToCanvas(item, activeMap, mapView);
}
function worldCanvasPoint(point) {
  return mapPointToCanvas(point, activeMap, mapView);
}
function canvasPointFromEvent(event) {
  const box = canvas.getBoundingClientRect();
  return { x: event.clientX - box.left, y: event.clientY - box.top };
}
function worldPointFromEvent(event) {
  return canvasPointToMap(canvasPointFromEvent(event), activeMap, mapView);
}
function pointIsOnActiveMap(point) {
  return isPointOnMap(point, activeMap);
}
function drawEraseOperation(edit, draft = false) {
  const points = edit.points || [];
  if (!points.length) return;
  context.save();
  context.globalAlpha = 1;
  if (edit.kind === "brush_erase") {
    const radius = Number(edit.radius_m || eraserDiameterM / 2) * mapView.scale;
    const shape = edit.shape || "circle";
    context.strokeStyle = "#fff";
    context.fillStyle = "#fff";
    const first = worldCanvasPoint(points[0]);
    if (shape === "square") {
      const side = radius * 2;
      for (const point of points) {
        const next = worldCanvasPoint(point);
        context.fillRect(next.x - radius, next.y - radius, side, side);
      }
    } else {
      context.lineCap = "round";
      context.lineJoin = "round";
      context.lineWidth = radius * 2;
      context.beginPath();
      context.moveTo(first.x, first.y);
      for (const point of points.slice(1)) {
        const next = worldCanvasPoint(point);
        context.lineTo(next.x, next.y);
      }
      context.stroke();
      context.beginPath();
      context.arc(first.x, first.y, radius, 0, Math.PI * 2);
      context.fill();
    }
  } else if (points.length >= 3) {
    const first = worldCanvasPoint(points[0]);
    context.beginPath();
    context.moveTo(first.x, first.y);
    for (const point of points.slice(1)) {
      const next = worldCanvasPoint(point);
      context.lineTo(next.x, next.y);
    }
    context.closePath();
    context.fillStyle = "#fff";
    context.fill();
  }
  context.restore();
}
function drawMapEdits() {
  for (const edit of eraseEditsForRender({
    savedEdits: selectedProject?.map_edits || [],
    activeMapId: activeMap?.id,
    activeStroke: eraserStroke,
    pendingStroke: pendingEraserStroke,
  })) {
    drawEraseOperation(edit);
  }
  if (activeTool === "erase_brush" && eraserHoverPoint) {
    const center = worldCanvasPoint(eraserHoverPoint);
    const actualRadius = (eraserDiameterM / 2) * mapView.scale;
    // At fit-to-map scale a 0.8m brush can be only a few device pixels.  The
    // larger halo is cursor feedback only; the inner ring remains the exact
    // physical erase radius stored in the SiteProject.
    const previewRadius = Math.max(actualRadius, 15);
    context.save();
    context.fillStyle = "rgba(65, 216, 209, .24)";
    context.strokeStyle = "rgba(16, 157, 150, .98)";
    context.lineWidth = 2;
    context.setLineDash([5, 4]);
    context.beginPath();
    if (eraserShape === "square") {
      context.rect(
        center.x - previewRadius,
        center.y - previewRadius,
        previewRadius * 2,
        previewRadius * 2,
      );
    } else context.arc(center.x, center.y, previewRadius, 0, Math.PI * 2);
    context.fill();
    context.stroke();
    context.setLineDash([]);
    if (previewRadius !== actualRadius) {
      context.strokeStyle = "rgba(4, 119, 114, .96)";
      context.lineWidth = 1;
      context.beginPath();
      if (eraserShape === "square") {
        context.rect(
          center.x - actualRadius,
          center.y - actualRadius,
          actualRadius * 2,
          actualRadius * 2,
        );
      } else context.arc(center.x, center.y, actualRadius, 0, Math.PI * 2);
      context.stroke();
    }
    context.fillStyle = "rgba(255, 255, 255, .78)";
    context.beginPath();
    context.arc(center.x, center.y, 2.5, 0, Math.PI * 2);
    context.fill();
    context.fillStyle = "rgba(5, 67, 64, .96)";
    context.font = "600 10px ui-monospace, monospace";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(`${eraserDiameterM.toFixed(1)} m`, center.x, center.y);
    context.restore();
  }
  if (polygonEraseDraft.length) {
    context.save();
    context.strokeStyle = "#38d6d1";
    context.fillStyle = "rgba(56, 214, 209, .14)";
    context.lineWidth = 2;
    context.setLineDash([6, 5]);
    const first = worldCanvasPoint(polygonEraseDraft[0]);
    context.beginPath();
    context.moveTo(first.x, first.y);
    for (const point of polygonEraseDraft.slice(1)) {
      const next = worldCanvasPoint(point);
      context.lineTo(next.x, next.y);
    }
    if (polygonEraseDraft.length >= 3) context.closePath();
    context.stroke();
    if (polygonEraseDraft.length >= 3) context.fill();
    context.setLineDash([]);
    for (const point of polygonEraseDraft) {
      const next = worldCanvasPoint(point);
      context.fillStyle = "#38d6d1";
      context.beginPath();
      context.arc(next.x, next.y, 4, 0, Math.PI * 2);
      context.fill();
    }
    context.restore();
  }
}

function drawMapRoutes() {
  if (!activeMap) return;
  const points = new Map(
    (selectedProject?.waypoints || []).map((item) => [item.id, item]),
  );
  const routes = (selectedProject?.routes || []).filter(
    (route) => route.map_asset_id === activeMap.id,
  );
  const drawLine = (ids, color, dashed = false) => {
    const routePoints = ids.map((id) => points.get(id)).filter(Boolean);
    if (routePoints.length < 2) return;
    context.save();
    context.strokeStyle = color;
    context.lineWidth = dashed ? 2 : 3;
    if (dashed) context.setLineDash([7, 6]);
    context.beginPath();
    const first = worldCanvasPoint(routePoints[0]);
    context.moveTo(first.x, first.y);
    for (const point of routePoints.slice(1)) {
      const next = worldCanvasPoint(point);
      context.lineTo(next.x, next.y);
    }
    context.stroke();
    context.restore();
  };
  for (const route of routes) drawLine(route.waypoint_ids || [], "rgba(10, 132, 255, .9)");
  if (routeDraft.length) drawLine(routeDraft, "rgba(255, 149, 0, .95)", true);
}
function waypointHeadingDegrees(waypoint) {
  return Math.round((Number(waypoint.yaw || 0) * 180) / Math.PI);
}
function syncTransitionYawControl(waypoint) {
  const degrees = waypointHeadingDegrees(waypoint);
  let returnDegrees = degrees + 180;
  if (returnDegrees > 180) returnDegrees -= 360;
  $("waypointTransitionYaw").value = String(degrees);
  $("waypointPopoverDetail").textContent = `过渡点 · x ${Number(waypoint.x).toFixed(2)} · y ${Number(waypoint.y).toFixed(2)} · 去程 ${degrees}° · 返程 ${returnDegrees}°`;
}
function transitionDirectionHandlePoint(waypoint) {
  const center = worldCanvasPoint(waypoint);
  const yaw = Number(waypoint.yaw || 0);
  const distance = 32;
  return {
    x: center.x + Math.cos(yaw) * distance,
    y: center.y - Math.sin(yaw) * distance,
  };
}
function drawWaypointSymbol(point, px, py) {
  const palette = { start: "#39dcad", target: "#ffbd61", return: "#ff6b9d", map_transition: "#b995ef" };
  const isTransition = point.kind === "transition";
  const isTaskTransition = isTransition && Boolean(taskTransitionRole(point.map_asset_id));
  const selected = selectedWaypoint?.id === point.id;
  const color = palette[point.kind] || "#5bb8ff";
  context.save();
  context.fillStyle = color;
  context.beginPath();
  context.arc(px, py, point.kind === "map_transition" ? 7 : isTransition ? 6 : 5, 0, Math.PI * 2);
  context.fill();
  if (point.kind === "map_transition") {
    context.strokeStyle = "#fff";
    context.lineWidth = 1.5;
    context.beginPath();
    context.arc(px, py, 3, 0, Math.PI * 2);
    context.stroke();
  }
  if (isTaskTransition) {
    const yaw = Number(point.yaw || 0);
    context.translate(px, py);
    context.rotate(-yaw);
    context.strokeStyle = "#1677ff";
    context.lineWidth = 2.5;
    context.beginPath();
    context.moveTo(0, 0);
    context.lineTo(22, 0);
    context.stroke();
    context.fillStyle = "#1677ff";
    context.beginPath();
    context.moveTo(24, 0);
    context.lineTo(15, -5);
    context.lineTo(15, 5);
    context.closePath();
    context.fill();
    // The faint opposite arrow makes the automatically mirrored return
    // direction visible without turning it into a separately editable pose.
    context.strokeStyle = "rgba(22, 119, 255, .48)";
    context.lineWidth = 1.5;
    context.setLineDash([4, 3]);
    context.beginPath();
    context.moveTo(0, 0);
    context.lineTo(-18, 0);
    context.stroke();
    context.setLineDash([]);
    context.fillStyle = "rgba(22, 119, 255, .48)";
    context.beginPath();
    context.moveTo(-20, 0);
    context.lineTo(-12, -4);
    context.lineTo(-12, 4);
    context.closePath();
    context.fill();
    if (selected) {
      context.strokeStyle = "#77acff";
      context.lineWidth = 1.5;
      context.beginPath();
      context.moveTo(24, 0);
      context.lineTo(32, 0);
      context.stroke();
      context.fillStyle = "#0a84ff";
      context.beginPath();
      context.arc(32, 0, 8, 0, Math.PI * 2);
      context.fill();
      context.strokeStyle = "#fff";
      context.lineWidth = 1.5;
      context.beginPath();
      context.arc(32, 0, 3.5, -0.8, 2.4);
      context.stroke();
    }
    context.restore();
    context.save();
  }
  context.fillStyle = "rgba(18, 28, 34, .9)";
  context.font = "600 10px system-ui, sans-serif";
  context.textAlign = "left";
  context.fillText(isTaskTransition ? `${point.label} · 去 ${waypointHeadingDegrees(point)}°` : point.label, px + 9, py - 10);
  context.restore();
}
function componentLocalPoint(item, event) {
  return getComponentLocalPoint(item, canvasPointFromEvent(event), activeMap, mapView);
}
function drawElevatorDoorMarker(width, height) {
  const markerSize = Math.max(3, Math.min(8, Math.min(width, height) * 0.12));
  const top = -height / 2 + markerSize * 0.45;
  context.save();
  context.shadowColor = "transparent";
  context.fillStyle = "#ffffff";
  context.fillRect(-markerSize * 0.8, top - markerSize * 0.2, markerSize * 1.6, markerSize * 0.4);
  context.restore();
}
function drawStartDirectionMarker(item, px, py, radius) {
  const { lineStart, tip, leftWing, rightWing } = startDirectionGeometry({
    x: px,
    y: py,
    yaw: Number(item.yaw || 0),
    radius,
  });
  context.save();
  context.lineCap = "round";
  context.lineJoin = "round";
  context.strokeStyle = "rgba(255, 255, 255, .96)";
  context.lineWidth = 6;
  context.beginPath();
  context.moveTo(lineStart.x, lineStart.y);
  context.lineTo(tip.x, tip.y);
  context.stroke();
  context.fillStyle = "rgba(255, 255, 255, .96)";
  context.beginPath();
  context.moveTo(tip.x, tip.y);
  context.lineTo(leftWing.x, leftWing.y);
  context.lineTo(rightWing.x, rightWing.y);
  context.closePath();
  context.fill();
  context.strokeStyle = "#1677ff";
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(lineStart.x, lineStart.y);
  context.lineTo(tip.x, tip.y);
  context.stroke();
  context.fillStyle = "#1677ff";
  context.beginPath();
  context.moveTo(tip.x, tip.y);
  context.lineTo(leftWing.x, leftWing.y);
  context.lineTo(rightWing.x, rightWing.y);
  context.closePath();
  context.fill();
  context.restore();
}
function drawComponentSymbol(item, px, py) {
  const { width, height } = componentDimensions(item);
  const size = Math.max(width, height);
  const palette = {
    start: "#39dcad",
    target: "#ffbd61",
    building_entrance: "#b995ef",
    elevator: "#719eff",
    gate: "#5ed7d1",
    auto_door: "#75b8ff",
    narrow_passage: "#f2a4c9",
    ramp: "#e6b76b",
    slow_zone: "#ff9f6b",
  };
  const color = palette[item.kind] || "#b995ef";
  context.save();
  context.translate(px, py);
  context.rotate(-item.yaw || 0);
  context.lineWidth = 1.5;
  context.shadowColor = "rgba(7,18,25,.38)";
  context.shadowBlur = 8;
  context.shadowOffsetY = 3;
  const sticker = (w = width, h = height) => {
    context.beginPath();
    context.roundRect(-w / 2, -h / 2, w, h, Math.min(8, size * 0.18));
    context.fillStyle = `${color}66`;
    context.fill();
    context.shadowColor = "transparent";
    context.strokeStyle = `${color}`;
    context.stroke();
  };
  const line = (x1, y1, x2, y2) => {
    context.beginPath();
    context.moveTo(x1, y1);
    context.lineTo(x2, y2);
    context.stroke();
  };
  if (isDirectionalTaskAnchor(item.kind)) {
    context.beginPath();
    context.arc(0, 0, Math.min(width, height) * 0.36, 0, Math.PI * 2);
    context.fillStyle = `${color}77`;
    context.fill();
    context.shadowColor = "transparent";
    context.strokeStyle = color;
    context.stroke();
  } else if (item.kind === "building_entrance") {
    sticker();
    context.strokeStyle = "#f6eaff";
    line(-width * 0.32, height * 0.34, -width * 0.32, -height * 0.28);
    line(width * 0.32, height * 0.34, width * 0.32, -height * 0.28);
    line(-width * 0.32, -height * 0.28, width * 0.32, -height * 0.28);
  } else if (item.kind === "elevator") {
    sticker();
    context.strokeStyle = "#e9f1ff";
    drawElevatorDoorMarker(width, height);
    line(0, -height * 0.37, 0, height * 0.37);
    line(-width * 0.25, -height * 0.37, -width * 0.25, height * 0.37);
    line(width * 0.25, -height * 0.37, width * 0.25, height * 0.37);
    context.fillStyle = "#e9f1ff";
    context.fillRect(
      -width * 0.08,
      -height * 0.08,
      width * 0.16,
      height * 0.16,
    );
  } else if (item.kind === "gate") {
    sticker();
    context.strokeStyle = "#ddfffd";
    for (let x = -width * 0.42; x <= width * 0.42; x += width * 0.22)
      line(x, -height * 0.32, x, height * 0.32);
  } else if (item.kind === "auto_door") {
    sticker();
    context.strokeStyle = "#e5f3ff";
    line(0, -height * 0.4, 0, height * 0.4);
    line(-width * 0.43, -height * 0.34, -width * 0.12, height * 0.34);
    line(width * 0.43, -height * 0.34, width * 0.12, height * 0.34);
  } else if (item.kind === "narrow_passage") {
    sticker();
    context.strokeStyle = "#fff0f7";
    line(-width * 0.24, -height * 0.42, -width * 0.24, height * 0.42);
    line(width * 0.24, -height * 0.42, width * 0.24, height * 0.42);
  } else if (item.kind === "ramp") {
    sticker();
    context.strokeStyle = "#fff1d2";
    line(-width * 0.42, height * 0.28, width * 0.4, -height * 0.28);
  } else if (item.kind === "slow_zone") {
    sticker();
    context.strokeStyle = "#fff1e6";
    for (let x = -width * 0.42; x < width * 0.4; x += width * 0.22)
      line(x, -height * 0.3, x + width * 0.22, height * 0.3);
  } else sticker();
  context.save();
  context.fillStyle = "#ffffff";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.font = `700 ${Math.max(8, Math.min(12, width / Math.max(componentName(item).length, 2) - 1))}px sans-serif`;
  context.fillText(componentName(item), 0, 0);
  context.restore();
  if (selectedComponent?.id === item.id) {
    context.strokeStyle = "#fff";
    context.setLineDash([4, 3]);
    context.strokeRect(
      -width / 2 - 5,
      -height / 2 - 5,
      width + 10,
      height + 10,
    );
    context.setLineDash([]);
    context.strokeStyle = "#0a84ff";
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(width / 2 - 1, height / 2 - 1);
    context.lineTo(width / 2 + 9, height / 2 + 9);
    context.stroke();
    context.fillStyle = "#fff";
    context.fillRect(width / 2 + 4, height / 2 + 4, 10, 10);
    context.strokeStyle = "#0a84ff";
    context.strokeRect(width / 2 + 4, height / 2 + 4, 10, 10);
    // Rotation is deliberately adjacent to, rather than overloading, the
    // resize handle.  Both controls stay attached to the lower-right corner.
    context.strokeStyle = "#77acff";
    context.lineWidth = 1.5;
    line(width / 2 + 9, height / 2 + 9, width / 2 + 26, height / 2 + 9);
    context.fillStyle = "#0a84ff";
    context.beginPath();
    context.arc(width / 2 + 29, height / 2 + 9, 9, 0, Math.PI * 2);
    context.fill();
    context.strokeStyle = "#fff";
    context.lineWidth = 1.3;
    context.beginPath();
    context.arc(width / 2 + 29, height / 2 + 9, 4, -0.8, 2.4);
    context.stroke();
    context.beginPath();
    context.moveTo(width / 2 + 32.5, height / 2 + 5.5);
    context.lineTo(width / 2 + 33.5, height / 2 + 10);
    context.lineTo(width / 2 + 29.3, height / 2 + 8.8);
    context.stroke();
  }
  context.restore();
  if (isDirectionalTaskAnchor(item.kind)) {
    drawStartDirectionMarker(item, px, py, Math.min(width, height) * 0.36);
  }
}
function drawMap() {
  const box = canvas.getBoundingClientRect();
  drawDeploymentCanvas({
    context,
    canvasBox: box,
    activeMap,
    mapImage,
    liveMapImage,
    mappingPreview: mappingSession?.preview,
    project: selectedProject,
    view: mapView,
    drawGrid,
    drawMapEdits,
    drawVirtualWalls,
    drawMapRoutes,
    drawWaypointSymbol,
    drawComponentSymbol,
    drawMapOrigin,
    drawLocalizationMarkers,
    mapPointToCanvas,
  });
}
function flushCanvasInteractionReadout() {
  if (pendingComponentSizeReadout) {
    $("componentSizeReadout").textContent = pendingComponentSizeReadout;
    pendingComponentSizeReadout = null;
  }
  if (pendingComponentYaw !== null) {
    $("componentYaw").value = pendingComponentYaw;
    pendingComponentYaw = null;
  }
  if (pendingWaypointYaw) {
    syncTransitionYawControl(pendingWaypointYaw);
    pendingWaypointYaw = null;
  }
}
scheduleMapDraw = createCanvasDrawScheduler(() => {
  flushCanvasInteractionReadout();
  drawMap();
});
function virtualWallsForActiveMap() {
  if (!selectedProject || !activeMap) return [];
  return (selectedProject.virtual_walls || []).filter((wall) => {
    const points = Array.isArray(wall?.points)
      ? wall.points
      : [wall?.start, wall?.end];
    return wall?.map_asset_id === activeMap.id && points.length >= 2 && points.every(
      (point) => Number.isFinite(point?.x) && Number.isFinite(point?.y),
    );
  });
}
function drawVirtualWalls() {
  if (!activeMap) return;
  const walls = wallsForDisplay(
    virtualWallsForActiveMap(),
    virtualWallDrag ? selectedVirtualWall : null,
  );
  const draftPoints = virtualWallDraft?.hover
    ? [...virtualWallDraft.points, virtualWallDraft.hover]
    : virtualWallDraft?.points;
  const draft = draftPoints?.length >= 2
    ? [{ id: "virtual-wall-draft", points: draftPoints, draft: true }]
    : [];
  for (const wall of [...walls, ...draft]) {
    const points = Array.isArray(wall.points) ? wall.points : [wall.start, wall.end];
    context.save();
    context.lineCap = "round";
    context.lineJoin = "round";
    context.strokeStyle = wall.draft ? "rgba(220, 38, 38, .65)" : "#dc2626";
    context.lineWidth = wall.draft ? 4 : 3;
    if (wall.draft) context.setLineDash([7, 5]);
    const first = worldCanvasPoint(points[0]);
    context.beginPath();
    context.moveTo(first.x, first.y);
    for (const point of points.slice(1)) {
      const canvasPoint = worldCanvasPoint(point);
      context.lineTo(canvasPoint.x, canvasPoint.y);
    }
    context.stroke();
    // Persistent virtual walls stay visually quiet. Vertices are a drawing
    // affordance only, so they disappear once the polyline is saved.
    if (wall.draft) {
      for (const point of points.map(worldCanvasPoint)) {
        context.fillStyle = "#fff";
        context.strokeStyle = "#dc2626";
        context.lineWidth = 2;
        context.beginPath();
        context.arc(point.x, point.y, 5.5, 0, Math.PI * 2);
        context.fill();
        context.stroke();
      }
    }
    context.restore();
  }
}
function virtualWallAt(event) {
  if (!activeMap) return null;
  const point = canvasPointFromEvent(event);
  for (const wall of [...virtualWallsForActiveMap()].reverse()) {
    const hit = wallHitTest(wall, activeMap, mapView, point);
    if (hit) return { wall, hit };
  }
  return null;
}
function selectVirtualWall(wall) {
  selectedVirtualWall = wall;
  selectedComponent = null;
  closeComponentPopover();
  closeWaypointPopover();
  drawMap();
}
async function createVirtualWall(points) {
  if (!selectedProject || !activeMap) return;
  virtualWallPlacementPending = true;
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/virtual-walls`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ map_id: activeMap.id, points }),
      },
    );
    renderProject(data.project);
    selectedVirtualWall = data.virtual_wall;
    drawMap();
    note("mapToolHint", "虚拟墙已保存为红色不可穿越折线；可继续绘制下一条。按 Esc 取消未完成折线。");
    keepMapAnnotationOpen("虚拟墙已保存；请继续检查当前地图，完成后再确认进入定位路线。", { force: true });
  } catch (error) {
    note("mapToolHint", error.message, true);
  } finally {
    virtualWallPlacementPending = false;
  }
}
async function persistVirtualWall(wall) {
  if (!selectedProject) return;
  const projectId = selectedProject.id;
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(projectId)}/virtual-walls/${encodeURIComponent(wall.id)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Array.isArray(wall.points)
          ? { points: wall.points }
          : { start: wall.start, end: wall.end }),
      },
    );
    renderProject(data.project);
    selectedVirtualWall = data.virtual_wall;
    drawMap();
    note("mapToolHint", "虚拟墙位置已保存。");
    keepMapAnnotationOpen("虚拟墙位置已保存；请继续检查当前地图，完成后再确认进入定位路线。", { force: true });
  } catch (error) {
    // Do not leave a locally dragged wall pretending it was saved. Reload the
    // authoritative project document, including the generated wall file view.
    await openProject(projectId).catch(() => undefined);
    selectedVirtualWall = null;
    note("mapToolHint", error.message, true);
  }
}
async function deleteSelectedVirtualWall() {
  if (!selectedProject || !selectedVirtualWall) return;
  const wall = selectedVirtualWall;
  if (!window.confirm("删除这段虚拟墙？系统会立即重新生成当前地图的 map_walls.yaml。")) return;
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/virtual-walls/${encodeURIComponent(wall.id)}`,
      { method: "DELETE" },
    );
    selectedVirtualWall = null;
    renderProject(data.project);
    drawMap();
    note("mapToolHint", "虚拟墙已删除，当前地图的不可穿越区域已自动重新计算。");
    keepMapAnnotationOpen("虚拟墙已删除；请继续检查当前地图，完成后再确认进入定位路线。", { force: true });
  } catch (error) {
    note("mapToolHint", error.message, true);
  }
}
function drawMapOrigin() {
  if (!activeMap) return;
  const point = mapPointToCanvas({ x: 0, y: 0 }, activeMap, mapView);
  if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) return;
  const crossSize = 8;
  context.save();
  context.translate(point.x, point.y);
  context.lineWidth = 1.25;
  context.strokeStyle = "rgba(10, 132, 255, 0.95)";
  context.beginPath();
  context.moveTo(-crossSize, 0);
  context.lineTo(crossSize, 0);
  context.moveTo(0, -crossSize);
  context.lineTo(0, crossSize);
  context.stroke();
  context.fillStyle = "rgba(255, 255, 255, 0.96)";
  context.beginPath();
  context.arc(0, 0, 2.5, 0, Math.PI * 2);
  context.fill();
  context.strokeStyle = "#0a84ff";
  context.lineWidth = 1;
  context.stroke();
  context.fillStyle = "rgba(18, 28, 34, 0.88)";
  context.font = "600 10px system-ui, sans-serif";
  context.textAlign = "left";
  context.fillText("(0, 0)", 10, -10);
  context.restore();
}
function drawLocalizationMarkers() {
  for (const binding of localizationBindings().filter((item) => item.map_asset_id === activeMap?.id)) {
    for (const [kind, pose] of [["go", binding.init_go], ["return", binding.init_return]]) {
      if (!pose) continue;
      const point = mapPointToCanvas(pose, activeMap, mapView);
      context.save(); context.fillStyle = kind === "go" ? "#0a84ff" : "#ff9f0a";
      context.beginPath(); context.arc(point.x, point.y, 7, 0, Math.PI * 2); context.fill();
      context.fillStyle = "#fff"; context.font = "700 9px system-ui"; context.textAlign = "center"; context.fillText(kind === "go" ? "去" : "返", point.x, point.y + 3); context.restore();
    }
  }
}
function selectMap(map, { persist = true } = {}) {
  if (!selectedProject) return;
  if (routeDraft.length && activeMap?.id !== map.id) routeDraft = [];
  if (activeMap?.id !== map.id) {
    selectedVirtualWall = null;
    virtualWallDraft = null;
  }
  activeMap = map;
  if (persist) persistDeploymentSession();
  document.body.classList.remove("deployment-no-map");
  mapImage = new Image();
  mapImage.onload = () => {
    $("mapCanvasEmpty").classList.add("hidden");
    fitMap();
  };
  mapImage.onerror = () => {
    mapImage = null;
    const empty = $("mapCanvasEmpty");
    empty.querySelector("b").textContent = "地图预览加载失败";
    empty.querySelector("small").textContent = "请检查项目地图快照是否完整，然后重新打开该地图。";
    empty.classList.remove("hidden");
    drawMap();
  };
  mapImage.src = `/api/deployments/${encodeURIComponent(selectedProject.id)}/maps/${encodeURIComponent(map.id)}/preview.png`;
  $("instanceControls").classList.remove("deployment-hidden");
  $("instanceMessage").textContent = `当前地图：${map.label}`;
  renderProject(selectedProject);
}
async function loadProjects() {
  try {
    const data = await request("/api/deployments");
    $("projectList").innerHTML = data.projects.length
      ? data.projects
          .map(
            (item) =>
            `<div class="asset-row project-row"><div><b>${esc(item.name)}</b><small>${esc(item.id)} · ${item.map_count} 张地图 · 更新于 ${esc(item.updated_at)}</small></div><div class="project-row-actions"><button class="compact-action open-project" data-id="${esc(item.id)}" type="button">打开</button><span class="project-delete-slot"><button class="project-delete-button delete-project" data-id="${esc(item.id)}" data-name="${esc(item.name)}" type="button" aria-label="删除部署项目 ${esc(item.name)}"><svg class="project-delete-icon" viewBox="0 0 24 24" aria-hidden="true"><path class="project-delete-lid" d="M5 7h14M9 7V5h6v2"/><path d="M7 9l1 10h8l1-10M10 11v5M14 11v5"/></svg><span>删除</span></button></span></div></div>`,
          )
          .join("")
      : '<div class="page-empty">还没有部署项目。</div>';
    const session = readDeploymentSession();
    const restoredProject = session?.projectId
      ? data.projects.find((item) => item.id === session.projectId)
      : null;
    if (restoredProject && !selectedProject) {
      await openProject(restoredProject.id, { restoringSession: true });
    } else if (session?.projectId && !restoredProject) {
      clearDeploymentSession();
    }
  } catch (error) {
    $("projectList").innerHTML =
      `<div class="page-empty">读取失败：${esc(error.message)}</div>`;
  }
}
async function loadComponentSpeedDefaults() {
  const data = await request("/api/deployment-component-defaults");
  componentSpeedDefaults = data.component_speed_defaults || {};
}
async function openProject(id, { restoringSession = false } = {}) {
  const data = await request(`/api/deployments/${encodeURIComponent(id)}`);
  topology = null;
  if (!restoringSession) creatingAnotherProject = false;
  renderProject(data.project, { restoringSession });
  persistDeploymentSession();
  await refreshMappingStatus();
  await refreshTopology();
  await restoreTaskCompilerPreview(id);
}
async function saveCurrentDeploymentFlow() {
  if (!selectedProject || !validateFlow(deploymentFlow).valid) return;
  const button = $("saveDeploymentFlow");
  button.disabled = true;
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/deployment-flow`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ flow: deploymentFlow }),
      },
    );
    selectedProject = data.project;
    deploymentFlow = flowForProject(selectedProject);
    renderProject(selectedProject);
    topology = data.stage_plan;
    renderTopology();
    renderDeploymentGuide();
    note("deploymentFlowMessage", "部署流程已保存；地图阶段将按新顺序显示。");
    completeDeploymentTask("部署流程已保存，地图阶段已按新顺序刷新。");
  } catch (error) {
    note("deploymentFlowMessage", error.message, true);
    renderDeploymentFlowEditor();
  }
}
$("saveDeploymentFlow").addEventListener("click", saveCurrentDeploymentFlow);
$("deploymentFlowPalette").addEventListener("click", (event) => {
  const button = event.target.closest("[data-flow-add]");
  if (!button) return;
  const node = createFlowNode(button.dataset.flowAdd, deploymentFlow);
  if (!node) return;
  if (node.type === "target_floor") deploymentFlow.push(node);
  else {
    const targetIndex = deploymentFlow.findIndex((item) => item.type === "target_floor");
    deploymentFlow.splice(targetIndex >= 0 ? targetIndex : deploymentFlow.length, 0, node);
  }
  renderDeploymentFlowEditor();
});
async function prepareMappingSession() {
  if (!selectedProject) return;
  const foreignActiveSession = mappingSession &&
    mappingSession.project_id !== selectedProject.id &&
    ["prepared", "running", "stopping"].includes(mappingSession.state);
  if (foreignActiveSession) {
    note("mappingMessage", `请先处理项目“${mappingSession.project_id}”的活动建图会话，当前项目不会重复创建。`, true);
    focusGuideTarget("mappingMessage");
    return;
  }
  try {
    const data = await request("/api/mapping/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: selectedProject.id,
        template_id: mappingTemplate?.id,
        label: $("mappingLabel").value,
        // 建图会话只负责产出地图；地图用途统一在“部署拓扑位置”中设置。
        kind: "custom",
      }),
    });
    mappingSession = data.session;
    renderMappingStatus();
    renderDeploymentTaskConsole();
    completeDeploymentTask("建图会话已准备完成，可以进入建图工作台。");
  } catch (error) {
    note("mappingMessage", error.message, true);
  }
}
$("prepareMapping").addEventListener("click", prepareMappingSession);
$("mappingTemplateFile").addEventListener("change", async () => {
  const file = $("mappingTemplateFile").files?.[0];
  if (!file || !selectedProject) return;
  try {
    $("mappingTemplateMessage").textContent = "正在保存 YAML 工作区副本…";
    const form = new FormData();
    form.append("template", file, file.name);
    const response = await fetch(`/api/deployments/${encodeURIComponent(selectedProject.id)}/mapping-template`, {
      method: "POST", body: form, cache: "no-store",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `模板上传失败（${response.status}）`);
    mappingTemplate = data.template;
    $("mappingTemplateMessage").textContent = `已保存副本：${mappingTemplate.name}。不会修改小车原配置。`;
    renderMappingStatus();
  } catch (error) {
    mappingTemplate = null;
    $("mappingTemplateMessage").textContent = error.message;
    $("mappingTemplateMessage").classList.add("error");
    renderMappingStatus();
  }
});
$("localizationTemplateFile").addEventListener("change", async () => {
  const file = $("localizationTemplateFile").files?.[0];
  if (!file || !selectedProject) return;
  try {
    $("localizationTemplateMessage").textContent = "正在保存定位配置模板…";
    const form = new FormData();
    form.append("template", file, file.name);
    const response = await fetch(`/api/deployments/${encodeURIComponent(selectedProject.id)}/localization-template`, {
      method: "POST", body: form, cache: "no-store",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `模板上传失败（${response.status}）`);
    renderProject(data.project);
  } catch (error) {
    $("localizationTemplateMessage").textContent = error.message;
    $("localizationTemplateMessage").classList.add("error");
  }
});
$("openMappingWorkbench").addEventListener("click", () => {
  if (mappingSession && ["prepared", "running"].includes(mappingSession.state)) {
    window.location.assign("/mapping-workbench.html");
  }
});
$("discardMapping").addEventListener("click", async () => {
  if (!mappingSession) return;
  try {
    const data = await request(
      `/api/mapping/sessions/${encodeURIComponent(mappingSession.id)}/discard`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
    );
    mappingSession = null;
    renderMappingStatus();
    note("mappingMessage", `已放弃会话“${data.session.label}”；没有修改地图、YAML 或车端配置。`);
  } catch (error) {
    note("mappingMessage", error.message, true);
  }
});
async function createDeploymentProject() {
  try {
    const data = await request("/api/deployments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: $("projectName").value,
        task_mode: $("projectTaskMode").value,
      }),
    });
    $("projectName").value = "";
    topology = null;
    renderProject(data.project);
    note("projectMessage", "部署项目已创建。");
    await loadProjects();
    await refreshMappingStatus();
    await refreshTopology();
    completeDeploymentTask("部署项目已创建；下一步配置现场地图流程。");
  } catch (error) {
    note("projectMessage", error.message, true);
  }
}
$("createProject").addEventListener("click", createDeploymentProject);
function revealNewProjectForm() {
  $("newProjectForm").classList.remove("deployment-hidden");
  $("currentProjectCard").classList.add("deployment-hidden");
  $("projectName").focus();
}
function startAnotherDeploymentProject() {
  if (!selectedProject) return;
  creatingAnotherProject = true;
  viewedDeploymentStage = null;
  editingDeploymentStage = null;
  deploymentTaskDraft = {
    mapSource: null,
    fileSummary: null,
    mapLabel: "",
    latestCreatedMapId: null,
    receipt: null,
  };
  persistDeploymentSession();
  renderDeploymentGuide();
  revealNewProjectForm();
  note("projectMessage", `“${selectedProject.name}”已保留。填写新项目后才会切换。`);
}
$("showNewProjectForm").addEventListener("click", startAnotherDeploymentProject);
$("startAnotherDeployment").addEventListener("click", startAnotherDeploymentProject);
function renderMapFolderSelection(files) {
  const manifest = $("mapFolderManifest");
  const importButton = $("importMap");
  const entries = files.map((file) => {
    const name = (file.webkitRelativePath || file.name).split("/").at(-1);
    const lower = name.toLowerCase();
    const type = lower === "map.yaml"
      ? "yaml"
      : lower.endsWith(".pgm")
        ? "pgm"
        : lower.endsWith(".pcd")
          ? "pcd"
          : lower === "index.txt"
            ? "index"
            : "other";
    return { name, type };
  });
  const counts = entries.reduce((result, item) => ({ ...result, [item.type]: (result[item.type] || 0) + 1 }), {});
  const yamlCount = counts.yaml || 0;
  const pgmCount = counts.pgm || 0;
  const pcdCount = counts.pcd || 0;
  const indexCount = counts.index || 0;
  const rows = [
    ["YAML", yamlCount, yamlCount === 1 ? "可用" : "需要 1 个 map.yaml"],
    ["PGM", pgmCount, pgmCount ? "已选择" : "必须选择 YAML 引用的 PGM"],
    ["PCD", pcdCount, pcdCount ? "定位点云已发现" : "可选；定位导出阶段需要至少 1 个有效 PCD"],
    ["index.txt", indexCount, indexCount ? "兼容文件会原样保留" : "可选，不影响导入"],
  ];
  manifest.innerHTML = rows.map(([label, count, detail]) => `<div class="map-folder-manifest-row ${((label === "YAML" && yamlCount !== 1) || (label === "PGM" && pgmCount < 1)) ? "invalid" : ""}"><span>${label}</span><b>${count}</b><small>${detail}</small></div>`).join("");
  importButton.disabled = !selectedProject || yamlCount !== 1 || pgmCount < 1;
  if (!files.length) {
    manifest.textContent = "选择文件后，这里会显示 YAML、PGM、PCD 和可选兼容文件的清单。";
    importButton.disabled = true;
  }
  return { yamlCount, pgmCount, pcdCount, indexCount };
}
async function importSelectedMap() {
  if (!selectedProject) return;
  const files = Array.from($("mapFolder").files || []);
  const candidates = files.filter((file) => (file.webkitRelativePath || file.name).split("/").pop().toLowerCase() === "map.yaml");
  if (candidates.length !== 1) {
    note("importMessage", "请同时选择一个 map.yaml 与其对应的 PGM 文件。", true);
    return;
  }
  try {
    note("importMessage", "正在上传、校验并复制地图快照…");
    const payload = new FormData();
    payload.append("map_yaml", candidates[0].webkitRelativePath || candidates[0].name);
    payload.append("label", $("mapLabel").value);
    // 地图用途只在“部署拓扑位置”中设置，导入时不重复填写类型。
    payload.append("kind", "custom");
    files.forEach((file) => payload.append("files", file, file.webkitRelativePath || file.name));
    const data = await new Promise((resolve, reject) => {
      const upload = new XMLHttpRequest();
      upload.open("POST", `/api/deployments/${encodeURIComponent(selectedProject.id)}/maps/upload`);
      upload.timeout = 300000;
      upload.upload.onprogress = (event) => {
        if (event.lengthComputable) note("importMessage", `正在上传地图：${Math.round(event.loaded / event.total * 100)}%`);
      };
      upload.onerror = () => reject(new Error("地图上传连接中断，未确认导入。"));
      upload.onabort = () => reject(new Error("地图上传已取消，未确认导入。"));
      upload.ontimeout = () => reject(new Error("地图上传超时，未确认导入；请检查连接后重试。"));
      upload.onload = () => {
        let response;
        try {
          response = JSON.parse(upload.responseText || "{}");
        } catch {
          reject(new Error("地图导入返回了无法解析的数据，未确认导入。"));
          return;
        }
        if (upload.status >= 200 && upload.status < 300) resolve(response);
        else reject(new Error(response.error || `地图导入失败（HTTP ${upload.status}）`));
      };
      upload.send(payload);
    });
    deploymentTaskDraft = nextMapImportDraft();
    $("mapLabel").value = "";
    renderProject(data.project);
    const createdMap = (data.project.map_assets || []).find((item) => item.id === data.map.id);
    if (createdMap) selectMap(createdMap);
    await refreshTopology();
    $("mapFolder").value = "";
    renderMapFolderSelection([]);
    note("importMessage", `已导入 ${data.map.label}；机器人原地图未被修改。`);
    deploymentTaskDraft.receipt = {
      taskId: "maps.describe",
      message: `${data.map.label} 已导入并通过校验。`,
    };
    completeDeploymentTask(`${data.map.label} 已导入并通过校验。`);
    await loadProjects();
  } catch (error) {
    note("importMessage", error.message, true);
  }
}
$("importMap").addEventListener("click", importSelectedMap);
$("mapFolder").addEventListener("change", () => {
  const files = Array.from($("mapFolder").files || []);
  const summary = renderMapFolderSelection(files);
  const mapYaml = files.filter((file) => (file.webkitRelativePath || file.name).split("/").pop().toLowerCase() === "map.yaml");
  if (mapYaml.length === 1) {
    const relative = mapYaml[0].webkitRelativePath || mapYaml[0].name;
    const name = relative.split("/").slice(0, -1).join(" / ");
    if (!$("mapLabel").value.trim()) $("mapLabel").value = name;
    deploymentTaskDraft.mapLabel = $("mapLabel").value;
    note("mapFolderMessage", summary.pgmCount
      ? `已选择 ${files.length} 个文件，将使用 ${relative}。${summary.pcdCount ? `已发现 ${summary.pcdCount} 个 PCD。` : "定位导出时请准备至少一个 PCD。"}`
      : `已选择 ${files.length} 个文件，但缺少 YAML 引用的 PGM。`, !summary.pgmCount);
  } else {
    note("mapFolderMessage", `已选择 ${files.length} 个文件；需要且只能包含一个 map.yaml。`, true);
  }
  deploymentTaskDraft.fileSummary = {
    ...summary,
    valid: summary.yamlCount === 1 && summary.pgmCount > 0,
  };
  persistDeploymentSession();
  renderDeploymentTaskConsole();
  focusCurrentTaskHeading();
});
$("mapLabel").addEventListener("input", () => {
  deploymentTaskDraft.mapLabel = $("mapLabel").value;
  persistDeploymentSession();
});
$("mapSourceChoices").addEventListener("change", (event) => {
  const source = event.target.closest("[data-map-source]")?.dataset.mapSource;
  if (!source) return;
  deploymentTaskDraft = {
    ...deploymentTaskDraft,
    mapSource: source,
    fileSummary: null,
    latestCreatedMapId: null,
    receipt: null,
  };
  persistDeploymentSession();
  renderDeploymentTaskConsole();
  focusCurrentTaskHeading();
});
$("addProtocol").addEventListener("click", async () => {
  if (!selectedProject) return;
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/component-templates`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "add",
          category: $("protocolCategory").value,
          label: $("protocolLabel").value,
        }),
      },
    );
    $("protocolLabel").value = "";
    renderProject(data.project);
    note("protocolMessage", "通信协议模板已更新。");
    completeDeploymentEdit("通信协议模板已更新，已返回当前任务。");
  } catch (error) {
    note("protocolMessage", error.message, true);
  }
});
document.addEventListener("click", (event) => {
  const button = event.target.closest(".open-project");
  if (button) {
    activeMap = null;
    mapImage = null;
    openProject(button.dataset.id).catch((error) =>
      note("projectMessage", error.message, true),
    );
  }
});
document.addEventListener("click", async (event) => {
  const button = event.target.closest(".delete-project");
  if (!button) return;
  event.preventDefault();
  event.stopPropagation();
  const projectId = button.dataset.id;
  const projectName = button.dataset.name || projectId;
  if (!window.confirm(`确认删除部署项目“${projectName}”？\n\n项目内地图快照、点位和配置将一并删除，无法恢复。`)) return;
  button.disabled = true;
  try {
    await request(`/api/deployments/${encodeURIComponent(projectId)}`, { method: "DELETE" });
    if (selectedProject?.id === projectId) {
      clearDeploymentSession();
      window.location.reload();
      return;
    }
    await loadProjects();
    note("projectMessage", "部署项目已删除。");
  } catch (error) {
    button.disabled = false;
    note("projectMessage", error.message, true);
  }
});
document.addEventListener("click", (event) => {
  const button = event.target.closest(".delete-protocol");
  if (!button || !selectedProject) return;
  request(
    `/api/deployments/${encodeURIComponent(selectedProject.id)}/component-templates`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "remove",
        category: button.dataset.category,
        protocol_id: button.dataset.protocolId,
      }),
    },
  )
    .then((data) => {
      renderProject(data.project);
      note("protocolMessage", "通信协议模板已更新。");
      completeDeploymentEdit("通信协议模板已更新，已返回当前任务。");
    })
    .catch((error) => note("protocolMessage", error.message, true));
});
document.addEventListener("click", (event) => {
  const card = event.target.closest(".deployment-map");
  if (!card || !selectedProject) return;
  const map = selectedProject.map_assets.find(
    (item) => item.id === card.dataset.mapId,
  );
  if (map && map.id !== activeMap?.id) selectMap(map);
});
$("resetMapView").addEventListener("click", fitMap);
$("panTool").addEventListener("click", () => setTool("pan"));
document
  .querySelectorAll(".waypoint-tool")
  .forEach((button) =>
    button.addEventListener("click", () =>
      setTool(button.dataset.waypointKind),
    ),
  );
function setTool(tool) {
  activeTool = tool;
  if (tool !== "erase_brush") eraserHoverPoint = null;
  const isBrush = tool === "erase_brush";
  const isPolygon = tool === "erase_polygon";
  $("eraserSizeControl").classList.toggle("deployment-hidden", !isBrush);
  $("completeErasePolygon").classList.toggle("deployment-hidden", !isPolygon);
  document
    .querySelectorAll(".waypoint-tool,#panTool")
    .forEach((item) =>
      item.classList.toggle(
        "active-tool",
        item === $("panTool")
          ? tool === "pan"
          : item.dataset.waypointKind === tool,
      ),
    );
  $("mapToolHint").textContent =
    tool === "pan"
      ? "选择模式：拖动画布平移；左键拖动组件移动，滚轮或双指缩放。"
      : tool === "virtual_wall"
        ? "虚拟墙：左键连续加点；双击或 Enter 完成。红线顶点可拖动，拖线段可整体移动，选中后按 Delete 删除。"
      : isBrush
        ? "橡皮擦：左键实时擦除；滚轮调节直径，Ctrl + 滚轮缩放；中键或空格可平移。"
        : isPolygon
          ? "框选擦除：左键逐点勾勒任意区域，至少三个点后点击“完成框选”。"
          : `一次放置：点击地图空白处添加${COMPONENT_SPECS[tool]?.name || tool}；放置后会自动回到选择模式。`;
}
async function commitMapEdit(payload, successMessage) {
  if (!selectedProject || !activeMap) return;
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/map-edits`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ map_id: activeMap.id, ...payload }),
      },
    );
    renderProject(data.project);
    note("mapToolHint", successMessage);
    keepMapAnnotationOpen(`${successMessage}；请继续检查当前地图，完成后再确认进入定位路线。`) ||
      completeDeploymentEdit(`${successMessage} 已返回当前任务。`);
  } catch (error) {
    note("mapToolHint", error.message, true);
  }
}
function setEraserDiameter(value) {
  eraserDiameterM = Math.max(0.1, Math.min(8, Math.round(value * 10) / 10));
  $("eraserDiameterValue").textContent = `${eraserDiameterM.toFixed(1)} m`;
  $("eraserButtonSize").textContent = `${eraserDiameterM.toFixed(1)} m`;
  scheduleMapDraw();
}
function setEraserShape(shape) {
  eraserShape = shape;
  $("eraserCircle").classList.toggle("active", shape === "circle");
  $("eraserSquare").classList.toggle("active", shape === "square");
  scheduleMapDraw();
}
$("eraserCircle").addEventListener("click", () => setEraserShape("circle"));
$("eraserSquare").addEventListener("click", () => setEraserShape("square"));
$("completeErasePolygon").addEventListener("click", async () => {
  if (polygonEraseDraft.length < 3) {
    note("mapToolHint", "框选擦除至少需要三个顶点。", true);
    return;
  }
  const points = polygonEraseDraft;
  polygonEraseDraft = [];
  drawMap();
  await commitMapEdit(
    { action: "add", kind: "polygon_erase", points },
    "不规则擦除区域已保存到项目地图编辑层。",
  );
});
$("undoMapEdit").addEventListener("click", async () => {
  if (polygonEraseDraft.length) {
    polygonEraseDraft.pop();
    drawMap();
    note("mapToolHint", "已移除框选的最后一个顶点。");
    return;
  }
  await commitMapEdit({ action: "undo" }, "已撤销当前地图最近一次擦除。");
});
$("clearMapEdits").addEventListener("click", async () => {
  if (!activeMap || !selectedProject) return;
  if (!window.confirm("清空当前地图的全部擦除记录？原始导入地图不会被修改。"))
    return;
  polygonEraseDraft = [];
  await commitMapEdit({ action: "clear" }, "已清空当前地图的擦除记录。");
});
function selectComponent(component) {
  selectedComponent = component;
  if (component) {
    $("componentSizeReadout").textContent =
      `${Number(component.attributes?.width_m ?? 0.8).toFixed(2)} m × ${Number(component.attributes?.height_m ?? 0.8).toFixed(2)} m`;
    $("componentYaw").value = component.yaw ?? 0;
    renderComponentAttributes(component);
  }
  drawMap();
}
function renderComponentAttributes(component) {
  const spec = COMPONENT_SPECS[component.kind] || { fields: [] };
  const attributes = component.attributes || {};
  const isAccessBarrier = ["gate", "auto_door"].includes(component.kind);
  $("componentDirectionHint").classList.toggle("deployment-hidden", !isAccessBarrier);
  $("componentPopoverTitle").textContent =
    `${componentName(component)} · 快捷编辑`;
  const controls = spec.fields
    .map((field) => {
      const value = attributes[field.key] ?? field.default ?? "";
      if (field.type === "select") {
        const options = field.protocolCategory
          ? protocolOptions(selectedProject, field.protocolCategory)
          : field.options;
        return `<label>${esc(field.label)}<select data-component-attribute="${esc(field.key)}">${options.map(([option, title]) => `<option value="${esc(option)}" ${String(value) === option ? "selected" : ""}>${esc(title)}</option>`).join("")}</select></label>`;
      }
      return `<label>${esc(field.label)}<input data-component-attribute="${esc(field.key)}" type="${esc(field.type)}" value="${esc(value)}" ${field.placeholder ? `placeholder="${esc(field.placeholder)}"` : ""} ${field.inputMode ? `inputmode="${esc(field.inputMode)}"` : ""} ${field.pattern ? `pattern="${esc(field.pattern)}"` : ""} ${field.required ? "required" : ""} ${field.min ? `min="${esc(field.min)}"` : ""} ${field.max ? `max="${esc(field.max)}"` : ""} ${field.step ? `step="${esc(field.step)}"` : ""} /></label>`;
    })
    .join("");
  const configuredSpeed = componentSpeedDefaults[component.kind]?.locked
    ? componentSpeedDefaults[component.kind]?.speed_profile
    : null;
  const speedLabels = {
    task_point: "任务点",
    single_point: "常规",
    slow_point: "减速",
    narrow_point: "窄通道",
  };
  const fixedSpeedControl = configuredSpeed
    ? `<label>速度模式<output class="component-fixed-value">${esc(speedLabels[configuredSpeed] || configuredSpeed)} · 只读</output></label>`
    : "";
  const sharedElevator = physicalElevatorFor(component);
  const mapInstance = mapInstanceFor(component.map_asset_id);
  const sharedContext =
    component.kind === "elevator"
      ? sharedElevator
        ? `<div class="physical-floor"><span>关联物理电梯 · ${esc(sharedElevator.elevator_id)}</span><strong>${esc(protocolTitle(selectedProject, sharedElevator.elevator_protocol))} · ${esc(sharedElevator.min_floor)}F 至 ${esc(sharedElevator.max_floor)}F</strong><small>本地图电梯按钮层：${esc(component.attributes?.button_floor ?? "未填写")}。物理层由服务端按按钮序列推导，按钮 0 不参与编号。</small><button class="compact-action edit-shared-elevator" type="button" data-physical-elevator-id="${esc(sharedElevator.id)}">编辑共享电梯</button></div>`
        : '<p class="component-no-options">此电梯落点缺少共享电梯关联；请删除后重新关联。</p>'
      : "";
  $("componentAttributeFields").innerHTML =
    `${sharedContext}${controls}${fixedSpeedControl}` ||
    '<p class="component-no-options">此组件暂没有附加部署属性。</p>';
}
function closeComponentPopover() {
  $("componentPopover").classList.add("deployment-hidden");
}
function closeWaypointPopover() {
  selectedWaypoint = null;
  $("waypointPopover").classList.add("deployment-hidden");
}
function openWaypointPopover(waypoint, event) {
  selectedWaypoint = waypoint;
  const popover = $("waypointPopover");
  note("waypointPopoverStatus", "");
  $("waypointPopoverTitle").textContent = waypoint.label || "地图标记";
  const waypointKindLabel = waypoint.kind === "transition" ? "过渡点" : waypoint.kind;
  $("waypointPopoverDetail").textContent = `${waypointKindLabel} · x ${Number(waypoint.x).toFixed(2)} · y ${Number(waypoint.y).toFixed(2)} · yaw ${Number(waypoint.yaw || 0).toFixed(2)}`;
  const isTaskTransition = waypoint.kind === "transition" && !waypoint.generated_by;
  const transitionRole = isTaskTransition ? taskTransitionRole(waypoint.map_asset_id) : null;
  const appearsInTask = Boolean(transitionRole);
  $("transitionSpeedControl").classList.toggle("deployment-hidden", !appearsInTask);
  $("transitionYawControl").classList.toggle("deployment-hidden", !appearsInTask);
  $("transitionReturnDirectionHint").classList.toggle("deployment-hidden", !appearsInTask);
  $("saveWaypointTransitionSpeed").classList.toggle("deployment-hidden", !appearsInTask);
  $("waypointTransitionSpeed").value = waypoint.speed_mode || "single_point";
  syncTransitionYawControl(waypoint);
 $("waypointPopoverPurpose").textContent = appearsInTask
    ? `${transitionRole === "lobby" ? "电梯大厅" : "用户楼层"}任务过渡点会自动纳入去程；系统会按当前地图标记自动派生它在去程中的位置，返程严格按该链反向经过。实线箭头表示去程，虚线箭头表示自动反向的返程。拖动蓝色圆形方向手柄即可调整去程朝向；它不生成行为树。`
    : isTaskTransition
      ? "这是定位路线的过渡锚点。当前实验任务只会编译用户楼层地图上的任务过渡点，因此它不会写入配送任务 JSON。"
    : "删除后系统会根据剩余地图标记重新派生路线；缺少起点、目标或电梯等核心标记时会明确提示补齐。";
  closeComponentPopover();
  popover.classList.remove("deployment-hidden");
  const workspace = $("mapWorkspace");
  const width = popover.offsetWidth;
  const height = popover.offsetHeight;
  const x = event.clientX - workspace.getBoundingClientRect().left;
  const y = event.clientY - workspace.getBoundingClientRect().top;
  popover.style.left = `${Math.max(12, Math.min(x + 14, workspace.clientWidth - width - 12))}px`;
  popover.style.top = `${Math.max(12, Math.min(y + 14, workspace.clientHeight - height - 12))}px`;
  drawMap();
}
function elevatorLandingMode() {
  return document.querySelector('input[name="elevatorLandingMode"]:checked')?.value || "existing";
}
function unavailableElevatorButtons(elevator) {
  return Array.isArray(elevator?.unavailable_button_floors)
    ? elevator.unavailable_button_floors.map(Number).filter(Number.isInteger)
    : [];
}
function parseUnavailableElevatorButtons() {
  const raw = $("newPhysicalElevatorUnavailableButtons").value.trim();
  if (!raw) return [];
  const values = raw.split(/[，,、]/).map((value) => value.trim());
  if (values.some((value) => !/^-?\d+$/.test(value))) {
    throw new Error("缺失按键请填写整数；多个按键请用逗号分隔。");
  }
  return values.map(Number);
}
function renderElevatorLandingDialog() {
  const elevators = physicalElevators();
  const editing = Boolean(elevatorLandingDraft?.editing);
  const editingElevator = editing
    ? elevators.find((item) => item.id === elevatorLandingDraft.physicalElevatorId)
    : null;
  const existing = $("existingPhysicalElevator");
  const previous = existing.value;
  existing.innerHTML = elevators.length
    ? elevators
        .map(
          (item) =>
            `<option value="${esc(item.id)}">${esc(item.elevator_id)} · ${esc(protocolTitle(selectedProject, item.elevator_protocol))}</option>`,
        )
        .join("")
    : '<option value="">当前项目还没有物理电梯</option>';
  if (elevators.some((item) => item.id === previous)) existing.value = previous;
  const protocol = $("newPhysicalElevatorProtocol");
  const previousProtocol = protocol.value;
  protocol.innerHTML = protocolOptions(selectedProject, "elevator_protocols")
    .map(([id, label]) => `<option value="${esc(id)}">${esc(label)}</option>`)
    .join("");
  if (protocolOptions(selectedProject, "elevator_protocols").some(([id]) => id === previousProtocol)) {
    protocol.value = previousProtocol;
  }
  if (editingElevator) {
    $("newPhysicalElevatorNumber").value = editingElevator.elevator_id;
    protocol.value = editingElevator.elevator_protocol;
    $("newPhysicalElevatorMinFloor").value = editingElevator.min_floor;
    $("newPhysicalElevatorMaxFloor").value = editingElevator.max_floor;
    $("newPhysicalElevatorUnavailableButtons").value = unavailableElevatorButtons(editingElevator).join(", ");
  }
  const existingRadio = document.querySelector('input[name="elevatorLandingMode"][value="existing"]');
  existingRadio.disabled = !elevators.length;
  if (!elevators.length) {
    document.querySelector('input[name="elevatorLandingMode"][value="new"]').checked = true;
  }
  const linked = elevators.find((item) => item.id === existing.value);
  $("existingPhysicalElevatorSummary").textContent = linked
    ? `编号 ${linked.elevator_id} · ${protocolTitle(selectedProject, linked.elevator_protocol)} · 服务 ${linked.min_floor}F 至 ${linked.max_floor}F${unavailableElevatorButtons(linked).length ? ` · 缺失按键 ${unavailableElevatorButtons(linked).join("、")}` : ""}。各楼层分别确认门方向。`
    : "请先新建一部物理电梯，再在其他楼层关联它。";
  const isNew = editing || elevatorLandingMode() === "new";
  const showLocalButtonFloor = !editing;
  $("elevatorLandingDialogTitle").textContent = editing ? "编辑共享电梯" : "放置电梯落点";
  $("elevatorLandingDialogDescription").textContent = editing
    ? "这里只编辑实体电梯的共享属性；当前地图的按钮层、门向和候梯距离请在右侧组件面板维护。"
    : "先关联或新建共享电梯，再填写当前地图的实际面板按键层。";
  $("elevatorLandingDialog").querySelector(".elevator-landing-mode").classList.toggle("deployment-hidden", editing);
  $("existingElevatorLandingFields").classList.toggle("deployment-hidden", isNew);
  $("newElevatorLandingFields").classList.toggle("deployment-hidden", !isNew);
  $("elevatorLandingButtonFloorField").classList.toggle("deployment-hidden", !showLocalButtonFloor);
  $("elevatorLandingButtonFloorLabel").textContent = activeMap?.label
    ? `当前地图“${activeMap.label}”的电梯面板按键层`
    : "本地图电梯按钮层";
  $("confirmElevatorLanding").textContent = editing ? "保存共享配置" : "确认放置";
  $("confirmElevatorLanding").disabled = !elevatorLandingDraft || (!isNew && !linked);
  $("elevatorLandingMessage").textContent = isNew
    ? editing
      ? "修改后会同步应用到该物理电梯的所有地图落点；不能把已有落点设置为缺失按键。"
      : "共享编号、协议、服务范围和缺失按键只在这里填写一次。"
    : "当前地图将保存独立的电梯门方向、尺寸和候梯距离。";
}
function openElevatorLandingDialog(point) {
  elevatorLandingDraft = { point };
  $("elevatorLandingButtonFloor").value = "";
  $("newPhysicalElevatorUnavailableButtons").value = "";
  $("elevatorLandingDialog").classList.remove("deployment-hidden");
  renderElevatorLandingDialog();
  $(elevatorLandingMode() === "new" ? "newPhysicalElevatorNumber" : "existingPhysicalElevator").focus();
}
function closeElevatorLandingDialog() {
  elevatorLandingDraft = null;
  $("elevatorLandingDialog").classList.add("deployment-hidden");
}
function openPhysicalElevatorEditor(physicalElevatorId) {
  if (!physicalElevators().some((item) => item.id === physicalElevatorId)) return;
  elevatorLandingDraft = { editing: true, physicalElevatorId };
  $("elevatorLandingDialog").classList.remove("deployment-hidden");
  renderElevatorLandingDialog();
  $("newPhysicalElevatorNumber").focus();
}
async function confirmElevatorLanding() {
  if (!selectedProject || !activeMap || !elevatorLandingDraft) return;
  const button = $("confirmElevatorLanding");
  button.disabled = true;
  try {
    if (elevatorLandingDraft.editing) {
      const data = await request(
        `/api/deployments/${encodeURIComponent(selectedProject.id)}/physical-elevators/${encodeURIComponent(elevatorLandingDraft.physicalElevatorId)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            elevator_id: $("newPhysicalElevatorNumber").value,
            elevator_protocol: $("newPhysicalElevatorProtocol").value,
            min_floor: Number($("newPhysicalElevatorMinFloor").value),
            max_floor: Number($("newPhysicalElevatorMaxFloor").value),
            unavailable_button_floors: parseUnavailableElevatorButtons(),
          }),
        },
      );
      renderProject(data.project);
      const component = data.project.components.find((item) => item.id === selectedComponent?.id);
      if (component) selectComponent(component);
      closeElevatorLandingDialog();
      note("mapToolHint", "共享电梯配置已更新；所有关联地图均使用新的协议和服务楼层。");
      completeDeploymentEdit("共享电梯配置已更新，已返回当前任务。");
      return;
    }
    const buttonFloor = Number($("elevatorLandingButtonFloor").value);
    if (!Number.isInteger(buttonFloor)) {
      throw new Error("请填写本地图电梯按钮层");
    }
    let physicalElevatorId = $("existingPhysicalElevator").value;
    if (elevatorLandingMode() === "new") {
      const created = await request(
        `/api/deployments/${encodeURIComponent(selectedProject.id)}/physical-elevators`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            elevator_id: $("newPhysicalElevatorNumber").value,
            elevator_protocol: $("newPhysicalElevatorProtocol").value,
            min_floor: Number($("newPhysicalElevatorMinFloor").value),
            max_floor: Number($("newPhysicalElevatorMaxFloor").value),
            unavailable_button_floors: parseUnavailableElevatorButtons(),
          }),
        },
      );
      physicalElevatorId = created.physical_elevator.id;
      renderProject(created.project);
    }
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/components`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          map_id: activeMap.id,
          kind: "elevator",
          x: elevatorLandingDraft.point.x,
          y: elevatorLandingDraft.point.y,
          yaw: 0,
          attributes: { physical_elevator_id: physicalElevatorId, button_floor: buttonFloor },
        }),
      },
    );
    renderProject(data.project);
    selectComponent(data.component);
    closeElevatorLandingDialog();
    await refreshTopology();
    note("mapToolHint", "已放置电梯落点；可拖动、旋转门方向，或右键调整候梯距离。");
    keepMapAnnotationOpen("电梯落点已保存；请继续检查当前地图，完成后再确认进入定位路线。") ||
      completeDeploymentEdit("电梯落点已保存，已返回当前任务。");
  } catch (error) {
    note("elevatorLandingMessage", error.message, true);
  } finally {
    if (!$("elevatorLandingDialog").classList.contains("deployment-hidden")) {
      button.disabled = false;
    }
  }
}
document.querySelectorAll('input[name="elevatorLandingMode"]').forEach((input) => {
  input.addEventListener("change", renderElevatorLandingDialog);
});
$("existingPhysicalElevator").addEventListener("change", renderElevatorLandingDialog);
$("confirmElevatorLanding").addEventListener("click", confirmElevatorLanding);
$("cancelElevatorLanding").addEventListener("click", closeElevatorLandingDialog);
$("cancelElevatorLandingSecondary").addEventListener("click", closeElevatorLandingDialog);
$("openLocalizationBinding").addEventListener("click", () => openLocalizationBinding());
$("openLocalizationRoute").addEventListener("click", openSuggestedLocalizationRoute);
$("cancelLocalizationBinding").addEventListener("click", closeLocalizationBinding);
$("saveLocalizationBinding").addEventListener("click", saveLocalizationBinding);
$("deleteLocalizationBinding").addEventListener("click", deleteLocalizationBinding);
$("localizationBindingType").addEventListener("change", localizationTypeChanged);
$("cancelLocalizationRoute").addEventListener("click", closeLocalizationRoute);
$("saveLocalizationRoute").addEventListener("click", saveLocalizationRoute);
document.addEventListener("click", (event) => {
  const button = event.target.closest(".edit-localization-binding");
  if (button) openLocalizationBinding(localizationBindings().find((item) => item.id === button.dataset.bindingId));
  const routeButton = event.target.closest(".edit-localization-route");
  if (routeButton) openLocalizationRoute();
});
$("componentAttributeFields").addEventListener("click", (event) => {
  const button = event.target.closest(".edit-shared-elevator");
  if (button) openPhysicalElevatorEditor(button.dataset.physicalElevatorId);
});
function openComponentPopover(component, event) {
  selectComponent(component);
  const popover = $("componentPopover");
  note("componentPopoverStatus", "");
  const workspace = $("mapWorkspace");
  popover.classList.remove("deployment-hidden");
  const width = popover.offsetWidth;
  const height = popover.offsetHeight;
  const workspaceBox = workspace.getBoundingClientRect();
  const x = event.clientX - workspaceBox.left;
  const y = event.clientY - workspaceBox.top;
  popover.style.left = `${Math.max(12, Math.min(x + 14, workspace.clientWidth - width - 12))}px`;
  popover.style.top = `${Math.max(12, Math.min(y + 14, workspace.clientHeight - height - 12))}px`;
}
function componentAt(event) {
  if (!activeMap) return null;
  const pointer = canvasPointFromEvent(event);
  return (selectedProject?.components || [])
    .filter((item) => item.map_asset_id === activeMap.id)
    .reverse()
    .find((item) => isComponentHit(item, pointer, activeMap, mapView));
}

function waypointAt(event) {
  if (!activeMap) return null;
  const pointer = canvasPointFromEvent(event);
  return (selectedProject?.waypoints || [])
    .filter((item) => item.map_asset_id === activeMap.id && !item.generated_by)
    .map((item) => ({ item, point: worldCanvasPoint(item) }))
    .filter(({ point }) => Math.hypot(pointer.x - point.x, pointer.y - point.y) <= 14)
    .sort((left, right) => Math.hypot(pointer.x - left.point.x, pointer.y - left.point.y) - Math.hypot(pointer.x - right.point.x, pointer.y - right.point.y))[0]?.item || null;
}

async function selectTopologyWaypoint(waypoint) {
  if (!selectedProject || !activeMap || !waypoint) return;
  if (activeTool === "route_link") {
    if (routeDraft.includes(waypoint.id)) {
      note("mapToolHint", "该 Waypoint 已在当前路线中；请选择下一个点。", true);
      return;
    }
    routeDraft.push(waypoint.id);
    renderTopology();
    drawMap();
    note("mapToolHint", `已加入路线：${waypoint.label}。继续选择，或保存当前路线。`);
    return;
  }
}
function resizeHandleAt(event) {
  if (!selectedComponent || selectedComponent.map_asset_id !== activeMap?.id)
    return false;
  return isResizeHandleHit(
    selectedComponent,
    canvasPointFromEvent(event),
    activeMap,
    mapView,
  );
}
function rotateHandleAt(event) {
  if (!selectedComponent || selectedComponent.map_asset_id !== activeMap?.id)
    return false;
  return isRotateHandleHit(
    selectedComponent,
    canvasPointFromEvent(event),
    activeMap,
    mapView,
  );
}
function transitionRotateHandleAt(event) {
  if (
    !selectedWaypoint ||
    selectedWaypoint.map_asset_id !== activeMap?.id ||
    selectedWaypoint.kind !== "transition" ||
    !taskTransitionRole(selectedWaypoint.map_asset_id)
  ) return false;
  const pointer = canvasPointFromEvent(event);
  const handle = transitionDirectionHandlePoint(selectedWaypoint);
  return Math.hypot(pointer.x - handle.x, pointer.y - handle.y) <= 14;
}
$("saveComponent").addEventListener("click", async () => {
  if (!selectedComponent || !selectedProject) return;
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/components/${encodeURIComponent(selectedComponent.id)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          x: selectedComponent.x,
          y: selectedComponent.y,
          yaw: $("componentYaw").value,
          attributes: {
            ...selectedComponent.attributes,
            ...Object.fromEntries(
              [...document.querySelectorAll("[data-component-attribute]")].map(
                (input) => [
                  input.dataset.componentAttribute,
                  input.type === "number" ? Number(input.value) : input.value,
                ],
              ),
            ),
          },
        }),
      },
    );
    const updated = data.project.components.find(
      (item) => item.id === selectedComponent.id,
    );
    selectedComponent = updated;
    renderProject(data.project);
    selectComponent(updated);
    keepMapAnnotationOpen("组件属性已保存；请继续检查当前地图，完成后再确认进入定位路线。") ||
      completeDeploymentEdit("组件属性已保存，已返回当前任务。");
  } catch (error) {
    note("mapToolHint", error.message, true);
  }
});
async function deleteSelectedMapAnnotation({
  annotation,
  collection,
  button,
  popoverStatusId,
  close,
}) {
  if (annotationDeleteInFlight || !annotation || !selectedProject) return;
  const projectId = selectedProject.id;
  const stableAnnotation = { id: annotation.id, label: annotation.label };
  const label = componentName(annotation) || annotation.label || "此标记";
  if (!window.confirm(`删除“${label}”？系统将立即按剩余标记重新计算路线。`)) return;
  annotationDeleteInFlight = true;
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "删除中…";
  try {
    await deleteDeploymentAnnotation({
      projectId,
      annotation: stableAnnotation,
      collection,
      request,
      refreshProject: openProject,
      notify: (message, error = false) => {
        note("mapToolHint", message, error);
        note(popoverStatusId, message, error);
      },
    });
    close();
    keepMapAnnotationOpen("标记已删除；系统已根据剩余标记重新计算路线，请继续检查当前地图。") ||
      completeDeploymentEdit("标记已删除，系统已重新计算路线并返回当前任务。");
  } catch {
    // The helper leaves a visible, retryable error in both the canvas hint
    // and this open popover.  Keep the selected item so the operator can retry.
  } finally {
    annotationDeleteInFlight = false;
    button.disabled = false;
    button.textContent = originalText;
  }
}
$("deleteComponent").addEventListener("click", () => {
  const component = selectedComponent;
  deleteSelectedMapAnnotation({
    annotation: component,
    collection: "components",
    button: $("deleteComponent"),
    popoverStatusId: "componentPopoverStatus",
    close: () => {
      selectComponent(null);
      closeComponentPopover();
    },
  });
});
$("deleteWaypoint").addEventListener("click", () => {
  const waypoint = selectedWaypoint;
  deleteSelectedMapAnnotation({
    annotation: waypoint,
    collection: "waypoints",
    button: $("deleteWaypoint"),
    popoverStatusId: "waypointPopoverStatus",
    close: closeWaypointPopover,
  });
});
$("saveWaypointTransitionSpeed").addEventListener("click", async () => {
  if (!selectedProject || !selectedWaypoint || selectedWaypoint.kind !== "transition") return;
  const yawDegrees = Number($("waypointTransitionYaw").value);
  if (!Number.isFinite(yawDegrees) || yawDegrees < -180 || yawDegrees > 180) {
    note("mapToolHint", "过渡点朝向请输入 -180 到 180 的数字。", true);
    return;
  }
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/waypoints/${encodeURIComponent(selectedWaypoint.id)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          speed_mode: $("waypointTransitionSpeed").value,
          yaw: yawDegrees * Math.PI / 180,
        }),
      },
    );
    renderProject(data.project);
    selectedWaypoint = data.waypoint;
    note("mapToolHint", `过渡点速度和去程朝向已保存；重新生成预览后会同步写入去程与返程任务 JSON。`);
    closeWaypointPopover();
  } catch (error) {
    note("mapToolHint", error.message, true);
  }
});
$("addInstance").addEventListener("click", async () => {
  if (!selectedProject || !activeMap) return;
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/map-instances`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          map_id: activeMap.id,
          role: $("instanceRole").value,
          building: $("instanceBuilding").value,
          unit: $("instanceUnit").value,
          label: activeMap.label,
        }),
      },
    );
    renderProject(data.project);
    note("instanceMessage", "地图实例已加入部署拓扑。");
    completeDeploymentEdit("地图实例已保存，已返回当前任务。") ||
      completeDeploymentTask("地图实例已保存；正在检查下一张地图的部署位置。");
  } catch (error) {
    note("instanceMessage", error.message, true);
  }
});
async function assignCurrentMapStage() {
  if (!selectedProject) return;
  const targetMapId = deploymentTask?.targetMapId || activeMap?.id || null;
  const targetStageId = deploymentTask?.targetStageId || $("mapStageAssignment").value || null;
  const targetMap = (selectedProject.map_assets || []).find((item) => item.id === targetMapId);
  if (!targetMapId || !targetStageId || !targetMap) {
    note("stageAssignmentMessage", "当前任务缺少可绑定的地图或部署阶段，请刷新项目后重试。", true);
    return;
  }
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/map-stages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          map_asset_id: targetMapId,
          stage: targetStageId,
        }),
      },
    );
    topology = { ...topology, stages: data.stage_plan.stages };
    renderProject(data.project);
    await refreshTopology();
    note("stageAssignmentMessage", "当前地图的部署阶段已保存。");
    deploymentTaskDraft = {
      mapSource: null,
      fileSummary: null,
      mapLabel: "",
      latestCreatedMapId: null,
      receipt: {
        taskId: "maps.assign",
        message: `${targetMap.label} 的地图阶段已保存。`,
      },
    };
    completeDeploymentTask(`${targetMap.label} 的地图阶段已保存。`);
  } catch (error) {
    note("stageAssignmentMessage", error.message, true);
  }
}
$("assignMapStage").addEventListener("click", assignCurrentMapStage);
$("saveTaskCompilerConfig").addEventListener("click", saveTaskCompilerConfig);
$("generateTaskCompilerPreview").addEventListener("click", refreshTaskCompilerPreview);
$("downloadTaskCompilerBundle").addEventListener("click", downloadTaskCompilerBundle);
async function runDeploymentTaskAction(actionId) {
  if (actionId === "request-stage-edit") {
    return openDeploymentEditImpact(deploymentTask?.stageId);
  }
  if (actionId === "createProject") {
    if (!$("projectName").value.trim()) return focusGuideTarget("projectName");
    return createDeploymentProject();
  }
  if (actionId === "confirmScene") {
    if ($("saveDeploymentFlow").disabled) return focusGuideTarget("deploymentFlowEditor");
    return saveCurrentDeploymentFlow();
  }
  if (actionId === "saveCompilerIdentity") {
    if (!$("taskCompilerCommunity").value.trim()) return focusGuideTarget("taskCompilerCommunity");
    return saveTaskCompilerConfig();
  }
  if (actionId === "bindLocalization" && !$("openLocalizationBinding").disabled) {
    return $("openLocalizationBinding").click();
  }
  if (actionId === "choose-map-source") return focusGuideTarget("mapSourceChoices");
  if (actionId === "configure-map-instance") return focusGuideTarget("instanceControls");
  if (actionId === "focus-mapping-conflict") return focusGuideTarget("mappingMessage");
  if (actionId === "select-map-files") return $("mapFolder").click();
  if (actionId === "import-map") return importSelectedMap();
  if (actionId === "prepare-mapping") return prepareMappingSession();
  if (actionId === "open-mapping-workbench") return $("openMappingWorkbench").click();
  if (actionId === "assign-map-stage") return assignCurrentMapStage();
  if (actionId === "preview") return refreshTaskCompilerPreview();
  if (actionId === "export") return downloadTaskCompilerBundle();
  return runDeploymentGuideAction(actionId);
}
$("deploymentTaskConsole").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-task-action]");
  if (!button || !deploymentTask) return;
  const actionId = button.dataset.taskAction;
  await taskActionGate.run(deploymentTask.id, async () => {
    deploymentTaskPending = deploymentTask.id;
    renderDeploymentTaskConsole();
    try {
      await runDeploymentTaskAction(actionId);
    } finally {
      deploymentTaskPending = null;
      renderDeploymentTaskConsole();
    }
  });
});
$("deploymentEditImpactDialog").addEventListener("click", (event) => {
  if (event.target.closest("#cancelDeploymentStageEdit")) {
    closeDeploymentEditImpact();
    return;
  }
  if (event.target.closest("#confirmDeploymentStageEdit")) {
    confirmDeploymentStageEdit();
  }
});
$("deploymentGuide").addEventListener("click", (event) => {
  const action = event.target.closest("[data-guide-action]");
  if (action) {
    runDeploymentGuideAction(action.dataset.guideAction);
    return;
  }
  const stepButton = event.target.closest("[data-guide-step]");
  if (stepButton) focusGuideStep(stepButton.dataset.guideStep);
});
let drag = null;
let componentDrag = null;
let componentResize = null;
let componentRotate = null;
let waypointRotate = null;
let componentPlacementPending = false;
function beginCanvasPan(event) {
  event.preventDefault();
  eraserHoverPoint = null;
  drag = {
    x: event.clientX,
    y: event.clientY,
    viewX: mapView.x,
    viewY: mapView.y,
  };
  canvas.setPointerCapture(event.pointerId);
  canvas.style.cursor = "grabbing";
}
function trackEraserStroke(events) {
  if (!eraserStroke || !activeMap) return false;
  let hasVisiblePoint = false;
  for (const event of events) {
    const point = worldPointFromEvent(event);
    if (!pointIsOnActiveMap(point)) {
      eraserHoverPoint = null;
      continue;
    }
    // The preview is the actual pointer position, not the last point that was
    // sampled into the stored stroke. This keeps the translucent brush locked
    // to the cursor even during very small, slow movements.
    eraserHoverPoint = point;
    hasVisiblePoint = true;
    const previous = eraserStroke.points.at(-1);
    if (
      !previous ||
      Math.hypot(point.x - previous.x, point.y - previous.y) >= 0.01
    ) {
      eraserStroke.points.push(point);
    }
  }
  return hasVisiblePoint;
}
canvas.addEventListener("pointerdown", async (event) => {
  if (taskPreviewOpen) {
    if (event.button === 0 || event.button === 1) beginCanvasPan(event);
    return;
  }
  if (event.button === 1 || (spacePanActive && event.button === 0)) {
    beginCanvasPan(event);
    return;
  }
  if (event.button !== 0) return;
  if (
    activeTool === "route_link" &&
    activeMap &&
    selectedProject
  ) {
    const waypoint = waypointAt(event);
    if (!waypoint) {
      note("mapToolHint", "请点击当前地图已有的 Waypoint。", true);
      return;
    }
    await selectTopologyWaypoint(waypoint);
    return;
  }
  if (
    (activeTool === "erase_brush" || activeTool === "erase_polygon") &&
    activeMap &&
    selectedProject
  ) {
    const point = worldPointFromEvent(event);
    if (!pointIsOnActiveMap(point)) return;
    closeComponentPopover();
    selectComponent(null);
    if (activeTool === "erase_brush") {
      if (eraserCommitPending) return;
      eraserHoverPoint = point;
      eraserStroke = {
        kind: "brush_erase",
        radius_m: eraserDiameterM / 2,
        shape: eraserShape,
        points: [point],
      };
      drawMap();
      canvas.setPointerCapture(event.pointerId);
    } else {
      polygonEraseDraft.push(point);
      drawMap();
      note(
        "mapToolHint",
        `已添加第 ${polygonEraseDraft.length} 个顶点；完成后点击“完成框选”。`,
      );
    }
    return;
  }
  if (rotateHandleAt(event)) {
    if (activeTool !== "pan") setTool("pan");
    componentRotate = selectedComponent;
    canvas.setPointerCapture(event.pointerId);
    canvas.style.cursor = "crosshair";
    return;
  }
  if (transitionRotateHandleAt(event)) {
    if (activeTool !== "pan") setTool("pan");
    waypointRotate = selectedWaypoint;
    canvas.setPointerCapture(event.pointerId);
    canvas.style.cursor = "crosshair";
    return;
  }
  if (resizeHandleAt(event)) {
    if (activeTool !== "pan") setTool("pan");
    componentResize = selectedComponent;
    canvas.setPointerCapture(event.pointerId);
    canvas.style.cursor = "nwse-resize";
    return;
  }
  // Existing stickers always win hit-testing over the insertion tool.  This
  // makes it safe to immediately drag a component even if a placement tool
  // was selected moments before.
  const hit = componentAt(event);
  if (hit) {
    if (activeTool !== "pan") setTool("pan");
    selectComponent(hit);
    componentDrag = hit;
    canvas.setPointerCapture(event.pointerId);
    return;
  }
  const waypoint = waypointAt(event);
  if (waypoint) {
    if (activeTool !== "pan") setTool("pan");
    openWaypointPopover(waypoint, event);
    return;
  }
  // Existing markers always win over virtual-wall hit testing.  A wall can
  // safely cross a facility marker without making that marker uneditable.
  const virtualWallHit = virtualWallAt(event);
  if (virtualWallHit) {
    if (activeTool !== "pan") setTool("pan");
    virtualWallDraft = null;
    selectVirtualWall(virtualWallHit.wall);
    const point = worldPointFromEvent(event);
    virtualWallDrag = {
      wall: virtualWallHit.wall,
      hit: virtualWallHit.hit,
      pointer: point,
      initial: {
        ...virtualWallHit.wall,
        start: { ...virtualWallHit.wall.start },
        end: { ...virtualWallHit.wall.end },
      },
    };
    canvas.setPointerCapture(event.pointerId);
    canvas.style.cursor = virtualWallHit.hit.startsWith("segment") ? "move" : "crosshair";
    return;
  }
  if (activeTool === "virtual_wall" && activeMap && selectedProject) {
    const point = worldPointFromEvent(event);
    if (!pointIsOnActiveMap(point) || virtualWallPlacementPending) return;
    if (!virtualWallDraft) {
      virtualWallDraft = { points: [point], hover: point };
      closeComponentPopover();
      selectComponent(null);
      note("mapToolHint", "已确定虚拟墙起点；继续左键添加拐点，双击或按 Enter 完成。按 Esc 取消本条墙。");
      drawMap();
    } else if (event.detail >= 2 && virtualWallDraft.points.length >= 2) {
      const points = virtualWallDraft.points;
      virtualWallDraft = null;
      drawMap();
      await createVirtualWall(points);
    } else {
      virtualWallDraft.points.push(point);
      virtualWallDraft.hover = point;
      note("mapToolHint", `已添加第 ${virtualWallDraft.points.length} 个虚拟墙点；继续左键添加，双击或按 Enter 完成。`);
      drawMap();
    }
    return;
  }
  if (activeTool !== "pan" && activeMap && selectedProject) {
    if (componentPlacementPending) return;
    const placementKind = activeTool;
    componentPlacementPending = true;
      setTool("pan");
    const point = worldPointFromEvent(event);
    try {
      if (placementKind === "transition") {
        const data = await request(
          `/api/deployments/${encodeURIComponent(selectedProject.id)}/waypoints`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              map_id: activeMap.id,
              kind: "transition",
              label: "过渡点",
              x: point.x,
              y: point.y,
              yaw: 0,
              speed_mode: "single_point",
            }),
          },
        );
        renderProject(data.project);
        const transitionRole = taskTransitionRole(activeMap.id);
        note("mapToolHint", transitionRole
          ? `已标记${transitionRole === "lobby" ? "电梯大厅" : "用户楼层"}任务过渡点；点选它可配置速度和去程朝向。系统会按当前地图标记自动派生它在去程中的位置，生成预览将写入去程和返程。`
          : "已标记定位过渡锚点。只有大厅或用户楼层地图上的任务过渡点会写入配送任务 JSON。");
        keepMapAnnotationOpen("过渡点已保存；请继续检查当前地图，完成后再确认进入定位路线。") ||
          completeDeploymentEdit("过渡点已保存，已返回当前任务。");
        return;
      }
      if (placementKind === "elevator") {
        openElevatorLandingDialog(point);
        return;
      }
      const data = await request(
        `/api/deployments/${encodeURIComponent(selectedProject.id)}/components`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            map_id: activeMap.id,
            kind: placementKind,
            x: point.x,
            y: point.y,
            yaw: 0,
            attributes: {},
          }),
        },
      );
      renderProject(data.project);
      selectComponent(data.component);
      await refreshTopology();
      note(
        "mapToolHint",
        `已放置${componentName(data.component)}；现在可左键拖动它，或右键编辑属性。`,
      );
      keepMapAnnotationOpen(`${componentName(data.component)}已保存；请继续检查当前地图，完成后再确认进入定位路线。`) ||
        completeDeploymentEdit(`${componentName(data.component)}已保存，已返回当前任务。`);
    } catch (error) {
      note("mapToolHint", error.message, true);
    } finally {
      componentPlacementPending = false;
    }
    return;
  }
  selectComponent(null);
  closeComponentPopover();
  beginCanvasPan(event);
});
document.addEventListener("keydown", (event) => {
  const textInput = event.target.matches?.("input, textarea, select");
  if (event.code !== "Space" || textInput) return;
  spacePanActive = true;
  event.preventDefault();
  if (!drag) canvas.style.cursor = "grab";
});
document.addEventListener("keyup", (event) => {
  if (event.code !== "Space") return;
  spacePanActive = false;
  if (!drag)
    canvas.style.cursor = activeTool === "erase_brush" ? "crosshair" : "grab";
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (virtualWallDraft) {
    virtualWallDraft = null;
    drawMap();
    note("mapToolHint", "已取消当前未完成的虚拟墙；已保存的红色折线保持不变。");
    return;
  }
  if (activeTool === "pan") return;
  if (polygonEraseDraft.length || eraserStroke) {
    polygonEraseDraft = [];
    eraserStroke = null;
    drawMap();
    note("mapToolHint", "已取消当前擦除操作；之前保存的擦除记录保持不变。");
    return;
  }
  setTool("pan");
  note("mapToolHint", "已取消当前工具。现在可选择或拖动已有组件。");
});
document.addEventListener("keydown", (event) => {
  const textInput = event.target.matches?.("input, textarea, select");
  if (textInput || !selectedVirtualWall || !["Delete", "Backspace"].includes(event.key)) return;
  event.preventDefault();
  deleteSelectedVirtualWall();
});
document.addEventListener("keydown", async (event) => {
  const textInput = event.target.matches?.("input, textarea, select");
  if (textInput || event.key !== "Enter" || !virtualWallDraft) return;
  if (virtualWallDraft.points.length < 2 || virtualWallPlacementPending) {
    note("mapToolHint", "虚拟墙至少需要两个点。", true);
    return;
  }
  event.preventDefault();
  const points = virtualWallDraft.points;
  virtualWallDraft = null;
  drawMap();
  await createVirtualWall(points);
});
canvas.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  if (taskPreviewOpen) return;
  const hit = componentAt(event);
  if (hit) openComponentPopover(hit, event);
  else {
    const waypoint = waypointAt(event);
    if (waypoint) openWaypointPopover(waypoint, event);
    else {
      const virtualWallHit = virtualWallAt(event);
      if (virtualWallHit) {
        selectVirtualWall(virtualWallHit.wall);
        note("mapToolHint", "已选中虚拟墙；拖动任意红色顶点或线段调整，按 Delete 删除。");
      } else {
        selectedVirtualWall = null;
        closeComponentPopover();
        closeWaypointPopover();
        drawMap();
      }
    }
  }
});
$("closeComponentPopover").addEventListener("click", closeComponentPopover);
$("closeWaypointPopover").addEventListener("click", closeWaypointPopover);
canvas.addEventListener("pointermove", (event) => {
  if (drag) {
    mapView.x = drag.viewX + event.clientX - drag.x;
    mapView.y = drag.viewY + event.clientY - drag.y;
    scheduleMapDraw();
    return;
  }
  if (activeMap) {
    const pointerWorld = worldPointFromEvent(event);
    const { x, y } = pointerWorld;
    $("mapCursor").textContent = `x ${x.toFixed(2)} m · y ${y.toFixed(2)} m`;
    if (eraserStroke) {
      const samples = event.getCoalescedEvents?.() || [event];
      trackEraserStroke(samples);
      // Always repaint while the button is held. In particular, this redraws
      // the live brush halo between sampled erase points, so it visibly follows
      // the pointer instead of appearing to lag at the stroke origin.
      scheduleMapDraw();
      return;
    }
    if (activeTool === "erase_brush") {
      eraserHoverPoint = pointIsOnActiveMap(pointerWorld) ? pointerWorld : null;
      canvas.style.cursor = "crosshair";
      scheduleMapDraw();
      return;
    }
    if (virtualWallDraft) {
      virtualWallDraft.hover = pointIsOnActiveMap(pointerWorld) ? pointerWorld : null;
      canvas.style.cursor = "crosshair";
      scheduleMapDraw();
      return;
    }
    if (virtualWallDrag) {
      if (!pointIsOnActiveMap(pointerWorld)) return;
      const { initial, hit, pointer } = virtualWallDrag;
      selectedVirtualWall = hit.startsWith("segment")
        ? translateWall(initial, { x: pointerWorld.x - pointer.x, y: pointerWorld.y - pointer.y })
        : hit.startsWith("vertex:")
          ? moveWallVertex(initial, Number(hit.split(":")[1]), pointerWorld)
        : moveWallEndpoint(initial, hit, pointerWorld);
      scheduleMapDraw();
      return;
    }
    if (componentDrag) {
      componentDrag.x = x;
      componentDrag.y = y;
      scheduleMapDraw();
      return;
    }
    if (componentResize) {
      const point = componentLocalPoint(componentResize, event);
      const width = Math.max(
        0.1,
        (Math.max(0.05, point.x) * 2) / mapView.scale,
      );
      const height = Math.max(
        0.1,
        (Math.max(0.05, point.y) * 2) / mapView.scale,
      );
      componentResize.attributes = {
        ...componentResize.attributes,
        width_m: Math.min(20, width),
        height_m: Math.min(20, height),
      };
      pendingComponentSizeReadout =
        `${componentResize.attributes.width_m.toFixed(2)} m × ${componentResize.attributes.height_m.toFixed(2)} m`;
      scheduleMapDraw();
      return;
    }
    if (componentRotate) {
      const center = componentCanvasPoint(componentRotate);
      const pointer = canvasPointFromEvent(event);
      const rawYaw = -Math.atan2(pointer.y - center.y, pointer.x - center.x);
      const increment = Math.PI / 18;
      const snappedYaw = Math.round(rawYaw / increment) * increment;
      componentRotate.yaw = Math.max(-Math.PI, Math.min(Math.PI, snappedYaw));
      pendingComponentYaw = componentRotate.yaw.toFixed(3);
      scheduleMapDraw();
      return;
    }
    if (waypointRotate) {
      const center = worldCanvasPoint(waypointRotate);
      const pointer = canvasPointFromEvent(event);
      const rawYaw = -Math.atan2(pointer.y - center.y, pointer.x - center.x);
      const increment = Math.PI / 18;
      const snappedYaw = Math.round(rawYaw / increment) * increment;
      waypointRotate.yaw = Math.max(-Math.PI, Math.min(Math.PI, snappedYaw));
      pendingWaypointYaw = waypointRotate;
      scheduleMapDraw();
      return;
    }
    if (!drag) {
      canvas.style.cursor = transitionRotateHandleAt(event)
        ? "crosshair"
        : rotateHandleAt(event)
        ? "crosshair"
        : resizeHandleAt(event)
          ? "nwse-resize"
          : componentAt(event)
            ? "move"
            : activeTool === "virtual_wall"
              ? "crosshair"
              : virtualWallAt(event)
                ? "move"
                : "grab";
    }
  }
});
canvas.addEventListener("pointerleave", () => {
  let changed = false;
  if (eraserHoverPoint) {
    eraserHoverPoint = null;
    changed = true;
  }
  if (virtualWallDraft?.hover) {
    virtualWallDraft.hover = null;
    changed = true;
  }
  if (changed) scheduleMapDraw();
});
canvas.addEventListener("pointerup", async (event) => {
  drag = null;
  canvas.style.cursor = activeTool === "erase_brush" ? "crosshair" : "grab";
  if (eraserStroke) {
    trackEraserStroke(event.getCoalescedEvents?.() || [event]);
    const stroke = eraserStroke;
    // Render the exact final sample without leaving a brush halo frozen in
    // the temporary frame.  The captured result remains visible during the
    // asynchronous save and cannot flash back to the original map image.
    eraserHoverPoint = null;
    drawMap();
    eraseFrameMask.cover();
    eraserStroke = null;
    pendingEraserStroke = stroke;
    eraserCommitPending = true;
    scheduleMapDraw();
    try {
      await commitMapEdit(
        {
          action: "add",
          kind: "brush_erase",
          radius_m: stroke.radius_m,
          shape: stroke.shape,
          points: stroke.points,
        },
        "擦除笔刷已保存到项目地图编辑层；可继续擦除或撤销。",
      );
    } finally {
      pendingEraserStroke = null;
      eraserCommitPending = false;
      drawMap();
      eraseFrameMask.revealAfterPaint();
    }
    return;
  }
  if (virtualWallDrag && selectedProject) {
    const wall = selectedVirtualWall;
    virtualWallDrag = null;
    if (wall) await persistVirtualWall(wall);
    return;
  }
  if (componentRotate && selectedProject) {
    const retainAnnotationWorkspace = isMapAnnotationWorkspaceActive();
    try {
      const data = await request(
        `/api/deployments/${encodeURIComponent(selectedProject.id)}/components/${encodeURIComponent(componentRotate.id)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ yaw: componentRotate.yaw }),
        },
      );
      const updated = data.project.components.find(
        (item) => item.id === componentRotate.id,
      );
      renderProject(data.project);
      selectComponent(updated);
      note("mapToolHint", "组件朝向已保存（每 10° 自动吸附）。");
      if (retainAnnotationWorkspace) {
        keepMapAnnotationOpen(
          "组件朝向已保存；请继续检查当前地图，完成后再确认进入定位路线。",
          { force: retainAnnotationWorkspace },
        );
      } else {
        completeDeploymentEdit("组件朝向已保存，已返回当前任务。");
      }
    } catch (error) {
      note("mapToolHint", error.message, true);
    }
    componentRotate = null;
    return;
  }
  if (waypointRotate && selectedProject) {
    const retainAnnotationWorkspace = isMapAnnotationWorkspaceActive();
    try {
      const data = await request(
        `/api/deployments/${encodeURIComponent(selectedProject.id)}/waypoints/${encodeURIComponent(waypointRotate.id)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ yaw: waypointRotate.yaw }),
        },
      );
      renderProject(data.project);
      selectedWaypoint = data.waypoint;
      syncTransitionYawControl(selectedWaypoint);
      drawMap();
      note("mapToolHint", "过渡点去程朝向已保存（每 10° 自动吸附）；虚线箭头会自动表示返程方向。");
      if (retainAnnotationWorkspace) {
        keepMapAnnotationOpen(
          "过渡点去程朝向已保存；请继续检查当前地图，完成后再确认进入定位路线。",
          { force: retainAnnotationWorkspace },
        );
      } else {
        completeDeploymentEdit("过渡点去程朝向已保存，已返回当前任务。");
      }
    } catch (error) {
      note("mapToolHint", error.message, true);
    }
    waypointRotate = null;
    return;
  }
  if (componentResize && selectedProject) {
    try {
      const data = await request(
        `/api/deployments/${encodeURIComponent(selectedProject.id)}/components/${encodeURIComponent(componentResize.id)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ attributes: componentResize.attributes }),
        },
      );
      const updated = data.project.components.find(
        (item) => item.id === componentResize.id,
      );
      renderProject(data.project);
      selectComponent(updated);
      note("mapToolHint", "组件尺寸已保存；继续拖动组件可调整位置。");
      keepMapAnnotationOpen("组件尺寸已保存；请继续检查当前地图，完成后再确认进入定位路线。") ||
        completeDeploymentEdit("组件尺寸已保存，已返回当前任务。");
    } catch (error) {
      note("mapToolHint", error.message, true);
    }
    componentResize = null;
    return;
  }
  if (componentDrag && selectedProject) {
    try {
      const data = await request(
        `/api/deployments/${encodeURIComponent(selectedProject.id)}/components/${encodeURIComponent(componentDrag.id)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ x: componentDrag.x, y: componentDrag.y }),
        },
      );
      const updated = data.project.components.find(
        (item) => item.id === componentDrag.id,
      );
      renderProject(data.project);
      selectComponent(updated);
      note("mapToolHint", "组件位置已保存。");
      keepMapAnnotationOpen("组件位置已保存；请继续检查当前地图，完成后再确认进入定位路线。") ||
        completeDeploymentEdit("组件位置已保存，已返回当前任务。");
    } catch (error) {
      note("mapToolHint", error.message, true);
    }
    componentDrag = null;
  }
});
canvas.addEventListener(
  "wheel",
  (event) => {
    event.preventDefault();
    if (activeTool === "erase_brush" && !event.ctrlKey && !event.metaKey) {
      setEraserDiameter(eraserDiameterM + (event.deltaY < 0 ? 0.1 : -0.1));
      return;
    }
    const pointer = canvasPointFromEvent(event);
    Object.assign(mapView, zoomAt(mapView, pointer, event.deltaY));
    scheduleMapDraw();
  },
  { passive: false },
);
$("closeTaskPreview").addEventListener("click", closeTaskPreview);
$("taskPreviewDownload").addEventListener("click", downloadTaskCompilerBundle);
$("taskPreviewMapSwitcher").addEventListener("click", (event) => {
  const button = event.target.closest("[data-task-preview-map]");
  if (!button) return;
  const map = previewMapAssets().find((item) => item.id === button.dataset.taskPreviewMap);
  if (!map) return;
  selectMap(map, { persist: false });
  renderTaskPreviewOverlay(taskCompilerPreview);
  requestAnimationFrame(() => fitMap());
});
document.addEventListener("keydown", (event) => {
  if (!taskPreviewOpen || event.key !== "Escape") return;
  event.preventDefault();
  closeTaskPreview();
});
document.addEventListener("keydown", (event) => {
  const dialog = $("deploymentEditImpactDialog");
  if (!dialog || dialog.classList.contains("deployment-hidden")) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeDeploymentEditImpact();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = Array.from(dialog.querySelectorAll("button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])"));
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});
document.addEventListener("click", (event) => {
  const button = event.target.closest(".delete-waypoint");
  if (!button || !selectedProject) return;
  request(
    `/api/deployments/${encodeURIComponent(selectedProject.id)}/waypoints/${encodeURIComponent(button.dataset.id)}`,
    { method: "DELETE" },
  )
    .then(async () => {
      await openProject(selectedProject.id);
      note("mapToolHint", "地图标记已删除；系统已根据剩余标记重新计算路线。");
    })
    .catch((error) => note("mapToolHint", error.message, true));
});
window.addEventListener("resize", scheduleCanvasResize);
if ("ResizeObserver" in window) {
  new ResizeObserver(scheduleCanvasResize).observe(canvas);
}
resizeCanvas();
renderDeploymentGuide();
loadComponentSpeedDefaults()
  .catch((error) => console.error("读取组件默认速度配置失败", error))
  .finally(loadProjects);
refreshMappingStatus();
