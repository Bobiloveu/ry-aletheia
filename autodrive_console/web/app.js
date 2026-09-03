const $ = (id) => document.getElementById(id);
const initializeTheme = () => { const key = 'ry-aletheia-theme'; const apply = () => { const light = localStorage.getItem(key) === 'light'; document.body.classList.toggle('theme-light', light); document.documentElement.style.colorScheme = light ? 'light' : 'dark'; const mark = document.querySelector('.brand .mark'); if (mark) { mark.tabIndex = 0; mark.setAttribute('role', 'button'); mark.setAttribute('aria-label', light ? '切换到深色主题' : '切换到白天主题'); mark.title = light ? '切换到深色主题' : '切换到白天主题'; } }; const toggle = () => { localStorage.setItem(key, document.body.classList.contains('theme-light') ? 'dark' : 'light'); apply(); }; const mark = document.querySelector('.brand .mark'); mark?.addEventListener('click', toggle); mark?.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); } }); apply(); };
initializeTheme();
let cases = [], uiPreferences = { case_id: '', count: 20, interval_seconds: 3 }, dependencyPlan = { enabled: false, steps: [] }, monitorNodes = [], supervisorProcesses = [], timer = null, currentRun = null;
const acknowledgedStallAlerts = new Set();
const trajectoryView = { scale: 1, x: 0, y: 0, drag: null };
// 轮询恰好落在 TF/map 短暂切换窗口时，状态包可能没有路线百分比；同一轮
// 必须保留上一次有效值，不能把实际已运行的进度视觉上归零。
const displayedRouteProgress = { runId: null, attempt: null, percent: 0 };

function routeProgressStorageKey(runId, attempt) { return `ry-aletheia-route-progress:${runId}:${attempt}`; }
function restoredRouteProgress(runId, attempt) {
  try {
    const value = Number(sessionStorage.getItem(routeProgressStorageKey(runId, attempt)));
    return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
  } catch (_) { return 0; }
}
function rememberRouteProgress(runId, attempt, percent) {
  try {
    const current = restoredRouteProgress(runId, attempt);
    sessionStorage.setItem(routeProgressStorageKey(runId, attempt), String(Math.max(current, percent)));
  } catch (_) { /* 隐私模式或存储不可用时仍由服务端快照恢复。 */ }
}

function tickClock() { $('clock').textContent = new Date().toLocaleString('zh-CN', { hour12: false }); }
function escapeHtml(value) { const el = document.createElement('span'); el.textContent = value ?? ''; return el.innerHTML; }
function statusText(status) { return ({ queued: '排队中', preparing: '预检中', running: '执行中', awaiting_recovery: '等待人工恢复', recovering: '恢复预检中', cancelling: '正在终止', cancelled: '已取消', completed: '已完成', blocked: '已拦截', failed: '运行中断' })[status] || status || '待命'; }
function minutes(seconds) { return `${(Number(seconds || 0) / 60).toFixed(2)} 分钟`; }

async function loadCases() {
  try {
    const response = await fetch('/api/cases'); const data = await response.json();
    if (!response.ok || !Array.isArray(data.cases)) throw new Error(data.error || '用例扫描接口返回异常');
    cases = data.cases; $('caseCount').textContent = cases.length;
    $('caseSelect').innerHTML = cases.length ? cases.map(c => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.alias || c.filename)}</option>`).join('') : '<option>未发现有效用例</option>';
    applyUiPreferences();
    $('issues').innerHTML = (data.validationIssues || []).map(i => `<div>配置校验：${escapeHtml(i.filename)} — ${escapeHtml(i.message)}</div>`).join(''); showCase();
  } catch (error) {
    cases = []; $('caseCount').textContent = '—'; $('caseSelect').innerHTML = '<option>用例扫描失败，请查看提示</option>'; $('issues').innerHTML = `<div>用例扫描失败：${escapeHtml(error.message)}</div>`; $('formMessage').textContent = `用例扫描失败：${error.message}`;
  }
}
function showCase() {
  const testCase = cases.find(item => item.id === $('caseSelect').value);
  $('caseMeta').textContent = testCase ? `当前用例：${testCase.alias || testCase.filename}  |  community=${testCase.parameters.community}, building=${testCase.parameters.building}, unit=${testCase.parameters.unit}, floor=${testCase.parameters.floor}, door=${testCase.parameters.door}` : '请在 tasks/ 目录中放入有效的 JSON 用例文件';
}
function applyUiPreferences() {
  if (uiPreferences.case_id && cases.some(item => item.id === uiPreferences.case_id)) $('caseSelect').value = uiPreferences.case_id;
  $('count').value = uiPreferences.count ?? 20; $('interval').value = uiPreferences.interval_seconds ?? 3; showCase();
}
function rememberUiPreferences() {
  uiPreferences = { case_id: $('caseSelect').value || '', count: Number($('count').value || 20), interval_seconds: Number($('interval').value || 0) };
  fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ui_preferences: uiPreferences }) }).catch(() => {});
}
function renderNodes(preflight) {
  const nodes = preflight?.node_states || [];
  const scenario = preflight?.scenario;
  const scenarioStatus = scenario ? `场景方案 ${scenario.profile_name ? `“${scenario.profile_name}”` : "常规配置"} · ${scenario.restore_state === 'restored' ? '已恢复' : scenario.restore_state === 'restore_failed' ? '恢复失败' : scenario.state === 'applied' ? '已应用，等待节点编排' : scenario.message || '未绑定'}` : '';
  const mapStatus = preflight?.trajectory_maps;
  const orchestration = preflight?.orchestration;
  const orchestrationStatus = orchestration?.enabled ? ` · 依赖总闸 ${orchestration.all_ready ? '全部 RUNNING' : '未就绪'}` : '';
  const serviceStatus = preflight?.ros_service ? ` · ${preflight.ros_service.message}` : '';
  const finalGateStatus = preflight?.final_dependency_gate ? ` · 服务后总闸 ${preflight.final_dependency_gate.ok ? '通过' : '未通过'}` : '';
  const checkedAt = preflight?.node_states_checked_at ? ` · 最近检查 ${new Date(preflight.node_states_checked_at).toLocaleTimeString('zh-CN', { hour12: false })}` : '';
  const summary = preflight ? `${scenarioStatus ? `${scenarioStatus} · ` : ''}${preflight.task_sync}${orchestrationStatus}${serviceStatus}${finalGateStatus}${mapStatus ? ` · ${mapStatus.message}` : ''}${checkedAt}` : '开始测试后将按编排重启并检查本机 Supervisor 节点。';
  const ready = Boolean(preflight?.final_dependency_gate?.ok || (orchestration?.enabled && orchestration.all_ready));
  const blocked = Boolean(preflight && !ready && (preflight.final_dependency_gate || orchestration?.enabled));
  $('syncStatus').textContent = !preflight ? '等待预检' : ready ? '预检通过' : blocked ? '预检未通过' : '预检已更新';
  $('preflightSummary').textContent = summary;
  $('nodeGrid').innerHTML = nodes.length ? nodes.map(node => `<div class="node"><div class="node-top"><b>${escapeHtml(node.label)}</b><span class="node-state ${node.status === 'RUNNING' ? 'running' : 'bad'}">${escapeHtml(node.status)}</span></div><small>${escapeHtml(node.supervisor)}${node.required ? ' · REQUIRED' : ' · OPTIONAL'}</small></div>`).join('') : '<div class="node-empty">开始测试后自动读取本机 Supervisor 节点状态</div>';
}
function renderLiveProgress(run) {
  const progress = run?.liveProgress;
  const visible = run?.status === 'running' && Boolean(progress?.visible);
  $('routeProgress').hidden = !visible;
  if (!visible) return;
  const runId = String(run.id || ''); const attempt = progress.attempt;
  if (displayedRouteProgress.runId !== runId || displayedRouteProgress.attempt !== attempt) {
    displayedRouteProgress.runId = runId;
    displayedRouteProgress.attempt = progress.attempt;
    displayedRouteProgress.percent = restoredRouteProgress(runId, attempt);
  }
  // 仅轨迹采集器明确确认的投影才可显示为真实百分比；缺字段的旧快照或
  // 新一轮初始化都属于未知，不能把数值占位 0 误导为“路线卡在起点”。
  const progressAvailable = progress.progress_available === true;
  const receivedPercent = Number(progress.percent);
  if (progressAvailable && Number.isFinite(receivedPercent)) displayedRouteProgress.percent = Math.max(displayedRouteProgress.percent, Math.max(0, Math.min(100, receivedPercent)));
  const percent = displayedRouteProgress.percent;
  if (progressAvailable) rememberRouteProgress(runId, attempt, percent);
  $('routeProgressPercent').textContent = progressAvailable ? `${percent.toFixed(1)}%` : '—';
  $('routeProgressFill').style.width = `${progressAvailable ? percent : 0}%`;
  $('routeProgressAttempt').textContent = `本轮 T-${String(progress.attempt).padStart(3, '0')} / ${progress.attempt_total} · 已采集 ${progress.points || 0} 点`;
  const elevator = progress.elevator_wait;
  $('routeProgressRoute').textContent = elevator?.active ? `电梯流程 · ${elevator.task || elevator.waypoint_id || elevator.speed_mode || '等待调度'} · 已等待 ${Math.round(elevator.elapsed_s || 0)} 秒` : (!progressAvailable ? `${progress.map_label || '当前地图'} · 等待切换至 ${progress.expected_map_label || '当前子任务地图'}` : (progress.route_name ? `${progress.map_label || '任务地图'} · ${progress.route_name}（路径段 ${progress.route_index}/${progress.route_total}，段内 ${Number(progress.route_percent || 0).toFixed(1)}% · ${progress.match_mode || '等待匹配'}）` : (progress.map_label || progress.state || '等待任务地图')));
  $('routeProgressHint').textContent = `${progress.state || '本轮线路进度'}。由 /odom 投影到任务理想路线，仅作实时参考，不参与通过判定。`;
  if (elevator?.active && !elevator.timed_out) $('routeProgressHint').textContent = `电梯任务预期等待中；已暂停普通 ${30} 秒车辆停滞提醒。电梯状态退出后将自动恢复监测。`;
  if (progress.stalled) $('routeProgressHint').textContent = `注意：${progress.alert_reason || '车辆可能停滞'}，已持续约 ${Math.round(progress.stalled_seconds || 0)} 秒。请检查车辆状态。`;
  const alertKey = `${run.id}:${progress.attempt}:${progress.alert_id}`;
  if (progress.alert && !acknowledgedStallAlerts.has(alertKey)) {
    acknowledgedStallAlerts.add(alertKey);
    const elevatorTimeout = Boolean(elevator?.timed_out);
    $('stallDialogBody').textContent = elevatorTimeout ? `电梯流程已等待约 ${Math.round(elevator.elapsed_s || 0)} 秒，超过预期等待阈值。请确认电梯是否仍在调度或车辆是否需要人工处置；本提醒不会自动停止当前任务。` : `${progress.alert_reason || '车辆可能停滞'}已持续约 ${Math.round(progress.stalled_seconds || 0)} 秒。请前往确认小车是否急停、受阻或发生突发情况；本提醒不会自动停止当前任务。`;
    $('stallReleased').textContent = elevatorTimeout ? '电梯仍在调度，继续等待' : '急停已解除，继续本轮';
    $('stallDialog').classList.add('show'); $('stallDialog').setAttribute('aria-hidden', 'false');
  }
}
function renderRun(run) {
  currentRun = run || null;
  const hasRun = Boolean(run), summary = run?.summary || { completed: 0, passed: 0, failed: 0, passRate: 0 };
  $('runStatus').textContent = hasRun ? statusText(run.status) : '待命'; $('runHint').textContent = hasRun ? `${summary.completed}/${run.requestedCount} 次已完成` : 'PRE-FLIGHT REQUIRED'; $('passRate').textContent = hasRun && summary.completed ? `${summary.passRate}%` : '—'; $('runId').textContent = hasRun ? `RUN / ${run.id}` : '';
  $('statusBadge').textContent = hasRun ? run.status.toUpperCase() : 'IDLE'; $('statusBadge').className = `badge ${run?.status === 'running' || run?.status === 'preparing' ? '' : 'muted'}`;
  $('progressBar').style.width = `${hasRun ? summary.completed / run.requestedCount * 100 : 0}%`; $('progressText').textContent = hasRun ? `${statusText(run.status)} · ${summary.completed}/${run.requestedCount} 次 · ${summary.passed} 通过 / ${summary.failed} 失败${summary.cancelled ? ` / ${summary.cancelled} 已取消` : ''}` : '暂无执行任务'; $('durationText').textContent = run?.attempts?.length ? `最近 ${minutes(run.attempts.at(-1).duration_s)}` : '—';
  $('resultBody').innerHTML = run?.attempts?.length ? run.attempts.slice().reverse().map(item => `<tr><td>T-${String(item.index).padStart(3, '0')}</td><td>${new Date(item.started_at).toLocaleTimeString('zh-CN', { hour12: false })}</td><td class="status ${item.status}">${item.status.toUpperCase()}</td><td>${escapeHtml(item.message)}</td><td>${minutes(item.duration_s)}</td><td>${item.trajectory?.visualizations?.length ? `<button class="trajectory-view" data-attempt="${item.index}" type="button">查看轨迹</button>` : '—'}</td></tr>`).join('') : `<tr><td colspan="6" class="empty">${escapeHtml(run?.error || '等待测试任务')}</td></tr>`;
  $('chart').innerHTML = run?.attempts?.length ? run.attempts.map(item => `<div class="bar ${item.status === 'failed' ? 'failed' : ''}" data-tip="${minutes(item.duration_s)}" style="height:${Math.min(100, Math.max(12, item.duration_s * 12))}%"></div>`).join('') : '<div class="chart-empty">执行后显示单次耗时趋势</div>';
  renderNodes(run?.preflight); renderLiveProgress(run); const active = ['running', 'queued', 'preparing', 'awaiting_recovery', 'recovering', 'cancelling'].includes(run?.status); $('startButton').disabled = active || !cases.length; $('cancelButton').disabled = !['queued', 'preparing', 'running', 'awaiting_recovery', 'recovering'].includes(run?.status); $('recoveryAction').hidden = run?.status !== 'awaiting_recovery'; $('resumeButton').disabled = run?.status !== 'awaiting_recovery'; $('serviceState').textContent = run?.error || (run?.preflight?.ros_service?.ok ? '本机依赖与 ROS2 服务均已就绪' : '等待本机节点预检');
}
async function loadSettings() {
  const settings = await (await fetch('/api/settings')).json(); uiPreferences = settings.ui_preferences || uiPreferences; dependencyPlan = settings.dependency_plan || { enabled: false, steps: [] }; monitorNodes = settings.monitor_nodes || []; applyUiPreferences(); renderDependencyEditor();
}
async function poll() { const data = await (await fetch('/api/runs/latest')).json(); renderRun(data.run); if (['running', 'queued', 'preparing', 'awaiting_recovery', 'recovering', 'cancelling'].includes(data.run?.status)) timer = setTimeout(poll, 1000); }
function toast(message, tone = 'success') { const element = $('toast'); element.textContent = message; element.className = `toast show ${tone}`; clearTimeout(toast.timer); toast.timer = setTimeout(() => element.className = 'toast', 3200); }
function confirmAction({ eyebrow, title, body, confirmText, danger = false }) {
  return new Promise(resolve => { const dialog = $('confirmDialog'); $('dialogEyebrow').textContent = eyebrow; $('dialogTitle').textContent = title; $('dialogBody').textContent = body; $('dialogConfirm').textContent = confirmText; $('dialogConfirm').className = danger ? 'danger-confirm' : ''; dialog.classList.add('show'); dialog.setAttribute('aria-hidden', 'false'); const finish = answer => { dialog.classList.remove('show'); dialog.setAttribute('aria-hidden', 'true'); $('dialogConfirm').onclick = null; $('dialogCancel').onclick = null; resolve(answer); }; $('dialogConfirm').onclick = () => finish(true); $('dialogCancel').onclick = () => finish(false); });
}
function showTrajectory(attempt) {
  const views = attempt?.trajectory?.visualizations || []; if (!views.length || !currentRun) return;
  const dialog = $('trajectoryDialog'); $('trajectoryTitle').textContent = `T-${String(attempt.index).padStart(3, '0')} 地图运行轨迹`;
  // 旧报告没有 point_count 时，从保存的 segments 推导。将包含实测点的地图排在
  // 最前面，避免同名离线缓存/运行时地图并存时默认打开一张“无轨迹”的底图。
  const pointCount = view => Number.isFinite(Number(view.point_count))
    ? Number(view.point_count)
    : (attempt?.trajectory?.segments || []).filter(segment => segment.map_id === view.map_id).reduce((total, segment) => total + (Array.isArray(segment.points) ? segment.points.length : 0), 0);
  const orderedViews = views.slice().sort((left, right) => pointCount(right) - pointCount(left));
  $('trajectoryMapSelect').innerHTML = orderedViews.map(view => {
    const points = pointCount(view);
    const suffix = points ? ` · 实测 ${points} 点` : ' · 未采到实测点';
    return `<option value="${escapeHtml(view.map_id)}">${escapeHtml(view.label)}${suffix}</option>`;
  }).join('');
  const display = () => { const view = orderedViews.find(item => item.map_id === $('trajectoryMapSelect').value); $('trajectoryImage').src = `/api/runs/${encodeURIComponent(currentRun.id)}/attempts/${attempt.index}/trajectory/${encodeURIComponent(view.map_id)}`; };
  $('trajectoryMapSelect').onchange = display; display(); dialog.classList.add('show'); dialog.setAttribute('aria-hidden', 'false');
}
function applyTrajectoryTransform() { $('trajectoryImage').style.transform = `translate(-50%, -50%) translate(${trajectoryView.x}px, ${trajectoryView.y}px) scale(${trajectoryView.scale})`; }
function resetTrajectoryView() {
  const image = $('trajectoryImage'), canvas = $('trajectoryCanvas'); if (!image.naturalWidth || !image.naturalHeight) return;
  trajectoryView.scale = Math.min(1, (canvas.clientWidth - 28) / image.naturalWidth, (canvas.clientHeight - 28) / image.naturalHeight); trajectoryView.x = 0; trajectoryView.y = 0; applyTrajectoryTransform();
}
function zoomTrajectory(factor, centerX = null, centerY = null) {
  const canvas = $('trajectoryCanvas'); const rect = canvas.getBoundingClientRect();
  // 图像平移以画布中心为原点；将鼠标位置转换到相同坐标系，缩放后保持该地图点位于光标下。
  const cx = (centerX ?? rect.width / 2) - rect.width / 2, cy = (centerY ?? rect.height / 2) - rect.height / 2;
  const next = Math.max(.15, Math.min(12, trajectoryView.scale * factor)); const ratio = next / trajectoryView.scale;
  trajectoryView.x = cx - (cx - trajectoryView.x) * ratio; trajectoryView.y = cy - (cy - trajectoryView.y) * ratio; trajectoryView.scale = next; applyTrajectoryTransform();
}
function renderDependencyEditor() {
  $('dependencyEnabled').checked = Boolean(dependencyPlan.enabled);
  const selected = new Set(dependencyPlan.steps.flatMap(step => step.nodes));
  $('discoveredProcesses').innerHTML = supervisorProcesses.length ? supervisorProcesses.map(process => `<div class="process-choice ${selected.has(process.name) ? 'assigned' : ''}" role="row"><div class="process-selection" role="cell"><label><input class="monitor-node" type="checkbox" value="${escapeHtml(process.name)}" ${monitorNodes.includes(process.name) ? 'checked' : ''} title="运行依赖状态监控" aria-label="监控 ${escapeHtml(process.name)} 的运行状态"><span>监控</span></label></div><div class="process-selection" role="cell"><label><input class="orchestration-node" type="checkbox" value="${escapeHtml(process.name)}" ${selected.has(process.name) ? 'disabled' : ''} title="加入启动编排" aria-label="将 ${escapeHtml(process.name)} 加入启动编排"><span>编排</span></label></div><span class="node-state ${process.status === 'RUNNING' ? 'running' : 'bad'}" role="cell">${escapeHtml(process.status)}</span><div class="process-identity" role="cell"><b>${escapeHtml(process.name)}</b><small>${escapeHtml(process.detail)}</small></div></div>`).join('') : '<p>点击“重新识别节点”读取本机状态。</p>';
  $('dependencyFlow').innerHTML = dependencyPlan.steps.length ? dependencyPlan.steps.map((step, index) => `<section class="flow-step" data-step="${index}" aria-labelledby="flowStepTitle${index}"><div class="flow-step-summary"><strong id="flowStepTitle${index}" class="flow-index">阶段 ${index + 1}</strong><small>并行处理后，等待全部节点稳定 RUNNING</small></div><div class="flow-step-nodes"><span>本阶段节点</span><div class="flow-nodes">${step.nodes.map(name => `<span>${escapeHtml(name)}</span>`).join('')}</div></div><label class="flow-wait">额外稳定等待 <input class="step-wait" type="number" min="0" max="300" value="${Number(step.wait_seconds || 0)}" aria-label="阶段 ${index + 1} 的额外稳定等待秒数"> <span>秒</span></label><div class="flow-actions" role="group" aria-label="阶段 ${index + 1} 操作"><button class="move-step" data-direction="up" type="button" aria-label="将阶段上移" ${index ? '' : 'disabled'}>上移</button><button class="move-step" data-direction="down" type="button" aria-label="将阶段下移" ${index < dependencyPlan.steps.length - 1 ? '' : 'disabled'}>下移</button><button class="remove-step" type="button" aria-label="移除阶段">移除</button></div></section>${index < dependencyPlan.steps.length - 1 ? '<p class="flow-arrow">上一阶段全部就绪后继续</p>' : ''}`).join('') : '<p>尚未配置依赖阶段。</p>';
}
async function discoverSupervisor() {
  $('dependencyMessage').textContent = '正在读取本机 Supervisor 状态…';
  try { const response = await fetch('/api/supervisor/processes'); const data = await response.json(); if (!response.ok) throw new Error(data.error); supervisorProcesses = data.processes; $('dependencyMessage').style.color = '#35d69c'; $('dependencyMessage').textContent = `已识别 ${supervisorProcesses.length} 个 Supervisor 进程。`; renderDependencyEditor(); } catch (error) { $('dependencyMessage').style.color = ''; $('dependencyMessage').textContent = error.message; }
}
function saveDependencyPlan() {
  return fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dependency_plan: dependencyPlan, monitor_nodes: monitorNodes }) }).then(async response => { const data = await response.json(); if (!response.ok) throw new Error(data.error); dependencyPlan = data.dependency_plan; monitorNodes = data.monitor_nodes || []; return data; });
}

$('caseSelect').addEventListener('change', () => { showCase(); rememberUiPreferences(); });
$('count').addEventListener('change', rememberUiPreferences); $('interval').addEventListener('change', rememberUiPreferences);
$('dependencyButton').addEventListener('click', () => { $('dependencyDialog').classList.add('show'); $('dependencyDialog').setAttribute('aria-hidden', 'false'); renderDependencyEditor(); if (!supervisorProcesses.length) discoverSupervisor(); });
$('dependencyClose').addEventListener('click', () => { $('dependencyDialog').classList.remove('show'); $('dependencyDialog').setAttribute('aria-hidden', 'true'); });
function closeStallDialog() { $('stallDialog').classList.remove('show'); $('stallDialog').setAttribute('aria-hidden', 'true'); }
async function submitStallAction(action, label) {
  if (!currentRun) return;
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(currentRun.id)}/stall-action`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }) });
    const data = await response.json(); if (!response.ok) throw new Error(data.error);
    closeStallDialog(); renderRun(data.run); toast(`${label}，已写入本次测试记录。`, action === 'mark_attempt_failed' ? 'warning' : 'success'); poll();
  } catch (error) { toast(`停滞处置提交失败：${error.message}`, 'error'); }
}
$('stallReleased').addEventListener('click', () => submitStallAction('released_estop', '已记录急停/阻塞解除，将继续当前轮'));
$('stallFailAttempt').addEventListener('click', () => submitStallAction('mark_attempt_failed', '已记录人工判定失败；当前调用返回后将等待人工恢复'));
$('stallDialogClose').addEventListener('click', () => submitStallAction('continue_observing', '已记录继续观察'));
$('discoverSupervisor').addEventListener('click', discoverSupervisor);
$('dependencyEnabled').addEventListener('change', event => { dependencyPlan.enabled = event.target.checked; });
$('addDependencyStep').addEventListener('click', () => { const nodes = [...$('discoveredProcesses').querySelectorAll('.orchestration-node:checked')].map(item => item.value); if (!nodes.length) { $('dependencyMessage').style.color = ''; $('dependencyMessage').textContent = '请先选择至少一个未分配的编排节点。'; return; } dependencyPlan.steps.push({ nodes, wait_seconds: 0 }); renderDependencyEditor(); });
$('discoveredProcesses').addEventListener('change', event => { if (!event.target.matches('.monitor-node')) return; const name = event.target.value; monitorNodes = event.target.checked ? [...new Set([...monitorNodes, name])] : monitorNodes.filter(item => item !== name); });
$('dependencyFlow').addEventListener('click', event => { const step = event.target.closest('.flow-step'); if (!step) return; const index = Number(step.dataset.step); if (event.target.closest('.remove-step')) dependencyPlan.steps.splice(index, 1); const move = event.target.closest('.move-step'); if (move) { const other = index + (move.dataset.direction === 'up' ? -1 : 1); [dependencyPlan.steps[index], dependencyPlan.steps[other]] = [dependencyPlan.steps[other], dependencyPlan.steps[index]]; } renderDependencyEditor(); });
$('dependencyFlow').addEventListener('change', event => { if (!event.target.matches('.step-wait')) return; dependencyPlan.steps[Number(event.target.closest('.flow-step').dataset.step)].wait_seconds = Number(event.target.value); });
$('saveDependencyPlan').addEventListener('click', async () => { try { await saveDependencyPlan(); $('dependencyMessage').style.color = '#35d69c'; $('dependencyMessage').textContent = '依赖编排已保存；下次创建测试计划时将按阶段强制重启。'; toast('测试依赖编排已保存。'); } catch (error) { $('dependencyMessage').style.color = ''; $('dependencyMessage').textContent = error.message; } });
$('resultBody').addEventListener('click', event => { const button = event.target.closest('.trajectory-view'); if (!button) return; showTrajectory(currentRun?.attempts?.find(item => item.index === Number(button.dataset.attempt))); });
$('trajectoryClose').addEventListener('click', () => { $('trajectoryDialog').classList.remove('show'); $('trajectoryDialog').setAttribute('aria-hidden', 'true'); $('trajectoryImage').removeAttribute('src'); });
$('trajectoryImage').addEventListener('load', resetTrajectoryView); $('trajectoryReset').addEventListener('click', resetTrajectoryView); $('trajectoryZoomIn').addEventListener('click', () => zoomTrajectory(1.25)); $('trajectoryZoomOut').addEventListener('click', () => zoomTrajectory(.8));
$('trajectoryCanvas').addEventListener('wheel', event => { event.preventDefault(); const rect = event.currentTarget.getBoundingClientRect(); zoomTrajectory(event.deltaY < 0 ? 1.15 : 1 / 1.15, event.clientX - rect.left, event.clientY - rect.top); }, { passive: false });
$('trajectoryCanvas').addEventListener('pointerdown', event => { if (event.button !== 0) return; trajectoryView.drag = { x: event.clientX, y: event.clientY }; event.currentTarget.setPointerCapture(event.pointerId); });
$('trajectoryCanvas').addEventListener('pointermove', event => { if (!trajectoryView.drag) return; trajectoryView.x += event.clientX - trajectoryView.drag.x; trajectoryView.y += event.clientY - trajectoryView.drag.y; trajectoryView.drag = { x: event.clientX, y: event.clientY }; applyTrajectoryTransform(); });
$('trajectoryCanvas').addEventListener('pointerup', event => { trajectoryView.drag = null; event.currentTarget.releasePointerCapture(event.pointerId); });
$('trajectoryCanvas').addEventListener('pointercancel', () => { trajectoryView.drag = null; });
$('startButton').addEventListener('click', async () => {
  $('formMessage').textContent = '';
  const testCase = cases.find(item => item.id === $('caseSelect').value); const accepted = await confirmAction({ eyebrow: 'CONFIRM TEST EXECUTION', title: '确认开始自动化测试？', body: `用例：${testCase?.alias || testCase?.filename || '未选择'}；执行 ${$('count').value} 轮，每轮间隔 ${$('interval').value} 秒。`, confirmText: '确认开始' }); if (!accepted) return;
  try { const response = await fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ caseId: $('caseSelect').value, count: +$('count').value, intervalSeconds: +$('interval').value, prepareTrajectoryMaps: true }) }); const data = await response.json(); if (!response.ok) throw new Error(data.error); renderRun(data.run); toast('测试计划已创建，正在执行前置条件校验。'); poll(); } catch (error) { $('formMessage').textContent = error.message; }
});
$('cancelButton').addEventListener('click', async () => {
  if (!currentRun) return;
  const accepted = await confirmAction({ eyebrow: 'STOP REMAINING TESTS', title: '确认终止剩余测试轮次？', body: '不会强行中断已发出的 ROS 服务调用；当前轮结束后，将不再发起后续轮次。', confirmText: '终止剩余轮次', danger: true }); if (!accepted) return;
  try { const response = await fetch(`/api/runs/${encodeURIComponent(currentRun.id)}/cancel`, { method: 'POST' }); const data = await response.json(); if (!response.ok) throw new Error(data.error); renderRun(data.run); toast('已请求终止：当前轮完成后将停止后续测试。', 'warning'); poll(); } catch (error) { toast(`终止请求失败：${error.message}`, 'error'); }
});
$('resumeButton').addEventListener('click', async () => {
  if (!currentRun) return;
  const accepted = await confirmAction({ eyebrow: 'MANUAL RECOVERY CONFIRMATION', title: '确认车辆已恢复到测试起点？', body: '继续后将重新执行当前依赖编排、等待 Supervisor 节点稳定 RUNNING、重新发现 ROS2 服务，然后从下一轮开始执行。失败轮次会保留为 FAILED。', confirmText: '确认恢复并继续' }); if (!accepted) return;
  try { const response = await fetch(`/api/runs/${encodeURIComponent(currentRun.id)}/resume`, { method: 'POST' }); const data = await response.json(); if (!response.ok) throw new Error(data.error); renderRun(data.run); toast('已确认人工恢复，正在重新执行依赖预检。', 'warning'); poll(); } catch (error) { toast(`恢复请求失败：${error.message}`, 'error'); }
});
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
async function waitForConsoleShutdown(timeoutMilliseconds = 8000) {
  const deadline = Date.now() + timeoutMilliseconds;
  await sleep(450);
  while (Date.now() < deadline) {
    try {
      await fetch(`/api/system/upgrade?shutdownProbe=${Date.now()}`, { cache: 'no-store' });
    } catch (_) {
      return true;
    }
    await sleep(300);
  }
  return false;
}
$('shutdownButton').addEventListener('click', async () => {
  const accepted = await confirmAction({ eyebrow: 'SAFE SHUTDOWN', title: '确认退出测试控制台？', body: '当前 Web 服务将停止。若测试正在执行，建议等待当前测试结束后再退出。', confirmText: '安全退出', danger: true });
  if (!accepted) return;
  try {
    const response = await fetch('/api/system/shutdown', { method: 'POST' });
    if (!response.ok) throw new Error('控制台未接受退出请求');
    toast('正在确认控制台已停止…', 'warning');
    if (!await waitForConsoleShutdown()) {
      throw new Error('8087 仍在响应，控制台未停止。请确认没有其他 RY Aletheia 进程仍在运行。');
    }
    document.body.innerHTML = '<main class="closed-state"><p>TEST CONSOLE STOPPED</p><h1>控制台已安全退出</h1><span>8087 已停止监听，可以关闭此浏览器标签页。</span></main>';
  } catch (error) {
    toast(`安全退出未完成：${error.message}`, 'error');
  }
});
tickClock(); setInterval(tickClock, 1000); Promise.all([loadCases(), loadSettings()]).then(poll).catch(error => $('formMessage').textContent = `控制台连接失败：${error.message}`);
