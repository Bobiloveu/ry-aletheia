(() => {
  const themeKey = 'ry-aletheia-theme';
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
    if (!nav.querySelector('a[href="/deployment.html"]')) {
      const link = document.createElement('a');
      link.href = '/deployment.html';
      link.innerHTML = '<span aria-hidden="true">◇</span>部署建图';
      const reference = nav.querySelector('a[href="/live-observation.html"]');
      nav.insertBefore(link, reference || null);
    }
    if (!nav.querySelector('a[href="/manual-control.html"]')) {
      const link = document.createElement('a');
      link.href = '/manual-control.html';
      link.innerHTML = '<span aria-hidden="true">⌁</span>手动控制';
      const reference = nav.querySelector('a[href="/live-observation.html"]');
      nav.insertBefore(link, reference || null);
    }
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
