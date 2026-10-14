"""Persistent, read-only localization health monitor for the PC console."""
from __future__ import annotations

from collections import deque
import logging
import threading
import time
from collections.abc import Callable
from typing import Any


LOGGER = logging.getLogger("ry_aletheia.localization_status")


_STATE_PUBLIC = {
    0: ("initializing", "定位初始化中", "正在建立定位"),
    1: ("normal", "定位正常", "定位服务正常"),
    2: ("warning", "定位告警", "定位质量需关注"),
    3: ("error", "定位异常", "定位状态需检查"),
    4: ("relocalizing", "重定位中", "正在恢复定位"),
}
_ERROR_DETAILS = {
    0: "无错误",
    100: "NDT 匹配质量低",
    101: "NDT 未收敛",
    200: "LIO 漂移或快速运动检测",
    201: "LIO 结果不可信",
    300: "IMU 异常",
    301: "雷达数据断流",
    400: "定位内部异常",
}


class LocalizationStatusMonitor:
    """Retain bounded localization incidents without changing recovery behaviour."""

    TOPIC = "/localization/status"

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        freshness_s: float = 4.0,
        max_events: int = 256,
    ) -> None:
        self._clock = clock
        self.freshness_s = float(freshness_s)
        self._lock = threading.RLock()
        self._latest: dict[str, object] | None = None
        self._runtime_state = "idle"
        self._runtime_error = ""
        self._closed = False
        self._node = None
        self._executor = None
        self._thread: threading.Thread | None = None
        self._event_sequence = 0
        self._events: deque[dict[str, object]] = deque(maxlen=max(1, int(max_events)))
        # Manual Service initialization may have fault_id=0. Keep its evidence
        # separate from the incident stream used by reports and trajectories.
        self._state_sequence = 0
        self._state_events: deque[dict[str, object]] = deque(maxlen=max(1, int(max_events)))
        # 事件正文可以限长；故障实例 ID 的去重记忆不能随之淘汰，
        # 否则长时间运行后同一 incident 会被错误地二次计数。
        self._seen_fault_ids: set[object] = set()

    def start(self) -> None:
        """Start a passive subscriber; a ROS import failure must not stop the console."""
        self._ensure_started()

    def close(self) -> None:
        """Release this monitor's node without shutting down process-wide rclpy."""
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
                LOGGER.exception("关闭定位状态 ROS executor 失败")
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if node is not None:
            try:
                node.destroy_node()
            except Exception:
                LOGGER.exception("销毁定位状态 ROS node 失败")

    def observe(self, message: object, *, received_at: float | None = None) -> None:
        """Normalize health and retain independent state and fault histories."""
        state_code = _as_int(getattr(message, "state", None))
        error_code = _as_int(getattr(message, "error_code", None))
        fault_id = _fault_id(getattr(message, "fault_id", None))
        received = self._clock() if received_at is None else float(received_at)
        phase, label, default_detail = _STATE_PUBLIC.get(
            state_code,
            ("unavailable", "定位状态暂不可用", "定位状态需检查"),
        )
        detail = (
            default_detail
            if state_code == 1 or error_code in {None, 0}
            else _ERROR_DETAILS.get(error_code, default_detail)
        )
        snapshot = {
            "phase": phase,
            "label": label,
            "detail": detail,
            "updated_at": received,
            "state_code": state_code if state_code in _STATE_PUBLIC else None,
            "error_code": error_code if error_code in _ERROR_DETAILS else None,
            "error_detail": _ERROR_DETAILS.get(error_code, "错误码不可用"),
            "error_retained": state_code == 1 and error_code not in {None, 0},
        }
        with self._lock:
            previous_phase = self._latest.get("phase") if self._latest is not None else None
            # Repeated normal heartbeats must not evict a short initialization.
            # Repeated reset samples still establish fresh post-request evidence.
            if phase != previous_phase or phase in {"initializing", "relocalizing"}:
                self._state_sequence += 1
                self._state_events.append({
                    "sequence": self._state_sequence,
                    "received_at": received,
                    "state": phase,
                })
            self._latest = snapshot
            if state_code == 4 and fault_id is not None and fault_id not in self._seen_fault_ids:
                self._seen_fault_ids.add(fault_id)
                self._event_sequence += 1
                self._events.append(
                    {
                        "sequence": self._event_sequence,
                        "fault_id": fault_id,
                        "received_at": received,
                        "state": "relocalizing",
                    }
                )

    def status(self) -> dict[str, object]:
        """Return a non-ROS public snapshot and never imply normality after staleness."""
        now = self._clock()
        with self._lock:
            latest = dict(self._latest) if self._latest is not None else None
            runtime_state, runtime_error = self._runtime_state, self._runtime_error
        if latest is None:
            return _unavailable_snapshot(
                None, _runtime_unavailable_detail(runtime_state, runtime_error), None,
            )
        updated_at = float(latest["updated_at"])
        age_ms = max(0, round((now - updated_at) * 1000))
        if now - updated_at > self.freshness_s:
            detail = (
                _runtime_unavailable_detail(runtime_state, runtime_error)
                if runtime_state == "unavailable"
                else "等待新的定位状态"
            )
            return _unavailable_snapshot(updated_at, detail, age_ms)
        latest["age_ms"] = age_ms
        return latest

    def cursor(self) -> int:
        with self._lock:
            return self._event_sequence

    def state_cursor(self) -> int:
        """Mark the current state stream independently of fault incident IDs."""
        with self._lock:
            return self._state_sequence

    def state_events_since(self, cursor: int) -> tuple[int, list[dict[str, object]]]:
        """Return bounded state evidence strictly newer than a manual request."""
        lower_bound = int(cursor)
        with self._lock:
            return self._state_sequence, [
                dict(event) for event in self._state_events
                if int(event["sequence"]) > lower_bound
            ]

    def events_since(self, cursor: int) -> tuple[int, list[dict[str, object]]]:
        """Return bounded reset incidents strictly newer than a session cursor."""
        try:
            lower_bound = int(cursor)
        except (TypeError, ValueError):
            lower_bound = 0
        with self._lock:
            return self._event_sequence, [dict(event) for event in self._events if int(event["sequence"]) > lower_bound]

    def _ensure_started(self) -> None:
        with self._lock:
            if self._closed or self._runtime_state in {"ready", "starting", "unavailable"}:
                return
            self._runtime_state = "starting"
            self._runtime_error = ""
        try:
            import rclpy
            from master_interfaces.msg import LocalizationStatus
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

            if not rclpy.ok():
                rclpy.init()
            node = rclpy.create_node("ry_aletheia_localization_status")
            qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE)
            node.create_subscription(LocalizationStatus, self.TOPIC, self.observe, qos)
            executor = SingleThreadedExecutor()
            executor.add_node(node)
            thread = threading.Thread(target=executor.spin, daemon=True, name="localization-status")
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
            LOGGER.info("定位状态 ROS 监控已启动：topic=%s", self.TOPIC)
        except Exception as exc:
            with self._lock:
                self._runtime_state = "unavailable"
                self._runtime_error = str(exc)
            LOGGER.warning("定位状态 ROS 监控不可用：%s", exc)


def _as_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fault_id(value: object) -> object | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _unavailable_snapshot(
    updated_at: float | None, detail: str, age_ms: int | None,
) -> dict[str, object]:
    return {
        "phase": "unavailable",
        "label": "定位状态暂不可用",
        "detail": detail,
        "updated_at": updated_at,
        "state_code": None,
        "error_code": None,
        "error_detail": "错误码不可用",
        "error_retained": False,
        "age_ms": age_ms,
    }


def _runtime_unavailable_detail(runtime_state: str, runtime_error: str) -> str:
    """Convert optional ROS capability failures into safe operator-facing text."""
    if runtime_state != "unavailable":
        return "等待定位状态"
    if "LocalizationStatus" in runtime_error or "master_interfaces.msg" in runtime_error:
        return "该车不支持实时定位状态"
    return "定位状态订阅不可用"
