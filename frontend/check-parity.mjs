import { readFileSync } from 'node:fs';

const original = readFileSync('../autodrive_console/web/runtime-settings.html', 'utf8');
const runtimeSettingsSource = readFileSync('../autodrive_console/web/runtime_settings.js', 'utf8');
const sharedNavigation = readFileSync('../autodrive_console/web/brand_version.js', 'utf8');
const vue = readFileSync('./src/main.js', 'utf8');
const originalDashboard = readFileSync('../autodrive_console/web/index.html', 'utf8');
const vueDashboard = readFileSync('./src/dashboard.js', 'utf8');
const viteConfig = readFileSync('./vite.config.js', 'utf8');
const expected = [
  ['品牌、主导航与诊断入口', ['RY <span>Aletheia</span>', '任务指挥台', '测试用例管理', '报告中心', '运行配置', 'side-diagnostic-link', '诊断日志']],
  ['运行配置页面骨架', ['page-main', 'page-header', 'page-grid', 'CONSOLE SETTINGS', '本机运行参数']],
  ['运行参数字段与保存操作', ['任务目标目录', 'Supervisor 查询超时（秒）', '保存配置']],
  ['测试依赖说明', ['DEPENDENCY ORCHESTRATION', '测试依赖编排']],
  ['离线升级组件', ['OFFLINE CONSOLE UPGRADE', '工具离线升级', 'upgrade-panel', 'upgrade-dropzone', '校验并应用升级', 'Ed25519', 'SHA-256']],
  ['升级安全边界', ['UPGRADE SAFETY', '升级边界']],
];

let failed = false;
for (const [section, values] of expected) {
  // 静态页面通过 web_console.py 注入共享品牌脚本；其中统一修正导航文案。
  const missingOriginal = values.filter(value => !(original + sharedNavigation).includes(value));
  const missingVue = values.filter(value => !vue.includes(value));
  if (missingOriginal.length || missingVue.length) {
    failed = true;
    console.error(`FAIL: ${section}；原页面缺失=[${missingOriginal.join(', ')}]；Vue 缺失=[${missingVue.join(', ')}]`);
  }
}
for (const asset of ['styles.css', 'refinement.css', 'page_views.css']) {
  if (!vue.includes(asset)) { failed = true; console.error(`FAIL: Vue 未复用原共享样式 ${asset}`); }
}
for (const endpoint of ['/api/settings', '/api/system/upgrade']) {
  if (!vue.includes(endpoint)) { failed = true; console.error(`FAIL: Vue 未接入原 API ${endpoint}`); }
}
for (const value of ['type="module" src="/runtime_settings.js"', 'from "./platform/http.js"', '/api/settings', '/api/system/upgrade']) {
  if (!(original + runtimeSettingsSource).includes(value)) {
    failed = true;
    console.error(`FAIL: 运行配置页未接入共享请求层：${value}`);
  }
}
if (failed) process.exit(1);

const dashboardIds = [...originalDashboard.matchAll(/id="([^"]+)"/g)].map((match) => match[1]);
if (dashboardIds.length < 40 || !vueDashboard.includes("documentNode.body.innerHTML")) {
  failed = true;
  console.error('FAIL: Vue 任务指挥台未以原始完整 DOM 作为保真挂载基线。');
}
for (const value of ['index.html?raw', 'styles.css', 'refinement.css', 'app.js', 'dashboardMarkup', 'routeLegacyPage']) {
  if (!vueDashboard.includes(value)) {
    failed = true;
    console.error(`FAIL: Vue 任务指挥台缺少保真迁移基线：${value}`);
  }
}
for (const route of ['/acceptance-test.html', '/acceptance_test.js', '/acceptance_test.css']) {
  if (!viteConfig.includes(`"${route}"`)) {
    failed = true;
    console.error(`FAIL: Vue 预览未代理既有部署验收资源 ${route}`);
  }
}
const robotLogsPage = readFileSync('../autodrive_console/web/robot-logs.html', 'utf8');
const robotLogsSource = readFileSync('../autodrive_console/web/robot_logs.js', 'utf8');
for (const value of [
  'type="module" src="/robot_logs.js"',
  'from "./platform/http.js"',
  'from "./platform/format.js"',
  '/api/robot-logs/sources',
  '/api/robot-logs/downloads',
]) {
  if (!(robotLogsPage + robotLogsSource).includes(value)) {
    failed = true;
    console.error(`FAIL: Robot Logs platform migration missing ${value}`);
  }
}
const deploymentPage = readFileSync('../autodrive_console/web/deployment.html', 'utf8');
const deploymentSource = readFileSync('../autodrive_console/web/deployment.js', 'utf8');
const deploymentCss = readFileSync('../autodrive_console/web/deployment.css', 'utf8');
const mappingWorkbenchPage = readFileSync('../autodrive_console/web/mapping-workbench.html', 'utf8');
const mappingWorkbenchSource = readFileSync('../autodrive_console/web/mapping_workbench.js', 'utf8');
for (const value of [
  'type="module" src="/deployment.js"',
  'from "./deployment/component-specs.js"',
  'from "./deployment/canvas-geometry.js"',
  'from "./deployment/canvas-renderer.js"',
  'from "./platform/http.js"',
  '/api/deployments',
  '/api/mapping/sessions',
  '/task-compiler/preview',
]) {
  if (!(deploymentPage + deploymentSource).includes(value)) {
    failed = true;
    console.error(`FAIL: Deployment modularization missing ${value}`);
  }
}
for (const stylesheet of ["compiler.css", "tools.css"]) {
  if (deploymentCss.includes(`@import url("/deployment/${stylesheet}")`)) continue;
  failed = true;
  console.error(`FAIL: Deployment CSS does not preserve the ${stylesheet} module import.`);
}
for (const value of [
  'type="module" src="/mapping_workbench.js"',
  'from "./mapping-workbench/api.js"',
  '/api/vehicle-control/heartbeat',
  '/api/mapping/sessions',
]) {
  if (!(mappingWorkbenchPage + mappingWorkbenchSource).includes(value)) {
    failed = true;
    console.error(`FAIL: Mapping workbench platform migration missing ${value}`);
  }
}
const manualControlPage = readFileSync('../autodrive_console/web/manual-control.html', 'utf8');
const manualControlSource = readFileSync('../autodrive_console/web/manual_control.js', 'utf8');
for (const value of [
  'type="module" src="/manual_control.js"',
  'from "./platform/vehicle-control.js"',
  '/api/vehicle-control/enter',
  '/api/vehicle-control/command',
  '/api/vehicle-control/release-emergency-stop',
]) {
  if (!(manualControlPage + manualControlSource).includes(value)) {
    failed = true;
    console.error(`FAIL: Manual Control platform migration missing ${value}`);
  }
}
const acceptancePage = readFileSync('../autodrive_console/web/acceptance-test.html', 'utf8');
const acceptanceSource = readFileSync('../autodrive_console/web/acceptance_test.js', 'utf8');
for (const value of [
  'type="module" src="/acceptance_test.js"',
  'from "./platform/http.js"',
  '/api/acceptance/catalog',
  '/api/acceptance/plans/current',
  '/api/acceptance/plans',
]) {
  if (!(acceptancePage + acceptanceSource).includes(value)) {
    failed = true;
    console.error(`FAIL: Acceptance platform migration missing ${value}`);
  }
}
const scenarioSetupPage = readFileSync('../autodrive_console/web/scenario-setup.html', 'utf8');
const scenarioSetupSource = readFileSync('../autodrive_console/web/scenario_setup.js', 'utf8');
for (const value of [
  'type="module" src="/scenario_setup.js"',
  'from "./platform/http.js"',
  '/api/scenario-setup',
  '/api/scenario-setup/file',
  '/api/scenario-setup/browse',
]) {
  if (!(scenarioSetupPage + scenarioSetupSource).includes(value)) {
    failed = true;
    console.error(`FAIL: Scenario setup platform migration missing ${value}`);
  }
}
const toolLogsPage = readFileSync('../autodrive_console/web/tool-logs.html', 'utf8');
const toolLogsSource = readFileSync('../autodrive_console/web/tool-logs.js', 'utf8');
for (const value of [
  'type="module" src="/tool-logs.js"',
  'from "./platform/http.js"',
  'from "./platform/format.js"',
  '/api/tool-logs?scope=',
  '/api/tool-logs/files',
]) {
  if (!(toolLogsPage + toolLogsSource).includes(value)) {
    failed = true;
    console.error(`FAIL: Tool Logs platform migration missing ${value}`);
  }
}
const reportsPage = readFileSync('../autodrive_console/web/reports.html', 'utf8');
const reportsSource = readFileSync('../autodrive_console/web/reports.js', 'utf8');
for (const value of [
  'type="module" src="/reports.js"',
  'from "./platform/http.js"',
  '/api/reports',
  '/api/runs/latest',
  '/api/reports/${encodeURIComponent(filename)}',
]) {
  if (!(reportsPage + reportsSource).includes(value)) {
    failed = true;
    console.error(`FAIL: Reports platform migration missing ${value}`);
  }
}
for (const value of [
  'type="module" src="/app.js"',
  'from "./platform/http.js"',
  '/api/cases',
  '/api/runs/latest',
  '/api/system/shutdown',
]) {
  if (!(originalDashboard + readFileSync('../autodrive_console/web/app.js', 'utf8')).includes(value)) {
    failed = true;
    console.error(`FAIL: Dashboard platform migration missing ${value}`);
  }
}
if (!vueDashboard.includes('controller.type = "module"')) {
  failed = true;
  console.error('FAIL: Vue dashboard compatibility loader must preserve the module controller entry.');
}
for (const sourceName of ['app.js', 'case_library.js', 'reports.js', 'runtime_settings.js', 'scenario_setup.js', 'tool-logs.js']) {
  const source = readFileSync(`../autodrive_console/web/${sourceName}`, 'utf8');
  if (source.includes('ry-aletheia-theme')) {
    failed = true;
    console.error(`FAIL: ${sourceName} 不得重复注册共享主题控制。`);
  }
}
if (failed) process.exit(1);
console.log('PASS: Vue 运行配置页与任务指挥台保留原页面关键区块、共享样式及控制接口。');
