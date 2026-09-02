# RY Aletheia 协作规则

## 开始前阅读

1. 阅读 `README.md`、[docs/development/PROFILES.md](docs/development/PROFILES.md)、相关模块 README，以及 `shared/contracts/` 中适用的 Existing 契约。
2. 修改前阅读 `PROJECT_OVERVIEW.md` 中的机器人与运行时事实，并检查 `git status`。
3. 修改 Backend、Web 或 Mobile 前，阅读对应模块的 `AGENTS.md`。

## 边界

- 未经明确批准，不得进行大规模物理目录迁移、重写业务逻辑、删除数据，或改变机器人安全边界。
- 当前真实模块位置保持不变：机器人 Backend 为 `web_console.py` 与 `autodrive_console/`；Web 源码为 `frontend/`；Flutter 为 `mobile/`；Unity 位于 `unity/`，且当前暂停。
- 跨客户端 API、ROS Topic、WebSocket 线协议或共享数据模型变更，必须同步更新 `shared/contracts/` 并验证每个消费者。
- 修改 `shared/contracts/` 前，先在契约中识别 Backend/Web/Mobile 消费者、更新影响记录，并且只运行受影响模块的检查；普通单模块变更不应因此引入无关平台依赖。
- 任务只要求修改一个模块时，只修改该模块和必要的契约/脚本文档，并说明跨域影响。
- 不得重复实现已有能力，也不得绕过 Backend 所控制的 ROS、视频、任务或部署边界。
- 不得提交构建产物、缓存、日志、签名材料、地图、现场数据或其他开发者的 Golden 失败图片。

## 验证

完成前运行最小相关检查：`scripts/test-backend.sh`、`scripts/test-web.sh` 或 `scripts/test-mobile.sh`。环境行为相关时运行 `scripts/doctor.sh --profile <profile>`。Flutter `CustomPaint` 是当前发布的移动端渲染器；不得默认恢复 Unity。
