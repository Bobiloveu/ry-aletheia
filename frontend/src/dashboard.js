// 任务指挥台的第一阶段采用兼容挂载：Vue 负责页面生命周期与开发入口，
// 原页面 DOM、类名与已验证的控制器保持不变。后续拆分组件时以此为视觉/行为基线。
import { createApp, nextTick, onBeforeUnmount, onMounted, ref } from 'vue/dist/vue.esm-bundler.js';
import legacyHtml from '../../autodrive_console/web/index.html?raw';
import '../../autodrive_console/web/styles.css';
import '../../autodrive_console/web/refinement.css';

function dashboardMarkup() {
  const documentNode = new DOMParser().parseFromString(legacyHtml, 'text/html');
  documentNode.querySelectorAll('script').forEach((script) => script.remove());
  documentNode.querySelectorAll('a[href="/case-library.html"]').forEach((link) => {
    const icon = link.querySelector('span');
    link.textContent = '';
    if (icon) link.appendChild(icon);
    link.append('测试用例管理');
  });
  return documentNode.body.innerHTML;
}

function legacyControllerUrl() {
  // Vite 预览通过 8087 后端加载原控制器；生产构建则由当前控制台提供。
  if (window.location.port === '5173') {
    return `${window.location.protocol}//${window.location.hostname}:8087/app.js`;
  }
  return '/app.js';
}

createApp({
  setup() {
    const dashboardHost = ref(null);
    let controller = null;

    function routeLegacyPage(event) {
      const link = event.target.closest('aside nav a');
      if (!link) return;
      const target = link.getAttribute('href');
      if (target === '/') {
        event.preventDefault();
        return;
      }
      event.preventDefault();
      if (window.location.port === '5173') {
        // 所有预览路由均保持在 Vite；兼容页面由 Vite 代理至本地后端。
        if (target === '/runtime-settings.html') window.location.assign('/runtime-settings.html');
        else window.location.assign(target);
      } else {
        window.location.assign(target);
      }
    }

    onMounted(async () => {
      dashboardHost.value.innerHTML = dashboardMarkup();
      dashboardHost.value.addEventListener('click', routeLegacyPage);
      await nextTick();
      controller = document.createElement('script');
      controller.src = legacyControllerUrl();
      controller.async = false;
      controller.dataset.vueDashboardController = 'true';
      document.body.appendChild(controller);
    });

    onBeforeUnmount(() => {
      dashboardHost.value?.removeEventListener('click', routeLegacyPage);
      controller?.remove();
    });

    return { dashboardHost };
  },
  template: '<div ref="dashboardHost" class="legacy-dashboard-host"></div>',
}).mount('#app');
