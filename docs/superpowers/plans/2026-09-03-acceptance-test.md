# 部署验收（Acceptance Test）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个只读扫描正式任务、覆盖优先抽样、可恢复执行并生成证据报告的桌面部署验收模块，同时复用既有机器人执行安全边界。

**Architecture:** `AcceptanceTaskCatalog` 只读扫描正式任务目录，`AcceptancePlanStore` 原子持久化冻结计划和验收标准，`AcceptanceOrchestrator` 在既有 `RunManager` 之上编排多任务序列。`RunManager` 继续是唯一的 ROS2 执行、取消、人工恢复和轨迹采集入口；验收仅通过受控 HTTP API 和一个新桌面 Web 页面操作。

**Tech Stack:** Python 3.10、标准库 `json/hashlib/random/threading`、现有 ROS2 Humble 执行器、原生 `BaseHTTPRequestHandler`、HTML/CSS/Vanilla JavaScript、pytest、Pixi/Vite。

**Spec:** `docs/superpowers/specs/2026-09-03-acceptance-test-design.md`

## Global Constraints

- `task_directory`（默认 `/opt/ry/data/tasks/origin_tasks`）只读；不得创建、修改、重命名或删除其中的任务 JSON。
- 不新增 ROS node、executor、Topic、Service 或浏览器直连 ROS；`RosTaskExecutor` 和 `RobotGateway` 保持为唯一执行/前置检查实现。
- 普通 `RunManager.start(case, count, interval_s)`、任务执行 API、报告、场景方案、视频、实时观测、手动控制、急停、升级和 Flutter/mobile 行为必须保持兼容。
- 验收与普通测试共用活动态互斥；任何一方运行时，另一方返回 409，不允许并行下发机器人任务。
- 执行中的计划、顺序、随机种子、标准快照和源文件 SHA-256 指纹必须冻结；刷新或重启不得悄悄重排或重发当前任务。
- 单项失败后必须等待人工恢复；进程重启后的未知项必须显式确认，绝不自动重发。
- 未完整配置官方阈值时只能给 `CONDITIONAL_PASS`；不编造通过率、覆盖率或人工干预阈值。
- 新页面继承现有深色工业化桌面控制台视觉系统；不新增 Flutter/mobile 页面或路由。
- 工作树已有与本功能无关的未提交修改；每次提交只使用精确文件清单，禁止 `git add .`。

---

## File Structure

| File | Responsibility |
| --- | --- |
| `autodrive_console/acceptance_catalog.py` | 正式任务只读扫描、右向文件名解析、内容检查、指纹、范围统计。 |
| `autodrive_console/acceptance_plan.py` | 验收标准、冻结计划数据、覆盖优先排序、统计与原子持久化。 |
| `autodrive_console/acceptance_orchestrator.py` | 状态机、计划生命周期、序列执行回调、重启中断处理。 |
| `autodrive_console/acceptance_report.py` | 专用 HTML/CSV 验收报告和安全的报告引用。 |
| `autodrive_console/models.py` | 对 `RunRecord` / `AttemptResult` 做最小扩展，保留每个序列项的 case 身份。 |
| `autodrive_console/run_manager.py` | 抽取共享的准备/执行/恢复步骤，增加受控多 case 序列入口，不重复 ROS 逻辑。 |
| `web_console.py` | 构造编排器、路由验收 API、提供静态页面和安全报告下载。 |
| `autodrive_console/web/acceptance-test.html` | 新桌面部署验收页面的语义结构。 |
| `autodrive_console/web/acceptance_test.js` | 页面状态拉取、计划预览、确认执行、恢复、取消和报告下载。 |
| `autodrive_console/web/acceptance_test.css` | 继承现有 Operate UI 的布局、状态、响应式和可访问性样式。 |
| `autodrive_console/web/app_shell.js` | 在桌面壳层加入“部署验收”导航入口。 |
| `shared/contracts/task_execution.md` | 记录新增 API 的 Backend/Web 消费者、Mobile 非消费者和兼容性边界。 |
| `PROJECT_OVERVIEW.md`, `README.md` | 面向维护者记录模块边界、目录只读、恢复和验收判定政策。 |
| `tests/test_acceptance.py` | Catalog、计划、持久化、标准、编排器、报告和 API 的离线测试。 |
| `tests/test_trajectory_fallback.py` | 普通 run 与验收 sequence 共享互斥、恢复和轨迹 case 归属回归。 |

### Task 1: 正式任务 Catalog 与右向解析

**Files:**
- Create: `autodrive_console/acceptance_catalog.py`
- Create: `tests/test_acceptance.py`

**Interfaces:**
- Produces `AcceptanceTask` frozen dataclass: `path: Path`, `filename: str`, `parameters: TaskParameters | None`, `task_group_name: str | None`, `valid: bool`, `warnings: tuple[str, ...]`, `sha256: str | None`.
- Produces `AcceptanceTaskCatalog(task_directory: Path).scan() -> CatalogSnapshot`.
- `CatalogSnapshot` exposes `valid_tasks: tuple[AcceptanceTask, ...]`, `issues: tuple[CatalogIssue, ...]`, `communities() -> list[str]`, `physical_buildings(community: str) -> list[tuple[int, int]]`, and `select(scope_type: str, community: str, building: int | None, unit: int | None) -> list[AcceptanceTask]`.
- Consumers: Task 2’s plan factory and Task 5’s HTTP catalog endpoint.

在 `tests/test_acceptance.py` 先定义全模块共用的临时任务 fixture：

```python
@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    root = tmp_path / "origin_tasks"
    root.mkdir()
    return root


@pytest.fixture
def catalog_snapshot(task_dir: Path):
    for building, unit, floor, door in ((1, 1, 1, 101), (2, 1, 2, 201), (3, 2, 3, 301), (6, 1, 1, 601)):
        write_task(task_dir / f"园区_A_{building}_{unit}_{floor}_{door}.json")
    return AcceptanceTaskCatalog(task_dir).scan()
```

- [ ] **Step 1: 写入失败的右向解析与过滤测试**

```python
def write_task(path: Path, payload: dict | None = None) -> None:
    path.write_text(json.dumps(payload or {"subtasks": [{}], "task_group_name": "示例"}), encoding="utf-8")


def test_catalog_parses_community_from_right_and_ignores_nonformal_files(tmp_path):
    write_task(tmp_path / "成都_龙湖_6_1_3_303.json")
    write_task(tmp_path / "成都_龙湖_6_1_3_304_backup.json")
    write_task(tmp_path / ".hidden_6_1_3_305.json")
    write_task(tmp_path / "成都_龙湖_6_1_3_306_bak_copy.json")

    snapshot = AcceptanceTaskCatalog(tmp_path).scan()

    assert [task.filename for task in snapshot.valid_tasks] == ["成都_龙湖_6_1_3_303.json"]
    task = snapshot.valid_tasks[0]
    assert task.parameters == TaskParameters("成都_龙湖", 6, 1, 3, 303)
    assert task.sha256 and len(task.sha256) == 64
```

- [ ] **Step 2: 写入失败的内容校验、warning 与范围选择测试**

```python
def test_catalog_keeps_invalid_files_as_issues_and_uses_filename_for_scope(tmp_path):
    write_task(tmp_path / "云_栖_6_1_3_301.json", {"subtasks": [{}], "task_group_name": "错误命名"})
    write_task(tmp_path / "云_栖_7_1_3_302.json", {"subtasks": []})
    (tmp_path / "云_栖_8_x_3_303.json").write_text("{}", encoding="utf-8")

    snapshot = AcceptanceTaskCatalog(tmp_path).scan()

    assert [item.parameters.building for item in snapshot.select("building", "云_栖", 6)] == [6]
    assert snapshot.valid_tasks[0].warnings
    assert {issue.filename for issue in snapshot.issues} == {"云_栖_7_1_3_302.json", "云_栖_8_x_3_303.json"}
```

- [ ] **Step 3: 运行测试，确认因模块不存在而失败**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_acceptance.py -k catalog`

Expected: FAIL，`ModuleNotFoundError: autodrive_console.acceptance_catalog`。

- [ ] **Step 4: 实现最小只读 Catalog**

实现下面的固定规则：

```python
FORMAL_SUFFIX = re.compile(r"^(?P<community>.+)_(?P<building>\d+)_(?P<unit>\d+)_(?P<floor>\d+)_(?P<door>\d+)$")
EXCLUDED_NAME = re.compile(r"(?:_bak_|_backup|_old_)", re.IGNORECASE)

def parse_formal_filename(filename: str) -> TaskParameters:
    stem = Path(filename).stem
    match = FORMAL_SUFFIX.fullmatch(stem)
    if not match or not match.group("community"):
        raise ValueError("文件名应以 小区_楼栋_单元_楼层_门牌.json 结尾")
    values = match.groupdict()
    return TaskParameters(values["community"], *(int(values[name]) for name in ("building", "unit", "floor", "door")))
```

`scan()` 只处理目录下一层普通 `.json` 文件。跳过点文件、临时后缀和 `EXCLUDED_NAME` 命中项；其他 JSON/UTF-8/`subtasks` 错误以 `CatalogIssue` 返回。有效 payload 必须为 dict，`subtasks` 必须是非空 list。读取可选字符串 `task_group_name`，缺失或不含可辨认 filename community/building 信息时添加 warning，但不得使任务无效。对有效文件的字节内容计算 SHA-256；按 filename 稳定排序。

- [ ] **Step 5: 增加完整 Catalog 边界测试并验证**

增加测试：非 JSON 忽略、临时文件忽略、无权限/读取失败为 issue、`building` 范围必须来自实际 community、选择不存在社区/楼栋抛 `ValueError`、相同输入快照排序稳定。

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_acceptance.py -k catalog`

Expected: PASS。

- [ ] **Step 6: 提交 Catalog**

```bash
git add autodrive_console/acceptance_catalog.py tests/test_acceptance.py
git commit -m "feat: scan formal tasks for acceptance plans"
```

### Task 2: 冻结计划、覆盖优先选择、标准与原子持久化

**Files:**
- Create: `autodrive_console/acceptance_plan.py`
- Modify: `tests/test_acceptance.py`

**Interfaces:**
- Consumes `AcceptanceTask` and `CatalogSnapshot` from Task 1.
- Produces `AcceptanceCriteria`, `AcceptancePlan`, `AcceptanceResult`, `CoverageSummary`, `AcceptancePlanStore` and `AcceptancePlanFactory`.
- `AcceptancePlanFactory.create(snapshot, *, scope_type, community, building, unit=None, mode, sample_size, random_seed=None, criteria) -> AcceptancePlan`.
- `AcceptancePlanStore(config_dir: Path).load_current() -> AcceptancePlan | None`, `.save(plan) -> None`, `.mark_interrupted_runs() -> list[AcceptancePlan]`, `.load_criteria() -> AcceptanceCriteria`, `.save_criteria(criteria) -> AcceptanceCriteria`.
- Consumers: Task 3 orchestrator, Task 5 API, Task 6 UI.

- [ ] **Step 1: 写入失败的固定种子、冻结快照与覆盖排序测试**

```python
def test_sample_plan_is_seeded_frozen_and_covers_buildings_before_duplicates(catalog_snapshot):
    criteria = AcceptanceCriteria.empty()
    first = AcceptancePlanFactory.create(
        catalog_snapshot, scope_type="community", community="园区_A", building=None,
        mode="sample", sample_size=4, random_seed=41, criteria=criteria,
    )
    second = AcceptancePlanFactory.create(
        catalog_snapshot, scope_type="community", community="园区_A", building=None,
        mode="sample", sample_size=4, random_seed=41, criteria=criteria,
    )

    assert [item.filename for item in first.items] == [item.filename for item in second.items]
    assert len({item.parameters.building for item in first.items[:3]}) == 3
    assert all(item.sha256 for item in first.items)
    assert first.criteria_snapshot == criteria.to_dict()
```

- [ ] **Step 2: 写入失败的结论与未配置阈值测试**

```python
def test_criteria_requires_all_thresholds_for_formal_pass():
    plan = completed_plan(passed=4, failed=0, planned_buildings={1, 2}, passed_buildings={1, 2})
    assert evaluate_conclusion(plan, AcceptanceCriteria.empty()).status == "CONDITIONAL_PASS"

    criteria = AcceptanceCriteria(
        min_pass_rate=100, min_physical_building_coverage=100,
        min_floor_coverage=100, min_door_coverage=100, max_failed_tasks=0,
        max_manual_interventions=0,
    )
    assert evaluate_conclusion(plan, criteria).status == "PASS"
    assert evaluate_conclusion(completed_plan(passed=3, failed=1), criteria).status == "FAIL"
```

- [ ] **Step 3: 写入失败的原子持久化与重启中断测试**

```python
def test_plan_store_preserves_frozen_plan_and_marks_inflight_run_interrupted(tmp_path, catalog_snapshot):
    plan = AcceptancePlanFactory.create(
        catalog_snapshot, scope_type="building", community="园区_A", building=6,
        mode="full", sample_size=None, random_seed=9, criteria=AcceptanceCriteria.empty(),
    )
    plan.status = "running"
    plan.current_index = 1
    store = AcceptancePlanStore(tmp_path)
    store.save(plan)

    recovered = AcceptancePlanStore(tmp_path).mark_interrupted_runs()[0]

    assert recovered.status == "interrupted"
    assert recovered.items[1].status == "unknown_after_restart"
    assert recovered.random_seed == 9
    assert not list(tmp_path.rglob("*.tmp"))
```

- [ ] **Step 4: 运行测试，确认领域对象尚不存在而失败**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_acceptance.py -k 'plan or criteria or store'`

Expected: FAIL，`ModuleNotFoundError: autodrive_console.acceptance_plan`。

- [ ] **Step 5: 实现计划数据与选择算法**

早期计划曾包含可编辑阈值。当前验收页面不再要求实施人员填写这些字段：计划内所有任务通过才通过，任一未通过即不通过。`AcceptanceCriteria` 仅保留给旧状态读取兼容，不参与新计划的结论。

选择过程必须先将候选按 `(building, unit, floor, door, filename)` 排序，再以 `random.Random(seed)` 生成稳定 tie-break。每轮从未选项中选择下列元组最小者：

```python
score = (
    selected_building_count[candidate.building] if community_scope else 0,
    selected_unit_count[candidate.unit],
    selected_floor_count[candidate.floor],
    selected_door_count[candidate.door],
    int(candidate.building == previous.building) if previous else 0,
    int(candidate.unit == previous.unit) if previous else 0,
    int(candidate.floor == previous.floor) if previous else 0,
    tie_break[candidate.filename],
)
```

全量模式选择全部候选；抽样模式要求 `1 <= sample_size <= len(pool)`。抽样显示中性的实际覆盖摘要，不因为未覆盖所有楼层/住户产生警告。`random_seed is None` 时由 `secrets.randbits(63)` 在后端生成并保存，仅用于持久化计划与离线审计报告，公共 API 与页面不得显示。

覆盖统计按 planned/executed/passed 分别计算楼栋、单元、楼层、户集合占比；结论只用 passed coverage。若计划状态不是 `completed`，结论为 `None`。任一已配置阈值违反则 FAIL；所有阈值配置且全部满足才 PASS；否则 CONDITIONAL_PASS。

`AcceptancePlanStore` 写入 `config/acceptance/current-plan.json` 和 `criteria.json`，通过同目录临时文件、`flush()`、`os.fsync()`、`Path.replace()` 原子替换；读取时严格验证 schema/version 且拒绝目录逃逸路径。`mark_interrupted_runs()` 仅把进行中状态改 `interrupted`，将 `current_index` 对应 item 标为 `unknown_after_restart`，绝不改选项顺序或重发任务。

- [ ] **Step 6: 运行计划领域测试**

增加测试：楼栋范围不混入其他楼栋、不同 seed 允许不同排序、sample size 越界、criteria 不接受负数或 >100 覆盖率、已配置阈值失败优先于缺失阈值、planned/executed/passed 分母正确、被打断/取消计划没有结论、指纹变化检测返回明确阻塞理由。

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_acceptance.py -k 'plan or criteria or store'`

Expected: PASS。

- [ ] **Step 7: 提交计划领域层**

```bash
git add autodrive_console/acceptance_plan.py tests/test_acceptance.py
git commit -m "feat: persist acceptance plans and criteria"
```

### Task 3: 受控多任务 RunManager 序列与恢复复用

**Files:**
- Modify: `autodrive_console/models.py:18-75`
- Modify: `autodrive_console/run_manager.py:53-845`
- Modify: `tests/test_trajectory_fallback.py`
- Modify: `tests/test_acceptance.py`

**Interfaces:**
- Produces `RunManager.start_sequence(cases: list[TestCase], *, interval_s: float = 0, prepare_trajectory_maps: bool = True, event_callback: Callable[[dict], None] | None = None) -> RunRecord`.
- Produces sequence event payloads with `type` (`item_preparing`, `item_started`, `item_finished`, `awaiting_recovery`, `recovered`, `sequence_finished`), `run_id`, `item_index`, `case`, `attempt`, `status`, `message`, `trajectory`.
- Extends `AttemptResult` with `case_id: str | None = None` and `case_filename: str | None = None`; legacy constructor defaults keep all normal callers compatible.
- Consumers: Task 4 orchestrator; existing ordinary run consumers retain existing `RunRecord.to_dict()` fields.

在 `tests/test_trajectory_fallback.py` 增加以下最小离线 fake，避免 sequence 测试启动 ROS 或依赖真实时间：

```python
class _SequenceExecutor:
    def __init__(self, results):
        self.results = iter(results)
        self.executed = []

    @staticmethod
    def wait_until_available(**_kwargs):
        return True, "ROS2 服务已就绪"

    def execute(self, parameters, *_args, **_kwargs):
        self.executed.append(parameters)
        return next(self.results)


def wait_until(predicate, timeout_s=2.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("等待后台执行状态超时")


def make_case(number: int) -> TestCase:
    return TestCase(
        id=f"case-{number}", filename=f"园区_{number}_1_1_{number}.json", name=f"任务 {number}",
        parameters=TaskParameters("园区", number, 1, 1, number), source=f"case-{number}.json",
    )


def wait_for_terminal(run: RunRecord) -> None:
    wait_until(lambda: run.status in {"completed", "cancelled", "blocked"})
```

- [ ] **Step 1: 写入失败的 sequence 互斥与 case 归属测试**

```python
def test_sequence_reuses_active_run_lock_and_emits_each_case_result(tmp_path):
    two_cases = [make_case(1), make_case(2)]
    manager = RunManager(tmp_path / "reports", _SequenceExecutor([(True, "完成", 0.0), (True, "完成", 0.0)]), _Settings())
    events = []

    run = manager.start_sequence(two_cases, event_callback=events.append)

    with pytest.raises(RuntimeError, match="已有任务正在执行"):
        manager.start(two_cases[0], 1, 0)
    wait_for_terminal(run)
    finished = [event for event in events if event["type"] == "item_finished"]
    assert [event["case"]["filename"] for event in finished] == [case.filename for case in two_cases]
    assert [attempt.case_filename for attempt in run.attempts] == [case.filename for case in two_cases]
```

- [ ] **Step 2: 写入失败的失败恢复与普通 run 不回归测试**

```python
def test_sequence_failure_waits_for_manual_recovery_before_next_case(tmp_path):
    two_cases = [make_case(1), make_case(2)]
    manager = RunManager(tmp_path / "reports", _SequenceExecutor([(False, "导航失败", 1.0), (True, "完成", 1.0)]), _Settings())
    run = manager.start_sequence(two_cases)
    wait_until(lambda: run.status == "awaiting_recovery")
    assert run.attempts[0].case_filename == two_cases[0].filename
    assert manager.resume(run.id) is run
    wait_for_terminal(run)
    assert [item.case_filename for item in run.attempts] == [case.filename for case in two_cases]


def test_regular_start_keeps_single_case_report_shape(tmp_path):
    one_case = make_case(1)
    manager = RunManager(tmp_path / "reports", _SequenceExecutor([(True, "完成", 0.0), (True, "完成", 0.0)]), _Settings())
    run = manager.start(one_case, 2, 0)
    wait_for_terminal(run)
    assert run.to_dict()["case"]["filename"] == one_case.filename
    assert all(item.case_filename == one_case.filename for item in run.attempts)
```

- [ ] **Step 3: 运行测试，确认 sequence API 尚不存在而失败**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_trajectory_fallback.py tests/test_acceptance.py -k 'sequence or regular_start_keeps_single_case'`

Expected: FAIL，`RunManager` 尚无 `start_sequence`。

- [ ] **Step 4: 以共享 helper 最小重构 RunManager**

不复制 `_run()` 中的 ROS 代码。将既有逻辑抽为以下私有 helper，并让普通 run 与 sequence 都调用：

```python
def _prepare_case(self, run: RunRecord, case: TestCase, cancel_event: threading.Event) -> tuple[bool, dict, list[CachedMapAsset], list[dict], str]: ...
def _execute_case_attempt(self, run: RunRecord, case: TestCase, item_index: int, cancel_event: threading.Event, interrupt_event: threading.Event, assets: list[CachedMapAsset], route_plan: list[dict]) -> AttemptResult: ...
def _recover_after_manual_intervention(self, run: RunRecord, case: TestCase, cancel_event: threading.Event | None = None) -> tuple[bool, str]: ...
```

`start()` 继续创建普通 `RunRecord` 并调用原普通路径；`start_sequence()` 创建同一类型 record，附带私有 sequence case 列表、一个共享 cancel/resume/interrupt event 和同一 `_execution_lock`。sequence 对每个冻结 case 调用 `_prepare_case()` 后执行一次，写 `AttemptResult(case_id=case.id, case_filename=case.filename)`。当前项失败后，发出 `awaiting_recovery` event，使用现有 `resume()` 事件和 `_recover_after_manual_intervention(run, case, ...)`；成功恢复后才继续下一项。

保留现有 scenario 应用/恢复时序；每次 case 的 scenario、preflight、服务发现和轨迹地图均由共享 helper 处理。普通 run 保持“同 case 多次执行”的现有外部语义，不改变 endpoint、状态名或报告文件格式。`to_dict()` 仅在安全的尝试项中附加 `caseId`、`caseFilename`，不要向浏览器暴露绝对 source path。

- [ ] **Step 5: 增加取消、指纹阻塞和异常回收测试**

在 `event_callback` 运行中：取消 sequence 后不得执行后续 case；`_prepare_case()` 失败应发出一个 blocked item event 并结束；executor 抛异常时必须记录 failed item、关闭轨迹 session、释放 execution lock；sequence 结束后新的 ordinary `start()` 可立即开始。使用 fake executor/gateway/trajectory，不启动 ROS 或 Supervisor。

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_trajectory_fallback.py tests/test_acceptance.py -k 'sequence or run_manager'`

Expected: PASS。

- [ ] **Step 6: 提交 sequence 执行层**

```bash
git add autodrive_console/models.py autodrive_console/run_manager.py \
  tests/test_trajectory_fallback.py tests/test_acceptance.py
git commit -m "feat: execute acceptance task sequences through run manager"
```

### Task 4: 验收状态机、指纹保护与专用报告

**Files:**
- Create: `autodrive_console/acceptance_orchestrator.py`
- Create: `autodrive_console/acceptance_report.py`
- Modify: `tests/test_acceptance.py`

**Interfaces:**
- Produces `AcceptanceOrchestrator(catalog, plan_store, run_manager, report_dir)`.
- Produces `catalog() -> dict`, `create_plan(payload: dict) -> dict`, `start(plan_id: str) -> dict`, `resume(plan_id: str) -> dict`, `cancel(plan_id: str) -> dict`, `resolve_interruption(plan_id: str, resolution: Literal["mark_failed", "recover"]) -> dict`, `current() -> dict | None`.
- Produces `AcceptanceConflict(RuntimeError)` for invalid lifecycle transitions and source/active-run conflicts, and `AcceptanceValidationError(ValueError)` for invalid request values.
- Produces `AcceptanceReportWriter(report_dir).write(plan: AcceptancePlan) -> ReportReference`.
- Consumers: Task 5 HTTP endpoints and Task 6 UI.

在 `tests/test_acceptance.py` 统一使用以下 helper；测试通过 task directory 访问源文件，但编排器公开响应不得返回 source path：

```python
def make_orchestrator(task_dir: Path, state_dir: Path, manager: RunManager) -> AcceptanceOrchestrator:
    return AcceptanceOrchestrator(
        catalog=AcceptanceTaskCatalog(task_dir),
        plan_store=AcceptancePlanStore(state_dir / "acceptance"),
        run_manager=manager,
        report_dir=state_dir / "reports",
    )


def full_plan_payload() -> dict[str, object]:
    return {"scope_type": "community", "community": "园区_A", "mode": "full"}
```

- [ ] **Step 1: 写入失败的计划生命周期与源文件指纹测试**

```python
def test_orchestrator_blocks_changed_source_before_start(task_dir, state_dir, manager):
    orchestrator = make_orchestrator(task_dir, state_dir, manager)
    plan = orchestrator.create_plan({
        "scope_type": "building", "community": "园区_A", "building": 6,
        "mode": "full",
    })
    changed = task_dir / plan["items"][0]["filename"]
    changed.write_text(json.dumps({"subtasks": [{"changed": True}]}), encoding="utf-8")

    with pytest.raises(AcceptanceConflict, match="正式任务文件已变化"):
        orchestrator.start(plan["plan_id"])
    assert orchestrator.current()["status"] == "blocked"
```

- [ ] **Step 2: 写入失败的失败—恢复—重启中断测试**

```python
def test_orchestrator_requires_explicit_resolution_after_restart(task_dir, state_dir, manager):
    orchestrator = make_orchestrator(task_dir, state_dir, manager)
    plan = orchestrator.create_plan(full_plan_payload())
    orchestrator.start(plan["plan_id"])
    wait_until(lambda: orchestrator.current()["status"] == "awaiting_recovery")

    recovered = make_orchestrator(task_dir, state_dir, manager)
    assert recovered.current()["status"] == "interrupted"
    with pytest.raises(AcceptanceConflict, match="先核对中断任务"):
        recovered.resume(plan["plan_id"])
    assert recovered.resolve_interruption(plan["plan_id"], "mark_failed")["status"] == "awaiting_recovery"
```

- [ ] **Step 3: 运行测试，确认编排器和报告 writer 尚不存在而失败**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_acceptance.py -k 'orchestrator or acceptance_report'`

Expected: FAIL，`ModuleNotFoundError` 或缺少 `AcceptanceOrchestrator`。

- [ ] **Step 4: 实现状态同步和报告生成**

编排器创建计划时只接受 `scope_type`、community、实际 catalog 的 building、`mode` 和整数 sample size；拒绝前端传来的 source path、参数、task 内容、随机顺序和 criteria snapshot。创建后 status 为 `ready`。

在 start 前重新扫描并逐项验证 `filename`、canonical resolved source path 和 SHA-256 均与冻结项一致。通过后将 status 改 `running`，调用 `RunManager.start_sequence()`；event callback 在持久锁中更新 current item、执行结果、人工干预和状态。回调不得执行网络 I/O 或阻塞 ROS 线程。

`resolve_interruption(..., "mark_failed")` 把未知项记为 `failed` 并转 `awaiting_recovery`；`"recover"` 转 `recovering` 并调用正常恢复，不得直接跳至下一项。只有 finished、cancelled/blocked/interrupted 的状态转换遵循 spec 状态机；重复 start、错误计划 id、无 current plan 都抛明确领域异常。

报告 writer 只写入 `reports/acceptance_<12位hex>_<YYYYMMDD_HHMMSS>.html/.csv`。HTML 通过 `html.escape()` 写所有任务/消息字段，CSV 使用 `csv.writer`，内容包含冻结范围/seed/指纹、单项时间线、人工恢复、覆盖三层、阈值快照、结论和安全相对轨迹链接。报告引用只包含根目录 filename，不包含用户输入路径。

- [ ] **Step 5: 增加报告内容与生命周期回归测试**

测试：成功完成时 writer 只产生安全命名 html/csv；HTML 转义 malicious task_group/message；未完整 criteria 得出 CONDITIONAL_PASS；所有 criteria 满足得 PASS；有一个 criteria 违反得 FAIL；计划取消/阻塞/中断不生成正式结论；catalog 重扫后文件未变仍能启动；多次浏览器读取不创建第二个 `RunManager` run。

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_acceptance.py -k 'orchestrator or acceptance_report or conclusion'`

Expected: PASS。

- [ ] **Step 6: 提交验收编排与报告**

```bash
git add autodrive_console/acceptance_orchestrator.py autodrive_console/acceptance_report.py \
  tests/test_acceptance.py
git commit -m "feat: orchestrate and report deployment acceptance"
```

### Task 5: 受控 HTTP API、报告下载与契约

**Files:**
- Modify: `web_console.py:17-139, do_GET/do_POST routing, 1104-1175`
- Modify: `shared/contracts/task_execution.md`
- Modify: `tests/test_acceptance.py`

**Interfaces:**
- Consumes singleton `ACCEPTANCE = AcceptanceOrchestrator(...)` and Task 4 methods.
- Produces `/acceptance-test.html` static route and `/api/acceptance/*` routes defined in the design spec.
- Extends standard report listing only with safe acceptance files; no absolute path disclosure.
- Consumers: desktop Web only. Flutter/mobile remains an explicit non-consumer.

- [ ] **Step 1: 写入失败的 HTTP input validation 和冲突测试**

```python
def test_acceptance_api_rejects_arbitrary_paths_and_invalid_scope(monkeypatch):
    handler = make_handler("POST", "/api/acceptance/plans", {
        "scope_type": "building", "community": "园区_A", "building": "../../etc/passwd",
        "mode": "sample", "sample_size": 2, "source_path": "/etc/passwd",
    })
    handler._acceptance_action(handler.path)
    handler._json.assert_called_once()
    assert handler._json.call_args.args[0]["error"]
    assert handler._json.call_args.args[1] == HTTPStatus.BAD_REQUEST


def test_acceptance_start_returns_conflict_when_regular_run_is_active(monkeypatch):
    acceptance = Mock()
    acceptance.start.side_effect = AcceptanceConflict("已有任务正在执行")
    handler = make_handler("POST", "/api/acceptance/plans/a1/start", {})
    monkeypatch.setattr(web_console, "ACCEPTANCE", acceptance)
    handler._acceptance_action(handler.path)
    assert handler._json.call_args.args[1] == HTTPStatus.CONFLICT
```

- [ ] **Step 2: 运行 API 测试，确认路由尚不存在而失败**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_acceptance.py -k acceptance_api`

Expected: FAIL，handler 尚无 `_acceptance_action` 或路由为 404。

- [ ] **Step 3: 实现 API 和安全报告引用**

导入并构造 `AcceptanceTaskCatalog(Path(SETTINGS.load().task_directory))`、`AcceptancePlanStore(CONFIG_DIR / "acceptance")`、`AcceptanceOrchestrator(..., RUNS, WORKSPACE / "reports")`；目录每次 catalog request/plan create 时从最新 Settings 读取，不能在 import 时将机器人路径固化。

按下列路由分派：

```text
GET  /api/acceptance/catalog
GET  /api/acceptance/criteria
PUT  /api/acceptance/criteria
POST /api/acceptance/plans
GET  /api/acceptance/plans/current
GET  /api/acceptance/plans/<plan_id>
POST /api/acceptance/plans/<plan_id>/reroll
POST /api/acceptance/plans/<plan_id>/start
POST /api/acceptance/plans/<plan_id>/resume
POST /api/acceptance/plans/<plan_id>/cancel
POST /api/acceptance/plans/<plan_id>/resolve-interruption
GET  /api/acceptance/plans/<plan_id>/report
```

`plan_id` 必须匹配 `[0-9a-f]{12}`。JSON body 限制为合理小对象（复用现有解析上限）；未知键、类型不符、值域不符为 400，非法状态/活动 run/源变更为 409，未知 plan 为 404。下载报告仅通过 orchestrator 的安全 root filename；不能把 URL 提供的文件名拼接到 filesystem。

将 `REPORT_FILENAME` 扩展为同时识别现有普通报告和 `acceptance_<12位hex>_<14位时间>.html`；`_reports()` 给 acceptance 项加 `kind: "acceptance"`，既有普通项仍默认 `kind: "run"`。删除验证必须基于正则和 root directory，验收报告删除只删除同 stem 的 `.html/.csv`，不删除其他 run 的轨迹目录。

在 `shared/contracts/task_execution.md` 增加“部署验收 API”章节，标出 Backend producer、Desktop Web consumer、Mobile non-consumer、只读正式任务目录、普通 run 互斥和 additive compatibility。

- [ ] **Step 4: 增加 API 与报告安全测试并运行**

测试：catalog 只返回安全相对字段；所有合法 action 交给编排器；criteria PUT 不能写入计划 snapshot；未知 action/path 404；report 下载不能 traversal；普通报告列表/下载/删除仍通过；acceptance 报告列表/下载/删除按安全 stem 工作。

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_acceptance.py tests/test_repository_conventions.py -k 'acceptance or report'`

Expected: PASS。

- [ ] **Step 5: 提交 API 和契约**

```bash
git add web_console.py shared/contracts/task_execution.md tests/test_acceptance.py
git commit -m "feat: expose deployment acceptance API"
```

### Task 6: 桌面验收页面与导航

**Files:**
- Create: `autodrive_console/web/acceptance-test.html`
- Create: `autodrive_console/web/acceptance_test.js`
- Create: `autodrive_console/web/acceptance_test.css`
- Modify: `autodrive_console/web/app_shell.js`
- Modify: `tests/test_repository_conventions.py`

**Interfaces:**
- Consumes only Task 5’s `/api/acceptance/*` JSON API.
- Produces desktop route `/acceptance-test.html`, desktop app-shell navigation item `部署验收`, keyboard-accessible forms/buttons and visible async/error states.
- Mobile/Flutter are not consumers and remain untouched.

- [ ] **Step 1: 写入失败的页面存在性与 API 边界测试**

```python
def test_acceptance_page_is_desktop_only_and_uses_only_controlled_api_paths():
    html = (WEB_ROOT / "acceptance-test.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "acceptance_test.js").read_text(encoding="utf-8")

    assert "部署验收" in html
    assert "/api/acceptance/catalog" in script
    assert "rosbridge" not in script.lower()
    assert "/is_emergency_stop" not in script
    assert "acceptance-test.html" not in web_console.MOBILE_PAGE_NAMES
```

- [ ] **Step 2: 运行测试，确认页面尚不存在而失败**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_repository_conventions.py tests/test_acceptance.py -k acceptance_page`

Expected: FAIL，页面或脚本不存在。

- [ ] **Step 3: 在实现 UI 前执行页面设计约束检查**

运行并记录现有视觉上下文；这是既有控制台扩展，不创建新的视觉身份或独立 mobile 页面：

```bash
node /home/bob/.codex/skills/impeccable/scripts/context.mjs --target autodrive_console/web/acceptance-test.html
```

使用现有 `styles.css`、`refinement.css`、`page_views.css`、`app_shell.css` 的字体、token、卡片、表单、状态色、sidebar 和按钮语义。页面第一屏必须明确回答：当前可验收范围是什么、计划是否已经冻结、下一步是否需要生成/确认/人工恢复；不要堆叠装饰图表或引入新的渐变/玻璃视觉体系。

- [ ] **Step 4: 实现语义结构、状态和交互**

HTML 使用现有 page shell，创建四个具备 `<section aria-labelledby>` 的区域：

```text
验收范围：community select、scope radios、building select、catalog summary/warnings
计划预览：full/sample radios、bounded sample input、生成计划、seed、coverage warning、冻结任务表、开始确认
执行状态：current task、progress、awaiting recovery explanation、resume/cancel/interruption resolution
验收标准与结果：七项 threshold inputs、保存标准、planned/executed/passed coverage、conclusion、report link
```

JS 使用一个 `state` 对象和 `refresh()`，每 2 秒仅在 active plan 时轮询 `GET /api/acceptance/plans/current`；页面隐藏时停止定时器，`visibilitychange` 恢复时立即刷新。所有 action 禁用重复点击直到响应完成，显示来自后端的错误文本；开始计划需要二次确认对话框，恢复/中断处理说明“不会自动重新下发当前任务”。不在前端随机、过滤、判定结论或持久化参数。

CSS 使用现有 token；范围/计划/结果使用响应式网格，宽度低于 900px 单列，不采用固定 pixel 表宽。失败、阻塞、未知、条件通过、通过都使用文字+色彩+图标/标签，保证非色觉用户可区分。所有 button/input 有 `:focus-visible`，不可用按钮给出说明而非只置灰。

在 `app_shell.js` 以现有动态导航方式注入“部署验收”入口；不要加入 `MOBILE_PAGE_NAMES`，不要改动已有移动页面。

- [ ] **Step 5: 运行页面静态检查、生产构建与视觉检测**

Run:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_repository_conventions.py tests/test_acceptance.py -k acceptance_page
./scripts/test-web.sh
node /home/bob/.codex/skills/impeccable/scripts/detect.mjs --json \
  autodrive_console/web/acceptance-test.html \
  autodrive_console/web/acceptance_test.js \
  autodrive_console/web/acceptance_test.css
```

Expected: tests/build PASS；修复 detector 可机械判定的问题，记录非机械项目供最终视觉复核。

- [ ] **Step 6: 在现有控制台中进行两轮视觉与交互检查**

以 1440px 与 390px 宽度检查：范围选择、楼栋联动、计划预览、过长中文小区名称、无任务空态、扫描 warning、active/awaiting recovery/blocked/conditional pass 状态、键盘 tab 顺序、浏览器刷新和页面隐藏恢复。每轮批量修复后再复查；不改变后端任务逻辑来迁就 UI。

- [ ] **Step 7: 提交桌面页面**

```bash
git add autodrive_console/web/acceptance-test.html autodrive_console/web/acceptance_test.js \
  autodrive_console/web/acceptance_test.css autodrive_console/web/app_shell.js \
  tests/test_repository_conventions.py
git commit -m "feat: add deployment acceptance console page"
```

### Task 7: 文档、完整回归与发布前核验

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_OVERVIEW.md`
- Modify: `docs/superpowers/specs/2026-09-03-acceptance-test-design.md`（状态改为已实施，写入实际接口/限制）
- Modify: `docs/superpowers/plans/2026-09-03-acceptance-test.md`（勾选已执行步骤并写入实际验证结果）
- Modify: `tests/test_acceptance.py`

**Interfaces:**
- Documents exact API, storage directory, recovery rule, criteria conclusion policy, read-only official-task rule and explicit non-impact on mobile/ROS protocol.
- Produces evidence that backend/web integration remains compatible.

- [ ] **Step 1: 写入失败的跨功能保护回归测试**

```python
def test_acceptance_addition_does_not_register_mobile_page_or_ros_transport():
    assert "acceptance-test.html" not in web_console.MOBILE_PAGE_NAMES
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("autodrive_console").glob("acceptance_*.py")
    )
    assert "rclpy.create_node" not in sources
    assert "RosTaskExecutor(" not in sources


def test_formal_task_directory_is_never_opened_for_write_in_acceptance_sources():
    catalog_source = Path("autodrive_console/acceptance_catalog.py").read_text(encoding="utf-8")
    assert ".write_text(" not in catalog_source
    assert ".unlink(" not in catalog_source
    assert ".rename(" not in catalog_source
```

- [ ] **Step 2: 运行保护测试并确认通过**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_acceptance.py -k 'does_not_register or never_opened'`

Expected: PASS。

- [ ] **Step 3: 更新维护文档**

在 README 增加“部署验收”入口、部署前任务目录要求和用户操作顺序：扫描范围 → 生成计划 → 核对 → 开始 → 人工恢复 → 下载报告。写明它不修改正式任务，未配置标准只会输出条件通过。

在 PROJECT_OVERVIEW 增加运行时文件 `config/acceptance/{criteria,current-plan}.json`、报告命名、与 `RunManager` 的互斥关系、后端重启后当前项需要人工核对的安全原则，以及不影响 Mobile/视频/手动控制的事实。

- [ ] **Step 4: 运行完整自动化验证**

Run:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run test
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run test-offline
./scripts/test-backend.sh
./scripts/test-web.sh
git diff --check
```

Expected: 每个命令 PASS；若既有测试失败，先按 `systematic-debugging` 分离已有失败与本次回归，不能把失败标为通过。

- [ ] **Step 5: 进行本地模拟验收**

用临时正式任务目录创建：小区名带下划线、多个楼栋/单元/楼层、备份文件、JSON 损坏文件和 task group 不一致文件。验证 catalog warning、whole community/building filter、full/sample、相同 seed、标准三种结论、普通 run 冲突、失败恢复、取消、重启中断确认、报告下载。该模拟不连接实车、不调用实际 ROS service。

- [ ] **Step 6: 记录实车验收清单并执行最终选择性提交**

实车前清单必须逐项显示为“待验证”：正式目录权限和只读性、相同路径任务同步行为、每任务 scenario/preflight/ROS service、导航失败后的人工恢复、取消时 STOP/收尾、长计划轨迹资产、报告下载、普通测试与验收互斥、后端重启后不重发未知项。

确认 `git status --short`，仅暂存本功能的新增/修改文件和已批准文档；不得纳入先前手动控制/打包等未提交修改。然后：

```bash
git add autodrive_console/acceptance_catalog.py autodrive_console/acceptance_plan.py \
  autodrive_console/acceptance_orchestrator.py autodrive_console/acceptance_report.py \
  autodrive_console/models.py autodrive_console/run_manager.py web_console.py \
  autodrive_console/web/acceptance-test.html autodrive_console/web/acceptance_test.js \
  autodrive_console/web/acceptance_test.css autodrive_console/web/app_shell.js \
  shared/contracts/task_execution.md README.md PROJECT_OVERVIEW.md \
  docs/superpowers/specs/2026-09-03-acceptance-test-design.md \
  docs/superpowers/plans/2026-09-03-acceptance-test.md tests/test_acceptance.py \
  tests/test_repository_conventions.py tests/test_trajectory_fallback.py
git commit -m "feat: add deployment acceptance plans"
```
