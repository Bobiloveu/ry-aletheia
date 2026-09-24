const STEP_LABELS = {
  project: "创建项目",
  maps: "准备地图",
  annotations: "标记地图",
  localization: "配置定位路线",
  export: "校验并导出",
};

const WORKFLOW_STAGE_ORDER = ["project", "maps", "annotations", "localization", "export"];

export function isDeploymentStageUnlocked(currentStage, requiredStage) {
  const currentIndex = WORKFLOW_STAGE_ORDER.indexOf(currentStage);
  const requiredIndex = WORKFLOW_STAGE_ORDER.indexOf(requiredStage);
  return currentIndex >= 0 && requiredIndex >= 0 && currentIndex >= requiredIndex;
}

export function resolveDeploymentViewStage(currentStage, requestedStage) {
  if (!requestedStage || !isDeploymentStageUnlocked(currentStage, requestedStage)) {
    return currentStage;
  }
  return requestedStage;
}

const ACTIONS = {
  createProject: { label: "填写项目名称", target: "projectName" },
  confirmScene: { label: "配置部署流程", target: "deploymentFlowEditor" },
  importMap: { label: "导入第一张地图", target: "mapFolder" },
  importNextMap: { label: "导入下一张地图", target: "mapFolder" },
  assignStage: { label: "完善地图阶段", target: "mapStageAssignment" },
  configureMapInstance: { label: "设置部署拓扑位置", target: "instanceControls" },
  annotate: { label: "标记当前地图", target: "mapWorkspace" },
  bindLocalization: { label: "设置地图运行角色", target: "openLocalizationBinding" },
  editRoute: { label: "确认地图经过顺序", target: "openLocalizationRoute" },
  saveCompilerIdentity: { label: "保存小区信息", target: "taskCompilerCommunity" },
  preview: { label: "生成实验预览", target: "generateTaskCompilerPreview" },
  export: { label: "导出部署包", target: "downloadTaskCompilerBundle" },
};

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

function list(value) {
  return Array.isArray(value) ? value : [];
}

export function nextMapImportDraft() {
  return {
    mapSource: null,
    fileSummary: null,
    mapLabel: "",
    latestCreatedMapId: null,
    receipt: null,
  };
}

export function deriveMapImportGuidance(topology, targetStageId = null) {
  const stages = list(topology?.stages);
  const requestedIndex = targetStageId
    ? stages.findIndex((stage) => stage.stage === targetStageId)
    : -1;
  const requestedStage = stages[requestedIndex] || null;
  const targetIndex = requestedStage && !requestedStage.map_asset_id
    ? requestedIndex
    : stages.findIndex((stage) => !stage.map_asset_id);
  const target = stages[targetIndex] || null;
  if (!target) {
    return {
      state: "complete",
      stageLabel: null,
      position: null,
      title: "地图阶段已齐全",
      detail: "所有已配置阶段均已绑定地图，不需要继续导入。",
      fileLabel: "选择地图文件",
      nameLabel: "显示名称",
      namePlaceholder: "室外地图 / 电梯大厅",
    };
  }
  const completedLabels = stages
    .slice(0, targetIndex)
    .filter((stage) => stage.map_asset_id)
    .map((stage) => stage.map_label || stage.label);
  const completed = completedLabels.length
    ? `${completedLabels.join("、")}已完成；`
    : "";
  const stageLabel = target.label;
  return {
    state: "target",
    stageLabel,
    position: `第 ${targetIndex + 1} / ${stages.length} 张`,
    title: `本次请导入：${stageLabel}地图`,
    detail: `${completed}导入后会自动绑定到“${stageLabel}”。`,
    fileLabel: `选择“${stageLabel}”地图文件`,
    nameLabel: `显示名称（${stageLabel}）`,
    namePlaceholder: `例如：${stageLabel}`,
  };
}

function mapLabel(map, fallback) {
  return map?.label || map?.id || fallback;
}

export function deriveLocalizationGuidance(project, activeMapId = null) {
  const maps = list(project?.map_assets);
  const bindings = list(project?.localization_bindings);
  const routes = list(project?.localization_routes);
  const activeMap = maps.find((map) => map.id === activeMapId) || null;
  const boundMapIds = new Set(bindings.map((binding) => binding.map_asset_id));
  const activeBindings = activeMap
    ? bindings.filter((binding) => binding.map_asset_id === activeMap.id)
    : [];
  const missingMap = maps.find((map) => !boundMapIds.has(map.id)) || null;
  const configuredCount = maps.filter((map) => boundMapIds.has(map.id)).length;
  const rolesComplete = Boolean(maps.length) && !missingMap;
  const activeBinding = activeBindings[0] || null;
  const routeIdentity = activeBinding
    ? { building: activeBinding.building || "", unit: activeBinding.unit || "" }
    : null;
  const configuredRoute = routeIdentity
    ? routes.find((route) => route.building === routeIdentity.building && route.unit === routeIdentity.unit)
    : null;

  if (!activeMap) {
    return {
      state: "select_map",
      currentMapLabel: null,
      detail: "先在地图列表中选择一张地图，再确定它承担的运行角色。",
      primaryAction: { label: "选择一张地图", target: "mapList" },
      roles: { complete: rolesComplete, configured: configuredCount, total: maps.length },
      route: { available: false, configured: false, identity: null },
    };
  }
  if (!activeBinding) {
    return {
      state: "needs_role",
      currentMapLabel: mapLabel(activeMap, "当前地图"),
      detail: "先确定这张地图承担的运行角色；这会决定机器人进入此地图时采用的定位配置。",
      primaryAction: { label: `设置 ${mapLabel(activeMap, "当前地图")} 的运行角色`, target: "openLocalizationBinding" },
      roles: { complete: false, configured: configuredCount, total: maps.length },
      route: { available: false, configured: false, identity: null },
    };
  }
  if (!rolesComplete) {
    return {
      state: "needs_other_role",
      currentMapLabel: mapLabel(activeMap, "当前地图"),
      detail: `“${mapLabel(missingMap, "另一张地图")}”还未确定运行角色。完成每张地图的角色后，才能确认机器人经过地图的顺序。`,
      primaryAction: { label: `设置 ${mapLabel(missingMap, "待配置地图")} 的运行角色`, target: "mapList" },
      roles: { complete: false, configured: configuredCount, total: maps.length },
      route: { available: false, configured: false, identity: routeIdentity },
    };
  }
  return {
    state: configuredRoute ? "route_ready" : "configure_route",
    currentMapLabel: mapLabel(activeMap, "当前地图"),
    detail: configuredRoute
      ? "地图角色和经过顺序已保存。可检查路线；返程会由系统按目标层电梯门前呼梯点自动派生。"
      : "所有地图已确定运行角色。接下来确认机器人去程经过的地图顺序和切图依据；返程由系统自动派生。",
    primaryAction: {
      label: configuredRoute ? "检查地图经过顺序" : "确认地图经过顺序",
      target: "openLocalizationRoute",
    },
    roles: { complete: true, configured: configuredCount, total: maps.length },
    route: { available: true, configured: Boolean(configuredRoute), identity: routeIdentity },
  };
}

function stageReady(topology, maps) {
  const stages = list(topology?.stages);
  return Boolean(
    maps.length &&
      stages.length &&
      stages.every((stage) => stage.map_asset_id),
  );
}

function missingMapInstance(project, topology) {
  const instances = list(project?.map_instances);
  const requirements = {
    lobby: { roles: ["lobby"], role: "lobby" },
    target_floor: { roles: ["typical_floor", "floor_override"], role: "typical_floor" },
  };
  for (const stage of list(topology?.stages)) {
    const requirement = requirements[stage.stage];
    if (!requirement || !stage.map_asset_id) continue;
    const matches = instances.filter(
      (instance) => instance?.map_asset_id === stage.map_asset_id && requirement.roles.includes(instance.role),
    );
    if (matches.length !== 1) {
      return {
        mapAssetId: stage.map_asset_id,
        stage: stage.stage,
        stageLabel: stage.label,
        role: requirement.role,
        duplicate: matches.length > 1,
      };
    }
  }
  return null;
}

function topologyReason(topology) {
  const firstError = list(topology?.errors).find(
    (error) => Boolean(error) && !/Transition|地图衔接|转场/.test(String(error)),
  );
  return firstError ? `服务端拓扑校验未通过：${firstError}` : "生成实验预览前还需要通过服务端拓扑校验。";
}

function missingAnnotationMap(project) {
  const maps = list(project?.map_assets);
  const waypoints = list(project?.waypoints);
  return maps.find((map) => !waypoints.some((item) => item.map_asset_id === map.id));
}

function routeReady(project) {
  const maps = list(project?.map_assets);
  const bindings = list(project?.localization_bindings);
  const routes = list(project?.localization_routes);
  const boundMapIds = new Set(bindings.map((item) => item.map_asset_id));
  return Boolean(
      maps.length &&
      maps.every((map) => boundMapIds.has(map.id)) &&
      routes.length &&
      routes.every((route) => (
        route?.task_start_waypoint_id &&
        route?.task_target_waypoint_id
      )),
  );
}

function annotationReady(project) {
  const maps = list(project?.map_assets);
  const waypoints = list(project?.waypoints);
  return Boolean(
    maps.length &&
      maps.every((map) => waypoints.some((item) => item.map_asset_id === map.id)),
  );
}

function step(id, status, detail, reason = "") {
  return { id, label: STEP_LABELS[id], status, detail, reason };
}

function action(id, detail = "") {
  return { id, ...ACTIONS[id], detail };
}

function mapProgress(current, completed = []) {
  return MAP_PROGRESS.map(([id, label]) => ({
    id,
    label,
    status: completed.includes(id)
      ? "complete"
      : id === current
        ? "current"
        : "pending",
  }));
}

function deploymentTask({
  id,
  stageId,
  title,
  detail,
  completionCriterion,
  primaryAction,
  nextTaskLabel,
  progressItems,
  targetMapId = null,
  targetStageId = null,
  instanceRole = null,
  readOnly = false,
}) {
  return {
    id,
    stageId,
    title,
    detail,
    completionCriterion,
    primaryAction,
    nextTaskLabel,
    progressItems,
    targetMapId,
    targetStageId,
    instanceRole,
    readOnly,
  };
}

export function deriveDeploymentTask({
  workflow,
  project,
  topology,
  mappingSession = null,
  draft = {},
  viewedStage = null,
  editingStage = null,
}) {
  const stageId = viewedStage || workflow.current.id;
  if (viewedStage && viewedStage !== workflow.current.id) {
    const reviewed = workflow.steps.find((item) => item.id === viewedStage);
    if (editingStage === viewedStage) {
      const annotationsFinished = viewedStage === "annotations";
      return deploymentTask({
        id: `${viewedStage}.edit`,
        stageId: viewedStage,
        title: annotationsFinished ? "确认地图标记已完成" : `继续修改${reviewed.label}`,
        detail: annotationsFinished
          ? "全部地图均已有标记。你仍可继续补充或调整当前地图；确认后才会进入定位路线。"
          : "编辑仅在现有保存按钮提交后生效；未保存离开不会改变项目事实。",
        completionCriterion: annotationsFinished
          ? "确认当前地图标记已完成"
          : "保存必要修改，并返回当前任务重新确认后续阶段",
        primaryAction: {
          id: "return-current",
          label: annotationsFinished ? "确认标记完成，进入定位路线" : "结束修改并返回",
          target: "deploymentTaskTitle",
        },
        nextTaskLabel: workflow.next.label,
        progressItems: workflow.steps.map((item) => ({
          id: item.id,
          label: item.label,
          status: item.status,
        })),
      });
    }
    return deploymentTask({
      id: `${viewedStage}.review`,
      stageId: viewedStage,
      title: reviewed.label,
      detail: "正在只读回看已完成阶段。",
      completionCriterion: reviewed.detail,
      primaryAction: {
        id: "return-current",
        label: "返回当前任务",
        target: "deploymentTaskTitle",
      },
      nextTaskLabel: workflow.next.label,
      progressItems: workflow.steps.map((item) => ({
        id: item.id,
        label: item.label,
        status: item.status,
      })),
      readOnly: true,
    });
  }
  if (stageId !== "maps") {
    const currentIndex = workflow.steps.findIndex((item) => item.id === stageId);
    return deploymentTask({
      id: `${stageId}.${workflow.next.id}`,
      stageId,
      title: workflow.next.label,
      detail: workflow.next.detail || workflow.current.reason || workflow.current.detail,
      completionCriterion: workflow.current.detail,
      primaryAction: {
        id: workflow.next.id,
        label: workflow.next.label,
        target: workflow.next.target,
      },
      nextTaskLabel: workflow.steps[currentIndex + 1]?.label || "完成部署",
      progressItems: workflow.checklist.map((item, index) => ({
        id: String(index),
        label: item.label,
        status: item.done ? "complete" : "pending",
      })),
      targetMapId: workflow.next.targetMapId || null,
    });
  }

  const stages = list(topology?.stages);
  const instanceNeed = missingMapInstance(project, topology);
  const nextStage = stages.find((item) => !item.map_asset_id) || null;
  const mapImportGuidance = deriveMapImportGuidance(topology, nextStage?.stage);
  const assignedMapIds = new Set(
    stages.map((item) => item.map_asset_id).filter(Boolean),
  );
  const maps = list(project?.map_assets);
  const latestCreatedMap = maps.find(
    (item) => item.id === draft.latestCreatedMapId,
  ) || null;
  const unboundMap =
    (latestCreatedMap && !assignedMapIds.has(latestCreatedMap.id)
      ? latestCreatedMap
      : null) ||
    maps.find((item) => !assignedMapIds.has(item.id)) ||
    null;
  if (unboundMap && nextStage) {
    return deploymentTask({
      id: DEPLOYMENT_TASK_IDS.MAP_ASSIGN,
      stageId,
      title: `绑定“${unboundMap.label || unboundMap.id}”的地图阶段`,
      detail: `将当前地图绑定到“${nextStage.label}”。`,
      completionCriterion: "地图已保存到正确的部署阶段",
      primaryAction: {
        id: "assign-map-stage",
        label: "保存绑定并继续",
        target: "mapStageAssignment",
      },
      nextTaskLabel:
        stages.filter((item) => !item.map_asset_id).length > 1
          ? "准备下一张地图"
          : "标记地图",
      progressItems: mapProgress("assign", ["source", "import", "describe"]),
      targetMapId: unboundMap.id,
      targetStageId: nextStage.stage,
    });
  }
  if (instanceNeed) {
    const roleLabel = instanceNeed.role === "lobby" ? "大厅 / 首层" : "标准层";
    return deploymentTask({
      id: "maps.instance",
      stageId,
      title: `设置“${instanceNeed.stageLabel}”的部署拓扑位置`,
      detail: instanceNeed.duplicate
        ? `“${instanceNeed.stageLabel}”已有多个可用地图实例；编译要求仅保留一个。`
        : `当前地图需要设为“${roleLabel}”，并填写实际楼栋、单元和楼层。`,
      completionCriterion: instanceNeed.duplicate
        ? "仅保留一个符合当前地图阶段的实例"
        : "该地图已建立一个符合阶段用途的部署拓扑位置",
      primaryAction: {
        id: "configure-map-instance",
        label: "设置部署拓扑位置",
        target: "instanceControls",
      },
      nextTaskLabel: instanceNeed.stage === "lobby" ? "设置用户楼层的部署拓扑位置" : "标记地图",
      progressItems: mapProgress("confirm", ["source", "import", "describe", "assign"]),
      targetMapId: instanceNeed.mapAssetId,
      targetStageId: instanceNeed.stage,
      instanceRole: instanceNeed.role,
    });
  }
  if (latestCreatedMap && assignedMapIds.has(latestCreatedMap.id)) {
    return deploymentTask({
      id: DEPLOYMENT_TASK_IDS.MAP_SOURCE,
      stageId,
      title: "选择地图来源",
      detail: "当前地图“" + mapLabel(latestCreatedMap, "当前地图") + "”已自动绑定到部署阶段；请选择下一张地图的来源。",
      completionCriterion: "已明确下一张地图的来源",
      primaryAction: {
        id: "choose-map-source",
        label: "选择下一张地图来源",
        target: "mapSourceChoices",
      },
      nextTaskLabel: "读取并校验地图文件",
      progressItems: mapProgress("source"),
      targetStageId: nextStage?.stage || null,
    });
  }
  if (!draft.mapSource) {
    return deploymentTask({
      id: DEPLOYMENT_TASK_IDS.MAP_SOURCE,
      stageId,
      title: mapImportGuidance.state === "target"
        ? `选择“${mapImportGuidance.stageLabel}”地图来源`
        : "选择地图来源",
      detail: mapImportGuidance.state === "target"
        ? `${mapImportGuidance.position}。${mapImportGuidance.detail}`
        : "选择导入已有地图或车端实时建图。",
      completionCriterion: "已明确当前地图的来源",
      primaryAction: {
        id: "choose-map-source",
        label: "选择地图来源",
        target: "mapSourceChoices",
      },
      nextTaskLabel: "读取并校验地图文件",
      progressItems: mapProgress("source"),
      targetStageId: nextStage?.stage || null,
    });
  }
  if (draft.mapSource === "mapping") {
    const sessionIsActive =
      mappingSession &&
      ["prepared", "running", "stopping"].includes(mappingSession.state);
    if (sessionIsActive && mappingSession.project_id !== project?.id) {
      return deploymentTask({
        id: "maps.mapping_blocked",
        stageId,
        title: "先处理其他项目的建图会话",
        detail: `项目“${mappingSession.project_id}”仍有活动建图会话；当前项目不会重复创建会话。`,
        completionCriterion: "原建图会话已继续完成或安全放弃",
        primaryAction: {
          id: "focus-mapping-conflict",
          label: "查看会话处理方式",
          target: "mappingMessage",
        },
        nextTaskLabel: "准备当前项目的建图会话",
        progressItems: mapProgress("import", ["source"]),
        targetStageId: nextStage?.stage || null,
      });
    }
    const activeSession =
      sessionIsActive && mappingSession.project_id === project?.id;
    return deploymentTask({
      id: activeSession ? "maps.mapping_continue" : "maps.mapping_prepare",
      stageId,
      title: activeSession ? "继续车端实时建图" : "准备车端实时建图",
      detail: activeSession
        ? "返回当前建图会话，保存结果后继续绑定地图阶段。"
        : "选择建图模板和地图名称，准备受控建图会话。",
      completionCriterion: "建图结果已保存为当前项目地图快照",
      primaryAction: activeSession
        ? {
            id: "open-mapping-workbench",
            label: "进入建图工作台",
            target: "openMappingWorkbench",
          }
        : {
            id: "prepare-mapping",
            label: "准备建图会话",
            target: "prepareMapping",
          },
      nextTaskLabel: "命名并检查地图",
      progressItems: mapProgress("import", ["source"]),
      targetStageId: nextStage?.stage || null,
    });
  }
  if (!draft.fileSummary?.valid) {
    return deploymentTask({
      id: DEPLOYMENT_TASK_IDS.MAP_IMPORT,
      stageId,
      title: mapImportGuidance.state === "target"
        ? `读取“${mapImportGuidance.stageLabel}”地图文件`
        : "读取并校验地图文件",
      detail: mapImportGuidance.state === "target"
        ? `${mapImportGuidance.position}。${mapImportGuidance.detail} 请选择 YAML、PGM、可选 PCD 和兼容索引文件。`
        : "选择 YAML、PGM、可选 PCD 和兼容索引文件。",
      completionCriterion: "文件组合通过浏览器预检查",
      primaryAction: {
        id: "select-map-files",
        label: "选择地图文件",
        target: "mapFolder",
      },
      nextTaskLabel: "命名并检查地图",
      progressItems: mapProgress("import", ["source"]),
      targetStageId: nextStage?.stage || null,
    });
  }
  return deploymentTask({
    id: DEPLOYMENT_TASK_IDS.MAP_DESCRIBE,
    stageId,
    title: mapImportGuidance.state === "target"
      ? `命名并检查“${mapImportGuidance.stageLabel}”地图`
      : "命名并检查地图",
    detail: mapImportGuidance.state === "target"
      ? `${mapImportGuidance.position}。${mapImportGuidance.detail} 请填写现场可识别名称并确认文件清单。`
      : "填写现场可识别名称，并确认文件清单后导入项目快照。",
    completionCriterion: "名称清晰且地图文件信息无误",
    primaryAction: {
      id: "import-map",
      label: "导入并继续",
      target: "importMap",
    },
    nextTaskLabel: "绑定地图阶段",
    progressItems: mapProgress("describe", ["source", "import"]),
    targetStageId: nextStage?.stage || null,
  });
}

export function deriveDeploymentEditImpact(stageId, currentStageId) {
  const labels = STEP_LABELS;
  const currentIndex = WORKFLOW_STAGE_ORDER.indexOf(currentStageId);
  const startIndex = WORKFLOW_STAGE_ORDER.indexOf(stageId) + 1;
  const items = WORKFLOW_STAGE_ORDER.slice(startIndex, currentIndex + 2).map(
    (item, index) => ({
      stageId: item,
      label: labels[item],
      status:
        index === 0 ? "reconfirm" : item === "export" ? "locked" : "invalid",
    }),
  );
  return { stageId, returnStageId: stageId, items };
}

/**
 * Derive the field workflow from the existing SiteProject facts.
 * This is intentionally pure so the browser can explain the next action
 * without inventing or persisting a second workflow state machine.
 */
export function deriveDeploymentWorkflow(project, topology, preview) {
  const maps = list(project?.map_assets);
  const sceneReady = Boolean(
    project?.scene_model ||
      (Array.isArray(project?.deployment_flow) && project.deployment_flow.length),
  );
  const stagesReady = stageReady(topology, maps);
  const instanceNeed = missingMapInstance(project, topology);
  const mapsReady = sceneReady && stagesReady && !instanceNeed;
  const annotations = mapsReady && annotationReady(project);
  // Map switching is emitted by the behavior tree.  A hand-authored
  // Transition row is not part of the operator workflow; the route editor
  // only records ordered bindings and the elevator/component anchor needed
  // to derive init_return.
  const localization = annotations && routeReady(project);
  const exportReady = localization && preview?.status === "ready";
  const steps = [
    step(
      "project",
      project && sceneReady ? "complete" : project ? "current" : "current",
      project ? (sceneReady ? "项目与场景模型已确认" : "项目已创建，等待确认场景模型") : "需要先创建一个部署项目",
      project && !sceneReady ? "先配置部署流程，工具才能确定地图阶段和经过顺序。" : "",
    ),
    step(
      "maps",
      !sceneReady ? "locked" : mapsReady ? "complete" : "current",
      mapsReady
        ? `${maps.length} 张地图已完成阶段绑定和部署位置设置`
        : instanceNeed
          ? `“${instanceNeed.stageLabel}”还未设置部署拓扑位置`
          : maps.length ? "地图已导入，但阶段绑定还未完成" : "尚未导入地图",
      instanceNeed
        ? `先为“${instanceNeed.stageLabel}”设置部署拓扑位置，避免实验预览缺少地图实例。`
        : maps.length ? "请把已导入地图绑定到正确的部署阶段。" : "按当前场景模型，先导入或建立第一张地图。",
    ),
    step(
      "annotations",
      !mapsReady ? "locked" : annotations ? "complete" : "current",
      annotations ? "每张地图都有可用标记" : "还需要在地图画布上放置航点或组件",
      missingAnnotationMap(project)
        ? `地图“${mapLabel(missingAnnotationMap(project), "当前地图")}”还没有标记。`
        : "请在每张地图上至少标记一个后续路线需要的航点。",
    ),
    step(
      "localization",
      !annotations ? "locked" : localization ? "complete" : "current",
      localization
        ? "地图角色和定位路线已保存；切图由行为树自动执行"
        : "定位绑定或路线尚未完成",
      "先为地图配置运行角色，再按实际经过顺序保存定位路线。切图点无需手动绘制。",
    ),
    step(
      "export",
      !localization ? "locked" : exportReady ? "complete" : "current",
      exportReady ? "服务端校验通过，可导出部署包" : "等待服务端实验预览校验",
      topology?.valid
        ? "生成实验预览会检查地图、组件、定位路线和受控输出文件。"
        : topologyReason(topology),
    ),
  ];

  let current = steps.find((item) => item.status !== "complete") || steps.at(-1);
  let next;
  if (!project) {
    current = steps[0];
    next = action("createProject", "填写名称后创建项目，后续地图和部署事实都会保存在项目快照中。");
  } else if (!sceneReady) {
    current = steps[0];
    next = action("confirmScene", "部署流程决定地图阶段数量和导入顺序。");
  } else if (!maps.length) {
    current = steps[1];
    next = action("importMap", "可选择现有地图快照，或准备车端建图会话。");
  } else if (!stagesReady) {
    current = steps[1];
    next = action("assignStage", "先完成地图阶段绑定，避免后续路线顺序发生歧义。");
  } else if (instanceNeed) {
    current = steps[1];
    next = {
      ...action("configureMapInstance", `先设置“${instanceNeed.stageLabel}”的部署拓扑位置，编译器才可确定实际楼栋、单元和楼层。`),
      targetMapId: instanceNeed.mapAssetId,
      instanceRole: instanceNeed.role,
    };
  } else if (!annotations) {
    current = steps[2];
    const missing = missingAnnotationMap(project);
    next = {
      ...action("annotate", missing ? `请打开“${mapLabel(missing, "待标记地图")}”并标记航点。` : "请在地图画布上补充路线需要的航点和组件。"),
      label: missing ? `标记${mapLabel(missing, "待标记")}地图` : "标记当前地图",
      targetMapId: missing?.id || null,
    };
  } else if (!localization) {
    current = steps[3];
    const bindingCount = list(project.localization_bindings).length;
    next = action(bindingCount ? "editRoute" : "bindLocalization", bindingCount ? "地图角色已存在；下一步确认机器人去程经过地图的顺序和切图依据。" : "先为每张地图确定大厅、用户楼层、摆渡层或户外等运行角色。");
  } else if (!project.task_compiler?.identity?.community) {
    current = steps[4];
    next = action("saveCompilerIdentity", "导出文件需要一个明确的小区名称。");
  } else if (!exportReady) {
    current = steps[4];
    next = action("preview", "只生成实验预览，不会写入机器人运行目录。");
  } else {
    current = steps[4];
    next = action("export", "实验预览已通过，可下载部署包交给后续交付流程。");
  }

  const completed = steps.filter((item) => item.status === "complete").length;
  return {
    steps,
    current,
    next,
    completed,
    total: steps.length,
    percent: Math.round((completed / steps.length) * 100),
    checklist: [
      { label: "项目与场景模型", done: project && sceneReady },
      { label: "地图阶段已绑定", done: mapsReady },
      { label: "地图标记已补齐", done: annotations },
      { label: "定位路线已保存", done: localization },
      { label: "实验预览已校验", done: exportReady },
    ],
  };
}
