# 任务执行

**Status: Existing（已实现）**
**权威实现：** `web_console.py`、`autodrive_console/case_store.py`、`autodrive_console/run_manager.py` 和 Mobile 功能 Repository
**消费者：** `robot_backend`、`web_console`、`mobile`
**兼容性：** 优先增量变更；破坏性变更必须同时更新所有消费者和本文档。

Backend 拥有任务文件、校验、执行状态、报告、取消、恢复和 supervisor 协调能力。现有 API 家族包括 `/api/cases`、`/api/runs`、`/api/runs/latest`、`/api/reports`、`/api/acceptance`、`/api/scenario-setup`、`/api/supervisor/processes` 和 `/api/tool-logs`。

变更性操作属于受控动作：客户端 UI 必须呈现目标、确认、返回错误和当前状态。Mobile 可以消费这些 API，但不得直接改写机器人任务、执行任意命令或创建离线升级包。

## 部署验收（Desktop Web）

**运行时执行方：** Backend `AcceptanceOrchestrator` 通过既有 `RunManager`；**现有消费者：** PC Web `/acceptance-test.html`；**非消费者：** Mobile。

验收计划只能从正式任务目录只读扫描并冻结任务 SHA-256；执行仍走既有受控测试序列，不创建新的 ROS 控制或任务下发路径。范围可以是整个小区，或一个实际物理楼宇单元；物理楼宇单元的稳定键为 `(building, unit)`，例如 `5栋1单元` 与 `5栋2单元` 必须视为两个不同验收对象，即使它们属于相连的“5栋”。

抽样是代表性验收，不是住户普查。响应中的 `selection_summary` 以 `tasks`、`physical_buildings`、`floors`、`doors` 描述本次实际覆盖，不得把“抽样未覆盖每层/每户”当作告警。计划内部保存的随机种子仅用于可审计复现和离线报告，公共 API 与页面不得返回或显示该字段。

部署验收不要求实施人员填写通过率、覆盖率或允许失败数。系统自动显示计划的实际样本覆盖，并按固定规则判定：计划内**所有**任务通过才通过；任一未通过任务即不通过。抽样计划的结果文案必须明确为“本次抽样通过 / 不通过”，并说明它不代表全小区全量验收。旧本地状态中的阈值字段仅为读取兼容保留，不参与新计划的判定，也不应出现在新的计划公共响应或页面。

## Planned（规划中）

新的任务 schema 版本在使用前，需要在 `shared/schemas` 中提供 JSON Schema、经过 Backend 校验、完成消费者兼容性评审并给出迁移说明。
