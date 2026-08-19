const $ = id => document.getElementById(id);
const esc = value => { const node = document.createElement('span'); node.textContent = value ?? ''; return node.innerHTML; };
const initializeTheme = () => { const key = 'ry-aletheia-theme'; const apply = () => { const light = localStorage.getItem(key) === 'light'; document.body.classList.toggle('theme-light', light); document.documentElement.style.colorScheme = light ? 'light' : 'dark'; const mark = document.querySelector('.brand .mark'); if (mark) { mark.tabIndex = 0; mark.setAttribute('role', 'button'); mark.setAttribute('aria-label', light ? '切换到深色主题' : '切换到白天主题'); mark.title = light ? '切换到深色主题' : '切换到白天主题'; } }; const toggle = () => { localStorage.setItem(key, document.body.classList.contains('theme-light') ? 'dark' : 'light'); apply(); }; const mark = document.querySelector('.brand .mark'); mark?.addEventListener('click', toggle); mark?.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); } }); apply(); };
initializeTheme();
let scope = 'all';
const labels = { INFO: '信息', WARNING: '警告', ERROR: '错误', CRITICAL: '严重错误' };
function row(item) {
  const exception = item.exception ? `<details class="log-exception"><summary>查看完整异常堆栈</summary><pre>${esc(item.exception)}</pre></details>` : '';
  return `<div class="log-row level-${esc(item.level).toLowerCase()}"><time>${esc(item.time)}</time><span class="log-level">${esc(labels[item.level] || item.level)}</span><span class="log-source">${esc(item.source)}</span><div><p>${esc(item.message)}</p>${exception}</div></div>`;
}
async function loadLogs() { try { const response = await fetch(`/api/tool-logs?scope=${scope}`, { cache: 'no-store' }); const payload = await response.json(); if (!response.ok) throw new Error(payload.error || '日志读取失败'); const entries = payload.entries || []; $('logCount').textContent = `${entries.length} 条`; $('logDetail').textContent = scope === 'errors' ? '独立错误日志：最近 200 条。' : '运行日志：最近 200 条。'; $('logList').innerHTML = entries.length ? entries.map(row).join('') : '<div class="page-empty">当前范围内尚无日志记录。</div>'; $('downloadLogs').href = `/api/tool-logs/download?scope=${scope}`; $('downloadLogs').textContent = scope === 'errors' ? '下载错误日志' : '下载运行日志'; } catch (error) { $('logList').innerHTML = `<div class="page-empty">读取失败：${esc(error.message)}</div>`; } }
document.querySelectorAll('.log-tab').forEach(button => button.addEventListener('click', () => { scope = button.dataset.scope; document.querySelectorAll('.log-tab').forEach(item => item.classList.toggle('active', item === button)); loadLogs(); }));
$('refreshLogs').addEventListener('click', loadLogs);
loadLogs();
