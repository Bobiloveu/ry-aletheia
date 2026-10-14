# Behavior-tree Status-code Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one validated JSON registry the source of truth for the latest behavior-tree task-status codes, render only the semantically required XML status publications, and keep every Backend status-code consumer synchronized.

**Architecture:** `autodrive_console/task_status_codes.py` will validate and read the profile-owned JSON on every query. The task compiler will inject `STATUS_*` XML values, fingerprint that input in the preview manifest, and reject numeric status attributes left in approved templates. The execution monitor, automatic-return gate, and multi-task collector will obtain their named codes from the same registry while retaining their current public APIs and safety behavior.

**Tech Stack:** Python 3.10, ElementTree, JSON, pytest/Pixi, existing behavior-tree XML templates.

**Spec:** `docs/superpowers/specs/2026-09-27-behavior-tree-status-code-registry-design.md`

## Global Constraints

- Do not alter the deployment UI shell, left navigation, guided workflow, REST response shape, ROS topics, or task-dispatch behavior.
- Only the approved `indoor_elevator_v1` templates receive `PublishTaskStatus` changes; do not invent status publications for unsupported water, image, building, or multi-task actions.
- Status codes come only from `autodrive_console/task_templates/indoor_elevator_v1/task-status-codes.json`; no project form, component property, or browser input can change them.
- Keep physical-motion priority over TaskStatus in `VehicleExecutionStatusMonitor` and preserve the existing completed-task UUID guard.
- Invalid registry input must block preview compilation; live monitor falls back safely, while auto-return and delivery collection reject uncertain events.
- Do not stage, commit, or push changes; the user owns Git integration.

---

### Task 1: Add and validate the profile-owned status-code registry

**Files:**
- Create: `autodrive_console/task_templates/indoor_elevator_v1/task-status-codes.json`
- Create: `autodrive_console/task_status_codes.py`
- Create: `tests/test_task_status_codes.py`

**Interfaces:**
- Produces `task_status_codes() -> dict[str, int]`, `task_status_code(name: str) -> str`, `task_status_xml_values() -> dict[str, str]`, `task_status_phase_by_code() -> dict[str, str]`, and `TaskStatusCodeError(ValueError)`.
- Consumed by `task_compiler.py`, `vehicle_execution_status/classifier.py`, `vehicle_execution_status/monitor.py`, `return_signal.py`, and `multi_task_status.py`.

- [ ] **Step 1: Write failing registry tests.**

```python
def test_registry_exposes_the_confirmed_codes_and_xml_tokens():
    assert task_status_codes()["elevator_waiting"] == 200
    assert task_status_code("task_complete") == "109"
    assert task_status_xml_values()["STATUS_GATE_OUT"] == "302"
    assert task_status_phase_by_code()["304"] == "closing_access_door"

def test_registry_reloads_a_controlled_file_change(monkeypatch, tmp_path):
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    _replace_code(config, "gate_in", 811)
    assert task_status_code("gate_in") == "811"
    assert task_status_phase_by_code()["811"] == "opening_gate"

@pytest.mark.parametrize("mutation", ["missing_key", "non_integer", "out_of_range", "unknown_schema", "illegal_duplicate"])
def test_registry_rejects_invalid_configuration(monkeypatch, tmp_path, mutation):
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    _mutate_registry(config, mutation)
    with pytest.raises(TaskStatusCodeError):
        task_status_codes()
```

- [ ] **Step 2: Run the focused test to verify the registry does not exist yet.**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_task_status_codes.py -q`\
Expected: FAIL during collection because `autodrive_console.task_status_codes` is absent.

- [ ] **Step 3: Create the exact JSON registry and minimal loader.**

Create the JSON with the confirmed `schema: 1` and all 27 named values from the design: `task_start` through `multi_task_arrived`, including the only approved duplicate pair `door_waiting_open` / `door_waiting_close` equal to `305`.

```python
STATUS_CODE_PATH = Path(__file__).with_name("task_templates") / "indoor_elevator_v1" / "task-status-codes.json"

def task_status_codes() -> dict[str, int]:
    document = json.loads(STATUS_CODE_PATH.read_text(encoding="utf-8"))
    return _validate_codes(document)

def task_status_code(name: str) -> str:
    try:
        return str(task_status_codes()[name])
    except KeyError as exc:
        raise TaskStatusCodeError(f"未知任务状态码名称：{name}") from exc

def task_status_xml_values() -> dict[str, str]:
    return {f"STATUS_{name.upper()}": str(code) for name, code in task_status_codes().items()}
```

Implement `_validate_codes` with the fixed complete-key set, exact `schema == 1`, `type(code) is int`, range `100..999`, and a reverse-value uniqueness check that accepts only the exact `{door_waiting_open, door_waiting_close}` pair at `305`. Build `task_status_phase_by_code()` from a fixed name-to-existing-phase map: `task_complete → completed`; elevator waiting/in/taking/outing/arrived → existing elevator phases; gate and automatic-door directions → existing access phases; water names → `draining_or_unloading`; all other names (including `elevator_outed`, waiting codes, photo, building, and multi-task codes) → `task`.

- [ ] **Step 4: Run the registry tests to green.**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_task_status_codes.py -q`\
Expected: PASS, including changed-value reload and all invalid-registry rejections.

### Task 2: Tokenize only the approved behavior-tree status publications

**Files:**
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/start_task.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/task_complete.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/elevator_in_n_x.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/elevator_in_x_n.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/elevator_out_n_x.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/elevator_out_x_n.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/close_elevdoor_n.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/close_elevdoor_x.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/components/gate_open_go.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/components/gate_close_go.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/components/gate_open_back.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/components/gate_close_back.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/components/auto_door_open_go.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/components/auto_door_close_go.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/components/auto_door_open_back.xml`
- Modify: `autodrive_console/task_templates/indoor_elevator_v1/components/auto_door_close_back.xml`
- Modify: `tests/test_task_compiler.py`

**Interfaces:**
- Consumes `STATUS_*` token names returned by `task_status_xml_values()`.
- Produces template XML in which every `PublishTaskStatus.status_code` is a registry token and every position is an adjacent sibling of its relevant behavior node.

- [ ] **Step 1: Add failing XML-structure and token regression tests.**

```python
@pytest.mark.parametrize(("name", "expected"), [
    ("start_task.xml", ["STATUS_TASK_START"]),
    ("task_complete.xml", ["STATUS_TASK_COMPLETE"]),
    ("close_elevdoor_n.xml", ["STATUS_ELEVATOR_OUTING", "STATUS_ELEVATOR_OUTED"]),
    ("components/gate_open_go.xml", ["STATUS_DOOR_WAITING", "STATUS_GATE_IN"]),
    ("components/gate_close_go.xml", ["STATUS_DOOR_WAITING", "STATUS_GATE_OUT"]),
    ("components/auto_door_open_go.xml", ["STATUS_DOOR_WAITING", "STATUS_AUTO_DOOR_IN"]),
    ("components/auto_door_close_go.xml", ["STATUS_DOOR_WAITING", "STATUS_AUTO_DOOR_OUT"]),
])
def test_approved_templates_have_only_registry_status_tokens(name, expected):
    assert _status_tokens(_template(name)) == expected
    assert not re.search(r'status_code="[0-9]+"', _template(name))

def test_elevator_caller_statuses_are_adjacent_to_the_caller():
    root = ElementTree.fromstring(_template("elevator_in_n_x.xml"))
    sequence = root.find(".//Sequence[@name='CallAndCheckDoor']")
    children = list(sequence)
    caller_index = next(i for i, child in enumerate(children) if child.tag == "ElevatorCaller")
    assert children[caller_index - 1].attrib["status_code"] == "{{STATUS_ELEVATOR_WAITING}}"
    assert children[caller_index + 1].attrib["status_code"] == "{{STATUS_ELEVATOR_ARRIVED}}"
```

Cover both elevator-in templates, both elevator-out templates, all four directions for gate and automatic-door templates, and assert no template contains `STATUS_DOOR_WAITING_OPEN` or `STATUS_DOOR_WAITING_CLOSE`, since no actual behavior uses those codes yet.

- [ ] **Step 2: Run focused compiler tests and observe existing hard-coded values fail.**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_task_compiler.py -k 'status or template' -q`\
Expected: FAIL because current templates contain literal values such as `200`, `201`, and `303`.

- [ ] **Step 3: Apply the precise, semantic token placements.**

Use only these substitutions and insertions:

```xml
<!-- start_task.xml: first child of WaterDeliverySequence -->
<PublishTaskStatus status_code="{{STATUS_TASK_START}}"/>

<!-- elevator_in_*: immediate siblings of ElevatorCaller; after successful retry -->
<PublishTaskStatus status_code="{{STATUS_ELEVATOR_WAITING}}"/>
<ElevatorCaller .../>
<PublishTaskStatus status_code="{{STATUS_ELEVATOR_ARRIVED}}"/>
...
</RetryUntilSuccessful>
<PublishTaskStatus status_code="{{STATUS_ELEVATOR_IN}}"/>

<!-- elevator_out_*: immediately before retry, then around ElevatorCaller -->
<PublishTaskStatus status_code="{{STATUS_ELEVATOR_TAKING}}"/>
<RetryUntilSuccessful ...><Sequence ...>
  <PublishTaskStatus status_code="{{STATUS_ELEVATOR_WAITING}}"/>
  <ElevatorCaller .../>
  <PublishTaskStatus status_code="{{STATUS_ELEVATOR_ARRIVED}}"/>
</Sequence></RetryUntilSuccessful>

<!-- close_elevdoor_*: direct neighbors of ElevatorDoorKeeper -->
<PublishTaskStatus status_code="{{STATUS_ELEVATOR_OUTING}}"/>
<ElevatorDoorKeeper .../>
<PublishTaskStatus status_code="{{STATUS_ELEVATOR_OUTED}}"/>
```

In each `gate_open_*`, use `STATUS_DOOR_WAITING` immediately before `DoorControl executeid="2"` and `STATUS_GATE_IN` after the successful `RetryUntilSuccessful`. In each `gate_close_*`, use that same waiting code before `executeid="3"` and `STATUS_GATE_OUT` after it. For automatic doors use `STATUS_AUTO_DOOR_IN` after `executeid="2"` and `STATUS_AUTO_DOOR_OUT` after `executeid="3"`. Do not add any status node around `GetTaskTargetInfo`, map switching, `ChangeUssStatus`, `ElevatorStatus`, or retry cleanup.

- [ ] **Step 4: Run structural token tests to green.**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_task_compiler.py -k 'status or template' -q`\
Expected: PASS, with no numeric `status_code` XML attribute in an approved template.

### Task 3: Compile registry values, fingerprint the input, and prove rendered XML placement

**Files:**
- Modify: `autodrive_console/task_compiler.py:201-246,648-660,721-755,759-797,803-810`
- Modify: `tests/test_task_compiler.py`

**Interfaces:**
- Consumes `task_status_codes()`, `task_status_xml_values()`, and the raw JSON bytes from Task 1.
- Produces fully rendered XML without `STATUS_*` tokens; `manifest["task_status_codes_sha256"]`; and an input SHA that changes when the registry changes.

- [ ] **Step 1: Write failing end-to-end compiler tests.**

```python
def test_compiler_renders_current_registry_values_and_records_its_sha(two_map_project):
    preview = _compile(two_map_project)
    rendered = _artifact_text(preview, "waypoint_tasks/gk1/1_1_elevator_in_n_x.xml")
    assert 'status_code="200"' in rendered
    assert 'status_code="209"' in rendered
    assert "STATUS_" not in rendered
    assert preview.manifest["task_status_codes_sha256"] == _registry_sha()

def test_compiler_reacts_to_a_registry_code_change(monkeypatch, two_map_project, tmp_path):
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    before = _compile(two_map_project)
    _replace_code(config, "elevator_waiting", 811)
    after = _compile(two_map_project)
    assert before.input_sha256 != after.input_sha256
    assert 'status_code="811"' in _artifact_text(after, "waypoint_tasks/gk1/1_1_elevator_in_n_x.xml")

def test_compiler_blocks_preview_when_the_registry_is_invalid(monkeypatch, two_map_project, tmp_path):
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    _mutate_registry(config, "missing_key")
    with pytest.raises(CompilationError, match="任务状态码配置"):
        _compile(two_map_project)
```

- [ ] **Step 2: Run those tests and verify the compiler has not yet supplied status tokens or fingerprints.**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_task_compiler.py -k 'registry_values or registry_code_change or invalid_registry' -q`\
Expected: FAIL because `_xml_values` contains no `STATUS_*` entries and manifest/input hashing ignores the registry.

- [ ] **Step 3: Wire the registry through every render path.**

```python
try:
    status_xml_values = task_status_xml_values()
    status_config_bytes = status_code_config_bytes()
except TaskStatusCodeError as exc:
    raise CompilationError(f"任务状态码配置无效：{exc}") from exc

xml_values = {
    **_xml_values(...),
    **status_xml_values,
}
```

Pass the same merged dictionary into `_component_action_artifacts` so component XML is rendered identically to base XML. Before `_render_xml`, inspect each approved source template and reject a `PublishTaskStatus` whose `status_code` is not exactly one allowed `{{STATUS_*}}` token. Add the raw registry SHA under `task_status_codes_sha256`, add `task-status-codes.json` to `template_sha256`, and add the registry digest (or the validated codes object) to `_input_hash` payload. Keep artifact paths and task JSON unchanged.

- [ ] **Step 4: Run focused compiler tests to green and inspect a preview.**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_task_compiler.py -k 'status or registry or template' -q`\
Expected: PASS.

Run: `rg -n 'status_code="[0-9]+' autodrive_console/task_templates/indoor_elevator_v1`\
Expected: no output.

### Task 4: Make all Backend status-code consumers use the registry safely

**Files:**
- Modify: `autodrive_console/vehicle_execution_status/classifier.py:15-55,101-119`
- Modify: `autodrive_console/vehicle_execution_status/monitor.py:18-25,109-125,166-175`
- Modify: `autodrive_console/return_signal.py:15-40`
- Modify: `autodrive_console/multi_task_status.py:23-52`
- Modify: `tests/test_vehicle_execution_status.py`
- Modify: `tests/test_return_signal.py`
- Modify: `tests/test_multi_task_status.py`

**Interfaces:**
- Consumes the Task 1 registry API.
- Retains `classify_execution_state(...)`, `VehicleExecutionStatusMonitor.observe_task(...)`, `ReturnSignalGate.accept(...)`, and `MultiTaskStatusCollector.observe_fields(...)` signatures and their existing public outputs.

- [ ] **Step 1: Add failing dynamic-mapping and safety-fallback tests.**

```python
def test_classifier_uses_a_reloaded_registry_code(monkeypatch, tmp_path):
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    _replace_code(config, "auto_door_out", 812)
    snapshot = classify_execution_state(NavigationState(status="running"), TaskEvent(status_code="812"), restarting_nodes=False)
    assert snapshot.phase == "closing_access_door"

def test_monitor_keeps_last_good_complete_code_when_registry_reload_fails(monkeypatch, tmp_path):
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0)
    monitor.observe_task(FakeTask(status_code="100", task_uuid="task-a"), received_at=8.0)
    _mutate_registry(config, "missing_key")
    monitor.observe_task(FakeTask(status_code="109", task_uuid="task-a"), received_at=9.0)
    assert monitor.status() == {"phase": "completed", "label": "任务完成"}

def test_return_gate_and_multi_collector_follow_reloaded_named_codes(monkeypatch, tmp_path):
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    _replace_code(config, "task_return_waiting", 813)
    _replace_code(config, "multi_task_arrived", 814)
    gate = ReturnSignalGate(); gate.arm(1)
    assert gate.accept("813") is True
    assert MultiTaskStatusCollector(request()).observe_fields("814", "task-001", "code-501") is True
```

Also assert a malformed config produces no automatic-return acceptance and no delivered-point acceptance. Preserve the existing test cases for `103`, `109`, and `701` against the default registry values.

- [ ] **Step 2: Run consumer tests and confirm literal-code implementation fails the changed-code cases.**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_vehicle_execution_status.py tests/test_return_signal.py tests/test_multi_task_status.py -q`\
Expected: FAIL on changed code `812`, `813`, and `814` because the current code compares fixed strings.

- [ ] **Step 3: Replace literals with named registry lookups and preserve safe degradation.**

In `classifier.py`, replace the three static event dictionaries with one successful `task_status_phase_by_code()` lookup; if loading raises `TaskStatusCodeError`, return `None` so filename semantics and generic active navigation remain available. In `monitor.py`, obtain a complete-code snapshot through a private `_task_complete_code()` that caches the last valid `task_complete` value; use it both in `observe_task` and stale-navigation completion handling, and leave the UUID session guard unchanged.

```python
def _task_complete_code(self) -> str:
    try:
        self._last_task_complete_code = task_status_code("task_complete")
    except TaskStatusCodeError:
        LOGGER.exception("任务状态码配置无效，继续使用上次完成码")
    return self._last_task_complete_code
```

Initialize `_last_task_complete_code` from the default confirmed value at construction time only after a successful lookup; if the first lookup fails, use no matching completion code rather than treating an arbitrary event as completed. In `ReturnSignalGate.accept` and `MultiTaskStatusCollector.observe_fields`, catch `TaskStatusCodeError` and return `False`. Replace their class literal constants with `task_status_code("task_return_waiting")` and `task_status_code("multi_task_arrived")` respectively. Do not add publishing, retries, or ROS subscriptions.

- [ ] **Step 4: Run the consumer tests to green.**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_vehicle_execution_status.py tests/test_return_signal.py tests/test_multi_task_status.py -q`\
Expected: PASS, including dynamic changes, rejected uncertain actions, current phase names, and same-UUID completion protection.

### Task 5: Update the shared contract and run release-level self-checks

**Files:**
- Modify: `shared/contracts/task_execution.md:1-7,车辆执行状态显示段落,部署验收自动返程段落,R6B 配送事件段落`
- Modify: `tests/test_task_compiler.py` and `tests/test_vehicle_execution_status.py` only if the final integrated suite reveals a missing contract-derived assertion.

**Interfaces:**
- Documents the existing `/task_status` protocol without changing its Topic, envelope, or PC Web `{phase,label}` response.

- [ ] **Step 1: Update consumer and impact documentation.**

Add the change record at the top of `shared/contracts/task_execution.md`: producer remains the vehicle behavior tree on `/task_status`; current consumers are the experimental compiler, vehicle status monitor, acceptance return bridge, and R6B multi-task collector; Web continues to consume only `{phase,label}` and Mobile remains a non-consumer. Replace statements that call out fixed numeric comparisons with named registry semantics, while retaining the documented default values `103`, `109`, and `701` for interoperability and the existing completion/session safety condition.

- [ ] **Step 2: Run all affected Backend tests.**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_task_status_codes.py tests/test_task_compiler.py tests/test_vehicle_execution_status.py tests/test_return_signal.py tests/test_multi_task_status.py -q`\
Expected: PASS.

- [ ] **Step 3: Run the required project checks.**

Run: `./scripts/test-backend.sh`\
Expected: all status-code-related tests pass; if the known independent video ABI assertion still fails, record it separately with its exact test name and do not change video code.

Run: `./scripts/test-web.sh`\
Expected: PASS; no deployment-page source files should change for this Backend-only protocol update.

- [ ] **Step 4: Perform final static self-audit before handoff.**

Run: `git diff --check`\
Expected: no whitespace errors.

Run: `rg -n 'status_code="[0-9]+' autodrive_console/task_templates/indoor_elevator_v1`\
Expected: no output.

Run: `git diff -- autodrive_console/task_status_codes.py autodrive_console/task_templates/indoor_elevator_v1/task-status-codes.json autodrive_console/task_compiler.py autodrive_console/vehicle_execution_status/classifier.py autodrive_console/vehicle_execution_status/monitor.py autodrive_console/return_signal.py autodrive_console/multi_task_status.py shared/contracts/task_execution.md`\
Expected: only registry, token rendering, status-consumer, and contract changes; no UI shell or navigation changes.

## Self-review

- **Spec coverage:** Task 1 supplies the editable single JSON and validation; Tasks 2–3 place and render only the status events named in the insertion table, reject hard-coded XML values, and fingerprint the result; Task 4 updates all discovered Backend readers of `103`/`109`/`701` as well as the monitor; Task 5 records consumers and validates Backend/Web boundaries.
- **No unsupported insertion:** The plan explicitly excludes `305`, water, photo, building, and multi-task XML insertion because the profile currently has no matching action node.
- **Type consistency:** Registry numeric values are `int` internally, XML/rendered protocol values and incoming ROS codes are `str`; public monitor, return-gate, and collector method signatures stay unchanged.
- **Placeholder scan:** This plan contains no TBD/TODO or generic “handle edge cases” instructions; every failure policy, file, API, command, and status mapping is concrete.
