import { componentName } from "./component-specs.js";

const ROLE_LABELS = {
  waypoint: "路径过渡",
  entry: "进入",
  exit: "离开",
};

const SPEED_LABELS = {
  task_point: "任务点",
  single_point: "单点",
  slow_point: "减速",
  narrow_point: "窄通道",
  backward: "返程",
};

export function executionNodeLabel(node, project = {}) {
  if (node?.source_kind === "component") {
    const component = (project.components || []).find((item) => item.id === node.source_id);
    if (!component) return "组件";
    const typeName = componentName(component);
    const customLabel = String(component.label || "").trim();
    return customLabel && customLabel !== typeName
      ? `${typeName} · ${customLabel}`
      : typeName;
  }
  const waypoint = (project.waypoints || []).find((item) => item.id === node?.source_id);
  if (!waypoint) return "过渡点";
  const customLabel = String(waypoint.label || "").trim();
  return customLabel && customLabel !== "过渡点"
    ? `过渡点 · ${customLabel}`
    : "过渡点";
}

export function executionNodeRoleLabel(role) {
  return ROLE_LABELS[role] || "路径节点";
}

export function executionNodeSpeedLabel(speed) {
  return SPEED_LABELS[speed] || "常规";
}
