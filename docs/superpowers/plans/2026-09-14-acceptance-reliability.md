# Deployment Acceptance Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent long deployment-acceptance routes from being locally failed by the ordinary test timeout, and archive an acceptance report for every terminal result.

**Architecture:** A plan-scoped child run marks its own service wait as unbounded; explicit operator cancellation and manual attempt failure remain the only early exits. The acceptance event sink writes its existing self-contained report for every terminal sequence status after it has received all completed/cancelled item facts. Existing SVG behaviour remains unchanged: blue is actual position data and yellow dashed is the task's ideal route.

**Tech Stack:** Python 3, pytest, ROS2 service client boundary, existing acceptance HTML report writer.

**Spec:** User request on 2026-09-14; [task execution contract](../../../shared/contracts/task_execution.md).

## Global Constraints

- Do not alter ROS topics, `/start_execute_tasks` request data, vehicle-control boundaries, or trajectory coordinate transforms.
- Ordinary test runs retain the configured `task_execution_timeout_s`; only deployment-acceptance sequences disable this local deadline.
- Cancellation, failed/blocked terminal plans and completed plans all retain their already-known item results and generate one offline HTML/CSV report.
- Do not hide the ideal route or join independent actual trajectory segments; the report legend remains truthful.

---

### Task 1: Make acceptance service waits plan-scoped and cancellable

**Files:**
- Modify: `autodrive_console/run_manager.py`
- Modify: `autodrive_console/ros_executor.py`
- Test: `tests/test_trajectory_fallback.py`

**Interfaces:**
- Consumes: `RunManager.start_sequence()` child `RunRecord` and `RosTaskExecutor.execute(..., timeout_s=...)`.
- Produces: acceptance child executions call `execute(..., timeout_s=0)`; `0` means no local deadline while cancellation and manual failure are still checked every spin.

- [x] **Step 1: Write the failing test**

```python
def test_acceptance_sequence_disables_only_the_local_service_deadline():
    run = manager.start_sequence([case], prepare_trajectory_maps=False)
    wait_until_terminal(run)
    assert executor.received_timeout == 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest -q tests/test_trajectory_fallback.py::TrajectoryFallbackTests::test_acceptance_sequence_disables_only_the_local_service_deadline`

Expected: FAIL because the child currently forwards `task_execution_timeout_s`.

- [x] **Step 3: Write minimal implementation**

```python
child._acceptance_sequence = True
execution_timeout = 0 if getattr(run, "_acceptance_sequence", False) else settings.task_execution_timeout_s
if effective_timeout > 0 and time.monotonic() - started > effective_timeout:
    return False, f"服务调用超时（{effective_timeout:.0f}s）", duration
```

- [x] **Step 4: Run test to verify it passes**

Run: `pixi run python -m pytest -q tests/test_trajectory_fallback.py::TrajectoryFallbackTests::test_acceptance_sequence_disables_only_the_local_service_deadline`

Expected: PASS.

### Task 2: Archive every terminal acceptance plan

**Files:**
- Modify: `autodrive_console/acceptance_orchestrator.py`
- Test: `tests/test_acceptance.py`

**Interfaces:**
- Consumes: the terminal `sequence_finished` event emitted after `RunManager` finalizes attempts.
- Produces: `AcceptancePlan.report_filename` for `completed`, `cancelled`, `blocked`, and `failed` plans.

- [x] **Step 1: Write the failing test**

```python
def test_orchestrator_writes_partial_report_when_sequence_is_cancelled(tmp_path):
    plan = create_plan(orchestrator)
    orchestrator._on_run_event(plan.plan_id, {"type": "sequence_finished", "status": "cancelled"})
    assert orchestrator.current()["report_filename"]
```

- [x] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest -q tests/test_acceptance.py::test_orchestrator_writes_partial_report_when_sequence_is_cancelled`

Expected: FAIL because the current event handler only invokes the report writer for `completed`.

- [x] **Step 3: Write minimal implementation**

```python
if plan.status in {"completed", "cancelled", "blocked", "failed"}:
    report = self.report_writer.write(plan)
    plan.report_filename = report.html_filename
```

- [x] **Step 4: Run test to verify it passes**

Run: `pixi run python -m pytest -q tests/test_acceptance.py::test_orchestrator_writes_partial_report_when_sequence_is_cancelled`

Expected: PASS and the report contains planned/partial/cancelled item states.

### Task 3: Verify trajectory evidence does not duplicate actual paths

**Files:**
- Test: `tests/test_trajectory_integrity.py`

**Interfaces:**
- Consumes: `TrajectorySession._segments` and `render_svg()`.
- Produces: a regression assertion that one actual segment is rendered once while the ideal route remains a distinct dashed evidence layer.

- [x] **Step 1: Add assertion to the existing visualisation test**

```python
assert svg.count('stroke="#168cff" stroke-width="2.5"') == 1
assert svg.count('stroke="#f5c84b" stroke-width="1.35"') == 1
```

- [x] **Step 2: Run the trajectory integrity tests**

Run: `pixi run python -m pytest -q tests/test_trajectory_integrity.py`

Expected: PASS; yellow dashed and blue solid remain deliberately different layers, not duplicate sampled position paths.

### Task 4: Full regression and contract update

**Files:**
- Modify: `shared/contracts/task_execution.md`
- Test: `scripts/test-backend.sh`

- [x] **Step 1: State the acceptance-specific wait/report rules in the existing contract**

```markdown
Deployment acceptance has no local task-service deadline; cancellation/manual failure remain available. Every terminal acceptance plan writes an offline report, including partial and cancelled plans.
```

- [x] **Step 2: Run final checks**

Run: `scripts/test-backend.sh && git diff --check`

Expected: all backend tests pass and no whitespace errors are reported.
