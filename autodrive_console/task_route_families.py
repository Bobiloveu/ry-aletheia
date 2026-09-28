"""Derive deployable task families from saved map and component facts.

This module is deliberately independent from HTTP, storage and runtime paths.
It turns the immutable deployment flow plus map instances into deterministic
per-building/unit route families and delivery branches.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from .location_manifest import LocationManifestError, physical_floor_index


class TaskRouteFamilyError(ValueError):
    """A SiteProject cannot be translated into safe task families."""


@dataclass(frozen=True)
class StageMap:
    stage: str
    map_asset_id: str


@dataclass(frozen=True)
class TargetBranch:
    component_id: str
    map_asset_id: str
    full_room_number: str
    physical_floor: int
    button_floor: int
    door: str
    target_role: str
    floor_stem: str


@dataclass(frozen=True)
class TaskRouteFamily:
    building: str
    unit: str
    stages: tuple[StageMap, ...]
    shared_bindings: dict[str, StageMap]
    targets: tuple[TargetBranch, ...]
    required_outputs: frozenset[str]


_FLOW_TYPES = frozenset({"ferry", "outdoor", "lobby", "target_floor"})
_TARGET_ROLES = frozenset({"typical_floor", "floor_override"})
_GLOBAL_ROLES = frozenset({"ferry"})
_ROOM = re.compile(r"[0-9]{1,16}\Z")


def derive_task_route_families(project: Mapping[str, Any]) -> tuple[TaskRouteFamily, ...]:
    """Return deterministic delivery families without accepting client ordering."""
    if not isinstance(project, Mapping):
        raise TaskRouteFamilyError("部署项目格式无效")
    flow = _flow(project)
    instances = _instances(project)
    components = _components(project)
    physical_elevators = _physical_elevators(project)
    globals_by_role = _global_stages(flow, instances)
    target_instances = [item for item in instances if item["role"] in _TARGET_ROLES]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for instance in target_instances:
        grouped.setdefault((instance["building"], instance["unit"]), []).append(instance)
    if not grouped:
        raise TaskRouteFamilyError("尚未标记用户楼层地图")

    families: list[TaskRouteFamily] = []
    stems: set[str] = set()
    for building, unit in sorted(grouped):
        unit_instances = [
            item for item in instances
            if item["building"] == building and item["unit"] == unit
        ]
        lobby = _one_instance(unit_instances, "lobby", f"{building} 栋 {unit} 单元电梯大厅")
        targets: list[TargetBranch] = []
        for instance in grouped[(building, unit)]:
            for component in components:
                if component["map_asset_id"] != instance["map_asset_id"] or component["kind"] != "target":
                    continue
                branch = _target_branch(component, instance, building, unit, components, physical_elevators)
                if branch.floor_stem in stems:
                    raise TaskRouteFamilyError("输出文件名冲突")
                stems.add(branch.floor_stem)
                targets.append(branch)
        if not targets:
            raise TaskRouteFamilyError(f"{building} 栋 {unit} 单元用户楼层尚未标记目标点")
        targets.sort(key=lambda item: (item.physical_floor, item.door, item.component_id))
        stage_maps: list[StageMap] = []
        shared: dict[str, StageMap] = {}
        for kind in flow:
            if kind in _GLOBAL_ROLES:
                stage = globals_by_role[kind]
                stage_maps.append(stage)
                shared[kind] = stage
            elif kind in {"outdoor", "lobby"}:
                label = "户外" if kind == "outdoor" else "电梯大厅"
                instance = _one_instance(unit_instances, kind, f"{building} 栋 {unit} 单元{label}")
                stage = StageMap(kind, instance["map_asset_id"])
                stage_maps.append(stage)
                shared[kind] = stage
            else:
                # Target maps are branch-specific; retain the stage fact but
                # never select a browser-controlled map order.
                stage_maps.append(StageMap(kind, ""))
        required = frozenset(
            {"floor", "indoor"}
            | ({"ferry"} if "ferry" in flow else set())
            | ({"outdoor"} if "outdoor" in flow else set())
        )
        families.append(TaskRouteFamily(building, unit, tuple(stage_maps), shared, tuple(targets), required))
    return tuple(families)


def _flow(project: Mapping[str, Any]) -> tuple[str, ...]:
    raw = project.get("deployment_flow")
    if not isinstance(raw, list) or not raw:
        raise TaskRouteFamilyError("请先配置部署流程")
    values: list[str] = []
    for item in raw:
        kind = str(item.get("type") or "") if isinstance(item, Mapping) else ""
        if kind not in _FLOW_TYPES:
            raise TaskRouteFamilyError("部署流程阶段无效")
        values.append(kind)
    if values.count("lobby") != 1 or values.count("target_floor") != 1 or values[-1] != "target_floor":
        raise TaskRouteFamilyError("部署流程必须以唯一用户楼层结束")
    return tuple(values)


def _instances(project: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = project.get("map_instances")
    if not isinstance(raw, list):
        raise TaskRouteFamilyError("地图实例无效")
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "")
        map_asset_id = str(item.get("map_asset_id") or "")
        if role not in _GLOBAL_ROLES | {"outdoor", "lobby"} | _TARGET_ROLES or not map_asset_id:
            continue
        expected_scope = "global" if role in _GLOBAL_ROLES else "unit"
        actual_scope = item.get("scope")
        if actual_scope is not None and actual_scope != expected_scope:
            raise TaskRouteFamilyError("地图实例归属与角色不一致")
        if role in _GLOBAL_ROLES:
            if any(item.get(key) not in (None, "") for key in ("building", "unit", "floor")):
                raise TaskRouteFamilyError("全局地图实例不能填写楼栋、单元或楼层")
            result.append({"role": role, "map_asset_id": map_asset_id, "building": "", "unit": "", "floor": None})
            continue
        building, unit = str(item.get("building") or "").strip(), str(item.get("unit") or "").strip()
        if not building or not unit:
            raise TaskRouteFamilyError("地图实例缺少楼栋或单元")
        floor = item.get("floor")
        if role in _TARGET_ROLES and floor not in (None, ""):
            try:
                floor = int(floor)
            except (TypeError, ValueError) as exc:
                raise TaskRouteFamilyError("用户楼层地图楼层无效") from exc
        result.append({"role": role, "map_asset_id": map_asset_id, "building": building, "unit": unit, "floor": floor})
    return result


def _components(project: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = project.get("components")
    if not isinstance(raw, list):
        raise TaskRouteFamilyError("组件数据无效")
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _physical_elevators(project: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = project.get("physical_elevators")
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise TaskRouteFamilyError("物理电梯数据无效")
    result: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        identifier = str(item.get("id") or "").strip()
        if identifier:
            result[identifier] = item
    return result


def _global_stages(flow: tuple[str, ...], instances: list[dict[str, Any]]) -> dict[str, StageMap]:
    result: dict[str, StageMap] = {}
    for kind in _GLOBAL_ROLES:
        if kind not in flow:
            continue
        matches = [item for item in instances if item["role"] == kind]
        if len(matches) != 1:
            raise TaskRouteFamilyError(f"流程中的{kind}必须有且只有一张全局地图")
        result[kind] = StageMap(kind, matches[0]["map_asset_id"])
    return result


def _one_instance(instances: list[dict[str, Any]], role: str, label: str) -> dict[str, Any]:
    matches = [item for item in instances if item["role"] == role]
    if len(matches) != 1:
        raise TaskRouteFamilyError(f"{label}必须有且只有一张地图")
    return matches[0]


def _target_branch(
    component: dict[str, Any], instance: dict[str, Any], building: str, unit: str,
    components: list[dict[str, Any]], physical_elevators: Mapping[str, Mapping[str, Any]],
) -> TargetBranch:
    attrs = component.get("attributes") if isinstance(component.get("attributes"), Mapping) else {}
    full_room = str(attrs.get("door") or "").strip()
    if not _ROOM.fullmatch(full_room):
        raise TaskRouteFamilyError("目标房号无效")
    physical_floor, button_floor = _target_floor(instance, components, physical_elevators)
    prefix = str(button_floor)
    if not full_room.startswith(prefix) or len(full_room) != len(prefix) + 2:
        raise TaskRouteFamilyError("目标房号与电梯按钮层不一致")
    suffix = full_room[len(prefix):]
    if not suffix.isdigit():
        raise TaskRouteFamilyError("目标房号无效")
    door = suffix.zfill(2)
    role = instance["role"]
    stem = f"{building}_{unit}_n_n{door}" if role == "typical_floor" else f"{building}_{unit}_{button_floor}_{full_room}"
    component_id = str(component.get("id") or "")
    if not component_id:
        raise TaskRouteFamilyError("目标组件标识无效")
    return TargetBranch(component_id, instance["map_asset_id"], full_room, physical_floor, button_floor, door, role, stem)


def _target_floor(
    instance: Mapping[str, Any], components: list[dict[str, Any]], physical_elevators: Mapping[str, Mapping[str, Any]],
) -> tuple[int, int]:
    """Return runtime physical floor and user-facing panel label for one map.

    New projects deliberately leave ``map_instances[].floor`` empty because
    the map stage happens before elevator annotation.  The target landing is
    the authoritative source once it exists.  The legacy map floor remains a
    read-only fallback for pre-migration project snapshots without shared
    physical-elevator metadata.
    """
    map_asset_id = str(instance.get("map_asset_id") or "")
    landings = [
        item for item in components
        if item.get("map_asset_id") == map_asset_id and item.get("kind") == "elevator"
    ]
    if physical_elevators:
        if len(landings) != 1:
            raise TaskRouteFamilyError("用户楼层地图必须标记唯一电梯落点以推导物理楼层")
        attributes = landings[0].get("attributes")
        attributes = attributes if isinstance(attributes, Mapping) else {}
        identifier = str(attributes.get("physical_elevator_id") or "").strip()
        elevator = physical_elevators.get(identifier)
        if elevator is None:
            raise TaskRouteFamilyError("用户楼层电梯落点未关联有效物理电梯")
        try:
            button = int(attributes.get("button_floor"))
            physical = physical_floor_index(
                int(elevator.get("min_floor")), int(elevator.get("max_floor")), button,
                elevator.get("unavailable_button_floors", ()),
            )
        except (TypeError, ValueError, LocationManifestError) as exc:
            raise TaskRouteFamilyError("用户楼层电梯落点缺少有效按钮层") from exc
        return physical, button
    try:
        legacy_floor = int(instance.get("floor"))
    except (TypeError, ValueError) as exc:
        raise TaskRouteFamilyError("用户楼层地图尚未完成电梯组件标记") from exc
    return legacy_floor, legacy_floor
