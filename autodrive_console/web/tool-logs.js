import { requestJson } from "./platform/http.js";
import { formatFileSize, formatUnixSeconds } from "./platform/format.js";

const $ = id => document.getElementById(id);
const esc = value => { const node = document.createElement('span'); node.textContent = value ?? ''; return node.innerHTML; };
const labels = { INFO: '信息', WARNING: '警告', ERROR: '错误', CRITICAL: '严重错误' };
let scope = 'all';

function row(item) {
  const exception = item.exception ? `<details class="log-exception"><summary>查看完整异常堆栈</summary><pre>${esc(item.exception)}</pre></details>` : '';
  return `<div class="log-row level-${esc(item.level).toLowerCase()}"><time>${esc(item.time)}</time><span class="log-level">${esc(labels[item.level] || item.level)}</span><span class="log-source">${esc(item.source)}</span><div><p>${esc(item.message)}</p>${exception}</div></div>`;
}
function fileRow(file) {
  const href = `/api/tool-logs/files/${encodeURIComponent(file.name)}/download`;
  return `<article class="diagnostic-file-row"><div class="diagnostic-file-main"><h3>${esc(file.label)}</h3><p>${esc(file.detail)}</p><code>${esc(file.name)}</code></div><div class="diagnostic-file-meta"><span>${esc(formatFileSize(file.size_bytes))}</span><time>${esc(formatUnixSeconds(file.modified_at))}</time></div><a class="compact-action diagnostic-file-download" href="${href}">下载</a></article>`;
}

async function loadLogs() {
  try {
    const payload = await requestJson(`/api/tool-logs?scope=${scope}`, {}, { errorMessage: '日志读取失败' });
    const entries = payload.entries || [];
    $('logCount').textContent = `${entries.length} 条`;
    $('logDetail').textContent = scope === 'errors' ? '独立错误事件：最近 200 条。' : '控制台事件：最近 200 条。';
    $('logList').innerHTML = entries.length ? entries.map(row).join('') : '<div class="page-empty">当前范围内尚无日志记录。</div>';
  } catch (error) {
    $('logList').innerHTML = `<div class="page-empty">读取失败：${esc(error.message)}</div>`;
  }
}
async function loadDiagnosticFiles() {
  try {
    const payload = await requestJson('/api/tool-logs/files', {}, { errorMessage: '文件清单读取失败' });
    const files = Array.isArray(payload.files) ? payload.files : [];
    $('logFileCount').textContent = `${files.length} 个文件`;
    $('diagnosticFileList').innerHTML = files.length ? files.map(fileRow).join('') : '<div class="page-empty">尚未产生可下载的诊断日志。</div>';
  } catch (error) {
    $('logFileCount').textContent = '读取失败';
    $('diagnosticFileList').innerHTML = `<div class="page-empty">文件清单读取失败：${esc(error.message)}</div>`;
  }
}
function refreshAll() { loadLogs(); loadDiagnosticFiles(); }

document.querySelectorAll('.log-tab').forEach(button => button.addEventListener('click', () => {
  scope = button.dataset.scope;
  document.querySelectorAll('.log-tab').forEach(item => item.classList.toggle('active', item === button));
  loadLogs();
}));
$('refreshLogs').addEventListener('click', refreshAll);
refreshAll();
