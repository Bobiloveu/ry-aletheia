(() => {
  // `/m/` is a dedicated mobile console.  Keep the application routes and their
  // APIs intact, but give every non-real-time page the same compact shell.
  const MOBILE_PAGES = new Set([
    '/', '/case-library.html', '/reports.html', '/scenario-setup.html', '/tool-logs.html',
    '/runtime-settings.html', '/live-observation.html', '/vue/dashboard.html',
  ]);

  const NAV_ITEMS = [
    { id: 'task', href: '/', label: '任务', icon: '<path d="M6 3.5h12v17H6zM9 8h6M9 12h6M9 16h3"/>' },
    { id: 'live', href: '/live-observation.html', label: '观测', icon: '<path d="M4 7.5h11v9H4zM15 10l5-3v10l-5-3"/>' },
    { id: 'cases', href: '/case-library.html', label: '用例', icon: '<path d="M5 5h14v14H5zM8 9h8M8 13h5"/>' },
    { id: 'reports', href: '/reports.html', label: '报告', icon: '<path d="M7 3.5h8l3 3V20.5H7zM10 11h5M10 15h5"/>' },
    { id: 'settings', href: '/runtime-settings.html', label: '设置', icon: '<path d="M12 8.3a3.7 3.7 0 1 0 0 7.4 3.7 3.7 0 0 0 0-7.4Zm0-5.3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4"/>' },
  ];

  const mobileHref = (value) => {
    const target = new URL(value, window.location.origin);
    if (target.origin !== window.location.origin || !MOBILE_PAGES.has(target.pathname)) return value;
    const page = target.pathname === '/' || target.pathname === '/vue/dashboard.html' ? '' : target.pathname;
    return `/m/${page.replace(/^\//, '')}${target.search}${target.hash}`;
  };

  const rewriteLinks = (selector) => {
    document.querySelectorAll(selector).forEach((link) => {
      const href = link.getAttribute('href');
      if (href) link.setAttribute('href', mobileHref(href));
    });
  };

  // The live page owns a performance-oriented shell and gestures for its map.
  // It must not receive the generic header, drawer or navigation a second time.
  const dedicatedLiveConsole = Boolean(
    document.querySelector('.mobile-console-bar') && document.querySelector('.mobile-bottom-nav'),
  );
  if (dedicatedLiveConsole) {
    document.body.classList.add('mobile-console');
    document.documentElement.classList.add('mobile-console');
    rewriteLinks('aside nav a, .side-diagnostic-link, .mobile-bottom-nav a');
    return;
  }

  const currentMobilePath = window.location.pathname.replace(/^\/m(?=\/|$)/, '') || '/';
  const activeNavigationId = () => {
    const path = currentMobilePath;
    if (path === '/' || path === '/vue/dashboard.html' || path === '/scenario-setup.html' || path === '/tool-logs.html') return 'task';
    if (path === '/live-observation.html') return 'live';
    if (path === '/case-library.html') return 'cases';
    if (path === '/reports.html') return 'reports';
    return 'settings';
  };

  const navItem = (item) => {
    const selected = item.id === activeNavigationId();
    return `<a class="mobile-shell-nav-item${selected ? ' is-active' : ''}" href="${mobileHref(item.href)}"${selected ? ' aria-current="page"' : ''}>
      <svg viewBox="0 0 24 24" aria-hidden="true">${item.icon}</svg><span>${item.label}</span>
    </a>`;
  };

  document.body.classList.add('mobile-console', 'mobile-shell-generic');
  document.body.dataset.mobileRoute = currentMobilePath;
  document.documentElement.classList.add('mobile-console');
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', '#d8dde3');
  document.body.insertAdjacentHTML('afterbegin', `
    <header class="mobile-shell-bar" aria-label="Aletheia 移动控制台">
      <a class="mobile-shell-brand" href="/m/" aria-label="Aletheia 首页">
        <span class="mobile-shell-mark" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M5 24 16 4l11 20-11 4z"/><path d="m11 21 5-10 5 10-5 2z"/></svg></span>
        <span><strong>Aletheia</strong><small>mobile console</small></span>
      </a>
      <span class="mobile-shell-state"><i></i><b>本地控制台</b></span>
    </header>
    <nav class="mobile-shell-nav" aria-label="主导航">${NAV_ITEMS.map(navItem).join('')}</nav>
  `);

  rewriteLinks('aside nav a, .side-diagnostic-link');

  // Vue pages mount after this script.  The observer only updates an accessible
  // title, never changes controls or business data rendered by the page itself.
  const syncShellTitle = () => {
    const title = document.querySelector('main h1, .page-main h1')?.textContent?.trim();
    const state = document.querySelector('.mobile-shell-state');
    if (title && state) state.title = title;
  };
  syncShellTitle();
  const titleObserver = new MutationObserver(syncShellTitle);
  titleObserver.observe(document.body, { childList: true, subtree: true });
  window.setTimeout(() => titleObserver.disconnect(), 3000);
})();
