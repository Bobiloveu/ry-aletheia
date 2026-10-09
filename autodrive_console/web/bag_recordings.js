import { requestJson } from './platform/http.js';

const $ = (id) => document.getElementById(id);
const text = (value) => String(value ?? '—');
const size = (bytes) => {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MiB`;
  return `${(value / 1024 ** 3).toFixed(2)} GiB`;
};
function statusLabel(status) { return status === 'passed' ? '审查通过' : status === 'warning' ? '审查警告' : '审查失败 / 未完成'; }
function createCard(archive) {
  const card = document.createElement('article'); card.className = 'archive-card';
  const info = document.createElement('div');
  const title = document.createElement('h3'); title.textContent = text(archive.display_name); info.append(title);
  const detail = document.createElement('p'); detail.textContent = `${text(archive.case_name)} · T-${String(archive.attempt_index ?? '—').padStart(3, '0')} · ${text(archive.started_at)}`; info.append(detail);
  const meta = document.createElement('div'); meta.className = 'archive-meta';
  [size(archive.total_size_bytes), text(archive.compression)].forEach(value => { const item = document.createElement('span'); item.textContent = value; meta.append(item); });
  const audit = document.createElement('span'); audit.className = `audit-badge ${text(archive.audit_status)}`; audit.textContent = statusLabel(archive.audit_status); meta.append(audit); info.append(meta);
  const actions = document.createElement('div'); actions.className = 'archive-actions';
  const detailButton = document.createElement('button'); detailButton.type = 'button'; detailButton.textContent = '审查详情'; detailButton.onclick = () => showDetail(archive.archive_id); actions.append(detailButton);
  const download = document.createElement('button'); download.type = 'button'; download.textContent = '下载'; download.onclick = () => { window.location.href = `/api/bag-recordings/${encodeURIComponent(archive.archive_id)}/download`; }; actions.append(download);
  const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'delete'; remove.textContent = '删除'; remove.onclick = () => removeArchive(archive); actions.append(remove);
  card.append(info, actions); return card;
}
async function load() {
  $('pageState').textContent = '读取中';
  try {
    const data = await requestJson('/api/bag-recordings'); const archives = Array.isArray(data.archives) ? data.archives : [];
    $('archiveList').replaceChildren(...(archives.length ? archives.map(createCard) : [Object.assign(document.createElement('p'), { textContent: '尚无诊断录包归档。' })]));
    $('archiveCount').textContent = archives.length; $('archiveBytes').textContent = size(archives.reduce((sum, item) => sum + (Number(item.total_size_bytes) || 0), 0)); $('archiveAttention').textContent = archives.filter(item => item.audit_status !== 'passed').length; $('pageState').textContent = '已更新';
  } catch (error) { $('archiveList').textContent = `无法读取归档：${error.message}`; $('pageState').textContent = '读取失败'; }
}
async function showDetail(id) { try { const data = await requestJson(`/api/bag-recordings/${encodeURIComponent(id)}`); $('detailTitle').textContent = data.archive?.display_name || '录包审查'; $('detailBody').textContent = JSON.stringify(data.manifest?.audit || {}, null, 2); $('detailDialog').showModal(); } catch (error) { window.alert(`无法读取审查详情：${error.message}`); } }
async function removeArchive(archive) { if (!window.confirm(`删除“${archive.display_name}”？该操作不可恢复。`)) return; try { await requestJson(`/api/bag-recordings/${encodeURIComponent(archive.archive_id)}`, { method: 'DELETE' }); load(); } catch (error) { window.alert(`删除失败：${error.message}`); } }
$('refresh').addEventListener('click', load); $('detailClose').addEventListener('click', () => $('detailDialog').close()); load();
