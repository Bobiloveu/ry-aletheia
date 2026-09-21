import { requestJson } from "./platform/http.js";
import { acceptancePlanPreflightPayload, activeAcceptancePlanSelection, dependencyPreparationView, readyPlanReplacementNotice, shouldRenderPreparationRuntime } from "./acceptance_preparation.js";

(() => {
  const DRAFT_KEY = 'ry-aletheia-acceptance-draft-v1';
  const $ = (id) => document.getElementById(id);
  const state = { catalog: null, scenario: null, settings: null, plan: null, draftRestored: false, dependencyPlanAvailable: false };
  const message = (text = '', error = false) => { const box = $('pageMessage'); box.textContent = text; box.hidden = !text; box.classList.toggle('error', error); };
  const request = (url, options) => requestJson(url, options);
  const scope = () => document.querySelector('input[name="scope"]:checked').value;
  const mode = () => document.querySelector('input[name="mode"]:checked').value;
  const selectedProfile = () => (state.scenario?.document?.profiles || []).find((profile) => profile.id === $('acceptanceScenarioProfile').value);

  function currentDraft() {
    return {
      scope_type: scope(), community: $('communitySelect').value, building_unit: $('buildingSelect').value,
      mode: mode(), sample_size: $('sampleSize').value, scenario_profile_id: $('acceptanceScenarioProfile').value,
      use_dependency_plan: $('acceptanceDependencyPlan').checked,
      use_automatic_return: $('acceptanceAutomaticReturn').checked,
    };
  }
  function saveDraft() {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(currentDraft())); } catch (_) { /* storage is an optional browser convenience */ }
    renderPreparationChoiceSummary();
  }
  function clearDraft() {
    try { localStorage.removeItem(DRAFT_KEY); } catch (_) { /* nothing to recover */ }
  }
  function storedDraft() {
    try { const value = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); return value && typeof value === 'object' ? value : null; } catch (_) { return null; }
  }

  function renderCatalog() {
    const communities = state.catalog?.communities || [];
    const select = $('communitySelect'); const previous = select.value;
    select.replaceChildren(...communities.map((item) => Object.assign(document.createElement('option'), { value: item.name, textContent: item.name })));
    if (communities.some((item) => item.name === previous)) select.value = previous;
    updateBuildings();
    $('catalogSummary').textContent = `可用正式任务 ${state.catalog?.valid_task_count || 0} 项`;
    $('catalogIssues').replaceChildren(...(state.catalog?.issues || []).map((issue) => Object.assign(document.createElement('p'), { textContent: `${issue.filename}：${issue.message}` })));
  }
  function updateBuildings() {
    const selected = (state.catalog?.communities || []).find((item) => item.name === $('communitySelect').value);
    const building = $('buildingSelect'); const previous = building.value;
    building.replaceChildren(...(selected?.physical_buildings || []).map((item) => Object.assign(document.createElement('option'), { value: `${item.building}:${item.unit}`, textContent: item.label })));
    if ([...building.options].some((option) => option.value === previous)) building.value = previous;
    building.disabled = scope() !== 'building';
  }
  function renderPreflightChoices() {
    const profiles = state.scenario?.document?.profiles || [];
    const select = $('acceptanceScenarioProfile'); const previous = select.value;
    select.replaceChildren(Object.assign(document.createElement('option'), { value: '', textContent: '不应用场景方案' }), ...profiles.map((profile) => Object.assign(document.createElement('option'), { value: profile.id, textContent: profile.name })));
    if (profiles.some((profile) => profile.id === previous)) select.value = previous;
    const dependency = state.settings?.dependency_plan;
    const available = dependency?.enabled === true && Array.isArray(dependency.steps) && dependency.steps.length > 0;
    state.dependencyPlanAvailable = available;
    const checkbox = $('acceptanceDependencyPlan'); checkbox.disabled = !available;
    if (!available) checkbox.checked = false;
    $('acceptanceDependencyHint').textContent = available ? `当前已保存 ${dependency.steps.length} 个启动阶段；勾选后会冻结到新计划。` : '当前没有已启用的 Supervisor 依赖编排；此验收会按常规流程执行。';
  }
  function restoreDraft() {
    if (state.draftRestored) return;
    state.draftRestored = true;
    const draft = storedDraft();
    if (!draft) return renderPreparationChoiceSummary();
    const savedScope = ['community', 'building'].includes(draft.scope_type) ? draft.scope_type : null;
    const scopeInput = savedScope && document.querySelector(`input[name="scope"][value="${savedScope}"]`);
    if (scopeInput) scopeInput.checked = true;
    if ([...$('communitySelect').options].some((option) => option.value === draft.community)) $('communitySelect').value = draft.community;
    updateBuildings();
    if ([...$('buildingSelect').options].some((option) => option.value === draft.building_unit)) $('buildingSelect').value = draft.building_unit;
    const savedMode = ['all', 'sample'].includes(draft.mode) ? draft.mode : null;
    const modeInput = savedMode && document.querySelector(`input[name="mode"][value="${savedMode}"]`);
    if (modeInput) modeInput.checked = true;
    $('sampleSize').disabled = mode() !== 'sample';
    if (typeof draft.sample_size === 'string') $('sampleSize').value = draft.sample_size;
    if ([...$('acceptanceScenarioProfile').options].some((option) => option.value === draft.scenario_profile_id)) $('acceptanceScenarioProfile').value = draft.scenario_profile_id;
    $('acceptanceDependencyPlan').checked = !$('acceptanceDependencyPlan').disabled && draft.use_dependency_plan === true;
    $('acceptanceAutomaticReturn').checked = draft.use_automatic_return === true;
    $('optionalPreparation').open = Boolean($('acceptanceScenarioProfile').value || $('acceptanceDependencyPlan').checked || $('acceptanceAutomaticReturn').checked);
    renderPreparationChoiceSummary();
  }
  function setChoiceDisabled(disabled) {
    $('communitySelect').disabled = disabled;
    document.querySelectorAll('input[name="scope"], input[name="mode"]').forEach((input) => { input.disabled = disabled; });
    $('buildingSelect').disabled = disabled || scope() !== 'building';
    $('sampleSize').disabled = disabled || mode() !== 'sample';
    $('acceptanceScenarioProfile').disabled = disabled;
    $('acceptanceDependencyPlan').disabled = disabled || !state.dependencyPlanAvailable;
    $('acceptanceAutomaticReturn').disabled = disabled;
    $('createPlan').disabled = disabled;
  }
  function synchronizeActivePlanSelection() {
    const selection = activeAcceptancePlanSelection(state.plan);
    const notice = $('sharedPlanNotice');
    if (!selection) {
      setChoiceDisabled(false);
      restoreDraft();
      const replacementNotice = readyPlanReplacementNotice(state.plan);
      notice.textContent = replacementNotice || '';
      notice.hidden = !replacementNotice;
      return;
    }
    const scopeInput = document.querySelector(`input[name="scope"][value="${selection.scope}"]`);
    if (scopeInput) scopeInput.checked = true;
    if ([...$('communitySelect').options].some((option) => option.value === selection.community)) $('communitySelect').value = selection.community;
    updateBuildings();
    if (selection.buildingUnit && [...$('buildingSelect').options].some((option) => option.value === selection.buildingUnit)) $('buildingSelect').value = selection.buildingUnit;
    const modeInput = document.querySelector(`input[name="mode"][value="${selection.mode}"]`);
    if (modeInput) modeInput.checked = true;
    if ([...$('acceptanceScenarioProfile').options].some((option) => option.value === selection.scenarioProfileId)) $('acceptanceScenarioProfile').value = selection.scenarioProfileId;
    $('acceptanceDependencyPlan').checked = selection.dependencyPlanEnabled;
    $('acceptanceAutomaticReturn').checked = selection.automaticReturnEnabled;
    $('optionalPreparation').open = Boolean(selection.scenarioProfileId || selection.dependencyPlanEnabled || selection.automaticReturnEnabled);
    setChoiceDisabled(true);
    notice.textContent = state.plan?.status === 'ready'
      ? '当前验收计划已冻结；范围与运行准备以后台计划为准，所有终端会同步显示。'
      : '当前验收计划正在执行；范围与运行准备以后台冻结计划为准，所有终端会同步显示。';
    notice.hidden = false;
  }
  function renderPreparationChoiceSummary() {
    const frozen = activeAcceptancePlanSelection(state.plan);
    if (frozen) {
      const frozenProfile = state.plan?.execution_preflight?.scenario_profile_name;
      const summary = frozenProfile || frozen.dependencyPlanEnabled || frozen.automaticReturnEnabled
        ? `已冻结：${frozenProfile ? `场景方案 ${frozenProfile}` : '不应用场景方案'}${frozen.dependencyPlanEnabled ? `${frozenProfile ? '；' : ''}执行已保存依赖编排` : ''}${frozen.automaticReturnEnabled ? `${frozenProfile || frozen.dependencyPlanEnabled ? '；' : ''}自动返程` : ''}`
        : '已冻结：不使用额外运行准备，按常规验收流程执行';
      $('preflightChoiceSummary').textContent = summary;
      return;
    }
    const profile = selectedProfile();
    const dependencies = $('acceptanceDependencyPlan').checked && !$('acceptanceDependencyPlan').disabled;
    const automaticReturn = $('acceptanceAutomaticReturn').checked;
    const summary = profile || dependencies || automaticReturn
      ? `已选择：${profile ? profile.name : '不应用场景方案'}${dependencies ? `${profile ? '；' : ''}执行已保存依赖编排` : ''}${automaticReturn ? `${profile || dependencies ? '；' : ''}自动返程` : ''}`
      : '不使用额外运行准备，按常规验收流程执行';
    $('preflightChoiceSummary').textContent = summary;
  }
  function renderRuntimeStatus(plan) {
    const box = $('preflightRuntimeStatus'); const runtime = plan?.execution_preflight_status;
    box.hidden = !shouldRenderPreparationRuntime(plan);
    if (box.hidden) return;
    box.className = `preflight-runtime-status ${runtime.state || ''}`;
    const updated = runtime.updated_at ? ` · 更新于 ${new Date(runtime.updated_at).toLocaleTimeString('zh-CN', { hour12: false })}` : '';
    box.textContent = `${runtime.message || '运行准备状态未知'}${updated}`;
  }
  function createDependencyStage(stage) {
    const section = document.createElement('section');
    section.className = `dependency-stage ${stage.state}${stage.current ? ' current' : ''}`;
    const heading = document.createElement('div');
    heading.className = 'dependency-stage-heading';
    const label = document.createElement('strong');
    label.textContent = `阶段 ${stage.index}`;
    const state = document.createElement('span');
    state.textContent = stage.stateLabel;
    heading.append(label, state);

    const nodes = document.createElement('ul');
    for (const node of stage.nodes) {
      const item = document.createElement('li');
      const name = document.createElement('code');
      name.textContent = node.name;
      const status = document.createElement('span');
      status.className = `supervisor-node-status ${node.status.toLowerCase()}`;
      status.textContent = node.statusLabel;
      const raw = document.createElement('small');
      raw.textContent = node.status;
      status.append(raw);
      item.append(name, status);
      nodes.append(item);
    }
    section.append(heading, nodes);
    return section;
  }
  function renderDependencyPreparation(plan) {
    const box = $('dependencyPreparation');
    const view = dependencyPreparationView(plan);
    box.hidden = !view.visible;
    if (!view.visible) return;
    box.replaceChildren();
    const heading = document.createElement('div');
    heading.className = 'dependency-preparation-heading';
    const title = document.createElement('strong');
    title.id = 'dependencyPreparationTitle';
    title.textContent = '节点运行准备';
    const current = document.createElement('p');
    current.className = 'dependency-preparation-current';
    current.textContent = `当前：第 ${view.currentStageIndex ?? '—'} 阶段 · ${view.currentStageLabel}`;
    const hint = document.createElement('small');
    hint.textContent = view.updatedAt
      ? `最后更新 ${new Date(view.updatedAt).toLocaleTimeString('zh-CN', { hour12: false })} · 状态来自 Supervisor 实时查询`
      : '等待 Supervisor 返回首个状态快照';
    heading.append(title, current, hint);
    box.append(heading);

    const stages = document.createElement('div');
    stages.className = 'dependency-preparation-stages';
    if (view.stages.length) {
      stages.append(...view.stages.map(createDependencyStage));
    } else {
      const empty = document.createElement('p');
      empty.className = 'muted';
      empty.textContent = '正在读取已冻结的 Supervisor 运行准备状态…';
      stages.append(empty);
    }
    box.append(stages);
  }
  function renderFrozenPreflight(plan) {
    const box = $('frozenPreflight'); const preflight = plan?.execution_preflight;
    box.hidden = !preflight;
    if (!preflight) return;
    const scenario = preflight.scenario_profile_name ? `场景方案：${preflight.scenario_profile_name}` : '场景方案：不应用';
    const dependencies = preflight.dependency_plan_enabled ? `Supervisor 依赖：${preflight.dependency_stage_count} 个阶段、${preflight.dependency_node_count} 个节点` : 'Supervisor 依赖：不执行';
    const automaticReturn = preflight.automatic_return_enabled ? '自动返程：启用' : '自动返程：不启用';
    box.textContent = plan?.status === 'ready'
      ? `当前未开始计划 · ${scenario}；${dependencies}；${automaticReturn}。可调整上方选项并重新生成计划；新计划会替换本计划，尚未执行任何任务。`
      : `已冻结运行准备 · ${scenario}；${dependencies}；${automaticReturn}。开始前统一执行一次，结束时只恢复常规启动配置。`;
  }
  function renderPlan() {
    const plan = state.plan; $('planState').textContent = plan?.status || '未生成计划'; $('planState').className = `acceptance-badge ${plan?.status || ''}`;
    const summary = plan?.selection_summary;
    $('selectionSummary').textContent = summary ? `${summary.tasks} 项 · 覆盖 ${summary.physical_buildings} 个物理楼宇单元、${summary.floors} 个楼层、${summary.doors} 户` : '生成后显示';
    const body = $('planItems'); body.replaceChildren();
    for (const [index, item] of (plan?.items || []).entries()) { const row = document.createElement('tr'); row.innerHTML = `<td>${index + 1}</td><td></td><td></td><td></td>`; row.children[1].textContent = item.filename; row.children[2].textContent = `${item.parameters.building}栋 ${item.parameters.unit}单元 ${item.parameters.floor}层 ${item.parameters.door}`; row.children[3].textContent = item.status; body.append(row); }
    if (!plan) body.innerHTML = '<tr><td colspan="4">尚未生成验收计划。</td></tr>';
    $('planWarnings').replaceChildren(...(plan?.warnings || []).map((item) => Object.assign(document.createElement('p'), { textContent: item })));
    renderFrozenPreflight(plan); renderRuntimeStatus(plan); renderDependencyPreparation(plan);
    $('createPlan').textContent = plan?.status === 'ready' ? '按当前选择重新生成计划' : '生成计划';
    $('startPlan').disabled = plan?.status !== 'ready'; $('resumePlan').disabled = plan?.status !== 'awaiting_recovery'; $('cancelPlan').disabled = !['preparing', 'running', 'awaiting_recovery', 'recovering'].includes(plan?.status); $('resolvePlan').disabled = plan?.status !== 'interrupted';
    const conclusion = plan?.conclusion; const completed = (plan?.items || []).filter((item) => ['passed', 'failed'].includes(item.status)).length;
    $('resultPassRate').textContent = conclusion?.status ? `${conclusion.pass_rate.toFixed(1)}%` : '—';
    $('resultCoverage').textContent = summary ? `${summary.physical_buildings} 个物理楼宇单元 · ${summary.floors} 个楼层 · ${summary.doors} 户` : '生成计划后显示';
    $('resultRule').textContent = plan?.mode === 'full' ? '全量：计划内所有任务均通过，才判定通过。' : '抽样：计划内所有任务均通过，才判定本次抽样通过。';
    $('conclusion').className = `conclusion ${conclusion?.status || ''}`;
    $('conclusion').textContent = conclusion ? conclusion.message : (plan ? `计划进行中：已完成 ${completed}/${plan.items.length} 项。` : '生成计划后，系统会自动计算本次验收结果。');
    $('reportLink').hidden = !plan?.report_filename; if (plan?.report_filename) $('reportLink').href = `/api/acceptance/plans/${plan.plan_id}/report`;
  }
  async function loadCurrentPlan() {
    const response = await fetch('/api/acceptance/plans/current', { cache: 'no-store' });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(payload.error || `读取当前验收计划失败（HTTP ${response.status}）`);
    return payload.plan || null;
  }
  async function refresh() {
    try {
      const [catalog, scenario, settings, plan] = await Promise.all([request('/api/acceptance/catalog'), request('/api/scenario-setup'), request('/api/settings'), loadCurrentPlan()]);
      state.catalog = catalog; state.scenario = scenario; state.settings = settings; state.plan = plan;
      renderCatalog(); renderPreflightChoices(); synchronizeActivePlanSelection(); renderPreparationChoiceSummary(); renderPlan();
    } catch (error) { message(error.message, true); }
  }
  async function refreshCurrentPlan() {
    try {
      state.plan = await loadCurrentPlan();
      synchronizeActivePlanSelection();
      renderPreparationChoiceSummary();
      renderPlan();
    } catch (error) { message(error.message, true); }
  }
  async function action(url, payload = {}, onSuccess = null) {
    try {
      message('正在处理…'); const result = await request(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      state.plan = result.plan || state.plan; if (onSuccess) onSuccess(result); synchronizeActivePlanSelection(); renderPreparationChoiceSummary(); renderPlan(); message('操作已提交。');
    } catch (error) { message(error.message, true); await refresh(); }
  }
  function bind() {
    document.querySelectorAll('input[name="scope"]').forEach((input) => input.addEventListener('change', () => { updateBuildings(); saveDraft(); }));
    document.querySelectorAll('input[name="mode"]').forEach((input) => input.addEventListener('change', () => { $('sampleSize').disabled = mode() !== 'sample'; saveDraft(); }));
    $('communitySelect').addEventListener('change', () => { updateBuildings(); saveDraft(); });
    ['buildingSelect', 'sampleSize', 'acceptanceScenarioProfile', 'acceptanceDependencyPlan', 'acceptanceAutomaticReturn'].forEach((id) => $(id).addEventListener(id === 'sampleSize' ? 'input' : 'change', saveDraft));
    $('createPlan').addEventListener('click', () => {
      const [building, unit] = scope() === 'building' ? $('buildingSelect').value.split(':').map(Number) : [null, null];
      action('/api/acceptance/plans', {
        scope_type: scope(), community: $('communitySelect').value, building, unit,
        mode: mode(), sample_size: mode() === 'sample' ? Number($('sampleSize').value) : null,
        ...acceptancePlanPreflightPayload({
          scenarioProfileId: $('acceptanceScenarioProfile').value,
          dependencyPlanEnabled: $('acceptanceDependencyPlan').checked,
          automaticReturnEnabled: $('acceptanceAutomaticReturn').checked,
        }),
      }, clearDraft);
    });
    $('startPlan').addEventListener('click', () => { const preflight = state.plan?.execution_preflight; const summary = preflight?.scenario_profile_name || preflight?.dependency_plan_enabled || preflight?.automatic_return_enabled ? `\n运行准备将统一执行一次：${preflight.scenario_profile_name || '不应用场景方案'}；${preflight.dependency_plan_enabled ? '执行已保存的 Supervisor 依赖编排' : '不执行 Supervisor 依赖编排'}；${preflight.automatic_return_enabled ? '自动返程' : '不自动返程'}。` : '\n本次按常规验收流程执行。'; if (confirm(`确认开始已冻结的验收计划？计划执行期间不能同时运行普通测试。${summary}`)) action(`/api/acceptance/plans/${state.plan.plan_id}/start`); });
    $('resumePlan').addEventListener('click', () => action(`/api/acceptance/plans/${state.plan.plan_id}/resume`));
    $('cancelPlan').addEventListener('click', () => { if (confirm('确认取消剩余验收任务？')) action(`/api/acceptance/plans/${state.plan.plan_id}/cancel`); });
    $('resolvePlan').addEventListener('click', () => { if (confirm('确认已核对现场？未知任务将按失败记录，绝不会自动重发。')) action(`/api/acceptance/plans/${state.plan.plan_id}/resolve-interruption`, { resolution: 'mark_failed' }); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshCurrentPlan(); });
    setInterval(() => { if (!document.hidden) refreshCurrentPlan(); }, 2000);
  }
  document.addEventListener('DOMContentLoaded', async () => { bind(); await refresh(); });
})();
