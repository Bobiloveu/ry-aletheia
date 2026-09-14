const stageLabels = {
  pending: "待开始",
  restarting: "正在重启",
  waiting_stable: "等待稳定 RUNNING",
  settling: "稳定等待中",
  ready: "已就绪",
  blocked: "准备失败",
  cancelled: "已取消",
};

export function shouldRenderDependencyPreparation(plan) {
  return plan?.execution_preflight?.dependency_plan_enabled === true;
}

export function dependencyPreparationView(plan) {
  const visible = shouldRenderDependencyPreparation(plan);
  const stages = plan?.execution_preflight_status?.dependency_progress?.stages;
  return {
    visible,
    stages: visible && Array.isArray(stages)
      ? stages.map((stage) => ({
        index: stage.index,
        state: stage.state,
        stateLabel: stageLabels[stage.state] || "状态未知",
        nodes: Array.isArray(stage.nodes) ? stage.nodes.map((node) => ({ name: node.name, status: node.status })) : [],
      }))
      : [],
  };
}
