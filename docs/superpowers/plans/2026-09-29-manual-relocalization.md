# Manual Relocalization Implementation Plan

> 2026-10-14 更新：下文为原始实现计划，启动脚本定位配置选择及仅凭服务成功恢复的旧描述已被替代。当前实现以 [设计文档](../specs/2026-09-29-manual-relocalization-design.md) 和 [Existing 契约](../../../shared/contracts/realtime_observation.md) 为准：已核验运行版本使用空 `map_path` 沿用节点当前配置；独立状态记录确认本次初始化/重定位后恢复正常。不得据旧计划重新引入 YAML 副本或启动脚本路径回退。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let PC realtime-observation operators align a stationary vehicle preview with map features and safely submit that pose to the existing lightning relocalization service.

**Architecture:** A dedicated backend coordinator owns the relocalization operation, temporarily acquires an exclusive stationary miniapp control-source lease, derives the active lightning YAML only from the trusted scenario startup script, and calls the ROS service from a backend ROS node. The web page only sends a finite candidate pose and locally applies one rigid preview transform to the vehicle-relative telemetry layers; it never sees or selects ROS paths.

**Tech Stack:** Python 3 / rclpy / stdlib HTTP server, existing `VehicleControlController`, PixiJS, static HTML/CSS/ES modules, Node tests, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-manual-relocalization-design.md`

## Global Constraints

- The browser must not directly access ROS, publish motion, submit a map/YAML path, choose a service name, or control z/roll/pitch.
- A running test does not block calibration; no test status may be cancelled, paused, or mutated by calibration.
- Only `/control_source_state=miniapp` confirms the stationary calibration state; only `/control_source_state=navigation` confirms automatic navigation recovery.
- All failed/timeout/unavailable relocalization paths remain stopped in `miniapp`; recovery to navigation is explicit.
- Active lightning config must be uniquely parsed from the current controlled startup script and resolve under `/opt/ry/` with a YAML extension.
- `z_m` defaults to `0.4` from `config/console.json` through `live_observation.manual_relocalization`; roll/pitch are always zero and `use_wheel_odom` is always false.
- Point cloud and local costmap must use the same `targetPose * inverse(realPose)` preview transform; static map, grid, scale, walls and routes do not move.
- This is PC-only. Do not add mobile entry points or change mobile rendering.
- Do not commit generated `autodrive_console/web-vue/` output or unrelated dirty worktree changes. Create commits only after explicit user authorization.

---

### Task 1: Configure and isolate the stationary calibration lease

**Files:**
- Modify: `autodrive_console/settings.py`
- Modify: `autodrive_console/vehicle_control.py`
- Test: `tests/test_vehicle_control.py`

**Interfaces:**
- Produces `VehicleControlController.begin_relocalization_hold() -> dict`, `finish_relocalization_hold(success: bool) -> dict`, and `recover_navigation_after_relocalization() -> dict`.
- Produces validated settings `live_observation.manual_relocalization = {"z_m": 0.4, "service_timeout_seconds": 12}`.
- Consumed by `ManualRelocalizationController` in Task 2.

- [ ] **Step 1: Write failing settings tests**

```python
def test_live_observation_defaults_manual_relocalization_config():
    settings = SettingsStore(tmp_path / "console.json").load()
    assert settings.live_observation["manual_relocalization"] == {
        "z_m": 0.4,
        "service_timeout_seconds": 12,
    }

def test_live_observation_rejects_invalid_manual_relocalization_values():
    with pytest.raises(ValueError, match="重定位 z 值"):
        SettingsStore(tmp_path / "console.json").save({
            "live_observation": {"manual_relocalization": {"z_m": float("nan"), "service_timeout_seconds": 12}}
        })
```

- [ ] **Step 2: Run the new settings tests and verify they fail**

Run: `pixi run pytest tests/test_offline_modules.py -k manual_relocalization -q`

Expected: FAIL because the nested setting does not exist or is not validated.

- [ ] **Step 3: Add the nested default and strict validation**

```python
DEFAULT_MANUAL_RELOCALIZATION = {"z_m": 0.4, "service_timeout_seconds": 12}

manual = observation.get("manual_relocalization")
if not isinstance(manual, dict):
    raise ValueError("手动重定位配置格式错误")
z_m = float(manual.get("z_m"))
timeout = int(manual.get("service_timeout_seconds"))
if not math.isfinite(z_m) or not 0.0 <= z_m <= 2.0:
    raise ValueError("重定位 z 值必须介于 0 和 2 米")
if not 1 <= timeout <= 30:
    raise ValueError("重定位服务超时必须介于 1 和 30 秒")
```

Deep-merge this nested default during legacy settings migration so existing `console.json` receives both fields.

- [ ] **Step 4: Write failing exclusive-hold tests**

```python
def test_relocalization_hold_allows_active_run_but_stops_and_confirms_miniapp(control):
    control._active_run_guard = lambda: True
    snapshot = control.begin_relocalization_hold()
    assert snapshot["transition"] == "miniapp"
    control._on_source_state(String(data="miniapp"))
    assert control.status()["relocalization_hold"] == "active"
    with pytest.raises(VehicleControlConflict, match="定位校准正在占用"):
        control.set_vector("any-session", 1, 0)

def test_failed_relocalization_hold_stays_in_miniapp_until_explicit_recovery(control):
    activate_relocalization_hold(control)
    control.finish_relocalization_hold(success=False)
    assert control.status()["relocalization_hold"] == "failed"
    assert control.status()["actual_source"] == "miniapp"
```

- [ ] **Step 5: Run the hold tests and verify they fail**

Run: `pixi run pytest tests/test_vehicle_control.py -k relocalization_hold -q`

Expected: FAIL because the exclusive hold API and status field do not exist.

- [ ] **Step 6: Implement a server-owned, non-drivable hold in `VehicleControlController`**

Add a private `_relocalization_hold` state with values `idle`, `switching`, `active`, `failed`, `recovering`. `begin_relocalization_hold()` must bypass only the active-run guard, clear all motion, reject existing regular manual sessions/pending transitions, request `miniapp`, and reuse the existing three-frame STOP behavior. While hold is not `idle`, reject `begin_manual_session`, `set_command`, `set_vector`, `set_speed`, and regular navigation requests with `VehicleControlConflict`; do not create a session ID. Add a dedicated navigation-recovery method that performs STOP → navigation request → real topic confirmation. Expose only the phase and safe reason in `_snapshot_locked()`.

- [ ] **Step 7: Run focused controller and settings tests**

Run: `pixi run pytest tests/test_vehicle_control.py tests/test_offline_modules.py -k 'relocalization or manual_relocalization' -q`

Expected: PASS.

- [ ] **Step 8: Inspect the scoped diff; commit only if the user authorizes it**

Run: `git diff --check -- autodrive_console/settings.py autodrive_console/vehicle_control.py tests/test_vehicle_control.py tests/test_offline_modules.py`

Expected: no output.

### Task 2: Build the trusted ROS relocalization coordinator

**Files:**
- Create: `autodrive_console/manual_relocalization.py`
- Modify: `autodrive_console/scenario_setup.py`
- Test: `tests/test_manual_relocalization.py`

**Interfaces:**
- Consumes `VehicleControlController.begin_relocalization_hold()`, `finish_relocalization_hold()`, and `recover_navigation_after_relocalization()` from Task 1.
- Produces `ManualRelocalizationController.status(settings)`, `begin(settings)`, `apply(settings, pose)`, `cancel()`, and `recover_navigation()`.
- Produces `ScenarioSetupStore.active_lightning_config() -> Path` without exposing path data to HTTP clients.
- Consumed by `web_console.py` in Task 3.

- [ ] **Step 1: Write failing parser and request-shaping tests**

```python
def test_active_lightning_config_requires_exactly_one_trusted_config(tmp_path):
    script = tmp_path / "handle_modules.sh"
    script.write_text("ros2 run lightning run_loc_online --config /opt/ry/config/live.yaml\n")
    store = ScenarioSetupStore(tmp_path / "console")
    store.save({"startup_script": str(script), "search_directories": [], "bindings": {}, "profiles": [], "case_bindings": {}})
    assert store.active_lightning_config() == Path("/opt/ry/config/live.yaml")

def test_apply_uses_two_stage_relocalize_protocol_without_browser_map_path(controller, settings):
    controller.begin(settings)
    mark_control_source_miniapp(controller)
    controller.apply(settings, {"x": 1.25, "y": -2.5, "yaw": 0.75})
    assert controller.client.requests == [{
        "map_path": "/opt/ry/config/live.yaml", "x": 1.25, "y": -2.5,
        "z": 0.4, "roll": 0.0, "pitch": 0.0, "yaw": 0.75,
        "use_wheel_odom": True,
    }, {
        "map_path": "/opt/ry/config/live.yaml", "x": 1.25, "y": -2.5,
        "z": 0.4, "roll": 0.0, "pitch": 0.0, "yaw": 0.75,
        "use_wheel_odom": False,
    }]
```

- [ ] **Step 2: Run the parser/request tests and verify they fail**

Run: `pixi run pytest tests/test_manual_relocalization.py -k 'lightning_config or fixed_relocalize' -q`

Expected: FAIL because the store accessor and controller do not exist.

- [ ] **Step 3: Implement trusted active-config lookup**

In `ScenarioSetupStore`, reuse `_LIGHTNING` and the current startup-script inspection. Require exactly one match; `resolve(strict=True)` the value; require it is under `/opt/ry`, is a regular file and ends with `.yaml` or `.yml`; otherwise raise `ScenarioSetupError` with a public-safe reason. Do not return its string through an HTTP payload.

- [ ] **Step 4: Implement `ManualRelocalizationController` with injectable ROS client factory**

Use an operation `RLock` and phases `idle`, `switching_to_miniapp`, `calibrating`, `calling_service`, `switching_to_navigation`, `failed`. Validate `x`, `y`, and `yaw` are finite and bound x/y to ±10000 m and yaw to ±8π before constructing the request. Create the ROS client internally for `lightning.srv.Relocalize`; wait at most configured timeout; convert only a known boolean `success=False`, a timeout, exception, or unavailable service into a safe failure. On successful response call `finish_relocalization_hold(success=True)` and request navigation. Log only operation phase and numeric pose, never the config path or raw exception.

- [ ] **Step 5: Write failing failure-path and serialization tests**

```python
def test_service_timeout_remains_stopped_in_miniapp(controller, settings):
    activate_calibration(controller, settings)
    controller.client.never_complete = True
    result = controller.apply(settings, {"x": 0, "y": 0, "yaw": 0})
    assert result["phase"] == "failed"
    assert result["vehicle_source"] == "miniapp"
    assert result["can_recover_navigation"] is True

def test_second_apply_while_calling_is_rejected(controller, settings):
    activate_calibration(controller, settings)
    controller.client.block_request = True
    controller.apply_in_background(settings, {"x": 0, "y": 0, "yaw": 0})
    with pytest.raises(ManualRelocalizationConflict):
        controller.apply(settings, {"x": 1, "y": 1, "yaw": 1})
```

- [ ] **Step 6: Run failure-path tests and verify they fail**

Run: `pixi run pytest tests/test_manual_relocalization.py -k 'timeout or second_apply' -q`

Expected: FAIL until operation state and failure behavior are implemented.

- [ ] **Step 7: Implement timeout, navigation confirmation, cancellation, and recovery semantics**

`cancel()` may only transition `calibrating → idle` through the dedicated navigation recovery and must reject `calling_service`. A service failure calls `finish_relocalization_hold(success=False)` and leaves the phase `failed`; only `recover_navigation()` may transition it to navigation recovery. A navigation timeout remains `failed` and miniapp-stopped. Return only `{phase, label, detail, can_begin, can_apply, can_cancel, can_recover_navigation, vehicle_source}`.

- [ ] **Step 8: Run the complete controller suite**

Run: `pixi run pytest tests/test_manual_relocalization.py -q`

Expected: PASS, including task-active begin, path escape rejection, invalid coordinates, timeout, failure, success, cancel, recovery, and concurrent operation cases.

- [ ] **Step 9: Inspect the scoped diff; commit only if the user authorizes it**

Run: `git diff --check -- autodrive_console/manual_relocalization.py autodrive_console/scenario_setup.py tests/test_manual_relocalization.py`

Expected: no output.

### Task 3: Wire the new PC-only observation API and document its contract

**Files:**
- Modify: `web_console.py`
- Modify: `shared/contracts/realtime_observation.md`
- Modify: `shared/contracts/robot_control.md`
- Modify: `tests/test_offline_modules.py`

**Interfaces:**
- Consumes `ManualRelocalizationController` from Task 2.
- Produces `GET /api/observation/relocalization` and the four POST actions from the spec.
- Consumed only by `frontend/src/liveObservation.js` in Task 4.

- [ ] **Step 1: Write failing HTTP dispatch tests**

```python
def test_observation_relocalization_routes_never_accept_map_path(handler, fake_relocalization):
    handler.path = "/api/observation/relocalization/apply"
    handler.rfile = BytesIO(b'{"x":1,"y":2,"yaw":0,"map_path":"/tmp/untrusted.yaml"}')
    handler.headers["Content-Length"] = str(len(handler.rfile.getvalue()))
    handler._observation_action(handler.path)
    assert fake_relocalization.calls == [("apply", {"x": 1, "y": 2, "yaw": 0})]

def test_relocalization_get_returns_safe_snapshot(handler, fake_relocalization):
    handler.path = "/api/observation/relocalization"
    handler.do_GET()
    assert 'map_path' not in handler.json_body
```

- [ ] **Step 2: Run the dispatch tests and verify they fail**

Run: `pixi run pytest tests/test_offline_modules.py -k relocalization_route -q`

Expected: FAIL because no route is registered.

- [ ] **Step 3: Construct the controller once and add strict route dispatch**

Instantiate the coordinator beside `OBSERVATION` and `VEHICLE_CONTROL`. GET returns `status(SETTINGS.load())`. POST `/begin`, `/apply`, `/cancel`, and `/recover-navigation` accepts at most 16 KiB JSON objects, retains only `x/y/yaw` for apply, and maps input conflicts to 409, unavailable ROS to 503, malformed values to 400, and accepted transition work to 202. Keep all ROS calls in the controller, not `ConsoleHandler`.

- [ ] **Step 4: Update both shared contracts before testing consumer behavior**

Add the exact endpoint table, phase meanings, PC-only consumer declaration, all stationary/control-source confirmations, task-active allowance, failure-stays-miniapp rule, position input ownership, and no-path-disclosure rule. In `robot_control.md`, define the relocalization hold as server-owned and mutually exclusive with regular manual sessions/motion commands.

- [ ] **Step 5: Run dispatch and contract regression tests**

Run: `pixi run pytest tests/test_offline_modules.py -k 'relocalization or observation' -q`

Expected: PASS.

- [ ] **Step 6: Inspect the scoped diff; commit only if the user authorizes it**

Run: `git diff --check -- web_console.py shared/contracts/realtime_observation.md shared/contracts/robot_control.md tests/test_offline_modules.py`

Expected: no output.

### Task 4: Add deterministic relocalization preview mathematics to the map renderer

**Files:**
- Modify: `frontend/src/liveObservation.js`
- Test: `frontend/test/live-observation-map.test.mjs`

**Interfaces:**
- Consumes `GET/POST /api/observation/relocalization` from Task 3.
- Produces pure helpers `composePreviewTransform(realPose, targetPose)`, `transformMapPoint(point, preview)`, `transformCostmapOrigin(origin, preview)`, and `previewVehiclePose()`.
- Consumed by Task 5 UI event handling.

- [ ] **Step 1: Write failing transform tests**

```javascript
test("relocalization preview applies one rigid delta to vehicle-relative layers", () => {
  const real = { x: 2, y: 3, yaw: Math.PI / 2 };
  const target = { x: 8, y: 1, yaw: Math.PI };
  const delta = composePreviewTransform(real, target);
  assert.deepEqual(transformMapPoint({ x: 2, y: 4 }, delta), { x: 7, y: 1 });
  assert.equal(transformCostmapOrigin({ x: 2, y: 3, yaw: 0 }, delta).yaw, Math.PI / 2);
});

test("preview cancellation restores the live vehicle pose without mutating telemetry", () => {
  setRelocalizationPreview({ x: 4, y: 5, yaw: 0 });
  clearRelocalizationPreview();
  assert.deepEqual(previewVehiclePose(), vehiclePoseInMap());
});
```

- [ ] **Step 2: Run the transform tests and verify they fail**

Run: `node --test frontend/test/live-observation-map.test.mjs --test-name-pattern='relocalization preview'`

Expected: FAIL because the helpers and state are absent.

- [ ] **Step 3: Implement pure pose-delta helpers and preview state**

Keep raw telemetry structures unchanged. Store only `{realPose, targetPose}` in local preview state, normalize yaw to `[-π, π)`, and recompute delta when live pose updates. Route `renderCloudPoints`, `renderCostmap`, `syncVehicleLayer`, follow-centering, and diagnostics through transformed presentation values while preview is active. Do not transform static map/world layers or mutate incoming `cloud`/`costmap` packets.

- [ ] **Step 4: Add a costmap and point-cloud regression assertion**

```javascript
test("cloud and costmap share the preview delta while walls retain map coordinates", () => {
  const delta = composePreviewTransform({ x: 0, y: 0, yaw: 0 }, { x: 1, y: 0, yaw: Math.PI / 2 });
  assert.deepEqual(transformMapPoint({ x: 1, y: 0 }, delta), { x: 1, y: 1 });
  assert.equal(virtualWallWorldPoint({ x: 1, y: 0 }).x, 1);
});
```

- [ ] **Step 5: Run the map test file**

Run: `node --test frontend/test/live-observation-map.test.mjs`

Expected: PASS.

- [ ] **Step 6: Inspect the scoped diff; commit only if the user authorizes it**

Run: `git diff --check -- frontend/src/liveObservation.js frontend/test/live-observation-map.test.mjs`

Expected: no output.

### Task 5: Build the compact Apple-style PC calibration UI

**Files:**
- Modify: `frontend/live-observation.html`
- Modify: `frontend/src/liveObservation.js`
- Modify: `frontend/src/liveObservation.css`
- Modify: `frontend/test/live-observation-map.test.mjs`

**Interfaces:**
- Consumes renderer preview helpers from Task 4 and safe relocalization snapshots/actions from Task 3.
- Produces a desktop-only, keyboard-accessible calibration panel; mobile retains no control.

- [ ] **Step 1: Write failing UI structure and request tests**

```javascript
test("desktop observation exposes a collapsed calibration entry with staged confirmation", () => {
  assert.match(html, /id="relocalizationToggle"/);
  assert.match(html, /id="relocalizationPanel"/);
  assert.match(html, /id="relocalizationApply"/);
  assert.match(source, /\/api\/observation\/relocalization\/begin/);
  assert.match(source, /\/api\/observation\/relocalization\/apply/);
  assert.match(stylesheet, /html\.mobile-console \.relocalization-control\s*\{\s*display:\s*none/);
});
```

- [ ] **Step 2: Run the UI test and verify it fails**

Run: `node --test frontend/test/live-observation-map.test.mjs --test-name-pattern='calibration entry'`

Expected: FAIL because the panel is absent.

- [ ] **Step 3: Add restrained desktop markup and styling**

Place `relocalization-control` beside the existing compact map-layer control. Collapsed state is a small neutral “校准定位” entry with no persistent alert styling. Expanded panel presents explicit sequence labels: `1 停车确认`, `2 拖拽对齐`, `3 确认重定位`; expose a non-editable x/y/yaw readout, cancel/recover actions, inline error text, and a confirm dialog that repeats the selected pose. Use the existing light/dark CSS variables, `prefers-reduced-motion`, 44px minimum touch targets for actionable controls, and `hidden`/ARIA state. Hide the entire control in `html.mobile-console`.

- [ ] **Step 4: Implement UI state and map manipulation**

Poll safe relocalization status only while the desktop page is open. Begin must wait for backend `calibrating` before enabling pointer drag. On drag, convert screen delta through existing map world/screen conversion; add a rotation handle/key-accessible yaw control; keep latest live pose as the preview anchor. Apply sends exactly `{x, y, yaw}` after a second confirmation. Cancel clears local preview and calls cancel. Failed state only shows “切回自动驾驶”, which calls recover-navigation; no automatic retry loops.

- [ ] **Step 5: Run frontend map tests and static check**

Run: `node --test frontend/test/live-observation-map.test.mjs && pixi run frontend-check`

Expected: PASS.

- [ ] **Step 6: Inspect the scoped diff; commit only if the user authorizes it**

Run: `git diff --check -- frontend/live-observation.html frontend/src/liveObservation.js frontend/src/liveObservation.css frontend/test/live-observation-map.test.mjs`

Expected: no output.

### Task 6: Run integration checks and browser acceptance review

**Files:**
- Modify only if a verified integration failure requires a scoped fix.
- Test: `tests/test_manual_relocalization.py`, `tests/test_vehicle_control.py`, `tests/test_live_observation_realtime.py`, `frontend/test/live-observation-map.test.mjs`

**Interfaces:**
- Verifies all outputs from Tasks 1–5 and no unrelated runtime/build artifact changes.

- [ ] **Step 1: Run focused backend tests**

Run: `./scripts/test-backend.sh`

Expected: PASS with no regression in existing vehicle control, scene setup, observation, or handler behavior.

- [ ] **Step 2: Run the Web suite and production build**

Run: `./scripts/test-web.sh`

Expected: PASS; confirm Vite emits output without adding generated artifacts to the git index.

- [ ] **Step 3: Perform browser acceptance checks**

Run: start the existing local preview only if no user-owned server is already listening, then use the desktop realtime page to verify:

1. Collapsed calibration control remains lower-emphasis than the map and opens/closes with pointer, Escape, and accessible state.
2. Begin does not enable drag before miniapp confirmation; simulated failure is readable and leaves only explicit navigation recovery.
3. Drag moves vehicle, cloud, and local costmap together while map/walls/grid remain fixed; cancel restores the exact live presentation.
4. Deep/light themes and narrow desktop viewport retain readable compact layout; mobile hides the control.
5. Incoming telemetry continues latest-wins rendering while a preview is active, without an unbounded frame queue.

- [ ] **Step 4: Run final change and contract checks**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only deliberate source, test, contract, and documentation changes are identified before any user-authorized commit.

- [ ] **Step 5: Report completion evidence without committing**

Report the exact backend/Web test results, browser scenarios observed, known on-vehicle prerequisite (`lightning/srv/Relocalize` present), and the final file list. Do not claim vehicle-side success without a real service call on the target robot.
