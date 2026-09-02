# Web Console 规则

Web 源码位于 `frontend/`。在第二阶段迁移前，其生产构建产物有意保留在 `autodrive_console/web-vue/`。

- 保持 Vite 输出与 Backend 静态资源查找逻辑兼容。
- 浏览器代码只消费受控 HTTP、WebSocket 与 WHEP/WebRTC 接口；绝不直接控制 ROS 或机器人文件。
- 保持 latest-wins 的实时行为以及每路视频流生命周期。
- 修改 Web 消费的跨客户端接口前，先更新 `shared/contracts/`。编辑契约时识别每个 Existing 消费者并运行其定向检查；仅 Web 展示层的变更不需要 Mobile 工具链。
- 使用 `pixi run frontend-check` 验证。不得提交 `frontend/node_modules` 或构建后的 `web-vue` 输出。
