"""Bounded, read-only collection of R6B delivery-code status events."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any

from .models import MultiTaskRequest


@dataclass(frozen=True)
class DeliveryEvent:
    delivery_code: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "delivery_code": self.delivery_code,
            "status": self.status,
            "message": self.message,
        }


class MultiTaskStatusCollector:
    """Match status ``701`` events to one frozen R6B request.

    The collector deliberately has no publisher and no cargo-control behavior;
    it only consumes the existing ``/task_status`` edge protocol.
    """

    DELIVERY_STATUS_CODE = "701"
    TASK_STATUS_TOPIC = "/task_status"

    def __init__(self, request: MultiTaskRequest) -> None:
        self.request = request
        self._delivery_codes = tuple(item.delivery_code for item in request.destinations)
        self._events: dict[str, DeliveryEvent] = {}
        self._lock = threading.RLock()

    def observe(self, message: Any) -> bool:
        return self.observe_fields(
            getattr(message, "status_code", ""),
            getattr(message, "task_uuid", ""),
            getattr(message, "message", ""),
        )

    def observe_fields(self, status_code: object, task_uuid: object, message: object) -> bool:
        if str(status_code).strip() != self.DELIVERY_STATUS_CODE:
            return False
        if str(task_uuid).strip() != self.request.task_uuid:
            return False
        delivery_code = str(message).strip()
        if delivery_code not in self._delivery_codes:
            return False
        with self._lock:
            if delivery_code in self._events:
                return False
            self._events[delivery_code] = DeliveryEvent(delivery_code, "passed", "收到配送码事件")
        return True

    def evidence(self) -> list[dict[str, str]]:
        with self._lock:
            return [
                self._events.get(
                    delivery_code,
                    DeliveryEvent(delivery_code, "skipped", "未收到匹配的 701 配送码事件"),
                ).to_dict()
                for delivery_code in self._delivery_codes
            ]

    def attach(self, node, qos_profile=None):
        """Attach to an existing ROS node; importing ROS stays lazy."""
        from master_interfaces.msg import TaskStatus

        return node.create_subscription(TaskStatus, self.TASK_STATUS_TOPIC, self.observe, qos_profile)
