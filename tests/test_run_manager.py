from __future__ import annotations

import time
from types import SimpleNamespace
from pathlib import Path

from autodrive_console.models import MultiDestination, MultiTaskRequest, TaskParameters, TestCase as AcceptanceTestCase
from autodrive_console.run_manager import RunManager


class FakeSettings:
    def load(self):
        return SimpleNamespace(dependency_plan={"enabled": False, "steps": []})


class FakeGateway:
    def __init__(self, *_args, **_kwargs):
        pass

    def preflight_without_orchestration(self, *_args, **_kwargs):
        return SimpleNamespace(ok=True, message="ready", to_dict=lambda: {"ok": True, "message": "ready"})

    def preflight(self, *_args, **_kwargs):
        return self.preflight_without_orchestration()

    def confirm_dependencies_ready(self, **_kwargs):
        return True, "ready", []


class FakeExecutor:
    def __init__(self):
        self.single_calls = 0
        self.multi_calls = []

    def wait_until_available(self, **_kwargs):
        return True, "ready"

    def execute(self, *_args, **_kwargs):
        self.single_calls += 1
        return True, "single", 0.01

    def execute_multi(self, request, *_args, **_kwargs):
        self.multi_calls.append(request)
        return SimpleNamespace(
            success=True,
            message="multi",
            duration_s=0.01,
            delivery_evidence=[
                {"delivery_code": item.delivery_code, "status": "passed", "message": "收到配送码事件"}
                for item in request.destinations
            ],
        )


def test_run_manager_dispatches_one_r6b_chain_to_execute_multi(monkeypatch, tmp_path):
    monkeypatch.setattr("autodrive_console.run_manager.RobotGateway", FakeGateway)
    executor = FakeExecutor()
    manager = RunManager(tmp_path / "reports", executor, FakeSettings())
    request = MultiTaskRequest(
        "数创大厦",
        False,
        True,
        (MultiDestination("5", "1", "5", "501", 1, "code-501"),),
        "task-001",
    )
    case = AcceptanceTestCase(
        "chain-1",
        "chain-1.json",
        "chain-1",
        TaskParameters("数创大厦", 5, 1, 5, 501, "multi_r6b"),
        str(Path("/tmp/route.json")),
        execution_mode="multi_r6b",
        multi_request=request,
    )
    events = []

    run = manager.start_sequence([case], prepare_trajectory_maps=False, event_callback=events.append)
    deadline = time.monotonic() + 3
    while manager.get(run.id).status in {"preparing", "running"} and time.monotonic() < deadline:
        time.sleep(0.01)

    assert manager.get(run.id).status == "completed"
    assert executor.single_calls == 0
    assert executor.multi_calls == [request]
    finished = next(item for item in events if item["type"] == "item_finished")
    assert finished["attempt"]["delivery_evidence"][0]["delivery_code"] == "code-501"


def test_run_manager_marks_multi_chain_failed_when_delivery_event_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("autodrive_console.run_manager.RobotGateway", FakeGateway)

    class MissingDeliveryExecutor(FakeExecutor):
        def execute_multi(self, request, *_args, **_kwargs):
            self.multi_calls.append(request)
            return SimpleNamespace(
                success=False,
                message="服务返回成功，但未收到配送码事件：code-301",
                duration_s=0.01,
                delivery_evidence=[
                    {"delivery_code": "code-501", "status": "passed", "message": "收到配送码事件"},
                    {"delivery_code": "code-301", "status": "skipped", "message": "未收到匹配的 701 配送码事件"},
                ],
            )

    executor = MissingDeliveryExecutor()
    manager = RunManager(tmp_path / "reports", executor, FakeSettings())
    request = MultiTaskRequest(
        "数创大厦", False, True,
        (
            MultiDestination("5", "1", "5", "501", 1, "code-501"),
            MultiDestination("5", "1", "3", "301", 2, "code-301"),
        ),
        "task-002",
    )
    case = AcceptanceTestCase(
        "chain-2", "chain-2.json", "chain-2",
        TaskParameters("数创大厦", 5, 1, 5, 501, "multi_r6b"), str(Path("/tmp/route.json")),
        execution_mode="multi_r6b", multi_request=request,
    )
    events = []

    run = manager.start_sequence([case], prepare_trajectory_maps=False, event_callback=events.append)
    deadline = time.monotonic() + 3
    while manager.get(run.id).status in {"preparing", "running", "awaiting_recovery"} and time.monotonic() < deadline:
        if manager.get(run.id).status == "awaiting_recovery":
            manager.cancel(run.id)
        time.sleep(0.01)

    finished = next(item for item in events if item["type"] == "item_finished")
    assert finished["attempt"]["status"] == "failed"
    assert finished["attempt"]["delivery_evidence"][1]["status"] == "skipped"

class FakeBagRecorder:
    def __init__(self, *, start_error: Exception | None = None, audit_status: str = "passed"):
        self.start_error = start_error
        self.audit_status = audit_status
        self.validated = []
        self.started_attempts = []
        self.stopped_attempts = []

    def validate_request(self, request, count):
        self.validated.append((request, count))
        return SimpleNamespace(attempt_index=request["attemptIndex"], topics=tuple(request["topics"])) if request else None

    def start(self, run_id, case_name, attempt_index, request):
        self.started_attempts.append(attempt_index)
        if self.start_error:
            raise self.start_error
        return SimpleNamespace(attempt_index=attempt_index, request=request, run_id=run_id)

    def stop(self, active):
        self.stopped_attempts.append(active.attempt_index)
        return {
            "archive_id": "a" * 32,
            "display_name": "bag_test",
            "total_size_bytes": 42,
            "audit": {"status": self.audit_status, "errors": [] if self.audit_status == "passed" else ["audit failed"]},
        }


def _normal_case():
    return AcceptanceTestCase(
        "normal", "normal.json", "普通测试",
        TaskParameters("园区", 1, 1, 1, 101), "/tmp/normal.json",
    )


def _wait_for_terminal(manager, run_id):
    deadline = time.monotonic() + 3
    while manager.get(run_id).status in {"queued", "preparing", "running", "recovering", "cancelling"} and time.monotonic() < deadline:
        time.sleep(0.01)
    return manager.get(run_id)


def test_run_manager_records_only_selected_round_and_attaches_audit(monkeypatch, tmp_path):
    monkeypatch.setattr("autodrive_console.run_manager.RobotGateway", FakeGateway)
    recorder = FakeBagRecorder()
    executor = FakeExecutor()
    manager = RunManager(tmp_path / "reports", executor, FakeSettings(), bag_recordings=recorder)

    run = manager.start(_normal_case(), 3, 0, False, bag_recording={"attemptIndex": 2, "topics": ["/odom"]})
    finished = _wait_for_terminal(manager, run.id)

    assert finished.status == "completed"
    assert executor.single_calls == 3
    assert recorder.validated == [({"attemptIndex": 2, "topics": ["/odom"]}, 3)]
    assert recorder.started_attempts == [2]
    assert recorder.stopped_attempts == [2]
    assert finished.attempts[1].bag_recording["audit"]["status"] == "passed"
    assert finished.attempts[0].bag_recording is None


def test_run_manager_never_dispatches_selected_round_when_recording_cannot_start(monkeypatch, tmp_path):
    from autodrive_console.bag_recording import BagRecordingError

    monkeypatch.setattr("autodrive_console.run_manager.RobotGateway", FakeGateway)
    executor = FakeExecutor()
    manager = RunManager(
        tmp_path / "reports", executor, FakeSettings(),
        bag_recordings=FakeBagRecorder(start_error=BagRecordingError("ROS 环境无效")),
    )

    run = manager.start(_normal_case(), 3, 0, False, bag_recording={"attemptIndex": 2, "topics": ["/odom"]})
    finished = _wait_for_terminal(manager, run.id)

    assert finished.status == "failed"
    assert executor.single_calls == 1
    assert finished.attempts[-1].index == 2
    assert "录包未开始" in finished.attempts[-1].message
