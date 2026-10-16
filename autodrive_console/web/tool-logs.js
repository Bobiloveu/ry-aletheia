import { requestJson } from "./platform/http.js";
import { formatFileSize, formatUnixSeconds } from "./platform/format.js";

const $ = id => document.getElementById(id);
const esc = value => { const node = document.createElement('span'); node.textContent = value ?? ''; return node.innerHTML.replaceAll('"', '&quot;').replaceAll("'", '&#39;'); };
const labels = { INFO: '信息', WARNING: '警告', ERROR: '错误', CRITICAL: '严重错误' };
let scope = 'all';
let fileScope = 'current';
let files = [], storage, policyDirty = false, busy = false, pendingAction;
let fileRequest, logRequest, generation = 0;

async function boundedRequest(url, options = {}, controller = new AbortController()) {
  const deadline = window.setTimeout(() => controller.abort(), 15000);
  try {
    return await requestJson(url, { ...options, signal: controller.signal }, { errorMessage: '日志操作未完成' });
  } finally { window.clearTimeout(deadline); }
}

function message(text, error = false, source = 'operation') {
  $('logManagementMessage').textContent = text;
  $('logManagementMessage').dataset.error = String(error);
  $('logManagementMessage').dataset.source = source;
}

function row(item) {
  const exception = item.exception ? `<details class="log-exception"><summary>查看完整异常堆栈</summary><pre>${esc(item.exception)}</pre></details>` : '';
  return `<div class="log-row level-${esc(item.level).toLowerCase()}"><time>${esc(item.time)}</time><span class="log-level">${esc(labels[item.level] || item.level)}</span><span class="log-source">${esc(item.source)}</span><div><p>${esc(item.message)}</p>${exception}</div></div>`;
}
function fileRow(file) {
  const href = `/api/tool-logs/files/${encodeURIComponent(file.name)}/download`;
  const action = file.file_id && (file.can_clear || file.can_delete)
    ? `<button type="button" class="log-action ${file.can_delete ? 'log-danger-action' : ''}" data-log-action="${file.can_clear ? 'clear' : 'delete'}" data-file-name="${esc(file.name)}" aria-label="${file.can_clear ? '清空' : '删除'}${esc(file.label)}" ${busy ? 'disabled' : ''}>${file.can_clear ? '清空' : '删除'}</button>` : '';
  return `<article class="diagnostic-file-row"><div class="diagnostic-file-main"><h3>${esc(file.label)}</h3><p>${esc(file.detail)}</p><code>${esc(file.name)}</code></div><div class="diagnostic-file-meta"><span>${esc(formatFileSize(file.size_bytes))}</span><time>${esc(formatUnixSeconds(file.modified_at))}</time></div><div class="diagnostic-file-actions"><a class="log-action diagnostic-file-download" href="${href}">下载</a>${action}</div></article>`;
}

function renderFiles() {
  const selected = files.filter(file => (file.kind || 'current') === fileScope);
  const historical = files.filter(file => file.kind === 'archive').length;
  $('logFileCount').textContent = `${files.length - historical} 个当前 · ${historical} 个历史`;
  $('logHistoryCount').textContent = String(historical);
  $('deleteLogHistory').disabled = busy || !historical || !storage?.policy;
  $('diagnosticFileList').innerHTML = selected.length ? selected.map(fileRow).join('')
    : `<div class="page-empty">${fileScope === 'archive' ? '暂无历史日志。文件轮转后会显示在这里。' : '尚未产生可下载的诊断日志。'}</div>`;
}

function renderStorage() {
  const available = !!storage?.policy;
  $('retentionPolicyForm').hidden = !available;
  $('cleanupLogs').disabled = busy || !available;
  $('saveRetentionPolicy').disabled = busy || !available;
  $('storageSummary').textContent = available ? `${formatFileSize(storage.total_size_bytes)} / ${formatFileSize(storage.limit_bytes)}` : '存储信息暂不可用';
  $('storageSummary').dataset.overBudget = String(available && storage.total_size_bytes > storage.limit_bytes);
  $('logRetentionSummary').textContent = available ? `${storage.last_error ? '自动整理需要关注' : '自动整理已启用'} · 历史保留 ${storage.policy.retention_days} 天` : '可以继续下载已有日志。';
  $('logRetentionError').textContent = storage?.last_error || '';
  $('logLastCleanup').textContent = storage?.last_cleanup_at ? `最近整理：${formatUnixSeconds(storage.last_cleanup_at)}` : '后台会自动检查日志容量。';
  if (available && !policyDirty) {
    $('retentionDays').value = String(storage.policy.retention_days);
    $('retentionTotalMib').value = String(storage.policy.max_total_mib);
    $('retentionFileMib').value = String(storage.policy.max_file_mib);
  }
}

function loadLogs() {
  if (logRequest) return logRequest.promise;
  const currentScope = scope;
  const current = { controller: new AbortController(), generation };
  logRequest = current;
  current.promise = (async () => {
    try {
      const payload = await boundedRequest(`/api/tool-logs?scope=${currentScope}`, {}, current.controller);
      if (current.generation !== generation || currentScope !== scope) return;
      const entries = Array.isArray(payload.entries) ? payload.entries : [];
      $('logCount').textContent = `${entries.length} 条`;
      $('logDetail').textContent = currentScope === 'errors' ? '最近 200 条错误事件' : '最近 200 条控制台事件';
      $('logList').innerHTML = entries.length ? entries.map(row).join('') : '<div class="page-empty">当前范围内尚无日志记录。</div>';
    } catch (error) {
      if (current.generation === generation && currentScope === scope)
        $('logList').innerHTML = `<div class="page-empty">读取失败：${esc(error.message)}</div>`;
    } finally { if (logRequest === current) logRequest = undefined; }
  })();
  return current.promise;
}

function loadDiagnosticFiles() {
  if (fileRequest) return fileRequest.promise;
  const current = { controller: new AbortController(), generation };
  fileRequest = current;
  current.promise = (async () => {
    try {
      const payload = await boundedRequest('/api/tool-logs/files', {}, current.controller);
      if (current.generation !== generation) return;
      if (!Array.isArray(payload.files)) throw Error('日志清单响应不完整');
      files = payload.files;
      storage = payload.storage;
      renderStorage(); renderFiles();
      if ($('logManagementMessage').dataset.source === 'files') message('');
    } catch (error) {
      if (current.generation === generation) {
        $('logFileCount').textContent = '清单暂未更新';
        message(`日志清单读取失败：${error.message}`, true, 'files');
      }
    } finally { if (fileRequest === current) fileRequest = undefined; }
  })();
  return current.promise;
}

function refreshAll() { if (busy) return Promise.resolve(); return Promise.all([loadLogs(), loadDiagnosticFiles()]); }
function invalidateReads() {
  generation++;
  fileRequest?.controller.abort(); logRequest?.controller.abort();
  fileRequest = logRequest = undefined;
}
function setBusy(value) {
  busy = value;
  for (const id of ['refreshLogs', 'cleanupLogs', 'deleteLogHistory', 'saveRetentionPolicy', 'logConfirmAction', 'logCancelAction']) $(id).disabled = value;
  document.querySelectorAll('[data-log-action]').forEach(button => { button.disabled = value; });
  for (const id of ['retentionDays', 'retentionTotalMib', 'retentionFileMib']) $(id).disabled = value;
  if (!value) { renderStorage(); renderFiles(); }
}

async function mutate(url, method, body, success) {
  if (busy) return;
  invalidateReads(); setBusy(true);
  try {
    const result = await boundedRequest(url, {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (result.storage) storage = result.storage;
    if (method === 'PUT') policyDirty = false;
    const skipped = result.skipped_count ? `；${result.skipped_count} 项正生成下载快照，暂未整理` : '';
    message(`${success}，释放 ${formatFileSize(result.freed_bytes || 0)}${skipped}。`);
  } catch (error) {
    message(`操作未确认：${error.message}。请刷新核对，系统不会重复提交。`, true);
  } finally {
    $('logActionDialog').close(); pendingAction = undefined;
    setBusy(false); await refreshAll();
  }
}

function openAction(kind, file) {
  if (busy) return;
  if (kind !== 'history' && (!file?.file_id || (kind === 'clear' ? !file.can_clear : !file.can_delete))) return;
  pendingAction = {kind, file};
  $('logActionTitle').textContent = kind === 'clear' ? '清空当前日志？' : kind === 'history' ? '删除全部历史日志？' : '删除历史日志？';
  $('logActionTarget').textContent = file?.label || `${files.filter(item => item.kind === 'archive').length} 个历史文件`;
  $('logActionDescription').textContent = kind === 'clear'
    ? '当前内容将被清空，后续运行日志会继续记录。已有历史文件保留。'
    : kind === 'history' ? '仅删除历史文件，当前日志保留。删除后无法恢复。' : '这份历史文件将被删除，删除后无法恢复。';
  $('logConfirmAction').textContent = kind === 'clear' ? '确认清空' : '确认删除';
  $('logActionDialog').showModal();
}

async function confirmAction() {
  if (busy || !pendingAction) return;
  const {kind, file} = pendingAction;
  if (kind === 'history') return mutate('/api/tool-logs/cleanup', 'POST', {mode:'history', confirm:true}, '历史日志已删除');
  const url = `/api/tool-logs/files/${encodeURIComponent(file.name)}`;
  return mutate(kind === 'clear' ? `${url}/clear` : url, kind === 'clear' ? 'POST' : 'DELETE', {file_id:file.file_id, confirm:true}, kind === 'clear' ? '当前日志已清空' : '历史日志已删除');
}

document.querySelectorAll('.log-tab').forEach(button => button.addEventListener('click', () => {
  scope = button.dataset.scope;
  document.querySelectorAll('.log-tab').forEach(item => {
    item.classList.toggle('active', item === button);
    item.setAttribute('aria-pressed', String(item === button));
  });
  logRequest?.controller.abort(); logRequest = undefined;
  loadLogs();
}));
document.querySelectorAll('.file-tab').forEach(button => button.addEventListener('click', () => {
  fileScope = button.dataset.fileScope;
  document.querySelectorAll('.file-tab').forEach(item => {
    item.classList.toggle('active', item === button);
    item.setAttribute('aria-pressed', String(item === button));
  });
  renderFiles();
}));
$('diagnosticFileList').addEventListener('click', event => {
  const button = event.target.closest('button[data-log-action]');
  if (!button) return;
  openAction(button.dataset.logAction, files.find(file => file.name === button.dataset.fileName));
});
$('retentionPolicyForm').addEventListener('input', () => { policyDirty = true; });
$('retentionPolicyForm').addEventListener('submit', event => {
  event.preventDefault();
  return mutate('/api/tool-logs/retention', 'PUT', {policy:{retention_days:Number($('retentionDays').value),max_total_mib:Number($('retentionTotalMib').value),max_file_mib:Number($('retentionFileMib').value)}}, '保留设置已保存并整理');
});
$('cleanupLogs').addEventListener('click', () => mutate('/api/tool-logs/cleanup', 'POST', {mode:'expired', confirm:true}, '已按保留设置整理'));
$('deleteLogHistory').addEventListener('click', () => openAction('history'));
$('logConfirmAction').addEventListener('click', confirmAction);
$('logCancelAction').addEventListener('click', () => { if (!busy) $('logActionDialog').close(); });
$('logActionDialog').addEventListener('close', () => { pendingAction = undefined; });
$('logActionDialog').addEventListener('cancel', event => { if (busy) event.preventDefault(); });
$('refreshLogs').addEventListener('click', refreshAll);
let refreshTimer;
function startRefreshing() {
  if (refreshTimer !== undefined) return;
  refreshTimer = window.setInterval(() => { if (!document.hidden && !busy) refreshAll(); }, 15000);
}
startRefreshing();
document.addEventListener('visibilitychange', () => { if (document.hidden) invalidateReads(); else refreshAll(); });
window.addEventListener('pagehide', () => { invalidateReads(); window.clearInterval(refreshTimer); refreshTimer = undefined; });
window.addEventListener('pageshow', event => { if (event.persisted) { startRefreshing(); refreshAll(); } });
refreshAll();
