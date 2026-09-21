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
  annotate: { label: "标记当前地图", target: "mapWorkspace" },
  bindLocalization: { label: "配置定位绑定", target: "openLocalizationBinding" },
  editRoute: { label: "编辑定位路线", target: "localizationRouteList" },
  saveCompilerIdentity: { label: "保存小区信息", target: "taskCompilerCommunity" },
  preview: { label: "生成实验预览", target: "generateTaskCompilerPreview" },
  export: { label: "导出部署包", target: "downloadTaskCompilerBundle" },
};

function list(value) {
  return Array.isArray(value) ? value : [];
}

function mapLabel(map, fallback) {
  return map?.label || map?.id || fallback;
}

function stageReady(topology, maps) {
  const stages = list(topology?.stages);
  return Boolean(
    maps.length &&
      stages.length &&
      stages.every((stage) => stage.map_asset_id),
  );
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
  const mapsReady = sceneReady && stageReady(topology, maps);
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
      mapsReady ? `${maps.length} 张地图已完成阶段绑定` : maps.length ? "地图已导入，但阶段绑定还未完成" : "尚未导入地图",
      maps.length ? "请把已导入地图绑定到正确的部署阶段。" : "按当前场景模型，先导入或建立第一张地图。",
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
  } else if (!mapsReady) {
    current = steps[1];
    next = action("assignStage", "先完成地图阶段绑定，避免后续路线顺序发生歧义。");
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
    next = action(bindingCount ? "editRoute" : "bindLocalization", bindingCount ? "地图角色已存在，下一步按实际经过顺序编辑定位路线。" : "先为当前地图保存户外、大厅、摆渡层或用户楼层角色。");
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
