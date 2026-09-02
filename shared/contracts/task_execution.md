# 任务执行

**Status: Existing（已实现）**
**权威实现：** `web_console.py`、`autodrive_console/case_store.py`、`autodrive_console/run_manager.py` 和 Mobile 功能 Repository
**消费者：** `robot_backend`、`web_console`、`mobile`
**兼容性：** 优先增量变更；破坏性变更必须同时更新所有消费者和本文档。

Backend 拥有任务文件、校验、执行状态、报告、取消、恢复和 supervisor 协调能力。现有 API 家族包括 `/api/cases`、`/api/runs`、`/api/runs/latest`、`/api/reports`、`/api/scenario-setup`、`/api/supervisor/processes` 和 `/api/tool-logs`。

变更性操作属于受控动作：客户端 UI 必须呈现目标、确认、返回错误和当前状态。Mobile 可以消费这些 API，但不得直接改写机器人任务、执行任意命令或创建离线升级包。

## Planned（规划中）

新的任务 schema 版本在使用前，需要在 `shared/schemas` 中提供 JSON Schema、经过 Backend 校验、完成消费者兼容性评审并给出迁移说明。
