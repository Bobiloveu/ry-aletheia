import { requestJson } from './platform/http.js';

const $ = (id) => document.getElementById(id);
let loadInFlight = false;
let pollTimer = null;
const text = (value) => String(value ?? '—');
const size = (bytes) => {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MiB`;
  return `${(value / 1024 ** 3).toFixed(2)} GiB`;
};
function statusLabel(status) { return status === 'passed' ? '审查通过' : status === 'warning' ? '审查警告' : '审查失败 / 未完成'; }
function formatStartedAt(value) {
  const match = typeof value === 'string' && value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:[+-]\d{2}:\d{2}|Z)?$/);
  return match ? `${match[1]} ${match[2]}` : '开始时间未知';
}
function createCard(archive) {
  const card = document.createElement('article'); card.className = 'archive-card';
  const info = document.createElement('div');
  const title = document.createElement('h3'); title.textContent = text(archive.display_name); info.append(title);
  const detail = document.createElement('p');
  detail.textContent = `${archive.source === 'manual' ? '手动录制' : archive.attempt_index == null ? '录制未完成' : '测试录制'} · ${formatStartedAt(archive.started_at)}`;
  info.append(detail);
  const meta = document.createElement('div'); meta.className = 'archive-meta';
  [size(archive.total_size_bytes), text(archive.compression)].forEach(value => { const item = document.createElement('span'); item.textContent = value; meta.append(item); });
  const audit = document.createElement('span'); audit.className = `audit-badge ${text(archive.audit_status)}`; audit.textContent = statusLabel(archive.audit_status); meta.append(audit); info.append(meta);
  const actions = document.createElement('div'); actions.className = 'archive-actions';
  const detailButton = document.createElement('button'); detailButton.type = 'button'; detailButton.textContent = '审查详情'; detailButton.onclick = () => showDetail(archive.archive_id); actions.append(detailButton);
  const download = document.createElement('button'); download.type = 'button'; download.textContent = '下载'; download.onclick = () => { window.location.href = `/api/bag-recordings/${encodeURIComponent(archive.archive_id)}/download`; }; actions.append(download);
  const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'delete'; remove.textContent = '删除'; remove.onclick = () => removeArchive(archive); actions.append(remove);
  card.append(info, actions); return card;
}
function formatRemaining(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(value / 60); const remainder = value % 60;
  return minutes ? `${minutes} 分 ${String(remainder).padStart(2, '0')} 秒` : `${remainder} 秒`;
}
function renderManualRecording(manual) {
  const active = manual?.state === 'recording';
  $('configureManualBagRecording').hidden = active || manual?.state === 'finalizing';
  $('stopManualRecording').hidden = !active;
  if (active) {
    const title = manual.label ? `“${manual.label}”` : '未命名场景';
    $('manualRecordingSummary').textContent = `手动场景录制正在进行：${title}，已选 ${text(manual.topic_count)} 个 Topic，剩余约 ${formatRemaining(manual.remaining_seconds)}。`;
  } else if (manual?.state === 'finalizing') {
    $('manualRecordingSummary').textContent = '正在停止并归档手动场景录制，请稍候。';
  } else {
    $('manualRecordingSummary').textContent = '未在录制。可先选择 Topic 和时长，再用手动遥控复现场景。';
  }
}
async function load() {
  if (loadInFlight) return;
  loadInFlight = true;
  $('pageState').textContent = '读取中';
  try {
    const [archiveResult, manualResult] = await Promise.allSettled([requestJson('/api/bag-recordings'), requestJson('/api/bag-recordings/manual')]);
    if (archiveResult.status === 'fulfilled') {
      const archives = Array.isArray(archiveResult.value.archives) ? archiveResult.value.archives : [];
      $('archiveList').replaceChildren(...(archives.length ? archives.map(createCard) : [Object.assign(document.createElement('p'), { textContent: '尚无诊断录包归档。' })]));
      $('archiveCount').textContent = archives.length; $('archiveBytes').textContent = size(archives.reduce((sum, item) => sum + (Number(item.total_size_bytes) || 0), 0)); $('archiveAttention').textContent = archives.filter(item => item.audit_status !== 'passed').length;
    } else {
      $('archiveList').textContent = `无法读取归档：${archiveResult.reason.message}`;
      ['archiveCount', 'archiveBytes', 'archiveAttention'].forEach(id => { $(id).textContent = '—'; });
    }
    if (manualResult.status === 'fulfilled') renderManualRecording(manualResult.value.manual);
    else $('manualRecordingSummary').textContent = '暂时无法读取手动录制状态，请刷新重试。';
    const failures = [archiveResult, manualResult].filter(result => result.status === 'rejected').length;
    $('pageState').textContent = failures === 0 ? '已更新' : failures === 1 ? '部分更新' : '读取失败';
  } catch (error) { $('archiveList').textContent = `无法读取归档：${error.message}`; $('manualRecordingSummary').textContent = '暂时无法读取手动录制状态。'; $('pageState').textContent = '读取失败'; }
  finally { loadInFlight = false; }
}
async function showDetail(id) { try { const data = await requestJson(`/api/bag-recordings/${encodeURIComponent(id)}`); $('detailTitle').textContent = data.archive?.display_name || '录包审查'; $('detailBody').textContent = JSON.stringify(data.manifest?.audit || {}, null, 2); $('detailDialog').showModal(); } catch (error) { window.alert(`无法读取审查详情：${error.message}`); } }
async function removeArchive(archive) { if (!window.confirm(`删除“${archive.display_name}”？该操作不可恢复。`)) return; try { await requestJson(`/api/bag-recordings/${encodeURIComponent(archive.archive_id)}`, { method: 'DELETE' }); load(); } catch (error) { window.alert(`删除失败：${error.message}`); } }
$('refresh').addEventListener('click', load);
$('detailClose').addEventListener('click', () => $('detailDialog').close());
$('stopManualRecording').addEventListener('click', async () => {
  $('stopManualRecording').disabled = true;
  try {
    await requestJson('/api/bag-recordings/manual/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  } catch (error) {
    window.alert(`无法停止录制：${error.message}`);
  } finally {
    await load(); $('stopManualRecording').disabled = false;
  }
});
load();
function startPolling() {
  if (pollTimer !== null) return;
  pollTimer = window.setInterval(() => { if (document.visibilityState === 'visible') load(); }, 5000);
}
function stopPolling() {
  if (pollTimer === null) return;
  window.clearInterval(pollTimer);
  pollTimer = null;
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') { startPolling(); load(); }
  else stopPolling();
});
window.addEventListener('pagehide', stopPolling);
startPolling();
