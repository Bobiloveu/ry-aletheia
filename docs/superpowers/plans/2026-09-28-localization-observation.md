# Localization Observation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display localization health in the PC live map and preserve per-run, per-round relocalization evidence in reports.

**Architecture:** A persistent read-only `LocalizationStatusMonitor` owns ROS subscription and a bounded normalized event ledger. `RunManager` passes that monitor to each `TrajectorySession`, which attaches only verified map coordinates to reset events. The existing HTTP control plane exposes a small snapshot to the PC page; reports render independent event markers without changing trajectory geometry.

**Tech Stack:** Python 3.10, rclpy, ThreadingHTTPServer, PixiJS/Vite JavaScript, SVG, pytest, Node test runner.

**Spec:** `docs/superpowers/specs/2026-09-28-localization-observation-design.md`

## Global Constraints

- Read only `/localization/status` of type `master_interfaces/msg/LocalizationStatus`; never call a relocalization service.
- Count only the first `state=4` event for each non-empty `fault_id`.
- Browser uses controlled HTTP only; no ROS, WebSocket protocol, vehicle-control, Node Manager, or Mobile behavior changes.
- Marker coordinates must originate from an already verified map-coordinate trajectory sample; missing coordinates must remain unrendered.
- Preserve current map layout and actual trajectory rendering; new status UI is a compact overlay only.

---

### Task 1: Normalize persistent localization status and events

**Files:**
- Create: `autodrive_console/localization_status.py`
- Modify: `web_console.py`
- Test: `tests/test_localization_status.py`

**Interfaces:**
- Produces `LocalizationStatusMonitor.status() -> dict[str, str | int | None]`, `cursor() -> int`, and `events_since(cursor: int) -> tuple[int, list[dict]]`.
- `web_console.py` exposes `GET /api/observation/localization-status` from that monitor.

- [x] **Step 1: Write failing monitor tests**

```python
def test_resetting_is_counted_once_for_each_fault_id():
    monitor = LocalizationStatusMonitor(clock=lambda: 10.0)
    monitor.observe(FakeStatus(state=4, error_code=100, fault_id=42))
    monitor.observe(FakeStatus(state=4, error_code=100, fault_id=42))
    _, events = monitor.events_since(0)
    assert [event["fault_id"] for event in events] == [42]
```

- [x] **Step 2: Run the test and verify it fails because the monitor is absent**

Run: `pixi run pytest tests/test_localization_status.py -q`

- [x] **Step 3: Implement the monitor and endpoint wiring**

```python
class LocalizationStatusMonitor:
    TOPIC = "/localization/status"
    def observe(self, message) -> None:
        """Normalize one ROS localization status message."""
    def status(self) -> dict[str, object]:
        """Return the current public, non-ROS snapshot."""
    def events_since(self, cursor: int) -> tuple[int, list[dict[str, object]]]:
        """Return reset events strictly newer than cursor."""
```

- [x] **Step 4: Re-run the monitor tests**

Run: `pixi run pytest tests/test_localization_status.py -q`

### Task 2: Capture relocalization evidence per trajectory round

**Files:**
- Modify: `autodrive_console/trajectory.py`
- Modify: `autodrive_console/run_manager.py`
- Modify: `autodrive_console/models.py`
- Test: `tests/test_localization_status.py`

**Interfaces:**
- Consumes `LocalizationStatusMonitor.events_since`.
- Produces trajectory-level `relocalizations: list[dict]` and `AttemptResult.relocalization_count: int`.

- [x] **Step 1: Write failing evidence tests**

```python
def test_trajectory_attaches_reset_event_to_the_next_verified_map_sample():
    session = TrajectorySession([], localization_monitor=monitor)
    session._record_relocalizations_for_sample({"x": 1.25, "y": -0.5, "map_id": "map-a"})
    assert session._relocalizations[0]["x"] == 1.25
```

- [x] **Step 2: Run the test and verify the missing argument/helper failure**

Run: `pixi run pytest tests/test_localization_status.py -q`

- [x] **Step 3: Add event capture and report model field**

```python
TrajectorySession(maps, route_plan=None, progress_callback=None, localization_monitor=None)
AttemptResult(index, status, message, duration_s, started_at, relocalization_count=0)
```

- [x] **Step 4: Re-run the evidence tests**

Run: `pixi run pytest tests/test_localization_status.py -q`

### Task 3: Render markers and counts into offline reports

**Files:**
- Modify: `autodrive_console/trajectory_render.py`
- Modify: `autodrive_console/run_manager.py`
- Test: `tests/test_offline_modules.py`

**Interfaces:**
- Consumes `trajectory["relocalizations"]` and `AttemptResult.relocalization_count`.
- Produces SVG `relocalization-marker` nodes, summary metric, and a relocalization column in HTML/CSV.

- [x] **Step 1: Write failing report tests**

```python
assert "重定位次数" in contents
assert "relocalization-marker" in contents
assert "T-001" in contents
```

- [x] **Step 2: Run the focused report test and verify it fails**

Run: `pixi run pytest tests/test_offline_modules.py::OfflineModulesTest::test_downloadable_report_inlines_trajectory_svg -q`

- [x] **Step 3: Add non-obscuring marker layer and report statistics**

```python
marker_layer = '<g class="relocalization-markers"><circle class="relocalization-marker" /></g>'
writer.writerow(["Run_ID", "Test_ID", "Status", "Relocalization_Count"])
```

- [x] **Step 4: Re-run focused report tests**

Run: `pixi run pytest tests/test_offline_modules.py -q`

### Task 4: Add the compact PC localization overlay

**Files:**
- Modify: `frontend/live-observation.html`
- Modify: `frontend/src/liveObservation.js`
- Modify: `frontend/src/liveObservation.css`
- Test: `frontend/test/live-observation-map.test.mjs`
- Test: `tests/test_live_observation_realtime.py`

**Interfaces:**
- Consumes `GET /api/observation/localization-status` at low-frequency control-plane cadence.
- Produces `#localizationStatus` with a readable state label and non-internal detail.

- [x] **Step 1: Write failing DOM behavior tests**

```js
assert.match(page, /id="localizationStatus"/);
assert.match(source, /request\("\/api\/observation\/localization-status"\)/);
```

- [x] **Step 2: Run the web test and verify it fails**

Run: `pixi run node --test frontend/test/live-observation-map.test.mjs`

- [x] **Step 3: Implement semantic overlay, refresh, and reduced-motion-safe styling**

```js
function applyLocalizationStatus(snapshot) {
  document.querySelector("#localizationStatus").dataset.phase = snapshot.phase;
}
window.setInterval(refreshLocalizationStatus, 1000);
```

- [x] **Step 4: Re-run frontend and targeted Python tests**

Run: `pixi run node --test frontend/test/live-observation-map.test.mjs && pixi run pytest tests/test_live_observation_realtime.py -q`

### Task 5: Document the additive contract and verify end to end

**Files:**
- Modify: `shared/contracts/realtime_observation.md`
- Test: `scripts/test-backend.sh`
- Test: `scripts/test-web.sh`

**Interfaces:**
- Documents the backward-compatible PC-only snapshot endpoint and the public state enum.

- [x] **Step 1: Document endpoint fields, freshness behavior, and consumers**

```markdown
GET /api/observation/localization-status returns phase, label, detail and updated_at.
```

- [x] **Step 2: Run the full affected checks**

Run: `./scripts/test-backend.sh && ./scripts/test-web.sh`

- [x] **Step 3: Render and inspect the local/robot live page once at desktop and mobile widths**

Run: `agent-browser open http://192.168.1.20:8087/live-observation.html`

- [x] **Step 4: Run the UI detector**

Run: `node /home/bob/.codex/skills/impeccable/scripts/detect.mjs --json frontend/live-observation.html frontend/src/liveObservation.js frontend/src/liveObservation.css`
