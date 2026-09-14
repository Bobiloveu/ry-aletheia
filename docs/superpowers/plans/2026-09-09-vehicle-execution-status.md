# Vehicle Execution Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add a PC-only, full-viewport vehicle-behaviour status surface whose only visible content is a large animated face and the current authoritative Chinese status label.

**Architecture:** A persistent read-only ROS monitor retains the latest task and navigation messages and delegates the public phase to a pure classifier. web_console.py exposes the current snapshot through a no-cache HTTP endpoint and serves one explicit static page without the normal desktop shell. The Web module polls only that endpoint and renders a validated phase/label pair; the existing task dashboard receives only a link.

**Tech Stack:** Python 3.10, ROS 2 Humble/rclpy, Python dataclasses, ThreadingHTTPServer, native ES modules, CSS animation, Node test runner, pytest.

**Spec:** docs/superpowers/specs/2026-09-09-vehicle-execution-status-design.md

## Global Constraints

- PC Web is the only consumer; do not modify Flutter, mobile routes, or the mobile build.
- Browser clients use controlled HTTP only; they never subscribe to ROS directly.
- The read-only endpoint always returns exactly phase and label. Unknown, stale, conflicting, and unavailable conditions return {"phase":"unavailable","label":"状态暂不可用"} with HTTP 200.
- /task_status and /navigate_todoor_detailed_status are volatile. Subscriptions must start with the console process, never when the page opens.
- Unknown task codes, unknown behavior names, ambiguous reused codes, unreadable runtime, and stale navigation fail closed to unavailable; do not fuzzy-match filenames.
- restarting_nodes is allowed only while RunManager is performing Aletheia-controlled dependency orchestration/restart work.
- The status page contains only the approved dark circular face with two pupil-free white vertical oval eyes and one enormous Chinese label. No shell, navigation, card, progress, caption, control, selector, task detail, or diagnostic text.
- Preserve every existing desktop page’s markup, style, and behavior. The task dashboard changes only by one narrow entry link.
- Motion uses only CSS transform/opacity/shape. unavailable is still; prefers-reduced-motion: reduce disables nonessential motion.
- Do not use external visual assets or libraries. Do not copy source or assets from the referenced project.
- Update shared/contracts/task_execution.md with Backend and PC Web consumers and state that Mobile and vehicle screen are non-consumers.
- Required final checks: scripts/test-backend.sh, scripts/test-web.sh, git diff --check, and focused browser visual inspection. Do not run Mobile tests.

## File Structure

~~~text
autodrive_console/
├── vehicle_execution_status/
│   ├── __init__.py                 # narrow public exports
│   ├── model.py                    # immutable normalized messages and snapshot
│   ├── classifier.py               # pure, deterministic phase classifier
│   └── monitor.py                  # persistent rclpy lifecycle and freshness
├── robot_gateway.py                # controlled restart activity callback
├── run_manager.py                  # thread-safe restart-activity source
└── web/
    ├── index.html                  # dashboard link only
    ├── vehicle-execution-status.html
    ├── vehicle_execution_status.js
    └── vehicle_execution_status.css
frontend/
├── vite.config.js                  # proxy list for legacy page/assets
└── test/vehicle-execution-status.test.mjs
tests/
├── test_vehicle_execution_status.py
└── test_offline_modules.py
web_console.py                       # lifecycle, endpoint, shell-free route
shared/contracts/task_execution.md   # API/consumer contract
~~~

---

### Task 1: Immutable execution-state model and fail-closed classifier

**Files:**
- Create: autodrive_console/vehicle_execution_status/__init__.py
- Create: autodrive_console/vehicle_execution_status/model.py
- Create: autodrive_console/vehicle_execution_status/classifier.py
- Create: tests/test_vehicle_execution_status.py

**Interfaces:**
- Consumes: normalized scalar fields from ROS callbacks, supplied as plain Python values.
- Produces: NavigationState, TaskEvent, ExecutionSnapshot, PUBLIC_LABELS, and classify_execution_state(navigation, task_event, *, restarting_nodes: bool) -> ExecutionSnapshot.

- [ ] **Step 1: Write the failing classifier tests**

~~~python
def test_classifier_uses_exact_semantics_before_reused_status_code():
    result = classify_execution_state(
        NavigationState(status="running", current_task="1_1_close_elevdoor_x.xml"),
        TaskEvent(status_code="203"),
        restarting_nodes=False,
    )
    assert (result.phase, result.label) == ("closing_elevator_door", "关电梯门")


def test_classifier_rejects_unknown_ambiguous_inputs():
    result = classify_execution_state(
        NavigationState(status="running", current_task="unreviewed_elevator_action.xml"),
        TaskEvent(status_code="203"),
        restarting_nodes=False,
    )
    assert (result.phase, result.label) == ("unavailable", "状态暂不可用")
~~~

- [ ] **Step 2: Run the test to verify it fails**

Run: pixi run pytest tests/test_vehicle_execution_status.py -q

Expected: FAIL because autodrive_console.vehicle_execution_status does not exist.

- [ ] **Step 3: Define immutable input and output types**

Create frozen dataclasses in model.py:

~~~python
@dataclass(frozen=True)
class NavigationState:
    status: str = ""
    current_task: str = ""
    current_waypoint_id: str = ""
    current_speed_mode: str = ""


@dataclass(frozen=True)
class TaskEvent:
    status_code: str = ""


@dataclass(frozen=True)
class ExecutionSnapshot:
    phase: str
    label: str

    def to_public_dict(self) -> dict[str, str]:
        return {"phase": self.phase, "label": self.label}
~~~

Declare closed labels for task, calling_elevator, entering_elevator, riding_elevator, exiting_elevator, closing_elevator_door, opening_gate, closing_gate, opening_access_door, closing_access_door, draining_or_unloading, completed, restarting_nodes, and unavailable.

- [ ] **Step 4: Implement only exact, approved classification**

Implement a pure classifier with exact basename/action-token parsing; it must not read files or import rclpy. Use an explicit approved action-token map, including elevator_in_, elevator_out_, close_elevdoor_, e_guard_open_, e_guard_close_, clamp_water, and place_water. Test every accepted action and not_elevator_in.xml as a rejected action.

Priority is: controlled restart; fresh terminal navigation (completed/successful); approved behavior semantic; unambiguous event code (200, 201, 202, 400–403, 109); generic active navigation (task); unavailable. Codes 203, 209, and 300–304 require a recognized exact semantic or return unavailable.

- [ ] **Step 5: Expand tests for priority and fail-closed rules**

~~~python
assert classify_execution_state(
    NavigationState(status="completed", current_task="elevator_out_1.xml"),
    TaskEvent(status_code="202"), restarting_nodes=False,
).phase == "completed"

assert classify_execution_state(
    NavigationState(status="running"), TaskEvent(status_code="200"), restarting_nodes=True,
).phase == "restarting_nodes"

assert classify_execution_state(
    NavigationState(status="running"), TaskEvent(status_code=""), restarting_nodes=False,
).phase == "task"
~~~

- [ ] **Step 6: Run focused classifier tests**

Run: pixi run pytest tests/test_vehicle_execution_status.py -q

Expected: PASS.

- [ ] **Step 7: Commit the classifier**

~~~bash
git add autodrive_console/vehicle_execution_status tests/test_vehicle_execution_status.py
git commit -m "feat: classify vehicle execution status"
~~~

### Task 2: Persistent ROS monitor and truthful dependency-restart signal

**Files:**
- Create: autodrive_console/vehicle_execution_status/monitor.py
- Modify: autodrive_console/vehicle_execution_status/__init__.py
- Modify: autodrive_console/run_manager.py
- Modify: autodrive_console/robot_gateway.py
- Modify: tests/test_vehicle_execution_status.py

**Interfaces:**
- Consumes: classifier/model types and Callable[[], bool] supplied by RunManager.dependency_restart_active.
- Produces: VehicleExecutionStatusMonitor.start() -> None, .close() -> None, .status() -> dict[str, str], and RunManager.dependency_restart_active() -> bool.

- [ ] **Step 1: Write failing freshness and callback tests**

~~~python
def test_monitor_returns_unavailable_after_navigation_expiry():
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0, freshness_s=4.0)
    monitor.observe_navigation(FakeNavigation(status="running"), received_at=1.0)
    assert monitor.status() == {"phase": "unavailable", "label": "状态暂不可用"}


def test_monitor_keeps_latest_callback_snapshot():
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 5.0, freshness_s=4.0)
    monitor.observe_navigation(FakeNavigation(status="running", current_task="elevator_in_1.xml"), received_at=4.0)
    monitor.observe_task(FakeTask(status_code="201"), received_at=5.0)
    assert monitor.status()["phase"] == "entering_elevator"
~~~

Also test unavailable rclpy startup, idempotent close, and a restart callback sequence of [True, False] on both success and error.

- [ ] **Step 2: Run the test to verify it fails**

Run: pixi run pytest tests/test_vehicle_execution_status.py -q

Expected: FAIL because VehicleExecutionStatusMonitor is undefined.

- [ ] **Step 3: Implement monitor state and freshness before ROS startup**

Use one lock, injected clock: Callable[[], float] = time.monotonic, navigation freshness of 4 seconds, and task-event freshness of 15 seconds. Implement callback-safe observe_navigation and observe_task that store only normalized immutable values and a monotonic receive time. Copy snapshots under the lock and classify outside it.

A stale navigation sample always returns unavailable, except a fresh terminal completed event. A fresh nonterminal event never extends stale navigation. Navigation failed, error, idle, or unrecognized terminal data returns unavailable unless the controlled restart signal is currently active.

- [ ] **Step 4: Implement persistent, read-only ROS lifecycle**

Follow VehicleControlController’s lazy-import/lock/executor/thread lifecycle. Subscribe reliably/volatile to master_interfaces.msg.TaskStatus on /task_status and master_interfaces.msg.NavigateTodoorStatus on /navigate_todoor_detailed_status. Do not subscribe to /elevator_status. Callbacks only normalize/store fields. A failed import, node, executor, or subscription logs a warning, tears down partial state, and leaves .status() as unavailable without stopping the console. Make .close() bounded and idempotent.

- [ ] **Step 5: Instrument only actual dependency-control intervals**

Add a lock-protected refcount to RunManager and:

~~~python
def dependency_restart_active(self) -> bool:
    with self._lock:
        return self._dependency_restart_count > 0
~~~

Extend RobotGateway with an optional named dependency_restart_callback: Callable[[bool], None] | None. Around real supervisor start/restart commands plus their stability wait in _apply_dependency_plan() and the minimal-consumer path of restart_configured_dependencies(), invoke true then invoke false in finally. Do not signal passive supervisor discovery, plain preflight, scenario file writes, or a generic run state. Every RunManager-created gateway receives the callback; nested intervals use the refcount.

- [ ] **Step 6: Run monitor and affected gateway tests**

Run: pixi run pytest tests/test_vehicle_execution_status.py tests/test_trajectory_fallback.py tests/test_offline_modules.py -q

Expected: PASS without changing existing preflight behavior.

- [ ] **Step 7: Commit monitor and activity signal**

~~~bash
git add autodrive_console/vehicle_execution_status autodrive_console/run_manager.py autodrive_console/robot_gateway.py tests/test_vehicle_execution_status.py
git commit -m "feat: monitor vehicle execution status"
~~~

### Task 3: Console lifecycle, shell-free route, HTTP endpoint, and contract

**Files:**
- Modify: web_console.py
- Modify: shared/contracts/task_execution.md
- Modify: tests/test_offline_modules.py

**Interfaces:**
- Consumes: VehicleExecutionStatusMonitor(restarting_nodes=RUNS.dependency_restart_active) and .status() -> dict[str, str].
- Produces: GET /api/vehicle-execution-status with no-cache JSON and one explicit static route excluding normal shell injection.

- [ ] **Step 1: Write failing route and shell tests**

Use the existing handler harness to assert a stub status is unchanged, the response has Cache-Control: no-store, max-age=0, the new page has neither /app_shell.js nor /brand_version.js, and ordinary dashboard HTML still gets the normal shell injection.

- [ ] **Step 2: Run focused route tests to verify they fail**

Run: pixi run pytest tests/test_offline_modules.py -q

Expected: FAIL because the new route and shell opt-out do not exist.

- [ ] **Step 3: Add monitor ownership to console startup and shutdown**

Instantiate one global monitor next to RUNS and VEHICLE_CONTROL, passing RUNS.dependency_restart_active. Start it before binding ThreadingHTTPServer; log a warning on unavailable ROS without blocking console startup. Close it in the existing finally before closing the server. Never create it per request.

- [ ] **Step 4: Add the API and a narrow shell-injection opt-out**

Register GET /api/vehicle-execution-status alongside state routes and return only self._json(VEHICLE_EXECUTION_STATUS.status()). Give _static_from keyword-only inject_console_shell: bool = True, retain that default for every existing caller, and call it with false only for explicit /vehicle-execution-status.html. Preserve its resolved-path, MIME, and no-store behavior. Do not add this page to mobile route sets.

- [ ] **Step 5: Update the shared contract**

Add an Existing — Vehicle execution status display section documenting the endpoint, closed phase list, response examples, Backend runtime owner, PC Web current consumer, Mobile/vehicle display non-consumers, unavailable HTTP-200 behavior, and relevant Backend/Web checks. State clearly that this is read-only snapshot data and adds no ROS control channel.

- [ ] **Step 6: Verify route and contract tests**

Run: pixi run pytest tests/test_offline_modules.py -q && git diff --check

Expected: PASS with no whitespace error and no desktop shell on the new route.

- [ ] **Step 7: Commit API and contract**

~~~bash
git add web_console.py shared/contracts/task_execution.md tests/test_offline_modules.py
git commit -m "feat: expose vehicle execution status"
~~~

### Task 4: Minimal PC status page and dashboard entry

**Files:**
- Modify: autodrive_console/web/index.html
- Create: autodrive_console/web/vehicle-execution-status.html
- Create: autodrive_console/web/vehicle_execution_status.js
- Create: autodrive_console/web/vehicle_execution_status.css
- Modify: frontend/vite.config.js
- Create: frontend/test/vehicle-execution-status.test.mjs
- Modify: frontend/test/dev-preview-proxy.test.mjs

**Interfaces:**
- Consumes: the two-string HTTP response and existing requestJson from /platform/http.js.
- Produces: isolated rendering functions normalizeExecutionStatus, shouldRenderExecutionStatus, and startExecutionStatusPolling.

- [ ] **Step 1: Write failing Web module and proxy tests**

~~~javascript
test("only a complete API tuple is renderable", () => {
  assert.deepEqual(
    normalizeExecutionStatus({ phase: "riding_elevator", label: "乘梯中" }),
    { phase: "riding_elevator", label: "乘梯中" },
  );
  assert.deepEqual(normalizeExecutionStatus({ phase: "riding_elevator" }), {
    phase: "unavailable", label: "状态暂不可用",
  });
});

test("same state is not re-rendered", () => {
  assert.equal(shouldRenderExecutionStatus("riding_elevator", "riding_elevator"), false);
  assert.equal(shouldRenderExecutionStatus("riding_elevator", "entering_elevator"), true);
});
~~~

Add Vite proxy assertions for the new HTML, JS, and CSS paths.

- [ ] **Step 2: Run focused Node tests to verify they fail**

Run: pixi run node --test frontend/test/vehicle-execution-status.test.mjs frontend/test/dev-preview-proxy.test.mjs

Expected: FAIL because the module and proxy entries do not exist.

- [ ] **Step 3: Create the intentionally shell-free document**

Use only this content structure:

~~~html
<main class="vehicle-execution-status" aria-live="polite">
  <div class="execution-face" aria-hidden="true"><i class="eye eye-left"></i><i class="eye eye-right"></i></div>
  <h1 id="vehicleExecutionLabel">状态暂不可用</h1>
</main>
~~~

Do not add existing console CSS, shell scripts, brand, breadcrumb, helper text, controls, hidden debug UI, or task metadata.

- [ ] **Step 4: Implement isolated polling and safe DOM rendering**

Validate a closed client phase allowlist plus a nonempty label; otherwise use unavailable. Render exclusively through document.body.dataset.phase and textContent. Keep a monotonically increasing request generation so a late response cannot overwrite a newer one. Skip DOM mutations when the phase and label are identical so polling does not restart CSS animation.

~~~javascript
export function shouldRenderExecutionStatus(previous, next) {
  return previous?.phase !== next.phase || previous?.label !== next.label;
}
~~~

Poll immediately then every 1000 ms. A transport or parse error renders unavailable. Do not ship a query-string mock mode or detail/history/control UI.

- [ ] **Step 5: Implement the approved high-distance visual treatment**

Immediately before editing UI CSS, read /home/bob/.codex/skills/impeccable/reference/craft-floor.md. Use page-local CSS only: quiet off-white background, a deep navy circle, two pupil-free white vertical ellipse eyes, and the approved high-contrast violet/blue label. Set face width to min(54vw, 510px); set label size to clamp(72px, 10vw, 152px). Per-phase motion may alter only face transform/scale and eye shape. No body, pupils, mouth, icon, copy, or second indicator. Keep all animation inside prefers-reduced-motion: no-preference; force no animation or transition for reduced motion. The unavailable state is still.

- [ ] **Step 6: Add one dashboard link and all dev-proxy dependencies**

In the existing task-dashboard header action area add one small anchor to /vehicle-execution-status.html labelled 执行状态. Do not change app.js, cards, layout classes, or dashboard CSS. Add the new HTML, JS, and CSS to legacyBackendPaths in frontend/vite.config.js.

- [ ] **Step 7: Verify Web behavior and visual scope**

Run: pixi run node --test frontend/test/vehicle-execution-status.test.mjs frontend/test/dev-preview-proxy.test.mjs && scripts/test-web.sh

Expected: PASS.

Run a console-backed preview. Inspect /vehicle-execution-status.html at a common desktop width and a small-screen reference width: exactly one face and one huge label, no injected shell, unavailable is still, reduced-motion behavior is stable, and the dashboard gained only its entry link. Run:

~~~bash
node /home/bob/.codex/skills/impeccable/scripts/detect.mjs --json autodrive_console/web/vehicle-execution-status.html autodrive_console/web/vehicle_execution_status.css
~~~

Expected: no blocking finding. Make at most one batched correction round and repeat the screenshot pair once.

- [ ] **Step 8: Commit the Web surface**

~~~bash
git add autodrive_console/web/index.html autodrive_console/web/vehicle-execution-status.html autodrive_console/web/vehicle_execution_status.js autodrive_console/web/vehicle_execution_status.css frontend/vite.config.js frontend/test/vehicle-execution-status.test.mjs frontend/test/dev-preview-proxy.test.mjs
git commit -m "feat: add vehicle execution status display"
~~~

### Task 5: Integration regression and delivery review

**Files:**
- Modify: tests/test_vehicle_execution_status.py only if integration uncovers an untested contract boundary.
- Modify: shared/contracts/task_execution.md only if implementation names differ from the closed contract.

**Interfaces:**
- Consumes: completed monitor/API/page.
- Produces: evidence of read-only behavior, stale-data fail-closed behavior, and no regression to legacy shell pages.

- [ ] **Step 1: Add the stale-event boundary test before a correction**

~~~python
def test_nonterminal_event_cannot_extend_expired_navigation():
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 20.0, freshness_s=4.0)
    monitor.observe_navigation(FakeNavigation(status="running"), received_at=1.0)
    monitor.observe_task(FakeTask(status_code="200"), received_at=19.0)
    assert monitor.status()["phase"] == "unavailable"
~~~

- [ ] **Step 2: Run the boundary test**

Run: pixi run pytest tests/test_vehicle_execution_status.py -q

Expected: PASS if the earlier freshness contract is already satisfied; otherwise FAIL before changing production code.

- [ ] **Step 3: Make only a contract-preserving correction if Step 2 fails**

Correct the exact monitor/classifier branch covered by the test. Do not add stale-code, filename, or process-state guesses. Keep ExecutionSnapshot.to_public_dict() limited to phase and label.

- [ ] **Step 4: Run required final checks**

Run:

~~~bash
scripts/test-backend.sh
scripts/test-web.sh
git diff --check
git status --short
~~~

Expected: Backend and Web checks pass, no whitespace errors, and any user-owned pre-existing dirty files remain untouched.

- [ ] **Step 5: Verify the unavailable runtime response**

Run the console with the monitor unavailable or mocked, then:

~~~bash
curl -s http://127.0.0.1:8087/api/vehicle-execution-status
~~~

Expected:

~~~json
{"phase":"unavailable","label":"状态暂不可用"}
~~~

Confirm the route remains visually minimal and static in that state.

- [ ] **Step 6: Commit verification-only fixes if files changed**

~~~bash
git add tests/test_vehicle_execution_status.py shared/contracts/task_execution.md autodrive_console/vehicle_execution_status
git commit -m "test: cover vehicle execution status boundaries"
~~~

Run this command only if Task 5 changed tracked files.

## Plan Self-Review

**Spec coverage:** Task 1 covers the closed state vocabulary, code reuse, exact semantic precedence, completion, and fail-closed classification. Task 2 covers persistent volatile subscriptions, freshness, ROS-unavailable degradation, thread-safe snapshots, and controlled restart activity. Task 3 covers lifecycle, API, no-cache behavior, shell isolation, and the contract. Task 4 covers the isolated route, approved visual behavior, animation safety, response ordering, Vite proxy, and the sole dashboard change. Task 5 covers stale-event safety and final Backend/Web verification.

**Clarification resolved:** The approved design mentioned parsing XML target_floor, but the minimal API/page have no consumer for that field. This plan intentionally normalizes only approved behavior-tree basenames and does not read XML. A future consumer that needs floor data must introduce a separately tested, path-confined parser and amend the shared contract first.

**Placeholder scan:** No task depends on an undefined API, generic error-handling instruction, or deferred implementation. The final conditional commit is explicitly restricted to changed tracked files.

**Type consistency:** The monitor produces dict[str, str] through ExecutionSnapshot.to_public_dict(). The HTTP adapter returns it unchanged. The Web module consumes only those two strings and does not derive robot state. RunManager.dependency_restart_active() is the sole non-ROS input for restarting_nodes.
