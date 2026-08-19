(() => {
  const $ = id => document.getElementById(id);
  let heartbeat = null;
  const state = { payload: null };
  const themeKey = 'ry-aletheia-theme';
  function initializeTheme() {
    const apply = () => {
      const light = localStorage.getItem(themeKey) === 'light';
      document.body.classList.toggle('theme-light', light);
      document.documentElement.style.colorScheme = light ? 'light' : 'dark';
    };
    const toggle = () => { localStorage.setItem(themeKey, document.body.classList.contains('theme-light') ? 'dark' : 'light'); apply(); };
    const mark = document.querySelector('.brand .mark');
    if (mark) { mark.tabIndex = 0; mark.setAttribute('role', 'button'); mark.addEventListener('click', toggle); mark.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); } }); }
    apply();
  }
  const request = async (url, options = {}) => {
    const response = await fetch(url, { cache: 'no-store', ...options });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || `请求失败（HTTP ${response.status}）`);
    return body;
  };
  function apply(payload) {
    state.payload = payload;
    const bridge = payload.bridge || {};
    const online = Boolean(bridge.online);
    $('bridgeState').textContent = online ? (bridge.managed ? '运行中 · 本页管理' : '运行中 · 外部实例') : '未连接';
    $('bridgeDetail').textContent = online ? `Bridge：${bridge.host}:${bridge.port}。${payload.enabled ? '观测页面关闭后将自动回收本页启动的实例。' : '运行配置尚未启用自动启动。'}` : (bridge.detail || '未检测到 Bridge');
    $('observationSideState').textContent = online ? '实时观测已连接' : '按需观测已停止';
    const ready = payload.enabled && online && payload.embed_configured;
    $('embedState').textContent = ready ? 'LIVE' : (!payload.enabled ? '已禁用' : (!online ? '等待 Bridge' : '未配置'));
    $('embedState').className = `badge ${ready ? '' : 'muted'}`;
    const frame = $('foxgloveFrame'); const notice = $('embedNotice');
    if (ready) { frame.hidden = false; notice.hidden = true; if (frame.dataset.url !== payload.embed_url) { frame.src = payload.embed_url; frame.dataset.url = payload.embed_url; } }
    else { frame.hidden = true; frame.removeAttribute('src'); frame.dataset.url = ''; notice.hidden = false; notice.textContent = !payload.enabled ? '实时观测当前未启用。请在“运行配置”保存启用开关后再启动。' : (!online ? 'Foxglove Bridge 未运行。点击“启动实时观测”后将检查并按需拉起。' : 'Bridge 已就绪；请在“运行配置”填写 Foxglove HTTPS 嵌入地址。'); }
    const maps = payload.maps || []; const select = $('mapSelect');
    const previous = select.value; select.replaceChildren();
    maps.forEach(map => { const option = document.createElement('option'); option.value = map.id; option.textContent = `${map.label} · ${map.width}×${map.height}`; select.append(option); });
    $('mapEmpty').hidden = maps.length > 0; $('mapCanvas').hidden = maps.length === 0; select.disabled = maps.length === 0;
    if (maps.length) { const active = payload.active_map_id; select.value = maps.some(map => map.id === active) ? active : (maps.some(map => map.id === previous) ? previous : maps[0].id); showMap(); }
  }
  function showMap() { const id = $('mapSelect').value; if (id) { $('mapEmpty').hidden = true; $('mapCanvas').hidden = false; $('mapPreview').src = `/api/observation/maps/${encodeURIComponent(id)}/preview.png`; } }
  async function refresh() { try { const payload = await request('/api/observation'); apply(payload); return payload; } catch (error) { $('bridgeState').textContent = '读取失败'; $('bridgeDetail').textContent = error.message; return null; } }
  async function start() { $('startObservation').disabled = true; try { apply(await request('/api/observation/start', { method: 'POST' })); } catch (error) { $('bridgeDetail').textContent = error.message; } finally { $('startObservation').disabled = false; } }
  async function stop() { try { apply(await request('/api/observation/stop', { method: 'POST' })); } catch (error) { $('bridgeDetail').textContent = error.message; } }
  function beginHeartbeat() { heartbeat = window.setInterval(async () => { try { apply(await request('/api/observation/heartbeat', { method: 'POST' })); } catch (_) {} }, 3000); }
  $('startObservation').addEventListener('click', start); $('stopObservation').addEventListener('click', stop); $('mapSelect').addEventListener('change', showMap);
  $('mapPreview').addEventListener('error', () => { $('mapCanvas').hidden = true; $('mapEmpty').hidden = false; $('mapEmpty').textContent = '缓存地图预览加载失败；不会影响测试或轨迹取证。请刷新页面，若持续出现请在诊断日志中导出错误信息。'; });
  window.addEventListener('beforeunload', () => { if (heartbeat) clearInterval(heartbeat); });
  async function initializeObservation() {
    const payload = await refresh();
    // 观测是按页面使用的：仅在操作者显式开启功能并进入本页后才启动。
    // 已监听的端口视为外部 Bridge，只复用，绝不接管或停止。
    if (payload?.enabled && !payload.bridge?.online) await start();
    beginHeartbeat();
  }
  initializeTheme(); initializeObservation();
})();
