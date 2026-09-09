"""Persistent, read-only ROS monitor for the vehicle execution display."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .classifier import classify_execution_state
from .model import NavigationState, TaskEvent, snapshot_for, unavailable_snapshot


LOGGER = logging.getLogger("ry_aletheia.vehicle_execution_status")


class VehicleExecutionStatusMonitor:
    """Retain volatile ROS state independently of any test-run lifecycle."""

    TASK_STATUS_TOPIC = "/task_status"
    NAVIGATION_STATUS_TOPIC = "/navigate_todoor_detailed_status"

    def __init__(
        self,
        *,
        restarting_nodes: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        freshness_s: float = 4.0,
        task_event_freshness_s: float = 15.0,
    ) -> None:
        self._restarting_nodes = restarting_nodes or (lambda: False)
        self._clock = clock
        self.freshness_s = float(freshness_s)
        self.task_event_freshness_s = float(task_event_freshness_s)
        self._lock = threading.RLock()
        self._runtime_state = "idle"
        self._runtime_error = ""
        self._closed = False
        self._node = None
        self._executor = None
        self._thread: threading.Thread | None = None
        self._navigation: NavigationState | None = None
        self._navigation_received_at: float | None = None
        self._task_event: TaskEvent | None = None
        self._task_event_received_at: float | None = None

    def start(self) -> None:
        """Start the persistent monitor without making console startup fragile."""
        self._ensure_started()

    def close(self) -> None:
        """Release only this monitor's executor and node; never shut down global rclpy."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            executor, thread, node = self._executor, self._thread, self._node
            self._executor = self._thread = self._node = None
        if executor is not None:
            try:
                executor.shutdown()
            except Exception:
                LOGGER.exception("关闭车辆执行状态 ROS executor 失败")
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if node is not None:
            try:
                node.destroy_node()
            except Exception:
                LOGGER.exception("销毁车辆执行状态 ROS node 失败")

    def observe_navigation(self, message, *, received_at: float | None = None) -> None:
        """Store only the normalized fields consumed by the pure classifier."""
        snapshot = NavigationState(
            status=str(getattr(message, "status", "")).strip(),
            current_task=str(getattr(message, "current_task", "")).strip(),
            current_waypoint_id=str(getattr(message, "current_waypoint_id", "")).strip(),
            current_speed_mode=str(getattr(message, "current_speed_mode", "")).strip(),
        )
        with self._lock:
            self._navigation = snapshot
            self._navigation_received_at = self._clock() if received_at is None else float(received_at)

    def observe_task(self, message, *, received_at: float | None = None) -> None:
        """Store the most recent event; freshness is decided when read."""
        snapshot = TaskEvent(status_code=str(getattr(message, "status_code", "")).strip())
        with self._lock:
            self._task_event = snapshot
            self._task_event_received_at = self._clock() if received_at is None else float(received_at)

    def status(self) -> dict[str, str]:
        """Return a tiny public snapshot and never surface ROS details to a client."""
        now = self._clock()
        try:
            restarting_nodes = bool(self._restarting_nodes())
        except Exception:
            LOGGER.exception("读取运行依赖重启状态失败")
            restarting_nodes = False
        if restarting_nodes:
            return snapshot_for("restarting_nodes").to_public_dict()

        with self._lock:
            navigation = self._navigation
            navigation_received_at = self._navigation_received_at
            task_event = self._task_event
            task_event_received_at = self._task_event_received_at

        task_is_fresh = task_event is not None and task_event_received_at is not None and now - task_event_received_at <= self.task_event_freshness_s
        navigation_is_fresh = navigation is not None and navigation_received_at is not None and now - navigation_received_at <= self.freshness_s
        if not navigation_is_fresh:
            if task_is_fresh and task_event.status_code == "109":
                return snapshot_for("completed").to_public_dict()
            return unavailable_snapshot().to_public_dict()

        snapshot = classify_execution_state(
            navigation,
            task_event if task_is_fresh and task_event is not None else TaskEvent(),
            restarting_nodes=False,
        )
        return snapshot.to_public_dict()

    def _ensure_started(self) -> None:
        with self._lock:
            if self._closed or self._runtime_state in {"ready", "starting", "unavailable"}:
                return
            self._runtime_state = "starting"
            self._runtime_error = ""
        try:
            import rclpy
            from master_interfaces.msg import NavigateTodoorStatus, TaskStatus
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

            if not rclpy.ok():
                rclpy.init()
            node = rclpy.create_node("ry_aletheia_vehicle_execution_status")
            qos = QoSProfile(
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.VOLATILE,
            )
            node.create_subscription(TaskStatus, self.TASK_STATUS_TOPIC, self.observe_task, qos)
            node.create_subscription(NavigateTodoorStatus, self.NAVIGATION_STATUS_TOPIC, self.observe_navigation, qos)
            executor = SingleThreadedExecutor()
            executor.add_node(node)
            thread = threading.Thread(target=executor.spin, daemon=True, name="vehicle-execution-status")
            with self._lock:
                if self._closed:
                    executor.shutdown()
                    node.destroy_node()
                    return
                self._node = node
                self._executor = executor
                self._thread = thread
                self._runtime_state = "ready"
            thread.start()
            LOGGER.info("车辆执行状态 ROS 监控已启动：task=%s navigation=%s", self.TASK_STATUS_TOPIC, self.NAVIGATION_STATUS_TOPIC)
        except Exception as exc:
            with self._lock:
                self._runtime_state = "unavailable"
                self._runtime_error = str(exc)
            LOGGER.warning("车辆执行状态 ROS 监控不可用：%s", exc)
