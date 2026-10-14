# 当前地图任务起终点 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 PC 实时地图上可靠补画虚拟墙，并以独立图层展示当前地图严格匹配的车端任务起点和终点，支持右键后受控前往。

**Architecture:** 前端对未确认墙的已加载地图调用既有 `live-layers` 补偿 API，并按地图 signature 有界重试。Backend 以后台 `CurrentMapTaskPointIndex` 建立任务文件到地图起终点的只读内存索引；状态端点只返回当前已确认地图的脱敏点位，导航端点只接受不透明点位 ID 并在发 Nav2 Goal 前再次验证文件、地图与安全状态。前端将点位绘制为 PixiJS 独立层，以地图坐标命中右键菜单。

**Tech Stack:** Python 3.10、标准库线程/路径/JSON、ROS2 rclpy/Nav2、HTTP JSON、Vite ES modules、PixiJS、Node test runner、pytest。

**Spec:** `docs/superpowers/specs/2026-09-30-current-map-task-points-design.md`

## Global Constraints

- 浏览器仅访问 Backend HTTP/WebSocket；不得直接控制 ROS、读取任务目录或提交坐标、地图路径、行为树、速度参数。
- 任务文件、地图 YAML 和 virtual wall 均只读；不得创建、覆盖、移动或删除车端任务文件。
- 同图判定必须同时通过 map_server YAML、活动 OccupancyGrid 的 resolution/width/height/origin 校验；歧义时宁可无墙、无点位、无导航。
- 页面轮询、HTTP handler 与右键操作不得递归扫描任务目录；首次构建和文件变化刷新只能在后台 worker 进行。
- 起终点导航仅在 `navigation` 控制源、定位 normal、急停 normal、无手动/重定位占用、无活动运行时允许；失去安全条件必须取消唯一拥有的 Nav2 Goal。
- PC-only；Mobile 不新增入口或端点消费者。
- 使用半透明、紧凑、低阴影的既有实时观测语言；任务点图层默认开启，起点蓝色、终点琥珀色，支持浅/深主题与 reduced motion。
- 不提交构建产物、缓存、日志或不相关用户改动；当前工作树脏，执行过程中不得 `reset`、`checkout`、清理或创建提交。

---

### Task 1: 虚拟墙补偿重试

**Files:**
- Modify: `frontend/src/liveObservation.js: refreshActiveMap(), loadCachedMap(), map state declarations`
- Modify: `frontend/test/live-observation-map.test.mjs`
- Modify: `tests/test_live_observation_realtime.py`

**Interfaces:**
- Consumes: `POST /api/observation/live-layers` with `{ resolution, width, height, origin, frame_id }`.
- Produces: `requestLiveWallCompensation(mapId, metadata)` and `clearLiveWallCompensation()`; `virtualWalls` is replaced only for the current map signature.

- [x] **Step 1: Write failing frontend and source-boundary tests**

```js
test('live map retries wall compensation without reloading the base map', async () => {
  const source = await readFile('src/liveObservation.js', 'utf8');
  assert.match(source, /function requestLiveWallCompensation\(/);
  assert.match(source, /\/api\/observation\/live-layers/);
  assert.match(source, /clearLiveWallCompensation\(/);
});
```

```python
def test_live_wall_endpoint_is_used_by_the_pc_map_after_cached_map_loading():
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert "requestLiveWallCompensation" in source
    assert '"/api/observation/live-layers"' in source
```

- [x] **Step 2: Run the targeted tests and verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run test-realtime` and `cd frontend && node --test test/live-observation-map.test.mjs`.

Expected: FAIL because the compensation functions and endpoint use do not exist.

- [x] **Step 3: Implement bounded signature-scoped compensation**

```js
async function requestLiveWallCompensation(mapId, metadata) {
  const signature = liveWallSignature(mapId, metadata);
  if (!signature || signature !== activeLiveWallSignature) return;
  const result = await request('/api/observation/live-layers', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(metadata),
  });
  if (signature !== activeLiveWallSignature || !result.matched) return;
  virtualWalls = Array.isArray(result.virtual_walls) ? result.virtual_walls : [];
  renderStaticWorld(); scheduleMapDraw();
}
```

Keep a single timer per active signature: immediate request, 1 second retries while unmatched, then a capped low-frequency retry. Clear the timer and signature before any map switch. Do not redraw the base texture, invalidate point cloud data, or reset view state when only walls arrive.

- [x] **Step 4: Run focused tests and inspect the negative-path invariant**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run test-realtime` and `cd frontend && node --test test/live-observation-map.test.mjs`.

Expected: PASS; test source confirms a live-layer request and cleanup. Confirm existing `ObservationManager.live_layers()` still does not cache `matched=False`.

### Task 2: 后台当前地图任务点索引

**Files:**
- Create: `autodrive_console/current_map_task_points.py`
- Modify: `autodrive_console/task_start_navigation.py`
- Modify: `web_console.py: imports, singleton setup, GET/POST routes`
- Test: `tests/test_current_map_task_points.py`

**Interfaces:**
- Produces `CurrentMapTaskPointIndex(single_root: Path, multi_root: Path)` with `status_for_active_map(observation) -> dict[str, object]` and `resolve(point_id: str) -> TaskPoint`.
- `TaskPoint` contains private task path/fingerprint/map path and public opaque `id`, `kind`, `x`, `y`, `yaw`, `label`.
- Consumes `ObservationManager.verify_active_task_map(map_path) -> tuple[bool, str]`.

- [x] **Step 1: Write failing unit tests for non-blocking indexing and task parsing**

```python
def test_status_returns_only_same_map_start_and_end_from_background_index(tmp_path):
    index = CurrentMapTaskPointIndex(single_root, multi_root)
    first = index.status_for_active_map(observation)
    assert first["refreshing"] is True
    assert first["points"] == []
    assert _wait_until(lambda: not index.status_for_active_map(observation)["refreshing"])
    assert {(item["kind"], item["x"], item["y"]) for item in index.status_for_active_map(observation)["points"]} == {
        ("start", -6.0, 5.0), ("end", 2.0, 3.0),
    }

def test_status_never_exposes_task_path_or_map_url(tmp_path):
    payload = index.status_for_active_map(observation)
    assert "map_path" not in json.dumps(payload)
    assert "task_path" not in json.dumps(payload)
```

- [x] **Step 2: Run the new tests and verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run test -- tests/test_current_map_task_points.py`.

Expected: FAIL with `ModuleNotFoundError` for `current_map_task_points`.

- [x] **Step 3: Implement only the index and parsing model**

```python
@dataclass(frozen=True)
class TaskPoint:
    id: str; kind: Literal["start", "end"]; map_path: Path
    x: float; y: float; yaw: float; task_path: Path; fingerprint: str

class CurrentMapTaskPointIndex:
    def status_for_active_map(self, observation: object) -> dict[str, object]:
        self._schedule_refresh_if_needed()
        return self._public_snapshot_for(observation)
```

Use one daemon worker and immutable snapshots under a lock. Parse `subtasks[*]` for single tasks and direct `waypoints` for multi tasks; ignore `_r` multi fragments only if they are explicit return mirrors, but preserve their terminal endpoints if they are ordinary valid tasks. Canonicalize finite x/y/yaw and reject invalid quaternions. Deduplicate only identical map/kind/x/y/yaw tuples. Record file stat/fingerprint so `resolve()` can reject stale data; never rescan in `status_for_active_map`.

- [x] **Step 4: Add stale-file, invalid-file, multi-task, and map-switch tests**

```python
def test_resolve_rejects_a_changed_task_file(tmp_path):
    point = _ready_index(index).status_for_active_map(observation)["points"][0]
    task_path.write_text("{}", encoding="utf-8")
    with pytest.raises(TaskPointIndexError, match="任务文件已变更"):
        index.resolve(point["id"])
```

Ensure a nonmatching current map produces zero public points and no raw path leakage.

- [x] **Step 5: Run Task 2 tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run test -- tests/test_current_map_task_points.py tests/test_task_start_navigation.py`.

Expected: PASS.

### Task 3: 受控点位导航 API 与双向互斥

**Files:**
- Modify: `autodrive_console/task_start_navigation.py`
- Modify: `web_console.py: /api/observation/task-points and task-point-navigation routes`
- Modify: `autodrive_console/run_manager.py` only if its existing guard needs the renamed controller interface
- Modify: `shared/contracts/realtime_observation.md`
- Modify: `shared/contracts/robot_control.md`
- Modify: `shared/contracts/task_execution.md`
- Test: `tests/test_task_start_navigation.py`
- Test: `tests/test_offline_modules.py`

**Interfaces:**
- Consumes `CurrentMapTaskPointIndex.resolve(id) -> TaskPoint`.
- Produces `GET /api/observation/task-points`, `POST /api/observation/task-point-navigation/begin`, and `/cancel`.
- Reuses `TaskStartNavigationController.begin_point(point_id: str) -> dict[str, object]` and its existing Nav2 transport.

- [x] **Step 1: Write failing route and controller tests**

```python
def test_begin_point_rechecks_file_map_and_safety_before_nav_goal():
    snapshot = controller.begin_point("point-opaque")
    assert snapshot["phase"] == "navigating"
    assert transport.goals == [("map", -6.0, 5.0, 1.2)]

def test_navigation_route_accepts_only_an_opaque_id():
    response = _post("/api/observation/task-point-navigation/begin", {"id": "opaque"})
    assert response.status == HTTPStatus.OK
```

Include a 409 regression test for changed file/current-map mismatch and a 503 test for an unavailable Action transport.

- [x] **Step 2: Run and verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run test -- tests/test_task_start_navigation.py tests/test_offline_modules.py`.

Expected: FAIL because `begin_point` and new routes do not exist.

- [x] **Step 3: Replace source/id navigation with point-id navigation**

```python
def begin_point(self, point_id: str) -> dict[str, object]:
    self._enter_checking()
    point = self._index.resolve(point_id)
    self._require_safe_to_begin()
    matched, reason = self._observation.verify_active_task_map(point.map_path)
    if not matched: raise TaskStartNavigationConflict(reason)
    self._require_safe_to_begin()
    return self._send_goal(point)
```

Remove the obsolete top-selector API and its file-source parameters only after all callers use the point API. Preserve the existing one-goal lock, cancellation, timeout, safety-loss cancellation, `RunManager` guard and audit logs. Update every affected contract before tests are finalized.

- [x] **Step 4: Run Task 3 test suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run test -- tests/test_task_start_navigation.py tests/test_current_map_task_points.py tests/test_offline_modules.py`.

Expected: PASS.

### Task 4: PixiJS task-point layer and right-click operation

**Files:**
- Modify: `frontend/live-observation.html: map layer list; remove task-start control`
- Modify: `frontend/src/liveObservation.js: task point state, Pixi layer, right-click hit test/menu, API polling`
- Modify: `frontend/src/liveObservation.css: marker/menu styles and themes`
- Modify: `frontend/test/live-observation-map.test.mjs`

**Interfaces:**
- Consumes `GET /api/observation/task-points` and point navigation begin/cancel endpoints.
- Produces `pixiTaskPointLayer`, `renderTaskPoints()`, `taskPointsVisible`, `openTaskPointMenu(point, clientX, clientY)`, and `closeTaskPointMenu()`.

- [x] **Step 1: Write failing web tests**

```js
test('desktop map has an independent task start and end layer with right-click action', async () => {
  const [html, source, css] = await Promise.all([...]);
  assert.match(html, /id="taskPointsVisible"/);
  assert.match(source, /function renderTaskPoints\(/);
  assert.match(source, /contextmenu/);
  assert.match(source, /task-point-navigation\/begin/);
  assert.match(css, /\.task-point-menu/);
});
```

- [x] **Step 2: Run and verify RED**

Run: `cd frontend && node --test test/live-observation-map.test.mjs`.

Expected: FAIL because no task point layer/menu exists.

- [x] **Step 3: Add the minimal DOM and Pixi layer**

```html
<label class="map-layer-toggle" id="taskPointsToggle">
  <input id="taskPointsVisible" type="checkbox" checked />
  <span>任务起终点</span>
</label>
<div class="task-point-menu" id="taskPointMenu" hidden>…</div>
```

Create a Pixi `Container` between wall and cloud layers. Render starts as blue circles and ends as amber circles; render a composed double-ring only when equal coordinates hold both kinds. Use the same world-to-screen transform as the map, avoid permanent labels, and hide the layer without discarding its cached snapshot.

- [x] **Step 4: Add right-click hit testing and confirmation**

```js
interactionLayer.addEventListener('contextmenu', (event) => {
  const point = nearestTaskPoint(worldPointFromEvent(event), 16 / currentMapLayout().ratio);
  if (!point || !taskPointsVisible) return;
  event.preventDefault(); openTaskPointMenu(point, event.clientX, event.clientY);
});
```

The menu uses one action labelled by point kind and one cancel action. Before `POST` begin, use the existing confirmation convention; no point coordinates enter the request. Close menu on Esc, map drag/zoom, map change, layer disable, click outside, unload and navigation terminal state. Hide desktop-only UI under `html.mobile-console`.

- [x] **Step 5: Implement point polling only while layer is enabled**

Request task points after confirmed map load and on a modest timer only while the checkbox is checked. Clear points immediately on map signature change. Do not poll task directories from browser, do not create a point fetch when the layer is off, and preserve a visible navigation cancel state independently of the layer checkbox.

- [x] **Step 6: Run Task 4 web tests**

Run: `cd frontend && node --test test/live-observation-map.test.mjs`.

Expected: PASS.

### Task 5: Contract and whole-system verification

**Files:**
- Modify: `shared/contracts/realtime_observation.md`
- Modify: `shared/contracts/robot_control.md`
- Modify: `shared/contracts/task_execution.md`
- Modify: `tests/test_offline_modules.py`

**Interfaces:**
- Documents the final PC-only task-point endpoints, background index behavior, raw data privacy, map gate and navigation mutual exclusion.

- [x] **Step 1: Write failing contract-consumer assertions**

```python
def test_task_point_contract_has_no_browser_coordinate_navigation():
    contract = Path("shared/contracts/realtime_observation.md").read_text(encoding="utf-8")
    assert "/api/observation/task-points" in contract
    assert '"id": "opaque-id"' in contract
    assert "浏览器不得提交坐标" in contract
```

- [x] **Step 2: Run and verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run test-offline`.

Expected: FAIL until contract text and consumer assertions name the new API.

- [x] **Step 3: Update contracts and consumer checks**

Document old selector removal, current-map-only filtering, start/end semantics, default-visible desktop layer, virtual-wall compensation, right-click confirmation, backend revalidation, timeout/cancel and Mobile non-consumption. Keep all absolute paths and raw task/ROS values private.

- [x] **Step 4: Run full verification**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 scripts/test-backend.sh`.

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run test-offline`.

Run: `pixi run frontend-check`.

Run: `git diff --check`.

Expected: all commands exit 0. Use local Vite preview plus browser automation to inspect dark/light themes, layer off/on, wall late-arrival, right-click menu, point menu cancellation and no control overlap. Do not send a real Nav2 goal during local verification.
