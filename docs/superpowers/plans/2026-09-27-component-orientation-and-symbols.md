# Component Orientation and Symbols Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make component direction derive from physical geometry and the automatic route, while removing persistent component arrows without changing the guided deployment UI.

**Architecture:** `execution_chain.py` becomes the single source of crossing geometry: barrier components cross their long face along local Y and choose sides from adjacent automatic nodes. The deployment canvas renders neutral component symbols and leaves only task-transition pose arrows. The shared deployment contract records the new separation between geometry and robot pose.

**Tech Stack:** Python 3.10, existing task compiler, Canvas 2D, HTML/ES modules, Node test runner, Pixi.

**Spec:** `docs/superpowers/specs/2026-09-27-component-orientation-and-symbols-design.md`

## Global Constraints

- Do not alter the deployment page shell, left navigation, guided task gating, or map-editor layout.
- Components never display a persistent traversal arrow; only task-transition pose markers do.
- Gates and automatic doors retain existing controlled behavior-tree actions and strict numeric device-ID export validation.
- Existing saved component yaw values remain physical orientation data; no map-data migration or manual correction is required.
- Do not commit, push, or stage changes unless the user explicitly asks.

---

### Task 1: Derive controlled-barrier crossing from physical door geometry

**Files:**
- Modify: `autodrive_console/execution_chain.py:248-307`
- Modify: `tests/test_task_compiler.py`

**Interfaces:**
- `_access_nodes(asset, component, previous, following) -> list[ExecutionNode]` continues to emit `open_go`, `close_go`, `open_back`, `close_back` data.
- New private `_barrier_traversal_points(asset, component, previous, following) -> tuple[dict[str, float], dict[str, float], str]` returns entry, exit and speed from local-Y faces.

- [ ] **Step 1: Write the failing physical-crossing tests.**

```python
@pytest.mark.parametrize("kind", ["gate", "auto_door"])
def test_compiler_crosses_a_horizontal_barrier_perpendicular_to_its_long_edge(two_map_project, kind):
    barrier = configured_access_component(kind, x=3.0, y=0.0, yaw=0.0, width=2.0, height=1.0)
    two_map_project["components"].append(barrier)
    _set_execution_nodes(two_map_project, target=[{"kind": "component", "id": barrier["id"]}])

    outbound = _compile(two_map_project).task_json["subtasks"][1]["waypoints"]

    assert [(point["pose"]["position"]["x"], point["pose"]["position"]["y"]) for point in outbound[1:3]] == [(3.0, -0.5), (3.0, 0.5)]
```

- [ ] **Step 2: Run the focused test and verify it fails under the local-X implementation.**

Run: `pixi run pytest tests/test_task_compiler.py -k horizontal_barrier -q`\
Expected: FAIL because points are generated at `(2.0, 0.0)` and `(4.0, 0.0)`.

- [ ] **Step 3: Implement the minimal local-Y barrier derivation.**

```python
def _barrier_traversal_points(asset, component, previous, following):
    center, width, height, speed = _region_geometry(component)
    axis_x, axis_y = -sin(center["yaw"]), cos(center["yaw"])
    negative = {"x": center["x"] - axis_x * height / 2, "y": center["y"] - axis_y * height / 2}
    positive = {"x": center["x"] + axis_x * height / 2, "y": center["y"] + axis_y * height / 2}
    entry, exit_point = _ordered_opposite_faces(previous, following, center, negative, positive, component)
    travel_yaw = atan2(exit_point["y"] - entry["y"], exit_point["x"] - entry["x"])
    entry["yaw"] = exit_point["yaw"] = travel_yaw
    return entry, exit_point, speed
```

`_ordered_opposite_faces` must compare each adjacent node’s signed projection on the local-Y normal, reject same-side or centreline approach with a map-repair error, and validate both emitted map points. Replace `_traversal_points` only in `_access_nodes`; do not alter passive-region rules.

- [ ] **Step 4: Add reversed-route and same-side rejection tests; run green.**

```python
def test_compiler_mirrors_barrier_actions_on_return(two_map_project):
    preview = _compile(project_with_vertical_gate())
    assert [node["action"] for node in preview.manifest["execution_chain"]["target"]["return"][:2]] == ["open_back", "close_back"]

def test_compiler_rejects_a_route_that_does_not_cross_both_barrier_faces(two_map_project):
    with pytest.raises(CompilationError, match="门体没有被任务路径从两侧穿过"):
        _compile(project_with_same_side_auto_door())
```

Run: `pixi run pytest tests/test_task_compiler.py -k 'barrier or controlled_gate' -q`\
Expected: PASS.

### Task 2: Render neutral component symbols while preserving task-pose markers

**Files:**
- Modify: `autodrive_console/web/deployment.js:1621-1785,2387-2392`
- Modify: `autodrive_console/web/deployment.html:414`
- Modify: `frontend/test/deployment-workflow.test.mjs`

**Interfaces:**
- `drawComponentSymbol(item, px, py)` renders no component traversal arrow.
- `drawWaypointSymbol(point, px, py)` continues to render the task-transition yaw arrow.

- [ ] **Step 1: Write failing source-level canvas regression tests.**

```javascript
test("component symbols do not draw traversal arrows but task transitions retain their pose marker", () => {
  assert.doesNotMatch(deploymentSource, /drawTraversalDirectionArrow/);
  assert.match(deploymentSource, /function drawWaypointSymbol[\s\S]*context\.lineTo\(22, 0\)/);
  assert.doesNotMatch(deploymentPage, /组件箭头表示穿越方向/);
});
```

- [ ] **Step 2: Run the focused test and verify it fails because the renderer still calls `drawTraversalDirectionArrow`.**

Run: `node --test --test-name-pattern='component symbols do not draw traversal arrows' frontend/test/deployment-workflow.test.mjs`\
Expected: FAIL on the `drawTraversalDirectionArrow` match.

- [ ] **Step 3: Remove persistent directional decoration from components.**

Delete `drawTraversalDirectionArrow` and its gate/auto-door call. Replace the start/target triangle with the same neutral circular anchor treatment already used by the marker. Retain door leaves, gate bars, elevator door marker, region texture, labels, selection border, resize handle and rotation handle. Replace the directional hint copy with: `组件长边表示设施门面；系统会按当前自动路径推导通行、开门和关门顺序。` and show it only for gate/auto-door.

- [ ] **Step 4: Run the focused test and visual source checks.**

Run: `node --test --test-name-pattern='component symbols do not draw traversal arrows' frontend/test/deployment-workflow.test.mjs`\
Expected: PASS.

Run: `rg -n 'drawTraversalDirectionArrow|组件箭头表示穿越方向' autodrive_console/web/deployment.*`\
Expected: no output.

### Task 3: Synchronize contract and verify the real editor

**Files:**
- Modify: `shared/contracts/deployment.md:153-164`
- Modify: `docs/superpowers/specs/2026-09-27-component-orientation-and-symbols-design.md`

**Interfaces:**
- Existing project JSON preserves `yaw`; new wording says yaw is geometric orientation and automatic execution order determines crossing side.

- [ ] **Step 1: Add the cross-layer contract assertion.**

```javascript
test("deployment contract distinguishes neutral components from directed task transitions", () => {
  assert.match(contract, /闸机与自动门.*门面法线/);
  assert.match(contract, /任务过渡点.*yaw/);
  assert.doesNotMatch(contract, /组件箭头.*穿越方向/);
});
```

- [ ] **Step 2: Run the contract test and verify it fails until wording is updated.**

Run: `node --test frontend/test/deployment-workflow.test.mjs`\
Expected: FAIL with missing door-face-normal contract wording.

- [ ] **Step 3: Update the Existing contract and run targeted verification.**

State consumers (`execution_chain.py`, task compiler and deployment canvas), no data migration, the barrier two-face validation, and retained task-transition yaw. Do not change any ROS/HTTP/WebSocket interface.

Run: `pixi run pytest tests/test_task_compiler.py -q && pixi run node --test frontend/test/deployment-workflow.test.mjs`\
Expected: both pass.

- [ ] **Step 4: Run browser QA against the existing server without mutating project data.**

Run: `agent-browser open http://127.0.0.1:8087/deployment.html && agent-browser snapshot -i -c`\
Expected: original sidebar and progressive guide remain.

Open existing gate/auto-door/region components only; do not save, create or delete.\
Expected: no internal arrow in gate/automatic-door symbols, rotation handle remains, and task-transition marker remains directed.

### Task 4: Full verification and handoff

**Files:**
- Modify: none unless a failing regression exposes a scoped defect.

- [ ] **Step 1: Run all required affected checks.**

Run: `./scripts/test-backend.sh`\
Run: `./scripts/test-web.sh`\
Run: `git diff --check`

Expected: relevant component tests pass, Vite build passes and diff check is clean. If the known independent video ABI assertion fails, record its exact failure separately and do not modify video code in this task.

- [ ] **Step 2: Review changed files for guided-UI scope.**

Run: `git diff -- autodrive_console/web/deployment.html autodrive_console/web/deployment.css autodrive_console/web/deployment.js`\
Expected: only icon rendering and existing component-help copy change; no page shell, sidebar, guide or task-gating changes.

- [ ] **Step 3: Handoff without committing or pushing.**

Report changed files, focused/full verification commands, browser QA result and any pre-existing unrelated failure. Leave all changes uncommitted for the user to push.
