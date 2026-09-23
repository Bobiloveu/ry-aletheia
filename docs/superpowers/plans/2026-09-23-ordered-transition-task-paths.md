# Ordered Transition Task Paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist an explicit per-map order for manual transition waypoints, compile that order into outbound and reversed return task JSON, and make incomplete ordering visible and blocking in the deployment workflow.

**Architecture:** `localization_routes.task_paths` becomes the only persisted ordering authority. `DeploymentStore` strictly normalizes new saves, while the pure task compiler independently validates old snapshots and inserts transition points without creating behavior-tree artifacts. The route editor owns only an immutable draft; the Backend response remains authoritative after save, and the existing task preview exposes the compiled point-by-point order.

**Tech Stack:** Python 3.10, pytest, vanilla ES modules, Node.js test runner, HTML/CSS, existing Pixi test tasks.

**Spec:** `docs/superpowers/specs/2026-09-23-ordered-transition-task-paths-design.md`

## Global Constraints

- Keep this feature inside the existing project snapshot, HTTP API, route editor, and experimental compiler boundaries.
- Do not write robot runtime directories, start or stop ROS/Supervisor, install artifacts, or execute a generated task.
- Do not add speed modes or behavior-tree XML; every transition waypoint uses `single_point` and an empty `waypoint_task_id`.
- Preserve each transition waypoint's original ID, `x`, `y`, and `yaw`; return paths reverse only list order, never orientation.
- Do not infer ordering from coordinates, labels, creation time, `routes`, or `map_transitions`.
- Existing routes without `task_paths` remain compilable only when their selected maps contain no manual transition waypoints.
- Mobile is not a consumer. The affected consumers are `robot_backend` and PC `web_console` only.
- Preserve unrelated dirty-worktree changes and keep the running Backend/Vite previews available throughout execution.

## File and Responsibility Map

- `shared/contracts/deployment.md`: Existing API schema, compatibility behavior, compiler sequencing, error contract, and affected-consumer record.
- `autodrive_console/deployment.py`: strict route-save normalization, transition ownership validation, reference protection, and preview invalidation.
- `autodrive_console/task_compiler.py`: pure snapshot validation, ordered transition resolution, JSON insertion, derived metadata, and fingerprint facts.
- `autodrive_console/web/deployment/localization-route.js`: immutable route-draft operations and path diagnostics.
- `autodrive_console/web/deployment.js`: route editor rendering/events/payload and point-level task preview rendering.
- `autodrive_console/web/deployment.html`: explanatory copy and accessible preview/editor structure where a new container is required.
- `autodrive_console/web/deployment.css`: ordered path, pending-point, invalid-state, preview detail, theme, and narrow-screen styles.
- `tests/test_deployment.py`: store/API contract, reference integrity, and preview invalidation regression tests.
- `tests/test_task_compiler.py`: exact task ordering, field semantics, compatibility, fingerprint, and ZIP regressions.
- `frontend/test/deployment/localization-route.test.mjs`: pure route-draft ordering tests.
- `frontend/test/deployment-workflow.test.mjs`: DOM/source contract tests for editor blocking and preview details.

---

### Task 1: Extend the Existing Contract and Backend Route Authority

**Files:**
- Modify: `shared/contracts/deployment.md:85-140`
- Modify: `autodrive_console/deployment.py:662-861`
- Modify: `autodrive_console/deployment.py:1384-1417`
- Test: `tests/test_deployment.py:720-923`
- Test: `tests/test_deployment.py:1570-1660`

**Interfaces:**
- Consumes: persisted localization bindings, waypoints, and route payloads accepted by `create_localization_route()` and `update_localization_route()`.
- Produces: normalized `task_paths: list[{binding_id: str, transition_waypoint_ids: list[str]}]`.
- Produces: `_normalise_localization_task_paths(document, source, bindings)`, task-path reference protection, and waypoint-write preview invalidation.

- [ ] **Step 1: Update the Existing contract before changing its consumers**

Document the strict seven-key route request, including:

~~~json
"task_paths": [
  {"binding_id": "localization-a", "transition_waypoint_ids": []},
  {"binding_id": "localization-b", "transition_waypoint_ids": ["waypoint-transition-a"]}
]
~~~

State that new saves require the field; old snapshots may omit it only when no selected map has a manual transition; every manual transition on selected maps must be assigned exactly once; invalid or incomplete paths produce HTTP 422 and tell the operator to open the localization route and finish ordering. Replace the old “速度沿用其后继点” rule with the fixed pure-navigation fields and the four subtask sequences from the approved spec.

- [ ] **Step 2: Add failing store tests for canonical order and strict ownership**

Extend all new-save fixtures with one path per binding and remove legacy `task_return_waypoint_id` from POST/update fixtures; compatibility is tested by loading persisted snapshots, not by accepting the old field on new writes. Add a canonicalization test:

~~~python
saved = store.create_localization_route(project["id"], {
    **payload,
    "task_paths": [
        {"binding_id": bindings[-1]["id"], "transition_waypoint_ids": [target_b["id"], target_a["id"]]},
        {"binding_id": bindings[0]["id"], "transition_waypoint_ids": [lobby_a["id"]]},
        {"binding_id": bindings[1]["id"], "transition_waypoint_ids": []},
    ],
})
assert [item["binding_id"] for item in saved["task_paths"]] == saved["binding_ids"]
assert saved["task_paths"][-1]["transition_waypoint_ids"] == [target_b["id"], target_a["id"]]
~~~

Parameterize invalid saves for: missing `task_paths`, missing/duplicate binding entries, duplicate waypoint within or across paths, missing waypoint ID, wrong map, non-transition kind, component-generated waypoint, and an unassigned manual transition. Match an actionable message containing the affected map and point label/ID.

- [ ] **Step 3: Run the route tests and confirm the new expectations fail**

Run:

~~~bash
pixi run python -m pytest -q tests/test_deployment.py -k 'localization_route or waypoint_preview'
~~~

Expected: failures show that `task_paths` is not accepted or validated and waypoint writes do not invalidate preview state.

- [ ] **Step 4: Implement strict route-path normalization**

Accept exactly `building`, `unit`, `binding_ids`, `task_start_waypoint_id`, `task_target_waypoint_id`, `links`, and `task_paths`. Reject new POST/update payloads containing legacy `task_return_waypoint_id` or omitting `task_paths`; persisted snapshots remain readable because the read path does not rewrite them, and old-snapshot task compatibility belongs in the compiler.

Implement:

~~~python
def _normalise_localization_task_paths(
    self,
    document: dict[str, Any],
    source: object,
    bindings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate complete per-binding manual-transition order and return binding order."""
~~~

The helper validates exact item keys, binding-set equality, per-path and route-wide uniqueness, waypoint existence, `kind == "transition"`, absence of `generated_by`, and binding-map ownership. Compare assigned IDs with every manual transition on the selected binding maps. Return entries in `binding_ids` order. Errors name the map and point and incomplete-assignment errors end with “打开定位路线并完成过渡点排序”. Store the normalized result in the route.

- [ ] **Step 5: Protect path references and invalidate preview state**

Extend `_localization_route_references_waypoint()`:

~~~python
or any(
    waypoint_id in path.get("transition_waypoint_ids", [])
    for path in route.get("task_paths", [])
    if isinstance(path, dict)
)
~~~

Call `_invalidate_task_compiler_preview(document)` after a successful waypoint append and after a successful unreferenced waypoint removal, before persisting.

- [ ] **Step 6: Add and run invalidation/reference tests**

Generate a preview, verify deletion of a routed transition is rejected, then verify adding or deleting an unreferenced manual point clears `last_preview_input_sha256`.

Run:

~~~bash
pixi run python -m pytest -q tests/test_deployment.py -k 'localization_route or waypoint_preview or compiler_route'
~~~

Expected: all selected tests pass.

- [ ] **Step 7: Commit the contract and Backend route authority**

~~~bash
git add shared/contracts/deployment.md autodrive_console/deployment.py tests/test_deployment.py
git commit -m "feat: validate ordered transition task paths"
~~~

---

### Task 2: Compile Ordered Transition Points into the Four Task Segments

**Files:**
- Modify: `autodrive_console/task_compiler.py:78-223`
- Modify: `autodrive_console/task_compiler.py:534-713`
- Test: `tests/test_task_compiler.py:16-150`
- Test: `tests/test_task_compiler.py:338-489`

**Interfaces:**
- Consumes: normalized or legacy routes, selected lobby/floor bindings, and manual waypoint facts.
- Produces: `_assert_selected_localization_artifacts(...) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]`, ordered as selected route, lobby binding, floor binding.
- Produces: `_ordered_transition_waypoints(project, route, bindings) -> dict[str, tuple[dict[str, Any], ...]]`.
- Produces: `_task_json(value, points, task_paths, lobby_binding_id, floor_binding_id)` with exact outbound/return insertion order.

- [ ] **Step 1: Make the default fixture canonical**

Remove `task_return_waypoint_id` from the canonical fixture and helper, then add empty paths to the default two-map route and to `_add_store_localization_route()`:

~~~python
"task_paths": [
    {"binding_id": "lobby-binding", "transition_waypoint_ids": []},
    {"binding_id": "floor-binding", "transition_waypoint_ids": []},
],
~~~

This keeps the current zero-transition JSON as an exact regression baseline.

- [ ] **Step 2: Add failing exact-sequence and field tests**

Add two lobby and two target transitions in an order that differs from coordinates and creation order. Assert:

~~~python
assert [[point["waypoint_id"] for point in subtask["waypoints"]] for subtask in subtasks] == [
    ["lobby_start", "lobby-b", "lobby-a", "lobby_wait", "lobby_elevator_center"],
    ["target_wait", "target-a", "target-b", "target"],
    ["target-b", "target-a", "target_return_wait", "target_return_elevator_center"],
    ["lobby_return_wait", "lobby-a", "lobby-b", "lobby_return_start"],
]
~~~

For every transition occurrence assert blank `waypoint_task_id`, false `is_task_point`, `single_point`, false `is_backward`, true `is_single_point`, the saved pose, and original ID. Also assert no additional XML member, ZIP task JSON equals preview JSON, and `derived_points["transition:<id>"]` exists.

- [ ] **Step 3: Add failing compatibility, integrity, and fingerprint tests**

Add two explicit compatibility tests:

~~~python
def test_old_route_without_task_paths_still_compiles_without_transitions(two_map_project):
    two_map_project["localization_routes"][0].pop("task_paths")
    preview = _compile(two_map_project)
    assert [len(item["waypoints"]) for item in preview.task_json["subtasks"]] == [3, 2, 2, 2]


def test_old_route_without_task_paths_blocks_unassigned_transitions(two_map_project):
    two_map_project["localization_routes"][0].pop("task_paths")
    two_map_project["waypoints"].append({
        "id": "target-transition",
        "map_asset_id": "target-map",
        "kind": "transition",
        "label": "目标层过渡点",
        "x": 3.0,
        "y": 2.0,
        "yaw": 0.5,
    })
    with pytest.raises(CompilationError, match="打开定位路线并完成过渡点排序"):
        _compile(two_map_project)
~~~

Add a parameterized integrity test covering missing/duplicate binding paths, duplicate IDs, missing IDs, wrong maps, wrong kinds, and generated points. Add fingerprint tests that compile once, swap two `transition_waypoint_ids`, compile again, and assert unequal hashes; then repeat with one referenced point's `x`, `yaw`, and `kind`.

- [ ] **Step 4: Run focused compiler tests and verify failure**

~~~bash
pixi run python -m pytest -q tests/test_task_compiler.py -k 'transition or fingerprint or approved_speed_sequence or gk1_store_preview'
~~~

Expected: new tests fail because only fixed points are emitted.

- [ ] **Step 5: Return selected route facts from localization validation**

Change `_assert_selected_localization_artifacts()` to return `(selected_route, lobby_binding, floor_binding)` after current checks. Preserve existing errors and call it before resolving paths.

- [ ] **Step 6: Resolve and validate ordered paths in the pure compiler**

Implement:

~~~python
def _ordered_transition_waypoints(
    project: dict[str, Any],
    route: dict[str, Any],
    bindings: tuple[dict[str, Any], ...],
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Resolve a complete explicit route order without mutating the project."""
~~~

For missing `task_paths`, return empty tuples only if selected maps contain no manual transition. Otherwise raise the recovery error. For present paths, repeat Backend integrity checks because persisted JSON is not trusted. Validate finite geometry and map bounds before returning copied waypoint dictionaries.

- [ ] **Step 7: Insert transitions without behavior-tree artifacts**

Add:

~~~python
def _transition_waypoint(point: dict[str, Any]) -> dict[str, Any]:
    return _waypoint(
        str(point["id"]),
        _point_dict(point),
        "single_point",
        "",
        is_task_point=False,
    )
~~~

Build all four waypoint lists in spec order. Use `reversed(target_transitions)` and `reversed(lobby_transitions)` without changing yaw. Do not alter XML names/templates.

- [ ] **Step 8: Include path facts in preview metadata and hashing**

Add `transition:<waypoint-id>` entries to `derived`, add canonical paths to `manifest["task_paths"]`, and extend `_route_waypoint_facts()` with task-path IDs plus `kind` and `generated_by`. The route object supplies order; facts supply referenced content.

- [ ] **Step 9: Run compiler/store integration tests**

~~~bash
pixi run python -m pytest -q tests/test_task_compiler.py tests/test_deployment.py -k 'task_compiler or localization_route or transition'
~~~

Expected: all selected tests pass and the original empty-path sequence stays unchanged.

- [ ] **Step 10: Commit compiler behavior**

~~~bash
git add autodrive_console/task_compiler.py tests/test_task_compiler.py
git commit -m "feat: compile ordered transition waypoints"
~~~

---

### Task 3: Add Immutable Route-Draft Path Operations

**Files:**
- Modify: `autodrive_console/web/deployment/localization-route.js:1-66`
- Test: `frontend/test/deployment/localization-route.test.mjs`

**Interfaces:**
- Consumes: route drafts, selected bindings, and project waypoints.
- Produces: `routeTaskPathState(draft, bindings, waypoints)` with `{binding, ordered, unassigned, issues}`.
- Produces: immutable `assignRouteTransition()`, `removeRouteTransition()`, `moveRouteTransition()`, and `placeRouteTransition()`.

- [ ] **Step 1: Add failing diagnostics tests**

Verify ordered and pending points:

~~~javascript
const state = routeEditor.routeTaskPathState(route, bindings, waypoints);
assert.deepEqual(state[0].ordered.map((item) => item.id), ["lobby-b", "lobby-a"]);
assert.deepEqual(state[1].unassigned.map((item) => item.id), ["target-b"]);
assert.deepEqual(state.flatMap((item) => item.issues), []);
~~~

Add cases for missing IDs, wrong maps, duplicates, generated points, and newly selected bindings. Every operation must leave its input deeply unchanged.

- [ ] **Step 2: Add failing pointer/keyboard order-parity tests**

~~~javascript
const moved = routeEditor.moveRouteTransition(route, "floor-binding", "target-c", -1);
const placed = routeEditor.placeRouteTransition(route, "floor-binding", "target-c", "target-b");
assert.deepEqual(moved.task_paths, placed.task_paths);
~~~

Also test append-once assignment, removal to the derived pending collection, boundary no-ops, and cross-binding de-duplication.

- [ ] **Step 3: Run the helper test and confirm failure**

~~~bash
cd frontend && node --test test/deployment/localization-route.test.mjs
~~~

Expected: new exports are absent.

- [ ] **Step 4: Implement immutable path helpers**

Persist only:

~~~javascript
{ binding_id: "floor-binding", transition_waypoint_ids: ["target-a", "target-b"] }
~~~

`routeTaskPathState()` derives pending/invalid state but never writes it into the payload. `placeRouteTransition()` removes a point from every path, then inserts it before `beforeWaypointId` or at the end. `moveRouteTransition()` delegates to it. Update `withBindingIds()` so retained bindings keep copied paths, new bindings get empty paths, and output follows binding order. `resetRouteDraft()` returns `task_paths: []`.

- [ ] **Step 5: Run pure-state tests**

~~~bash
cd frontend && node --test test/deployment/localization-route.test.mjs
~~~

Expected: all route editor tests pass.

- [ ] **Step 6: Commit draft logic**

~~~bash
git add autodrive_console/web/deployment/localization-route.js frontend/test/deployment/localization-route.test.mjs
git commit -m "feat: add transition path draft operations"
~~~

---

### Task 4: Make Route Ordering and Point-Level Preview Explicit

**Files:**
- Modify: `autodrive_console/web/deployment.js:1-30`
- Modify: `autodrive_console/web/deployment.js:150-217`
- Modify: `autodrive_console/web/deployment.js:967-1168`
- Modify: `autodrive_console/web/deployment.js:2500-2560`
- Modify: `autodrive_console/web/deployment.html:544-562`
- Modify: `autodrive_console/web/deployment.html:692-704`
- Modify: `autodrive_console/web/deployment.css:1232-1375`
- Modify: `autodrive_console/web/deployment.css:2800-2871`
- Test: `frontend/test/deployment-workflow.test.mjs`

**Interfaces:**
- Consumes: Task 3 helper exports and Backend-normalized routes.
- Produces: canonical path payloads, explicit pending blockers, accessible pointer/keyboard ordering, and compiled waypoint details in both preview surfaces.

- [ ] **Step 1: Add failing Web source/markup tests**

Assert source coverage for `task_paths`, `routeTaskPathState`, add/move/remove data attributes, draggable rows, `Alt+ArrowUp/ArrowDown`, and the labels “纯导航”, “无行为树”, and `single_point`. Assert CSS provides wrapping point rows, pending/error/focus/drag states, light theme rules, and narrow-screen one-column fallback. Assert task preview renders nested waypoint rows, not counts only.

- [ ] **Step 2: Run the Web workflow test and confirm failure**

~~~bash
cd frontend && node --test test/deployment-workflow.test.mjs
~~~

Expected: new controls and point-level preview labels are absent.

- [ ] **Step 3: Wire canonical paths into draft, validation, and payload**

In `openLocalizationRoute()`, copy persisted paths; for an old route initialize empty paths so existing transitions appear pending rather than being guessed. Submit:

~~~javascript
task_paths: localizationRouteDraft.task_paths.map((path) => ({
  binding_id: path.binding_id,
  transition_waypoint_ids: [...path.transition_waypoint_ids],
})),
~~~

Add state issues and pending points to `routeValidation()`; messages name their map and point. Save remains blocked until resolved. Keep `renderProject(data.project)` after save so the server-normalized order replaces the draft.

- [ ] **Step 4: Render each map as an explicit path**

Show fixed endpoints and ordered transition rows:

~~~text
大厅：任务起点 → [过渡点] → 候梯点 → 电梯中心
目标层：出梯/候梯点 → [过渡点] → 任务目标
~~~

Each assigned point shows label, coordinates, yaw, and “纯导航 · 无行为树 · single_point”, plus up/down/remove controls. Add `tabindex="0"`, `draggable="true"`, binding ID, and transition ID. Pending points show “加入路径”; invalid saved references remain visible as blockers.

- [ ] **Step 5: Implement pointer and keyboard ordering**

Use delegated click events for add/remove/up/down. Add `dragstart`, `dragover`, and `drop` using `placeRouteTransition()`. Add delegated `keydown` so `Alt+ArrowUp` and `Alt+ArrowDown` call `moveRouteTransition()`, rerender, and restore focus. Never mutate `selectedProject` before the save response.

- [ ] **Step 6: Render point-level task preview**

Expand each subtask's waypoints in JSON order in both preview surfaces. Identify a transition using all three facts: empty task ID, false task point, and `single_point`. Display:

~~~text
过渡点名或 waypoint_id · 纯导航 · 无行为树 · single_point
~~~

Other points show waypoint ID, speed mode, and behavior-tree task ID when present. Keep download disabled for every non-ready preview.

- [ ] **Step 7: Add responsive and theme-safe styles**

Use `minmax(0, 1fr)`, `overflow-wrap: anywhere`, wrapping action rows, and no fixed path-row width. Add visible focus, drag target, pending warning, invalid error, dark/light styles. Collapse path rows and preview detail to one column under the existing narrow breakpoint without horizontal overflow.

- [ ] **Step 8: Run focused Web tests**

~~~bash
cd frontend && node --test test/deployment/localization-route.test.mjs test/deployment-workflow.test.mjs
~~~

Expected: all focused tests pass.

- [ ] **Step 9: Commit route editor and preview UI**

~~~bash
git add autodrive_console/web/deployment.js autodrive_console/web/deployment.html autodrive_console/web/deployment.css frontend/test/deployment-workflow.test.mjs
git commit -m "feat: expose ordered transition paths in deployment"
~~~

---

### Task 5: Verify the Full Contract Without Mutating Robot Runtime

**Files:**
- Verify: the approved spec and every file changed in Tasks 1-4.
- Modify only when a verification failure requires a scoped correction.

**Interfaces:**
- Consumes: completed Backend and Web implementation.
- Produces: test evidence, live-preview evidence, and a clear statement of any existing project path that still requires an operator save.

- [ ] **Step 1: Run the complete Backend check**

~~~bash
scripts/test-backend.sh
~~~

Expected: the complete suite passes without regressions in bundle contents, localization manifests, upgrade/runtime behavior, or unrelated APIs.

- [ ] **Step 2: Run the complete Web check**

~~~bash
scripts/test-web.sh
~~~

Expected: the complete frontend check passes and no generated build/cache artifact is staged.

- [ ] **Step 3: Confirm both previews remain available**

~~~bash
curl -fsS -o /dev/null http://127.0.0.1:8087/deployment.html
curl -fsS -o /dev/null http://127.0.0.1:5173
~~~

Expected: both exit 0. If a service stopped, restart only that existing preview command; do not start duplicate processes.

- [ ] **Step 4: Perform live browser QA without auto-saving user data**

Open “高科1号” and verify its existing target-map transition appears under “待编排”, with an explicit blocker and no ready preview/download state. Add it to the draft, exercise drag and `Alt+ArrowUp/ArrowDown`, and verify draft order changes. Leave the actual project unsaved unless the user explicitly saves or asks us to save it.

At desktop and narrow widths in light/dark themes verify: fixed endpoints are unambiguous; long labels/IDs wrap; controls retain visible focus; no horizontal overflow occurs; closing/reopening restores persisted Backend state rather than abandoned draft.

- [ ] **Step 5: Exercise a controlled preview and ZIP**

Use a disposable pytest project, not robot runtime directories. Confirm a target transition appears in outbound order and reversed return order, with blank behavior tree and `single_point`; confirm no extra XML and exact preview/ZIP task JSON equality.

- [ ] **Step 6: Review final scope**

~~~bash
git diff --check
git status --short
git diff -- shared/contracts/deployment.md autodrive_console/deployment.py autodrive_console/task_compiler.py autodrive_console/web/deployment/localization-route.js autodrive_console/web/deployment.js autodrive_console/web/deployment.html autodrive_console/web/deployment.css tests/test_deployment.py tests/test_task_compiler.py frontend/test/deployment/localization-route.test.mjs frontend/test/deployment-workflow.test.mjs
~~~

Expected: no whitespace errors, no unrelated staged files, and every behavior maps to the approved spec. If verification requires a correction, stage only scoped files and commit with `fix: complete transition task path verification`.
