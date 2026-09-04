(() => {
  const $ = (id) => document.getElementById(id);
  const state = { catalog: null, plan: null, timer: null };
  const message = (text = '', error = false) => { $('pageMessage').textContent = text; $('pageMessage').classList.toggle('error', error); };
  async function request(url, options) { const response = await fetch(url, options); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(body.error || '请求失败'); return body; }
  function scope() { return document.querySelector('input[name="scope"]:checked').value; }
  function mode() { return document.querySelector('input[name="mode"]:checked').value; }
  function renderCatalog() {
    const communities = state.catalog?.communities || []; const select = $('communitySelect'); const previous = select.value;
    select.replaceChildren(...communities.map((item) => Object.assign(document.createElement('option'), { value: item.name, textContent: item.name })));
    if (communities.some((item) => item.name === previous)) select.value = previous;
    updateBuildings(); $('catalogSummary').textContent = `可用正式任务 ${state.catalog?.valid_task_count || 0} 项`;
    $('catalogIssues').replaceChildren(...(state.catalog?.issues || []).map((issue) => Object.assign(document.createElement('p'), { textContent: `${issue.filename}：${issue.message}` })));
  }
  function updateBuildings() {
    const selected = (state.catalog?.communities || []).find((item) => item.name === $('communitySelect').value);
    const building = $('buildingSelect');
    building.replaceChildren(...(selected?.physical_buildings || []).map((item) => Object.assign(document.createElement('option'), { value: `${item.building}:${item.unit}`, textContent: item.label })));
    building.disabled = scope() !== 'building';
  }
  function renderPlan() {
    const plan = state.plan; $('planState').textContent = plan?.status || '未生成计划'; $('planState').className = `acceptance-badge ${plan?.status || ''}`;
    const summary = plan?.selection_summary;
    $('selectionSummary').textContent = summary ? `${summary.tasks} 项 · 覆盖 ${summary.physical_buildings} 个物理楼宇单元、${summary.floors} 个楼层、${summary.doors} 户` : '生成后显示';
    const body = $('planItems'); body.replaceChildren();
    for (const [index, item] of (plan?.items || []).entries()) { const row = document.createElement('tr'); row.innerHTML = `<td>${index + 1}</td><td></td><td></td><td></td>`; row.children[1].textContent = item.filename; row.children[2].textContent = `${item.parameters.building}栋 ${item.parameters.unit}单元 ${item.parameters.floor}层 ${item.parameters.door}`; row.children[3].textContent = item.status; body.append(row); }
    if (!plan) body.innerHTML = '<tr><td colspan="4">尚未生成验收计划。</td></tr>';
    $('planWarnings').replaceChildren(...(plan?.warnings || []).map((item) => Object.assign(document.createElement('p'), { textContent: item })));
    $('startPlan').disabled = plan?.status !== 'ready'; $('resumePlan').disabled = plan?.status !== 'awaiting_recovery'; $('cancelPlan').disabled = !['preparing', 'running', 'awaiting_recovery', 'recovering'].includes(plan?.status); $('resolvePlan').disabled = plan?.status !== 'interrupted';
    const conclusion = plan?.conclusion;
    const completed = (plan?.items || []).filter((item) => ['passed', 'failed'].includes(item.status)).length;
    $('resultPassRate').textContent = conclusion?.status ? `${conclusion.pass_rate.toFixed(1)}%` : '—';
    $('resultCoverage').textContent = summary ? `${summary.physical_buildings} 个物理楼宇单元 · ${summary.floors} 个楼层 · ${summary.doors} 户` : '生成计划后显示';
    $('resultRule').textContent = plan?.mode === 'full' ? '全量：计划内所有任务均通过，才判定通过。' : '抽样：计划内所有任务均通过，才判定本次抽样通过。';
    $('conclusion').className = `conclusion ${conclusion?.status || ''}`;
    $('conclusion').textContent = conclusion ? conclusion.message : (plan ? `计划进行中：已完成 ${completed}/${plan.items.length} 项。` : '生成计划后，系统会自动计算本次验收结果。');
    $('reportLink').hidden = !plan?.report_filename; if (plan?.report_filename) $('reportLink').href = `/api/acceptance/plans/${plan.plan_id}/report`;
  }
  async function refresh() { try { state.catalog = await request('/api/acceptance/catalog'); const response = await fetch('/api/acceptance/plans/current'); state.plan = response.ok ? (await response.json()).plan : null; renderCatalog(); renderPlan(); } catch (error) { message(error.message, true); } }
  async function action(url, payload = {}) { try { message('正在处理…'); const result = await request(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); state.plan = result.plan || state.plan; renderPlan(); message('操作已提交。'); } catch (error) { message(error.message, true); await refresh(); } }
  function bind() {
    document.querySelectorAll('input[name="scope"]').forEach((input) => input.addEventListener('change', updateBuildings)); document.querySelectorAll('input[name="mode"]').forEach((input) => input.addEventListener('change', () => { $('sampleSize').disabled = mode() !== 'sample'; })); $('communitySelect').addEventListener('change', updateBuildings);
    $('createPlan').addEventListener('click', () => {
      const [building, unit] = scope() === 'building' ? $('buildingSelect').value.split(':').map(Number) : [null, null];
      action('/api/acceptance/plans', { scope_type: scope(), community: $('communitySelect').value, building, unit, mode: mode(), sample_size: mode() === 'sample' ? Number($('sampleSize').value) : null });
    });
    $('startPlan').addEventListener('click', () => { if (confirm('确认开始已冻结的验收计划？计划执行期间不能同时运行普通测试。')) action(`/api/acceptance/plans/${state.plan.plan_id}/start`); });
    $('resumePlan').addEventListener('click', () => action(`/api/acceptance/plans/${state.plan.plan_id}/resume`)); $('cancelPlan').addEventListener('click', () => { if (confirm('确认取消剩余验收任务？')) action(`/api/acceptance/plans/${state.plan.plan_id}/cancel`); }); $('resolvePlan').addEventListener('click', () => { if (confirm('确认已核对现场？未知任务将按失败记录，绝不会自动重发。')) action(`/api/acceptance/plans/${state.plan.plan_id}/resolve-interruption`, { resolution: 'mark_failed' }); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); }); setInterval(() => { if (!document.hidden && ['preparing', 'running', 'awaiting_recovery', 'recovering'].includes(state.plan?.status)) refresh(); }, 2000);
  }
  document.addEventListener('DOMContentLoaded', async () => { bind(); await refresh(); });
})();
