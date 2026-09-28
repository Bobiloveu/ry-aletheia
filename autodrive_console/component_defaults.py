"""Read the operator-maintained component execution defaults for task templates."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


COMPONENT_DEFAULTS_PATH = (
    Path(__file__).with_name("task_templates")
    / "indoor_elevator_v1"
    / "components"
    / "component-defaults.json"
)
SPEED_PROFILES = frozenset({"task_point", "single_point", "slow_point", "narrow_point"})


class ComponentDefaultsError(ValueError):
    """The operator-owned task-template defaults cannot be used safely."""


def component_speed_defaults() -> dict[str, dict[str, str | bool]]:
    """Load and validate defaults for every request; changes apply without code edits."""
    try:
        payload = json.loads(COMPONENT_DEFAULTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComponentDefaultsError("组件默认速度配置文件不可读取") from exc
    entries = payload.get("component_speed_defaults") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        raise ComponentDefaultsError("组件默认速度配置格式无效")
    result: dict[str, dict[str, str | bool]] = {}
    for kind, item in entries.items():
        if not isinstance(kind, str) or not isinstance(item, dict):
            raise ComponentDefaultsError("组件默认速度配置格式无效")
        speed = item.get("speed_profile")
        locked = item.get("locked")
        if speed not in SPEED_PROFILES or not isinstance(locked, bool):
            raise ComponentDefaultsError("组件默认速度配置包含无效速度模式")
        result[kind] = {"speed_profile": speed, "locked": locked}
    for kind in ("auto_door", "gate"):
        if kind not in result or result[kind]["locked"] is not True:
            raise ComponentDefaultsError(f"组件默认速度配置必须锁定{kind}")
    return result


def component_speed_profile(kind: str, persisted: object = None) -> str | None:
    """Return the configured speed, overriding stale values for locked components."""
    configured = component_speed_defaults().get(kind)
    if configured is None:
        return str(persisted) if isinstance(persisted, str) and persisted else None
    if configured["locked"]:
        return str(configured["speed_profile"])
    return str(persisted) if isinstance(persisted, str) and persisted else str(configured["speed_profile"])
