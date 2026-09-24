export function taskConsoleMarkup(
  task,
  { pending = false, receipt = null, facts = [] } = {},
  esc = String,
) {
  const progress = task.progressItems
    .map(
      (item, index) => `
        <div class="deployment-task-progress-item ${esc(item.status)}">
          <span class="deployment-task-progress-mark" aria-hidden="true">${index + 1}</span>
          <div>
            <b>${esc(item.label)}</b>
            <small>${esc(
              item.status === "current"
                ? "正在进行"
                : item.status === "complete"
                  ? "已完成"
                  : "待完成",
            )}</small>
          </div>
        </div>`,
    )
    .join("");
  const receiptHtml = receipt
    ? `<div id="deploymentTaskReceipt" class="deployment-task-receipt" role="status">${esc(receipt.message)}</div>`
    : '<div id="deploymentTaskReceipt" class="deployment-task-receipt deployment-hidden" role="status"></div>';
  if (task.readOnly) {
    return {
      summaryHtml: `${receiptHtml}${completedStageReviewMarkup(task, facts, esc)}`,
      progressHtml: `<h2>本阶段进度</h2>${progress}`,
      afterHtml: `<b>当前流程不变：</b>${esc(task.nextTaskLabel)}`,
    };
  }
  return {
    summaryHtml: `${receiptHtml}
      <section id="deploymentTaskCard" class="deployment-task-card" aria-labelledby="deploymentTaskTitle">
        <div class="deployment-task-copy">
          <span class="deployment-task-sequence">当前任务 · ${esc(task.stageId)}</span>
          <h2 id="deploymentTaskTitle" tabindex="-1">${esc(task.title)}</h2>
          <p id="deploymentTaskDetail">${esc(task.detail)}</p>
          <p id="deploymentTaskCriterion"><span>完成标准</span>${esc(task.completionCriterion)}</p>
        </div>
        <div class="deployment-task-action">
          <button id="deploymentTaskPrimary" class="page-top-action" type="button" data-task-action="${esc(task.primaryAction.id)}"${pending ? ' disabled aria-busy="true"' : ""}>${esc(pending ? "正在处理…" : task.primaryAction.label)}</button>
        </div>
      </section>`,
    progressHtml: `<h2>本阶段进度</h2>${progress}`,
    afterHtml: `<b>成功后：</b>${esc(task.nextTaskLabel)}`,
  };
}

export function completedStageReviewMarkup(task, facts, esc = String) {
  const factRows = facts.length
    ? facts.map(({ label, value }) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join("")
    : "<div><dt>阶段状态</dt><dd>服务端已确认完成</dd></div>";
  return `<section class="deployment-review-readonly" aria-labelledby="deploymentTaskTitle">
    <div><span class="deployment-review-state">已完成</span><h2 id="deploymentTaskTitle" tabindex="-1">${esc(task.title)}</h2><p>以下内容默认只读，回看不会改变当前流程进度。</p></div>
    <dl>${factRows}</dl>
    <div class="deployment-review-actions"><button class="compact-action" type="button" data-task-action="return-current">返回当前任务</button><button class="compact-action" type="button" data-task-action="request-stage-edit">修改此步骤</button></div>
  </section>`;
}

export function createTaskActionGate() {
  let active = null;
  return {
    get active() {
      return active;
    },
    async run(id, work) {
      if (active) return undefined;
      active = id;
      try {
        return await work();
      } finally {
        active = null;
      }
    },
  };
}
