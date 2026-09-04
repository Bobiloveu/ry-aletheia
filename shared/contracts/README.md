# 跨客户端共享契约

本目录是 `robot_backend`、`web_console` 和 `mobile` 共用接口的文档唯一事实来源。这里保存带版本的事实和示例，而非实现代码。运行时代码负责实际执行；本目录负责约束跨模块兼容性与消费者影响范围。

## 状态标签

- **Status: Existing** — 已经实现且正在被消费，必须保持兼容。
- **Status: Planned** — 仅为设计意图；不得将其实现或视为已可用能力。

## 变更规则

优先采用向后兼容的增量变更。破坏性 API、ROS Topic、WebSocket 线协议或数据模型变更，必须在同一改动中更新对应契约、每个 Existing 消费者及其定向验证。契约变更必须写明运行时执行方、当前消费者、未来受影响模块、兼容性规则和验证影响。不能因为某客户端未来可能使用某项能力，就将其标记为 Existing 消费者。

普通 Backend、Web 或 Mobile 改动，如果不改变共享字段、端点、Topic、线协议、枚举或安全规则，就不需要其他平台环境。开发 Profile 矩阵见 [docs/development/PROFILES.md](../../docs/development/PROFILES.md)。

## 契约目录

- [机器人控制](robot_control.md)
- [实时观测](realtime_observation.md)
- [视频](video.md)
- [任务执行与部署验收](task_execution.md)
- [部署与地图配置](deployment.md)
- [机器人日志下载](robot_logs.md)
