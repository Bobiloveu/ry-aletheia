# Deployment Location Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Export a validated deployment location manifest, controlled map/localization assets, and physical-floor-correct elevator XML from a PC deployment project.

**Architecture:** Keep the existing topology model untouched. Persist new project-owned localization bindings, validate them in DeploymentStore, render their package files in a pure location-manifest module, and let the existing indoor compiler consume its resolved elevator landing buttons.

**Tech Stack:** Python 3.10 standard library, existing DeploymentStore/task compiler, static ES modules, HTML/CSS, pytest, Node test runner.

**Spec:** docs/superpowers/specs/2026-09-15-deployment-location-manifest-design.md

## Global Constraints

- The browser uses controlled HTTP only; no user-supplied robot path, ROS control, file browse, or runtime write is allowed.
- min_floor/max_floor keep their public names and mean elevator panel-button bounds.
- Physical floors are zero-based indexes in the inclusive button range with button 0 removed; map-floor-plus-one logic is forbidden.
- floor_template is a layout identifier only, never a task or elevator button floor.
- All package artifacts remain below deployments/project_id/exports/input_sha256; robot_runtime_changed remains false.
- Outdoor, ferry and additional floor templates are export-only until explicit task templates exist.
- Preserve current map import, mapping, components, transitions, routes, virtual walls, and experimental download behavior.
- Update shared/contracts/deployment.md. Final verification must run scripts/test-backend.sh, scripts/test-web.sh, git diff --check, and doctor backend/web profiles.

---

### Task 1: Add pure physical-floor and runtime-layout primitives

**Files:**
- Create: autodrive_console/location_manifest.py
- Test: tests/test_location_manifest.py

**Interfaces:**
- Produces button_sequence(min_floor: int, max_floor: int) -> tuple[int, ...].
- Produces physical_floor_index(min_floor: int, max_floor: int, button_floor: int) -> int.
- Produces RuntimeLayout(project_id: str, community: str) with localization_yaml(building, unit, key) and map_yaml(building, unit, key).
- Consumed by DeploymentStore and task_compiler.

- [ ] **Step 1: Write failing floor tests**

    from autodrive_console.location_manifest import button_sequence, physical_floor_index

    def test_button_sequence_skips_zero_and_returns_zero_based_indexes():
        assert button_sequence(-2, 25)[:4] == (-2, -1, 1, 2)
        assert physical_floor_index(-2, 25, -2) == 0
        assert physical_floor_index(-2, 25, -1) == 1
        assert physical_floor_index(-2, 25, 1) == 2

    def test_button_sequence_rejects_zero_and_button_outside_range():
        with pytest.raises(LocationManifestError, match="0"):
            physical_floor_index(-2, 25, 0)
        with pytest.raises(LocationManifestError, match="范围"):
            physical_floor_index(-2, 25, 26)

- [ ] **Step 2: Verify RED**

Run: pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_location_manifest.py'
Expected: FAIL because location_manifest does not exist.

- [ ] **Step 3: Implement the minimal physical-floor boundary**

    class LocationManifestError(ValueError):
        pass

    def button_sequence(min_floor, max_floor):
        if min_floor > max_floor:
            raise LocationManifestError("电梯按钮范围无效")
        values = tuple(value for value in range(min_floor, max_floor + 1) if value != 0)
        if not values:
            raise LocationManifestError("电梯按钮范围不能只包含 0")
        return values

    def physical_floor_index(min_floor, max_floor, button_floor):
        values = button_sequence(min_floor, max_floor)
        if button_floor not in values:
            raise LocationManifestError("电梯按钮层不在服务范围内")
        return values.index(button_floor)

Implement RuntimeLayout with component-wise validation: reject empty values, slash, backslash, control characters and dot segments. Its result contains deterministic package-relative runtime paths and fixed installer-root paths; it never accepts a source path.

- [ ] **Step 4: Add runtime-layout tests**

    def test_runtime_layout_has_deterministic_package_paths():
        layout = RuntimeLayout("site-a", "数创大厦")
        assert layout.localization_yaml("1", "1", "indoor").relative == "runtime/localization/数创大厦/1_1/indoor.yaml"
        assert layout.map_yaml("1", "1", "floor-2").relative == "runtime/maps/数创大厦/1_1/floor-2/map.yaml"

    def test_runtime_layout_rejects_path_identity():
        with pytest.raises(LocationManifestError):
            RuntimeLayout("site-a", "../unsafe")

- [ ] **Step 5: Verify GREEN and commit**

Run: pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_location_manifest.py'
Expected: PASS.

    git add autodrive_console/location_manifest.py tests/test_location_manifest.py
    git commit -m "feat: add deployment location floor primitives"

### Task 2: Persist validated localization bindings and elevator landing buttons

**Files:**
- Modify: autodrive_console/deployment.py
- Modify: web_console.py
- Test: tests/test_deployment.py

**Interfaces:**
- Produces DeploymentStore.create_localization_binding(project_id, data), update_localization_binding(project_id, binding_id, data), and delete_localization_binding(project_id, binding_id).
- Produces POST /api/deployments/project_id/localization-bindings, POST /api/deployments/project_id/localization-bindings/binding_id, and DELETE equivalent.
- Elevator attributes acquire button_floor: int after physical_elevator_id validation.

- [ ] **Step 1: Write failing Store tests**

    def test_binding_allows_distinct_floor_templates_but_not_duplicate_indoor(tmp_path, monkeypatch):
        store, project, maps = project_with_two_map_assets(tmp_path, monkeypatch)
        store.create_localization_binding(project["id"], binding_payload(maps[0]["id"], "1", "1", "indoor"))
        with pytest.raises(DeploymentError, match="indoor"):
            store.create_localization_binding(project["id"], binding_payload(maps[1]["id"], "1", "1", "indoor"))
        store.create_localization_binding(project["id"], binding_payload(maps[0]["id"], "1", "1", "floor", floor_template="2"))
        store.create_localization_binding(project["id"], binding_payload(maps[1]["id"], "1", "1", "floor", floor_template="3"))

    def test_binding_rejects_initial_pose_outside_asset(tmp_path, monkeypatch):
        store, project, maps = project_with_two_map_assets(tmp_path, monkeypatch)
        with pytest.raises(DeploymentError, match="初始化位"):
            store.create_localization_binding(project["id"], binding_payload(maps[0]["id"], "1", "1", "indoor", go_x=9999))

- [ ] **Step 2: Verify RED**

Run: pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py -k localization_binding'
Expected: FAIL because Store methods are absent.

- [ ] **Step 3: Implement migration and Store validation**

New projects contain localization_bindings: []. get() normalizes missing legacy values to []; do not change schema only to rename fields. Implement one private normalizer that persists:

    {
      "id": "localization-<12 hex>",
      "map_asset_id": "map-...",
      "building": "1", "unit": "1", "type": "floor",
      "floor_template": "2",
      "init_go": {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0},
      "init_return": {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0}
    }

Require map ownership and non-empty building/unit. Allow type outdoor, indoor, ferry, floor. Require floor_template only for floor; enforce one outdoor/indoor/ferry per building-unit and one floor per building-unit-template. Require finite z/yaw and asset-bounded x/y.

Extend _normalise_elevator_landing_attributes to validate button_floor using Task 1 against linked physical elevator min_floor/max_floor. Preserve physical_elevator_id; do not rename shared fields.

- [ ] **Step 4: Write HTTP RED test**

    def test_binding_http_forwards_only_project_owned_data():
        payload = binding_payload("map-a", "1", "1", "indoor")
        handler = _deployment_handler("/api/deployments/site/localization-bindings", payload)
        with patch.object(web_console.DEPLOYMENTS, "create_localization_binding", return_value={"id": "localization-a"}) as create:
            handler.do_POST()
        create.assert_called_once_with("site", payload)

- [ ] **Step 5: Implement routes, verify, and commit**

Place explicit collection/item routes before generic component routes. Reject malformed JSON, unknown keys, and malformed item paths with 400. Collection creation returns 201 and response key localization_binding.

Run: pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py -k "localization_binding or physical_elevator"'
Expected: PASS.

    git add autodrive_console/deployment.py web_console.py tests/test_deployment.py
    git commit -m "feat: persist deployment localization bindings"

### Task 3: Render controlled manifest assets and correct elevator XML

**Files:**
- Modify: autodrive_console/location_manifest.py
- Modify: autodrive_console/task_compiler.py
- Modify: autodrive_console/deployment.py
- Test: tests/test_location_manifest.py
- Test: tests/test_deployment.py

**Interfaces:**
- Produces compile_location_manifest(project, map_root) -> RenderedLocationManifest with json_bytes, artifacts and public summaries.
- CompilationPreview gains location_manifest summary and runtime artifacts.
- compile_indoor_elevator obtains source and target physical values from physical_floor_index.

- [ ] **Step 1: Write failing renderer tests**

    def test_location_manifest_groups_by_building_unit_and_preserves_template():
        rendered = compile_location_manifest(project_with_bindings(), map_root=project_maps)
        document = json.loads(rendered.json_bytes)
        assert document["community"] == "数创大厦"
        floor = next(item for item in document["loc_yaml"][0]["yaml_index"] if item["type"] == "floor")
        assert floor["floor"] == "2"

    def test_compiler_writes_origin_floor_from_elevator_button_index():
        preview = compile_indoor_elevator(project_with_origin_button(-2, -1, 1), map_root=project_maps)
        outgoing = artifact_text(preview, "waypoint_tasks/site/1_1_elevator_out_n_x.xml")
        assert 'output_key="origin_floor" value="2"' in outgoing

- [ ] **Step 2: Verify RED**

Run: pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_location_manifest.py tests/test_deployment.py -k "location_manifest or origin_floor"'
Expected: FAIL because manifest rendering and button-floor XML rendering are absent.

- [ ] **Step 3: Implement deterministic renderer**

Sort building/unit and yaml_index in outdoor, indoor, ferry, floor_template order. Render community, loc_yaml, building, unit, type, floor only for floor, yaml, 2D_yaml, init_go and init_return exactly as specified.

Copy only declared project snapshot map members whose resolved sources stay under map_root. Reject missing map YAML/image artifacts. Render localization YAML from the existing approved base and replace only its map_path line with generated runtime map directory. Add runtime artifacts to the existing ZIP allowlist; do not allow any other new root.

Replace _shared_physical_floor logical-floor-plus-one behavior with physical_floor_index(physical.min_floor, physical.max_floor, landing.attributes.button_floor) for both source and target XML values.

- [ ] **Step 4: Add package and failure tests**

    def test_location_manifest_rejects_missing_binding_without_map_name_guess():
        with pytest.raises(CompilationError, match="定位绑定"):
            compile_location_manifest(project_missing_indoor_binding(), map_root=project_maps)

    def test_bundle_contains_manifest_but_never_writes_runtime(tmp_path, monkeypatch):
        package = store.task_compiler_bundle(project_id)[1]
        assert "runtime/loc_yaml_path.json" in zip_members(package)
        assert runtime_sentinel.read_bytes() == b"unchanged"

- [ ] **Step 5: Expose safe preview, verify, and commit**

Expose only community, binding count, building/unit/type/template summaries, relative artifact names and validation errors. Do not expose project working paths, upload locations, ROS settings, or write controls.

Run: pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_location_manifest.py tests/test_deployment.py'
Expected: PASS.

    git add autodrive_console/location_manifest.py autodrive_console/task_compiler.py autodrive_console/deployment.py tests/test_location_manifest.py tests/test_deployment.py
    git commit -m "feat: export deployment location manifest"

### Task 4: Add constrained binding editor and initialization markers

**Files:**
- Modify: autodrive_console/web/deployment.html
- Modify: autodrive_console/web/deployment.js
- Modify: autodrive_console/web/deployment.css
- Modify: autodrive_console/web/deployment/canvas-renderer.js
- Test: tests/test_deployment.py
- Test: frontend/test/legacy-app-module.test.mjs

**Interfaces:**
- Consumes Task 2 routes and project.localization_bindings.
- Sends only map_asset_id, building, unit, type, optional floor_template, init_go, init_return.
- Adds button_floor only to existing elevator landing save payloads.

- [ ] **Step 1: Write failing structure tests**

    def test_page_has_binding_editor_but_no_robot_path_input():
        source = (ROOT / "autodrive_console/web/deployment.html").read_text(encoding="utf-8")
        assert 'id="localizationBindingDialog"' in source
        assert 'id="localizationFloorTemplate"' in source
        assert "2D_yaml" not in source
        assert "定位 YAML 路径" not in source

    test("deployment module uses localization binding routes", () => {
      const source = readFileSync(deploymentPath, "utf8");
      assert.match(source, /\/localization-bindings/);
      assert.doesNotMatch(source, /source_yaml.*localization/i);
    });

- [ ] **Step 2: Verify RED**

Run: pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py -k binding_editor' && cd frontend && node --test test/legacy-app-module.test.mjs
Expected: FAIL because dialog and routes are absent.

- [ ] **Step 3: Implement compact editor under existing map detail**

Add one Localization Binding action to selected-map detail. The dialog has type, building, unit, conditional floor-template, go/return pose summaries, Set Go on Canvas, Set Return on Canvas, and Copy Go to Return. It has no global-page card and no path field.

Add two canvas tools with distinct small markers. Each click uses the existing canvas world transform and updates only the selected binding pose. Preserve pan, components, virtual walls, routes and existing selection. z defaults to 0; yaw follows current canvas convention.

Extend the existing elevator landing dialog with integer button_floor and read-only derived text such as button 1 to physical floor 2. origin_floor remains non-editable and Backend-authoritative.

- [ ] **Step 4: Render safe preview and verify**

Add to current task compiler preview: building/unit, type, optional template and package-relative artifacts. Escape all values with existing esc and render server errors as text. Add no install, start or ROS action.

Run: scripts/test-web.sh && pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py -k "binding_editor or deployment_page"'
Expected: PASS.

    git add autodrive_console/web/deployment.html autodrive_console/web/deployment.js autodrive_console/web/deployment.css autodrive_console/web/deployment/canvas-renderer.js tests/test_deployment.py frontend/test/legacy-app-module.test.mjs
    git commit -m "feat: edit deployment localization bindings"

### Task 5: Publish API contract and complete verification

**Files:**
- Modify: shared/contracts/deployment.md
- Modify: tests/test_deployment.py

**Interfaces:**
- Documents Task 2 binding routes, Task 3 experimental artifacts, physical-floor calculation, and PC-Web-only consumer status.
- Mobile remains non-consuming.

- [ ] **Step 1: Write a failing path-rejection test**

    def test_binding_http_rejects_robot_path_field():
        handler = _deployment_handler(
            "/api/deployments/site/localization-bindings",
            {"map_asset_id": "map-a", "building": "1", "unit": "1", "type": "indoor", "yaml": "/opt/ry/private.yaml"},
        )
        handler.do_POST()
        assert handler._json.call_args.args[1] == HTTPStatus.BAD_REQUEST

- [ ] **Step 2: Verify RED**

Run: pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py -k robot_path'
Expected: FAIL until unknown binding keys are rejected.

- [ ] **Step 3: Enforce and document exact boundary**

Route layer accepts only Task 2 fields, rejecting yaml, 2D_yaml, source_path, destination_path, runtime_path and every unknown key. Update shared/contracts/deployment.md with request/response shapes, physical floor sequence, generated layout, experimental-only boundary and Backend/Web/Mobile consumers.

- [ ] **Step 4: Run fresh complete verification**

Run: scripts/test-backend.sh
Expected: all Backend tests pass.

Run: scripts/test-web.sh
Expected: all Web tests pass and production Vite build succeeds.

Run: scripts/doctor.sh --profile backend && scripts/doctor.sh --profile web && git diff --check
Expected: required backend/web checks are OK and diff check has no output.

- [ ] **Step 5: Commit**

    git add shared/contracts/deployment.md tests/test_deployment.py
    git commit -m "docs: define deployment location manifest contract"

After committing, repeat scripts/test-backend.sh, scripts/test-web.sh and git diff --check. Report fresh evidence and explicitly state that no robot runtime directory, ROS process, task file or localization file was changed.
