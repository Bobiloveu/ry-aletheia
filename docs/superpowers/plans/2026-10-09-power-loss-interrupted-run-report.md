+# 断电中断普通测试的部分报告 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 普通循环测试在整车断电、进程崩溃或强制终止后，保留已确认轮次和已归档轨迹；控制台下次启动时把未确认运行转为“中断/结果未知”，生成且只生成一份可下载的部分报告，不恢复或重发任何机器人任务。

**Architecture:** 为普通 `RunManager.start()` 运行增加一个独立、严格校验的磁盘检查点存储。执行线程只在可信边界持久化冻结快照；新的 `RunManager` 实例在构造完成后只读取这些快照，重建只读的 `RunRecord`、把正在进行的轮次标为 `unknown_after_power_loss`，原子归档报告并在成功后删除检查点。部署验收继续由其现有 `AcceptancePlanStore` 管理，完全不接入此存储。

**Tech Stack:** Python 3.10、dataclasses、JSON、`os.replace`/fsync、pytest；现有受控 HTTP API 和原生 ES-module 任务看板。

**Spec:** `docs/superpowers/specs/2026-10-09-power-loss-interrupted-run-report-design.md`

## Global Constraints

- 仅覆盖普通 `RunManager.start()` 循环测试；`start_sequence()`、`AcceptanceOrchestrator`、验收检查点和验收锁定语义保持不变。
- 恢复是审计归档，不是执行恢复：不得创建 `RobotGateway`、ROS client、`RosReturnSignalBridge`、导航目标、执行器调用、线程或任何车辆控制命令。
- 重启后不增加确认弹窗或阻止新普通测试；恢复记录是历史终态 `interrupted`，不会占用自动运行互斥锁。
- `unknown_after_power_loss` 不表示 passed/failed/cancelled，不计入通过率；断电在两轮之间时不得编造未知轮次。
- 检查点、轨迹引用和报告写入均受 `report_dir` 目录边界约束；快照不得携带可在恢复中被当作任意路径使用的字段。
- 检查点写入使用同目录临时文件、flush、文件 fsync、`os.replace`、目录 fsync；只有 HTML 与 CSV 都持久化后才删除检查点。
- 不修改机器人配置、ROS Topic、安全边界、任务配置或升级路径；不编译、不打包、不部署到小车。
- 这是 Backend 与 PC Web 的公开运行状态增量。更新 `shared/contracts/task_execution.md`；Mobile 不消费普通运行 API，因此不改 Mobile 源码。

---

## File Map

| File | Responsibility |
| --- | --- |
| `autodrive_console/run_checkpoint.py` (new) | 检查点 schema、严格反序列化、原子持久化、报告目录路径收敛和恢复候选扫描。 |
| `autodrive_console/models.py` | 为 `RunRecord.to_dict()` 增加未知结果计数并保持通过率分母只含 passed/failed。 |
| `autodrive_console/run_manager.py` | 普通运行检查点边界、启动恢复、部分报告文案、原子报告对、幂等恢复清理。 |
| `autodrive_console/web/app.js` | 显示中断运行、未知轮次和非阻塞恢复提示；不改变启动按钮互斥规则。 |
| `shared/contracts/task_execution.md` | 声明普通运行 `interrupted`/`unknown_after_power_loss`、统计、恢复与消费者边界。 |
| `tests/test_run_checkpoint.py` (new) | 存储格式、路径安全、原子写入和无效快照回归。 |
| `tests/test_run_manager.py` | 断电恢复、未知轮次、报告幂等、失败重试和“无 ROS 调用”回归。 |
| `tests/test_offline_modules.py` | HTML/CSV 部分报告的用户可读标签与未知统计回归。 |
| `frontend/test/legacy-app-module.test.mjs` | 看板源码对新状态/非阻塞提示的定向回归。 |

## Implementation Steps

- [ ] **1. 先建立恢复存储的失败测试和安全边界**

  **Files:**
  - Create: `tests/test_run_checkpoint.py`
  - Create: `autodrive_console/run_checkpoint.py`

  **Step 1: Write the failing tests.**
  - 用一个冻结的普通 `RunRecord` 样本验证检查点写入路径是 `<report_dir>/.run-checkpoints/<run-id>.json`，且文件内容只包含 schema、运行 ID、可报告的 case 摘要、状态、轮次、前置检查、人工干预和已验证轨迹引用。
  - 验证一次保存使用临时同目录文件并最终只留下目标 JSON；通过 monkeypatch 文件/目录 fsync 与 `os.replace` 证明替换顺序。
  - 构造错误 schema、缺失字段、重复轮次、非法状态、错配 run ID、`../escape`、报告目录外绝对路径、以及不属于运行 ID 的轨迹目录，断言扫描跳过它们且不抛出。
  - 验证扫描只返回非终态普通运行检查点；不创建目录、不修改文件、不导入或调用任何 ROS/执行器类型。
  - Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest tests/test_run_checkpoint.py -q`
  - Expected: FAIL，因为存储模块尚不存在。

  **Step 2: Implement the smallest storage module.**
  - 定义私有常量 `CHECKPOINT_SCHEMA_VERSION = 1`、普通活动状态集合和 `RunCheckpointStore(report_dir)`；构造器只计算路径，读取路径不存在时不创建目录。
  - 以显式字段函数序列化和恢复 `TestCase`、`TaskParameters`、可选 `MultiTaskRequest`、`AttemptResult` 与 `RunRecord`。恢复出来的 `TestCase.source` 设为不可执行的空值：恢复对象只供 API/报告使用，不能重发任务。
  - 将轨迹中的 `file`、`visualizations[*].file`、冻结地图及任何报告证据统一转换为并只接受 `report_dir` 内的相对路径；恢复时再由经过 `resolve()` + `is_relative_to(report_root)` 的路径重建。拒绝符号链接逃逸、非预期后缀和错误的 `run_<id>_trajectory` 归属。
  - 实现 `save(run, *, attempt_in_progress: bool)`、`remove(run_id)`、`load_recoverable()` 和 `mark_recovered_if_report_exists(...)`。每次 `save` 使用 `tempfile.mkstemp(dir=target.parent)`、UTF-8 JSON、flush、`os.fsync`、`os.replace` 和对父目录的 fsync；清理只删除这个受验证 run ID 的检查点。
  - 将无效检查点记录为受控诊断日志，保留文件以便现场审查，绝不据此生成报告。

  **Step 3: Re-run the focused test.**
  - Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest tests/test_run_checkpoint.py -q`
  - Expected: PASS。

  **Step 4: Commit the storage slice.**
  - `git add autodrive_console/run_checkpoint.py tests/test_run_checkpoint.py && git commit -m "feat: persist ordinary test checkpoints"`

- [ ] **2. 定义普通运行的中断数据和统计语义**

  **Files:**
  - Modify: `autodrive_console/models.py`
  - Modify: `tests/test_run_checkpoint.py`
  - Modify: `tests/test_run_manager.py`

  **Step 1: Add failing model tests.**
  - 断言 `RunRecord(status="interrupted")` 的 `to_dict()` 包含 `summary.unknown`，`completed` 包含已经产生终态或未知结果的记录，`passRate` 仍严格为 `passed / (passed + failed)`。
  - 覆盖只有 `unknown_after_power_loss`、混合 passed/failed/cancelled/unknown，以及断电发生在轮次之间的零未知条目。
  - Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest tests/test_run_checkpoint.py tests/test_run_manager.py -q`
  - Expected: FAIL，因为未知计数和状态尚未进入 API 模型。

  **Step 2: Update the model serialization.**
  - 在 `RunRecord.to_dict()` 统计 `unknown_after_power_loss`，返回稳定的 `summary.unknown`；保留原有字段与已有 completed/passed/failed/cancelled 兼容。
  - 不扩大 `has_active_run()` 或 `manual_control_blocked()` 的集合：`interrupted` 是恢复后的历史记录，不是车辆运动所有者。
  - 将状态/结果文本映射保留在展示层和报告层，模型仍只传固定枚举字符串。

  **Step 3: Re-run the focused tests.**
  - Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest tests/test_run_checkpoint.py tests/test_run_manager.py -q`
  - Expected: PASS。

  **Step 4: Commit the model slice.**
  - `git add autodrive_console/models.py tests/test_run_checkpoint.py tests/test_run_manager.py && git commit -m "feat: expose interrupted run summaries"`

- [ ] **3. 在普通 RunManager 生命周期接入检查点与启动恢复**

  **Files:**
  - Modify: `autodrive_console/run_manager.py`
  - Modify: `tests/test_run_manager.py`
  - Modify: `tests/test_trajectory_fallback.py`

  **Step 1: Write failing lifecycle tests.**
  - 用假的 settings/executor 与已完成 8 轮、`active_attempt=9`、`attempt_in_progress=True` 的检查点初始化全新 `RunManager`；断言它在内存中暴露 `interrupted` 运行、只追加 T-009 的 `unknown_after_power_loss`，并生成一对 HTML/CSV 报告。
  - 验证第 9 轮未知结果不修改第 1–8 轮结果、轨迹和重定位证据；报告名称绑定 run ID。
  - 为“断在轮次之间”写入 `attempt_in_progress=False` 检查点，断言不会增加虚构 attempt。
  - 模拟第一次报告落盘失败：检查点仍在；新 manager 的下一次恢复成功后才删除它。
  - 初始化两次并断言同一 run ID 不会出现两份 HTML/CSV 或重复 Native archive；若上次已完整写出 HTML/CSV 但尚未来得及删除检查点，本次只完成清理。
  - 将 `RobotGateway`、executor 的 `execute/execute_multi/wait_until_available`、`TrajectorySession` 与 return-signal factory 全部设为会失败的 spy，断言构造恢复过程没有触发它们。
  - 运行普通 `start()` 的 stubbed 成功/失败/取消路径，断言检查点分别在创建、尝试开始、可信结果（含轨迹写入之后）、人工恢复、取消请求及正常报告成功后更新或清除。
  - 运行 `start_sequence()` 的既有验收测试，断言不会创建普通 `.run-checkpoints` 文件。
  - Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest tests/test_run_manager.py tests/test_trajectory_fallback.py -q`
  - Expected: FAIL，因为普通 RunManager 尚未持久化或恢复。

  **Step 2: Integrate the checkpoint store without changing execution ownership.**
  - 在 `RunManager.__init__` 初始化 `RunCheckpointStore`，并在全部纯内存字段就绪后调用私有 `_recover_interrupted_runs()`。该方法只读取存储，重建记录、将状态设为 `interrupted`、设置 `finished_at`、以固定中文原因说明意外断电，必要时追加未知 AttemptResult，再放入 `_runs`；绝不分配取消/恢复事件，绝不启动线程。
  - 在 `start()` 登记 `RunRecord` 后、创建线程前写入初始检查点；若检查点持久化失败，移除刚登记的运行和 events，返回受控错误，保证没有任务会在无恢复记录的情况下启动。
  - 为普通运行增加集中私有 helper（例如 `_save_checkpoint(run, attempt_in_progress=...)`），只用于没有 `_skip_report`、没有 `_acceptance_sequence` 标记的记录。把调用放在：
    1. 进入 preparing/running；
    2. 设置 `active_attempt`、还未下发执行器之前；
    3. `_write_trajectory()` 返回且结果已追加/更新后；
    4. `cancel()`、`resume()`、人工停滞处置和每一次进入/退出 `awaiting_recovery`；
    5. finally 中的终态写报告前。
  - 保持检查点“当前轮开始”标志直到服务真实返回且 attempt 已带可信结果写回；不能在轮间等待或恢复等待中留下错误的未知标志。
  - 把验收 parent/child 标记作为显式排除条件；不调整 `start_sequence()` 的事件回调、验收报告或 `AcceptancePlanStore`。
  - 正常、取消、拦截和失败报告成功后清除该普通运行检查点；报告失败保留检查点，并把错误追加到运行诊断。对恢复运行，报告成功后才清理。
  - 复用现有报告文件名中的 run ID 实现幂等识别；恢复前验证同一 stem 的 HTML 与 CSV 是否已经同时存在。两者都存在时只补做受控 Native archive（可重入）和清理，不再写第二份。

  **Step 3: Make report persistence atomic and make partial reports operator-readable.**
  - 将 `_write_report()` 改为先为同一稳定 stem 在报告目录写临时 CSV 与临时 HTML，fsync 后分别原子替换；只有两个最终文件都存在才视为报告可恢复，并随后调用既有 `NativeReportArchive`（其失败仍为不阻断的附加诊断）。
  - 将 `_write_html_report()` 拆为“生成 HTML 字符串”与“写入指定临时路径”，避免直接对最终 `.html` 写入。保留既有 HTML/CSV 格式和报告列表兼容。
  - 在 HTML 增加 `interrupted` 状态标签“意外断电中断”，将未知轮次显示为“结果未知（断电）”，为未知单元格与徽章使用 warning 样式；摘要单列“结果未知”，通过率说明明确“结果未知、取消和未执行均不计入”。
  - 保留所有已验证轨迹的嵌入规则；未知轮若没有可信轨迹，显示缺失证据说明，不能构造或推断路线。
  - 将 `_write_trajectory()` 最终 JSON 改为同目录原子写入，并确保检查点只在该方法成功返回后记录引用。

  **Step 4: Re-run lifecycle and regression tests.**
  - Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest tests/test_run_checkpoint.py tests/test_run_manager.py tests/test_trajectory_fallback.py tests/test_offline_modules.py -q`
  - Expected: PASS。

  **Step 5: Commit the manager slice.**
  - `git add autodrive_console/run_manager.py tests/test_run_manager.py tests/test_trajectory_fallback.py tests/test_offline_modules.py && git commit -m "feat: recover interrupted ordinary test reports"`

- [ ] **4. 更新公开契约与 PC 看板，而不增加重启后的操作门槛**

  **Files:**
  - Modify: `shared/contracts/task_execution.md`
  - Modify: `autodrive_console/web/app.js`
  - Modify: `frontend/test/legacy-app-module.test.mjs`

  **Step 1: Write failing consumer tests.**
  - 断言看板源码为 `interrupted` 提供“意外断电中断”状态，为 `unknown_after_power_loss` 提供“结果未知（断电）”标签，进度/统计文字包含未知数且不把它计入通过率。
  - 断言 `interrupted` 不在 `active`、取消按钮可用状态或启动按钮禁用集合中，并且页面只显示非阻塞说明，不产生确认弹窗、resume 请求或新 API。
  - 断言契约文字明确 Backend 和 PC Web 消费者、Mobile 非消费者、无自动恢复/ROS 发布与结果未知统计规则。
  - Run: `pixi run node --test frontend/test/legacy-app-module.test.mjs`
  - Expected: FAIL，因为新状态尚未被看板和契约描述。

  **Step 2: Update the contract first, then UI.**
  - 在 `shared/contracts/task_execution.md` 现有普通测试/API 描述处增加固定 `RunRecord.status=interrupted` 与 `AttemptResult.status=unknown_after_power_loss`：来源是启动恢复的普通检查点、不能自动重发、已结束且不占运行互斥、`summary.unknown` 的含义及 passRate 分母规则。
  - 标注当前消费者是 Backend 和 PC Web `/index.html`，Mobile 不消费 `/api/runs*`；不修改 Mobile。
  - 在 `statusText()` 与 `renderRun()` 使用受控中文文案。摘要默认对象加 `unknown`，进度行追加“结果未知 n 次”，attempt 表格为未知项提供用户可读的中文结果；仅当运行是 interrupted 时显示“已从意外断电恢复为历史记录；可直接开始新的测试”的非阻塞提示。
  - 保持既有 `active` 状态集合不含 `interrupted`，不新增按钮、POST 路由或任何车辆控制调用。

  **Step 3: Re-run consumer tests.**
  - Run: `pixi run node --test frontend/test/legacy-app-module.test.mjs`
  - Expected: PASS。

  **Step 4: Commit the contract and web slice.**
  - `git add shared/contracts/task_execution.md autodrive_console/web/app.js frontend/test/legacy-app-module.test.mjs && git commit -m "feat: show interrupted test recovery"`

- [ ] **5. 最终定向验证和变更审阅**

  **Files:**
  - Review: 所有本计划改动文件。

  **Step 1: Run focused Backend and Web suites without building.**
  - Run:
    ```sh
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest \
      tests/test_run_checkpoint.py \
      tests/test_run_manager.py \
      tests/test_trajectory_fallback.py \
      tests/test_offline_modules.py -q
    pixi run node --test frontend/test/legacy-app-module.test.mjs
    ```
  - Expected: all targeted tests PASS. Do not run release build, Vite production build, packaging, upload, SSH deployment, or robot upgrade.

  **Step 2: Run static integrity checks.**
  - Run:
    ```sh
    pixi run python -m py_compile autodrive_console/run_checkpoint.py autodrive_console/models.py autodrive_console/run_manager.py
    git diff --check -- autodrive_console/run_checkpoint.py autodrive_console/models.py autodrive_console/run_manager.py autodrive_console/web/app.js shared/contracts/task_execution.md tests/test_run_checkpoint.py tests/test_run_manager.py tests/test_trajectory_fallback.py tests/test_offline_modules.py frontend/test/legacy-app-module.test.mjs
    rg -n 'TODO|FIXME|placeholder|pass #|NotImplemented' autodrive_console/run_checkpoint.py autodrive_console/models.py autodrive_console/run_manager.py tests/test_run_checkpoint.py
    ```
  - Expected: syntax/check output clean; placeholder scan has no newly introduced placeholders.

  **Step 3: Review the diff against safety and scope.**
  - Confirm reports/checkpoints are the only persistent additions; recovery contains no ROS/import side effects; sequence/acceptance paths are excluded; no robot config or packaging file changed.
  - Confirm every externally visible new status is described in the shared contract and has a PC consumer test.
  - Commit the final verification-only changes if any: `git add <exact files> && git commit -m "test: cover interrupted test recovery"`.
