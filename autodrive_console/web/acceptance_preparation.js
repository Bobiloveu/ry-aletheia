const stageLabels = {
  pending: "待开始",
  restarting: "正在重启",
  waiting_stable: "等待稳定 RUNNING",
  settling: "稳定等待中",
  ready: "已就绪",
  blocked: "准备失败",
  cancelled: "已取消",
};

const nodeStatusLabels = {
  PENDING: "待开始",
  RUNNING: "运行中",
  STARTING: "启动中",
  STOPPED: "已停止",
  BACKOFF: "正在重试",
  EXITED: "已退出",
  FATAL: "启动失败",
  MISSING: "未发现",
  UNKNOWN: "状态未知",
};

const activeStageStates = new Set(["restarting", "waiting_stable", "settling", "blocked", "cancelled"]);
// A generated plan is deliberately replaceable until an operator starts it.
// Only a plan with an active or unresolved execution owns the shared controls.
const lockedPlanStatuses = new Set(["preparing", "running", "awaiting_recovery", "recovering", "cancelling", "interrupted"]);
const terminalPlanStatuses = new Set(["completed", "cancelled", "blocked", "failed"]);

export function acceptancePlanPreflightPayload({
  scenarioProfileId = null,
  dependencyPlanEnabled = false,
  automaticReturnEnabled = false,
} = {}) {
  return {
    scenario_profile_id: typeof scenarioProfileId === "string" && scenarioProfileId ? scenarioProfileId : null,
    use_dependency_plan: dependencyPlanEnabled === true,
    use_automatic_return: automaticReturnEnabled === true,
  };
}

export function activeAcceptancePlanSelection(plan) {
  if (!lockedPlanStatuses.has(plan?.status)) return null;
  return {
    scope: plan.scope_type,
    community: plan.community,
    buildingUnit: plan.scope_type === "building" ? `${plan.building}:${plan.unit}` : "",
    mode: plan.mode,
    scenarioProfileId: plan.execution_preflight?.scenario_profile_id || "",
    dependencyPlanEnabled: plan.execution_preflight?.dependency_plan_enabled === true,
    automaticReturnEnabled: plan.execution_preflight?.automatic_return_enabled === true,
  };
}

export function readyPlanReplacementNotice(plan) {
  if (plan?.status !== "ready") return null;
  return "计划尚未开始。可调整范围或运行准备后重新生成计划；新计划会替换当前未开始计划。";
}

export function shouldRenderDependencyPreparation(plan) {
  return plan?.execution_preflight?.dependency_plan_enabled === true && !terminalPlanStatuses.has(plan?.status);
}

export function shouldRenderPreparationRuntime(plan) {
  return Boolean(plan?.execution_preflight_status) && !terminalPlanStatuses.has(plan?.status);
}

export function dependencyPreparationView(plan) {
  const visible = shouldRenderDependencyPreparation(plan);
  const snapshot = plan?.execution_preflight_status;
  const sourceStages = snapshot?.dependency_progress?.stages;
  const stages = visible && Array.isArray(sourceStages)
    ? sourceStages.map((stage) => ({
      index: stage.index,
      state: stage.state,
      stateLabel: stageLabels[stage.state] || "状态未知",
      current: activeStageStates.has(stage.state),
      nodes: Array.isArray(stage.nodes) ? stage.nodes.map((node) => ({
        name: node.name,
        status: node.status,
        statusLabel: nodeStatusLabels[node.status] || "状态未知",
      })) : [],
    }))
    : [];
  const current = stages.find((stage) => stage.current)
    || stages.find((stage) => stage.state !== "ready")
    || stages.at(-1)
    || null;
  if (current && !stages.some((stage) => stage.current)) current.current = true;
  return {
    visible,
    currentStageIndex: current?.index ?? null,
    currentStageLabel: current?.stateLabel ?? "正在读取状态",
    ...(typeof snapshot?.updated_at === "string" ? { updatedAt: snapshot.updated_at } : {}),
    stages,
  };
}
