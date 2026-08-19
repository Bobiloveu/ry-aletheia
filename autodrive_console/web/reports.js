const $ = id => document.getElementById(id);
const initializeTheme = () => { const key = 'ry-aletheia-theme'; const apply = () => { const light = localStorage.getItem(key) === 'light'; document.body.classList.toggle('theme-light', light); document.documentElement.style.colorScheme = light ? 'light' : 'dark'; const mark = document.querySelector('.brand .mark'); if (mark) { mark.tabIndex = 0; mark.setAttribute('role', 'button'); mark.setAttribute('aria-label', light ? '切换到深色主题' : '切换到白天主题'); mark.title = light ? '切换到深色主题' : '切换到白天主题'; } }; const toggle = () => { localStorage.setItem(key, document.body.classList.contains('theme-light') ? 'dark' : 'light'); apply(); }; const mark = document.querySelector('.brand .mark'); mark?.addEventListener('click', toggle); mark?.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); } }); apply(); };
initializeTheme();
const esc = value => { const node = document.createElement('span'); node.textContent = value ?? ''; return node.innerHTML; };
const formatBytes = bytes => bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
const status = value => ({queued:'排队中',preparing:'预检中',running:'执行中',awaiting_recovery:'等待人工恢复',recovering:'恢复预检中',cancelling:'正在终止',cancelled:'已取消',completed:'已完成',blocked:'已拦截',failed:'运行中断'})[value] || '暂无运行';

function reportRow(item) {
  const encoded = encodeURIComponent(item.filename);
  return `<div class="report-row"><div><b>${esc(item.filename)}</b><small>生成时间：${new Date(item.modified_at).toLocaleString('zh-CN',{hour12:false})}</small></div><div><span class="file-kind">TRAJECTORY REPORT</span><small>${formatBytes(item.size)} · 单文件 HTML</small></div><div class="report-actions"><a class="compact-action" target="_blank" href="/api/report-files/${encoded}">查看</a><a class="compact-action" href="/api/reports/${encoded}/download">下载 HTML</a>${item.csv_filename ? `<a class="compact-action" href="/api/report-files/${encodeURIComponent(item.csv_filename)}">CSV</a>` : ''}<button class="compact-action danger-action report-delete" data-report="${esc(item.filename)}" type="button">删除</button></div></div>`;
}

async function loadReports() {
  try {
    const [reportResponse, runResponse] = await Promise.all([fetch('/api/reports'), fetch('/api/runs/latest')]);
    const reports = await reportResponse.json(), latest = await runResponse.json();
    if (!reportResponse.ok) throw new Error(reports.error || '报告索引读取失败');
    const run = latest.run;
    $('latestStatus').textContent = status(run?.status);
    $('latestDetail').textContent = run ? `${run.case.filename} · ${run.summary.completed}/${run.requestedCount} 次完成 · ${run.summary.passed} 通过 / ${run.summary.failed} 失败` : '尚未创建自动化测试计划。';
    $('reportCount').textContent = `${reports.reports.length} 份报告`;
    $('reportList').innerHTML = reports.reports.length ? reports.reports.map(reportRow).join('') : '<div class="page-empty">reports/ 中尚未生成带轨迹证据的验证报告。</div>';
  } catch (error) {
    $('reportList').innerHTML = `<div class="page-empty">读取失败：${esc(error.message)}</div>`;
  }
}

$('refreshReports').addEventListener('click', loadReports);
$('reportList').addEventListener('click', async event => {
  const button = event.target.closest('.report-delete');
  if (!button) return;
  const filename = button.dataset.report;
  if (!window.confirm(`确认删除报告“${filename}”？\n\n将同时删除对应 CSV 和全部轨迹证据文件，此操作不可恢复。`)) return;
  button.disabled = true;
  try {
    const response = await fetch(`/api/reports/${encodeURIComponent(filename)}`, {method: 'DELETE'});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '删除失败');
    await loadReports();
  } catch (error) {
    button.disabled = false;
    window.alert(`删除报告失败：${error.message}`);
  }
});

loadReports();
