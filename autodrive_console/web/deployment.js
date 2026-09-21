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
import {
  orderedRouteBindingIds,
  moveRouteBinding,
  resetRouteDraft,
  routeBindingChoices,
  routeEndpointFields,
  setRouteBindingIncluded,
} from "./deployment/localization-route.js";
import {
  deriveDeploymentWorkflow,
  isDeploymentStageUnlocked,
} from "./deployment/workflow.js";
import {
  clampDeploymentStage,
  clearDeploymentSession,
  readDeploymentSession,
  writeDeploymentSession,
} from "./deployment/session-state.js";
import {
  createFlowNode,
  flowForProject,
  reorderFlow,
  renderDeploymentFlow,
  validateFlow,
} from "./deployment/flow-editor.js";
import { requestJson } from "./platform/http.js";

const $ = (id) => document.getElementById(id);
const esc = (value) => {
  const node = document.createElement("span");
  node.textContent = value ?? "";
  return node.innerHTML;
};
let selectedProject = null;
let deploymentFlow = [];
let activeMap = null;
let mapImage = null;
let mapNeedsFit = false;
let activeTool = "pan";
let selectedComponent = null;
let selectedWaypoint = null;
let mappingSession = null;
let mappingRuntime = null;
let mappingTemplate = null;
let liveMapImage = null;
let lastLivePreviewRevision = 0;
let mappingPollTimer = null;
let eraserDiameterM = 0.8;
let eraserShape = "circle";
let eraserStroke = null;
let polygonEraseDraft = [];
let eraserHoverPoint = null;
let spacePanActive = false;
let topology = null;
let routeDraft = [];
let taskCompilerPreview = null;
let taskCompilerProjectId = null;
let deploymentWorkflow = null;
let viewedDeploymentStage = null;
let elevatorLandingDraft = null;
let localizationBindingDraft = null;
let localizationRouteDraft = null;
const mapView = { scale: 40, x: 0, y: 0 };
const canvas = $("mapCanvas");
const context = canvas.getContext("2d");
const mapWorkspace = $("mapWorkspace");
const taskPreviewOverlay = $("taskPreviewOverlay");
const taskPreviewMapMount = $("taskPreviewMapMount");
let taskPreviewOpen = false;
let taskPreviewOriginMapId = null;
let taskPreviewWorkspaceParent = null;
let taskPreviewWorkspaceBefore = null;
let canvasResizeFrame = null;
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
    viewedStage: viewedDeploymentStage || deploymentWorkflow?.current?.id || null,
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
      : '<div class="compiler-empty">预览没有返回可展示的子任务。</div>',
    warnings.length
      ? `<ul class="compiler-warning-list">${warnings.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`
      : "",
    `<p class="compiler-artifact-meta">${Array.isArray(preview.artifacts) ? preview.artifacts.length : 0} 个实验文件 · 输入校验 ${esc(preview.input_sha256 || "—")}</p>`,
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
  $("taskPreviewStepCount").textContent = `${subtasks.length} 个子任务`;
  $("taskPreviewTaskList").innerHTML = subtasks.map((subtask, index) => {
    const points = Array.isArray(subtask.waypoints) ? subtask.waypoints : [];
    return `<li class="task-preview-task-item${index === 0 ? " is-active" : ""}"><span class="task-preview-task-index">${index + 1}</span><div><strong>${esc(subtask.subtask_name || `子任务 ${index + 1}`)}</strong><small>${points.length} 个路点</small></div></li>`;
  }).join("") || '<li class="task-preview-task-empty">预览没有返回任务步骤。</li>';
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
function renderTaskCompilerState(project) {
  const compiler = project?.task_compiler || {};
  const identity = compiler.identity || {};
  const community = identity.community || "";
  $("taskCompilerCommunity").value = community;
  const localizationTemplate = project?.localization_template;
  const localizationTemplateMessage = $("localizationTemplateMessage");
  localizationTemplateMessage.classList.remove("error");
  localizationTemplateMessage.textContent = localizationTemplate
    ? `当前模板：${localizationTemplate.name || "localization-template.yaml"}；已加载，生成时会以此模板为准。`
    : "未导入时使用项目默认模板；导入后每次生成都以该模板为准。";
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
  } catch (error) {
    taskCompilerMessage(compilerRecovery(error.message), true);
  } finally {
    button.disabled = !selectedProject;
  }
}
async function refreshTaskCompilerPreview() {
  if (!selectedProject) return;
  const button = $("generateTaskCompilerPreview");
  button.disabled = true;
  taskCompilerMessage("正在由服务端校验组件并生成实验预览…");
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/task-compiler/preview`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      },
    );
    taskCompilerPreview = data.preview;
    taskCompilerProjectId = selectedProject.id;
    renderTaskCompilerPreview(data.preview);
    openTaskPreview(data.preview);
  } catch (error) {
    taskCompilerPreview = {
      status: "blocked",
      errors: [error.message],
      recovery: "请检查小区名称、地图阶段、组件属性和机器人地图来源后重试。",
    };
    renderTaskCompilerPreview(taskCompilerPreview);
  } finally {
    button.disabled = !selectedProject?.task_compiler?.identity?.community;
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
  $("mapStageSummary").innerHTML = stages
    .map((stage, index) => {
      const bound = Boolean(stage.map_asset_id);
      return `<span class="${bound ? "done" : stage.status === "editing" ? "active" : ""}"><b>${bound ? "✓" : index + 1}</b>${esc(stage.map_label || stage.label)}</span>`;
    })
    .join("");
  const current = stages.find((stage) => !stage.map_asset_id);
  $("importMessage").textContent = current
    ? `当前待完善：${current.label}。可导入既有地图或使用下方车端建图。`
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
      .map((stage) => `<div class="topology-stage ${esc(stage.status)}"><span>${stage.status === "complete" ? "✓" : stage.status === "editing" ? "•" : "—"}</span><div><b>${esc(stage.label)}</b><small>${esc(stage.map_label || "尚未绑定地图")}</small></div></div>`)
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
    maps: topology?.stages?.length && topology.stages.every((stage) => stage.map_asset_id)
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
  deploymentWorkflow = deriveDeploymentWorkflow(selectedProject, topology, taskCompilerPreview);
  const { steps, current, next, completed, total, percent, checklist } = deploymentWorkflow;
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
  const guideTitle = reviewingCompletedStage ? `${activeStep.label}已完成` : next.label;
  const guideDetail = reviewingCompletedStage
    ? "正在查看已完成阶段；返回当前步骤后继续现场配置。"
    : next.detail || current.reason || current.detail;
  const guideButton = reviewingCompletedStage
    ? '<button id="deploymentGuideNext" class="page-top-action" type="button" data-guide-action="return-current">回到当前步骤</button>'
    : `<button id="deploymentGuideNext" class="page-top-action" type="button" data-guide-action="${esc(next.id)}">${esc(next.label)}</button>`;
  $("deploymentGuideCurrent").innerHTML = `<div class="deployment-guide-current-copy">
    <span class="deployment-guide-kicker">${reviewingCompletedStage ? "已完成阶段" : `当前要做 · ${esc(current.label)}`}</span>
    <h3>${esc(guideTitle)}</h3>
    <p>${esc(guideDetail)}</p>
    ${!reviewingCompletedStage && current.reason ? `<small class="deployment-guide-reason">${esc(current.reason)}</small>` : ""}
  </div>${guideButton}`;
  $("deploymentGuideChecklist").innerHTML = checklist
    .map(
      (item) => `<div class="deployment-guide-check ${item.done ? "done" : ""}"><span class="deployment-guide-check-mark" aria-hidden="true"></span><span>${esc(item.label)}</span><small>${item.done ? "已确认" : "待完成"}</small></div>`,
    )
    .join("");
  $("deploymentGuideChecklistMeta").textContent = `${checklist.filter((item) => item.done).length} / ${checklist.length}`;
  applyDeploymentStageGating();
  persistDeploymentSession();
}

function applyDeploymentStageGating() {
  const activeStage = viewedDeploymentStage || deploymentWorkflow?.current?.id || "project";
  if (activeStage === "maps" && activeTool !== "pan") setTool("pan");
  document.body.dataset.deploymentStage = activeStage;
  document.querySelectorAll("[data-deployment-stage], [data-deployment-stages]").forEach((panel) => {
    const requiredStages = (panel.dataset.deploymentStages || panel.dataset.deploymentStage || "")
      .split(/\s+/)
      .filter(Boolean);
    const visible = requiredStages.includes(activeStage);
    panel.classList.toggle("deployment-stage-hidden", !visible);
    panel.classList.toggle("deployment-stage-visible", visible);
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
    persistDeploymentSession();
    renderDeploymentGuide();
    focusGuideTarget(guideTargetForStep(deploymentWorkflow?.current?.id));
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
    const routeButton = $("localizationRouteList")?.querySelector("button");
    if (routeButton) {
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
  persistDeploymentSession();
  renderDeploymentGuide();
  const target = guideTargetForStep(stepId);
  if (stepId === "annotations" && deploymentWorkflow?.next?.targetMapId) {
    const map = (selectedProject?.map_assets || []).find((item) => item.id === deploymentWorkflow.next.targetMapId);
    if (map) selectMap(map);
  }
  focusGuideTarget(target);
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
function renderProject(project) {
  const projectChanged = selectedProject?.id !== project?.id;
  selectedProject = project;
  if (projectChanged) {
    activeMap = null;
    mapImage = null;
    selectedWaypoint = null;
    $("waypointPopover").classList.add("deployment-hidden");
    const session = readDeploymentSession();
    viewedDeploymentStage = session?.projectId === project.id ? session.viewedStage : null;
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
  $("currentProjectMeta").textContent = `项目 ID：${project.id} · 已导入 ${maps.length} 张地图`;
  $("selectedProjectTitle").textContent = project.name;
  $("deploymentFlowEditor").classList.remove("deployment-hidden");
  deploymentFlow = flowForProject(project);
  renderDeploymentFlowEditor();
  $("importControls").classList.remove("deployment-hidden");
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
  renderLocalizationRoutes();
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
}
function localizationBindings() {
  return Array.isArray(selectedProject?.localization_bindings)
    ? selectedProject.localization_bindings
    : [];
}
function localizationRoutes() {
  return Array.isArray(selectedProject?.localization_routes)
    ? selectedProject.localization_routes
    : [];
}
function bindingsForIdentity(building, unit) {
  return localizationBindings().filter(
    (item) => item.building === building && item.unit === unit,
  );
}
function mapForId(mapAssetId) {
  return (selectedProject?.map_assets || []).find((item) => item.id === mapAssetId);
}
function routeAnchorOptions(mapAssetId) {
  const waypointOptions = (selectedProject?.waypoints || [])
    .filter((item) => item.map_asset_id === mapAssetId)
    .map((item) => ({
      value: `waypoint:${item.id}`,
      label: `航点 · ${item.label || item.kind || item.id}`,
      anchor: { kind: "waypoint", waypoint_id: item.id },
    }));
  const componentOptions = (selectedProject?.components || [])
    .filter((item) => item.map_asset_id === mapAssetId)
    .map((item) => ({
      value: `component:${item.id}`,
      label: `${item.kind === "elevator" ? "电梯组件中心" : "组件中心"} · ${componentName(item) || item.id}`,
      anchor: { kind: "component_center", component_id: item.id },
    }));
  return [...waypointOptions, ...componentOptions];
}
function routeAnchorValue(anchor) {
  if (anchor?.kind === "waypoint") return `waypoint:${anchor.waypoint_id}`;
  if (anchor?.kind === "component_center") return `component:${anchor.component_id}`;
  return "";
}
function routeAnchorForValue(value) {
  const [kind, id] = String(value || "").split(":");
  if (!id) return null;
  return kind === "component"
    ? { kind: "component_center", component_id: id }
    : kind === "waypoint"
      ? { kind: "waypoint", waypoint_id: id }
      : null;
}
function routeForIdentity(building, unit) {
  return localizationRoutes().find(
    (item) => item.building === building && item.unit === unit,
  );
}
function routeBindings() {
  const bindings = bindingsForIdentity(
    localizationRouteDraft?.building,
    localizationRouteDraft?.unit,
  );
  return (localizationRouteDraft?.binding_ids || [])
    .map((id) => bindings.find((item) => item.id === id))
    .filter(Boolean);
}
function ensureRouteLinks() {
  const bindings = routeBindings();
  const retained = new Map(
    (localizationRouteDraft?.links || []).map((item) => [
      `${item.from_binding_id}:${item.to_binding_id}`,
      item.anchor,
    ]),
  );
  localizationRouteDraft.links = bindings.slice(0, -1).map((item, index) => {
    const next = bindings[index + 1];
    const key = `${item.id}:${next.id}`;
    const elevators = (selectedProject?.components || []).filter(
      (component) => component.map_asset_id === item.map_asset_id && component.kind === "elevator",
    );
    return {
      from_binding_id: item.id,
      to_binding_id: next.id,
      anchor: retained.get(key) || (elevators.length === 1
        ? { kind: "component_center", component_id: elevators[0].id }
        : null),
    };
  });
}
function localizationRoutePayload() {
  if (!localizationRouteDraft) return null;
  ensureRouteLinks();
  return {
    building: localizationRouteDraft.building,
    unit: localizationRouteDraft.unit,
    binding_ids: [...localizationRouteDraft.binding_ids],
    task_start_waypoint_id: localizationRouteDraft.task_start_waypoint_id || "",
    task_target_waypoint_id: localizationRouteDraft.task_target_waypoint_id || "",
    links: localizationRouteDraft.links.map((item) => ({
      from_binding_id: item.from_binding_id,
      to_binding_id: item.to_binding_id,
      anchor: item.anchor,
    })),
  };
}
function routeEndpointOptions(mapAssetId, kind) {
  return (selectedProject?.waypoints || []).filter(
    (item) => item.map_asset_id === mapAssetId && item.kind === kind,
  );
}
function routeWaypointLabel(item, kind) {
  const role = kind === "start" ? "任务起点" : kind === "transition" ? "过渡点" : "任务终点";
  const name = item.label || item.id || `${kind} 航点`;
  const x = Number(item.x);
  const y = Number(item.y);
  const coordinates = Number.isFinite(x) && Number.isFinite(y)
    ? ` · (${x.toFixed(2)}, ${y.toFixed(2)})`
    : "";
  return `${role} · ${name}${coordinates}`;
}
function routeValidation(bindings) {
  const lastIsFloor = bindings.at(-1)?.type === "floor" && bindings.slice(0, -1).every((binding) => binding.type !== "floor");
  const missing = [];
  if (!localizationRouteDraft?.task_start_waypoint_id) missing.push("首张地图任务起点");
  if (!localizationRouteDraft?.task_target_waypoint_id) missing.push("末张地图任务终点");
  if (localizationRouteDraft?.links?.some((item) => !item.anchor)) missing.push("地图切图依据");
  return { lastIsFloor, missing, complete: lastIsFloor && missing.length === 0 };
}
function openLocalizationRoute(building, unit) {
  const existing = routeForIdentity(building, unit);
  const bindings = bindingsForIdentity(building, unit);
  localizationRouteDraft = {
    id: existing?.id || null,
    building,
    unit,
    binding_ids: orderedRouteBindingIds(
      existing?.binding_ids,
      bindings,
      building,
      unit,
    ),
    task_start_waypoint_id: existing?.task_start_waypoint_id || "",
    task_target_waypoint_id: existing?.task_target_waypoint_id || "",
    links: existing?.links ? [...existing.links] : [],
  };
  ensureRouteLinks();
  $("localizationRouteDialog").classList.remove("deployment-hidden");
  renderLocalizationRouteDialog();
  $("localizationRouteLinks").querySelector("select, button")?.focus();
}
function closeLocalizationRoute() {
  localizationRouteDraft = null;
  $("localizationRouteDialog").classList.add("deployment-hidden");
}
function derivedRouteSource(binding, index, bindings) {
  const go = index === 0 ? "人工任务起点" : "电梯中心坐标 0,0";
  if (index === bindings.length - 1) return { go, back: "电梯门前呼梯点自动派生" };
  const anchor = localizationRouteDraft.links[index]?.anchor;
  return { go, back: anchor?.kind === "component_center" ? "组件中心自动派生" : "受控锚点" };
}
function renderLocalizationRouteDialog() {
  if (!localizationRouteDraft) return;
  ensureRouteLinks();
  const bindings = routeBindings();
  const holder = $("localizationRouteLinks");
  const choices = routeBindingChoices(localizationBindings(), localizationRouteDraft.building, localizationRouteDraft.unit, localizationRouteDraft.binding_ids);
  $("localizationRouteMembership").innerHTML = choices.map((binding) => `<label><input type="checkbox" data-route-include="${esc(binding.id)}" ${binding.included ? "checked" : ""}><span>${esc(mapForId(binding.map_asset_id)?.label || binding.map_asset_id)} · ${esc(binding.type === "floor" ? `用户楼层模板 ${binding.floor_template}` : { outdoor: "户外", indoor: "室内大厅", ferry: "摆渡层" }[binding.type] || binding.type)}</span></label>`).join("");
  $("deleteLocalizationRoute").classList.toggle("deployment-hidden", !localizationRouteDraft.id);
  $("localizationRouteIdentity").textContent = `${localizationRouteDraft.building} 栋 ${localizationRouteDraft.unit} 单元 · 后续地图从电梯中心 0,0 起步；楼上返程目标自动取电梯门前呼梯点。`;
  if (!bindings.length) {
    holder.innerHTML = '<div class="page-empty">勾选本次路线需要的地图，然后配置起终点和自动切图依据。</div>';
    $("localizationRouteMessage").textContent = "尚未选择路线地图。";
    $("localizationRouteSummary").textContent = "尚不能生成派生定位文件。";
    return;
  }
  holder.innerHTML = bindings.map((binding, index) => {
    const map = mapForId(binding.map_asset_id) || {};
    const first = index === 0;
    const last = index === bindings.length - 1;
    const sources = derivedRouteSource(binding, index, bindings);
    const starts = routeEndpointOptions(binding.map_asset_id, "start");
    const targets = routeEndpointOptions(binding.map_asset_id, "target");
    const link = localizationRouteDraft.links[index];
    const anchorOptions = !last ? routeAnchorOptions(binding.map_asset_id) : [];
    const elevators = (selectedProject?.components || []).filter(
      (item) => item.map_asset_id === binding.map_asset_id && item.kind === "elevator",
    );
    const endpointFields = routeEndpointFields(first, last);
    const endpoint = [
      endpointFields.includes("start")
        ? `<label>人工任务起点<select data-route-start><option value="">未选择：首张地图任务起点</option>${starts.map((item) => `<option value="${esc(item.id)}" ${item.id === localizationRouteDraft.task_start_waypoint_id ? "selected" : ""}>${esc(routeWaypointLabel(item, "start"))}</option>`).join("")}</select></label>`
        : "",
      endpointFields.includes("target")
        ? `<label>去程任务终点<select data-route-target><option value="">未选择：选择交付目标点</option>${targets.map((item) => `<option value="${esc(item.id)}" ${item.id === localizationRouteDraft.task_target_waypoint_id ? "selected" : ""}>${esc(routeWaypointLabel(item, "target"))}</option>`).join("")}</select></label><p class="route-auto-note">返程子任务目标自动使用目标层电梯门前呼梯点。</p>`
        : "",
    ].join("");
    const anchor = !last
      ? `<label>地图切图依据<select data-route-anchor="${index}"><option value="">选择电梯组件中心</option>${anchorOptions.map((item) => `<option value="${esc(item.value)}" ${routeAnchorValue(link?.anchor) === item.value ? "selected" : ""}>${esc(item.label)}</option>`).join("")}</select></label>${elevators.length > 1 ? `<p class="route-blocker">本图有 ${elevators.length} 个电梯组件：请明确关联实际使用的电梯；单电梯会自动选中。</p>` : elevators.length === 1 ? '<p class="route-auto-note">已按唯一电梯组件中心自动派生。</p>' : '<p class="route-blocker">本图没有可自动派生的电梯组件，请先标记电梯。</p>'}`
      : "";
    return `<article class="localization-route-card"><header><div><b>${index + 1}. ${esc(map.label || binding.map_asset_id)}</b><small>${esc(binding.type === "floor" ? `用户楼层 · 模板 ${binding.floor_template}` : binding.type)}</small></div><div class="route-order-actions"><button class="compact-action" data-route-move="up" data-route-index="${index}" type="button" ${first ? "disabled" : ""}>上移</button><button class="compact-action" data-route-move="down" data-route-index="${index}" type="button" ${last ? "disabled" : ""}>下移</button></div></header><div class="route-derived"><span>进入：${esc(sources.go)}</span><span>返回：${esc(sources.back)}</span></div>${endpoint}${anchor}${last ? '<p class="route-last-note">末项必须为“用户楼层”。</p>' : ""}</article>`;
  }).join("");
  const validation = routeValidation(bindings);
  $("localizationRouteMessage").textContent = validation.complete
    ? "路线完整：位姿将由受控地图事实派生。"
    : validation.lastIsFloor
      ? `待补齐：${validation.missing.join("、")}。`
      : "用户楼层只能在末项；请排除其他模板并调整顺序。";
  $("localizationRouteMessage").style.color = validation.complete ? "#35d69c" : "#ffc05a";
  $("localizationRouteSummary").innerHTML = `<b>${validation.complete ? "派生状态已完整" : "派生状态待补齐"}</b><span>将生成 <code>loc_yaml_path.json</code> 与 <code>lift_id_list.json</code>；仅显示相对文件名。</span>`;
}
async function saveLocalizationRoute() {
  if (!selectedProject || !localizationRouteDraft) return;
  const payload = localizationRoutePayload();
  const bindings = routeBindings();
  const validation = routeValidation(bindings);
  if (!validation.complete) {
    const reason = validation.lastIsFloor
      ? `待补齐：${validation.missing.join("、")}。`
      : "用户楼层只能在末项；请排除其他模板并调整顺序。";
    note("localizationRouteMessage", reason, true);
    return;
  }
  try {
    const id = localizationRouteDraft.id;
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/localization-routes${id ? `/${encodeURIComponent(id)}` : ""}`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    );
    renderProject(data.project);
    closeLocalizationRoute();
  } catch (error) {
    note("localizationRouteMessage", error.message, true);
  }
}
function resetLocalizationRoute() {
  if (!localizationRouteDraft || !window.confirm("清空当前定位路线草稿？已保存的路线保留，只有再次保存才会替换。")) return;
  localizationRouteDraft = resetRouteDraft(localizationRouteDraft);
  renderLocalizationRouteDialog();
}
async function deleteLocalizationRoute() {
  const route = localizationRouteDraft;
  if (!selectedProject || !route?.id || !window.confirm(`删除 ${route.building} 栋 ${route.unit} 单元的定位路线？地图和定位绑定会保留，删除后可重新编辑绑定。`)) return;
  const button = $("deleteLocalizationRoute");
  button.disabled = true;
  try {
    await request(`/api/deployments/${encodeURIComponent(selectedProject.id)}/localization-routes/${encodeURIComponent(route.id)}`, { method: "DELETE" });
    const data = await request(`/api/deployments/${encodeURIComponent(selectedProject.id)}`);
    renderProject(data.project);
    closeLocalizationRoute();
  } catch (error) {
    note("localizationRouteMessage", error.message, true);
  } finally {
    button.disabled = false;
  }
}
function renderLocalizationRoutes() {
  const holder = $("localizationRouteList");
  const routes = localizationRoutes();
  holder.innerHTML = routes.length
    ? routes.map((route) => {
      const bindings = route.binding_ids.map((id) => localizationBindings().find((item) => item.id === id)).filter(Boolean);
      const labels = bindings.map((binding, index) => `${mapForId(binding.map_asset_id)?.label || binding.map_asset_id}：${index === 0 ? "人工任务起点" : "电梯中心 0,0"}${index === bindings.length - 1 ? ` / 去程终点${route.task_target_waypoint_id ? " · 返程呼梯点自动派生" : ""}` : ` / ${route.links[index]?.anchor?.kind === "component_center" ? "组件中心自动派生" : "受控锚点"}`}`);
      return `<div class="localization-route-row"><div><b>${esc(route.building)} 栋 ${esc(route.unit)} 单元 · ${bindings.length} 图路线</b><small>${labels.map(esc).join(" · ")}</small></div><button class="compact-action edit-localization-route" data-route-building="${esc(route.building)}" data-route-unit="${esc(route.unit)}" type="button">编辑定位路线</button></div>`;
    }).join("")
    : '<div class="page-empty">保存同一楼栋/单元的多个绑定后，可在此编辑定位路线。</div>';
}
function renderLocalizationBindings() {
  const holder = $("localizationBindingList");
  const open = $("openLocalizationBinding");
  open.disabled = !selectedProject || !activeMap;
  const bindings = localizationBindings().filter(
    (item) => item.map_asset_id === activeMap?.id,
  );
  holder.innerHTML = bindings.length
    ? bindings.map((item) => `<div class="localization-binding-row active"><div><b>${esc(item.type === "floor" ? `用户楼层 · 模板 ${item.floor_template}` : { outdoor: "户外", indoor: "室内大厅", ferry: "摆渡层" }[item.type] || item.type)}</b><small>${esc(item.building)} 栋 ${esc(item.unit)} 单元 · 当前地图</small></div><div class="localization-binding-actions"><button class="compact-action edit-localization-binding" data-binding-id="${esc(item.id)}" type="button">编辑</button><button class="compact-action edit-localization-route" data-route-building="${esc(item.building)}" data-route-unit="${esc(item.unit)}" type="button">编辑定位路线</button></div></div>`).join("")
    : '<div class="page-empty">当前地图尚未配置定位绑定。</div>';
}
function localizationTypeChanged() {
  const floor = $("localizationBindingType").value === "floor";
  $("localizationFloorTemplateLabel").classList.toggle("deployment-hidden", !floor);
  $("localizationFloorTemplate").required = floor;
}
function openLocalizationBinding(binding = null) {
  if (!selectedProject || !activeMap) return;
  const instance = mapInstanceFor(activeMap.id) || {};
  localizationBindingDraft = binding || { map_asset_id: activeMap.id, building: instance.building || "", unit: instance.unit || "", type: "indoor" };
  $("localizationBindingType").value = localizationBindingDraft.type;
  $("localizationBuilding").value = localizationBindingDraft.building || "";
  $("localizationUnit").value = localizationBindingDraft.unit || "";
  $("localizationFloorTemplate").value = localizationBindingDraft.floor_template || "";
  $("deleteLocalizationBinding").classList.toggle("deployment-hidden", !binding?.id);
  $("localizationBindingDialog").classList.remove("deployment-hidden");
  localizationTypeChanged();
  $("localizationBindingType").focus();
}
function closeLocalizationBinding() {
  localizationBindingDraft = null;
  $("localizationBindingDialog").classList.add("deployment-hidden");
}
async function saveLocalizationBinding() {
  if (!selectedProject || !activeMap) return;
  const payload = { map_asset_id: activeMap.id, building: $("localizationBuilding").value, unit: $("localizationUnit").value, type: $("localizationBindingType").value };
  if (payload.type === "floor") payload.floor_template = $("localizationFloorTemplate").value;
  const id = localizationBindingDraft?.id;
  try {
    const data = await request(`/api/deployments/${encodeURIComponent(selectedProject.id)}/localization-bindings${id ? `/${encodeURIComponent(id)}` : ""}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    renderProject(data.project);
    closeLocalizationBinding();
    note("mapToolHint", "定位绑定已保存；导出时将自动生成受控定位路径。");
  } catch (error) { note("localizationBindingMessage", error.message, true); }
}
async function deleteLocalizationBinding() {
  if (!selectedProject || !localizationBindingDraft?.id) return;
  try {
    await request(`/api/deployments/${encodeURIComponent(selectedProject.id)}/localization-bindings/${encodeURIComponent(localizationBindingDraft.id)}`, { method: "DELETE" });
    await openProject(selectedProject.id);
    closeLocalizationBinding();
  } catch (error) { note("localizationBindingMessage", error.message, true); }
}
function renderInstances() {
  const items = selectedProject?.map_instances || [];
  $("instanceList").innerHTML = items.length
    ? items
        .map(
          (item) =>
            `<div class="asset-row"><div><b>${esc(item.label)}</b><small>${esc(item.role)} · ${item.building ? `${esc(item.building)} 栋 ${esc(item.unit)} 单元 ${esc(item.floor)}F` : "园区室外"}</small></div></div>`,
        )
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
  for (const edit of (selectedProject?.map_edits || []).filter(
    (item) => item.map_asset_id === activeMap?.id,
  )) {
    drawEraseOperation(edit);
  }
  if (eraserStroke) drawEraseOperation(eraserStroke, true);
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
function componentLocalPoint(item, event) {
  return getComponentLocalPoint(item, canvasPointFromEvent(event), activeMap, mapView);
}
function drawElevatorDoorMarker(width, height) {
  const markerSize = Math.max(3, Math.min(8, Math.min(width, height) * 0.12));
  const top = -height / 2 + markerSize * 0.45;
  context.save();
  context.shadowColor = "transparent";
  context.fillStyle = "#ffffff";
  context.beginPath();
  context.moveTo(0, top - markerSize * 0.7);
  context.lineTo(-markerSize * 0.7, top + markerSize * 0.45);
  context.lineTo(markerSize * 0.7, top + markerSize * 0.45);
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
  if (item.kind === "start" || item.kind === "target") {
    context.beginPath();
    context.arc(0, 0, Math.min(width, height) * 0.36, 0, Math.PI * 2);
    context.fillStyle = `${color}77`;
    context.fill();
    context.shadowColor = "transparent";
    context.strokeStyle = color;
    context.stroke();
    context.fillStyle = color;
    context.beginPath();
    context.moveTo(width * 0.2, 0);
    context.lineTo(-width * 0.13, -height * 0.16);
    context.lineTo(-width * 0.13, height * 0.16);
    context.closePath();
    context.fill();
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
    drawMapRoutes,
    drawComponentSymbol,
    drawMapOrigin,
    drawLocalizationMarkers,
    mapPointToCanvas,
  });
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
            `<div class="asset-row project-row"><div><b>${esc(item.name)}</b><small>${esc(item.id)} · ${item.map_count} 张地图 · 更新于 ${esc(item.updated_at)}</small></div><div class="project-row-actions"><button class="compact-action open-project" data-id="${esc(item.id)}" type="button">打开</button><button class="project-delete-button delete-project" data-id="${esc(item.id)}" data-name="${esc(item.name)}" type="button" aria-label="删除部署项目 ${esc(item.name)}" title="删除部署项目"><svg class="project-delete-icon" viewBox="0 0 24 24" aria-hidden="true"><path class="project-delete-lid" d="M5 7h14M9 7V5h6v2"/><path d="M7 9l1 10h8l1-10M10 11v5M14 11v5"/></svg><span>删除</span></button></div></div>`,
          )
          .join("")
      : '<div class="page-empty">还没有部署项目。</div>';
    const session = readDeploymentSession();
    const restoredProject = session?.projectId
      ? data.projects.find((item) => item.id === session.projectId)
      : null;
    if (restoredProject && !selectedProject) {
      await openProject(restoredProject.id);
    } else if (session?.projectId && !restoredProject) {
      clearDeploymentSession();
    }
  } catch (error) {
    $("projectList").innerHTML =
      `<div class="page-empty">读取失败：${esc(error.message)}</div>`;
  }
}
async function openProject(id) {
  const data = await request(`/api/deployments/${encodeURIComponent(id)}`);
  topology = null;
  renderProject(data.project);
  persistDeploymentSession();
  await refreshMappingStatus();
  await refreshTopology();
}
$("saveDeploymentFlow").addEventListener("click", async () => {
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
  } catch (error) {
    note("deploymentFlowMessage", error.message, true);
    renderDeploymentFlowEditor();
  }
});
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
$("prepareMapping").addEventListener("click", async () => {
  if (!selectedProject) return;
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
  } catch (error) {
    note("mappingMessage", error.message, true);
  }
});
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
$("createProject").addEventListener("click", async () => {
  try {
    const data = await request("/api/deployments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: $("projectName").value }),
    });
    $("projectName").value = "";
    renderProject(data.project);
    note("projectMessage", "部署项目已创建。");
    await loadProjects();
    await refreshMappingStatus();
  } catch (error) {
    note("projectMessage", error.message, true);
  }
});
$("showNewProjectForm").addEventListener("click", () => {
  $("newProjectForm").classList.remove("deployment-hidden");
  $("currentProjectCard").classList.add("deployment-hidden");
  $("projectName").focus();
  note("projectMessage", `仍在编辑“${selectedProject?.name || "当前项目"}”；创建新项目后才会切换。`);
});
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
$("importMap").addEventListener("click", async () => {
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
      upload.upload.onprogress = (event) => {
        if (event.lengthComputable) note("importMessage", `正在上传地图：${Math.round(event.loaded / event.total * 100)}%`);
      };
      upload.onerror = () => reject(new Error("地图上传连接中断，未确认导入。"));
      upload.onload = () => {
        const response = JSON.parse(upload.responseText || "{}");
        if (upload.status >= 200 && upload.status < 300) resolve(response);
        else reject(new Error(response.error || `地图导入失败（HTTP ${upload.status}）`));
      };
      upload.send(payload);
    });
    renderProject(data.project);
    await refreshTopology();
    $("mapFolder").value = "";
    renderMapFolderSelection([]);
    note("mapFolderMessage", "地图文件已导入；可继续选择下一张地图。 ");
    note("importMessage", `已导入 ${data.map.label}；机器人原地图未被修改。`);
    await loadProjects();
  } catch (error) {
    note("importMessage", error.message, true);
  }
});
$("mapFolder").addEventListener("change", () => {
  const files = Array.from($("mapFolder").files || []);
  const summary = renderMapFolderSelection(files);
  const mapYaml = files.filter((file) => (file.webkitRelativePath || file.name).split("/").pop().toLowerCase() === "map.yaml");
  if (mapYaml.length === 1) {
    const relative = mapYaml[0].webkitRelativePath || mapYaml[0].name;
    const name = relative.split("/").slice(0, -1).join(" / ");
    if (!$("mapLabel").value.trim()) $("mapLabel").value = name;
    note("mapFolderMessage", summary.pgmCount
      ? `已选择 ${files.length} 个文件，将使用 ${relative}。${summary.pcdCount ? `已发现 ${summary.pcdCount} 个 PCD。` : "定位导出时请准备至少一个 PCD。"}`
      : `已选择 ${files.length} 个文件，但缺少 YAML 引用的 PGM。`, !summary.pgmCount);
  } else {
    note("mapFolderMessage", `已选择 ${files.length} 个文件；需要且只能包含一个 map.yaml。`, true);
  }
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
  } catch (error) {
    note("mapToolHint", error.message, true);
  }
}
function setEraserDiameter(value) {
  eraserDiameterM = Math.max(0.1, Math.min(8, Math.round(value * 10) / 10));
  $("eraserDiameterValue").textContent = `${eraserDiameterM.toFixed(1)} m`;
  $("eraserButtonSize").textContent = `${eraserDiameterM.toFixed(1)} m`;
  drawMap();
}
function setEraserShape(shape) {
  eraserShape = shape;
  $("eraserCircle").classList.toggle("active", shape === "circle");
  $("eraserSquare").classList.toggle("active", shape === "square");
  drawMap();
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
      return `<label>${esc(field.label)}<input data-component-attribute="${esc(field.key)}" type="${esc(field.type)}" value="${esc(value)}" ${field.placeholder ? `placeholder="${esc(field.placeholder)}"` : ""} ${field.min ? `min="${esc(field.min)}"` : ""} ${field.max ? `max="${esc(field.max)}"` : ""} ${field.step ? `step="${esc(field.step)}"` : ""} /></label>`;
    })
    .join("");
  const sharedElevator = physicalElevatorFor(component);
  const mapInstance = mapInstanceFor(component.map_asset_id);
  const sharedContext =
    component.kind === "elevator"
      ? sharedElevator
        ? `<div class="physical-floor"><span>关联物理电梯 · ${esc(sharedElevator.elevator_id)}</span><strong>${esc(protocolTitle(selectedProject, sharedElevator.elevator_protocol))} · ${esc(sharedElevator.min_floor)}F 至 ${esc(sharedElevator.max_floor)}F</strong><small>本地图电梯按钮层：${esc(component.attributes?.button_floor ?? "未填写")}。物理层由服务端按按钮序列推导，按钮 0 不参与编号。</small><button class="compact-action edit-shared-elevator" type="button" data-physical-elevator-id="${esc(sharedElevator.id)}">编辑共享电梯</button></div>`
        : '<p class="component-no-options">此电梯落点缺少共享电梯关联；请删除后重新关联。</p>'
      : "";
  $("componentAttributeFields").innerHTML =
    `${sharedContext}${controls}` ||
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
  $("waypointPopoverTitle").textContent = waypoint.label || "地图标记";
  const waypointKindLabel = waypoint.kind === "transition" ? "过渡点" : waypoint.kind;
  $("waypointPopoverDetail").textContent = `${waypointKindLabel} · x ${Number(waypoint.x).toFixed(2)} · y ${Number(waypoint.y).toFixed(2)} · yaw ${Number(waypoint.yaw || 0).toFixed(2)}`;
  closeComponentPopover();
  popover.classList.remove("deployment-hidden");
  const workspace = $("mapWorkspace");
  const width = popover.offsetWidth;
  const height = popover.offsetHeight;
  const x = event.clientX - workspace.getBoundingClientRect().left;
  const y = event.clientY - workspace.getBoundingClientRect().top;
  popover.style.left = `${Math.max(12, Math.min(x + 14, workspace.clientWidth - width - 12))}px`;
  popover.style.top = `${Math.max(12, Math.min(y + 14, workspace.clientHeight - height - 12))}px`;
}
function elevatorLandingMode() {
  return document.querySelector('input[name="elevatorLandingMode"]:checked')?.value || "existing";
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
  }
  const existingRadio = document.querySelector('input[name="elevatorLandingMode"][value="existing"]');
  existingRadio.disabled = !elevators.length;
  if (!elevators.length) {
    document.querySelector('input[name="elevatorLandingMode"][value="new"]').checked = true;
  }
  const linked = elevators.find((item) => item.id === existing.value);
  $("existingPhysicalElevatorSummary").textContent = linked
    ? `编号 ${linked.elevator_id} · ${protocolTitle(selectedProject, linked.elevator_protocol)} · 服务 ${linked.min_floor}F 至 ${linked.max_floor}F。各楼层分别确认门方向。`
    : "请先新建一部物理电梯，再在其他楼层关联它。";
  const isNew = editing || elevatorLandingMode() === "new";
  $("elevatorLandingDialogTitle").textContent = editing ? "编辑共享电梯" : "放置电梯落点";
  $("elevatorLandingDialogDescription").textContent = editing
    ? "此处修改的是同一部实体电梯的编号、协议和服务范围；各地图的门向不会被改动。"
    : "共享硬件信息只维护一次；本层只确认门向与候梯距离。";
  $("elevatorLandingDialog").querySelector(".elevator-landing-mode").classList.toggle("deployment-hidden", editing);
  $("existingElevatorLandingFields").classList.toggle("deployment-hidden", isNew);
  $("newElevatorLandingFields").classList.toggle("deployment-hidden", !isNew);
  $("confirmElevatorLanding").textContent = editing ? "保存共享配置" : "确认放置";
  $("confirmElevatorLanding").disabled = !elevatorLandingDraft || (!isNew && !linked);
  $("elevatorLandingMessage").textContent = isNew
    ? editing
      ? "修改后会同步应用到该物理电梯的所有地图落点。"
      : "共享编号、协议和服务楼层只在这里填写一次。"
    : "当前地图将保存独立的电梯门方向、尺寸和候梯距离。";
}
function openElevatorLandingDialog(point) {
  elevatorLandingDraft = { point };
  $("elevatorLandingButtonFloor").value = "";
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
          }),
        },
      );
      renderProject(data.project);
      const component = data.project.components.find((item) => item.id === selectedComponent?.id);
      if (component) selectComponent(component);
      closeElevatorLandingDialog();
      note("mapToolHint", "共享电梯配置已更新；所有关联地图均使用新的协议和服务楼层。");
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
$("cancelLocalizationBinding").addEventListener("click", closeLocalizationBinding);
$("saveLocalizationBinding").addEventListener("click", saveLocalizationBinding);
$("deleteLocalizationBinding").addEventListener("click", deleteLocalizationBinding);
$("localizationBindingType").addEventListener("change", localizationTypeChanged);
$("cancelLocalizationRoute").addEventListener("click", closeLocalizationRoute);
$("saveLocalizationRoute").addEventListener("click", saveLocalizationRoute);
$("resetLocalizationRoute").addEventListener("click", resetLocalizationRoute);
$("deleteLocalizationRoute").addEventListener("click", deleteLocalizationRoute);
$("localizationRouteMembership").addEventListener("change", (event) => {
  if (!localizationRouteDraft || !event.target.matches("[data-route-include]")) return;
  localizationRouteDraft = setRouteBindingIncluded(localizationRouteDraft, localizationBindings(), event.target.dataset.routeInclude, event.target.checked);
  renderLocalizationRouteDialog();
});
$("localizationRouteLinks").addEventListener("change", (event) => {
  if (!localizationRouteDraft) return;
  if (event.target.matches("[data-route-start]")) {
    localizationRouteDraft.task_start_waypoint_id = event.target.value;
  } else if (event.target.matches("[data-route-target]")) {
    localizationRouteDraft.task_target_waypoint_id = event.target.value;
  } else if (event.target.matches("[data-route-anchor]")) {
    localizationRouteDraft.links[Number(event.target.dataset.routeAnchor)].anchor = routeAnchorForValue(event.target.value);
  } else return;
  renderLocalizationRouteDialog();
});
$("localizationRouteLinks").addEventListener("click", (event) => {
  const button = event.target.closest("[data-route-move]");
  if (!button || !localizationRouteDraft) return;
  const index = Number(button.dataset.routeIndex);
  localizationRouteDraft = moveRouteBinding(localizationRouteDraft, index, button.dataset.routeMove === "up" ? -1 : 1);
  ensureRouteLinks();
  renderLocalizationRouteDialog();
});
document.addEventListener("click", (event) => {
  const button = event.target.closest(".edit-localization-binding");
  if (button) openLocalizationBinding(localizationBindings().find((item) => item.id === button.dataset.bindingId));
  const routeButton = event.target.closest(".edit-localization-route");
  if (routeButton) openLocalizationRoute(routeButton.dataset.routeBuilding, routeButton.dataset.routeUnit);
});
$("componentAttributeFields").addEventListener("click", (event) => {
  const button = event.target.closest(".edit-shared-elevator");
  if (button) openPhysicalElevatorEditor(button.dataset.physicalElevatorId);
});
function openComponentPopover(component, event) {
  selectComponent(component);
  const popover = $("componentPopover");
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
  } catch (error) {
    note("mapToolHint", error.message, true);
  }
});
$("deleteComponent").addEventListener("click", async () => {
  if (!selectedComponent || !selectedProject) return;
  try {
    await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/components/${encodeURIComponent(selectedComponent.id)}`,
      { method: "DELETE" },
    );
    selectComponent(null);
    closeComponentPopover();
    await openProject(selectedProject.id);
  } catch (error) {
    note("mapToolHint", error.message, true);
  }
});
$("deleteWaypoint").addEventListener("click", async () => {
  if (!selectedProject || !selectedWaypoint) return;
  if (!window.confirm(`删除“${selectedWaypoint.label || "此标记"}”？已保存定位路线引用它时会先阻止删除。`)) return;
  try {
    await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/waypoints/${encodeURIComponent(selectedWaypoint.id)}`,
      { method: "DELETE" },
    );
    closeWaypointPopover();
    await openProject(selectedProject.id);
    note("mapToolHint", "地图标记已删除；如该点用于定位路线，请重新选择中间过渡锚点。");
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
          floor: $("instanceFloor").value,
          label: activeMap.label,
        }),
      },
    );
    renderProject(data.project);
    note("instanceMessage", "地图实例已加入部署拓扑。");
  } catch (error) {
    note("instanceMessage", error.message, true);
  }
});
$("assignMapStage").addEventListener("click", async () => {
  if (!selectedProject || !activeMap) return;
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/map-stages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          map_asset_id: activeMap.id,
          stage: $("mapStageAssignment").value,
        }),
      },
    );
    topology = { ...topology, stages: data.stage_plan.stages };
    renderProject(data.project);
    await refreshTopology();
    note("stageAssignmentMessage", "当前地图的部署阶段已保存。");
  } catch (error) {
    note("stageAssignmentMessage", error.message, true);
  }
});
$("saveTaskCompilerConfig").addEventListener("click", saveTaskCompilerConfig);
$("generateTaskCompilerPreview").addEventListener("click", refreshTaskCompilerPreview);
$("downloadTaskCompilerBundle").addEventListener("click", downloadTaskCompilerBundle);
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
            }),
          },
        );
        renderProject(data.project);
        note("mapToolHint", "已标记过渡点；需要时可作为中间切图锚点，速度沿用下一个点。");
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
  if (event.key !== "Escape" || activeTool === "pan") return;
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
canvas.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  if (taskPreviewOpen) return;
  const hit = componentAt(event);
  if (hit) openComponentPopover(hit, event);
  else {
    const waypoint = waypointAt(event);
    if (waypoint) openWaypointPopover(waypoint, event);
    else {
      closeComponentPopover();
      closeWaypointPopover();
    }
  }
});
$("closeComponentPopover").addEventListener("click", closeComponentPopover);
$("closeWaypointPopover").addEventListener("click", closeWaypointPopover);
canvas.addEventListener("pointermove", (event) => {
  if (drag) {
    mapView.x = drag.viewX + event.clientX - drag.x;
    mapView.y = drag.viewY + event.clientY - drag.y;
    drawMap();
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
      drawMap();
      return;
    }
    if (activeTool === "erase_brush") {
      eraserHoverPoint = pointIsOnActiveMap(pointerWorld) ? pointerWorld : null;
      canvas.style.cursor = "crosshair";
      drawMap();
      return;
    }
    if (componentDrag) {
      componentDrag.x = x;
      componentDrag.y = y;
      drawMap();
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
      $("componentSizeReadout").textContent =
        `${componentResize.attributes.width_m.toFixed(2)} m × ${componentResize.attributes.height_m.toFixed(2)} m`;
      drawMap();
      return;
    }
    if (componentRotate) {
      const center = componentCanvasPoint(componentRotate);
      const pointer = canvasPointFromEvent(event);
      const rawYaw = -Math.atan2(pointer.y - center.y, pointer.x - center.x);
      const increment = Math.PI / 18;
      const snappedYaw = Math.round(rawYaw / increment) * increment;
      componentRotate.yaw = Math.max(-Math.PI, Math.min(Math.PI, snappedYaw));
      $("componentYaw").value = componentRotate.yaw.toFixed(3);
      drawMap();
      return;
    }
    if (!drag) {
      canvas.style.cursor = rotateHandleAt(event)
        ? "crosshair"
        : resizeHandleAt(event)
          ? "nwse-resize"
          : componentAt(event)
            ? "move"
            : "grab";
    }
  }
});
canvas.addEventListener("pointerleave", () => {
  if (!eraserHoverPoint) return;
  eraserHoverPoint = null;
  drawMap();
});
canvas.addEventListener("pointerup", async (event) => {
  drag = null;
  canvas.style.cursor = activeTool === "erase_brush" ? "crosshair" : "grab";
  if (eraserStroke) {
    trackEraserStroke(event.getCoalescedEvents?.() || [event]);
    const stroke = eraserStroke;
    eraserStroke = null;
    drawMap();
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
    return;
  }
  if (componentRotate && selectedProject) {
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
    } catch (error) {
      note("mapToolHint", error.message, true);
    }
    componentRotate = null;
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
    drawMap();
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
document.addEventListener("click", (event) => {
  const button = event.target.closest(".delete-waypoint");
  if (!button || !selectedProject) return;
  request(
    `/api/deployments/${encodeURIComponent(selectedProject.id)}/waypoints/${encodeURIComponent(button.dataset.id)}`,
    { method: "DELETE" },
  )
    .then(() => openProject(selectedProject.id))
    .catch((error) => note("mapToolHint", error.message, true));
});
window.addEventListener("resize", scheduleCanvasResize);
if ("ResizeObserver" in window) {
  new ResizeObserver(scheduleCanvasResize).observe(canvas);
}
resizeCanvas();
renderDeploymentGuide();
loadProjects();
refreshMappingStatus();
