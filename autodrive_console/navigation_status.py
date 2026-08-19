"""导航详细状态的低成本解析，专门为测试期间的预期电梯等待服务。"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ElevatorWaitState:
    active: bool = False
    timed_out: bool = False
    elapsed_s: float = 0.0
    status: str = ""
    waypoint_id: str = ""
    task: str = ""
    speed_mode: str = ""

    def to_dict(self) -> dict:
        return {
            "active": self.active, "timed_out": self.timed_out, "elapsed_s": round(self.elapsed_s, 1),
            "status": self.status, "waypoint_id": self.waypoint_id, "task": self.task, "speed_mode": self.speed_mode,
        }


class NavigationStatusMonitor:
    """仅缓存最新 NavigateTodoorStatus；不参与任务通过/失败判定。"""

    NON_ELEVATOR_GRACE_S = 5.0
    TERMINAL = {"idle", "completed", "failed", "successful"}
    ELEVATOR_SPEED_MODES = {"elevator_in"}
    ELEVATOR_KEYWORDS = ("elevator", "eletest", "lift", "电梯")

    def __init__(self, timeout_s: float = 180.0) -> None:
        self.timeout_s = timeout_s
        self._entered_at: float | None = None
        self._last_seen_at: float | None = None
        self._non_elevator_at: float | None = None
        self._state = ElevatorWaitState()

    def observe(self, message, now: float | None = None) -> ElevatorWaitState:
        now = time.monotonic() if now is None else now
        status = str(getattr(message, "status", "")).strip().lower()
        speed_mode = str(getattr(message, "current_speed_mode", "")).strip().lower()
        waypoint_id = str(getattr(message, "current_waypoint_id", "")).strip()
        task = str(getattr(message, "current_task", "")).strip()
        self._last_seen_at = now
        if status in self.TERMINAL:
            self._clear()
            return self.snapshot(now)
        text = f"{speed_mode} {waypoint_id} {task}".lower()
        is_elevator = speed_mode in self.ELEVATOR_SPEED_MODES or any(word in text for word in self.ELEVATOR_KEYWORDS)
        if is_elevator:
            self._entered_at = now if self._entered_at is None else self._entered_at
            self._non_elevator_at = None
        elif self._entered_at is not None:
            self._non_elevator_at = now if self._non_elevator_at is None else self._non_elevator_at
        self._state = ElevatorWaitState(False, False, 0.0, status, waypoint_id, task, speed_mode)
        return self.snapshot(now)

    def snapshot(self, now: float | None = None) -> ElevatorWaitState:
        now = time.monotonic() if now is None else now
        if self._entered_at is None:
            return self._state
        if self._non_elevator_at is not None and now - self._non_elevator_at >= self.NON_ELEVATOR_GRACE_S:
            self._clear()
            return self._state
        elapsed = max(0.0, now - self._entered_at)
        return ElevatorWaitState(True, elapsed >= self.timeout_s, elapsed, self._state.status, self._state.waypoint_id, self._state.task, self._state.speed_mode)

    def _clear(self) -> None:
        self._entered_at = self._non_elevator_at = None
        self._state = ElevatorWaitState()
