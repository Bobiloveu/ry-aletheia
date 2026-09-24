"""Shared, ordered task-transition chains for experimental deployment artifacts.

The task JSON and localization manifest are two consumers of the same robot
path.  This module is deliberately independent from the compiler and manifest
so neither can silently invent a different return hand-off.
"""
from __future__ import annotations

from math import isfinite, pi
from typing import Any, Iterable


class TaskPathError(ValueError):
    """A manually marked task transition is malformed."""


TASK_TRANSITION_SPEED_MODES = frozenset({
    "task_point", "single_point", "slow_point", "narrow_point",
})


def task_segment_transitions(
    project: dict[str, Any], map_asset_id: str,
) -> list[dict[str, float | str]]:
    """Return one map segment's manual transitions in persisted outbound order."""
    values = project.get("waypoints")
    if not isinstance(values, list):
        return []
    transitions: list[dict[str, float | str]] = []
    for waypoint in values:
        if not isinstance(waypoint, dict) or waypoint.get("kind") != "transition":
            continue
        if (
            waypoint.get("map_asset_id") != map_asset_id
            or waypoint.get("generated_by")
            or waypoint.get("exclude_task_export")
        ):
            continue
        speed_mode = str(waypoint.get("speed_mode") or "single_point")
        if speed_mode not in TASK_TRANSITION_SPEED_MODES:
            raise TaskPathError(
                "过渡点速度模式仅支持 task_point、single_point、slow_point 或 narrow_point"
            )
        transitions.append({
            "x": _number(waypoint.get("x"), "任务过渡点 x 坐标"),
            "y": _number(waypoint.get("y"), "任务过渡点 y 坐标"),
            "yaw": _number(waypoint.get("yaw", 0.0), "任务过渡点朝向"),
            "speed_mode": speed_mode,
        })
    return transitions


def return_task_transition_points(
    outbound: Iterable[dict[str, float | str]],
) -> list[dict[str, float | str]]:
    """Reverse a saved segment and turn each heading toward the return route."""
    result: list[dict[str, float | str]] = []
    for point in reversed(list(outbound)):
        copied = dict(point)
        copied["yaw"] = return_yaw(_number(point.get("yaw"), "任务过渡点朝向"))
        result.append(copied)
    return result


def return_yaw(yaw: float) -> float:
    """Turn an outbound direction by 180 degrees in the canonical [-π, π) span."""
    return (yaw + 2 * pi) % (2 * pi) - pi


def task_transition_pose(point: dict[str, float | str]) -> dict[str, float]:
    """Drop task-only fields when the chain becomes a localization pose."""
    return {
        "x": _number(point.get("x"), "任务过渡点 x 坐标"),
        "y": _number(point.get("y"), "任务过渡点 y 坐标"),
        "z": 0.0,
        "yaw": _number(point.get("yaw"), "任务过渡点朝向"),
    }


def _number(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TaskPathError(f"{label}无效") from exc
    if not isfinite(number) or abs(number) >= 1e7:
        raise TaskPathError(f"{label}无效")
    return number
