# 部署验收自动返程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让已选择自动返程的部署验收任务在正式状态码 `103` 到达时安全发布一次既有返程信号。

**Architecture:** 验收计划将一个默认关闭的布尔策略冻结为 schema 4；`AcceptanceOrchestrator` 只验证和转交该策略。`RunManager` 仅为开启策略的验收序列拥有短生命周期 ROS bridge，bridge 用纯 Python gate 确保每个子任务仅在真实服务调用窗口处理首个 `103`；PC Web 仅显示和提交该冻结选择。

**Tech Stack:** Python dataclasses/threading/rclpy、ROS2 `master_interfaces/TaskStatus` 与 `std_msgs/Bool`、原生 ES modules、Node/Pytest。

**Spec:** `docs/superpowers/specs/2026-09-15-acceptance-auto-return-design.md`

## Global Constraints

- 仅 `status_code == "103"` 可触发，固定发布 `/start_return` 的 `Bool(data=true)`。
- 不允许浏览器直接发布 ROS、选择 Topic 或提交命令内容。
- 默认关闭；旧 schema 计划读取时必须为关闭；普通测试没有 bridge。
- 仅首个 armed `103` 触发；结束后必须释放 ROS node、executor 和线程。
- UI 保持既有可选运行准备折叠区的布局与主题；不增加独立控制入口。
- 同步更新 Existing 契约；只运行 Backend/Web 的受影响检查。

---

### Task 1: 冻结并公开自动返程策略

**Files:**
- Modify: `autodrive_console/acceptance_plan.py`
- Modify: `autodrive_console/acceptance_orchestrator.py`
- Test: `tests/test_acceptance.py`

**Interfaces:**
- Consumes: `POST /api/acceptance/plans` field `use_automatic_return: bool`.
- Produces: frozen `execution_preflight.automatic_return: bool` and public `execution_preflight.automatic_return_enabled: bool`.

- [x] **Step 1: Write failing tests**

```python
def test_orchestrator_freezes_automatic_return_and_defaults_legacy_plans_off(tmp_path):
    task_dir = tmp_path / "tasks"
    catalog_snapshot_for_plan(task_dir)
    plan = make_orchestrator(task_dir, tmp_path / "state").create_plan({
        "scope_type": "community", "community": "园区_A", "mode": "full",
        "use_automatic_return": True,
    })
    assert plan["execution_preflight"]["automatic_return_enabled"] is True

    legacy_plan = AcceptancePlanFactory.create(
        AcceptanceTaskCatalog(task_dir).scan(), scope_type="community", community="园区_A",
        building=None, unit=None, mode="full", sample_size=None, random_seed=1,
        criteria=AcceptanceCriteria.empty(),
    )
    legacy = legacy_plan.to_storage_dict()
    legacy["schema"] = 3
    legacy["execution_preflight"].pop("automatic_return")
    assert AcceptancePlan.from_storage_dict(legacy).execution_preflight["automatic_return"] is False
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `pixi run test tests/test_acceptance.py -k automatic_return -q`

Expected: FAIL because the creation field and frozen/public plan fields do not exist.

- [x] **Step 3: Implement the minimal schema-4 compatibility path**

```python
def default_execution_preflight() -> dict[str, Any]:
    return {"scenario_profile_id": None, "scenario_profile_name": None,
            "dependency_plan": {"enabled": False, "steps": []},
            "automatic_return": False}

def public_execution_preflight(value: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_execution_preflight(value)
    return {"scenario_profile_id": normalized["scenario_profile_id"],
            "scenario_profile_name": normalized["scenario_profile_name"],
            "dependency_plan_enabled": normalized["dependency_plan"]["enabled"],
            "dependency_stage_count": len(normalized["dependency_plan"]["steps"]),
            "dependency_node_count": sum(len(step["nodes"]) for step in normalized["dependency_plan"]["steps"]),
            "automatic_return_enabled": normalized["automatic_return"]}
```

Accept schema 1–3 shapes without this field and normalize to `False`; write new plans as schema 4. Add `use_automatic_return` to the accepted creation payload, reject non-bools, and freeze it without accepting arbitrary ROS data.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `pixi run test tests/test_acceptance.py -k automatic_return -q`

Expected: PASS.

### Task 2: 用一次性 gate 和短生命周期 ROS bridge 受控发布返程信号

**Files:**
- Create: `autodrive_console/return_signal.py`
- Modify: `autodrive_console/run_manager.py`
- Test: `tests/test_return_signal.py`
- Test: `tests/test_trajectory_fallback.py`

**Interfaces:**
- Consumes: status code strings and `automatic_return: bool` in the frozen sequence context.
- Produces: `ReturnSignalGate.arm(item_index)`, `ReturnSignalGate.accept(status_code) -> bool`, and `RosReturnSignalBridge.start()/arm(item_index)/close()`.

- [x] **Step 1: Write failing gate and lifecycle tests**

```python
def test_return_gate_sends_once_only_for_the_armed_waiting_return_code():
    gate = ReturnSignalGate()
    gate.arm(1)
    assert gate.accept("403") is False
    assert gate.accept("103") is True
    assert gate.accept("103") is False
    gate.arm(2)
    assert gate.accept("103") is True
```

```python
def test_disabled_acceptance_sequence_never_constructs_a_return_signal_bridge():
    class NeverConstructed:
        def __call__(self):
            raise AssertionError("关闭自动返程时不得创建 ROS bridge")
    case = TestCase("case", "case.json", "任务", TaskParameters("园区", 1, 1, 1, 101), "unused.json")
    manager = RunManager(Path(tempfile.mkdtemp()), _Executor(), _Settings(), return_signal_factory=NeverConstructed())
    run = manager.start_sequence([case], automatic_return=False)
    wait_for_terminal(run)
    assert run.status == "completed"
```

- [x] **Step 2: Run focused tests and verify RED**

Run: `pixi run test tests/test_return_signal.py tests/test_trajectory_fallback.py -k 'return_signal or automatic_return' -q`

Expected: FAIL because the bridge and sequence argument do not exist.

- [ ] **Step 3: Implement the smallest controlled bridge**

```python
class ReturnSignalGate:
    WAITING_RETURN_CODE = "103"
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._armed_item: int | None = None
        self._sent_for_item: int | None = None

    def arm(self, item_index: int) -> None:
        with self._lock:
            self._armed_item = item_index

    def accept(self, status_code: object) -> bool:
        with self._lock:
            if str(status_code).strip() != self.WAITING_RETURN_CODE or self._armed_item is None:
                return False
            if self._sent_for_item == self._armed_item:
                return False
            self._sent_for_item = self._armed_item
            return True

class RosReturnSignalBridge:
    def start(self) -> None:
        import rclpy
        from master_interfaces.msg import TaskStatus
        from std_msgs.msg import Bool
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        if not rclpy.ok():
            rclpy.init()
        node = rclpy.create_node("ry_aletheia_acceptance_return_signal")
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.VOLATILE)
        self._publisher = node.create_publisher(Bool, "/start_return", qos)
        node.create_subscription(TaskStatus, "/task_status", self._on_task_status, qos)
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(node)
        self._node = node
        self._thread = threading.Thread(target=self._executor.spin, daemon=True)
        self._thread.start()

    def arm(self, item_index: int) -> None:
        self._gate.arm(item_index)

    def close(self) -> None:
        executor, thread, node = self._executor, self._thread, self._node
        self._executor = self._thread = self._node = None
        if executor is not None:
            executor.shutdown()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if node is not None:
            node.destroy_node()
```

The bridge creates a reliable/volatile subscription to `/task_status` and a reliable/volatile publisher on `/start_return`; only its callback publishes `Bool(data=True)` when `gate.accept()` returns true. `RunManager.start_sequence()` derives the option only from frozen `execution_preflight.automatic_return`, starts the bridge synchronously only when that value is `True`, arms it immediately before every child service call, disarms it when that call returns, and closes it in `_run_sequence` `finally`. Initialization failure raises before any execution thread starts.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `pixi run test tests/test_return_signal.py tests/test_trajectory_fallback.py -k 'return_signal or automatic_return' -q`

Expected: PASS.

### Task 3: 扩展验收页面、契约与验证

**Files:**
- Modify: `autodrive_console/web/acceptance-test.html`
- Modify: `autodrive_console/web/acceptance_test.js`
- Modify: `frontend/test/legacy-app-module.test.mjs` or focused acceptance Web test
- Modify: `shared/contracts/task_execution.md`

**Interfaces:**
- Consumes: `execution_preflight.automatic_return_enabled` and page-local checkbox `acceptanceAutomaticReturn`.
- Produces: creation payload `use_automatic_return: boolean` and frozen summary text.

- [x] **Step 1: Write a failing Web test**

```js
test("acceptance page preserves the frozen automatic-return selection in its request payload", async () => {
  const payload = collectAcceptancePlanPayload({ automaticReturn: true });
  assert.equal(payload.use_automatic_return, true);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test frontend/test/acceptance-auto-return.test.mjs`

Expected: FAIL because the payload helper and checkbox state do not exist.

- [x] **Step 3: Implement restrained UI and contract documentation**

Add an `自动返程` checkbox inside `#optionalPreparation` with the approved explanatory copy. Store it in the local draft, include it in plan creation, use the frozen public value when the plan is shared/locked, and append `自动返程：启用/不启用` to the existing frozen summary. Update the Existing deployment-acceptance contract with exact trigger, one-shot behavior, fixed ROS boundary, PC-only consumer, schema compatibility and Backend/Web checks.

- [x] **Step 4: Run focused test and verify GREEN**

Run: `node --test frontend/test/acceptance-auto-return.test.mjs`

Expected: PASS.

- [ ] **Step 5: Run required verification**

Run: `./scripts/test-backend.sh && ./scripts/test-web.sh && git diff --check`

Expected: backend and web checks pass, and the diff has no whitespace errors.
