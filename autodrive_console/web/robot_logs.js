const $ = (id) => document.getElementById(id);
const esc = (value) => { const node = document.createElement('span'); node.textContent = value ?? ''; return node.innerHTML; };
const state = { sources: [], selectedSourceId: null, files: [], selectedFileIds: new Set(), fileRequest: null, downloading: false };
let searchTimer = null;

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
function setMessage(id, message = '', tone = '') {
  const node = $(id);
  node.textContent = message;
  node.className = node.className.replace(/\b(error|success)\b/g, '').trim();
  if (tone) node.classList.add(tone);
}
function setDownloadProgress(download, index, total) {
  const sent = Number(download.sent_bytes) || 0;
  const size = Number(download.total_bytes) || 0;
  const percent = size ? Math.min(100, Math.round((sent / size) * 100)) : 0;
  $('downloadProgress').hidden = false;
  $('downloadProgressTitle').textContent = `正在下载 ${index} / ${total}：${download.name}`;
  $('downloadProgressValue').textContent = `${percent}%`;
  $('downloadProgressBar').value = percent;
  $('downloadProgressDetail').textContent = download.state === 'prepared'
    ? '等待浏览器开始接收文件。'
    : `${formatBytes(sent)} / ${formatBytes(size)} · 小车正在传输到浏览器`;
}
function hideDownloadProgress() {
  $('downloadProgress').hidden = true;
  $('downloadProgressBar').value = 0;
}
function sleep(milliseconds) { return new Promise((resolve) => window.setTimeout(resolve, milliseconds)); }
async function requestJson(url, options) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || '请求失败');
  return payload;
}
function sourceRows() {
  return state.sources.map((source) => `<div class="source-directory-row" data-source-id="${esc(source.id)}"><label>名称<input data-field="name" value="${esc(source.name)}" maxlength="64" /></label><label>本机目录<input data-field="path" value="${esc(source.path)}" maxlength="512" spellcheck="false" /></label><button class="outline-button danger-outline remove-source" type="button">删除</button></div>`).join('');
}
function renderDirectoryManager() {
  $('sourceDirectoryList').innerHTML = state.sources.length ? sourceRows() : '<div class="page-empty">尚未配置日志目录。请添加一个可读取的本机目录。</div>';
}
function renderSourceSelector() {
  const available = state.sources.filter((source) => source.status === 'available');
  if (!available.some((source) => source.id === state.selectedSourceId)) state.selectedSourceId = available[0]?.id || null;
  $('sourceSelector').innerHTML = state.sources.length ? state.sources.map((source) => {
    const selected = source.id === state.selectedSourceId;
    const unavailable = source.status !== 'available';
    return `<button class="source-tab" type="button" role="tab" aria-selected="${selected}" data-source-id="${esc(source.id)}" ${unavailable ? 'disabled' : ''}><span class="source-status-dot ${esc(source.status)}"></span><span class="source-tab-main"><b>${esc(source.name)}</b><small>${esc(source.message)} · ${source.file_count} 个文件</small></span></button>`;
  }).join('') : '<div class="page-empty">请先保存至少一个日志目录。</div>';
  const selected = state.sources.find((source) => source.id === state.selectedSourceId);
  $('selectedSourceDetail').textContent = selected ? `${selected.name}：${selected.file_count} 个可读取文件。文件名筛选不会读取日志正文。` : '没有可读取的日志目录。请检查目录是否存在以及当前账户是否有读取权限。';
}
function updateSelectionSummary() {
  const selected = state.files.filter((file) => state.selectedFileIds.has(file.id));
  const bytes = selected.reduce((total, file) => total + Number(file.size_bytes || 0), 0);
  $('selectedCount').textContent = selected.length ? `已选 ${selected.length} 个 · ${formatBytes(bytes)}` : '未选择文件';
  $('downloadSelected').disabled = !selected.length || state.downloading;
  $('selectAllFiles').checked = Boolean(state.files.length) && state.files.every((file) => state.selectedFileIds.has(file.id));
  $('selectAllFiles').indeterminate = Boolean(selected.length) && selected.length < state.files.length;
}
function renderFiles() {
  const list = $('fileList');
  if (!state.selectedSourceId) {
    list.innerHTML = '<tr><td colspan="4" class="table-empty">请选择一个可读取的日志目录。</td></tr>';
  } else if (!state.files.length) {
    list.innerHTML = '<tr><td colspan="4" class="table-empty">没有匹配的日志文件。</td></tr>';
  } else {
    list.innerHTML = state.files.map((file) => `<tr><td><input class="file-checkbox" type="checkbox" data-file-id="${esc(file.id)}" aria-label="选择 ${esc(file.name)}" ${state.selectedFileIds.has(file.id) ? 'checked' : ''} /></td><td class="file-name" title="${esc(file.name)}">${esc(file.name)}</td><td>${esc(formatBytes(file.size_bytes))}</td><td>${esc(formatTime(file.modified_at))}</td></tr>`).join('');
  }
  updateSelectionSummary();
}
async function loadFiles() {
  const sourceId = state.selectedSourceId;
  if (!sourceId) { state.files = []; renderFiles(); return; }
  state.fileRequest?.abort();
  state.fileRequest = new AbortController();
  $('fileList').innerHTML = '<tr><td colspan="4" class="table-empty">正在读取文件清单…</td></tr>';
  try {
    const query = encodeURIComponent($('fileKeyword').value.trim());
    const payload = await requestJson(`/api/robot-logs/sources/${encodeURIComponent(sourceId)}/files?query=${query}`, { signal: state.fileRequest.signal });
    if (state.selectedSourceId !== sourceId) return;
    state.files = Array.isArray(payload.files) ? payload.files : [];
    const present = new Set(state.files.map((file) => file.id));
    state.selectedFileIds = new Set([...state.selectedFileIds].filter((id) => present.has(id)));
    renderFiles();
  } catch (error) {
    if (error.name === 'AbortError') return;
    state.files = [];
    state.selectedFileIds.clear();
    $('fileList').innerHTML = `<tr><td colspan="4" class="table-empty">读取文件失败：${esc(error.message)}</td></tr>`;
    updateSelectionSummary();
  }
}
async function loadSources() {
  setMessage('configMessage');
  try {
    const payload = await requestJson('/api/robot-logs/sources');
    state.sources = Array.isArray(payload.sources) ? payload.sources : [];
    renderDirectoryManager();
    renderSourceSelector();
    await loadFiles();
  } catch (error) {
    state.sources = [];
    state.files = [];
    renderDirectoryManager();
    renderSourceSelector();
    renderFiles();
    setMessage('configMessage', `读取目录失败：${error.message}`, 'error');
  }
}
function collectSources() {
  return [...document.querySelectorAll('.source-directory-row')].map((row) => ({
    ...(row.dataset.sourceId ? { id: row.dataset.sourceId } : {}),
    name: row.querySelector('[data-field="name"]').value.trim(),
    path: row.querySelector('[data-field="path"]').value.trim(),
  }));
}
async function saveSources() {
  const sources = collectSources();
  if (!sources.length) { setMessage('configMessage', '请至少保留一个日志目录。', 'error'); return; }
  $('saveSources').disabled = true;
  setMessage('configMessage', '正在保存目录…');
  try {
    const payload = await requestJson('/api/robot-logs/sources', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sources }) });
    state.sources = Array.isArray(payload.sources) ? payload.sources : [];
    renderDirectoryManager();
    renderSourceSelector();
    await loadFiles();
    setMessage('configMessage', '日志目录已保存。', 'success');
  } catch (error) {
    setMessage('configMessage', `无法保存：${error.message}`, 'error');
  } finally {
    $('saveSources').disabled = false;
  }
}
async function downloadSelected() {
  const selected = state.files.filter((file) => state.selectedFileIds.has(file.id));
  if (!state.selectedSourceId || !selected.length || state.downloading) return;
  const convertRosTime = $('convertRosTime').checked;
  const downloadKind = convertRosTime ? '北京时间转换版' : '原始日志';
  state.downloading = true;
  updateSelectionSummary();
  hideDownloadProgress();
  setMessage('downloadMessage', `正在向浏览器提交 ${selected.length} 个${downloadKind}下载。保存位置由浏览器决定；如需每次选择，请先展开下方说明并开启浏览器下载询问。`);
  try {
    for (const [index, file] of selected.entries()) {
      const payload = await requestJson('/api/robot-logs/downloads', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_id: state.selectedSourceId, file_id: file.id, ros_time: convertRosTime ? 'beijing' : 'raw' }),
      });
      const download = payload.download;
      if (!download?.id) throw new Error('无法创建下载进度');
      setDownloadProgress(download, index + 1, selected.length);
      const anchor = document.createElement('a');
      anchor.href = `/api/robot-logs/downloads/${encodeURIComponent(download.id)}/file`;
      anchor.download = file.name;
      anchor.hidden = true;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      while (true) {
        await sleep(250);
        const current = (await requestJson(`/api/robot-logs/downloads/${encodeURIComponent(download.id)}`)).download;
        setDownloadProgress(current, index + 1, selected.length);
        if (current.state === 'completed') break;
        if (current.state === 'failed') throw new Error(current.error || '下载失败');
      }
    }
    setMessage('downloadMessage', `${selected.length} 个${downloadKind}已传输完成；浏览器会按当前下载设置保存文件。`, 'success');
  } catch (error) {
    setMessage('downloadMessage', `下载未完成：${error.message}。已完成的文件不会重传。`, 'error');
  } finally {
    state.downloading = false;
    updateSelectionSummary();
  }
}

$('sourceDirectoryList').addEventListener('click', (event) => {
  const button = event.target.closest('.remove-source');
  if (!button) return;
  const row = button.closest('.source-directory-row');
  const name = row.querySelector('[data-field="name"]').value.trim() || '此目录';
  if (window.confirm(`删除“${name}”吗？删除后需要点击“保存目录”才会生效。`)) row.remove();
});
$('addSource').addEventListener('click', () => {
  $('sourceDirectoryList').insertAdjacentHTML('beforeend', '<div class="source-directory-row"><label>名称<input data-field="name" maxlength="64" placeholder="例如 drivers" /></label><label>本机目录<input data-field="path" maxlength="512" placeholder="/opt/ry/Log/..." spellcheck="false" /></label><button class="outline-button danger-outline remove-source" type="button">删除</button></div>');
  $('sourceDirectoryList').querySelector('.source-directory-row:last-child [data-field="name"]').focus();
});
$('saveSources').addEventListener('click', saveSources);
$('refreshSources').addEventListener('click', loadSources);
$('sourceSelector').addEventListener('click', (event) => {
  const button = event.target.closest('[data-source-id]');
  if (!button || button.disabled || button.dataset.sourceId === state.selectedSourceId) return;
  state.selectedSourceId = button.dataset.sourceId;
  state.files = [];
  state.selectedFileIds.clear();
  renderSourceSelector();
  loadFiles();
});
$('fileKeyword').addEventListener('input', () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(loadFiles, 180);
});
$('fileList').addEventListener('change', (event) => {
  const checkbox = event.target.closest('.file-checkbox');
  if (!checkbox) return;
  if (checkbox.checked) state.selectedFileIds.add(checkbox.dataset.fileId); else state.selectedFileIds.delete(checkbox.dataset.fileId);
  updateSelectionSummary();
});
$('selectAllFiles').addEventListener('change', (event) => {
  for (const file of state.files) {
    if (event.target.checked) state.selectedFileIds.add(file.id); else state.selectedFileIds.delete(file.id);
  }
  renderFiles();
});
$('downloadSelected').addEventListener('click', downloadSelected);
loadSources();
