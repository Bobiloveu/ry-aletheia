"""Service diagnostics without launching ROS, subprocesses, or the HTTP runtime."""
import logging
import threading
from types import SimpleNamespace

import pytest

from autodrive_console.mapping import MappingSessionController
from autodrive_console.models import RunRecord, TaskParameters, TestCase as Case
from autodrive_console.run_manager import RunManager
from autodrive_console.scenario_activation import ScenarioActivationTracker
from autodrive_console.supervisor import SupervisorClient
from autodrive_console.trajectory import TrajectorySession


@pytest.fixture(autouse=True)
def capture_tool_namespace(caplog):
    # HTTP test modules configure a non-propagating application logger during
    # collection. Capture that real destination as well as pytest's root logger.
    logger = logging.getLogger("ry_aletheia")
    handler_added = not logger.propagate
    if handler_added:
        logger.addHandler(caplog.handler)
    yield
    if handler_added:
        logger.removeHandler(caplog.handler)


def _records(caplog, namespace):
    return [record for record in caplog.records if record.name == namespace]


def test_mapping_unexpected_exit_is_logged_once_across_status_polling(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="ry_aletheia")
    controller = MappingSessionController(tmp_path / "sessions")
    controller._session = {"id": "mapping-test", "project_id": "project-test", "state": "running", "preview": {}}
    controller._process = SimpleNamespace(pid=17, poll=lambda: 23)
    monkeypatch.setattr(controller, "_stop_preview_listener", lambda: None)
    monkeypatch.setattr(controller, "_probe_lightning", lambda: (True, "ready"))

    assert controller.status()["session"]["state"] == "failed"
    controller.status()

    records = _records(caplog, "ry_aletheia.mapping")
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert "mapping-test" in records[0].message and "23" in records[0].message


def test_mapping_failed_save_is_logged_even_when_stop_returns_a_snapshot(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="ry_aletheia")
    controller = MappingSessionController(tmp_path / "sessions")
    controller._session = {"id": "mapping-test", "project_id": "project-test", "state": "running", "preview": {}}
    monkeypatch.setattr(controller, "_stop_preview_listener", lambda: None)

    def fail_save(_session_id):
        raise OSError("disk full")

    monkeypatch.setattr(controller, "_save_map", fail_save)
    result = controller.stop("mapping-test")

    assert result["state"] == "stopped"
    errors = [record for record in _records(caplog, "ry_aletheia.mapping") if record.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "mapping-test" in errors[0].message and "disk full" in errors[0].message


def test_mapping_preview_failure_logs_edges_instead_of_every_grid(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="ry_aletheia")
    controller = MappingSessionController(tmp_path / "sessions")
    controller._session = {"id": "mapping-test", "label": "map", "state": "running", "preview": {"revision": 0}}

    def fail_cache(*_args, **_kwargs):
        raise OSError("disk full")

    with monkeypatch.context() as failures:
        failures.setattr("autodrive_console.mapping.MapAssetCache.cache_occupancy_grid", fail_cache)
        for _ in range(20):
            controller.ingest_grid(resolution=0.2, width=2, height=2, origin=[0, 0, 0], frame_id="map", data=[0, 0, 0, 0])
    controller.ingest_grid(resolution=0.2, width=2, height=2, origin=[0, 0, 0], frame_id="map", data=[0, 0, 0, 0])

    records = _records(caplog, "ry_aletheia.mapping")
    assert [record.levelno for record in records] == [logging.WARNING, logging.INFO]
    assert controller._session["preview"]["revision"] == 1


def test_scenario_activation_logs_accepted_phase_edges_and_terminal_result(caplog):
    caplog.set_level(logging.INFO, logger="ry_aletheia")
    workers = []

    def runner(_profile_id, _document, progress):
        for _ in range(20):
            progress("restarting", "等待节点", {"stages": []})
        return {"message": "ready"}

    tracker = ScenarioActivationTracker(runner, thread_factory=lambda **kwargs: workers.append(kwargs["target"]) or SimpleNamespace(start=lambda: None))
    tracker.start("hall", {"secret": "must-not-log"})
    workers[0]()

    records = _records(caplog, "ry_aletheia.scenario_activation")
    assert tracker.status()["state"] == "completed"
    assert len(records) == 3
    assert "hall" in records[0].message and "hall" in records[-1].message
    assert "restarting" in records[1].message
    assert "must-not-log" not in caplog.text


@pytest.mark.parametrize("returncode", [0, 7])
def test_supervisor_logs_actual_action_results_without_command_credentials(monkeypatch, caplog, returncode):
    caplog.set_level(logging.INFO, logger="ry_aletheia")
    monkeypatch.setattr("autodrive_console.supervisor.subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=returncode, stdout="node RUNNING\n", stderr=""))
    client = SupervisorClient("supervisorctl -u operator -p private-secret status", 5)
    if returncode:
        with pytest.raises(RuntimeError):
            client.restart("robot:nav")
    else:
        client.restart("robot:nav")
    count = len(_records(caplog, "ry_aletheia.supervisor"))
    client.discover()

    records = _records(caplog, "ry_aletheia.supervisor")
    assert len(records) == count and count >= 1
    assert "robot:nav" in records[-1].message and "restart" in records[-1].message
    assert records[-1].levelno == (logging.ERROR if returncode else logging.INFO)
    assert "private-secret" not in caplog.text


def test_supervisor_timeout_log_omits_command_embedded_in_exception(monkeypatch, caplog):
    import subprocess

    caplog.set_level(logging.INFO, logger="ry_aletheia")

    def timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 5)

    monkeypatch.setattr("autodrive_console.supervisor.subprocess.run", timeout)
    with pytest.raises(RuntimeError):
        SupervisorClient("supervisorctl -p private-secret status", 5).start("robot:nav")
    assert any(record.levelno == logging.ERROR for record in _records(caplog, "ry_aletheia.supervisor"))
    assert "private-secret" not in caplog.text


@pytest.mark.parametrize("outcome", ["passed", "failed", "cancelled", "blocked"])
def test_run_records_attempt_outcomes_and_blocked_reason(tmp_path, monkeypatch, caplog, outcome):
    caplog.set_level(logging.INFO, logger="ry_aletheia")
    case = Case("case-test", "case.json", "case", TaskParameters("site", 1, 1, 1, 101), "unused.json")
    run = RunRecord("run-test", case, 1, 0, prepare_trajectory_maps=False)
    cancel = threading.Event()

    def execute(*_args, **_kwargs):
        if outcome == "cancelled":
            cancel.set()
        return outcome == "passed", "task-result", 1.2

    executor = SimpleNamespace(execute=execute, wait_until_available=lambda **kwargs: (True, "ready"))
    manager = RunManager(tmp_path / "reports", executor, SimpleNamespace(load=lambda: SimpleNamespace(task_execution_timeout_s=60)))
    manager._cancel_events[run.id] = cancel
    manager._resume_events[run.id] = threading.Event()
    manager._attempt_interrupt_events[run.id] = threading.Event()
    run._skip_report = True
    preflight = SimpleNamespace(ok=outcome != "blocked", message="dependency unavailable", to_dict=lambda: {})
    gateway = SimpleNamespace(preflight=lambda *_args, **_kwargs: preflight, confirm_dependencies_ready=lambda **kwargs: (True, "ready", []))
    monkeypatch.setattr("autodrive_console.run_manager.RobotGateway", lambda *args: gateway)

    manager._run(run)

    records = _records(caplog, "ry_aletheia.run")
    if outcome == "blocked":
        assert run.status == "blocked"
        assert any(record.levelno >= logging.WARNING and "dependency unavailable" in record.message for record in records)
    else:
        terminal = [record for record in records if "attempt=1" in record.message and f"status={outcome}" in record.message]
        assert len(terminal) == 1
        assert "run-test" in terminal[0].message and "task-result" in terminal[0].message
        assert terminal[0].levelno == (logging.WARNING if outcome == "failed" else logging.INFO)


def test_trajectory_summary_logs_rejected_evidence_without_per_sample_noise(caplog):
    caplog.set_level(logging.INFO, logger="ry_aletheia")
    trajectory = TrajectorySession([])
    trajectory._tf_errors = 4
    trajectory._points_rejected = 4
    trajectory._tf_last_error = "map transform unavailable"

    summary = trajectory.stop()

    assert summary["diagnostics"]["points_rejected"] == 4
    records = _records(caplog, "ry_aletheia.trajectory")
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "4" in records[0].message and "map transform unavailable" in records[0].message


def test_trajectory_localization_monitor_failure_logs_only_failure_and_recovery_edges(caplog):
    caplog.set_level(logging.INFO, logger="ry_aletheia")

    class Monitor:
        failing = True

        def events_since(self, cursor):
            if self.failing:
                raise RuntimeError("monitor unavailable")
            return cursor, []

    monitor = Monitor()
    trajectory = TrajectorySession([], localization_monitor=monitor)
    for _ in range(20):
        trajectory._record_relocalizations_for_sample(None)
    monitor.failing = False
    trajectory._record_relocalizations_for_sample(None)
    trajectory._record_relocalizations_for_sample(None)

    records = _records(caplog, "ry_aletheia.trajectory")
    assert [record.levelno for record in records] == [logging.WARNING, logging.INFO]
