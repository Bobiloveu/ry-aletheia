from __future__ import annotations

from types import SimpleNamespace

from autodrive_console.models import MultiDestination, MultiTaskRequest
from autodrive_console.ros_executor import RosTaskExecutor


def test_build_multi_request_preserves_ros_fields_and_order():
    request = MultiTaskRequest(
        community="数创大厦",
        out_eguard=True,
        return_origin=False,
        destinations=(
            MultiDestination("1", "1", "5", "501", 1, "code-501"),
            MultiDestination("1", "1", "3", "301", 2, "code-301"),
        ),
        task_uuid="task-001",
    )
    service_request = SimpleNamespace()

    RosTaskExecutor.build_multi_request(service_request, request, SimpleNamespace)

    assert service_request.community == "数创大厦"
    assert service_request.out_eguard is True
    assert service_request.return_origin is False
    assert service_request.task_uuid == "task-001"
    assert [(item.floor, item.door, item.cargo_type, item.delivery_code) for item in service_request.tasks_seqs] == [
        ("5", "501", 1, "code-501"),
        ("3", "301", 2, "code-301"),
    ]
