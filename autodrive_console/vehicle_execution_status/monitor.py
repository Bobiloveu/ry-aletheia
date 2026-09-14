"""Persistent, read-only ROS monitor for the vehicle execution display."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import replace
from typing import Callable

from .classifier import classify_execution_state
from .model import ExecutionSnapshot, NavigationState, TaskEvent, snapshot_for, unavailable_snapshot


LOGGER = logging.getLogger("ry_aletheia.vehicle_execution_status")


class VehicleExecutionStatusMonitor:
    """Retain volatile ROS state independently of any test-run lifecycle."""

    TASK_STATUS_TOPIC = "/task_status"
    NAVIGATION_STATUS_TOPIC = "/navigate_todoor_detailed_status"
    NAVIGATION_HEARTBEAT_TOPIC = "/navigate_todoor_status"
    TASK_COMPLETE_CODE = "109"
    SAFE_TASK_UUID = "safe"

    def __init__(
        self,
        *,
        restarting_nodes: Callable[[], bool] | None = None,
        vehicle_control_status: Callable[[], Mapping[str, object]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        freshness_s: float = 4.0,
        task_event_freshness_s: float = 15.0,
    ) -> None:
        self._restarting_nodes = restarting_nodes or (lambda: False)
        # 复用既有控制器对 /control_source_state 与 /is_emergency_stop 的唯一
        # 真实确认；本监控器不创建第二组 ROS 订阅或任何控制通道。
        self._vehicle_control_status = vehicle_control_status or (lambda: {})
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
        self._navigation_heartbeat_status = ""
        self._navigation_heartbeat_received_at: float | None = None
        self._task_event: TaskEvent | None = None
        self._task_event_received_at: float | None = None
        # TaskStatus is an edge-triggered protocol. Completion is meaningful
        # only after this monitor has observed the same task session.
        self._active_task_uuid = ""

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
            if snapshot.status.strip().casefold() in {"completed", "successful", "idle"}:
                # A terminal navigation lifecycle ends the retained one-shot
                # TaskStatus event. Individual XML/action transitions do not:
                # they are normal steps inside the same ROS task.
                self._task_event = None
                self._task_event_received_at = None
                self._active_task_uuid = ""

    def observe_task(self, message, *, received_at: float | None = None) -> None:
        """Store the most recent event; freshness is decided when read."""
        snapshot = TaskEvent(
            status_code=str(getattr(message, "status_code", "")).strip(),
            task_uuid=str(getattr(message, "task_uuid", "")).strip(),
            message=str(getattr(message, "message", "")).strip(),
        )
        with self._lock:
            if snapshot.task_uuid == self.SAFE_TASK_UUID:
                # Node-manager safety notifications share this message type,
                # but are not vehicle task lifecycle events.
                return
            if snapshot.status_code == self.TASK_COMPLETE_CODE:
                if not snapshot.task_uuid or snapshot.task_uuid != self._active_task_uuid:
                    # An old retained 109 must not turn an idle vehicle into a
                    # false completion when the console starts.
                    return
                self._active_task_uuid = ""
            elif snapshot.task_uuid:
                # Any non-terminal event with a task UUID establishes (or
                # resumes after monitor startup) the active task session.
                self._active_task_uuid = snapshot.task_uuid
            self._task_event = snapshot
            self._task_event_received_at = self._clock() if received_at is None else float(received_at)

    def observe_navigation_heartbeat(self, message, *, received_at: float | None = None) -> None:
        """Retain the simple navigation topic solely as a liveness signal.

        NavigateTodoorStatus is emitted at transitions rather than continuously;
        its route context remains useful while this separate 50 Hz status topic
        confirms that navigation is still alive.
        """
        status = _normalize_navigation_status(getattr(message, "data", ""))
        with self._lock:
            self._navigation_heartbeat_status = status
            self._navigation_heartbeat_received_at = self._clock() if received_at is None else float(received_at)

    def status(self) -> dict[str, str]:
        """Return a tiny public snapshot and never surface ROS details to a client."""
        now = self._clock()
        control_snapshot = self._control_override_snapshot()
        if control_snapshot is not None:
            return control_snapshot.to_public_dict()
        try:
            restarting_nodes = bool(self._restarting_nodes())
        except Exception:
            LOGGER.exception("读取运行依赖重启状态失败")
            restarting_nodes = False
        if restarting_nodes:
            return snapshot_for("restarting_nodes").to_public_dict()

        with self._lock:
            runtime_state = self._runtime_state
            navigation = self._navigation
            navigation_received_at = self._navigation_received_at
            heartbeat_status = self._navigation_heartbeat_status
            heartbeat_received_at = self._navigation_heartbeat_received_at
            task_event = self._task_event
            task_event_received_at = self._task_event_received_at

        if runtime_state == "unavailable":
            return unavailable_snapshot().to_public_dict()

        task_is_fresh = task_event is not None and task_event_received_at is not None and now - task_event_received_at <= self.task_event_freshness_s
        heartbeat_is_fresh = heartbeat_received_at is not None and now - heartbeat_received_at <= self.freshness_s
        detailed_status_is_fresh = navigation is not None and navigation_received_at is not None and now - navigation_received_at <= self.freshness_s
        if not heartbeat_is_fresh and not detailed_status_is_fresh:
            if task_is_fresh and task_event.status_code == "109":
                return snapshot_for("completed").to_public_dict()
            if navigation is None or navigation.status.strip().casefold() in {"", "idle"}:
                return snapshot_for("idle").to_public_dict()
            return unavailable_snapshot().to_public_dict()

        if navigation is None:
            navigation = NavigationState(status=heartbeat_status)
        elif heartbeat_is_fresh and heartbeat_status:
            # Current simple status is newer than transition metadata. Keep the
            # detailed waypoint/action context but never retain a stale lifecycle.
            navigation = replace(navigation, status=heartbeat_status)

        snapshot = classify_execution_state(
            navigation,
            # TaskStatus is an edge-triggered phase event, not a heartbeat.
            # While navigation itself is live, retain the latest event until a
            # later code or a terminal navigation lifecycle replaces it.
            task_event if task_event is not None else TaskEvent(),
            restarting_nodes=False,
        )
        return snapshot.to_public_dict()

    def _control_override_snapshot(self) -> ExecutionSnapshot | None:
        """Map only confirmed safety/control facts into the minimal public phases."""
        try:
            control_status = self._vehicle_control_status()
        except Exception:
            LOGGER.exception("读取车辆控制安全状态失败")
            return None
        if not isinstance(control_status, Mapping):
            return None

        emergency_stop = control_status.get("emergency_stop")
        if isinstance(emergency_stop, Mapping) and emergency_stop.get("state") == "triggered":
            return snapshot_for("emergency_stop")

        sync = control_status.get("car_state_sync")
        if (
            control_status.get("actual_source") == "miniapp"
            and isinstance(sync, Mapping)
            and sync.get("control_source") == "confirmed"
        ):
            return snapshot_for("manual_control")
        return None

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
            from std_msgs.msg import String

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
            node.create_subscription(String, self.NAVIGATION_HEARTBEAT_TOPIC, self.observe_navigation_heartbeat, qos)
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
            LOGGER.info(
                "车辆执行状态 ROS 监控已启动：task=%s navigation=%s heartbeat=%s",
                self.TASK_STATUS_TOPIC,
                self.NAVIGATION_STATUS_TOPIC,
                self.NAVIGATION_HEARTBEAT_TOPIC,
            )
        except Exception as exc:
            with self._lock:
                self._runtime_state = "unavailable"
                self._runtime_error = str(exc)
            LOGGER.warning("车辆执行状态 ROS 监控不可用：%s", exc)


def _normalize_navigation_status(value: object) -> str:
    """Normalize the deployed simple-topic vocabulary into detailed-status values."""
    status = str(value or "").strip().casefold()
    aliases = {
        "执行任务点任务": "task_executing",
        "重新执行任务": "task_retrying",
        "任务失败，重新导航": "replanning",
    }
    return aliases.get(status, status)
