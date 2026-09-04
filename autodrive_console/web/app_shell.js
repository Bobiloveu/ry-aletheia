(() => {
  const themeKey = 'ry-aletheia-theme';
  // Desktop navigation has one source of truth so future entries are added to
  // their information group instead of being injected into every page shell.
  const NAVIGATION_GROUPS = [
    {
      label: "作业",
      items: [
        { href: "/", label: "任务指挥台", icon: "⌘" },
        { href: "/manual-control.html", label: "手动控制", icon: "⌁" },
      ],
    },
    {
      label: "部署与验收",
      items: [
        { href: "/deployment.html", label: "部署建图", icon: "◇" },
        { href: "/acceptance-test.html", label: "部署验收", icon: "✓" },
      ],
    },
    {
      label: "测试与诊断",
      items: [
        { href: "/live-observation.html", label: "实时运行观测", icon: "◉" },
        { href: "/case-library.html", label: "测试用例管理", icon: "▤" },
      ],
    },
    {
      label: "记录与分析",
      items: [
        { href: "/reports.html", label: "报告中心", icon: "◫" },
        {
          href: "/robot-logs.html",
          label: "机器人日志",
          icon: '<svg viewBox="0 0 16 16" focusable="false"><path d="M3 1.5h7l3 3v10H3zM10 1.5v3h3M5.5 8h5M5.5 10.5h5"/></svg>',
        },
      ],
    },
    {
      label: "系统",
      items: [
        { href: "/runtime-settings.html", label: "运行配置", icon: "⚙" },
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
    const parentRoute = { '/scenario-setup.html': '/case-library.html' }[current] || current;
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
        link.innerHTML = `<span aria-hidden="true">${item.icon}</span>${item.label}`;
        entries.append(link);
      });
      section.append(entries);
      groups.append(section);
    });
    nav.replaceChildren(groups);
    markActive();
  };
  const installBrandThemeControl = () => {
    document.querySelectorAll('.brand .mark').forEach((mark) => {
      if (!mark.querySelector('img[src="/aletheia.svg"]')) {
        mark.replaceChildren(Object.assign(document.createElement('img'), {
          src: '/aletheia.svg', alt: '', draggable: false,
        }));
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
