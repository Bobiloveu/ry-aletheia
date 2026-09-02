const $ = (id) => document.getElementById(id);
const esc = (value) => {
  const node = document.createElement("span");
  node.textContent = value ?? "";
  return node.innerHTML;
};
let selectedProject = null;
let activeMap = null;
let mapImage = null;
let activeTool = "pan";
let selectedComponent = null;
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
let transitionDraft = null;
let routeDraft = [];
const mapView = { scale: 40, x: 0, y: 0 };
const canvas = $("mapCanvas");
const context = canvas.getContext("2d");
let canvasResizeFrame = null;
document.body.classList.add("deployment-no-project", "deployment-no-map");
const DEFAULT_COMPONENT_TEMPLATES = {
  access_protocols: [
    { id: "bluetooth", label: "蓝牙" },
    { id: "4g", label: "4G" },
  ],
  elevator_protocols: [
    { id: "bluetooth", label: "蓝牙" },
    { id: "4g", label: "4G" },
  ],
};
const COMPONENT_SPECS = {
  start: {
    name: "起点",
    fields: [
      {
        key: "start_action",
        label: "起始动作",
        type: "select",
        options: [
          ["dispatch", "派送起始"],
          ["return", "返程起始"],
        ],
      },
    ],
  },
  target: {
    name: "目标点",
    fields: [
      {
        key: "arrival_action",
        label: "到达动作",
        type: "select",
        options: [
          ["deliver", "投递"],
          ["wait", "等待"],
          ["return", "返程"],
        ],
      },
    ],
  },
  elevator: {
    name: "电梯",
    fields: [
      {
        key: "elevator_id",
        label: "电梯编号",
        type: "text",
        placeholder: "例如：E-01",
        default: "",
      },
      {
        key: "elevator_protocol",
        label: "梯控协议",
        type: "select",
        protocolCategory: "elevator_protocols",
        default: "bluetooth",
      },
      {
        key: "min_floor",
        label: "最低逻辑楼层",
        type: "number",
        step: "1",
        default: 1,
      },
      {
        key: "max_floor",
        label: "最高逻辑楼层",
        type: "number",
        step: "1",
        default: 1,
      },
      {
        key: "map_floor",
        label: "当前地图所在楼层",
        type: "number",
        step: "1",
        default: 1,
      },
    ],
  },
  gate: {
    name: "闸机",
    fields: [
      {
        key: "gate_id",
        label: "闸机编号",
        type: "text",
        placeholder: "例如：G-01",
      },
      {
        key: "access_protocol",
        label: "控制协议",
        type: "select",
        protocolCategory: "access_protocols",
        default: "bluetooth",
      },
      {
        key: "speed_profile",
        label: "速度模式",
        type: "select",
        options: [
          ["single_point", "常规"],
          ["slow_point", "减速"],
          ["narrow_point", "窄通道"],
        ],
      },
    ],
  },
  auto_door: {
    name: "自动门",
    fields: [
      {
        key: "door_id",
        label: "门编号",
        type: "text",
        placeholder: "例如：D-01",
      },
      {
        key: "access_protocol",
        label: "控制协议",
        type: "select",
        protocolCategory: "access_protocols",
        default: "bluetooth",
      },
      {
        key: "speed_profile",
        label: "速度模式",
        type: "select",
        options: [
          ["single_point", "常规"],
          ["slow_point", "减速"],
        ],
      },
    ],
  },
  narrow_passage: {
    name: "窄通道",
    fields: [
      {
        key: "speed_profile",
        label: "速度模式",
        type: "select",
        options: [
          ["narrow_point", "窄通道"],
          ["slow_point", "减速"],
          ["single_point", "常规"],
        ],
      },
    ],
  },
  ramp: {
    name: "坡道",
    fields: [
      {
        key: "speed_profile",
        label: "速度模式",
        type: "select",
        options: [
          ["slow_point", "减速"],
          ["single_point", "常规"],
        ],
      },
    ],
  },
  slow_zone: {
    name: "减速区",
    fields: [
      {
        key: "speed_profile",
        label: "速度模式",
        type: "select",
        options: [
          ["slow_point", "减速"],
          ["single_point", "常规"],
        ],
      },
    ],
  },
};
const componentName = (component) =>
  COMPONENT_SPECS[component.kind]?.name || component.label || component.kind;
const protocolOptions = (category) => {
  const options = selectedProject?.component_templates?.[category];
  return Array.isArray(options) && options.length
    ? options.map((item) => [item.id, item.label])
    : (DEFAULT_COMPONENT_TEMPLATES[category] || []).map((item) => [
        item.id,
        item.label,
      ]);
};
async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}
function note(id, text, error = false) {
  const target = $(id);
  target.textContent = text;
  target.style.color = error ? "#ff899a" : "#35d69c";
}
function renderMapStages() {
  if (!selectedProject) return;
  const model = selectedProject.scene_model || "indoor_outdoor";
  const fallback = model === "indoor_outdoor"
    ? ["室外 / 起点", "大厅 / 首层", "目标楼层"]
    : model === "indoor"
      ? ["大厅 / 首层", "目标楼层"]
      : ["室外 / 起点"];
  const stages = topology?.stages?.length
    ? topology.stages
    : fallback.map((label, index) => ({ stage: String(index), label, status: "missing" }));
  $("mapStageSummary").innerHTML = stages
    .map((stage, index) => `<span class="${stage.status === "complete" ? "done" : stage.status === "editing" ? "active" : ""}"><b>${stage.status === "complete" ? "✓" : index + 1}</b>${esc(stage.map_label || stage.label)}</span>`)
    .join("");
  const current = topology?.stages?.find((stage) => stage.status !== "complete");
  $("importMessage").textContent = current
    ? `当前待完善：${current.label}。可导入既有地图或使用下方车端建图。`
    : "地图阶段已齐全；请继续检查交接、路线与虚拟墙。";
}

function renderTopology() {
  const holder = $("topologyPreview");
  const state = $("topologyState");
  const stageSelect = $("mapStageAssignment");
  const assignmentControls = $("stageAssignmentControls");
  if (!selectedProject || !topology) {
    state.textContent = "等待项目";
    state.className = "badge muted";
    holder.innerHTML = '<div class="page-empty">阶段、交接点与路线完成后，会在这里显示只读检查结果。</div>';
    assignmentControls.classList.add("deployment-hidden");
    return;
  }
  state.textContent = topology.valid ? "拓扑完整" : "需完善";
  state.className = `badge ${topology.valid ? "success" : "muted"}`;
  const stages = topology.stages || [];
  holder.innerHTML = [
    ...stages.map((stage) => `<div class="topology-stage ${esc(stage.status)}"><span>${stage.status === "complete" ? "✓" : stage.status === "editing" ? "•" : "—"}</span><div><b>${esc(stage.label)}</b><small>${esc(stage.map_label || "尚未绑定地图")}</small></div></div>`),
    ...(topology.errors || []).map((error) => `<p class="topology-error">${esc(error)}</p>`),
    `<p class="topology-meta">${(topology.transitions || []).length} 条地图衔接 · ${(topology.routes || []).length} 条地图内路线 · ${topology.virtual_wall_count || 0} 个虚拟墙</p>`,
  ].join("");
  const mapStage = stages.find((stage) => stage.map_asset_id === activeMap?.id)?.stage;
  assignmentControls.classList.toggle("deployment-hidden", !activeMap || !stages.length);
  stageSelect.innerHTML = stages.map((stage) => `<option value="${esc(stage.stage)}" ${stage.stage === mapStage ? "selected" : ""}>${esc(stage.label)}</option>`).join("");
  $("stageAssignmentMessage").textContent = activeMap
    ? `${activeMap.label}${mapStage ? ` 当前属于：${stages.find((stage) => stage.stage === mapStage)?.label}` : " 尚未绑定地图阶段"}。`
    : "选择地图后可检查其阶段归属。";
  $("routeDraftMessage").textContent = routeDraft.length
    ? `已选择 ${routeDraft.length} 个当前地图路线点。`
    : "选择“路线”后，按顺序点击当前地图的 Waypoint。";
  $("saveRoute").disabled = routeDraft.length < 2;
  $("clearRouteDraft").disabled = !routeDraft.length;
}

async function refreshTopology() {
  if (!selectedProject) return;
  try {
    const data = await request(`/api/deployments/${encodeURIComponent(selectedProject.id)}/topology`);
    topology = data.topology;
    renderMapStages();
    renderTopology();
    drawMap();
  } catch (error) {
    topology = null;
    renderTopology();
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
  selectedProject = project;
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
  $("sceneModelControls").classList.remove("deployment-hidden");
  $("sceneModel").value = project.scene_model || "indoor_outdoor";
  $("sceneModelMessage").textContent = `当前场景模型：${$("sceneModel").selectedOptions[0].textContent}。`;
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
  renderComponentTemplates();
  renderMapStages();
  renderTopology();
  renderMappingStatus();
  if (!activeMap && maps.length) selectMap(maps[0]);
  else drawMap();
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
  drawMap();
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
  return {
    width: Number(item.attributes?.width_m || 0.8) * mapView.scale,
    height: Number(item.attributes?.height_m || 0.8) * mapView.scale,
  };
}
function componentCanvasPoint(item) {
  return {
    x: mapView.x + (item.x - activeMap.origin[0]) * mapView.scale,
    y:
      mapView.y +
      (activeMap.height * activeMap.resolution_m -
        (item.y - activeMap.origin[1])) *
        mapView.scale,
  };
}
function worldCanvasPoint(point) {
  return {
    x: mapView.x + (point.x - activeMap.origin[0]) * mapView.scale,
    y:
      mapView.y +
      (activeMap.height * activeMap.resolution_m -
        (point.y - activeMap.origin[1])) *
        mapView.scale,
  };
}
function canvasPointFromEvent(event) {
  const box = canvas.getBoundingClientRect();
  return { x: event.clientX - box.left, y: event.clientY - box.top };
}
function worldPointFromEvent(event) {
  const point = canvasPointFromEvent(event);
  return {
    x: activeMap.origin[0] + (point.x - mapView.x) / mapView.scale,
    y:
      activeMap.origin[1] +
      (activeMap.height * activeMap.resolution_m -
        (point.y - mapView.y) / mapView.scale),
  };
}
function pointIsOnActiveMap(point) {
  return (
    point.x >= activeMap.origin[0] &&
    point.x <= activeMap.origin[0] + activeMap.width * activeMap.resolution_m &&
    point.y >= activeMap.origin[1] &&
    point.y <= activeMap.origin[1] + activeMap.height * activeMap.resolution_m
  );
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
  const point = componentCanvasPoint(item);
  const pointer = canvasPointFromEvent(event);
  const dx = pointer.x - point.x;
  const dy = pointer.y - point.y;
  const yaw = Number(item.yaw || 0);
  return {
    x: Math.cos(yaw) * dx - Math.sin(yaw) * dy,
    y: Math.sin(yaw) * dx + Math.cos(yaw) * dy,
  };
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
  context.clearRect(0, 0, box.width, box.height);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, box.width, box.height);
  if (!activeMap || !mapImage) {
    const preview = mappingSession?.preview;
    if (!liveMapImage || !preview?.width || !preview?.height) return;
    const scale = Math.min((box.width - 48) / preview.width, (box.height - 48) / preview.height);
    const width = preview.width * scale;
    const height = preview.height * scale;
    context.imageSmoothingEnabled = false;
    context.drawImage(liveMapImage, (box.width - width) / 2, (box.height - height) / 2, width, height);
    context.strokeStyle = "#0a84ff";
    context.strokeRect((box.width - width) / 2, (box.height - height) / 2, width, height);
    return;
  }
  drawGrid(box.width, box.height);
  const pixels = mapView.scale * activeMap.resolution_m;
  context.save();
  context.imageSmoothingEnabled = false;
  context.drawImage(
    mapImage,
    mapView.x,
    mapView.y,
    activeMap.width * pixels,
    activeMap.height * pixels,
  );
  context.strokeStyle = "#38d59a";
  context.lineWidth = 1.5;
  context.strokeRect(
    mapView.x,
    mapView.y,
    activeMap.width * pixels,
    activeMap.height * pixels,
  );
  context.save();
  context.beginPath();
  context.rect(
    mapView.x,
    mapView.y,
    activeMap.width * pixels,
    activeMap.height * pixels,
  );
  context.clip();
  drawMapEdits();
  context.restore();
  drawMapRoutes();
  for (const point of (selectedProject?.waypoints || []).filter(
    (item) => item.map_asset_id === activeMap.id && !item.generated_by,
  )) {
    const px = mapView.x + (point.x - activeMap.origin[0]) * mapView.scale;
    const py =
      mapView.y +
      (activeMap.height * activeMap.resolution_m -
        (point.y - activeMap.origin[1])) *
        mapView.scale;
    const palette = { start: "#39dcad", target: "#ffbd61", map_transition: "#b995ef" };
    const color = palette[point.kind] || "#5bb8ff";
    context.fillStyle = color;
    context.beginPath();
    context.arc(px, py, point.kind === "map_transition" ? 7 : 5, 0, Math.PI * 2);
    context.fill();
    if (point.kind === "map_transition") {
      context.strokeStyle = "#fff";
      context.lineWidth = 1.5;
      context.beginPath();
      context.arc(px, py, 3, 0, Math.PI * 2);
      context.stroke();
    }
    context.fillStyle = "rgba(18, 28, 34, .9)";
    context.font = "600 10px system-ui, sans-serif";
    context.textAlign = "left";
    context.fillText(point.label, px + 8, py - 8);
  }
  for (const item of (selectedProject?.components || []).filter(
    (component) => component.map_asset_id === activeMap.id,
  )) {
    const px = mapView.x + (item.x - activeMap.origin[0]) * mapView.scale;
    const py =
      mapView.y +
      (activeMap.height * activeMap.resolution_m -
        (item.y - activeMap.origin[1])) *
        mapView.scale;
    drawComponentSymbol(item, px, py);
  }
  context.restore();
}
function selectMap(map) {
  if (!selectedProject) return;
  if (routeDraft.length && activeMap?.id !== map.id) routeDraft = [];
  activeMap = map;
  document.body.classList.remove("deployment-no-map");
  mapImage = new Image();
  mapImage.onload = fitMap;
  mapImage.src = `/api/deployments/${encodeURIComponent(selectedProject.id)}/maps/${encodeURIComponent(map.id)}/preview.png`;
  $("mapCanvasEmpty").classList.add("hidden");
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
            `<div class="asset-row project-row"><div><b>${esc(item.name)}</b><small>${esc(item.id)} · ${item.map_count} 张地图 · 更新于 ${esc(item.updated_at)}</small></div><button class="compact-action open-project" data-id="${esc(item.id)}" type="button">打开</button></div>`,
          )
          .join("")
      : '<div class="page-empty">还没有部署项目。</div>';
  } catch (error) {
    $("projectList").innerHTML =
      `<div class="page-empty">读取失败：${esc(error.message)}</div>`;
  }
}
async function openProject(id) {
  const data = await request(`/api/deployments/${encodeURIComponent(id)}`);
  topology = null;
  renderProject(data.project);
  await refreshMappingStatus();
  await refreshTopology();
}
$("saveSceneModel").addEventListener("click", async () => {
  if (!selectedProject) return;
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/scene-model`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scene_model: $("sceneModel").value }),
      },
    );
    renderProject(data.project);
    await refreshTopology();
    note("sceneModelMessage", "场景模型已保存；地图段数量已按该模型调整。");
  } catch (error) {
    note("sceneModelMessage", error.message, true);
  }
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
        kind: $("mappingKind").value,
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
    payload.append("kind", $("mapKind").value);
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
    note("mapFolderMessage", "地图文件已导入；可继续选择下一张地图。 ");
    note("importMessage", `已导入 ${data.map.label}；机器人原地图未被修改。`);
    await loadProjects();
  } catch (error) {
    note("importMessage", error.message, true);
  }
});
$("mapFolder").addEventListener("change", () => {
  const files = Array.from($("mapFolder").files || []);
  const mapYaml = files.filter((file) => (file.webkitRelativePath || file.name).split("/").pop().toLowerCase() === "map.yaml");
  if (mapYaml.length === 1) {
    const relative = mapYaml[0].webkitRelativePath || mapYaml[0].name;
    const name = relative.split("/").slice(0, -1).join(" / ");
    if (!$("mapLabel").value.trim()) $("mapLabel").value = name;
    note("mapFolderMessage", `已选择 ${files.length} 个文件，将使用 ${relative}。`);
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
          ? protocolOptions(field.protocolCategory)
          : field.options;
        return `<label>${esc(field.label)}<select data-component-attribute="${esc(field.key)}">${options.map(([option, title]) => `<option value="${esc(option)}" ${String(value) === option ? "selected" : ""}>${esc(title)}</option>`).join("")}</select></label>`;
      }
      return `<label>${esc(field.label)}<input data-component-attribute="${esc(field.key)}" type="${esc(field.type)}" value="${esc(value)}" ${field.placeholder ? `placeholder="${esc(field.placeholder)}"` : ""} ${field.step ? `step="${esc(field.step)}"` : ""} /></label>`;
    })
    .join("");
  const physicalFloor =
    component.kind === "elevator"
      ? `<div class="physical-floor"><span>自动计算的物理楼层</span><strong id="physicalFloorValue">${Number(attributes.map_floor ?? 1) + 1}</strong><small>物理楼层 = 当前地图所在楼层 + 1（1F → 2）</small></div>`
      : "";
  $("componentAttributeFields").innerHTML =
    `${controls}${physicalFloor}` ||
    '<p class="component-no-options">此组件暂没有附加部署属性。</p>';
}
function refreshPhysicalFloor() {
  const value = $("physicalFloorValue");
  if (!value) return;
  const mapFloor = Number(
    document.querySelector('[data-component-attribute="map_floor"]')?.value ??
      1,
  );
  value.textContent = String(mapFloor + 1);
}
$("componentAttributeFields").addEventListener("input", refreshPhysicalFloor);
function closeComponentPopover() {
  $("componentPopover").classList.add("deployment-hidden");
}
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
  return (selectedProject?.components || [])
    .filter((item) => item.map_asset_id === activeMap.id)
    .reverse()
    .find((item) => {
      const point = componentLocalPoint(item, event);
      const { width, height } = componentDimensions(item);
      return Math.abs(point.x) <= width / 2 && Math.abs(point.y) <= height / 2;
    });
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
  if (activeTool !== "transition_link") return;
  if (!transitionDraft) {
    transitionDraft = { map_id: activeMap.id, waypoint_id: waypoint.id, label: waypoint.label };
    note("mapToolHint", `已选择交接起点“${waypoint.label}”；切换到下一张相邻地图后选择入口点。`);
    return;
  }
  if (transitionDraft.map_id === activeMap.id) {
    note("mapToolHint", "交接点必须位于另一张相邻地图；请切换地图后再选择入口。", true);
    return;
  }
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/transitions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          from_map_asset_id: transitionDraft.map_id,
          from_waypoint_id: transitionDraft.waypoint_id,
          to_map_asset_id: activeMap.id,
          to_waypoint_id: waypoint.id,
          label: `${transitionDraft.label} 至 ${waypoint.label}`,
        }),
      },
    );
    transitionDraft = null;
    renderProject(data.project);
    await refreshTopology();
    note("mapToolHint", "地图衔接已保存；坐标不会在两张地图之间转换。" );
  } catch (error) {
    note("mapToolHint", error.message, true);
  }
}

async function placeMapTransitionPoint(point) {
  if (!selectedProject || !activeMap) return;
  const data = await request(
    `/api/deployments/${encodeURIComponent(selectedProject.id)}/waypoints`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        map_id: activeMap.id,
        kind: "map_transition",
        label: `${activeMap.label} 交接点`,
        x: point.x,
        y: point.y,
        yaw: 0,
      }),
    },
  );
  renderProject(data.project);
  await refreshTopology();
  note("mapToolHint", "已放置交接点；使用“衔接”依次选择相邻地图的两个交接点。" );
}
function resizeHandleAt(event) {
  if (!selectedComponent || selectedComponent.map_asset_id !== activeMap?.id)
    return false;
  const point = componentLocalPoint(selectedComponent, event);
  const { width, height } = componentDimensions(selectedComponent);
  return Math.hypot(point.x - width / 2 - 9, point.y - height / 2 - 9) <= 16;
}
function rotateHandleAt(event) {
  if (!selectedComponent || selectedComponent.map_asset_id !== activeMap?.id)
    return false;
  const point = componentLocalPoint(selectedComponent, event);
  const { width, height } = componentDimensions(selectedComponent);
  return Math.hypot(point.x - width / 2 - 29, point.y - height / 2 - 9) <= 13;
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
$("saveRoute").addEventListener("click", async () => {
  if (!selectedProject || !activeMap || routeDraft.length < 2) return;
  try {
    const data = await request(
      `/api/deployments/${encodeURIComponent(selectedProject.id)}/routes`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          map_asset_id: activeMap.id,
          label: `${activeMap.label} 路线`,
          waypoint_ids: routeDraft,
        }),
      },
    );
    routeDraft = [];
    renderProject(data.project);
    await refreshTopology();
    note("mapToolHint", "当前地图路线已保存；跨地图路段由 Transition 单独表示。" );
  } catch (error) {
    note("mapToolHint", error.message, true);
  }
});
$("clearRouteDraft").addEventListener("click", () => {
  routeDraft = [];
  renderTopology();
  drawMap();
  note("mapToolHint", "当前路线选择已清空；已保存路线不会受影响。" );
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
  if (event.button === 1 || (spacePanActive && event.button === 0)) {
    beginCanvasPan(event);
    return;
  }
  if (event.button !== 0) return;
  if (
    (activeTool === "transition_link" || activeTool === "route_link") &&
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
      if (placementKind === "map_transition") {
        await placeMapTransitionPoint(point);
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
  const hit = componentAt(event);
  if (hit) openComponentPopover(hit, event);
  else closeComponentPopover();
});
$("closeComponentPopover").addEventListener("click", closeComponentPopover);
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
    const old = mapView.scale;
    const pointer = canvasPointFromEvent(event);
    mapView.scale = Math.max(
      5,
      Math.min(500, old * (event.deltaY < 0 ? 1.12 : 0.89)),
    );
    mapView.x = pointer.x - ((pointer.x - mapView.x) * mapView.scale) / old;
    mapView.y = pointer.y - ((pointer.y - mapView.y) * mapView.scale) / old;
    drawMap();
  },
  { passive: false },
);
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
loadProjects();
refreshMappingStatus();
