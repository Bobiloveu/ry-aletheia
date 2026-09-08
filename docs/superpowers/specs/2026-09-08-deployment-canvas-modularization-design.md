# 部署建图 Canvas 模块化设计

## 目标

在不改变部署建图现有行为的前提下，收敛 `autodrive_console/web/deployment.js` 的职责边界。第一阶段只模块化组件定义、Canvas 几何计算与绘制；页面状态、DOM 渲染、请求调用、指针事件和任务编排继续保留在入口文件。

## 现状与问题

`deployment.js` 约 2,300 行，当前同时保存页面状态、组件元数据、地图坐标转换、Canvas 绘制、组件命中检测、鼠标/触摸事件、服务端请求和任务编译预览。任意修改地图视觉或工具交互都需要理解整份文件，难以独立测试，也容易误碰部署业务逻辑。

`deployment.css` 暂不在本阶段拆分。样式的层叠和页面布局已经与现有壳层耦合，应在 JavaScript 边界稳定后另立任务处理。

## 方案对比

### 方案 A：一次性迁移为 Vue 页面

优点是最终统一技术栈；缺点是会同时改变 Canvas 生命周期、事件分发、DOM 模板和构建来源，难以区分交互回归来自何处。本阶段不采用。

### 方案 B：渐进提取无状态模块（采用）

保留 `deployment.js` 作为唯一入口，将不需要 DOM、网络或页面状态的逻辑拆为浏览器 ES Module。所有模块输入显式传递，输出不修改全局状态；入口仍负责写状态与调用服务端。可以通过 Node 单元测试锁定坐标和命中行为，再逐步迁移绘制。

### 方案 C：只按函数区域加注释

改动最小，但无法形成可复用或可测试边界，不能解决文件继续膨胀的问题。本阶段不采用。

## 模块边界

新增目录：`autodrive_console/web/deployment/`。

| 模块 | 职责 | 不承担的职责 |
| --- | --- | --- |
| `component-specs.js` | 组件名称、属性字段、默认尺寸及协议模板的纯查找。 | 读取 DOM、读取项目全局状态、发请求。 |
| `canvas-geometry.js` | 世界坐标/画布坐标转换、画布事件坐标、旋转组件局部坐标、矩形命中和缩放约束。 | 绘制 Canvas、修改组件、访问网络。 |
| `canvas-renderer.js` | 基于显式传入的 canvas context、地图、视图、项目数据和绘制回调，绘制网格、底图、路点、组件、路线和擦除预览。 | 绑定事件、读取/修改 DOM、发请求、决定业务工具状态。 |
| `deployment.js` | 页面状态、API、DOM 渲染、事件绑定、服务端持久化及调用上述模块。 | 继续保留作为页面入口，不在本阶段拆页面流程。 |

`deployment.js` 通过 `type="module"` 加载。其 URL、DOM ID、后端接口、请求方法、中文提示、任务预览、组件属性与最终任务生成规则均不改变。

## 数据流

```text
Canvas PointerEvent
  -> deployment.js（工具状态与业务判断）
  -> canvas-geometry.js（坐标 / 命中）
  -> deployment.js（更新本地草稿或请求服务端）
  -> canvas-renderer.js（读取快照并绘制）

组件静态定义
  component-specs.js
  -> deployment.js（属性面板与标签）
  -> canvas-renderer.js（组件符号尺寸）
```

绘制模块只消费只读快照；必要的页面特有绘制细节通过回调传入。因此它不保存跨帧状态，也不知晓小区、任务编译器或物理电梯等业务接口。

## 兼容与安全约束

- 不修改 `web_console.py`、`shared/contracts/`、后端 API、ROS Topic、WebSocket 协议或任务生成器。
- 不修改 `app_shell.css`、`app_shell.js`、`deployment.css`，不提交 `web-vue/` 或 `node_modules`。
- 保持 `/deployment.html` 以及现有页面初始化、工具快捷键、拖拽、缩放、旋转、擦除、路点/组件命中优先级不变。
- 浏览器仍只能通过既有受控 HTTP API 保存项目数据；新模块不得直接访问机器人文件或 ROS。

## 测试策略

在 `frontend/test/deployment/` 使用 Node 内置测试器覆盖纯模块：

- 世界坐标与画布坐标互逆；
- 地图边界判定与旋转组件局部坐标；
- 组件矩形命中与 resize/rotate 控制柄范围；
- 视图缩放范围限制及以指针为中心的缩放平移。

页面层保留既有 `frontend/check-parity.mjs` 守卫，新增部署页面模块入口与关键后端接口引用检查。验证执行 `scripts/test-web.sh`，并以本地 console 对 `/deployment.html` 做只读资源加载检查；不创建、更新或删除部署项目和现场地图数据。

## 分阶段交付

本设计只覆盖第一批 Canvas 模块化。完成后，`deployment.js` 仍会保留事件与业务编排代码；下一批再评估 DOM 渲染、API 调用和 CSS 的独立边界，且需要单独设计与验证。
