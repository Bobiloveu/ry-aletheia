import { defineConfig } from 'vite';
import { resolve } from 'node:path';

export default defineConfig({
  base: '/vue/',
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8087',
      '/report-files': 'http://127.0.0.1:8087',
      '/reports': 'http://127.0.0.1:8087',
      // 未迁移页面仍由本地后端提供，但在 Vite 预览中保持 5173 地址，
      // 这样侧栏切换不会退出源码热更新工作流。
      '/case-library.html': 'http://127.0.0.1:8087',
      '/reports.html': 'http://127.0.0.1:8087',
      '/tool-logs.html': 'http://127.0.0.1:8087',
      '/scenario-setup.html': 'http://127.0.0.1:8087',
      '/app.js': 'http://127.0.0.1:8087',
      '/case_library.js': 'http://127.0.0.1:8087',
      '/reports.js': 'http://127.0.0.1:8087',
      '/tool-logs.js': 'http://127.0.0.1:8087',
      '/scenario_setup.js': 'http://127.0.0.1:8087',
      '/styles.css': 'http://127.0.0.1:8087',
      '/refinement.css': 'http://127.0.0.1:8087',
      '/page_views.css': 'http://127.0.0.1:8087',
      '/theme.css': 'http://127.0.0.1:8087',
      '/case_library.css': 'http://127.0.0.1:8087',
      '/reports.css': 'http://127.0.0.1:8087',
      '/tool_logs.css': 'http://127.0.0.1:8087',
      '/scenario_setup.css': 'http://127.0.0.1:8087',
      '/scenario_browser.css': 'http://127.0.0.1:8087',
    },
  },
  build: {
    outDir: '../autodrive_console/web-vue',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      input: {
        runtimeSettings: resolve(import.meta.dirname, 'index.html'),
        runtimeSettingsAlias: resolve(import.meta.dirname, 'runtime-settings.html'),
        dashboard: resolve(import.meta.dirname, 'dashboard.html'),
        liveObservation: resolve(import.meta.dirname, 'live-observation.html'),
      },
    },
  },
});
