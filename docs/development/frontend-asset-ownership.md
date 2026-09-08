# Web 前端源码与资源归属

更新时间：2026-09-08

项目当前处于渐进迁移期：`frontend/` 与 `autodrive_console/web/` 会并存。修改页面前，先按本表确认唯一的源码入口；不要因页面地址相近而跨目录复制或修改实现。

## 页面归属

| 页面地址 | 当前源码目录 | 主要入口 | 说明 |
| --- | --- | --- | --- |
| `/runtime-settings.html` | `frontend/` | `frontend/src/main.js` | Vue/Vite 页面，构建输出到 `autodrive_console/web-vue/`。 |
| `/live-observation.html` | `frontend/` | `frontend/src/liveObservation.js` | Vue/Vite 页面，构建输出到 `autodrive_console/web-vue/`。 |
| `/vue/dashboard.html` | `frontend/` | `frontend/src/dashboard.js` | Vue/Vite 页面，构建输出到 `autodrive_console/web-vue/`。 |
| `/deployment.html` | `autodrive_console/web/` | `deployment.js` | 传统页面，部署建图主入口。 |
| `/mapping-workbench.html` | `autodrive_console/web/` | `mapping_workbench.js` | 传统页面，部署建图工作台。 |
| `/manual-control.html` | `autodrive_console/web/` | `manual_control.js` | 传统页面，车辆控制界面。 |
| `/acceptance-test.html` | `autodrive_console/web/` | `acceptance_test.js` | 传统页面，部署验收。 |
| `/case-library.html` | `autodrive_console/web/` | `case_library.js` | 传统页面，测试用例管理。 |
| `/reports.html` | `autodrive_console/web/` | `reports.js` | 传统页面，报告中心。 |
| `/robot-logs.html` | `autodrive_console/web/` | `robot_logs.js` | 传统页面；作为平台层试点，已使用统一 HTTP 与格式化模块。 |

`web_console.py` 负责将以上地址分别路由至 `web/` 或已构建的 `web-vue/`。`autodrive_console/web-vue/` 是构建产物，不是人工编辑目录。

## 共用能力归属

| 能力 | 位置 | 适用范围 |
| --- | --- | --- |
| JSON 请求与标准错误 | `autodrive_console/web/platform/http.js` | 传统页面；统一 `no-store` 策略及 HTTP JSON 错误。 |
| 文件大小、Unix 时间格式化 | `autodrive_console/web/platform/format.js` | 传统页面；避免同类格式化函数重复实现。 |
| 页面壳、侧栏、主题 | `autodrive_console/web/app_shell.js`、`app_shell.css` | 既有共享壳层；未进行迁移或重写。 |

新增传统页面的通用能力应优先放入 `web/platform/`，保持无页面状态、无 DOM 副作用，并配套 `frontend/test/platform/` 的 Node 单元测试。涉及 API、ROS Topic、WebSocket 或共享数据模型时，仍须先更新 `shared/contracts/`。

## 样式维护约束

传统页面的样式仍按加载顺序覆盖：基础样式、主题与细化样式、页面视图样式、页面专属样式、`app_shell.css`。在迁移未完成前：

- 页面专属布局只修改对应页面样式文件，避免借全局选择器修补局部问题；
- `app_shell.css` 与 `app_shell.js` 是公共壳层，修改前必须检查全部消费者；
- 不为单页需求再复制请求、时间或尺寸格式化函数；先复用平台层；
- Vue 页面只从 `frontend/` 修改，并用 `pixi run frontend-check` 生成和验证产物。

本阶段不迁移页面、不改变路由，也不调整机器人控制或部署业务逻辑；目标是先建立明确边界，再按页面逐步收敛。
