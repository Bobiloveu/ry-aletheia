"""Background diagnostics must reach the tool logger without exposing user data."""
import io
import logging
import subprocess
import threading

import pytest

from autodrive_console.bag_recording import BagRecordingError, BagRecordingManager, RecordingRequest
from autodrive_console.manual_bag_recording import ManualRecordingController
from autodrive_console.map_projection_jobs import MapProjectionJobs
from autodrive_console.native_report_archive import NativeReportArchive
from autodrive_console.settings import SettingsStore
from autodrive_console.software_inventory import SoftwareInventory
from autodrive_console.upgrade_manager import UpgradeError, UpgradeManager
from test_bag_recording import _FakeCounter, _FakeProcess, _metadata, _recording_environment
from test_manual_bag_recording import _Recordings, _Timer
from test_map_projection_jobs import analyze, wait_state, wait_worker_idle


@pytest.fixture(autouse=True)
def capture_tool_events(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="ry_aletheia")
    logger = logging.getLogger("ry_aletheia")
    monkeypatch.setattr(logger, "propagate", False)
    logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        logger.removeHandler(caplog.handler)


def events(caplog, module, event):
    return [record for record in caplog.records
            if record.name == f"ry_aletheia.{module}" and event in record.getMessage()]


def test_projection_failure_logs_correlated_traceback_and_keeps_sanitized_ui(tmp_path, caplog):
    from autodrive_console.deployment import DeploymentStore
    from autodrive_console import map_projection_jobs
    store = DeploymentStore(tmp_path / "deployments")
    pid = store.create("project")["id"]
    source = tmp_path / "cloud.pcd"
    source.write_bytes(b"original PCD bytes")

    def fail(_source):
        raise OSError("parser could not read /private/source")

    jobs = MapProjectionJobs(store, analyzer=fail)
    job = jobs.create(pid, source)
    failed = wait_state(jobs, pid, job["id"], "failed")
    wait_worker_idle(map_projection_jobs)
    assert "/private" not in failed["message"]
    failures = events(caplog, "map_projection_jobs", "failed")
    assert failures and failures[0].exc_info[0] is OSError
    assert pid in failures[0].getMessage() and job["id"] in failures[0].getMessage()


def test_cancelled_projection_logs_cancel_without_success_adoption(tmp_path, caplog):
    from autodrive_console.deployment import DeploymentStore
    from autodrive_console import map_projection_jobs
    store = DeploymentStore(tmp_path / "deployments")
    pid = store.create("project")["id"]
    source = tmp_path / "cloud.pcd"
    source.write_bytes(b"original PCD bytes")
    entered, release = threading.Event(), threading.Event()

    def delayed(source):
        entered.set()
        assert release.wait(5)
        return analyze(source)

    jobs = MapProjectionJobs(store, analyzer=delayed)
    job = jobs.create(pid, source)
    try:
        assert entered.wait(2)
        jobs.cancel(pid, job["id"])
    finally:
        release.set()
        wait_worker_idle(map_projection_jobs)
    assert jobs.get(pid, job["id"])["state"] == "cancelled"
    assert events(caplog, "map_projection_jobs", "cancelled")
    assert not events(caplog, "map_projection_jobs", "succeeded")


def test_projection_detail_worker_failure_logs_traceback(tmp_path, caplog, monkeypatch):
    from autodrive_console.deployment import DeploymentStore
    from autodrive_console import map_projection_jobs, pcd_projection
    store = DeploymentStore(tmp_path / "deployments")
    pid = store.create("project")["id"]
    source = tmp_path / "cloud.pcd"
    source.write_bytes(b"original PCD bytes")
    jobs = MapProjectionJobs(store, analyzer=analyze)
    job = jobs.create(pid, source)
    wait_state(jobs, pid, job["id"], "awaiting_parameters")

    def fail(*_args):
        raise RuntimeError("detail generation failed")

    monkeypatch.setattr(pcd_projection, "build_source_detail", fail)
    assert jobs.source_detail(pid, job["id"]) is None
    wait_worker_idle(map_projection_jobs)
    failures = events(caplog, "map_projection_jobs", "detail failed")
    assert failures and failures[0].exc_info[0] is RuntimeError


def test_bag_finalization_logs_archive_audit_and_unexpected_failure(tmp_path, caplog, monkeypatch):
    manager = BagRecordingManager(
        tmp_path, topic_probe=lambda: [{"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 1}],
        environment_verifier=_recording_environment, popen=lambda *_args, **_kwargs: _FakeProcess(),
        counter_factory=lambda _types: _FakeCounter(), metadata_reader=_metadata, sleeper=lambda _seconds: None,
    )
    active = manager.start("run123", "private case name", 1, RecordingRequest(1, ("/odom",)))
    active.bag_dir.mkdir()
    (active.bag_dir / "metadata.yaml").write_text("fixture")
    monkeypatch.setattr(manager, "_stop_process", lambda _process: 0)
    summary = manager.stop(active)
    completed = events(caplog, "bag_recording", "finalized")
    assert summary["audit_status"] == "passed"
    assert completed and active.archive_id in completed[0].getMessage()
    assert "passed" in completed[0].getMessage()
    assert "private case name" not in caplog.text

    active = manager.start("run123", "private case name", 2, RecordingRequest(2, ("/odom",)))

    def fail(*_args):
        raise OSError("archive write unavailable")

    monkeypatch.setattr(manager, "_finalize", fail)
    with pytest.raises(OSError):
        manager.stop(active)
    failed = events(caplog, "bag_recording", "finalization failed")
    assert failed and failed[0].exc_info[0] is OSError
    assert active.archive_id in failed[0].getMessage()


def test_manual_deadline_failure_is_logged_and_finalizing_state_is_released(caplog):
    recordings = _Recordings()
    timers = []
    controller = ManualRecordingController(recordings, timer_factory=lambda seconds, callback: timers.append(_Timer(seconds, callback)) or timers[-1])
    controller.start({"topics": ["/odom"], "durationMinutes": 5, "label": "private scene"})

    def fail(_active):
        raise BagRecordingError("archive unavailable")

    recordings.stop = fail
    with pytest.raises(BagRecordingError):
        timers[0].callback()
    assert controller.status()["state"] == "idle"
    failed = events(caplog, "manual_bag_recording", "failed")
    assert failed and failed[0].exc_info[0] is BagRecordingError
    assert "a" * 32 in failed[0].getMessage()
    assert "private scene" not in caplog.text


def test_bag_counter_executor_failure_preserves_exception_and_logs_traceback(caplog):
    from autodrive_console.bag_recording import _RclpyTopicCounter

    class FailingExecutor:
        def spin(self):
            raise RuntimeError("DDS executor failed")

    counter = _RclpyTopicCounter({"/odom": "nav_msgs/msg/Odometry"})
    with pytest.raises(RuntimeError, match="DDS executor failed"):
        counter._spin(FailingExecutor())
    failed = events(caplog, "bag_recording", "executor failed")
    assert failed and failed[0].exc_info[0] is RuntimeError


def test_inventory_polling_logs_only_availability_transitions(caplog, tmp_path):
    unavailable = True

    def runner(*_args, **_kwargs):
        if unavailable:
            raise subprocess.TimeoutExpired("dpkg-query", 5, stderr="private package database contents")
        return subprocess.CompletedProcess([], 0, "ry-runtime\t1.0\tamd64\tii \n", "")

    inventory = SoftwareInventory(SettingsStore(tmp_path / "console.json"), runner=runner)
    assert inventory.snapshot()["inventory_status"] == "unavailable"
    assert inventory.snapshot()["inventory_status"] == "unavailable"
    unavailable_events = events(caplog, "software_inventory", "unavailable")
    assert len(unavailable_events) == 1
    assert "TimeoutExpired" in unavailable_events[0].getMessage()
    unavailable = False
    assert len(inventory.snapshot()["packages"]) == 1
    inventory.snapshot()
    assert len(events(caplog, "software_inventory", "available packages=")) == 1
    assert "private package database contents" not in caplog.text


def test_upgrade_failure_and_success_are_logged_without_upload_name(tmp_path, caplog, monkeypatch):
    binary = tmp_path / "ry-aletheia"
    binary.write_bytes(b"old binary")
    manager = UpgradeManager(tmp_path, binary, True)
    with pytest.raises(UpgradeError):
        manager.apply(io.BytesIO(b"bad"), 3, "private-customer.zip")
    assert events(caplog, "upgrade_manager", "rejected")
    assert binary.read_bytes() == b"old binary"

    def validated(_archive, root):
        candidate = root / "ry-aletheia"
        candidate.write_bytes(b"new binary")
        return {"version": "9.1", "created_at": "2026-10-13", "binary": {"md5": "0" * 32, "size": 10}}, candidate

    monkeypatch.setattr(manager, "_validate_package", validated)
    monkeypatch.setattr(manager, "_verify_candidate_bootable", lambda _candidate: None)
    assert manager.apply(io.BytesIO(b"zip"), 3, "private-customer.zip")["version"] == "9.1"
    assert binary.read_bytes() == b"new binary"
    completed = events(caplog, "upgrade_manager", "succeeded")
    assert completed and "9.1" in completed[0].getMessage()
    assert "private-customer" not in caplog.text


def acceptance_fixture(tmp_path):
    from autodrive_console.acceptance_catalog import AcceptanceTaskCatalog
    from autodrive_console.acceptance_orchestrator import AcceptanceOrchestrator
    from autodrive_console.acceptance_plan import AcceptanceCriteria, AcceptancePlan, AcceptancePlanStore
    from autodrive_console.multi_task_catalog import MultiTaskCatalog
    orchestrator = AcceptanceOrchestrator(
        catalog=AcceptanceTaskCatalog(tmp_path / "tasks"),
        multi_catalog=MultiTaskCatalog(tmp_path / "multi_tasks"),
        plan_store=AcceptancePlanStore(tmp_path / "state"),
        run_manager=None, report_dir=tmp_path / "reports",
    )
    plan = AcceptancePlan(
        plan_id="123456789abc", created_at="2026-10-13T10:00:00+08:00", updated_at="2026-10-13T10:00:00+08:00",
        scope_type="community", community="private community", building=None, unit=None,
        mode="full", random_seed=7, task_pool_size=0, items=[], criteria_snapshot=AcceptanceCriteria.empty().to_dict(),
        status="cancelled",
    )
    return orchestrator, plan


def test_acceptance_report_error_reaches_tool_logger_with_plan_id(tmp_path, caplog, monkeypatch):
    orchestrator, plan = acceptance_fixture(tmp_path)

    def fail(_plan):
        raise OSError("report archive unavailable")

    monkeypatch.setattr(orchestrator.report_writer, "write", fail)
    orchestrator._archive_terminal_report(plan)
    failed = [r for r in caplog.records if r.name == "ry_aletheia.acceptance_orchestrator" and r.exc_info]
    assert failed and plan.plan_id in failed[0].getMessage()
    assert plan.status == "cancelled" and plan.warnings
    assert "private community" not in caplog.text


def test_acceptance_recovery_wait_logs_only_transitions(caplog, tmp_path):
    orchestrator, plan = acceptance_fixture(tmp_path)
    plan.status = "running"
    orchestrator.plan_store.save(plan)
    for _ in range(100):
        orchestrator._on_run_event(plan.plan_id, {"type": "awaiting_recovery", "item_index": 1})
    assert orchestrator.plan_store.load_current().status == "awaiting_recovery"
    assert len(events(caplog, "acceptance_orchestrator", "awaiting recovery")) == 1
    orchestrator._on_run_event(plan.plan_id, {"type": "recovered", "item_index": 1})
    for _ in range(100):
        orchestrator._on_run_event(plan.plan_id, {"type": "awaiting_recovery", "item_index": 1})
    assert len(events(caplog, "acceptance_orchestrator", "awaiting recovery")) == 2


def test_native_archive_migration_failure_is_logged_without_html_contents(tmp_path, caplog, monkeypatch):
    archive = NativeReportArchive(tmp_path)
    html = tmp_path / "test_123456789abc.html"
    html.write_text("private report body")

    def fail(_filename):
        raise OSError("missing frozen evidence")

    monkeypatch.setattr(archive, "_historic_sources", fail)
    assert archive.archive_historic_report(html.name) is False
    failed = events(caplog, "native_report_archive", "migration failed")
    assert failed and failed[0].exc_info[0] is OSError
    assert "private report body" not in caplog.text
