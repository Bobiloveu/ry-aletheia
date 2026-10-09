# Diagnostic ROS Bag Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide optional, auditable and manageable ROS 2 bag capture for one selected round of a normal desktop test run.

**Architecture:** `BagRecordingManager` owns topic discovery, ROS environment validation, recorder/monitor lifecycles, atomic archive finalization and safe archive management. `RunManager` invokes that manager only for the configured target attempt and refuses to dispatch that attempt when capture cannot start. The legacy desktop dashboard configures the request; a separate archive page manages finalized bags.

**Tech Stack:** Python 3, ROS 2 Humble `rclpy` and `rosbag2_py`, `ros2 bag record`, stdlib HTTP server, legacy HTML/CSS/ES modules, pytest and Node test runner.

**Spec:** `docs/superpowers/specs/2026-10-09-diagnostic-rosbag-recording-design.md`

## Global Constraints

- Do not publish ROS Topics, call ROS services, change robot configuration, compile a package, or deploy to a robot.
- `ros2 bag record` only receives a Backend-owned argv and inherited verified environment; no shell invocation or browser-controlled path/env/flags.
- Capture applies only to `RunManager.start`, not acceptance sequences; disabled capture leaves normal test execution unchanged.
- Fixed profile: SQLite3, Zstd file compression, queue 8, two compression threads and 512 MiB cache.
- An enabled capture must be started and preflight-verified before the selected test task is dispatched; a failed audit remains preserved and forces that attempt failed.
- Include `shared/contracts/task_execution.md`; Existing consumers are Desktop Web and Backend, Mobile is non-consumer.

---

### Task 1: Recorder domain model, graph discovery and environment preflight

**Files:**
- Create: `autodrive_console/bag_recording.py`
- Create: `tests/test_bag_recording.py`

**Interfaces:**
- Produces `BagRecordingManager(root: Path, *, popen=..., topic_probe=..., metadata_reader=...)`.
- Produces `available_topics() -> list[dict[str, object]]` and `validate_request(request: object, count: int) -> RecordingRequest | None`.
- Produces `BagRecordingError` for user-actionable failures.

- [ ] **Step 1: Write failing tests for request validation and current-graph discovery.**

```python
def test_validate_request_requires_unique_visible_topics_and_target_round(tmp_path):
    manager = BagRecordingManager(tmp_path, topic_probe=lambda: [
        {"name": "/scan", "type": "sensor_msgs/msg/LaserScan", "publisher_count": 1},
    ])
    assert manager.validate_request({"attemptIndex": 2, "topics": ["/scan"]}, 3).attempt_index == 2
    with pytest.raises(BagRecordingError, match="重复"):
        manager.validate_request({"attemptIndex": 2, "topics": ["/scan", "/scan"]}, 3)
```

- [ ] **Step 2: Run the new test and confirm it fails because the module is absent.**

Run: `pixi run pytest tests/test_bag_recording.py -q`
Expected: import failure for `autodrive_console.bag_recording`.

- [ ] **Step 3: Implement immutable request/profile records and a bounded ROS graph probe.**

```python
@dataclass(frozen=True)
class RecordingRequest:
    attempt_index: int
    topics: tuple[str, ...]

class BagRecordingManager:
    MAX_TOPICS = 32
    def validate_request(self, request: object, count: int) -> RecordingRequest | None:
        ...
```

Use an isolated `rclpy.context.Context`, `Node.get_topic_names_and_types()` and `get_publishers_info_by_topic()`. Return only one-type, non-hidden, publisher-backed topics in stable name order. Keep imports lazy so a missing ROS installation produces a clear `BagRecordingError` rather than crashing console startup.

- [ ] **Step 4: Add failing environment tests, run them, then implement the verified inherited-environment profile.**

```python
def test_environment_profile_rejects_missing_ros_prefix(tmp_path):
    manager = BagRecordingManager(tmp_path, environment={"ROS_DISTRO": "humble", "PATH": "/empty"})
    with pytest.raises(BagRecordingError, match="ROS 环境"):
        manager.verify_environment()
```

Validate ROS_DISTRO, AMENT_PREFIX_PATH, `shutil.which("ros2")`, and retain only the allowed environment fingerprint fields. Never source a shell script or accept env input through HTTP.

- [ ] **Step 5: Run the focused test file and commit the isolated unit.**

Run: `pixi run pytest tests/test_bag_recording.py -q`
Expected: PASS.

```bash
git add autodrive_console/bag_recording.py tests/test_bag_recording.py
git commit -m "feat: validate diagnostic bag recording requests"
```

### Task 2: Controlled recorder lifecycle, monitor and atomic audit archive

**Files:**
- Modify: `autodrive_console/bag_recording.py`
- Modify: `tests/test_bag_recording.py`

**Interfaces:**
- Produces `start(run_id: str, case_name: str, attempt_index: int, request: RecordingRequest) -> ActiveRecording`.
- Produces `stop(active: ActiveRecording) -> dict[str, object]` summary suitable for `AttemptResult`.
- Produces `list_archives()`, `archive_detail(id)`, `open_archive(id)`, and `delete_archive(id)`.

- [ ] **Step 1: Write failing tests for whitelisted argv, selected-topic presence and target-safe finalization.**

```python
def test_stop_writes_manifest_with_hashes_and_metadata_counts(tmp_path, fake_popen, metadata_reader):
    manager = BagRecordingManager(tmp_path, popen=fake_popen, metadata_reader=metadata_reader)
    active = manager.start("run123", "巡检", 2, RecordingRequest(2, ("/scan",)))
    summary = manager.stop(active)
    assert summary["audit"]["status"] == "passed"
    assert (tmp_path / summary["archive_id"] / "manifest.json").is_file()
```

- [ ] **Step 2: Run the lifecycle tests and confirm failure before implementation.**

Run: `pixi run pytest tests/test_bag_recording.py -q`
Expected: missing lifecycle methods/assertion failure.

- [ ] **Step 3: Implement safe recorder ownership and topic counting.**

Build the fixed argv from controlled stage paths. Use `Popen(..., shell=False, start_new_session=True, close_fds=True, env=verified_environment)`, log output inside staging, wait through startup grace, and terminate the owned process group with SIGINT then SIGKILL fallback. Implement dynamic message resolution with `rosidl_runtime_py.utilities.get_message`, an isolated `rclpy` Context and subscriptions which count messages only; counter startup or runtime failure is audit failure.

- [ ] **Step 4: Implement metadata inspection and atomic artifact finalization.**

Use `rosbag2_py.Info.read_metadata`; reject absent selected topics, zero selected-topic counts, unexpected compression/storage, symlinks and files outside staging. Calculate SHA-256 for each regular file, create `manifest.json.tmp`, `flush`/`fsync`, replace it, then rename staging to final directory. Calculate per-topic loss against monitor count and apply 1%/5% thresholds. Preserve failed bags. On constructor startup, convert stale staging directories into explicit incomplete archives.

- [ ] **Step 5: Add failing tests for startup crash, integrity failure, loss thresholds, recovery and confined deletion; implement until green.**

```python
def test_delete_rejects_active_or_path_escape_archive(tmp_path):
    manager = BagRecordingManager(tmp_path)
    with pytest.raises(BagRecordingError):
        manager.delete_archive("../../etc")
```

Run: `pixi run pytest tests/test_bag_recording.py -q`
Expected: PASS.

- [ ] **Step 6: Commit the lifecycle and archive implementation.**

```bash
git add autodrive_console/bag_recording.py tests/test_bag_recording.py
git commit -m "feat: add auditable ROS bag archive lifecycle"
```

### Task 3: Integrate the selected capture with normal test execution

**Files:**
- Modify: `autodrive_console/models.py`
- Modify: `autodrive_console/run_manager.py`
- Modify: `tests/test_run_manager.py`
- Modify: `web_console.py`
- Modify: `tests/test_web_console.py`

**Interfaces:**
- `RunManager(..., bag_recordings: BagRecordingManager | None = None)`.
- `RunManager.start(..., bag_recording: object | None = None)`.
- `AttemptResult.bag_recording: dict[str, Any] | None` serialized as `bagRecording`.

- [ ] **Step 1: Write a failing RunManager test that verifies only the requested attempt starts/stops capture.**

```python
def test_run_manager_records_only_selected_round_and_stops_before_result(tmp_path):
    recorder = FakeBagRecorder()
    manager = RunManager(tmp_path / "reports", FakeExecutor(), FakeSettings(), bag_recordings=recorder)
    run = manager.start(case, 3, 0, bag_recording={"attemptIndex": 2, "topics": ["/scan"]})
    wait_finished(manager, run.id)
    assert recorder.started_attempts == [2]
    assert manager.get(run.id).attempts[1].bag_recording["audit"]["status"] == "passed"
```

- [ ] **Step 2: Run the targeted test and confirm it fails for the absent constructor/argument.**

Run: `pixi run pytest tests/test_run_manager.py -q`
Expected: constructor or start signature failure.

- [ ] **Step 3: Add model serialization and RunManager fail-closed integration.**

At the beginning of the target loop iteration, call recorder start before trajectory/task executor. If start fails, append a clearly labeled failed attempt, set run error and stop remaining rounds without calling the executor. In `finally`, stop active capture on success, cancellation and execution exceptions. Attach the finalized audit to the attempt; audit failure forces that attempt failed while retaining the actual service message. Do not modify `start_sequence`.

- [ ] **Step 4: Add tests for start failure preventing executor use and audit failure forcing the attempt failed; run green.**

Run: `pixi run pytest tests/test_run_manager.py tests/test_bag_recording.py -q`
Expected: PASS.

- [ ] **Step 5: Write failing HTTP route tests, then wire the manager into `web_console.py`.**

Expose topic/list/detail/download/delete routes through controlled IDs. Extend only `POST /api/runs` to read optional `bagRecording`; instantiate one manager rooted at `WORKSPACE / "bag_recordings"`; retain existing response fields and error handling. Test malformed request rejection and Desktop-only API behavior.

Run: `pixi run pytest tests/test_web_console.py tests/test_run_manager.py tests/test_bag_recording.py -q`
Expected: PASS.

- [ ] **Step 6: Commit Backend integration.**

```bash
git add autodrive_console/models.py autodrive_console/run_manager.py web_console.py tests/test_run_manager.py tests/test_web_console.py
git commit -m "feat: record selected diagnostic test round"
```

### Task 4: Desktop workflow and archive management

**Files:**
- Modify: `autodrive_console/web/index.html`
- Modify: `autodrive_console/web/app.js`
- Modify: `autodrive_console/web/styles.css`
- Create: `autodrive_console/web/bag-recordings.html`
- Create: `autodrive_console/web/bag_recordings.js`
- Create: `autodrive_console/web/bag_recordings.css`
- Modify: `web_console.py`
- Modify: `frontend/test/legacy-app-module.test.mjs`

**Interfaces:**
- Dashboard sends `bagRecording: null | {attemptIndex, topics}` with `POST /api/runs`.
- Archive page consumes only `/api/bag-recordings*`; it has no ROS client code.

- [ ] **Step 1: Write a failing browser-module test for building a valid recording request.**

```js
test('diagnostic capture payload is omitted while disabled and includes selected round/topics while enabled', () => {
  assert.equal(buildBagRecordingPayload({ enabled: false }), null);
  assert.deepEqual(buildBagRecordingPayload({ enabled: true, attemptIndex: 3, topics: ['/scan'] }), {
    attemptIndex: 3, topics: ['/scan']
  });
});
```

- [ ] **Step 2: Run the module test and confirm it fails before exporting the helper.**

Run: `pixi run node --test frontend/test/legacy-app-module.test.mjs`
Expected: missing export or assertion failure.

- [ ] **Step 3: Add dashboard controls and request construction.**

Use a disabled-by-default checkbox, numeric target constrained by current count, refresh/searchable topic list, checked topic count, and threshold copy. Fetch discovery only after enabling/refreshing. Prevent start with enabled recording and zero valid selection. Render selected attempt audit in the execution ledger using text nodes, not interpolated HTML.

- [ ] **Step 4: Add the archive page and controlled navigation.**

Add one sidebar entry on desktop. List display name, case, target round, capture time, bytes, compression and audit badge; expose details, direct download and confirmed delete. The page must display clear `incomplete`/`failed` reasons and no absolute paths, command line or environment dump.

- [ ] **Step 5: Add static routing and mobile boundary.**

Serve `/bag-recordings.html` as a Desktop page and leave it out of `MOBILE_PAGE_NAMES`; ensure app-shell navigation remains consistent.

- [ ] **Step 6: Run Web tests and commit.**

Run: `pixi run node --test frontend/test/legacy-app-module.test.mjs`
Expected: PASS.

```bash
git add autodrive_console/web web_console.py frontend/test/legacy-app-module.test.mjs
git commit -m "feat: add desktop diagnostic bag recording workflow"
```

### Task 5: Contract, regression suite and audit review

**Files:**
- Modify: `shared/contracts/task_execution.md`
- Modify: `docs/superpowers/specs/2026-10-09-diagnostic-rosbag-recording-design.md`
- Modify: `docs/superpowers/plans/2026-10-09-diagnostic-rosbag-recording.md`

**Interfaces:**
- Contract documents `bagRecording` request plus all `/api/bag-recordings*` responses and Desktop/Mobile consumer status.

- [ ] **Step 1: Update the task-execution contract before final test runs.**

Document controlled environment behavior, selected-topic graph validation, selected-round semantics, fixed compression profile, audit outcomes, archive path boundary and endpoint consumers. Record Desktop Web and Backend as affected consumers, Mobile as non-consumer.

- [ ] **Step 2: Run focused backend and frontend checks.**

Run: `pixi run pytest tests/test_bag_recording.py tests/test_run_manager.py tests/test_web_console.py -q`
Expected: PASS.

Run: `pixi run node --test frontend/test/legacy-app-module.test.mjs`
Expected: PASS.

- [ ] **Step 3: Run required module checks without producing deployment artifacts.**

Run: `pixi run test`
Expected: PASS.

Run: `pixi run frontend-check`
Expected: PASS.

Do not run a package build, offline upgrade build, deploy script, service restart or robot command.

- [ ] **Step 4: Inspect final diff and contract coverage, then commit.**

```bash
git diff --check
git status --short
git add shared/contracts/task_execution.md docs/superpowers/specs/2026-10-09-diagnostic-rosbag-recording-design.md docs/superpowers/plans/2026-10-09-diagnostic-rosbag-recording.md
git commit -m "docs: specify diagnostic bag recording contract"
```
