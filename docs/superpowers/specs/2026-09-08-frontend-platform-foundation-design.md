# 前端公共层第一批重构设计

**状态：** 已确认，开始实施
**范围：** 仅公共无框架模块与机器人日志页面试点

## 目标

在不改变页面 URL、HTTP 接口、机器人安全边界、页面文案或视觉设计的前提下，建立传统页面与 Vue 页面未来可共同复用的前端公共层。第一批只迁移机器人日志页面，证明传统页面可以安全使用 ES module；部署建图与实时观测继续保持现状，后续单独拆分。

## 设计

公共模块放在 `autodrive_console/web/platform/`：

- `http.js`：统一 JSON 请求、`no-store` 缓存策略和 HTTP 错误对象；不重试、不注入业务文案。
- `format.js`：无 DOM 依赖的文件大小与时间格式化。

传统页面仍从 `autodrive_console/web/` 运行；迁移页面把自身脚本改为 `type="module"` 并从 `platform/` 导入函数。Vue 页面暂不改变入口，但后续通过显式 adapter 导入同一模块，禁止复制第二份请求或格式化实现。

## 约束

- 不修改 `web_console.py`、共享契约、ROS/WebSocket、任务执行或控制逻辑。
- 不触碰主工作区未提交的 `app_shell.css` 与 `app_shell.js`。
- 不新增 npm 依赖；测试使用 Node 内置 `node:test`。
- 不调整 `refinement.css` 或进行视觉重设计。
- 不提交 `frontend/node_modules` 或 `autodrive_console/web-vue/` 构建产物。

## 验收

1. 平台模块有失败—通过的自动化测试。
2. Robot Logs 页面保留所有现有请求 URL、DOM ID、下载轮询和中文状态文案。
3. `pixi run frontend-check`、`scripts/test-web.sh` 通过。
4. 静态服务可加载 `/robot-logs.html`、`/robot_logs.js` 与 `/platform/*.js`，不出现资源 404。
