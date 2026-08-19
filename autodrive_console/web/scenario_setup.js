(() => {
  const $ = (id) => document.getElementById(id);
  let documentState; let browserState; let commandCandidates = []; let lastInspection = {}; let lastActiveBackup = null;
  const request = async (url, options = {}) => { const response = await fetch(url, { cache: 'no-store', headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options }); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(body.error || `请求失败（HTTP ${response.status}）`); return body; };
  const escape = (value) => String(value || '').replace(/[&<>"']/g, (item) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[item]);
  const detected = (value, fallback) => value ? `自动识别：${escape(value)}` : fallback;

  function render(status, preserveInspection = false) {
    documentState = status.document;
    documentState.bindings = documentState.bindings || {};
    documentState.search_directories = Array.isArray(documentState.search_directories) ? documentState.search_directories : [];
    const info = preserveInspection ? lastInspection : (status.inspection || {});
    lastInspection = info;
    lastActiveBackup = preserveInspection ? lastActiveBackup : (status.active_backup || null);
    commandCandidates = info.candidates || [];
    const commandSelect = (slot, kind, label) => {
      const all = commandCandidates.filter((item) => item.kind === kind);
      const keyword = slot === 'fcrp' ? /fcrp/i : /lightning/i;
      const preferred = all.filter((item) => keyword.test(`${item.package || ''} ${item.executable || ''}`));
      const selectedPrefix = (documentState.bindings[slot] || {}).prefix;
      const selected = all.find((item) => item.prefix === selectedPrefix);
      const options = (preferred.length ? preferred : all).slice();
      if (selected && !options.some((item) => item.id === selected.id)) options.unshift(selected);
      return `<select data-binding="${slot}"><option value="">${options.length === 1 ? '自动唯一识别' : `请选择 ${label} 参数位置`}</option>${options.map((item) => `<option value="${escape(item.id)}" ${selectedPrefix === item.prefix ? 'selected' : ''}>${escape(item.package)} ${escape(item.executable || '')} → ${escape(item.current)}</option>`).join('')}</select>`;
    };
    $('inspection').innerHTML = [['启动脚本', `<code>${escape(documentState.startup_script)}</code>`], ['FCRP 参数位置', commandSelect('fcrp', 'launch', 'FCRP')], ['定位参数位置', commandSelect('lightning', 'config', 'lightning')]].map(([key, value]) => `<dt>${key}</dt><dd>${value}</dd>`).join('');
    const active = lastActiveBackup;
    $('transactionState').className = `scenario-state${active ? ' pending' : ''}`;
    $('transactionState').textContent = active ? `待恢复：${active.profile_name} 已于 ${active.created_at} 应用。恢复前将验证启动脚本未被外部修改。` : '当前为常规启动配置。应用方案前会自动创建可验证备份。';
    $('profileList').innerHTML = documentState.profiles.length ? documentState.profiles.map((profile) => `<div class="scenario-profile" data-id="${escape(profile.id)}"><label>方案名称<input data-field="name" value="${escape(profile.name)}"></label><label>FCRP 启动文件<div class="scenario-file-field"><input data-field="fcrp_launch" value="${escape(profile.fcrp_launch)}" readonly placeholder="浏览并选择 .launch.py"><button data-browse="fcrp" type="button">浏览</button></div></label><label>lightning 定位 YAML<div class="scenario-file-field"><input data-field="lightning_config" value="${escape(profile.lightning_config)}" readonly placeholder="浏览并选择 YAML"><button data-browse="lightning" type="button">浏览</button></div></label><div class="profile-actions"><button class="preview-profile outline-button" type="button">预览启动脚本</button><button class="apply-profile" type="button">应用</button><button class="remove-profile" type="button">删除</button></div></div>`).join('') : '<div class="page-empty">暂无场景方案。请添加一个受控启动参数方案。</div>';
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
    $('filePreviewMeta').textContent = `模拟预览 · ${result.path} · ${result.changed ? '将替换启动参数' : '参数未发生变化'} · SHA-256 ${result.sha256.slice(0, 12)}… · 未写入机器人`;
    $('filePreview').textContent = result.content;
    $('message').textContent = result.message || '';
  }
  async function browse(path) {
    const data = await request(`/api/scenario-setup/browse?kind=${encodeURIComponent(browserState.kind)}&path=${encodeURIComponent(path || '')}`);
    browserState.path = data.path; $('browserPath').textContent = data.path; $('browserUp').disabled = !data.parent; $('browserUp').dataset.path = data.parent || '';
    $('browserList').innerHTML = [...data.directories.map((item) => `<button data-directory="${escape(item.path)}" type="button"><span>▸ ${escape(item.name)}</span><small>目录</small></button>`), ...data.files.map((item) => `<button data-file="${escape(item.path)}" type="button"><span>✓ ${escape(item.name)}</span><small>${(item.size / 1024).toFixed(1)} KiB</small></button>`)].join('') || '<div class="page-empty">当前目录没有可选文件。</div>';
  }
  async function openBrowser(kind, row) {
    browserState = { kind, row, path: '/opt/ry' }; $('browserTitle').textContent = kind === 'fcrp' ? '选择 FCRP 启动文件' : '选择 lightning 定位 YAML'; $('fileBrowser').hidden = false;
    const field = row.querySelector(`[data-field="${kind === 'fcrp' ? 'fcrp_launch' : 'lightning_config'}"]`); const current = field.value.trim();
    try { await browse(current ? current.slice(0, current.lastIndexOf('/')) : ''); } catch (error) { $('browserList').innerHTML = `<div class="page-empty">${escape(error.message)}</div>`; }
  }
  function closeBrowser() { $('fileBrowser').hidden = true; browserState = undefined; }
  async function refresh() { try { render(await request('/api/scenario-setup')); } catch (error) { $('message').textContent = error.message; } }
  async function post(payload) { const result = await request('/api/scenario-setup', { method: 'POST', body: JSON.stringify(payload) }); $('message').textContent = result.message || ''; render(result.status || await request('/api/scenario-setup')); }
  $('addProfile').addEventListener('click', () => { documentState = { ...documentState, ...collect() }; documentState.profiles.push({ id: `profile-${Date.now()}`, name: '新场景方案', fcrp_launch: '', lightning_config: '' }); renderLocal(); });
  $('saveProfiles').addEventListener('click', () => post({ action: 'save', document: collect() }).catch((error) => { $('message').textContent = error.message; }));
  $('restoreDefault').addEventListener('click', () => { if (confirm('确认恢复常规启动配置？')) post({ action: 'restore' }).catch((error) => { $('message').textContent = error.message; }); });
  $('profileList').addEventListener('click', (event) => { const row = event.target.closest('.scenario-profile'); if (!row) return; if (event.target.dataset.browse) { openBrowser(event.target.dataset.browse, row); return; } if (event.target.classList.contains('preview-profile')) { previewApplication(row.dataset.id).catch((error) => { $('message').textContent = error.message; }); return; } if (event.target.classList.contains('remove-profile')) { documentState = { ...documentState, ...collect() }; documentState.profiles = documentState.profiles.filter((item) => item.id !== row.dataset.id); renderLocal(); } if (event.target.classList.contains('apply-profile') && confirm('应用该场景方案会修改受控启动参数。确认继续？')) post({ action: 'apply', profile_id: row.dataset.id }).catch((error) => { $('message').textContent = error.message; }); });
  $('browserList').addEventListener('click', (event) => { const button = event.target.closest('button'); if (!button || !browserState) return; if (button.dataset.directory) browse(button.dataset.directory).catch((error) => { $('browserList').innerHTML = `<div class="page-empty">${escape(error.message)}</div>`; }); if (button.dataset.file) { const field = browserState.row.querySelector(`[data-field="${browserState.kind === 'fcrp' ? 'fcrp_launch' : 'lightning_config'}"]`); field.value = button.dataset.file; preview(button.dataset.file); closeBrowser(); } });
  $('browserUp').addEventListener('click', () => { if (browserState && $('browserUp').dataset.path) browse($('browserUp').dataset.path).catch(() => {}); });
  $('closeBrowser').addEventListener('click', closeBrowser); $('fileBrowser').addEventListener('click', (event) => { if (event.target === $('fileBrowser')) closeBrowser(); });
  $('inspection').addEventListener('change', (event) => {
    const slot = event.target.dataset.binding;
    if (!slot || !documentState) return;
    const candidate = commandCandidates.find((item) => item.id === event.target.value);
    if (candidate) documentState.bindings[slot] = { kind: candidate.kind, prefix: candidate.prefix };
    else delete documentState.bindings[slot];
  });
  const brandMark = document.querySelector('.mark');
  if (brandMark) brandMark.addEventListener('click', () => { const key = 'ry-aletheia-theme'; const light = !document.body.classList.contains('theme-light'); document.body.classList.toggle('theme-light', light); localStorage.setItem(key, light ? 'light' : 'dark'); });
  if (localStorage.getItem('ry-aletheia-theme') === 'light') document.body.classList.add('theme-light');
  refresh();
})();
