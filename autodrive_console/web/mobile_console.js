(() => {
  const MOBILE_PAGES = new Set([
    '/', '/case-library.html', '/reports.html', '/scenario-setup.html', '/tool-logs.html',
    '/runtime-settings.html', '/live-observation.html', '/vue/dashboard.html',
  ]);

  const mobileHref = (value) => {
    const target = new URL(value, window.location.origin);
    if (target.origin !== window.location.origin || !MOBILE_PAGES.has(target.pathname)) return value;
    const page = target.pathname === '/' || target.pathname === '/vue/dashboard.html' ? '' : target.pathname;
    return `/m/${page.replace(/^\//, '')}${target.search}${target.hash}`;
  };

  const closeMenu = () => {
    document.body.classList.remove('mobile-nav-open');
    toggle.setAttribute('aria-expanded', 'false');
  };
  const toggle = document.createElement('button');
  toggle.className = 'mobile-nav-toggle';
  toggle.type = 'button';
  toggle.setAttribute('aria-label', '打开导航菜单');
  toggle.setAttribute('aria-expanded', 'false');
  toggle.innerHTML = '<span></span><span></span><span></span>';

  const scrim = document.createElement('button');
  scrim.className = 'mobile-nav-scrim';
  scrim.type = 'button';
  scrim.tabIndex = -1;
  scrim.setAttribute('aria-label', '关闭导航菜单');

  document.body.classList.add('mobile-console');
  document.body.prepend(scrim, toggle);
  toggle.addEventListener('click', () => {
    const open = document.body.classList.toggle('mobile-nav-open');
    toggle.setAttribute('aria-expanded', String(open));
  });
  scrim.addEventListener('click', closeMenu);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeMenu(); });

  document.querySelectorAll('aside nav a, .side-diagnostic-link').forEach((link) => {
    const href = link.getAttribute('href');
    if (href) link.setAttribute('href', mobileHref(href));
    link.addEventListener('click', closeMenu);
  });

  const desktop = document.createElement('a');
  const mobilePath = window.location.pathname.replace(/^\/m(?=\/|$)/, '') || '/';
  desktop.className = 'mobile-desktop-link';
  desktop.href = `${mobilePath}?view=desktop`;
  desktop.textContent = '↗ 使用桌面版';
  document.querySelector('aside .side-status')?.append(desktop);

  const workspace = document.getElementById('viewerWorkspace');
  if (!workspace) return;
  const viewerState = workspace.querySelector('.map-widget .viewer-state');
  const mapWrap = workspace.querySelector('.map-widget .local-map-wrap');
  if (!viewerState || !mapWrap) return;
  const fullscreen = document.createElement('button');
  fullscreen.className = 'mobile-viewer-fullscreen';
  fullscreen.type = 'button';
  fullscreen.textContent = '⛶ 全屏地图';
  fullscreen.setAttribute('aria-pressed', 'false');
  viewerState.append(fullscreen);
  const fullscreenExit = document.createElement('button');
  fullscreenExit.className = 'mobile-fullscreen-exit';
  fullscreenExit.type = 'button';
  fullscreenExit.textContent = '× 退出全屏';
  fullscreenExit.setAttribute('aria-label', '退出全屏地图');
  mapWrap.append(fullscreenExit);

  const updateFullscreen = (active) => {
    document.body.classList.toggle('mobile-viewer-fullscreen-active', active);
    fullscreen.textContent = active ? '× 退出全屏' : '⛶ 全屏地图';
    fullscreen.setAttribute('aria-pressed', String(active));
    fullscreen.setAttribute('aria-label', active ? '退出全屏地图' : '全屏显示地图');
  };
  const toggleFullscreen = async () => {
    const nativeActive = document.fullscreenElement === workspace;
    if (nativeActive || document.body.classList.contains('mobile-viewer-fullscreen-active')) {
      if (nativeActive && document.exitFullscreen) await document.exitFullscreen().catch(() => {});
      updateFullscreen(false);
      return;
    }
    updateFullscreen(true);
    // Android Chrome 等支持时使用真正全屏；iOS Safari 会拒绝普通 div 的请求，
    // 保留上面的沉浸式 CSS 状态，确保两类手机都能获得完整地图视图。
    if (workspace.requestFullscreen) await workspace.requestFullscreen().catch(() => {});
  };
  fullscreen.addEventListener('click', toggleFullscreen);
  fullscreenExit.addEventListener('click', toggleFullscreen);
  document.addEventListener('fullscreenchange', () => updateFullscreen(document.fullscreenElement === workspace));
  window.addEventListener('pagehide', () => updateFullscreen(false), { once: true });
})();
