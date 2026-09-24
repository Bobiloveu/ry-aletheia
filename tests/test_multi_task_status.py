from __future__ import annotations

from types import SimpleNamespace

from autodrive_console.models import MultiDestination, MultiTaskRequest
from autodrive_console.multi_task_status import MultiTaskStatusCollector


def request() -> MultiTaskRequest:
    return MultiTaskRequest(
        community="数创大厦",
        out_eguard=False,
        return_origin=True,
        destinations=(
            MultiDestination("5", "1", "5", "501", 1, "code-501"),
            MultiDestination("5", "1", "3", "301", 2, "code-301"),
        ),
        task_uuid="task-001",
    )


def test_collector_accepts_only_matching_uuid_delivery_events():
    collector = MultiTaskStatusCollector(request())

    assert collector.observe(SimpleNamespace(status_code="701", task_uuid="", message="code-501")) is False
    assert collector.observe(SimpleNamespace(status_code="701", task_uuid="old", message="code-501")) is False
    assert collector.observe(SimpleNamespace(status_code="109", task_uuid="task-001", message="code-501")) is False
    assert collector.observe(SimpleNamespace(status_code="701", task_uuid="task-001", message="unknown")) is False
    assert collector.observe(SimpleNamespace(status_code="701", task_uuid="task-001", message="code-501")) is True

    evidence = collector.evidence()
    assert evidence[0]["delivery_code"] == "code-501"
    assert evidence[0]["status"] == "passed"
    assert evidence[1]["delivery_code"] == "code-301"
    assert evidence[1]["status"] == "skipped"


def test_collector_does_not_accept_delivery_code_from_another_chain():
    collector = MultiTaskStatusCollector(request())

    assert collector.observe_fields("701", "task-001", "code-501") is True
    assert collector.observe_fields("701", "task-001", "code-501") is False
    assert collector.observe_fields("701", "task-001", "code-301") is True
    assert all(item["status"] == "passed" for item in collector.evidence())
