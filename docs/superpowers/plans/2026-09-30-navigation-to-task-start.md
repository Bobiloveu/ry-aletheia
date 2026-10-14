# 前往任务起点 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 PC 实时观测页安全地选择同图测试/车端任务起点，并通过 Nav2 `/navigate_to_pose` 将空闲车辆驶向该点。

**Architecture:** Backend 以新的只读起点目录和单操作导航控制器拥有任务解析、地图核验、车辆互斥与 ROS2 Action 生命周期；浏览器只消费受控状态与不透明候选 ID。现有 `VehicleControlController`、`RunManager` 和手动重定位将通过显式 guard 双向互斥，防止导航 Goal 与测试、手动或重定位争用车辆。

**Tech Stack:** Python 3.10、rclpy/`nav2_msgs.action.NavigateToPose`、既有 HTTP server、ES modules、PixiJS 实时观测页、Node test、pytest。

**Spec:** `docs/superpowers/specs/2026-09-30-navigation-to-task-start-design.md`

## Global Constraints

- 浏览器和 Mobile 绝不直连 ROS、发布 `/goal_pose`、Twist 或自行指定坐标、地图路径、Action 名称、行为树和速度。
- 只使用实车已经发现的 `/navigate_to_pose`（`nav2_msgs/action/NavigateToPose`），`frame_id` 固定为 `map`；不使用 `/goal_pose`。
- 只读 `settings.task_directory` 及其同级 `multi_tasks/`；不创建、修改、覆盖、重命名或删除任务文件。
- 单点取 `subtasks[0].waypoints[0]`；多点取正向片段根对象的 `waypoints[0]`，忽略 `_r.json`。
- 当前地图、控制源、急停、定位、手动/重定位占用和活动测试任一不满足时 fail closed；不自动切图、跨楼层、过电梯、重试或切换到 `miniapp`。
- 单次 Action 最长 300 秒；取消只能调用 Nav2 cancel，不发布 Twist 或伪造停止结果。
- PC-only；Mobile 不新增入口或 API 消费。
- 当前工作区有用户既有改动：只编辑本计划列出的文件，不暂存/提交无关内容，也不自行打包、部署或发送实车 Goal。

---

## File Structure

| 文件 | 职责 |
| --- | --- |
| `autodrive_console/task_start_catalog.py` | 受限根目录的只读任务首点扫描、严格解析、去重与不透明候选解析。 |
| `autodrive_console/task_start_navigation.py` | Nav2 Action 生命周期、安全 gates、操作锁、300 秒超时、取消与受控快照。 |
| `autodrive_console/observation.py` | 将候选任务 YAML 与活动 map_server/OccupancyGrid 元数据做严格同图核验。 |
| `autodrive_console/vehicle_control.py` | 在导航操作期间拒绝新手动会话和手动重定位占用。 |
| `autodrive_console/run_manager.py` | 在导航操作期间拒绝新建普通/验收运行。 |
| `web_console.py` | 构造控制器、接入 GET/POST API、统一 HTTP 错误映射。 |
| `frontend/src/taskStartNavigationState.js` | 纯前端状态/候选显示推导，便于不依赖 DOM 的测试。 |
| `frontend/live-observation.html`、`frontend/src/liveObservation.js`、`frontend/src/liveObservation.css` | PC 地图浮层、确认/取消与主题/窄屏呈现。 |
| `shared/contracts/{realtime_observation,robot_control,task_execution}.md` | API、ROS 所有权、安全互斥、消费者和验证影响。 |

### Task 1: 先更新跨端契约与 API 状态表

**Files:**
- Modify: `shared/contracts/realtime_observation.md`
- Modify: `shared/contracts/robot_control.md`
- Modify: `shared/contracts/task_execution.md`

**Interfaces:**
- Produces: PC-only `/api/observation/task-start-navigation` snapshot and begin/cancel contract; `idle|checking|navigating|cancelling|succeeded|failed|cancelled` state set.
- Produces: explicit backend-only `/navigate_to_pose` ownership and RunManager/vehicle-control mutual-exclusion rules.

- [ ] **Step 1: Add the failing contract-consumer assertions**

Add to `tests/test_offline_modules.py` assertions that all three contracts name the endpoint/Action, map mismatch refusal, 300-second timeout, Mobile non-consumer status, and mutual exclusion. The test must fail because the new terms are not documented.

```python
def test_task_start_navigation_contracts_define_pc_only_safe_nav2_boundary() -> None:
    observation = Path("shared/contracts/realtime_observation.md").read_text(encoding="utf-8")
    control = Path("shared/contracts/robot_control.md").read_text(encoding="utf-8")
    execution = Path("shared/contracts/task_execution.md").read_text(encoding="utf-8")
    assert "/api/observation/task-start-navigation" in observation
    assert "navigate_to_pose" in control
    assert "300" in observation
    assert "Mobile 不是" in observation
    assert "前往任务起点" in execution
```

- [ ] **Step 2: Run the targeted test to verify RED**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_offline_modules.py -k task_start_navigation_contracts -v`

Expected: FAIL because the three Existing contracts do not yet name the operation.

- [ ] **Step 3: Document the exact additive contract**

In `realtime_observation.md`, add the GET/POST table, request shape, public snapshot fields, 16 KiB limit, opaque IDs, two sources, map recheck and terminal states. In `robot_control.md`, state that only Backend owns `NavigateToPose`, requires confirmed `navigation`, and blocks manual/relocalization during operation. In `task_execution.md`, state the bidirectional 409 interlock and that no task is paused, replaced or resent.

- [ ] **Step 4: Run the targeted test to verify GREEN**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_offline_modules.py -k task_start_navigation_contracts -v`

Expected: PASS.

### Task 2: Build the read-only task-start catalog

**Files:**
- Create: `autodrive_console/task_start_catalog.py`
- Create: `tests/test_task_start_catalog.py`

**Interfaces:**
- Consumes: a test-case directory, `settings.task_directory`, and sibling `multi_tasks/` roots.
- Produces: `TaskStartCatalog.scan() -> TaskStartSnapshot`; `TaskStartCatalog.resolve(source: str, candidate_id: str) -> TaskStartCandidate`.
- Produces: immutable `TaskStartCandidate(id, source, label, map_path, x, y, yaw, member_count, member_paths, fingerprint)` without serializing `map_path` or `member_paths` to clients.

- [ ] **Step 1: Write failing catalog tests**

Create fixtures for: a complete single task group, a direct multi forward fragment, an `_r.json` fragment, malformed JSON, a non-finite coordinate, a zero-norm quaternion, and two equivalent forward files. Assert only valid forward first points appear, duplicate poses form one candidate, and `resolve()` rejects a stale fingerprint.

```python
def test_scan_groups_matching_forward_task_starts_and_excludes_return_fragments(tmp_path: Path) -> None:
    snapshot = TaskStartCatalog(single_root, multi_root).scan()
    starts = [item for item in snapshot.candidates if item.source == "robot_task"]
    assert [(item.member_count, item.x, item.y) for item in starts] == [(2, -6.0, 5.0)]

def test_resolve_rejects_candidate_when_representative_file_changed(tmp_path: Path) -> None:
    catalog = TaskStartCatalog(single_root, multi_root)
    candidate = catalog.scan().candidates[0]
    candidate.member_paths[0].write_text("{}", encoding="utf-8")
    with pytest.raises(TaskStartCatalogError, match="任务文件已变更"):
        catalog.resolve(candidate.source, candidate.id)
```

- [ ] **Step 2: Run the catalog test to verify RED**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_task_start_catalog.py -v`

Expected: FAIL with `ModuleNotFoundError` for `autodrive_console.task_start_catalog`.

- [ ] **Step 3: Implement strict parser and immutable snapshot**

Implement a single parser that accepts only a dict/list structure stated in the spec, finite `position.x/y`, and a finite, non-zero quaternion transformed via `atan2` to normalized yaw. Resolve files with `Path.resolve()` and reject paths outside their respective roots. Sort lexically; skip direct return fragments; group only a canonical map path plus normalized `x/y/yaw`; calculate a SHA-256 fingerprint from every grouped file. Candidate IDs must be SHA-256-derived opaque strings, never paths or filenames.

```python
@dataclass(frozen=True)
class TaskStartCandidate:
    id: str
    source: str
    label: str
    map_path: Path
    x: float
    y: float
    yaw: float
    member_count: int
    member_paths: tuple[Path, ...]
    fingerprint: str

class TaskStartCatalog:
    def scan(self) -> TaskStartSnapshot: ...
    def resolve(self, source: str, candidate_id: str) -> TaskStartCandidate: ...
```

- [ ] **Step 4: Run the catalog test to verify GREEN**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_task_start_catalog.py -v`

Expected: PASS; no fixture file is altered by production code.

### Task 3: Add strict active-map verification

**Files:**
- Modify: `autodrive_console/observation.py`
- Modify: `tests/test_offline_modules.py`

**Interfaces:**
- Consumes: candidate `map_path`, active `/map_server` YAML, active snapshot and cached map metadata.
- Produces: `ObservationManager.verify_active_task_map(candidate_map: Path) -> tuple[bool, str]`.

- [ ] **Step 1: Write failing map-verification tests**

Cover canonical same YAML plus matching resolution/dimensions/origin, same file with stale metadata, a different YAML, unavailable map_server YAML, and no active snapshot.

```python
def test_task_start_map_requires_current_yaml_and_live_snapshot_metadata(tmp_path: Path) -> None:
    manager = observation_with_active_map(tmp_path, yaml_path=active_yaml)
    assert manager.verify_active_task_map(active_yaml) == (True, "当前地图匹配")
    assert manager.verify_active_task_map(other_yaml)[0] is False
```

- [ ] **Step 2: Run targeted map tests to verify RED**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_offline_modules.py -k task_start_map -v`

Expected: FAIL because `verify_active_task_map` does not exist.

- [ ] **Step 3: Implement fail-closed verification using existing map_server path machinery**

Reuse `_map_server_yaml_path()` and the existing strict `_map_server_asset()` metadata rules. Require the resolved candidate YAML to equal the active YAML and require the active cached asset to agree with the current OccupancyGrid resolution, width, height and origin. Return only public reasons such as `当前地图不匹配` and `当前地图尚未确认`; never return paths.

- [ ] **Step 4: Run targeted map tests to verify GREEN**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_offline_modules.py -k task_start_map -v`

Expected: PASS.

### Task 4: Implement Nav2 action controller and all safety interlocks

**Files:**
- Create: `autodrive_console/task_start_navigation.py`
- Modify: `autodrive_console/vehicle_control.py`
- Modify: `autodrive_console/run_manager.py`
- Create: `tests/test_task_start_navigation.py`
- Modify: `tests/test_vehicle_control.py`
- Modify: `tests/test_run_manager.py`

**Interfaces:**
- Consumes: `TaskStartCatalog`, `ObservationManager.verify_active_task_map`, `VehicleControlController.status`, `LocalizationStatusMonitor.status`, and active-run guard.
- Produces: `TaskStartNavigationController.status()`, `begin(source, candidate_id)`, `cancel()`, and `blocks_runs()`.
- Produces: `VehicleControlController.set_task_start_navigation_guard(guard)` and `RunManager.set_task_start_navigation_guard(guard)`.

- [ ] **Step 1: Write failing controller and interlock tests**

Use injected action transport fakes; never use a real rclpy executor in unit tests. Cover every beginning gate, map recheck immediately before send, `map` frame goal quaternion, accepted-vs-succeeded distinction, feedback, rejected goal, Nav2 failure, 300-second timeout, cancel acknowledgement, safety loss cancellation, log redaction, action singleton, and run/manual/relocalization conflicts.

```python
def test_begin_sends_one_map_goal_only_after_all_safety_gates() -> None:
    controller = controller_with(transport=AcceptedThenSucceeded())
    snapshot = controller.begin("case", case_candidate_id)
    assert snapshot["phase"] == "navigating"
    assert transport.goals == [pytest.approx({"frame_id": "map", "x": -6.0, "y": 5.0, "yaw": 1.2})]

def test_active_navigation_blocks_new_run_and_manual_or_relocalization_sessions() -> None:
    controller = controller_with(transport=AcceptedNeverFinishes())
    controller.begin("robot_task", candidate_id)
    with pytest.raises(RunConflict): runs.start(case, 1, 0)
    with pytest.raises(VehicleControlConflict): vehicle.begin_manual_session()
```

- [ ] **Step 2: Run controller tests to verify RED**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_task_start_navigation.py tests/test_vehicle_control.py tests/test_run_manager.py -k "task_start or navigation" -v`

Expected: FAIL because the controller and guard setters do not exist.

- [ ] **Step 3: Implement controller, ROS transport, and bidirectional guards**

Implement a controller-owned daemon worker and a small injectable transport boundary. The production transport imports `rclpy`, `ActionClient`, `NavigateToPose` and `PoseStamped` inside its method, waits boundedly for `/navigate_to_pose`, stamps a `map` pose and monitors result/future callbacks. The controller owns only one Goal Handle under an `RLock`; all terminal paths clear it. `cancel()` calls the handle cancellation future, never VehicleControl Twist methods.

```python
class TaskStartNavigationController:
    ACTIVE_PHASES = frozenset({"checking", "navigating", "cancelling"})
    def status(self) -> dict[str, object]: ...
    def begin(self, source: str, candidate_id: str) -> dict[str, object]: ...
    def cancel(self) -> dict[str, object]: ...
    def blocks_runs(self) -> bool:
        return self._phase in self.ACTIVE_PHASES
```

Before creation and immediately before Action send, require: no active run, no manual sessions, relocalization hold idle, confirmed `navigation`, `normal` emergency stop, `normal` localization, valid same-map candidate and available server. On safety state loss or 300 seconds, request cancellation once and enter `failed` if a terminal Nav2 result is not available. `begin_manual_session()` and `begin_relocalization_hold()` must reject while `blocks_runs()` is true; `RunManager.start()` and `start_sequence()` must reject while the same guard is true.

- [ ] **Step 4: Run controller/interlock tests to verify GREEN**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_task_start_navigation.py tests/test_vehicle_control.py tests/test_run_manager.py -k "task_start or navigation" -v`

Expected: PASS.

### Task 5: Wire the server-owned API and tool logging

**Files:**
- Modify: `web_console.py`
- Modify: `tests/test_offline_modules.py`
- Modify: `tests/test_vehicle_control.py` if handler fixtures require controller setup

**Interfaces:**
- Consumes: global `CASES`, `SETTINGS`, `OBSERVATION`, `LOCALIZATION_STATUS`, `VEHICLE_CONTROL`, `RUNS`, and `TaskStartNavigationController`.
- Produces: `GET /api/observation/task-start-navigation`; `POST .../begin`; `POST .../cancel`.

- [ ] **Step 1: Write failing handler tests**

Test `GET` contains no file paths or raw coordinates; `begin` accepts only `{source,id}`, maps safety conflict to 409, unavailable ROS to 503, malformed bodies to 400, and terminal snapshots to 200 while active ones return 202.

```python
def test_task_start_navigation_begin_rejects_client_pose_and_keeps_paths_private(client) -> None:
    response = client.post("/api/observation/task-start-navigation/begin", json={
        "source": "case", "id": "opaque", "x": 9,
    })
    assert response.status_code == 400
    assert "/opt/ry/" not in response.text
```

- [ ] **Step 2: Run handler tests to verify RED**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_offline_modules.py -k task_start_navigation_api -v`

Expected: FAIL because routes and controller wiring are absent.

- [ ] **Step 3: Add routing, dependency wiring and public error mapping**

Construct one controller after existing service globals, give it the bidirectional guards, and route it in `_observation_action`. Validate an object body of at most 16 KiB and exactly the two `begin` fields. Log source category, public label, map result, phase and public reason through the existing tool logger; never interpolate a candidate path, payload or exception traceback into a client response or audit record.

- [ ] **Step 4: Run handler tests to verify GREEN**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_offline_modules.py -k task_start_navigation_api -v`

Expected: PASS.

### Task 6: Add PC-only floating control and state presentation

**Files:**
- Create: `frontend/src/taskStartNavigationState.js`
- Create: `frontend/test/task-start-navigation-state.test.mjs`
- Modify: `frontend/live-observation.html`
- Modify: `frontend/src/liveObservation.js`
- Modify: `frontend/src/liveObservation.css`
- Modify: `frontend/test/live-observation-map.test.mjs`

**Interfaces:**
- Consumes: GET snapshot and begin/cancel endpoints from Task 5.
- Produces: `taskStartNavigationView(snapshot, selectedSource, selectedId)` pure view model; PC-only `taskStartNavigationControl` overlay.

- [ ] **Step 1: Write failing pure-state and page tests**

Test source choices, disabled copy for map mismatch and busy runs, confirm-before-begin state, active cancel visibility, terminal display and no raw map paths. Extend the live observation page test to require a separate overlay, exclusive `announceMapOverlayOpen("task-start-navigation")`, and an explicit mobile hide rule.

```js
test("same-map candidate becomes confirmable while a mismatched candidate remains disabled", () => {
  assert.equal(taskStartNavigationView(readySnapshot, "case", "same").canConfirm, true);
  assert.equal(taskStartNavigationView(mismatchedSnapshot, "case", "other").canConfirm, false);
  assert.match(taskStartNavigationView(mismatchedSnapshot, "case", "other").detail, /另一张地图/);
});
```

- [ ] **Step 2: Run frontend tests to verify RED**

Run: `node --test frontend/test/task-start-navigation-state.test.mjs frontend/test/live-observation-map.test.mjs`

Expected: FAIL because the state module, overlay and API use do not exist.

- [ ] **Step 3: Implement the compact overlay and polling**

Add `taskStartNavigationControl` as a distinct desktop map overlay, not a child of the layer/relocalization controls. It contains source tabs, a deduplicated candidate selector, a public match/rejection detail, an in-panel confirmation state, one begin button and an active cancel button. Refresh its snapshot alongside existing observation status polling; dispatch overlay-open events so layers, relocalization and navigation panels close one another. Use only returned labels/opaque IDs and never put map path or pose fields in the DOM. Hide the entire control with `html.mobile-console .task-start-navigation-control { display:none; }`.

Keep the surface compact and translucent, preserve map interaction/viewport state, provide deep/light theme values, and make `prefers-reduced-motion` use no perpetual animation.

- [ ] **Step 4: Run frontend tests to verify GREEN**

Run: `node --test frontend/test/task-start-navigation-state.test.mjs frontend/test/live-observation-map.test.mjs`

Expected: PASS.

### Task 7: Verify integrated behavior without moving a real vehicle

**Files:**
- Modify: only files needed to correct failures found in this task.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified source and contracts; no package, deployment or robot movement.

- [ ] **Step 1: Run backend verification**

Run: `scripts/test-backend.sh && pixi run test-offline`

Expected: all existing and new backend/offline tests pass.

- [ ] **Step 2: Run Web verification**

Run: `pixi run frontend-check && git diff --check`

Expected: frontend tests/build and whitespace checks pass; generated `web-vue` artifacts remain untracked/unstaged.

- [ ] **Step 3: Inspect the PC UI locally**

Run: `cd frontend && npm run dev -- --port 5173`

Use `agent-browser` to inspect the real-time page in dark/light desktop, 390 px narrow layout and reduced-motion. Assert the navigation overlay is absent in mobile mode, map mismatch cannot reach confirmation, and the control does not alter map position. Stop the temporary dev server after inspection.

- [ ] **Step 4: Record the real-vehicle handoff rather than moving the robot**

Record that `/navigate_to_pose` was discovered read-only in ROS domain 66. Do not send a real Goal. Ask the operator to choose a clear area before validating one same-map goal, one map-mismatch refusal and one cancellation on the vehicle.

## Plan Self-Review

- Spec coverage: Task 2 covers both task formats/read-only deduplication; Task 3 covers strict map identity; Task 4 covers Nav2, timeout, cancel and all safety interlocks; Task 5 covers API/logging; Task 6 covers the PC presentation; Task 1 covers all contract consumers; Task 7 covers required checks and safe real-car handoff.
- Placeholder scan: no outstanding markers, deferred behavior, or unspecified error handling remains.
- Type consistency: `TaskStartCatalog.resolve(source, candidate_id)`, `ObservationManager.verify_active_task_map(path)`, `TaskStartNavigationController.begin(source, candidate_id)`, `cancel()` and `blocks_runs()` are defined before their consuming tasks.
