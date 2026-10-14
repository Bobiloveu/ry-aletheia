"""Diagnostic edges must not suppress repeated robot safety actions."""
import logging
import subprocess
from types import SimpleNamespace

import pytest

from autodrive_console.autostart import AutostartManager
from autodrive_console.map_marker_navigation import MapMarkerNavigationController
from autodrive_console.task_status_codes import TaskStatusCodeError
from autodrive_console.vehicle_control import VehicleControlController
from autodrive_console.vehicle_execution_status.monitor import VehicleExecutionStatusMonitor


@pytest.fixture(autouse=True)
def capture_tool_namespace(caplog):
    caplog.set_level(logging.INFO, logger="ry_aletheia")
    logger = logging.getLogger("ry_aletheia")
    handler_added = not logger.propagate
    if handler_added:
        logger.addHandler(caplog.handler)
    yield
    if handler_added:
        logger.removeHandler(caplog.handler)


def _records(caplog, namespace):
    return [record for record in caplog.records if record.name == namespace]


def test_autostart_fallback_records_reason_and_selected_mode(tmp_path, caplog):
    def unavailable(command, **kwargs):
        raise FileNotFoundError("systemctl unavailable")

    manager = AutostartManager(tmp_path / "workspace", home=tmp_path / "home", runner=unavailable)
    result = manager.apply(True)

    assert result["mode"] == "desktop-autostart"
    records = _records(caplog, "ry_aletheia.autostart")
    assert any(record.levelno == logging.WARNING and "systemctl unavailable" in record.message for record in records)
    assert any(record.levelno == logging.INFO and "desktop-autostart" in record.message for record in records)


def test_autostart_disable_logs_unavailable_systemd_and_removes_owned_files(tmp_path, caplog):
    def unavailable(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stderr="user bus unavailable")

    manager = AutostartManager(tmp_path / "workspace", home=tmp_path / "home", runner=unavailable)
    manager.service_path.parent.mkdir(parents=True)
    manager.service_path.write_text("owned unit", encoding="utf-8")

    result = manager.apply(False)

    assert result["enabled"] is False and not manager.service_path.exists()
    records = _records(caplog, "ry_aletheia.autostart")
    assert any(record.levelno == logging.WARNING and "user bus unavailable" in record.message for record in records)
    assert any(record.levelno == logging.INFO and "none" in record.message for record in records)


class _Publisher:
    def __init__(self):
        self.messages = []
        self.attempts = 0
        self.failing = False

    def publish(self, message):
        self.attempts += 1
        if self.failing:
            raise RuntimeError("publisher unavailable")
        self.messages.append(message)


def _control():
    control = VehicleControlController(clock=lambda: 10.0)
    control._runtime_state = "ready"
    control._Twist = lambda: SimpleNamespace(linear=SimpleNamespace(x=0.0, y=0.0, z=0.0), angular=SimpleNamespace(x=0.0, y=0.0, z=0.0))
    control._velocity_publisher = _Publisher()
    return control


def test_query_scheduler_failures_log_once_and_leave_stop_burst_running(monkeypatch, caplog):
    control = _control()
    control._stop_pending = True

    def failed_query():
        raise RuntimeError("query scheduling unavailable")

    monkeypatch.setattr(control, "_request_emergency_state_if_needed", failed_query)
    for _ in range(20):
        control._on_publish_tick()
    monkeypatch.setattr(control, "_request_emergency_state_if_needed", lambda: None)
    control._on_publish_tick()

    assert len(control._velocity_publisher.messages) == 3
    assert all(message.linear.x == 0.0 and message.angular.z == 0.0 for message in control._velocity_publisher.messages)
    records = _records(caplog, "ry_aletheia.vehicle_control")
    assert [record.levelno for record in records] == [logging.ERROR, logging.INFO]


def test_stop_failure_logging_does_not_reduce_stop_retries(caplog):
    control = _control()
    control._stop_pending = True
    control._velocity_publisher.failing = True
    for _ in range(20):
        control._publish_stop_now()
    assert control._stop_pending is True
    control._velocity_publisher.failing = False
    control._publish_stop_now()

    assert control._velocity_publisher.attempts == 21
    assert control._stop_pending is False
    assert control._velocity_publisher.messages[-1].linear.x == 0.0
    records = _records(caplog, "ry_aletheia.vehicle_control")
    assert [record.levelno for record in records] == [logging.ERROR, logging.INFO]


def test_repeated_emergency_stop_confirmation_logs_once_but_keeps_stopping(caplog):
    control = _control()
    for _ in range(20):
        control._on_emergency_stop(SimpleNamespace(data=True))

    assert control._velocity_publisher.attempts == 20
    assert control._emergency_stop is True
    records = _records(caplog, "ry_aletheia.vehicle_control")
    assert [record.levelno for record in records] == [logging.WARNING]


@pytest.mark.parametrize("mode", ["command", "vector"])
def test_continuous_control_inputs_log_movement_edges_without_session_tokens(caplog, mode):
    control = _control()
    control._actual_source = "miniapp"
    control._emergency_stop = False
    control._emergency_last_confirmed_at = 10.0
    control._sessions["private-session-token"] = {"id": "private-session-token", "state": "active", "last_heartbeat_at": 10.0, "last_input_at": 10.0}
    for index in range(20):
        if mode == "command":
            control.set_command("private-session-token", "forward")
        else:
            control.set_vector("private-session-token", 0.2 + index / 100, 0.0)
    control.stop("private-session-token")
    control.stop("private-session-token")

    assert control._target_linear == 0.0
    records = _records(caplog, "ry_aletheia.vehicle_control")
    assert len(records) == 2 and all(record.levelno == logging.INFO for record in records)
    assert mode in records[0].message
    assert "private-session-token" not in caplog.text


def test_emergency_topic_heartbeat_does_not_claim_query_service_recovery(caplog):
    control = _control()
    now = [10.0]
    control._clock = lambda: now[0]
    control._map_marker_navigation_guard = lambda: True
    attempts = []

    def failed_query(_request):
        attempts.append(None)
        raise RuntimeError("emergency service unavailable")

    control._GetEmergencyStop = SimpleNamespace(Request=lambda: object())
    control._emergency_state_client = SimpleNamespace(service_is_ready=lambda: True, call_async=failed_query)
    for _ in range(20):
        control._on_emergency_stop(SimpleNamespace(data=False))
        control._request_emergency_state_if_needed()
        now[0] += 1.0
    control._on_emergency_query_response(SimpleNamespace(is_emergency_stop=False), generation=control._emergency_state_generation)

    assert len(attempts) == 20
    records = _records(caplog, "ry_aletheia.vehicle_control")
    assert [record.levelno for record in records] == [logging.WARNING, logging.INFO]


def _navigation():
    return MapMarkerNavigationController(object(), object(), object(), object(), active_run_guard=lambda: False, transport=SimpleNamespace(cancel=lambda goal: None))


def test_automatic_navigation_cancel_logs_reason_once(caplog):
    navigation = _navigation()
    navigation._phase, navigation._goal = "navigating", object()
    navigation._request_cancel("active map changed")
    navigation._request_cancel("active map changed")

    assert navigation._phase == "cancelling" and navigation.blocks_runs()
    records = _records(caplog, "ry_aletheia.map_marker_navigation")
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    assert "active map changed" in records[0].message


@pytest.mark.parametrize("initial,success,level", [("navigating", False, logging.ERROR), ("navigating", True, logging.INFO), ("cancelling", False, logging.INFO)])
def test_navigation_result_uses_failure_severity(caplog, initial, success, level):
    navigation = _navigation()
    navigation._phase = initial
    navigation._on_result(SimpleNamespace(success=success))
    records = _records(caplog, "ry_aletheia.map_marker_navigation")
    assert len(records) == 1 and records[0].levelno == level


def test_navigation_monitor_logs_failure_recovery_edges_while_continuing_checks(monkeypatch, caplog):
    navigation = _navigation()
    calls = []

    def check():
        calls.append(None)
        if len(calls) <= 20:
            raise RuntimeError("monitor unavailable")

    iterations = iter([False] * 22 + [True])
    monkeypatch.setattr(navigation, "_monitor_once", check)
    monkeypatch.setattr(navigation._monitor_stop, "wait", lambda timeout: next(iterations))
    navigation._monitor_loop()

    assert len(calls) == 22
    records = _records(caplog, "ry_aletheia.map_marker_navigation")
    assert [record.levelno for record in records] == [logging.ERROR, logging.INFO]


def test_navigation_transport_exception_is_diagnostic_error(monkeypatch, caplog):
    from autodrive_console.map_marker_navigation import MapMarkerNavigationUnavailable

    navigation = _navigation()
    navigation._marker_store = SimpleNamespace(resolve=lambda *_args: SimpleNamespace(x=0.0, y=0.0, yaw=0.0))

    def fail_transport(*_args):
        raise RuntimeError("transport unavailable")

    navigation._transport = SimpleNamespace(send_goal=fail_transport)
    monkeypatch.setattr(navigation, "_wait_for_safe_to_begin", lambda: None)
    monkeypatch.setattr(navigation, "_require_active_map_id", lambda: "map")
    monkeypatch.setattr(navigation, "_require_current_map", lambda _map: None)
    with pytest.raises(MapMarkerNavigationUnavailable):
        navigation.begin_marker("marker")

    assert navigation._phase == "failed" and not navigation.blocks_runs()
    records = _records(caplog, "ry_aletheia.map_marker_navigation")
    assert len(records) == 1 and records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None


@pytest.mark.parametrize("dependency", ["control", "restarting", "registry"])
def test_execution_monitor_poll_errors_log_once_then_recovery(monkeypatch, caplog, dependency):
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0)
    failed = True
    reads = []

    def read(*args):
        reads.append(None)
        if failed:
            if dependency == "registry":
                raise TaskStatusCodeError("registry unavailable")
            raise RuntimeError("monitor input unavailable")
        return "109" if dependency == "registry" else {} if dependency == "control" else False

    if dependency == "control":
        monitor._vehicle_control_status = read
        poll = monitor.status
    elif dependency == "restarting":
        monitor._restarting_nodes = read
        poll = monitor.status
    else:
        monkeypatch.setattr("autodrive_console.vehicle_execution_status.monitor.task_status_code", read)
        poll = monitor._task_complete_code
    for _ in range(20):
        poll()
    failed = False
    poll()
    poll()

    assert len(reads) == 22
    records = _records(caplog, "ry_aletheia.vehicle_execution_status")
    assert [record.levelno for record in records] == [logging.ERROR, logging.INFO]
