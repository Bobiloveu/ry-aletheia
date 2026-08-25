import { readFileSync } from 'node:fs';

const original = readFileSync('../autodrive_console/web/runtime-settings.html', 'utf8');
const sharedNavigation = readFileSync('../autodrive_console/web/brand_version.js', 'utf8');
const vue = readFileSync('./src/main.js', 'utf8');
const originalDashboard = readFileSync('../autodrive_console/web/index.html', 'utf8');
const vueDashboard = readFileSync('./src/dashboard.js', 'utf8');
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
if (failed) process.exit(1);
console.log('PASS: Vue 运行配置页与任务指挥台保留原页面关键区块、共享样式及控制接口。');
