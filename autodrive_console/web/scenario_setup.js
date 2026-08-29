(() => {
  const $ = (id) => document.getElementById(id);
  let documentState; let browserState; let commandCandidates = []; let lastInspection = {}; let lastActiveBackup = null; let lastTransaction = { state: 'normal', restore_available: false, message: '未检测到待恢复事务' };
  const request = async (url, options = {}) => { const response = await fetch(url, { cache: 'no-store', headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options }); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(body.error || `请求失败（HTTP ${response.status}）`); return body; };
  const escape = (value) => String(value || '').replace(/[&<>"']/g, (item) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[item]);
  const detected = (value, fallback) => value ? `自动识别：${escape(value)}` : fallback;
  function statusCopy(transaction, active) {
    if (transaction.state === 'normal') return { title: '当前使用常规配置', detail: '小车处于日常运行设置。现在可以新建、编辑或绑定测试场景。' };
    if (transaction.state === 'corrupt') return { title: '需要维护人员处理', detail: '恢复记录无法读取。请先导出工具日志并联系维护人员；暂不要退出、升级或继续测试。' };
    if (transaction.phase === 'script_restored') return { title: '常规配置正在恢复', detail: '启动文件已恢复，还需要确认相关服务已重新启动。请点击“恢复常规配置”重试，并保持页面打开。' };
    if (transaction.phase === 'prepared') return { title: '正在检查上一次操作', detail: '上一次切换未能确认完成。请点击“恢复常规配置”，工具会安全核对并回到日常设置。' };
    const name = active && active.profile_name ? `“${active.profile_name}”` : '临时场景';
    return { title: `${name}正在使用`, detail: '为避免参数混乱，编辑操作已暂时锁定。测试结束会自动恢复；如不再测试，请点击“恢复常规配置”。' };
  }

  function render(status, preserveInspection = false) {
    documentState = status.document;
    documentState.bindings = documentState.bindings || {};
    documentState.search_directories = Array.isArray(documentState.search_directories) ? documentState.search_directories : [];
    const info = preserveInspection ? lastInspection : (status.inspection || {});
    lastInspection = info;
    lastActiveBackup = preserveInspection ? lastActiveBackup : (status.active_backup || null);
    lastTransaction = preserveInspection ? lastTransaction : (status.transaction || { state: lastActiveBackup ? 'pending' : 'normal', restore_available: Boolean(lastActiveBackup), message: lastActiveBackup ? '存在待恢复事务' : '未检测到待恢复事务' });
    const transactionLocked = lastTransaction.state !== 'normal';
    const mutationDisabled = transactionLocked ? 'disabled' : '';
    commandCandidates = info.candidates || [];
    const commandSelect = (slot, kind, label) => {
      const all = commandCandidates.filter((item) => item.kind === kind);
      const keyword = slot === 'fcrp' ? /fcrp/i : /lightning/i;
      const preferred = all.filter((item) => keyword.test(`${item.package || ''} ${item.executable || ''}`));
      const selectedBinding = documentState.bindings[slot] || {};
      const selectedPrefix = selectedBinding.prefix;
      const selectedOccurrence = selectedBinding.occurrence;
      const selected = all.find((item) => item.prefix === selectedPrefix && item.occurrence === selectedOccurrence);
      const options = (preferred.length ? preferred : all).slice();
      if (selected && !options.some((item) => item.id === selected.id)) options.unshift(selected);
      return `<select data-binding="${slot}" ${mutationDisabled}><option value="">${options.length === 1 ? '自动唯一识别' : `请选择 ${label} 参数位置`}</option>${options.map((item) => `<option value="${escape(item.id)}" ${selectedPrefix === item.prefix && selectedOccurrence === item.occurrence ? 'selected' : ''}>${escape(item.package)} ${escape(item.executable || '')} → ${escape(item.current)}</option>`).join('')}</select>`;
    };
    $('inspection').innerHTML = [['小车启动脚本', `<code>${escape(documentState.startup_script)}</code>`], ['导航启动参数', commandSelect('fcrp', 'launch', '导航')], ['定位配置参数', commandSelect('lightning', 'config', '定位')]].map(([key, value]) => `<dt>${key}</dt><dd>${value}</dd>`).join('');
    const active = lastActiveBackup;
    const transactionTone = lastTransaction.state === 'corrupt' ? ' error' : (transactionLocked ? ' pending' : '');
    $('transactionState').className = `scenario-state${transactionTone}`;
    const state = statusCopy(lastTransaction, active);
    $('transactionTitle').textContent = state.title;
    $('transactionDetail').textContent = state.detail;
    $('restoreDefault').hidden = !lastTransaction.restore_available;
    $('restoreDefault').disabled = !lastTransaction.restore_available;
    $('saveProfiles').disabled = transactionLocked;
    $('addProfile').disabled = transactionLocked;
    $('profileList').innerHTML = documentState.profiles.length ? documentState.profiles.map((profile) => `<div class="scenario-profile" data-id="${escape(profile.id)}"><label>方案名称<input data-field="name" value="${escape(profile.name)}" ${mutationDisabled} ${transactionLocked ? 'readonly' : ''}></label><label>导航启动文件（FCRP）<div class="scenario-file-field"><input data-field="fcrp_launch" value="${escape(profile.fcrp_launch)}" readonly placeholder="浏览并选择 .launch.py"><button data-browse="fcrp" type="button" ${mutationDisabled}>选择文件</button></div></label><label>定位配置文件（lightning）<div class="scenario-file-field"><input data-field="lightning_config" value="${escape(profile.lightning_config)}" readonly placeholder="浏览并选择 YAML"><button data-browse="lightning" type="button" ${mutationDisabled}>选择文件</button></div></label><div class="profile-actions"><button class="preview-profile outline-button" type="button">预览</button><button class="apply-profile" type="button" ${mutationDisabled}>启用此方案</button><button class="remove-profile" type="button" ${mutationDisabled}>删除</button></div></div>`).join('') : '<div class="page-empty">还没有场景方案。点击“新建方案”后，选择导航和定位文件并保存。</div>';
  }
  function renderLocal() { render({ document: documentState, inspection: lastInspection, active_backup: lastActiveBackup }, true); }
  function collect() {
    const profiles = [...document.querySelectorAll('.scenario-profile')].map((row, index) => ({ id: row.dataset.id || `profile-${index + 1}`, name: row.querySelector('[data-field="name"]').value.trim(), fcrp_launch: row.querySelector('[data-field="fcrp_launch"]').value.trim(), lightning_config: row.querySelector('[data-field="lightning_config"]').value.trim() }));
    return { startup_script: documentState.startup_script, search_directories: documentState.search_directories || [], bindings: documentState.bindings || {}, profiles, case_bindings: documentState.case_bindings || {} };
  }
  async function preview(path) {
    try { const item = await request(`/api/scenario-setup/file?path=${encodeURIComponent(path)}`); $('filePreviewMeta').textContent = `${item.path} · ${(item.size / 1024).toFixed(1)} KiB · SHA-256 ${item.sha256.slice(0, 12)}…`; $('filePreview').textContent = item.content; } catch (error) { $('filePreviewMeta').textContent = error.message; $('filePreview').textContent = '无法读取预览'; }
  }
  async function previewApplication(profileId) {
    const result = await request('/api/scenario-setup', { method: 'POST', body: JSON.stringify({ action: 'preview', profile_id: profileId, document: collect() }) });
    $('filePreviewMeta').textContent = `模拟结果 · ${result.path} · ${result.changed ? '启用时将更新这两个启动参数' : '参数无需变化'} · 未写入小车`;
    $('filePreview').textContent = result.content;
    $('message').textContent = result.message || '';
  }
  async function browse(path) {
    const data = await request(`/api/scenario-setup/browse?kind=${encodeURIComponent(browserState.kind)}&path=${encodeURIComponent(path || '')}`);
    browserState.path = data.path; $('browserPath').textContent = data.path; $('browserUp').disabled = !data.parent; $('browserUp').dataset.path = data.parent || '';
    $('browserList').innerHTML = [...data.directories.map((item) => `<button data-directory="${escape(item.path)}" type="button"><span>▸ ${escape(item.name)}</span><small>目录</small></button>`), ...data.files.map((item) => `<button data-file="${escape(item.path)}" type="button"><span>✓ ${escape(item.name)}</span><small>${(item.size / 1024).toFixed(1)} KiB</small></button>`)].join('') || '<div class="page-empty">当前目录没有可选文件。</div>';
  }
  async function openBrowser(kind, row) {
    browserState = { kind, row, path: '/opt/ry' }; $('browserTitle').textContent = kind === 'fcrp' ? '选择导航启动文件' : '选择定位配置文件'; $('fileBrowser').hidden = false;
    const field = row.querySelector(`[data-field="${kind === 'fcrp' ? 'fcrp_launch' : 'lightning_config'}"]`); const current = field.value.trim();
    try { await browse(current ? current.slice(0, current.lastIndexOf('/')) : ''); } catch (error) { $('browserList').innerHTML = `<div class="page-empty">${escape(error.message)}</div>`; }
  }
  function closeBrowser() { $('fileBrowser').hidden = true; browserState = undefined; }
  async function refresh() { try { render(await request('/api/scenario-setup')); } catch (error) { $('message').textContent = error.message; } }
  async function post(payload) { const result = await request('/api/scenario-setup', { method: 'POST', body: JSON.stringify(payload) }); render(result.status || await request('/api/scenario-setup')); $('message').textContent = result.message || ''; }
  $('addProfile').addEventListener('click', () => { if (lastTransaction.state !== 'normal') return; documentState = { ...documentState, ...collect() }; documentState.profiles.push({ id: `profile-${Date.now()}`, name: '新场景方案', fcrp_launch: '', lightning_config: '' }); renderLocal(); });
  $('saveProfiles').addEventListener('click', () => { if (lastTransaction.state === 'normal') post({ action: 'save', document: collect() }).catch((error) => { $('message').textContent = error.message; }); });
  $('restoreDefault').addEventListener('click', () => { if (confirm('要让小车恢复为平时的常规设置吗？\n工具会重启相关服务并确认恢复完成。')) post({ action: 'restore' }).catch((error) => { $('message').textContent = error.message; }); });
  $('profileList').addEventListener('click', (event) => { const row = event.target.closest('.scenario-profile'); if (!row) return; if (event.target.dataset.browse) { if (lastTransaction.state === 'normal') openBrowser(event.target.dataset.browse, row); return; } if (event.target.classList.contains('preview-profile')) { previewApplication(row.dataset.id).catch((error) => { $('message').textContent = error.message; }); return; } if (event.target.classList.contains('remove-profile')) { if (lastTransaction.state !== 'normal') return; documentState = { ...documentState, ...collect() }; documentState.profiles = documentState.profiles.filter((item) => item.id !== row.dataset.id); renderLocal(); return; } if (event.target.classList.contains('apply-profile') && lastTransaction.state === 'normal' && confirm(`要启用“${row.querySelector('[data-field="name"]').value.trim() || '这个方案'}”吗？\n工具会更新启动参数并重启相关服务。`)) post({ action: 'apply', profile_id: row.dataset.id, document: collect() }).catch((error) => { $('message').textContent = error.message; }); });
  $('browserList').addEventListener('click', (event) => { const button = event.target.closest('button'); if (!button || !browserState) return; if (button.dataset.directory) browse(button.dataset.directory).catch((error) => { $('browserList').innerHTML = `<div class="page-empty">${escape(error.message)}</div>`; }); if (button.dataset.file) { const field = browserState.row.querySelector(`[data-field="${browserState.kind === 'fcrp' ? 'fcrp_launch' : 'lightning_config'}"]`); field.value = button.dataset.file; preview(button.dataset.file); closeBrowser(); } });
  $('browserUp').addEventListener('click', () => { if (browserState && $('browserUp').dataset.path) browse($('browserUp').dataset.path).catch(() => {}); });
  $('closeBrowser').addEventListener('click', closeBrowser); $('fileBrowser').addEventListener('click', (event) => { if (event.target === $('fileBrowser')) closeBrowser(); });
  $('inspection').addEventListener('change', (event) => {
    const slot = event.target.dataset.binding;
    if (!slot || !documentState || lastTransaction.state !== 'normal') return;
    const candidate = commandCandidates.find((item) => item.id === event.target.value);
    if (candidate) documentState.bindings[slot] = { kind: candidate.kind, prefix: candidate.prefix, occurrence: candidate.occurrence };
    else delete documentState.bindings[slot];
  });
  const brandMark = document.querySelector('.mark');
  if (brandMark) brandMark.addEventListener('click', () => { const key = 'ry-aletheia-theme'; const light = !document.body.classList.contains('theme-light'); document.body.classList.toggle('theme-light', light); localStorage.setItem(key, light ? 'light' : 'dark'); });
  if (localStorage.getItem('ry-aletheia-theme') === 'light') document.body.classList.add('theme-light');
  refresh();
})();
