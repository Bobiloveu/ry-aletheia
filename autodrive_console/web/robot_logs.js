import { requestJson } from "./platform/http.js";
import { formatFileSize, formatUnixSeconds } from "./platform/format.js";
import { splitLogLine } from "./platform/log-format.js";
import { applyLiveLogWindowAction } from "./platform/live-log-window.js";
import { appendLiveLogLines, splitLiveLogText } from "./platform/live-log-buffer.js";

const $ = (id) => document.getElementById(id);
const esc = (value) => { const node = document.createElement('span'); node.textContent = value ?? ''; return node.innerHTML; };
// 固定节点池避免高频 stdout 持续创建/销毁 DOM；读流会等待每帧渲染完成，以
// 浏览器/网络背压控制积压，而不是截断或跳过日志内容。
const MAX_LIVE_VISIBLE_LINES = 240;
const MAX_LIVE_RENDER_BATCH_LINES = 48;
const LIVE_LOG_SESSION_KEY = 'ry-aletheia-live-log-windows';
const state = { sources: [], selectedSourceId: null, files: [], selectedFileIds: new Set(), fileRequest: null, downloading: false, liveLogs: new Map(), focusedLiveLogId: null, liveTailController: null, liveTailGeneration: 0, liveTailPending: '', restoredLiveLogs: false };
let searchTimer = null;

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
    : `${formatFileSize(sent)} / ${formatFileSize(size)} · 小车正在传输到浏览器`;
}
function hideDownloadProgress() {
  $('downloadProgress').hidden = true;
  $('downloadProgressBar').value = 0;
}
function sleep(milliseconds) { return new Promise((resolve) => window.setTimeout(resolve, milliseconds)); }
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
  $('selectedCount').textContent = selected.length ? `已选 ${selected.length} 个 · ${formatFileSize(bytes)}` : '未选择文件';
  $('downloadSelected').disabled = !selected.length || state.downloading;
  $('selectAllFiles').checked = Boolean(state.files.length) && state.files.every((file) => state.selectedFileIds.has(file.id));
  $('selectAllFiles').indeterminate = Boolean(selected.length) && selected.length < state.files.length;
}
function updateLiveSummary() {
  const count = state.liveLogs.size;
  $('liveLogCount').textContent = count ? `实时查看 ${count} 个` : '未打开实时日志';
}
function renderLiveEmpty() {
  const workspace = $('liveLogWorkspace');
  if (state.liveLogs.size || workspace.querySelector('.live-log-empty')) return;
  const empty = document.createElement('div');
  empty.className = 'live-log-empty';
  empty.textContent = '在上方日志列表中选择“实时查看”，即可打开对应的 Supervisor stdout。';
  workspace.append(empty);
}
function syncLiveLogWindows(action) {
  const records = [...state.liveLogs.values()].map((live) => ({ id: live.file.id, minimized: Boolean(live.minimized) }));
  const next = applyLiveLogWindowAction(records, state.focusedLiveLogId, action);
  state.focusedLiveLogId = next.focusedId;
  const workspace = $('liveLogWorkspace');
  workspace.classList.toggle('has-focused-log', Boolean(next.focusedId));
  for (const record of next.logs) {
    const live = state.liveLogs.get(record.id);
    if (!live) continue;
    live.minimized = record.minimized;
    const focused = record.id === next.focusedId;
    live.card.classList.toggle('is-minimized', record.minimized);
    live.card.classList.toggle('is-focused', focused);
    live.minimizeButton.setAttribute('aria-label', record.minimized ? '恢复日志窗口' : '最小化日志窗口');
    live.minimizeButton.title = record.minimized ? '恢复' : '最小化';
    live.maximizeButton.setAttribute('aria-label', focused ? '恢复多窗口布局' : '最大化日志窗口');
    live.maximizeButton.title = focused ? '恢复窗口' : '最大化';
    live.maximizeButton.setAttribute('aria-pressed', String(focused));
  }
}
function setLiveStatus(live, stateName = 'connecting') {
  if (live.disposed) return;
  live.card.dataset.state = stateName;
}
function isLiveLogAtBottom(live) {
  return live.output.scrollTop + live.output.clientHeight >= live.output.scrollHeight - 12;
}
function scrollLiveOutput(live) {
  live.output.scrollTop = live.output.scrollHeight;
}
function createLiveLineNode() {
  const node = document.createElement('div');
  node.className = 'live-log-line';
  node.hidden = true;
  const sequence = document.createElement('span');
  sequence.className = 'live-log-sequence';
  const content = document.createElement('div');
  content.className = 'live-log-content';
  const meta = document.createElement('div');
  meta.className = 'live-log-meta';
  const timestamp = document.createElement('time');
  timestamp.className = 'live-log-timestamp';
  const level = document.createElement('span');
  level.className = 'live-log-level';
  const message = document.createElement('span');
  message.className = 'live-log-text';
  meta.append(timestamp, level);
  content.append(meta, message);
  node.append(sequence, content);
  return { node, sequence, timestamp, level, message };
}
function initializeLiveLinePool(live) {
  const fragment = document.createDocumentFragment();
  for (let index = 0; index < MAX_LIVE_VISIBLE_LINES; index += 1) {
    const line = createLiveLineNode();
    live.linePool.push(line);
    fragment.append(line.node);
  }
  live.output.append(fragment);
}
function renderLiveLine(live, rawLine) {
  const fields = splitLogLine(rawLine);
  if (!fields.message && !fields.timestamp && !fields.level && rawLine !== '') return false;
  const line = live.linePool[live.nextLineIndex];
  live.nextLineIndex = (live.nextLineIndex + 1) % MAX_LIVE_VISIBLE_LINES;
  line.node.hidden = false;
  line.node.className = `live-log-line live-log-line--${fields.tone}`;
  line.sequence.textContent = String(++live.sequence);
  line.timestamp.hidden = !fields.timestamp;
  line.timestamp.textContent = fields.timestamp || '';
  line.level.hidden = !fields.level;
  line.level.textContent = fields.level || '';
  line.message.textContent = fields.message;
  // append 已有节点仅移动其位置；固定池不会随着 stdout 增长分配新 DOM 节点。
  live.output.append(line.node);
  return true;
}
function scheduleLiveLineFlush(live) {
  if (live.disposed) return Promise.resolve();
  if (!live.renderPromise)
    live.renderPromise = new Promise((resolve) => { live.resolveRender = resolve; });
  if (live.renderFrame) return live.renderPromise;
  live.renderFrame = requestAnimationFrame(() => flushLiveLines(live));
  return live.renderPromise;
}
function queueLiveLines(live, lines) {
  if (!lines.length) return Promise.resolve();
  appendLiveLogLines(live.pendingLines, lines);
  return scheduleLiveLineFlush(live);
}
function finishLiveLineFlush(live) {
  live.renderFrame = undefined;
  const resolve = live.resolveRender;
  live.resolveRender = undefined;
  live.renderPromise = undefined;
  resolve?.();
}
function flushLiveLines(live) {
  live.renderFrame = undefined;
  if (live.disposed) { finishLiveLineFlush(live); return; }
  const lines = live.pendingLines.splice(0, MAX_LIVE_RENDER_BATCH_LINES);
  for (const line of lines) renderLiveLine(live, line);
  if (lines.length) scrollLiveOutput(live);
  if (live.pendingLines.length) scheduleLiveLineFlush(live);
  else finishLiveLineFlush(live);
}
async function appendLiveText(live, text) {
  const parsed = splitLiveLogText(live.pending, text);
  live.pending = parsed.pending;
  await queueLiveLines(live, parsed.lines);
}
function clearLiveLog(live) {
  if (live.renderFrame) cancelAnimationFrame(live.renderFrame);
  finishLiveLineFlush(live);
  live.pending = '';
  live.pendingLines.length = 0;
  live.sequence = 0;
  live.nextLineIndex = 0;
  for (const line of live.linePool) line.node.hidden = true;
  live.retention.textContent = `最多显示最近 ${MAX_LIVE_VISIBLE_LINES.toLocaleString('zh-CN')} 行`;
}
function stopLiveTail() {
  state.liveTailGeneration += 1;
  state.liveTailController?.abort();
  state.liveTailController = null;
  state.liveTailPending = '';
}
function stopLiveLog(live) {
  live.paused = true;
  setLiveStatus(live, 'paused');
  if (live.renderFrame) cancelAnimationFrame(live.renderFrame);
  finishLiveLineFlush(live);
}
function setPauseControl(live, paused) {
  const label = paused ? '继续跟随' : '暂停跟随';
  live.pauseButton.dataset.mode = paused ? 'resume' : 'pause';
  live.pauseButton.setAttribute('aria-label', label);
  live.pauseButton.title = label;
}
function persistLiveLogs() {
  try {
    const records = [...state.liveLogs.values()].map((live) => ({ sourceId: live.sourceId, file: live.file, paused: Boolean(live.paused) }));
    if (records.length) sessionStorage.setItem(LIVE_LOG_SESSION_KEY, JSON.stringify(records));
    else sessionStorage.removeItem(LIVE_LOG_SESSION_KEY);
  } catch (_) {
    // 会话存储被浏览器策略禁用时，实时查看仍可在当前页正常使用。
  }
}
function restoreLiveLogs() {
  if (state.restoredLiveLogs) return;
  state.restoredLiveLogs = true;
  let records = [];
  try { records = JSON.parse(sessionStorage.getItem(LIVE_LOG_SESSION_KEY) || '[]'); } catch (_) { sessionStorage.removeItem(LIVE_LOG_SESSION_KEY); }
  if (!Array.isArray(records)) return;
  const sources = new Set(state.sources.map((source) => source.id));
  for (const record of records) {
    if (!sources.has(record?.sourceId) || !record.file?.id || !record.file?.name || state.liveLogs.has(record.file.id)) continue;
    createLiveLog(record.sourceId, record.file, { startTail: false, paused: Boolean(record.paused) });
  }
  restartLiveTail();
}
function closeLiveLog(live) {
  live.disposed = true;
  stopLiveLog(live);
  if (live.renderFrame) cancelAnimationFrame(live.renderFrame);
  finishLiveLineFlush(live);
  live.pendingLines.length = 0;
  live.linePool.length = 0;
  state.liveLogs.delete(live.file.id);
  if (state.focusedLiveLogId === live.file.id) state.focusedLiveLogId = null;
  live.card.remove();
  $('liveLogWorkspace').classList.toggle('has-focused-log', Boolean(state.focusedLiveLogId));
  updateLiveSummary();
  renderFiles();
  renderLiveEmpty();
  persistLiveLogs();
  restartLiveTail();
}
function liveLogForStream(stream) {
  const separator = typeof stream === 'string' ? stream.indexOf(':') : -1;
  if (separator <= 0) return null;
  const sourceId = stream.slice(0, separator);
  const fileId = stream.slice(separator + 1);
  return [...state.liveLogs.values()].find((live) => live.sourceId === sourceId && live.file.id === fileId) || null;
}
async function restartLiveTail() {
  stopLiveTail();
  const logs = [...state.liveLogs.values()].filter((live) => !live.disposed && !live.paused);
  if (!logs.length) return;
  const controller = new AbortController();
  const generation = ++state.liveTailGeneration;
  state.liveTailController = controller;
  for (const live of logs) setLiveStatus(live, 'connecting');
  const query = new URLSearchParams();
  for (const live of logs) query.append('stream', `${live.sourceId}:${live.file.id}`);
  try {
    const response = await fetch(`/api/robot-logs/tail?${query}`, {
      cache: 'no-store',
      signal: controller.signal,
      headers: { Accept: 'application/x-ndjson' },
    });
    if (!response.ok) {
      const detail = (await response.text()).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
      throw new Error(detail || `实时日志请求失败（${response.status}）`);
    }
    if (!response.body) throw new Error('浏览器不支持实时日志流');
    for (const live of logs) setLiveStatus(live, 'live');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    while (state.liveTailGeneration === generation) {
      const { value, done } = await reader.read();
      if (done) break;
      if (state.liveTailGeneration !== generation) break;
      const frames = `${state.liveTailPending}${decoder.decode(value, { stream: true })}`.split('\n');
      state.liveTailPending = frames.pop() || '';
      for (const frame of frames) {
        if (!frame) continue;
        let event;
        try { event = JSON.parse(frame); } catch (_) { continue; }
        const live = liveLogForStream(event.stream);
        if (live && !live.paused && typeof event.text === 'string') await appendLiveText(live, event.text);
      }
    }
    if (!controller.signal.aborted && state.liveTailGeneration === generation) for (const live of logs) setLiveStatus(live, 'stopped');
  } catch (error) {
    if (!controller.signal.aborted && state.liveTailGeneration === generation) {
      globalThis.RYAletheiaDiagnostics?.failure?.('robot-logs.live-stream','实时日志流读取失败');
      for (const live of logs) setLiveStatus(live, 'error');
    }
  } finally {
    if (state.liveTailController === controller) state.liveTailController = null;
  }
}
function createLiveLog(sourceId, file, { startTail = true, paused = false } = {}) {
  const workspace = $('liveLogWorkspace');
  workspace.querySelector('.live-log-empty')?.remove();
  const card = document.createElement('article');
  card.className = 'live-log-card';
  card.dataset.state = 'connecting';
  card.innerHTML = '<header class="live-log-card-header"><div class="live-log-window-controls"><button type="button" class="live-log-window-control live-log-window-control--close" aria-label="关闭日志窗口" title="关闭"></button><button type="button" class="live-log-window-control live-log-window-control--minimize" aria-label="最小化日志窗口" title="最小化"></button><button type="button" class="live-log-window-control live-log-window-control--maximize" aria-label="最大化日志窗口" title="最大化" aria-pressed="false"></button></div><div class="live-log-file"><strong></strong><span></span></div><div class="live-log-header-tools"><button type="button" class="live-log-header-action live-log-pause" data-mode="pause" aria-label="暂停跟随" title="暂停跟随"><svg class="live-log-pause-icon" viewBox="0 0 16 16" aria-hidden="true"><path class="pause-shape" d="M4.5 3.5v9M10.5 3.5v9" /><path class="resume-shape" d="m5 3.5 7 4.5-7 4.5z" /></svg></button><button type="button" class="live-log-header-action live-log-clear" aria-label="清空当前日志" title="清空当前日志"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4h10M6 4V2.5h4V4M5 6v6.5h6V6M7 7.5v3.5M9 7.5v3.5" /></svg></button></div></header><div class="live-log-output" tabindex="0" aria-label="实时日志内容"></div><footer class="live-log-footer"><span class="live-log-retention"></span><span class="live-log-follow">自动跟随</span></footer>';
  const live = {
    sourceId, file, card, output: card.querySelector('.live-log-output'),
    pauseButton: card.querySelector('.live-log-pause'), retention: card.querySelector('.live-log-retention'),
    minimizeButton: card.querySelector('.live-log-window-control--minimize'), maximizeButton: card.querySelector('.live-log-window-control--maximize'),
    sequence: 0, pending: '', pendingLines: [], linePool: [], nextLineIndex: 0, renderFrame: undefined, renderPromise: undefined, resolveRender: undefined,
    disposed: false, minimized: false, paused,
  };
  card.querySelector('.live-log-file strong').textContent = file.name;
  card.querySelector('.live-log-file span').textContent = `${formatFileSize(file.size_bytes)} · Supervisor stdout`;
  initializeLiveLinePool(live);
  live.retention.textContent = `最多显示最近 ${MAX_LIVE_VISIBLE_LINES.toLocaleString('zh-CN')} 行`;
  setPauseControl(live, paused);
  if (paused) setLiveStatus(live, 'paused');
  live.output.addEventListener('wheel', (event) => {
    if (event.deltaY > 0 && isLiveLogAtBottom(live)) {
      event.preventDefault();
      window.scrollBy({ top: event.deltaY, left: 0, behavior: 'auto' });
    }
  }, { passive: false });
  live.pauseButton.addEventListener('click', () => {
    live.paused = !live.paused;
    setPauseControl(live, live.paused);
    setLiveStatus(live, live.paused ? 'paused' : 'connecting');
    persistLiveLogs();
    restartLiveTail();
  });
  card.querySelector('.live-log-clear').addEventListener('click', () => clearLiveLog(live));
  card.querySelector('.live-log-window-control--close').addEventListener('click', () => closeLiveLog(live));
  live.minimizeButton.addEventListener('click', () => syncLiveLogWindows({ type: live.minimized ? 'restore' : 'minimize', id: live.file.id }));
  live.maximizeButton.addEventListener('click', () => syncLiveLogWindows({ type: state.focusedLiveLogId === live.file.id ? 'restore-size' : 'maximize', id: live.file.id }));
  workspace.append(card);
  state.liveLogs.set(file.id, live);
  syncLiveLogWindows({ type: 'restore', id: file.id });
  updateLiveSummary();
  renderFiles();
  persistLiveLogs();
  if (startTail) restartLiveTail();
}
function openLiveLog(file) {
  if (!state.selectedSourceId || state.liveLogs.has(file.id)) return;
  createLiveLog(state.selectedSourceId, file);
  setMessage('liveLogMessage', `正在打开“${file.name}”的 Supervisor stdout 实时日志。`);
}
function liveLogAction(file) {
  const opened = state.liveLogs.has(file.id);
  const title = opened ? '该日志正在实时查看' : `打开 ${file.name} 的 Supervisor stdout 实时日志`;
  const primaryLabel = opened ? '查看中' : '实时查看';
  const completeLabel = opened ? '查看中' : '打开日志';
  const primaryIcon = opened
    ? '<path d="m3.25 8.25 2.8 2.65 6.7-6.1" />'
    : '<rect x="2.25" y="2.5" width="11.5" height="9.5" rx="2" /><path d="m6.5 5.75 3 1.5-3 1.5z" />';
  const completeIcon = opened
    ? primaryIcon
    : '<path d="M3.5 8h8M8.5 4.5 12 8l-3.5 3.5" />';
  return `<button class="view-live-log${opened ? ' is-open' : ''}" type="button" data-live-file-id="${esc(file.id)}" aria-label="${esc(title)}" title="${esc(title)}" ${opened ? 'disabled' : ''}><span class="view-live-log-track"><span class="view-live-log-face view-live-log-face--primary"><span class="view-live-log-copy">${primaryLabel}</span><svg viewBox="0 0 16 16" aria-hidden="true">${primaryIcon}</svg></span><span class="view-live-log-face view-live-log-face--complete"><span class="view-live-log-copy">${completeLabel}</span><svg viewBox="0 0 16 16" aria-hidden="true">${completeIcon}</svg></span></span></button>`;
}
function renderFiles() {
  const list = $('fileList');
  if (!state.selectedSourceId) {
    list.innerHTML = '<tr><td colspan="5" class="table-empty">请选择一个可读取的日志目录。</td></tr>';
  } else if (!state.files.length) {
    list.innerHTML = '<tr><td colspan="5" class="table-empty">没有匹配的日志文件。</td></tr>';
  } else {
    list.innerHTML = state.files.map((file) => `<tr><td><input class="file-checkbox" type="checkbox" data-file-id="${esc(file.id)}" aria-label="选择 ${esc(file.name)}" ${state.selectedFileIds.has(file.id) ? 'checked' : ''} /></td><td class="file-name" title="${esc(file.name)}">${esc(file.name)}</td><td>${esc(formatFileSize(file.size_bytes))}</td><td>${esc(formatUnixSeconds(file.modified_at))}</td><td class="file-live-action">${liveLogAction(file)}</td></tr>`).join('');
  }
  updateSelectionSummary();
}
async function loadFiles() {
  const sourceId = state.selectedSourceId;
  if (!sourceId) { state.files = []; renderFiles(); return; }
  state.fileRequest?.abort();
  state.fileRequest = new AbortController();
  $('fileList').innerHTML = '<tr><td colspan="5" class="table-empty">正在读取文件清单…</td></tr>';
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
    $('fileList').innerHTML = `<tr><td colspan="5" class="table-empty">读取文件失败：${esc(error.message)}</td></tr>`;
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
    restoreLiveLogs();
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
$('fileList').addEventListener('click', (event) => {
  const button = event.target.closest('.view-live-log');
  if (!button || button.disabled) return;
  const file = state.files.find((candidate) => candidate.id === button.dataset.liveFileId);
  if (file) openLiveLog(file);
});
$('selectAllFiles').addEventListener('change', (event) => {
  for (const file of state.files) {
    if (event.target.checked) state.selectedFileIds.add(file.id); else state.selectedFileIds.delete(file.id);
  }
  renderFiles();
});
$('downloadSelected').addEventListener('click', downloadSelected);
window.addEventListener('pagehide', stopLiveTail, { once: true });
loadSources();
