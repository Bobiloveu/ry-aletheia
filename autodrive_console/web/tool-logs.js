const $ = id => document.getElementById(id);
const esc = value => { const node = document.createElement('span'); node.textContent = value ?? ''; return node.innerHTML; };
const labels = { INFO: '信息', WARNING: '警告', ERROR: '错误', CRITICAL: '严重错误' };
let scope = 'all';

const initializeTheme = () => {
  const key = 'ry-aletheia-theme';
  const apply = () => {
    const light = localStorage.getItem(key) === 'light';
    document.body.classList.toggle('theme-light', light);
    document.documentElement.style.colorScheme = light ? 'light' : 'dark';
    const mark = document.querySelector('.brand .mark');
    if (mark) { mark.tabIndex = 0; mark.setAttribute('role', 'button'); mark.setAttribute('aria-label', light ? '切换到深色主题' : '切换到白天主题'); mark.title = light ? '切换到深色主题' : '切换到白天主题'; }
  };
  const toggle = () => { localStorage.setItem(key, document.body.classList.contains('theme-light') ? 'dark' : 'light'); apply(); };
  const mark = document.querySelector('.brand .mark');
  mark?.addEventListener('click', toggle); mark?.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); } });
  apply();
};

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MiB`;
}
function formatTime(value) {
  const time = new Date((Number(value) || 0) * 1000);
  return Number.isNaN(time.getTime()) ? '未知时间' : time.toLocaleString('zh-CN', { hour12: false });
}
function row(item) {
  const exception = item.exception ? `<details class="log-exception"><summary>查看完整异常堆栈</summary><pre>${esc(item.exception)}</pre></details>` : '';
  return `<div class="log-row level-${esc(item.level).toLowerCase()}"><time>${esc(item.time)}</time><span class="log-level">${esc(labels[item.level] || item.level)}</span><span class="log-source">${esc(item.source)}</span><div><p>${esc(item.message)}</p>${exception}</div></div>`;
}
function fileRow(file) {
  const href = `/api/tool-logs/files/${encodeURIComponent(file.name)}/download`;
  return `<article class="diagnostic-file-row"><div class="diagnostic-file-main"><h3>${esc(file.label)}</h3><p>${esc(file.detail)}</p><code>${esc(file.name)}</code></div><div class="diagnostic-file-meta"><span>${esc(formatBytes(file.size_bytes))}</span><time>${esc(formatTime(file.modified_at))}</time></div><a class="compact-action diagnostic-file-download" href="${href}">下载</a></article>`;
}

async function loadLogs() {
  try {
    const response = await fetch(`/api/tool-logs?scope=${scope}`, { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '日志读取失败');
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
    const response = await fetch('/api/tool-logs/files', { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '文件清单读取失败');
    const files = Array.isArray(payload.files) ? payload.files : [];
    $('logFileCount').textContent = `${files.length} 个文件`;
    $('diagnosticFileList').innerHTML = files.length ? files.map(fileRow).join('') : '<div class="page-empty">尚未产生可下载的诊断日志。</div>';
  } catch (error) {
    $('logFileCount').textContent = '读取失败';
    $('diagnosticFileList').innerHTML = `<div class="page-empty">文件清单读取失败：${esc(error.message)}</div>`;
  }
}
function refreshAll() { loadLogs(); loadDiagnosticFiles(); }

initializeTheme();
document.querySelectorAll('.log-tab').forEach(button => button.addEventListener('click', () => {
  scope = button.dataset.scope;
  document.querySelectorAll('.log-tab').forEach(item => item.classList.toggle('active', item === button));
  loadLogs();
}));
$('refreshLogs').addEventListener('click', refreshAll);
refreshAll();
