"""Immutable inputs and public output for vehicle execution status."""
from __future__ import annotations

from dataclasses import dataclass


PUBLIC_LABELS: dict[str, str] = {
    "emergency_stop": "急停已触发",
    "manual_control": "手动控制中",
    "task": "任务中",
    "calling_elevator": "呼梯中",
    "entering_elevator": "进梯中",
    "riding_elevator": "乘梯中",
    "exiting_elevator": "出梯中",
    "closing_elevator_door": "关电梯门",
    "opening_gate": "开闸机",
    "closing_gate": "关闸机",
    "opening_access_door": "开门禁",
    "closing_access_door": "关门禁",
    "draining_or_unloading": "泄水/卸货中",
    "completed": "任务完成",
    "restarting_nodes": "节点重启中",
    "unavailable": "状态暂不可用",
}


@dataclass(frozen=True)
class NavigationState:
    status: str = ""
    current_task: str = ""
    current_waypoint_id: str = ""
    current_speed_mode: str = ""


@dataclass(frozen=True)
class TaskEvent:
    status_code: str = ""


@dataclass(frozen=True)
class ExecutionSnapshot:
    phase: str
    label: str

    def to_public_dict(self) -> dict[str, str]:
        return {"phase": self.phase, "label": self.label}


def snapshot_for(phase: str) -> ExecutionSnapshot:
    """Return a public snapshot or the intentionally fail-closed default."""
    return ExecutionSnapshot(phase, PUBLIC_LABELS[phase]) if phase in PUBLIC_LABELS else unavailable_snapshot()


def unavailable_snapshot() -> ExecutionSnapshot:
    return ExecutionSnapshot("unavailable", PUBLIC_LABELS["unavailable"])
