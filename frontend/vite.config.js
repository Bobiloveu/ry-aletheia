import { defineConfig } from "vite";
import { resolve } from "node:path";

const legacyBackendOrigin =
  process.env.RY_ALETHEIA_LEGACY_ORIGIN || "http://127.0.0.1:8087";

// These pages are intentionally still served by web_console.py while they are
// incrementally migrated. Keep their complete dependency tree here: Vite's
// history fallback returns the Vue entry HTML for an omitted route, which a
// browser silently treats as a stylesheet, module, or image load failure.
const legacyBackendPaths = [
  "/api",
  "/report-files",
  "/reports",
  "/case-library.html",
  "/reports.html",
  "/tool-logs.html",
  "/robot-logs.html",
  "/scenario-setup.html",
  "/deployment.html",
  "/mapping-workbench.html",
  "/manual-control.html",
  "/acceptance-test.html",
  "/app.js",
  "/case_library.js",
  "/reports.js",
  "/tool-logs.js",
  "/robot_logs.js",
  "/scenario_setup.js",
  "/deployment.js",
  "/mapping_workbench.js",
  "/manual_control.js",
  "/acceptance_test.js",
  "/runtime_settings.js",
  "/brand_version.js",
  "/styles.css",
  "/refinement.css",
  "/page_views.css",
  "/theme.css",
  "/case_library.css",
  "/reports.css",
  "/tool_logs.css",
  "/robot_logs.css",
  "/scenario_setup.css",
  "/scenario_browser.css",
  "/deployment.css",
  "/mapping_workbench.css",
  "/manual_control.css",
  "/acceptance_test.css",
  "/app_shell.css",
  "/app_shell.js",
  "/aletheia.svg",
  "/platform/",
  "/deployment/",
  "/mapping-workbench/",
];

function previewDashboardAtRoot() {
  return {
    name: "ry-aletheia-preview-dashboard-root",
    configureServer(server) {
      server.middlewares.use((request, _response, next) => {
        if (request.url === "/" || request.url?.startsWith("/?")) {
          request.url = `/dashboard.html${request.url.slice(1)}`;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  base: "/vue/",
  plugins: [previewDashboardAtRoot()],
  define: {
    __VUE_OPTIONS_API__: true,
    __VUE_PROD_DEVTOOLS__: false,
    __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: false,
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    // 未迁移页面仍由本地后端提供，但在 Vite 预览中保持 5173 地址，
    // 这样侧栏切换不会退出源码热更新工作流。
    proxy: Object.fromEntries(
      legacyBackendPaths.map((path) => [path, legacyBackendOrigin]),
    ),
  },
  build: {
    outDir: "../autodrive_console/web-vue",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      input: {
        runtimeSettings: resolve(import.meta.dirname, "index.html"),
        runtimeSettingsAlias: resolve(
          import.meta.dirname,
          "runtime-settings.html",
        ),
        dashboard: resolve(import.meta.dirname, "dashboard.html"),
        liveObservation: resolve(import.meta.dirname, "live-observation.html"),
      },
    },
  },
});
