# 机器人 Backend 规则

Backend 边界包含 `web_console.py`、`autodrive_console/`、`live_preprocessor/`、`config/`、`tasks/`、`packaging/` 和根目录发布脚本。

- 保持受控的 ROS2 所有权：浏览器与 Mobile 调用 HTTP API，绝不直接访问 ROS Topic。
- 保持工作区/运行时数据所有权，以及离线升级与 DEB 的兼容性。
- 未单独批准第二阶段迁移前，不得移动包目录或修改 `ROOT`/`WORKSPACE` 假设。
- 修改外部消费的 API、遥测线协议、视频行为或控制 Topic 前，先更新 `shared/contracts/`。
- 通过 Pixi 验证：Backend 改动运行 `pixi run test`；离线/运行时行为运行 `pixi run test-offline`。
