(() => {
  const themeKey = 'ry-aletheia-theme';
  // Desktop navigation has one source of truth so future entries are added to
  // their information group instead of being injected into every page shell.
  // Original sidebar glyphs share the approved 24px grid and optical weight.
  // Inline geometry inherits currentColor and needs no network or icon font.
  const NAVIGATION_ICONS = Object.freeze({
    "dashboard": "<rect x=\"3.5\" y=\"3.5\" width=\"7\" height=\"7\" rx=\"1.8\"/><rect x=\"3.5\" y=\"13.5\" width=\"7\" height=\"7\" rx=\"1.8\"/><rect x=\"13.5\" y=\"13.5\" width=\"7\" height=\"7\" rx=\"1.8\"/><path d=\"m15 3.9 5.2 3.1-5.2 3.1Z\" fill=\"currentColor\" stroke=\"none\"/>",
    "manual-control": "<rect x=\"4\" y=\"15.5\" width=\"16\" height=\"5\" rx=\"2.5\"/><path d=\"M12 9v6.5\"/><circle cx=\"12\" cy=\"6\" r=\"3\"/><path d=\"M17 18h.01\"/>",
    "deployment": "<path d=\"m9 3.8-5.5 3v13.4L9 17.3l6 3 5.5-3V3.8L15 6.7Zm0 0v13.5m6-10.6v13.6\"/>",
    "acceptance": "<path d=\"M8 5.5H6.5A2 2 0 0 0 4.5 7.5v12a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-12a2 2 0 0 0-2-2H16\"/><rect x=\"8\" y=\"2.5\" width=\"8\" height=\"5\" rx=\"1.6\"/><path d=\"m8 14 2.5 2.5 5.5-6\"/>",
    "observation": "<path d=\"M8 3.5H6a2.5 2.5 0 0 0-2.5 2.5v2m13-4.5H18A2.5 2.5 0 0 1 20.5 6v2M3.5 16v2A2.5 2.5 0 0 0 6 20.5h2m8 0h2a2.5 2.5 0 0 0 2.5-2.5v-2\"/><circle cx=\"12\" cy=\"12\" r=\"4\"/><circle cx=\"12\" cy=\"12\" r=\"1.1\" fill=\"currentColor\" stroke=\"none\"/>",
    "test-cases": "<path d=\"M16.5 3.5h-11a2 2 0 0 0-2 2v11\"/><rect x=\"7\" y=\"7\" width=\"13.5\" height=\"13.5\" rx=\"2\"/><path d=\"m10 12 1 1 2-2m2.5 1h2M10 16.5h7.5\"/>",
    "reports": "<rect x=\"4\" y=\"3\" width=\"16\" height=\"18\" rx=\"2.5\"/><path d=\"M8 16v-4m4 4V8m4 8v-6\"/>",
    "bag-recording": "<rect x=\"3.5\" y=\"5\" width=\"17\" height=\"14\" rx=\"2.5\"/><path d=\"M6.5 12H8l1.5-3.5 3 7 1.5-3.5h3.5\"/><circle cx=\"17.5\" cy=\"8\" r=\"1\" stroke=\"none\" fill=\"currentColor\"/>",
    "robot-logs": "<path d=\"M13.5 3.5H6a1.5 1.5 0 0 0-1.5 1.5v14A1.5 1.5 0 0 0 6 20.5h12a1.5 1.5 0 0 0 1.5-1.5V9.5Zm0 0V8A1.5 1.5 0 0 0 15 9.5h4.5M8 13h8m-8 4h5\"/>",
    "settings": "<path d=\"M4 6.5h3m4 0h9M4 12h9m4 0h3M4 17.5h3m4 0h9\"/><circle cx=\"9\" cy=\"6.5\" r=\"2\"/><circle cx=\"15\" cy=\"12\" r=\"2\"/><circle cx=\"9\" cy=\"17.5\" r=\"2\"/>",
    "software": "<path d=\"m12 3 8.5 4.8v8.4L12 21l-8.5-4.8V7.8Zm-8.5 4.8L12 12.6l8.5-4.8M12 12.6V21m-4.25-15.6 8.5 4.8\"/>",
  });
  const navigationIcon = (name) =>
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" focusable="false">${NAVIGATION_ICONS[name]}</svg>`;
  const NAVIGATION_GROUPS = [
    {
      label: "作业",
      items: [
        { href: "/", label: "任务指挥台", icon: "dashboard" },
        { href: "/manual-control.html", label: "手动控制", icon: "manual-control" },
      ],
    },
    {
      label: "部署与验收",
      items: [
        { href: "/deployment.html", label: "部署建图", icon: "deployment" },
        { href: "/acceptance-test.html", label: "部署验收", icon: "acceptance" },
      ],
    },
    {
      label: "测试与诊断",
      items: [
        { href: "/live-observation.html", label: "实时运行观测", icon: "observation" },
        { href: "/case-library.html", label: "测试用例管理", icon: "test-cases" },
      ],
    },
    {
      label: "记录与分析",
      items: [
        { href: "/reports.html", label: "报告中心", icon: "reports" },
        { href: "/bag-recordings.html", label: "诊断录包", icon: "bag-recording" },
        {
          href: "/robot-logs.html",
          label: "机器人日志",
          icon: "robot-logs",
        },
      ],
    },
    {
      label: "系统",
      items: [
        { href: "/runtime-settings.html", label: "运行配置", icon: "settings" },
        { href: "/software-inventory.html", label: "软件资产", icon: "software" },
      ],
    },
  ];
  const applyTheme = () => {
    const light = localStorage.getItem(themeKey) === 'light';
    document.body.classList.toggle('theme-light', light);
    document.documentElement.dataset.theme = light ? 'light' : 'dark';
    document.documentElement.style.colorScheme = light ? 'light' : 'dark';
    document.querySelectorAll('.brand .mark').forEach((mark) => {
      const label = light ? '切换到深色主题' : '切换到浅色主题';
      mark.setAttribute('aria-label', label);
      mark.title = label;
    });
  };
  const markActive = () => {
    const current = location.pathname === '/' ? '/' : location.pathname;
    const parentRoute = { '/scenario-setup.html': '/case-library.html', '/bag-recording-config.html': '/bag-recordings.html' }[current] || current;
    document.querySelectorAll('aside nav a').forEach((link) => {
      const href = link.getAttribute('href');
      link.classList.toggle('active', href === parentRoute);
    });
  };
  const installNavigation = () => {
    const nav = document.querySelector('aside nav');
    if (!nav) return;
    const groups = document.createDocumentFragment();
    NAVIGATION_GROUPS.forEach((group) => {
      const section = document.createElement('div');
      section.className = 'nav-group';
      section.setAttribute('role', 'group');
      section.setAttribute('aria-label', group.label);
      const label = document.createElement('span');
      label.className = 'nav-section-label';
      label.textContent = group.label;
      section.append(label);
      const entries = document.createElement('div');
      entries.className = 'nav-group-entries';
      group.items.forEach((item) => {
        const link = document.createElement('a');
        link.href = item.href;
        link.innerHTML = `<span class="nav-icon" aria-hidden="true">${navigationIcon(item.icon)}</span>${item.label}`;
        entries.append(link);
      });
      section.append(entries);
      groups.append(section);
    });
    nav.replaceChildren(groups);
    markActive();
  };
  const createBrandFallback = () => {
    const namespace = 'http://www.w3.org/2000/svg';
    const icon = document.createElementNS(namespace, 'svg');
    icon.setAttribute('viewBox', '0 0 32 32');
    icon.setAttribute('aria-hidden', 'true');
    const outer = document.createElementNS(namespace, 'path');
    outer.setAttribute('d', 'M5 24 16 4l11 20-11 4z');
    const inner = document.createElementNS(namespace, 'path');
    inner.setAttribute('d', 'm11 21 5-10 5 10-5 2z');
    icon.append(outer, inner);
    return icon;
  };
  const installBrandThemeControl = () => {
    document.querySelectorAll('.brand .mark').forEach((mark) => {
      if (!mark.querySelector('img[src="/aletheia.svg"]')) {
        const logo = Object.assign(document.createElement('img'), {
          src: '/aletheia.svg', alt: '', draggable: false,
        });
        logo.addEventListener('error', () => {
          if (mark.contains(logo)) mark.replaceChildren(createBrandFallback());
        }, { once: true });
        mark.replaceChildren(logo);
      }
      mark.tabIndex = 0;
      mark.setAttribute('role', 'button');
      const toggle = () => {
        const nextLight = !document.body.classList.contains('theme-light');
        localStorage.setItem(themeKey, nextLight ? 'light' : 'dark');
        applyTheme();
      };
      // Capture phase prevents page-specific legacy handlers from toggling a
      // second time while they are being gradually consolidated.
      mark.addEventListener('click', (event) => { event.stopImmediatePropagation(); toggle(); }, true);
      mark.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault(); event.stopImmediatePropagation(); toggle();
        }
      }, true);
    });
  };
  const install = () => { installNavigation(); installBrandThemeControl(); applyTheme(); };
  // Vue compatibility pages mount their legacy markup after DOMContentLoaded.
  // Exposing this tiny, presentation-only hook lets them receive the same shell
  // without duplicating navigation or theme state in every page implementation.
  window.RYAletheiaShell = { applyTheme, installNavigation, installBrandThemeControl, install };
  document.addEventListener('DOMContentLoaded', install);
})();
