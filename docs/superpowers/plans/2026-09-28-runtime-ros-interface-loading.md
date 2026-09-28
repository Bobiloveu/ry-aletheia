# Runtime ROS Interface Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the frozen console load `master_interfaces` from each vehicle's sourced ROS runtime, so localization status works where `LocalizationStatus` exists without embedding an interface version in a generic upgrade package.

**Architecture:** A PyInstaller runtime hook derives interface paths only from `AMENT_PREFIX_PATH` and places the vehicle package before frozen modules. The builder removes all embedded `master_interfaces` Python and ROSIDL content; the read-only monitor reports a controlled unavailable state when that optional interface is absent.

**Tech Stack:** Python 3.10, PyInstaller runtime hook, ROS 2 Humble, pytest, Bash.

**Spec:** `docs/superpowers/specs/2026-09-28-runtime-ros-interface-design.md`

## Global Constraints

- Do not alter ROS nodes, localization recovery, task control, Node Manager, or robot safety boundaries.
- Only a path declared by `AMENT_PREFIX_PATH` may supply `master_interfaces`.
- The one-file binary must not contain `master_interfaces` Python modules or `libmaster_interfaces__rosidl_*.so`.
- Missing or incompatible `LocalizationStatus` degrades only the read-only status feature, with Chinese public copy and no paths or raw errors.
- Before release run `./scripts/test-backend.sh`, `./scripts/test-web.sh`, inspect the archive, then verify the target API.

---

### Task 1: Add the runtime interface path hook

**Files:**
- Create: `packaging/runtime_hooks/ros_runtime_interfaces.py`
- Create: `tests/test_runtime_interface_hook.py`

**Interfaces:**
- Produces `runtime_interface_paths(ament_prefix_path: str | None, *, python_version: str, exists: Callable[[str], bool] = os.path.isdir) -> list[str]`.
- Produces `prepend_runtime_interface_paths(ament_prefix_path: str | None, *, python_version: str) -> None`.
- The hook invokes the latter at module import time, before PyInstaller imports `web_console`.

- [ ] **Step 1: Write the failing tests**

```python
def test_runtime_interface_paths_accepts_only_declared_existing_master_packages(tmp_path: Path) -> None:
    good = tmp_path / "good"
    package = good / "local/lib/python3.10/dist-packages/master_interfaces"
    package.mkdir(parents=True)
    assert runtime_interface_paths(
        f"{good}:{tmp_path / 'missing'}", python_version="python3.10"
    ) == [str(package.parent)]


def test_prepend_runtime_interface_paths_precedes_frozen_path(monkeypatch, tmp_path: Path) -> None:
    prefix = tmp_path / "vehicle"
    package = prefix / "local/lib/python3.10/dist-packages/master_interfaces"
    package.mkdir(parents=True)
    monkeypatch.setattr(sys, "path", ["/tmp/_MEI/frozen", str(package.parent)])
    prepend_runtime_interface_paths(f"{prefix}", python_version="python3.10")
    assert sys.path == [str(package.parent), "/tmp/_MEI/frozen"]
```

- [ ] **Step 2: Run the tests to verify red**

Run: `pixi run python -m pytest -q tests/test_runtime_interface_hook.py`

Expected: FAIL because `packaging/runtime_hooks/ros_runtime_interfaces.py` does not exist.

- [ ] **Step 3: Implement the smallest safe hook**

```python
def runtime_interface_paths(ament_prefix_path, *, python_version, exists=os.path.isdir):
    result = []
    for prefix in (ament_prefix_path or "").split(os.pathsep):
        path = os.path.join(prefix, "local", "lib", python_version, "dist-packages")
        if prefix and exists(os.path.join(path, "master_interfaces")):
            result.append(path)
    return list(dict.fromkeys(result))


def prepend_runtime_interface_paths(ament_prefix_path, *, python_version):
    for path in reversed(runtime_interface_paths(ament_prefix_path, python_version=python_version)):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
```

At module import, call `prepend_runtime_interface_paths(os.environ.get("AMENT_PREFIX_PATH"), python_version=f"python{sys.version_info.major}.{sys.version_info.minor}")`.

- [ ] **Step 4: Run focused tests to verify green**

Run: `pixi run python -m pytest -q tests/test_runtime_interface_hook.py`

Expected: PASS.

- [ ] **Step 5: Commit this task**

Run: `git add packaging/runtime_hooks/ros_runtime_interfaces.py tests/test_runtime_interface_hook.py && git commit -m "fix: load ROS interfaces from vehicle runtime"`

### Task 2: Remove vehicle-specific interfaces from the builder

**Files:**
- Modify: `build_binary.sh:59-148`
- Modify: `export_robot_build_deps.sh:63-67`
- Modify: `tests/test_task_status_codes.py:70-90`

**Interfaces:**
- Consumes the runtime hook through PyInstaller `--runtime-hook`.
- Produces a binary retaining common TF type support but excluding `master_interfaces` code and typesupport libraries.
- Preserves baseline task-service validation with `import master_interfaces.srv`.

- [ ] **Step 1: Replace the old packaging test with a failing contract**

```python
def test_onefile_release_builder_uses_vehicle_runtime_for_localization_interface() -> None:
    builder = (Path(__file__).resolve().parents[1] / "build_binary.sh").read_text(encoding="utf-8")
    assert '--runtime-hook "$BUILD_ROOT/packaging/runtime_hooks/ros_runtime_interfaces.py"' in builder
    assert "--collect-all master_interfaces" not in builder
    assert "--hidden-import master_interfaces.msg._localization_status" not in builder
    assert "for package in tf2_msgs; do" in builder


def test_robot_dependency_export_does_not_require_optional_localization_message() -> None:
    exporter = (Path(__file__).resolve().parents[1] / "export_robot_build_deps.sh").read_text(encoding="utf-8")
    assert "from master_interfaces.msg import LocalizationStatus" not in exporter
    assert "python3 -c 'import master_interfaces.srv'" in exporter
```

- [ ] **Step 2: Run the contract tests to verify red**

Run: `pixi run python -m pytest -q tests/test_task_status_codes.py -k 'release_builder or dependency_export'`

Expected: FAIL because the builder still requires and collects `LocalizationStatus`.

- [ ] **Step 3: Change the packaging boundary**

Change the preflight to:

```sh
python3 -c 'import rclpy; import master_interfaces.srv; import tf2_msgs.msg'
```

Collect ROSIDL libraries only in `for package in tf2_msgs; do`, and add:

```sh
  --runtime-hook "$BUILD_ROOT/packaging/runtime_hooks/ros_runtime_interfaces.py" \
```

Remove both `master_interfaces` hidden imports and `--collect-all master_interfaces`. In `export_robot_build_deps.sh`, use exactly `python3 -c 'import master_interfaces.srv'` for extracted-overlay validation.

- [ ] **Step 4: Run the contract tests to verify green**

Run: `pixi run python -m pytest -q tests/test_task_status_codes.py -k 'release_builder or dependency_export'`

Expected: PASS.

- [ ] **Step 5: Commit this task**

Run: `git add build_binary.sh export_robot_build_deps.sh tests/test_task_status_codes.py && git commit -m "fix: avoid freezing vehicle ROS interfaces"`

### Task 3: Safely identify an unavailable optional interface

**Files:**
- Modify: `autodrive_console/localization_status.py:87-100,145-181`
- Modify: `tests/test_localization_status.py`
- Modify: `shared/contracts/realtime_observation.md`

**Interfaces:**
- Produces `_runtime_unavailable_detail(runtime_state: str, runtime_error: str) -> str`.
- Preserves endpoint keys `phase`, `label`, `detail`, `updated_at`, and all existing relocalization-event behavior.

- [ ] **Step 1: Write the failing degradation test**

```python
def test_status_identifies_missing_vehicle_interface_without_leaking_paths() -> None:
    monitor = LocalizationStatusMonitor(clock=lambda: 1.0)
    monitor._runtime_state = "unavailable"
    monitor._runtime_error = "cannot import LocalizationStatus from /tmp/_MEI/master_interfaces/msg"
    snapshot = monitor.status()
    assert snapshot["phase"] == "unavailable"
    assert snapshot["detail"] == "该车不支持实时定位状态"
    assert "/tmp" not in snapshot["detail"]
```

- [ ] **Step 2: Run the test to verify red**

Run: `pixi run python -m pytest -q tests/test_localization_status.py -k missing_vehicle_interface`

Expected: FAIL because generic subscription-unavailable copy is returned.

- [ ] **Step 3: Implement the controlled public classifier**

```python
def _runtime_unavailable_detail(runtime_state: str, runtime_error: str) -> str:
    if runtime_state != "unavailable":
        return "等待定位状态"
    if "LocalizationStatus" in runtime_error or "master_interfaces.msg" in runtime_error:
        return "该车不支持实时定位状态"
    return "定位状态订阅不可用"
```

Use it for both no-snapshot and stale-snapshot responses. Keep the raw exception in server logs only, and document this optional capability in the observation contract.

- [ ] **Step 4: Run localization tests to verify green**

Run: `pixi run python -m pytest -q tests/test_localization_status.py`

Expected: PASS.

- [ ] **Step 5: Commit this task**

Run: `git add autodrive_console/localization_status.py tests/test_localization_status.py shared/contracts/realtime_observation.md && git commit -m "fix: safely degrade unavailable localization interface"`

### Task 4: Build, inspect, install, and validate the target

**Files:**
- Generated and inspected only: `dist/ry-aletheia` and a signed upgrade ZIP.
- No generated artifact, map, log, package key, or target data is committed.

**Interfaces:**
- Consumes Tasks 1-3.
- Produces a signed package without frozen `master_interfaces`, then verifies the target using the existing controlled upgrade workflow.

- [ ] **Step 1: Run the full relevant checks**

Run: `./scripts/test-backend.sh && ./scripts/test-web.sh`

Expected: both commands exit 0.

- [ ] **Step 2: Build the signed `--shm` upgrade package with the existing release command**

Use the next release version and current signing setup. Do not print signing material or change key permissions.

Expected: a ZIP is generated.

- [ ] **Step 3: Inspect the package before installation**

Use the PyInstaller archive viewer. Verify no entry matches `master_interfaces`, `_localization_status`, or `libmaster_interfaces__rosidl_`, and verify the runtime hook is present.

Expected: no frozen vehicle interface and one runtime hook.

- [ ] **Step 4: Install only through the existing signed console upgrade flow**

Do not use SSH passwords, replace `/opt/ry/install`, or modify the vehicle interface package.

Expected: the console returns after restart.

- [ ] **Step 5: Verify API and PC page**

Read `http://192.168.1.20:8087/api/observation/localization-status` and `http://192.168.1.20:8087/live-observation.html`.

Expected: this vehicle's observed `state: 1` yields `phase: "normal"` and “定位正常”; task-console behavior remains available.

- [ ] **Step 6: Confirm release hygiene**

Run: `git status --short`

Expected: no generated release artifact is staged.
