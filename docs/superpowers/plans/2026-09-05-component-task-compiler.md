# Component Task Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an experimental, component-driven compiler that produces a validated two-map indoor elevator delivery task JSON, its site behavior-tree XML files, and map-specific localization YAML files without writing any robot runtime directory.

**Architecture:** Add a pure `task_compiler.py` domain module that accepts an already-normalized `SiteProject` document and emits an immutable compilation manifest plus a controlled export tree. `DeploymentStore` owns project configuration, input fingerprinting and atomic export persistence; `web_console.py` exposes only preview and download endpoints. The existing native deployment page becomes component-first: it collects only task identity and real component facts, hides manual route/transition controls from the compiler workflow, and renders a read-only compilation timeline.

**Tech Stack:** Python 3.11, stdlib `json`/`hashlib`/`zipfile`/`xml.sax.saxutils`, pytest via Pixi, native HTML/CSS/JavaScript, existing `ConsoleHandler` HTTP server.

**Spec:** `docs/superpowers/specs/2026-09-05-component-task-compiler-design.md`

## Global Constraints

- The first executable profile is exactly `indoor_elevator_v1`: two indoor maps, one start, one target, one physical elevator, and four directional subtasks.
- Exports live only below the selected SiteProject export root; never write `/opt/ry/data/tasks/origin_tasks`, runtime `waypoint_tasks`, runtime localization config, maps, ROS, Supervisor or task execution state.
- Use only approved existing speed mode IDs: `task_point`, `single_point`, `elevator_in`, `backward`, `narrow_point`, `slow_point`.
- `start_task.xml` is the single fixed start behavior tree; target delivery remains `place_water`, and final return remains `task_complete`.
- An elevator waiting/exit point is `1.5 m` from the door face by default; a compiler must reject an out-of-map generated point rather than clamp it.
- Current manual routes, transitions and derived legacy waypoints remain readable compatibility data but are ignored by compiler input.
- All external paths and every template substitution must be allowlisted and validated server-side; browser code never reads robot files or ROS.
- Update `shared/contracts/deployment.md` in the same change because the new Backend/Web HTTP surface is an Existing shared API. Mobile remains an unaffected future consumer.
- Preserve current dark/light tokens and PC deployment-page layout; do not alter Mobile, task execution, scenario setup, realtime observation, reports or vehicle control.

---

## Target File Structure

| File | Responsibility |
| --- | --- |
| `autodrive_console/task_compiler.py` | Pure validation, geometry, XML/YAML/JSON rendering, artifact manifest and ZIP bytes. No HTTP, no ROS and no direct runtime filesystem ownership. |
| `autodrive_console/task_templates/indoor_elevator_v1/*` | Versioned snapshots of the approved Gk1 start/complete/elevator XML and localization baseline, converted to controlled `{{TOKEN}}` placeholders. |
| `autodrive_console/deployment.py` | SiteProject defaults/migration, task-identity validation, compiler invocation, input fingerprinting and atomic project-owned export storage. |
| `web_console.py` | Explicit preview/status/export HTTP routes and attachment response; does not implement compiler rules. |
| `autodrive_console/web/deployment.html` | Task identity and compilation preview controls; removes manual-route/transition controls from the normal flow. |
| `autodrive_console/web/deployment.js` | Fetches/saves compiler config, requests preview, renders read-only timeline/errors, downloads bundle. |
| `autodrive_console/web/deployment.css` | Compact preview/error/timeline states using existing CSS variables. |
| `shared/contracts/deployment.md` | Existing API request/response contract, ownership and compatibility rule. |
| `tests/test_task_compiler.py` | Pure compiler golden/invariant/unsafe-input tests. |
| `tests/test_deployment.py` | Store migration, atomic export, HTTP handler and no-runtime-write tests. |

### Task 1: Freeze the approved compiler profile and test pure geometry/rendering

**Files:**
- Create: `autodrive_console/task_compiler.py`
- Create: `autodrive_console/task_templates/indoor_elevator_v1/localization_base.yaml`
- Create: `autodrive_console/task_templates/indoor_elevator_v1/start_task.xml`
- Create: `autodrive_console/task_templates/indoor_elevator_v1/task_complete.xml`
- Create: `autodrive_console/task_templates/indoor_elevator_v1/elevator_in_n_x.xml`
- Create: `autodrive_console/task_templates/indoor_elevator_v1/elevator_in_x_n.xml`
- Create: `autodrive_console/task_templates/indoor_elevator_v1/elevator_out_n_x.xml`
- Create: `autodrive_console/task_templates/indoor_elevator_v1/elevator_out_x_n.xml`
- Create: `autodrive_console/task_templates/indoor_elevator_v1/close_elevdoor_n.xml`
- Create: `autodrive_console/task_templates/indoor_elevator_v1/close_elevdoor_x.xml`
- Create: `tests/test_task_compiler.py`

**Interfaces:**
- Consumes: one normalized project `dict`, map source YAMLs under `/opt/ry/data/maps`, and only the approved template directory.
- Produces: `CompilationError`, `CompilationInput`, `CompilationPreview`, `compile_indoor_elevator(project: dict) -> CompilationPreview`, and `bundle_zip(preview: CompilationPreview) -> bytes`.
- Later tasks consume: `CompilationPreview.input_sha256`, `CompilationPreview.manifest`, `CompilationPreview.artifacts`, `CompilationPreview.errors`, and `CompilationPreview.warnings`.

- [ ] **Step 1: Write failing golden and geometry tests**

Create `tests/test_task_compiler.py` with a minimal two-map project factory and tests that make the contract executable:

```python
from math import isclose

from autodrive_console.task_compiler import CompilationError, compile_indoor_elevator


def test_compiler_emits_four_subtasks_and_approved_speed_sequence(two_map_project):
    preview = compile_indoor_elevator(two_map_project)
    payload = preview.task_json
    assert [item["subtask_name"] for item in payload["subtasks"]] == [
        "elevator_hall", "1509", "1509_r", "elevator_hall_r",
    ]
    assert [[point["speed_mode"] for point in item["waypoints"]] for item in payload["subtasks"]] == [
        ["task_point", "single_point", "elevator_in"],
        ["backward", "single_point"],
        ["single_point", "task_point", "elevator_in"],
        ["backward", "single_point"],
    ]


def test_waiting_point_is_one_point_five_metres_beyond_the_door_face(two_map_project):
    preview = compile_indoor_elevator(two_map_project)
    waiting = preview.derived_points["lobby_wait"]
    elevator = two_map_project["components"][1]
    assert isclose(waiting["x"], elevator["x"], abs_tol=1e-9)
    assert isclose(waiting["y"], elevator["y"] + 2.5, abs_tol=1e-9)


def test_compiler_rejects_missing_pair_or_out_of_bounds_waiting_point(two_map_project):
    two_map_project["components"] = two_map_project["components"][:-1]
    with pytest.raises(CompilationError, match="同一电梯"):
        compile_indoor_elevator(two_map_project)
```

The factory must use a lobby elevator with `yaw=0`, `height_m=2.0`, so the door is north, the door face is one metre from its center, and waiting point is 2.5 metres north. It must include valid map dimensions large enough for all derived points.

- [ ] **Step 2: Run the new tests and confirm they fail because the module is absent**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_task_compiler.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'autodrive_console.task_compiler'`.

- [ ] **Step 3: Copy only approved behavior semantics into versioned templates**

Copy the exact behavior-tree structure from the approved Gk1 files into `autodrive_console/task_templates/indoor_elevator_v1/`. Replace only data values that the compiler owns with double-brace tokens, never raw `.format()` braces used by BehaviorTree blackboard values:

```xml
<SetBlackboard output_key="origin_floor" value="{{ORIGIN_FLOOR}}" />
<SetUseWheelOdom map_path="{{TARGET_LOCALIZATION_YAML}}" use_wheel_odom="true" />
<SwitchMap map_url="{{TARGET_MAP_YAML}}" />
<SetUseWheelOdom map_path="{{SOURCE_LOCALIZATION_YAML}}"
  pitch="0.0" roll="0.0" use_wheel_odom="false"
  x="{{RELOCALIZE_X}}" y="{{RELOCALIZE_Y}}" yaw="{{RELOCALIZE_YAW}}" z="0.4" />
```

Keep `{community}`, `{building}`, `{unit}`, `{floor}`, `{goal}` and every other runtime blackboard expression untouched. Use the provided `start_task.xml` semantics (`SetUseWheelOdom use_wheel_odom="true"`) and provided `task_complete.xml` semantics.

- [ ] **Step 4: Implement compiler types, project validation and coordinate helpers**

In `autodrive_console/task_compiler.py`, define frozen dataclasses and only stdlib helpers:

```python
class CompilationError(ValueError):
    pass


@dataclass(frozen=True)
class Artifact:
    relative_path: str
    content: bytes
    sha256: str


@dataclass(frozen=True)
class CompilationPreview:
    input_sha256: str
    task_json: dict[str, Any]
    artifacts: tuple[Artifact, ...]
    manifest: dict[str, Any]
    derived_points: dict[str, dict[str, float]]
    warnings: tuple[str, ...]
```

Require exactly `scene_model == "indoor"`; exactly one `lobby` and one `target_floor` stage; map instances for both stage maps with the same nonempty building/unit; exactly one lobby `start`, one target-floor `target`, and exactly two `elevator` components with one shared nonempty `elevator_id`. Require `task_compiler.identity.community` and target `attributes.door` to be nonempty safe filename segments. Reject source map YAMLs outside `/opt/ry/data/maps`.

Define door-out normal from the current canvas convention as:

```python
door_out = (-sin(component_yaw), cos(component_yaw))
inward_yaw = atan2(-door_out[1], -door_out[0])
wait_distance = component_height_m / 2 + wait_distance_m
wait = center + door_out * wait_distance
```

Validate every explicit and generated point against the matching asset origin/width/height/resolution. Convert yaw to `{"x": 0.0, "y": 0.0, "z": sin(yaw / 2), "w": cos(yaw / 2)}`.

- [ ] **Step 5: Implement deterministic JSON/XML/YAML/artifact rendering**

Render exactly four subtasks and the ten rows in the approved spec. Give each generated waypoint a deterministic ID based on role, stage and normalized identity, for example `lobby_wait`, never UUIDs. Render XML with an explicit token replacement map, reject a template containing an unresolved `{{TOKEN}}`, and XML-escape every compiler-owned text value. Replace YAML only with an anchored single-match expression:

```python
updated, count = re.subn(
    r"(?m)^(\s*map_path:\s*).*$",
    rf"\1{map_directory}",
    template_text,
    count=1,
)
if count != 1:
    raise CompilationError("定位基线缺少唯一 system.map_path")
```

For each artifact calculate SHA-256. Build `manifest` with compiler profile/version, input hash, template hashes, artifact hashes, derived points, validation status `experimental_preview`, and the explicit statement that no robot runtime file was changed. `bundle_zip()` must write only `Artifact.relative_path` names after rejecting absolute paths and `..` segments.

- [ ] **Step 6: Run focused compiler tests and expand them to every required invariant**

Add exact tests for all four yaw quadrants, origin/target floor substitutions, `SwitchMap` map URL substitutions, return re-localization coordinates, YAML-only-`map_path` replacement, valid ZIP member names, missing community/door/start/target, duplicate elevators, wrong scene model, and map-boundary failure.

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_task_compiler.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit the pure compiler profile**

```bash
git add autodrive_console/task_compiler.py autodrive_console/task_templates/indoor_elevator_v1 tests/test_task_compiler.py
git commit -m "feat: add indoor elevator task compiler"
```

### Task 2: Persist compiler identity and project-owned experimental exports

**Files:**
- Modify: `autodrive_console/deployment.py:DeploymentStore.create`, `DeploymentStore.get`, component normalization and component mutation methods
- Modify: `tests/test_deployment.py`

**Interfaces:**
- Consumes: `compile_indoor_elevator(project)` from Task 1.
- Produces: `DeploymentStore.update_task_compiler_config(project_id, data) -> dict`, `DeploymentStore.task_compiler_preview(project_id) -> dict`, `DeploymentStore.task_compiler_bundle(project_id) -> tuple[str, bytes]`.
- Later tasks consume: response-safe preview dictionaries and the filename/bytes tuple; no caller receives a writable filesystem path.

- [ ] **Step 1: Write failing store tests for migration, identity and atomic export**

Add tests that assert a legacy project returned by `get()` gains, without losing existing keys:

```python
assert project["task_compiler"] == {
    "profile": "indoor_elevator_v1",
    "identity": {"community": "", "last_preview_input_sha256": None},
}
```

Test `update_task_compiler_config(project_id, {"community": "高科一号"})` persists the community, rejects blank/overlong/path-like values, and invalidates the old preview hash. Test that updating a target component with `{"attributes": {"door": "1509"}}` persists a safe door value. Test a successful preview writes only under `<store.root>/<project>/exports/<input-hash>/`, and assert a sentinel file in `/opt/ry/data/tasks/origin_tasks` remains byte-identical by monkeypatching a temporary runtime root constant.

- [ ] **Step 2: Run store tests and confirm they fail on missing methods/fields**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py -k 'task_compiler' -q
```

Expected: failures name missing `task_compiler` configuration and `update_task_compiler_config`.

- [ ] **Step 3: Add backward-compatible SiteProject normalization**

In `DeploymentStore.create`, initialize:

```python
"task_compiler": {
    "profile": "indoor_elevator_v1",
    "identity": {"community": "", "last_preview_input_sha256": None},
},
```

In `get()`, normalize malformed/missing values into that shape and atomically persist only when migration changed the document. Do not increment `SCHEMA`; the addition is backward-compatible and `get()` already performs compatible derived-field migrations.

Extend target component defaults/normalization with `"door": ""`; accept only one trimmed segment of 1–32 characters matching `[A-Za-z0-9_-]+`. Extend elevator normalization with `wait_distance_m`, default `1.5`, and reject values outside `0.5 <= value <= 5.0`.

In both `update_component()` and `update_task_compiler_config()`, set `last_preview_input_sha256` to `None` whenever compiler input changes.

- [ ] **Step 4: Implement controlled preview/export persistence**

Add `EXPORTS_DIRNAME = "exports"` and helpers that resolve every target below `_project_dir(project_id) / EXPORTS_DIRNAME`. `task_compiler_preview()` calls Task 1, writes each artifact to `<exports>/<input_sha256>/` using the store's temporary-file + fsync + `os.replace` pattern, writes `manifest.json` last, then stores the input hash in `task_compiler.identity.last_preview_input_sha256`.

`task_compiler_bundle()` recompiles first, so stale state is never downloaded; it returns `("{community}_{building}_{unit}_{floor}_{door}_experimental.zip", bundle_zip(preview))`. It must not mutate runtime roots or template source files. It may refresh the same project export directory atomically.

- [ ] **Step 5: Run focused and complete deployment-store tests**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py -q
```

Expected: all deployment tests, including the compiler persistence tests, pass.

- [ ] **Step 6: Commit project persistence**

```bash
git add autodrive_console/deployment.py tests/test_deployment.py
git commit -m "feat: persist experimental task compiler exports"
```

### Task 3: Expose a narrow HTTP contract and safe experimental download

**Files:**
- Modify: `web_console.py:ConsoleHandler.do_GET` and `ConsoleHandler.do_POST`
- Modify: `shared/contracts/deployment.md`
- Modify: `tests/test_deployment.py`

**Interfaces:**
- Consumes: Task 2 store methods.
- Produces:
  - `POST /api/deployments/{project_id}/task-compiler/config` with `{ "community": "高科一号" }`;
  - `POST /api/deployments/{project_id}/task-compiler/preview` with `{}`;
  - `GET /api/deployments/{project_id}/task-compiler/preview`;
  - `GET /api/deployments/{project_id}/task-compiler/download` returning the experimental ZIP attachment.
- Later tasks consume: these exact response fields only.

- [ ] **Step 1: Write failing handler tests**

Add tests using the existing `_deployment_handler` pattern:

```python
def test_task_compiler_preview_http_returns_store_preview():
    handler = _deployment_handler("/api/deployments/site/task-compiler/preview", {})
    with patch.object(web_console.DEPLOYMENTS, "task_compiler_preview", return_value={"status": "ready"}) as preview:
        handler.do_POST()
    preview.assert_called_once_with("site")
    assert handler._json.call_args.args == ({"preview": {"status": "ready"}},)
```

Also test config payload exactness, malformed JSON/`DeploymentError` as 400, a preview `CompilationError` as 422, and download headers `Content-Type: application/zip`, UTF-8 `Content-Disposition`, `Content-Length`, and `X-Content-Type-Options: nosniff`.

- [ ] **Step 2: Run handler tests and confirm missing routes fail**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py -k 'task_compiler_http' -q
```

Expected: assertions fail because no task-compiler route dispatch exists.

- [ ] **Step 3: Implement explicit route dispatch before generic project GET/POST branches**

Add the four routes before the generic `/api/deployments/{project_id}` branch. Parse the body once, require config payload keys to be exactly `{ "community" }`, and map `CompilationError` to `HTTPStatus.UNPROCESSABLE_ENTITY`. For download, obtain `(filename, body)` from the store and use the same safe attachment pattern as `_export_case_package`; do not expose an artifact path or accept a filename from the client.

- [ ] **Step 4: Document Existing contract and consumer impact**

Append an `## Experimental task compiler` section to `shared/contracts/deployment.md` containing the four routes, request/response examples, status codes, ZIP-only download semantics, SiteProject ownership, no-runtime-write guarantee, and compatibility note: Web Console is the only current consumer; Mobile is unchanged and must not call these routes until explicitly implemented.

- [ ] **Step 5: Run focused HTTP tests and contract checks**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py -k 'task_compiler_http' -q
git diff --check
```

Expected: HTTP tests pass and `git diff --check` emits no output.

- [ ] **Step 6: Commit HTTP contract**

```bash
git add web_console.py shared/contracts/deployment.md tests/test_deployment.py
git commit -m "feat: expose experimental task compiler preview"
```

### Task 4: Make the deployment page component-first and render the compiler preview

**Files:**
- Modify: `autodrive_console/web/deployment.html`
- Modify: `autodrive_console/web/deployment.js`
- Modify: `autodrive_console/web/deployment.css`
- Modify: `tests/test_deployment.py`

**Interfaces:**
- Consumes: Task 3 endpoints and the persisted `project.task_compiler.identity.community` field.
- Produces: a PC deployment-page compile panel which saves community identity, requests preview, displays no editable route/transition controls, and downloads only the server-created experimental bundle.

- [ ] **Step 1: Add static regression tests before UI edits**

Add a source-level test that protects the safe workflow without requiring a browser runner:

```python
def test_deployment_page_uses_component_task_compiler_routes():
    source = (Path(__file__).resolve().parents[1] / "autodrive_console/web/deployment.js").read_text(encoding="utf-8")
    assert "/task-compiler/config" in source
    assert "/task-compiler/preview" in source
    assert "/task-compiler/download" in source
    assert "任务编译预览" in (Path(__file__).resolve().parents[1] / "autodrive_console/web/deployment.html").read_text(encoding="utf-8")
```

Add a second assertion that the HTML has no visible `data-waypoint-kind="map_transition"` or `data-waypoint-kind="route"` normal-flow tool.

- [ ] **Step 2: Run the static UI test and confirm it fails**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py -k 'deployment_page_uses_component_task_compiler' -q
```

Expected: failure because compiler controls/endpoints are absent.

- [ ] **Step 3: Replace manual workflow affordances with a compact compiler panel**

In `deployment.html`:

- remove the route and transition tool buttons and their draft-save controls from the primary workflow;
- replace the topology instruction with wording that components automatically determine route order and task boundaries;
- add a `任务编译` panel containing a project-community input, “保存任务信息” button, disabled-until-ready “生成实验预览” button, status area, read-only timeline holder and “下载实验包” button;
- retain map stage binding, map-instance facts, component editing, virtual walls and current project display;
- add target component field label `门牌号` and elevator component field label `候梯距离（m）` through existing `COMPONENT_SPECS` rendering, without adding a separate route form.

In `deployment.js`, implement `saveTaskCompilerConfig()`, `refreshTaskCompilerPreview()`, `renderTaskCompilerPreview(preview)`, and `downloadTaskCompilerBundle()`. Use `fetch` plus `URL.createObjectURL` for the download only after a successful response; always call `URL.revokeObjectURL` after anchor click. Render every backend error with its recovery text; never infer readiness from client-side component counts.

- [ ] **Step 4: Add restrained visual states in existing tokens**

In `deployment.css`, add only component-preview classes: `.task-compiler-panel`, `.task-compiler-summary`, `.compiler-timeline`, `.compiler-step`, `.compiler-blocking-errors`, `.compiler-warning-list`, `.compiler-empty`. Use existing `--surface-*`, `--line-*`, `--ink`, `--muted` and accent tokens. The ready state needs a visible text label, the blocked state needs the exact backend errors, and the generated state needs the explicit sentence “实验产物，尚未安装到机器人”. Preserve the responsive one-column behavior below the current narrow breakpoint.

- [ ] **Step 5: Run source/UI verification and production build**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py -k 'deployment_page_uses_component_task_compiler' -q
./scripts/test-web.sh
```

Expected: static regression passes and `vite build` completes.

- [ ] **Step 6: Commit the deployment UI**

```bash
git add autodrive_console/web/deployment.html autodrive_console/web/deployment.js autodrive_console/web/deployment.css tests/test_deployment.py
git commit -m "feat: add component task compiler preview UI"
```

### Task 5: Run integration regression and produce an auditable Gk1 comparison

**Files:**
- Modify: `tests/test_task_compiler.py`
- Modify: `docs/development/PROFILES.md`
- Modify: `PROJECT_OVERVIEW.md`

**Interfaces:**
- Consumes: final compiler, store, HTTP API and browser assets from Tasks 1–4.
- Produces: a documented experimental workflow and a deterministic Gk1 structural comparison test; no generated runtime artifacts are committed.

- [ ] **Step 1: Write an end-to-end fixture test before documentation edits**

Add a test that creates a valid two-map SiteProject through `DeploymentStore`, saves compiler identity and component data, calls `task_compiler_preview()`, opens the ZIP in memory and verifies:

```python
assert set(zip_file.namelist()) == {
    "manifest.json",
    "tasks/高科一号_1_1_15_1509.json",
    "waypoint_tasks/gk1/1_1_elevator_in_n_x.xml",
    "waypoint_tasks/gk1/1_1_elevator_out_n_x.xml",
    "waypoint_tasks/gk1/1_1_close_elevdoor_x.xml",
    "waypoint_tasks/gk1/1_1_elevator_in_x_n.xml",
    "waypoint_tasks/gk1/1_1_elevator_out_x_n.xml",
    "waypoint_tasks/gk1/1_1_close_elevdoor_n.xml",
    "waypoint_tasks/gk1/start_task.xml",
    "waypoint_tasks/gk1/task_complete.xml",
    "localization/rycx_loc_livox_1_1_lobby.yaml",
    "localization/rycx_loc_livox_1_1_target_floor.yaml",
}
```

Use the actual Gk1 sample only as a read-only structural oracle: compare subtask count, map order, speed mode sequence and behavior-tree naming pattern. Do not make tests depend on mutable `/opt/ry` files; copy the required minimal source data into test fixtures.

- [ ] **Step 2: Run integration test and confirm it identifies any missing artifact**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_task_compiler.py -k 'gk1' -q
```

Expected: pass only when the complete manifest, JSON, XML and YAML package is produced.

- [ ] **Step 3: Document experimental operation and exact non-deployment boundary**

Add a short `任务编译（实验）` subsection to `PROJECT_OVERVIEW.md` and `docs/development/PROFILES.md` stating:

- supported profile is indoor two-map single-elevator round trip only;
- user marks components and their actual attributes, not routes/transitions;
- preview/download writes project-local exports only;
- generated files require field-by-field comparison against an approved sample and local task-executor validation before any robot installation;
- three-map outdoor/lobby transitions and other device components remain unsupported until supplied with approved behavior templates.

- [ ] **Step 4: Run full relevant verification**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_task_compiler.py tests/test_deployment.py -q
./scripts/test-backend.sh
./scripts/test-web.sh
git diff --check
```

Expected: all tests and both checks pass; `git diff --check` has no output. Inspect `git status --short` and do not stage `ry-aletheia.spec`, `config/acceptance/`, `log/`, generated exports, maps, logs, or user data.

- [ ] **Step 5: Commit final documentation and regression proof**

```bash
git add tests/test_task_compiler.py docs/development/PROFILES.md PROJECT_OVERVIEW.md
git commit -m "docs: document experimental task compiler workflow"
```

## Plan Self-Review

### Spec coverage

- Experimental-only output, no runtime writes: Tasks 2, 3 and 5.
- Approved two-map indoor elevator scope and explicit rejection of unsupported scenes: Task 1 validation and Task 2 persistence.
- Door direction, center/waiting points, 1.5 m default, yaw/quat math and map boundaries: Task 1.
- Four-subtask JSON sequence, speed mode arrival semantics, behavior-tree IDs, XML substitutions and localization YAML: Task 1.
- Component-only user flow and removal of manual route/transition work from normal UI: Task 4.
- Shared contract and Backend authority: Task 3.
- Input changes invalidate output, deterministic manifests, templates/artifact hashes and secure downloads: Tasks 1–3.
- Gk1 structural comparison, regression checks and documentation: Task 5.
- Three-map/outdoor and other devices remain explicitly unsupported: Tasks 1 and 5.

### Placeholder scan

The plan has no open implementation placeholders. Every task declares paths, interfaces, test command, expected failure/pass condition and commit scope.

### Type consistency

`compile_indoor_elevator()` returns `CompilationPreview` in Task 1; Task 2 owns persistence and converts it to response-safe dictionaries; Task 3 only dispatches `DeploymentStore` methods; Task 4 consumes only the four Task 3 routes. Artifact ZIP construction remains in the pure compiler and is never exposed as a filesystem path.
