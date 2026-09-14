# 部署验收 Supervisor 运行准备状态 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在部署验收开始首个任务前，让已选择的 Supervisor 依赖编排以持久化阶段状态展示给现场人员。

**Architecture:** `RobotGateway` 产生只读阶段快照，`RunManager` 通过现有 `preflight_progress` 事件传递，`AcceptanceOrchestrator` 验证并持久化到冻结计划。PC Web 只渲染公开快照，未启用依赖编排时不创建状态区。

**Tech Stack:** Python 3.10、pytest、原生 ES modules、HTML/CSS、Vite。

**Spec:** `docs/superpowers/specs/2026-09-10-acceptance-supervisor-preparation-design.md`

## Global Constraints

- 浏览器绝不获取或下发 Supervisor 命令、ROS Topic、脚本路径或提权配置。
- 状态节点必须来自创建计划时冻结的 `dependency_plan.steps`，不采纳浏览器数据。
- Mobile 不是消费者；契约只能声明 PC Web。
- 未勾选依赖编排时 Supervisor 状态区必须完全隐藏。
- 保持已有部署验收视觉风格、键盘顺序和响应式布局。

---

### Task 1: 安全且可持久化的依赖阶段状态

**Files:**
- Modify: `autodrive_console/acceptance_plan.py`
- Modify: `autodrive_console/acceptance_orchestrator.py`
- Test: `tests/test_acceptance.py`

**Interfaces:**
- Produces: `normalize_execution_preflight_status(value, *, preflight)` 接受可选 `dependency_progress`。
- Produces: `AcceptancePlan.to_public_dict()` 在依赖冻结时返回经验证的阶段/节点只读快照。

- [x] **Step 1: Write the failing tests**

```python
def test_orchestrator_persists_frozen_dependency_stage_progress(tmp_path):
    orchestrator = make_orchestrator_with_dependency_plan(tmp_path)
    plan = orchestrator.create_plan(dependency_plan_request())
    orchestrator._on_run_event(plan["plan_id"], {
        "type": "preflight_progress",
        "preflight": {
            "state": "restarting_dependencies",
            "message": "正在重启第 1 阶段依赖",
            "dependency_progress": {
                "stages": [{"index": 1, "state": "waiting_stable", "nodes": [{"name": "MODULES:209-lightning", "status": "STARTING"}]}]
            },
        },
    })
    assert orchestrator.current()["execution_preflight_status"]["dependency_progress"]["stages"][0]["nodes"][0]["status"] == "STARTING"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pixi run test tests/test_acceptance.py -q`

Expected: failure because the existing status schema rejects `dependency_progress`.

- [x] **Step 3: Implement minimal normalization and persistence**

```python
def normalize_dependency_progress(value, *, preflight):
    # derive the allowed node names and stage indices only from frozen preflight
    # return None when dependency_plan.enabled is false
    ...
```

Extend only the status dictionary, retain the existing top-level state/message/timestamp and normalize schema-3 legacy values without a progress field to `None`.

- [x] **Step 4: Run targeted tests**

Run: `pixi run test tests/test_acceptance.py -q`

Expected: all acceptance tests pass.

### Task 2: 受控阶段快照事件

**Files:**
- Modify: `autodrive_console/robot_gateway.py`
- Modify: `autodrive_console/run_manager.py`
- Test: `tests/test_supervisor_monitoring.py`
- Test: `tests/test_trajectory_fallback.py`

**Interfaces:**
- Consumes: frozen `RobotSettings.dependency_plan`.
- Produces: `RobotGateway.restart_configured_dependencies(progress_callback=...)` snapshots with only stage index/state/names/current Supervisor status.
- Produces: `RunManager._emit_preflight_progress(..., dependency_progress=...)` carrying snapshots to the acceptance event callback.

- [x] **Step 1: Write the failing tests**

```python
def test_dependency_restart_reports_stage_node_states():
    updates = []
    gateway = RobotGateway(settings_with_two_stages())
    gateway.restart_configured_dependencies(progress_callback=updates.append)
    assert updates[0]["stages"][0]["state"] == "restarting"
    assert updates[-1]["stages"][0]["state"] == "ready"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pixi run test tests/test_supervisor_monitoring.py -q`

Expected: failure because no progress callback exists.

- [x] **Step 3: Implement snapshot publishing**

Extend the existing gateway restart path without changing restart/start selection, the five-sample `RUNNING` gate, cancellation semantics, or the restart activity lock. Snapshot before control, after accepted control, on every status poll, during optional settle, and on ready/failure. Thread that optional callback through the existing `RunManager` preflight progress callback.

- [x] **Step 4: Run targeted tests**

Run: `pixi run test tests/test_supervisor_monitoring.py tests/test_trajectory_fallback.py -q`

Expected: all targeted tests pass and existing “restart once per sequence” coverage remains green.

### Task 3: 验收页面的条件状态区

**Files:**
- Modify: `autodrive_console/web/acceptance-test.html`
- Modify: `autodrive_console/web/acceptance_test.js`
- Modify: `autodrive_console/web/acceptance_test.css`
- Test: `frontend/test/acceptance-preparation.test.mjs`

**Interfaces:**
- Consumes: public `execution_preflight.dependency_plan_enabled` and public `execution_preflight_status.dependency_progress`.
- Produces: `renderDependencyPreparation(plan)` with no visible output unless frozen dependencies are enabled.

- [x] **Step 1: Write the failing UI model test**

```js
test("dependency preparation is hidden without a frozen dependency plan", () => {
  assert.equal(shouldRenderDependencyPreparation({ execution_preflight: { dependency_plan_enabled: false } }), false);
});
test("dependency preparation names the current stage and current Supervisor state", () => {
  assert.deepEqual(dependencyPreparationView(frozenPlanWithStartingNode), {
    visible: true,
    stages: [{ index: 1, stateLabel: "等待稳定 RUNNING", nodes: [{ name: "MODULES:209-lightning", status: "STARTING" }] }],
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && node --test test/acceptance-preparation.test.mjs`

Expected: module-not-found failure for the new pure rendering helper.

- [x] **Step 3: Implement the smallest presentation boundary**

Create a pure `acceptance_preparation.js` helper for visibility and status labels. Use it from `acceptance_test.js`; render a semantic list below existing runtime status, preserve DOM order, use `hidden`, and add no new control. Keep the existing card vocabulary and only use semantic status colors. At <=900px stack stage rows without changing label/node order.

- [x] **Step 4: Run targeted Web tests**

Run: `cd frontend && node --test test/acceptance-preparation.test.mjs test/dev-preview-proxy.test.mjs`

Expected: UI model and legacy preview proxy tests pass.

### Task 4: 契约与全量验证

**Files:**
- Modify: `shared/contracts/task_execution.md`
- Verify: `scripts/test-backend.sh`
- Verify: `scripts/test-web.sh`

- [x] **Step 1: Update the Existing contract**

Document the additive public `dependency_progress` schema, exact state lists, PC-only consumer, legacy `null` compatibility, and the fact that the browser receives no control data.

- [x] **Step 2: Run the full verification commands**

Run: `scripts/test-backend.sh && scripts/test-web.sh`

Expected: Backend and Web suites pass.

- [x] **Step 3: Inspect the rendered page**

Verify desktop and 390px-wide renderings: disabled choice hides the state region; enabled frozen plan shows stage order, STARTING/RUNNING state, ready/blocked colors, long node names and no overflow.

- [x] **Step 4: Run the UI detector**

Run: `node /home/bob/.codex/skills/impeccable/scripts/detect.mjs --json autodrive_console/web/acceptance-test.html autodrive_console/web/acceptance_test.js autodrive_console/web/acceptance_test.css`

Expected: no unexplained findings.
