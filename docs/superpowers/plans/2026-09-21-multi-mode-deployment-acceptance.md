# 多模式部署验收 Implementation Plan

> **Execution:** 按任务顺序在当前工作区逐步执行；每个任务都先写失败测试，再实现，再运行定向和回归检查。步骤使用复选框（`- [ ]`）跟踪。

**Goal:** 在部署验收中增加可冻结、可审计的 R6B 多点配送模式，同时保持 R6S 单点任务兼容，并在每个阶段完成定向验证。

**Architecture:** 保留现有 `AcceptanceOrchestrator → RunManager → RosTaskExecutor` 执行链，在 `AcceptanceTaskCatalog` 旁增加只读的 `MultiTaskCatalog`，在计划项/测试用例中增加显式执行模式和请求载荷。前端以计划级模式选择隔离两种目录、服务和报告；R6B 计划用 `MultiTaskDestination[]` 调用多点服务，并通过既有 `/task_status` 记录配送码事件。

**Tech Stack:** Python 3.10 dataclasses/threading/rclpy/pytest；原生 ES modules、HTML/CSS、Node test；ROS2 `master_interfaces`；现有 HTML/CSV 报告生成器。

**Spec:** `docs/superpowers/specs/2026-09-21-multi-mode-deployment-acceptance-design.md`

## Global Constraints

- R6S 继续使用 `/start_execute_tasks` 和当前正式任务目录；R6B 只使用 `/opt/ry/data/tasks/multi_tasks` 与 `/start_multi_tasks_execute`。
- 不读取、复制、修改或删除 `multi_tasks`、`origin_tasks`、行为树、地图和运行配置中的现场文件。
- 计划模式、范围、摆渡策略、最终返程和链路模式在开始前冻结；Backend 按范围随机生成并冻结栋、单元、楼层、门牌、`cargo_type`、`task_uuid` 和 `delivery_code`，运行中不得切换模式或覆盖活动计划。
- `/task_status` 只读监听；不新增货舱控制通道，不重复实现 `CargoCommand`。
- 共享契约变更必须同步识别 Backend/Web 消费者，并运行 `scripts/test-backend.sh` 和 `scripts/test-web.sh`。
- 每个任务按 TDD 顺序执行：先写失败测试、确认失败、写最小实现、确认通过，再进行重构和回归。

## 文件地图

- Modify `autodrive_console/models.py`: 为测试用例、执行请求和配送点增加模式化数据结构，同时保持旧序列化字段兼容。
- Create `autodrive_console/multi_task_catalog.py`: 只读扫描 `multi_tasks`，解析社区、栋单元、标准模板、专用文件和正返程配对。
- Modify `autodrive_console/acceptance_catalog.py`: 保持 R6S catalog 原行为，并在统一摘要中公开两种模式的目录信息。
- Modify `autodrive_console/acceptance_plan.py`: 保存 `execution_mode`、R6B 请求和计划项，维护 schema 向后兼容、范围过滤、全量/抽样和判定摘要。
- Modify `autodrive_console/acceptance_orchestrator.py`: 根据模式构造 R6S/R6B `TestCase`，冻结来源指纹与请求，启动时再次验证目录能力。
- Modify `autodrive_console/ros_executor.py`: 保留旧单点执行，增加强类型多点 service client 和 `/task_status` 事件采集。
- Modify `autodrive_console/run_manager.py`: 将模式化请求传给执行器，在运行记录和轨迹证据中保存 R6B 链路/点位结果。
- Modify `autodrive_console/acceptance_report.py`: 展示模式、链路、配送点、货舱类型、配送码和 skipped 原因。
- Modify `web_console.py`: 动态读取两种 catalog，校验模式化计划请求，保持旧 API 字段兼容。
- Modify `autodrive_console/web/acceptance-test.html`, `acceptance_test.js`, `acceptance_test.css`: 增加模式选择、R6B 点位/链路编排和分层计划表。
- Modify `shared/contracts/task_execution.md`: 记录 `execution_mode`、R6B 目录、ROS 服务、配送码事件和 PC Web 唯一消费者。
- Test `tests/test_multi_task_catalog.py`, `tests/test_acceptance.py`, `tests/test_ros_executor.py`, `tests/test_multi_task_status.py`, `tests/test_run_manager.py`, `tests/test_acceptance_report.py`, `frontend/test/acceptance-preparation.test.mjs` and `frontend/test/acceptance-multi-mode.test.mjs`.

### Task 1: 先固定 R6B 目录扫描契约

**Files:**
- Create: `tests/test_multi_task_catalog.py`
- Create: `autodrive_console/multi_task_catalog.py`

**Interfaces:**
- Produces `MultiTaskCatalog.scan() -> MultiCatalogSnapshot`.
- Snapshot exposes `communities()`, `physical_buildings(community)`, `templates(community, building, unit)`, `special_points(...)`, and `validate_destination(...)`.

- [x] 写失败测试：用临时目录建立 `floor`, `indoor`, `outdoor`, `sub_outdoor_eguard*`，断开一个 `_r` 文件，断言该栋单元和楼层点被标记为不可用；标准 `n_n01` 与专用完整门牌分别被识别。
- [x] 运行 `pixi run bash -c 'unset PYTHONPATH; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_multi_task_catalog.py -q'`，确认新模块不存在或断言失败。
- [x] 实现严格文件名解析、正返程配对、目录越界保护和 JSON 可读性检查；标准模板不生成虚假的业务楼层清单。
- [x] 重新运行该测试并确认通过。
- [x] 运行现有 `tests/test_acceptance.py`（同一 Pixi/pytest 环境），确认 R6S catalog 没有回归。

### Task 2: 为模式化计划和执行请求建立兼容模型

**Files:**
- Modify: `autodrive_console/models.py`
- Modify: `autodrive_console/acceptance_plan.py`
- Test: `tests/test_acceptance.py`

**Interfaces:**
- `TaskParameters.execution_mode` defaults to `single_r6s` only when restoring legacy records.
- Add immutable `MultiDestination` and `MultiTaskRequest` with validation for `cargo_type in {1,2,0,-1}`, non-empty fields, and unique delivery codes within a chain.
- `AcceptancePlan` stores `execution_mode`, `multi_options`, and mode-specific plan items; schema 5 reads schemas 1–4 as R6S.

- [x] 写失败测试：旧计划缺少模式仍读取为 `single_r6s`；R6B 计划拒绝空目的地、重复 `delivery_code`、无效货舱类型；同一小区全量和指定栋单元范围过滤正确。
- [x] 运行 Pixi 隔离环境中的聚焦 pytest，确认新模型尚不存在时先失败。
- [x] 实现 dataclasses、存储/公开序列化、模式字段白名单和范围过滤；保留现有阈值兼容字段但不改变旧判定。
- [x] 重新运行聚焦测试和整个 `tests/test_acceptance.py`（35 passed）。

### Task 3: 增加 R6B 计划创建和冻结校验

**Files:**
- Modify: `autodrive_console/acceptance_orchestrator.py`
- Modify: `web_console.py`
- Test: `tests/test_acceptance.py`

**Interfaces:**
- `POST /api/acceptance/plans` accepts `execution_mode`.
- R6B accepts `multi_options` containing only `out_eguard`, `return_origin` and `chain_mode` (`single`, `chain`, `combined`); Backend generates valid destination rows from the selected multi-task catalog scope.
- `AcceptanceOrchestrator.create_plan` uses `MultiTaskCatalog` for R6B and freezes source fingerprints for every referenced task file.

- [x] 写失败测试：R6B 不能提交 R6S-only fields；目录缺少 paired floor files 时创建计划返回可操作错误，缺少可选 indoor/outdoor 不阻断，只有启用 `out_eguard` 才要求 gate；ready 计划可替换，active 计划拒绝覆盖。
- [x] 运行相关 pytest，确认新 orchestrator 参数和 R6B 分支尚不存在时先失败。
- [x] 实现请求白名单、范围过滤、目的地匹配、来源指纹和计划冻结；`origin_tasks` 不参与 R6B catalog 或校验。
- [x] 重新运行测试并检查旧 R6S 创建计划测试全部通过（37 passed）。

### Task 4: 扩展 ROS 执行器和配送码事件采集

**Files:**
- Modify: `autodrive_console/ros_executor.py`
- Create: `autodrive_console/multi_task_status.py`
- Test: `tests/test_ros_executor.py`, `tests/test_multi_task_status.py`

**Interfaces:**
- Keep `RosTaskExecutor.execute(TaskParameters, ...)` unchanged.
- Add `execute_multi(request: MultiTaskRequest, ...) -> MultiExecutionResult` using `master_interfaces.srv.StartMultiTasksExecute` and typed `MultiTaskDestination[]`.
- `MultiTaskStatusCollector` accepts only the frozen `task_uuid`, maps status code `701` message to delivery code, and returns per-point `passed/failed/skipped` evidence.

- [x] 写失败测试：构造的 ROS request 保留目的地顺序、货舱类型、配送码、摆渡和返程字段；只接受当前 UUID 的 `701`，忽略空 UUID/其他 UUID；未收到的点为 skipped。
- [x] 运行测试确认新 collector 和 request builder 尚不存在时先失败。
- [x] 实现延迟导入 rclpy、服务等待、取消/人工中断检查、bounded collector lifecycle 和异常降级；禁止调用 `CargoCommand`。
- [x] 重新运行聚焦测试（3 passed），并确认无 ROS 运行环境时模块可编译导入。

### Task 5: 将 R6B 请求接入 RunManager 和验收状态机

**Files:**
- Modify: `autodrive_console/run_manager.py`
- Modify: `autodrive_console/acceptance_orchestrator.py`
- Modify: `autodrive_console/models.py`
- Test: `tests/test_acceptance.py`, `tests/test_run_manager.py`

**Interfaces:**
- `TestCase` carries either legacy parameters or a `MultiTaskRequest`.
- `RunManager` dispatches by `execution_mode`; one R6B chain is one acceptance item, and its child delivery results are stored under that item.
- Cancellation, interruption, resume and `skipped` semantics remain identical to existing acceptance state machine.

- [x] 写失败测试：R6S dispatch remains unchanged; R6B invokes `execute_multi` once per chain; a missing delivery event fails the chain and marks later points skipped; restart marks active R6B item unknown without re-dispatch.
- [x] 运行聚焦测试确认 RunManager 尚未有 R6B dispatch 分支时先失败。
- [x] 实现最小 dispatch branch、逐点 evidence merge、当前项进度和终态处理。
- [x] 重新运行相关 Backend tests（RunManager 2 个定向测试通过，既有验收测试保持通过）。

### Task 6: 更新验收报告和共享契约

**Files:**
- Modify: `autodrive_console/acceptance_report.py`
- Modify: `shared/contracts/task_execution.md`
- Test: `tests/test_acceptance.py`, `tests/test_acceptance_report.py`

**Interfaces:**
- Acceptance report exposes mode, scope, chain count, delivery point count, cargo type, delivery code, result and skipped reason.
- Existing report list/download/delete contracts remain backward compatible.

- [x] 写失败测试：R6B report includes per-point delivery evidence and distinguishes sample/full; R6S report output remains unchanged for old plan records.
- [x] 运行报告测试确认 R6B 字段尚未出现时先失败。
- [x] 实现 HTML/CSV rendering and update contract consumer/compatibility notes.
- [x] 重新运行报告与验收回归测试（40 passed）。完整 `scripts/test-backend.sh` 留到集成验证阶段统一运行。

### Task 7: 增加前端模式选择和 R6B 配送点编排

**Files:**
- Modify: `autodrive_console/web/acceptance-test.html`
- Modify: `autodrive_console/web/acceptance_test.js`
- Modify: `autodrive_console/web/acceptance_test.css`
- Modify: `autodrive_console/web/acceptance_preparation.js`
- Test: `frontend/test/acceptance-preparation.test.mjs`, new `frontend/test/acceptance-multi-mode.test.mjs`

**Interfaces:**
- `activeAcceptancePlanSelection` returns `executionMode` and locks it for active plans.
- Mode selection switches R6S controls vs R6B controls without losing draft isolation.
- R6B controls render chain mode, `out_eguard` and `return_origin`; the selected scope drives Backend generation of destination rows, cargo types, UUIDs and delivery codes, which are displayed only after the plan is frozen.

- [x] 写失败测试：页面包含 mode selector and R6B fields; active R6B plan locks mode/scope; R6S draft never submits R6B fields; plan table renders nested delivery points and statuses.
- [x] 运行 `node --test frontend/test/acceptance-preparation.test.mjs frontend/test/acceptance-multi-mode.test.mjs`，确认新模式辅助函数尚不存在时先失败。
- [x] 实现 DOM controls、draft mode migration、R6B request payload and nested plan rendering without direct ROS/file access。
- [x] 运行 focused Node tests（13 passed）and `scripts/test-web.sh`（97 tests passed，Vite parity/build passed）。

### Task 8: 集成验证、文档和现场前置检查

**Files:**
- Modify: `docs/development/PROFILES.md` only if commands/requirements change
- Modify: `shared/contracts/task_execution.md` if prior implementation added fields not covered
- Test: all affected Backend/Web tests

- [x] 构造临时 `multi_tasks` fixture covering standard template, special point, missing return, single-point and multi-point chains; verify catalog and plan JSON without touching `/opt/ry`.
- [x] 运行 `scripts/test-backend.sh`（509 passed）。
- [x] 运行 `scripts/test-web.sh`（97 tests passed，parity/build passed）。
- [x] 运行 Pixi 环境中的 `compileall`、Node 语法检查和 focused acceptance tests。
- [x] Review `git diff --check`, `git status --short`, and confirm no build artifacts, reports, logs, task files or generated caches are tracked。
- [x] 汇总各阶段结果、ROS 车载现场验证要求和当前限制，交给现场验收前复核。
