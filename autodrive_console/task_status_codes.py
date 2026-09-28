"""Validated task-status codes for the approved indoor elevator profile."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


STATUS_CODE_PATH = (
    Path(__file__).with_name("task_templates")
    / "indoor_elevator_v1"
    / "task-status-codes.json"
)


class TaskStatusCodeError(ValueError):
    """The profile-owned task-status registry is not safe to consume."""


@dataclass(frozen=True)
class TaskStatusCodeSnapshot:
    """One validated registry revision, including the exact bytes that produced it."""

    codes: Mapping[str, int]
    raw_bytes: bytes

    def xml_values(self) -> dict[str, str]:
        return {
            f"STATUS_{name.upper()}": str(code)
            for name, code in self.codes.items()
        }


_CODE_NAMES = frozenset({
    "task_start",
    "outdoor_tasking",
    "indoor_tasking",
    "task_return_waiting",
    "task_complete",
    "elevator_waiting",
    "elevator_in",
    "elevator_taking",
    "elevator_outing",
    "elevator_outed",
    "elevator_arrived",
    "door_waiting",
    "gate_in",
    "gate_out",
    "auto_door_in",
    "auto_door_out",
    "door_waiting_open",
    "door_waiting_close",
    "clamp_water_waiting",
    "clamp_water",
    "place_water_waiting",
    "place_water",
    "photo_upload",
    "building_in",
    "building_out",
    "multi_task_start",
    "multi_task_arrived",
})
_ALLOWED_DUPLICATE_NAMES = frozenset({"door_waiting_open", "door_waiting_close"})
_ALLOWED_DUPLICATE_CODE = 305
_PHASE_BY_NAME = {
    "task_complete": "completed",
    "elevator_waiting": "calling_elevator",
    "elevator_in": "entering_elevator",
    "elevator_taking": "riding_elevator",
    "elevator_outing": "exiting_elevator",
    "elevator_arrived": "riding_elevator",
    "gate_in": "opening_gate",
    "gate_out": "closing_gate",
    "auto_door_in": "opening_access_door",
    "auto_door_out": "closing_access_door",
    "clamp_water_waiting": "draining_or_unloading",
    "clamp_water": "draining_or_unloading",
    "place_water_waiting": "draining_or_unloading",
    "place_water": "draining_or_unloading",
}


def task_status_codes() -> dict[str, int]:
    """Read and validate the registry on every request."""
    return dict(task_status_code_snapshot().codes)


def task_status_code_snapshot() -> TaskStatusCodeSnapshot:
    """Read raw registry bytes once and validate precisely that revision."""
    try:
        raw_bytes = STATUS_CODE_PATH.read_bytes()
    except OSError as exc:
        raise TaskStatusCodeError("任务状态码配置无法读取") from exc
    try:
        document = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskStatusCodeError("任务状态码配置无法读取") from exc
    return TaskStatusCodeSnapshot(
        codes=MappingProxyType(_validate_codes(document)),
        raw_bytes=raw_bytes,
    )


def task_status_code(name: str) -> str:
    """Return one named status code in the wire format used by task status."""
    try:
        return str(task_status_codes()[name])
    except KeyError as exc:
        raise TaskStatusCodeError(f"未知任务状态码名称：{name}") from exc


def task_status_xml_values() -> dict[str, str]:
    """Return template-token replacements for the current registry values."""
    return task_status_code_snapshot().xml_values()


def task_status_phase_by_code() -> dict[str, str]:
    """Map current codes onto the existing public execution-phase vocabulary."""
    return {
        str(code): _PHASE_BY_NAME.get(name, "task")
        for name, code in task_status_code_snapshot().codes.items()
    }


def _validate_codes(document: object) -> dict[str, int]:
    if not isinstance(document, dict) or set(document) != {"schema", "codes"}:
        raise TaskStatusCodeError("任务状态码配置格式无效")
    if document.get("schema") != 1:
        raise TaskStatusCodeError("任务状态码配置版本不受支持")
    codes = document.get("codes")
    if not isinstance(codes, dict) or set(codes) != _CODE_NAMES:
        raise TaskStatusCodeError("任务状态码配置键不完整")
    if any(type(code) is not int or not 100 <= code <= 999 for code in codes.values()):
        raise TaskStatusCodeError("任务状态码必须为三位整数")

    names_by_code: dict[int, set[str]] = defaultdict(set)
    for name, code in codes.items():
        names_by_code[code].add(name)
    for code, names in names_by_code.items():
        if names != _ALLOWED_DUPLICATE_NAMES or code != _ALLOWED_DUPLICATE_CODE:
            if len(names) > 1:
                raise TaskStatusCodeError("任务状态码存在未批准的重复值")
    return dict(codes)
