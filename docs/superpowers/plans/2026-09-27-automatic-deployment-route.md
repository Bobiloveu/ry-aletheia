# Automatic Deployment Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate every deployment-map route and component execution order from the saved scene flow and map markings, while preserving the existing progressive deployment UI.

**Architecture:** A pure Backend route derivation module reads the scene-stage map order, mandatory anchors and each map's occupancy grid. It produces a single persisted audit route containing ordered `execution_nodes`; the compiler and localization manifest consume that same result. The existing route-confirmation card remains in place, but changes from form editing to a read-only derived-result view with actionable map-fix errors.

**Tech Stack:** Python 3.10, existing `DeploymentStore`, PGM occupancy maps, HTML/ES modules, Node test runner, Pixi test scripts.

**Spec:** `docs/superpowers/specs/2026-09-27-automatic-deployment-route-design.md`

## Global Constraints

- Scene order is `deployment_flow` plus saved stage assignments; browser input never supplies map or node order.
- A* uses only imported project map snapshots and never writes robot maps, ROS, Supervisor or runtime task directories.
- The same derived chain must drive UI evidence, task JSON, `loc_yaml_path.json` and behavioral action expansion.
- Keep the current task-console, guide and panel gating structure; do not redesign the page shell.
- Do not commit, push, or stage changes unless the user explicitly requests it.

---

### Task 1: Deterministic map-local route derivation

**Files:**
- Create: `autodrive_console/automatic_route.py`
- Create: `tests/test_automatic_route.py`

**Interfaces:**
- Produces `AutomaticRouteError(ValueError)` for repairable project facts.
- Produces `derive_localization_routes(project: dict[str, Any]) -> list[dict[str, Any]]`.
- Each result contains `binding_ids`, `task_start_waypoint_id`, `task_target_waypoint_id`, elevator `links`, and ordered per-binding `execution_nodes`.

- [ ] **Step 1: Write failing tests for flow ownership and path order.**

```python
def test_derivation_uses_scene_flow_not_existing_route_or_marker_creation_order():
    project = project_with_lobby_and_floor_grid()
    project["localization_routes"] = [{"binding_ids": ["floor", "lobby"]}]
    project["waypoints"] += [transition("late", 4.0, 1.0), transition("early", 2.0, 1.0)]

    route = derive_localization_routes(project)[0]

    assert route["binding_ids"] == ["lobby", "floor"]
    assert route["execution_nodes"][0]["node_refs"] == [
        {"kind": "transition", "id": "early"},
        {"kind": "transition", "id": "late"},
    ]
```

- [ ] **Step 2: Run the focused test and confirm it fails because the derivation module does not exist.**

Run: `pixi run pytest tests/test_automatic_route.py -q`\
Expected: import failure for `autodrive_console.automatic_route`.

- [ ] **Step 3: Implement pure route derivation.**

```python
def derive_localization_routes(project: dict[str, Any]) -> list[dict[str, Any]]:
    stage_maps = _stage_maps(project, _index(project.get("map_assets"), "地图"))
    bindings = _ordered_bindings(_bindings(project), stage_maps)
    return [_derive_route(project, bindings)]

def _derive_map_node_refs(project, asset, map_id, start, end):
    path = _astar_map_path(asset, start, end)
    projections = [_project_candidate(path, item) for item in _task_candidates(project, map_id)]
    _reject_ambiguous_or_off_path(projections, asset)
    return [item.ref for item in sorted(projections, key=lambda item: item.arc_length)]
```

Implement occupancy-grid parsing from the imported PGM snapshot, nearest free-cell anchor lookup, deterministic 8-neighbour A*, path projection, and explicit errors for absent/ambiguous anchors, disconnected paths, off-path markers, conflicting elevator identity and indistinguishable projections. Return only IDs and no browser-owned order.

- [ ] **Step 4: Add failure tests and make them pass.**

```python
def test_derivation_rejects_off_path_transition_with_map_repair_message():
    with pytest.raises(AutomaticRouteError, match="回到地图调整标记"):
        derive_localization_routes(project_with_off_path_transition())

def test_derivation_reverses_target_return_from_last_outbound_transition():
    route = derive_localization_routes(project_with_target_transitions())[0]
    assert route["execution_nodes"][-1]["node_refs"][-1] == {"kind": "transition", "id": "target-last"}
```

Run: `pixi run pytest tests/test_automatic_route.py -q`\
Expected: all automatic-route tests pass.

### Task 2: Make `DeploymentStore` and compiler consume one derived chain

**Files:**
- Modify: `autodrive_console/deployment.py`
- Modify: `autodrive_console/task_compiler.py`
- Modify: `web_console.py`
- Modify: `shared/contracts/deployment.md`
- Modify: `tests/test_deployment.py`
- Modify: `tests/test_task_compiler.py`

**Interfaces:**
- Produces `DeploymentStore.derive_localization_routes(project_id: str) -> dict[str, Any]`.
- Adds `POST /api/deployments/{project_id}/localization-routes/derive` with an empty JSON object only.
- Compilation derives a fresh route first and does not accept stale/manual `execution_nodes`.

- [ ] **Step 1: Write failing API and compiler consistency tests.**

```python
def test_derive_route_endpoint_ignores_manual_route_order_and_persists_audit_chain(client, project_id):
    response = client.post(f"/api/deployments/{project_id}/localization-routes/derive", json={})
    assert response.status_code == HTTPStatus.OK
    route = response.json["project"]["localization_routes"][0]
    assert route["derivation"] == "scene-map-path-v1"
    assert route["binding_ids"] == expected_scene_order

def test_compiler_and_localization_manifest_use_last_target_chain_node_for_return(project):
    preview = compile_indoor_elevator(project)
    assert preview.manifest["execution_chain"]["target"]["return"][0]["source_id"] == "target-last"
    assert preview.loc_yaml["loc_yaml"][0]["yaml_index"][-1]["init_return"]["x"] == target_last_x
```

- [ ] **Step 2: Run tests and confirm they fail before the endpoint/derivation integration exists.**

Run: `pixi run pytest tests/test_deployment.py tests/test_task_compiler.py -q`\
Expected: missing derive endpoint or manual-route output mismatch.

- [ ] **Step 3: Integrate the pure derivation at the authoritative backend boundary.**

```python
def derive_localization_routes(self, project_id: str) -> dict[str, Any]:
    document = self.get(project_id)
    document["localization_routes"] = derive_localization_routes(document)
    self._invalidate_task_compiler_preview(document)
    self._write_json(self._document_path(project_id), document)
    return document
```

Expose the endpoint with strict empty-object validation. Before `compile_indoor_elevator` builds task/manifest files, derive the chain from the current project facts. Feed that chain into task-point expansion and localization manifest return pose so a target transition is the first return node. Update the Existing contract with endpoint request/response, automatic ownership, error behavior and consumers.

- [ ] **Step 4: Run targeted Backend verification.**

Run: `pixi run pytest tests/test_automatic_route.py tests/test_deployment.py tests/test_task_compiler.py -q`\
Expected: all targeted tests pass, including components, transitions, return reversal and blocked error cases.

### Task 3: Preserve the guided UI while replacing manual route controls with evidence

**Files:**
- Modify: `autodrive_console/web/deployment.js`
- Modify: `autodrive_console/web/deployment.html`
- Modify: `autodrive_console/web/deployment.css`
- Modify: `autodrive_console/web/deployment/localization-route.js`
- Modify: `frontend/test/deployment-workflow.test.mjs`
- Modify: `frontend/test/deployment/localization-route.test.mjs`

**Interfaces:**
- Web invokes only `POST .../localization-routes/derive` to refresh the route review.
- `automaticRouteBindings(route, bindings)` returns bindings in Backend order without any browser sorting.
- Existing `renderDeploymentTaskConsole()` and `applyDeploymentTaskGating()` remain the only progressive-disclosure authority.

- [ ] **Step 1: Write failing UI source tests.**

```javascript
test("route review preserves the guided surface but exposes no manual route ordering", () => {
  assert.match(deploymentSource, /localization-routes\/derive/);
  assert.doesNotMatch(deploymentSource, /data-route-move=|data-route-node-add=|data-route-node-move=/);
  assert.doesNotMatch(deploymentPage, /人工任务起点<select|选择路线地图/);
  assert.match(deploymentSource, /applyDeploymentTaskGating/);
  assert.match(deploymentPage, /deploymentTaskConsole/);
});
```

- [ ] **Step 2: Run the focused test and confirm it fails because manual controls remain.**

Run: `node --test --test-name-pattern='route review preserves the guided surface' frontend/test/deployment-workflow.test.mjs`\
Expected: failure matching a manual route-control marker.

- [ ] **Step 3: Replace only the route-card content, not the page shell.**

```javascript
async function refreshDerivedLocalizationRoutes() {
  const data = await request(`/api/deployments/${encodeURIComponent(selectedProject.id)}/localization-routes/derive`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
  });
  renderProject(data.project);
  renderLocalizationRouteDialog();
}
```

Keep the existing localization card, dialog container, current-task card, progress rail and map editor markup. Inside the route dialog, render the stored map order, fixed anchors and ordered components/transition points as non-editable evidence. On derivation failure, render the Backend repair message and a map-return action. Remove map checkboxes, endpoint/anchor selects, and all move/add/remove route buttons and handlers. Do not add a new sidebar, shell, wizard or expanded panel.

- [ ] **Step 4: Run Web checks and inspect the initial and route-review states.**

Run: `./scripts/test-web.sh`\
Expected: unit tests, parity check and Vite build pass.

Run: `agent-browser open http://127.0.0.1:8087/deployment.html && agent-browser snapshot -i -c`\
Expected: task console and current task gate the visible work area; no route-review manual inputs are present before a project reaches that step.

### Task 4: End-to-end guardrails and handoff

**Files:**
- Modify: `shared/contracts/deployment.md`
- Modify: `docs/superpowers/specs/2026-09-27-automatic-deployment-route-design.md`

- [ ] **Step 1: Add a cross-layer regression test for a component chain.**

```python
def test_preview_reuses_the_persisted_automatic_chain_for_task_and_manifest(store, project_id):
    project = store.derive_localization_routes(project_id)
    preview = store.task_compiler_preview(project_id)["preview"]
    assert preview["manifest"]["execution_chain"]["target"]["outbound"]
    assert project["localization_routes"][0]["execution_nodes"]
```

- [ ] **Step 2: Run the regression test and confirm it fails if either compilation input is changed to a manual/stale source.**

Run: `pixi run pytest tests/test_deployment.py tests/test_task_compiler.py -q`\
Expected: the test protects the shared automatic-chain ownership boundary.

- [ ] **Step 3: Final verification.**

Run: `./scripts/test-backend.sh && ./scripts/test-web.sh && git diff --check`\
Expected: all relevant test suites pass and no whitespace errors are reported.

- [ ] **Step 4: Record verification outcomes in the implementation notes without committing or pushing.**

Document the exact commands and outcomes in the final handoff; leave the worktree uncommitted for user review.
