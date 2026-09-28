"""Derive deployment routes exclusively from the saved scene and map marks.

The route object remains a persisted audit record, but no browser-supplied
ordering is accepted here.  A deterministic map path is the sole source for
the execution-node sequence.
"""
from __future__ import annotations

from collections import OrderedDict
from hashlib import blake2b
from heapq import heappop, heappush
from math import cos, hypot, isfinite, sin
from pathlib import Path
from threading import RLock
from typing import Any


Grid = tuple[int, int, set[tuple[int, int]]]
WallSegment = tuple[tuple[float, float], tuple[float, float], float, float, float, float]
_GRID_CACHE_LIMIT = 8
_GRID_CACHE_LOCK = RLock()
_GRID_CACHE: OrderedDict[tuple[str, bytes], Grid | None] = OrderedDict()


class AutomaticRouteError(ValueError):
    """The saved scene/map facts do not define one safe automatic route."""


def derive_localization_routes(project: dict[str, Any]) -> list[dict[str, Any]]:
    """Build all identity routes in scene-flow order from immutable map facts.

    This function deliberately does not inspect an existing ``localization_routes``
    value: historical manual order must never affect a newly derived deployment.
    """
    if not isinstance(project, dict):
        raise AutomaticRouteError("部署项目格式无效")
    assets = _index(project.get("map_assets"), "地图")
    bindings = _bindings(project, assets)
    topology_sequences = _unit_stage_sequences(project, assets)
    if topology_sequences:
        return _derive_unit_topology_routes(project, assets, bindings, topology_sequences)
    stage_maps = _stage_maps(project, assets)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for binding in bindings:
        grouped.setdefault((binding["building"], binding["unit"]), []).append(binding)
    routes: list[dict[str, Any]] = []
    for identity, identity_bindings in sorted(grouped.items()):
        ordered = _ordered_bindings(identity_bindings, stage_maps)
        components = _components(project)
        target_map_id = str(ordered[-1]["map_asset_id"])
        targets = [
            item for item in components
            if item.get("map_asset_id") == target_map_id and item.get("kind") == "target"
        ]
        if not targets:
            raise AutomaticRouteError(f"地图“{target_map_id}”的末图目标必须唯一；请回到地图补标记")
        for target in sorted(targets, key=lambda item: str(item.get("id") or "")):
            routes.append(_derive_route(project, assets, identity, ordered, target))
    if not routes:
        raise AutomaticRouteError("尚未完成地图定位绑定；请先按场景流程导入并绑定地图")
    return routes


def _unit_stage_sequences(
    project: dict[str, Any], assets: dict[str, dict[str, Any]],
) -> list[tuple[tuple[str, str], list[tuple[str, str]]]]:
    """Read the unit topology without collapsing it through legacy assignments.

    A scene flow describes *types*, while map instances describe which concrete
    lobby and floor map belongs to each building/unit.  The old single-value
    ``map_stage_assignments`` is retained for the import guide only and must
    not make a second building overwrite the first one.

    Each stage has a fixed semantic hand-off.  The operator marks those
    anchors on the relevant map; they never supplies a route order:

    * ferry/outdoor exit through one existing ``transition`` marker (the
      imported legacy ``map_transition`` spelling remains readable);
    * an outdoor map is entered through its ``start`` marker;
    * a lobby reached from outdoors is entered through one
      ``building_entrance`` marker and exits through its elevator; and
    * a user floor is entered at its elevator and ends at its delivery target.

    This lets a public ferry map be reused for every building/unit while an
    outdoor map remains a concrete per-unit stage.
    """
    flow = project.get("deployment_flow")
    instances = project.get("map_instances")
    if not isinstance(flow, list) or not isinstance(instances, list):
        return []
    types = [str(item.get("type") or "") for item in flow if isinstance(item, dict)]
    if not types or types[-2:] != ["lobby", "target_floor"] or any(
        item not in {"ferry", "outdoor", "lobby", "target_floor"}
        for item in types
    ):
        return []

    ferries: list[str] = []
    outdoors: dict[tuple[str, str], str] = {}
    lobbies: dict[tuple[str, str], str] = {}
    floors: dict[tuple[str, str], list[str]] = {}
    for instance in instances:
        if not isinstance(instance, dict):
            continue
        role = str(instance.get("role") or "")
        map_id = str(instance.get("map_asset_id") or "")
        building = str(instance.get("building") or "").strip()
        unit = str(instance.get("unit") or "").strip()
        if role == "ferry":
            if map_id not in assets or building or unit:
                raise AutomaticRouteError("摆渡层地图实例无效；请回到地图阶段修正")
            ferries.append(map_id)
            continue
        if role not in {"outdoor", "lobby", "typical_floor", "floor_override"}:
            continue
        if map_id not in assets or not building or not unit:
            raise AutomaticRouteError("地图实例缺少有效楼栋、单元或地图；请回到地图阶段修正")
        identity = (building, unit)
        if role == "outdoor":
            if identity in outdoors:
                raise AutomaticRouteError(f"{building} 栋 {unit} 单元必须且只能有一张户外地图")
            outdoors[identity] = map_id
        elif role == "lobby":
            if identity in lobbies:
                raise AutomaticRouteError(f"{building} 栋 {unit} 单元必须且只能有一张电梯大厅地图")
            lobbies[identity] = map_id
        else:
            floors.setdefault(identity, []).append(map_id)

    if not lobbies and not floors and not outdoors and not ferries:
        return []
    if "ferry" in types and len(ferries) != 1:
        raise AutomaticRouteError("流程中的摆渡层必须且只能有一张全局地图")
    if "ferry" not in types and ferries:
        raise AutomaticRouteError("摆渡层地图未在当前部署流程中使用")
    identities = sorted(set(lobbies) | set(floors))
    result: list[tuple[tuple[str, str], list[tuple[str, str]]]] = []
    for identity in identities:
        building, unit = identity
        lobby = lobbies.get(identity)
        outdoor = outdoors.get(identity)
        target_maps = sorted(set(floors.get(identity, [])))
        if not lobby or not target_maps:
            raise AutomaticRouteError(f"{building} 栋 {unit} 单元缺少电梯大厅或用户楼层地图实例")
        if "outdoor" in types and not outdoor:
            raise AutomaticRouteError(f"{building} 栋 {unit} 单元缺少户外地图实例")
        for target_map in target_maps:
            maps = {
                "ferry": ferries[0] if ferries else "",
                "outdoor": outdoor or "",
                "lobby": lobby,
                "target_floor": target_map,
            }
            result.append((identity, [(stage, maps[stage]) for stage in types]))
    return result


def _derive_unit_topology_routes(
    project: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    bindings: list[dict[str, Any]],
    sequences: list[tuple[tuple[str, str], list[tuple[str, str]]]],
) -> list[dict[str, Any]]:
    """Derive target branches for every concrete unit map pair."""
    components = _components(project)
    routes: list[dict[str, Any]] = []
    for identity, stage_maps in sequences:
        ordered = [
            _binding_for_identity_map(bindings, identity, stage, map_id)
            for stage, map_id in stage_maps
        ]
        target_map_id = stage_maps[-1][1]
        targets = [
            item for item in components
            if item.get("map_asset_id") == target_map_id and item.get("kind") == "target"
        ]
        if not targets:
            raise AutomaticRouteError(f"地图“{target_map_id}”的用户楼层缺少目标点；请回到地图补标记")
        for target in sorted(targets, key=lambda item: str(item.get("id") or "")):
            routes.append(_derive_route(project, assets, identity, ordered, target))
    return routes


def _binding_for_identity_map(
    bindings: list[dict[str, Any]],
    identity: tuple[str, str],
    stage: str,
    map_id: str,
) -> dict[str, Any]:
    expected_type = {"ferry": "ferry", "outdoor": "outdoor", "lobby": "indoor", "target_floor": "floor"}[stage]
    matches = [
        binding for binding in bindings
        if binding.get("map_asset_id") == map_id
        and binding.get("type") == expected_type
        and (
            (stage == "ferry" and not binding.get("building") and not binding.get("unit"))
            or (stage != "ferry" and binding.get("building") == identity[0]
                and binding.get("unit") == identity[1])
        )
    ]
    if len(matches) != 1:
        label = {"ferry": "摆渡层", "outdoor": "户外", "lobby": "电梯大厅", "target_floor": "用户楼层"}[stage]
        raise AutomaticRouteError(
            f"{identity[0]} 栋 {identity[1]} 单元的{label}地图缺少唯一定位绑定；请回到地图阶段修正"
        )
    return matches[0]


def _index(value: object, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise AutomaticRouteError(f"{label}列表无效")
    result = {
        str(item["id"]): item for item in value
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
    }
    if not result:
        raise AutomaticRouteError(f"尚未导入{label}")
    return result


def _bindings(project: dict[str, Any], assets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    raw = project.get("localization_bindings")
    if not isinstance(raw, list):
        raise AutomaticRouteError("定位绑定列表无效")
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        binding_id = str(item.get("id") or "").strip()
        map_id = str(item.get("map_asset_id") or "").strip()
        building = str(item.get("building") or "").strip()
        unit = str(item.get("unit") or "").strip()
        binding_type = str(item.get("type") or "").strip()
        global_ferry = binding_type == "ferry" and not building and not unit
        if not binding_id or map_id not in assets or (not global_ferry and (not building or not unit)):
            raise AutomaticRouteError("定位绑定不完整；请回到地图阶段补齐楼栋、单元与地图")
        if binding_type not in {"outdoor", "indoor", "ferry", "floor"}:
            raise AutomaticRouteError("定位绑定类型无效；请重新绑定地图阶段")
        result.append(item)
    return result


def _stage_maps(project: dict[str, Any], assets: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    flow = project.get("deployment_flow")
    assignments = project.get("map_stage_assignments")
    if not isinstance(flow, list) or not flow or not isinstance(assignments, list):
        raise AutomaticRouteError("尚未完成项目场景地图顺序；请回到创建项目检查部署流程")
    assigned = {
        str(row.get("stage")): str(row.get("map_asset_id")) for row in assignments
        if isinstance(row, dict) and str(row.get("stage") or "") and str(row.get("map_asset_id") or "") in assets
    }
    sequence: list[tuple[str, str]] = []
    for row in flow:
        if not isinstance(row, dict):
            raise AutomaticRouteError("项目场景地图顺序格式无效")
        stage = str(row.get("id") or "").strip()
        map_id = assigned.get(stage)
        if not stage or not map_id:
            raise AutomaticRouteError(f"场景阶段“{row.get('label') or stage or '未命名'}”尚未导入地图")
        sequence.append((stage, map_id))
    return sequence


def _ordered_bindings(bindings: list[dict[str, Any]], stage_maps: list[tuple[str, str]]) -> list[dict[str, Any]]:
    by_map: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        by_map.setdefault(str(binding["map_asset_id"]), []).append(binding)
    ordered: list[dict[str, Any]] = []
    for stage, map_id in stage_maps:
        candidates = by_map.get(map_id, [])
        if len(candidates) != 1:
            raise AutomaticRouteError(
                f"场景阶段“{stage}”需要且只能有一个同楼栋单元定位绑定；请回到地图阶段修正绑定"
            )
        binding = candidates[0]
        expected = "floor" if stage == "target_floor" else "indoor" if stage == "lobby" else None
        if expected and binding.get("type") != expected:
            raise AutomaticRouteError(f"场景阶段“{stage}”的地图绑定类型不正确；请回到地图阶段修正")
        ordered.append(binding)
    return ordered


def _derive_route(
    project: dict[str, Any], assets: dict[str, dict[str, Any]], identity: tuple[str, str], bindings: list[dict[str, Any]],
    target_component: dict[str, Any],
) -> dict[str, Any]:
    components = _components(project)
    waypoints = _waypoints(project)
    first_map_id = str(bindings[0]["map_asset_id"])
    start_component = _unique_component(components, first_map_id, "start", "首图起点")
    start_waypoint = _component_waypoint(start_component, waypoints, "start", "首图起点")
    target_waypoint = _component_waypoint(target_component, waypoints, "target", "末图目标")
    links: list[dict[str, Any]] = []
    entry_anchors: list[dict[str, Any]] = []
    entry_points: list[dict[str, float]] = [_pose(start_waypoint)]
    exit_points: list[dict[str, float]] = []
    elevators: list[dict[str, Any]] = []
    for index, binding in enumerate(bindings):
        stage = str(binding["type"])
        map_id = str(binding["map_asset_id"])
        if index:
            anchor, point = _stage_entry_anchor(components, waypoints, binding)
            entry_anchors.append({"binding_id": str(binding["id"]), "anchor": anchor})
            entry_points.append(point)
        if index == len(bindings) - 1:
            exit_points.append(_pose(target_waypoint))
            continue
        anchor, point, elevator = _stage_exit_anchor(components, waypoints, binding)
        links.append({
            "from_binding_id": str(binding["id"]),
            "to_binding_id": str(bindings[index + 1]["id"]),
            "anchor": anchor,
        })
        exit_points.append(point)
        if elevator is not None:
            elevators.append(elevator)
        # The map ID is intentionally read while deriving the anchor so
        # stale/malformed bindings cannot silently create cross-map links.
        if (anchor.get("component_id") or anchor.get("waypoint_id")) and map_id != str(binding["map_asset_id"]):
            raise AutomaticRouteError("地图切图锚点无效")
    elevator_chain = [
        _unique_component(components, str(binding["map_asset_id"]), "elevator", "地图切图电梯")
        for binding in bindings
        if binding.get("type") == "floor"
    ]
    _validate_elevator_chain([*elevators, *elevator_chain])
    handoff_transition_ids = {
        str(link["anchor"]["waypoint_id"])
        for link in links
        if link["anchor"].get("kind") == "waypoint"
    }
    execution_nodes: list[dict[str, Any]] = []
    for index, binding in enumerate(bindings):
        map_id = str(binding["map_asset_id"])
        refs = _derive_map_node_refs(
            project, assets[map_id], map_id, entry_points[index], exit_points[index],
            ignored_transition_ids=handoff_transition_ids,
        )
        execution_nodes.append({"binding_id": str(binding["id"]), "node_refs": refs})
    target_id = str(target_component.get("id") or "")
    target_count = sum(
        item.get("map_asset_id") == bindings[-1].get("map_asset_id") and item.get("kind") == "target"
        for item in components
    )
    return {
        "id": f"auto-{identity[0]}-{identity[1]}" if target_count == 1 else f"auto-{identity[0]}-{identity[1]}-{target_id}",
        "building": identity[0],
        "unit": identity[1],
        "binding_ids": [str(binding["id"]) for binding in bindings],
        "task_start_waypoint_id": str(start_waypoint["id"]),
        "task_target_waypoint_id": str(target_waypoint["id"]),
        "execution_nodes": execution_nodes,
        "links": links,
        **({"entry_anchors": entry_anchors} if entry_anchors else {}),
        "derivation": "scene-map-path-v1",
    }


def _stage_entry_anchor(
    components: list[dict[str, Any]], waypoints: list[dict[str, Any]], binding: dict[str, Any],
) -> tuple[dict[str, str], dict[str, float]]:
    """Resolve a map's automatic incoming hand-off from its stage semantics."""
    map_id, stage = str(binding["map_asset_id"]), str(binding["type"])
    if stage in {"ferry", "outdoor"}:
        component = _unique_component(components, map_id, "start", "转入地图起点")
        waypoint = _component_waypoint(component, waypoints, "start", "转入地图起点")
        return {"kind": "waypoint", "waypoint_id": str(waypoint["id"])}, _pose(waypoint)
    if stage == "indoor":
        component = _unique_component(components, map_id, "building_entrance", "楼栋入口")
        return {"kind": "component_center", "component_id": str(component["id"])}, _pose(component)
    if stage == "floor":
        component = _unique_component(components, map_id, "elevator", "用户层电梯")
        return {"kind": "component_center", "component_id": str(component["id"])}, _elevator_wait_pose(component)
    raise AutomaticRouteError("地图阶段类型无效")


def _stage_exit_anchor(
    components: list[dict[str, Any]], waypoints: list[dict[str, Any]], binding: dict[str, Any],
) -> tuple[dict[str, str], dict[str, float], dict[str, Any] | None]:
    """Resolve a map's outgoing hand-off without a user-controlled order."""
    map_id, stage = str(binding["map_asset_id"]), str(binding["type"])
    if stage in {"ferry", "outdoor"}:
        waypoint = _unique_handoff_waypoint(waypoints, map_id)
        return {"kind": "waypoint", "waypoint_id": str(waypoint["id"])}, _pose(waypoint), None
    if stage == "indoor":
        component = _unique_component(components, map_id, "elevator", "地图切图电梯")
        return (
            {"kind": "component_center", "component_id": str(component["id"])},
            _elevator_wait_pose(component),
            component,
        )
    raise AutomaticRouteError("当前地图阶段不能作为跨图来源")


def _unique_waypoint(
    waypoints: list[dict[str, Any]], map_id: str, kind: str, purpose: str,
) -> dict[str, Any]:
    candidates = [item for item in waypoints if item.get("map_asset_id") == map_id and item.get("kind") == kind]
    if len(candidates) != 1:
        action = "补标记" if not candidates else "只保留实际使用的一个标记"
        raise AutomaticRouteError(f"地图“{map_id}”的{purpose}必须唯一；请回到地图{action}")
    _pose(candidates[0])
    return candidates[0]


def _unique_handoff_waypoint(waypoints: list[dict[str, Any]], map_id: str) -> dict[str, Any]:
    """Use the established transition tool as an external map hand-off.

    ``map_transition`` remains accepted for imported legacy maps, but the
    guided UI intentionally keeps one familiar “过渡点” tool.  Its role is
    inferred solely from the map stage, never selected by the operator.
    """
    candidates = [
        item for item in waypoints
        if item.get("map_asset_id") == map_id and item.get("kind") in {"transition", "map_transition"}
        and not item.get("generated_by")
    ]
    if len(candidates) != 1:
        action = "补标记一个过渡点" if not candidates else "只保留一个过渡点"
        raise AutomaticRouteError(f"地图“{map_id}”的地图转场点必须唯一；请回到地图{action}")
    _pose(candidates[0])
    return candidates[0]


def _components(project: dict[str, Any]) -> list[dict[str, Any]]:
    value = project.get("components")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _waypoints(project: dict[str, Any]) -> list[dict[str, Any]]:
    value = project.get("waypoints")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _unique_component(components: list[dict[str, Any]], map_id: str, kind: str, purpose: str) -> dict[str, Any]:
    candidates = [item for item in components if item.get("map_asset_id") == map_id and item.get("kind") == kind]
    if len(candidates) != 1:
        action = "补标记" if not candidates else "只保留实际使用的一个标记"
        raise AutomaticRouteError(f"地图“{map_id}”的{purpose}必须唯一；请回到地图{action}")
    _pose(candidates[0])
    return candidates[0]


def _component_waypoint(component: dict[str, Any], waypoints: list[dict[str, Any]], kind: str, purpose: str) -> dict[str, Any]:
    ids = component.get("generated_waypoint_ids")
    candidates = [item for item in waypoints if item.get("generated_by") == component.get("id") and item.get("kind") == kind]
    if isinstance(ids, list):
        candidates = [item for item in candidates if item.get("id") in ids]
    if len(candidates) == 1:
        return candidates[0]
    # Compatibility for snapshots created before semantic components generated
    # their own waypoint.  It remains deterministic: exactly one is required.
    legacy = [item for item in waypoints if item.get("map_asset_id") == component.get("map_asset_id") and item.get("kind") == kind]
    if len(legacy) == 1:
        return legacy[0]
    raise AutomaticRouteError(f"地图“{component.get('map_asset_id')}”缺少唯一{purpose}；请在地图上重新标记")


def _validate_elevator_chain(elevators: list[dict[str, Any]]) -> None:
    if len(elevators) < 2:
        return
    physical_ids = []
    for elevator in elevators:
        attributes = elevator.get("attributes")
        physical_id = str(attributes.get("physical_elevator_id") or "").strip() if isinstance(attributes, dict) else ""
        if not physical_id:
            raise AutomaticRouteError(f"电梯“{elevator.get('label') or elevator.get('id')}”未关联物理电梯；请回到地图组件属性修正")
        physical_ids.append(physical_id)
    if len(set(physical_ids)) != 1:
        raise AutomaticRouteError("相邻地图的电梯未关联同一物理电梯；请回到地图组件属性修正")


def _elevator_wait_pose(elevator: dict[str, Any]) -> dict[str, float]:
    """Match the compiler's approved elevator-door wait geometry exactly."""
    center = _pose(elevator)
    attributes = elevator.get("attributes")
    if not isinstance(attributes, dict):
        raise AutomaticRouteError("电梯组件属性无效；请回到地图补齐候梯距离")
    try:
        height = float(attributes.get("height_m"))
        wait_distance = float(attributes.get("wait_distance_m", 1.5))
    except (TypeError, ValueError) as exc:
        raise AutomaticRouteError("电梯组件缺少有效门向尺寸或候梯距离") from exc
    if not 0 < height <= 20 or not 0.5 <= wait_distance <= 5:
        raise AutomaticRouteError("电梯组件门向尺寸或候梯距离无效")
    distance = height / 2.0 + wait_distance
    return {
        "x": center["x"] - sin(center["yaw"]) * distance,
        "y": center["y"] + cos(center["yaw"]) * distance,
        "yaw": center["yaw"],
    }


def _derive_map_node_refs(
    project: dict[str, Any], asset: dict[str, Any], map_id: str,
    start: dict[str, float], end: dict[str, float], *, ignored_transition_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    # Derivation must not inspect a previously saved route: only the hand-off
    # anchors selected from the current scene facts above may be excluded.
    handoff_ids = ignored_transition_ids or set()
    transitions = [
        waypoint for waypoint in _waypoints(project)
        if waypoint.get("map_asset_id") == map_id
        and waypoint.get("kind") == "transition"
        and not waypoint.get("generated_by")
        and not waypoint.get("exclude_task_export")
        and waypoint.get("id") not in handoff_ids
    ]
    candidates: list[tuple[dict[str, str], dict[str, float], str]] = []
    for waypoint in transitions:
        candidates.append((
            {"kind": "transition", "id": str(waypoint["id"])},
            _pose(waypoint),
            str(waypoint.get("label") or waypoint.get("id")),
        ))
    for component in _components(project):
        if component.get("map_asset_id") != map_id or component.get("kind") in {"start", "target", "elevator", "building_entrance"}:
            continue
        candidates.append((
            {"kind": "component", "id": str(component["id"])},
            _pose(component),
            str(component.get("label") or component.get("id")),
        ))
    return _ordered_map_nodes(
        asset,
        map_id,
        start,
        end,
        candidates,
        virtual_walls=_virtual_wall_segments(project, map_id),
    )


def _ordered_map_nodes(
    asset: dict[str, Any], map_id: str, start: dict[str, float], end: dict[str, float],
    candidates: list[tuple[dict[str, str], dict[str, float], str]],
    *,
    virtual_walls: list[dict[str, dict[str, float]]],
) -> list[dict[str, str]]:
    """Visit every marked task node without asking an operator to sort them.

    A transition or executable component is a deliberate map fact: it must be
    traversed, even where the shortest direct start-to-target route would not
    cross it. The next reachable fact is selected by map-path distance and a
    stable ref key breaks ties, producing one deterministic linked route.
    """
    remaining = list(candidates)
    ordered: list[dict[str, str]] = []
    current = start
    while remaining:
        options: list[tuple[float, str, tuple[dict[str, str], dict[str, float], str]]] = []
        for candidate in remaining:
            ref, point, label = candidate
            try:
                distance = _path_length(_map_path(asset, current, point, virtual_walls=virtual_walls))
            except AutomaticRouteError as error:
                kind = "过渡点" if ref["kind"] == "transition" else "组件"
                raise _map_node_error(asset, kind, label, error) from error
            options.append((distance, f"{ref['kind']}:{ref['id']}", candidate))
        _, _, selected = min(options)
        ref, point, _ = selected
        ordered.append(ref)
        current = point
        remaining.remove(selected)
    try:
        _map_path(asset, current, end, virtual_walls=virtual_walls)
    except AutomaticRouteError as error:
        raise _map_node_error(asset, "终点", str(asset.get("label") or map_id), error) from error
    return ordered


def _virtual_wall_segments(project: dict[str, Any], map_id: str) -> list[dict[str, dict[str, float]]]:
    """Return only this map's persisted virtual-wall segments.

    Virtual walls are drawn by an operator precisely to close map gaps and
    constrain the robot's usable space.  They therefore belong to the same
    per-map passability model as the imported occupancy grid, never to the
    user-editable route order.
    """
    raw_walls = project.get("virtual_walls")
    if not isinstance(raw_walls, list):
        return []
    matching = [
        wall for wall in raw_walls
        if isinstance(wall, dict) and str(wall.get("map_asset_id") or "") == map_id
    ]
    try:
        return _normalise_virtual_walls(matching)
    except ValueError as exc:
        raise AutomaticRouteError(f"地图“{map_id}”的虚拟墙无效；请回到地图修正") from exc


def _normalise_virtual_walls(value: object) -> list[dict[str, dict[str, float]]]:
    """Expand persisted polylines and legacy two-point walls into segments."""
    if not isinstance(value, (list, tuple)):
        raise ValueError("虚拟墙列表无效")
    segments: list[dict[str, dict[str, float]]] = []
    for wall in value:
        if not isinstance(wall, dict):
            raise ValueError("虚拟墙无效")
        points = wall.get("points")
        if points is None:
            points = [wall.get("start"), wall.get("end")]
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError("虚拟墙至少需要两个点")
        cleaned = [_wall_point(point) for point in points]
        for start, end in zip(cleaned, cleaned[1:]):
            if hypot(end["x"] - start["x"], end["y"] - start["y"]) <= 1e-9:
                raise ValueError("虚拟墙相邻点不能重合")
            segments.append({"start": start, "end": end})
    return segments


def _wall_point(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError("虚拟墙点位无效")
    try:
        point = {axis: float(value[axis]) for axis in ("x", "y")}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("虚拟墙点位无效") from exc
    if not all(isfinite(number) for number in point.values()):
        raise ValueError("虚拟墙点位无效")
    return point


def _path_length(path: list[tuple[float, float]]) -> float:
    return sum(hypot(right[0] - left[0], right[1] - left[1]) for left, right in zip(path, path[1:]))


def _map_node_error(asset: dict[str, Any], kind: str, label: str, error: AutomaticRouteError) -> AutomaticRouteError:
    map_label = str(asset.get("label") or asset.get("id") or "未命名地图")
    return AutomaticRouteError(f"地图“{map_label}”的{kind}“{label}”{error}")


def _pose(value: dict[str, Any]) -> dict[str, float]:
    try:
        point = {axis: float(value[axis]) for axis in ("x", "y")}
        point["yaw"] = float(value.get("yaw") or 0.0)
    except (KeyError, TypeError, ValueError) as exc:
        raise AutomaticRouteError("地图标记坐标无效；请回到地图重新标记") from exc
    if not all(isfinite(number) for number in point.values()):
        raise AutomaticRouteError("地图标记坐标无效；请回到地图重新标记")
    return point


def _map_path(
    asset: dict[str, Any], start: dict[str, float], end: dict[str, float], *, virtual_walls: object = (),
) -> list[tuple[float, float]]:
    walls = _normalise_virtual_walls(virtual_walls)
    wall_segments: list[WallSegment] = [
        _wall_segment(
            (wall["start"]["x"], wall["start"]["y"]),
            (wall["end"]["x"], wall["end"]["y"]),
        )
        for wall in walls
    ]
    grid = _read_grid(asset)
    if grid is None:
        return _direct_map_path(start, end, wall_segments)
    width, height, free = grid
    resolution = float(asset.get("resolution_m") or 0.0)
    origin = asset.get("origin")
    if resolution <= 0 or not isinstance(origin, list) or len(origin) < 2:
        return _direct_map_path(start, end, wall_segments)
    start_cell = _nearest_free_cell(
        start, width, height, free, origin, resolution, virtual_walls=wall_segments,
    )
    end_cell = _nearest_free_cell(
        end, width, height, free, origin, resolution, virtual_walls=wall_segments,
    )
    cells = _astar(
        width,
        height,
        free,
        start_cell,
        end_cell,
        origin=origin,
        resolution=resolution,
        virtual_walls=wall_segments,
    )
    if cells is None:
        raise AutomaticRouteError(
            f"地图“{asset.get('label') or asset.get('id')}”的起止标记被可通行区域或虚拟墙阻断；"
            "请回到地图检查"
        )
    return [(float(origin[0]) + (x + .5) * resolution, float(origin[1]) + (height - y - .5) * resolution) for x, y in cells]


def _direct_map_path(
    start: dict[str, float], end: dict[str, float],
    wall_segments: list[WallSegment],
) -> list[tuple[float, float]]:
    if _crosses_virtual_wall((start["x"], start["y"]), (end["x"], end["y"]), wall_segments):
        raise AutomaticRouteError("起止标记被虚拟墙阻断；请回到地图调整虚拟墙或标记")
    return [(start["x"], start["y"]), (end["x"], end["y"])]


def _read_grid(asset: dict[str, Any]) -> Grid | None:
    source_yaml = asset.get("source_yaml")
    if not isinstance(source_yaml, str):
        return None
    image = Path(source_yaml).with_name("map.pgm")
    try:
        data = image.read_bytes()
    except OSError:
        return None
    # Some deployment filesystems have coarse timestamp resolution.  A content
    # fingerprint avoids ever retaining an outdated occupancy map after a fast
    # re-import, while the expensive pixel-to-cell expansion remains cached.
    cache_key = (str(image.resolve()), blake2b(data, digest_size=16).digest())
    with _GRID_CACHE_LOCK:
        if cache_key in _GRID_CACHE:
            _GRID_CACHE.move_to_end(cache_key)
            return _GRID_CACHE[cache_key]

    grid = _read_grid_data(data)
    with _GRID_CACHE_LOCK:
        _GRID_CACHE[cache_key] = grid
        _GRID_CACHE.move_to_end(cache_key)
        while len(_GRID_CACHE) > _GRID_CACHE_LIMIT:
            _GRID_CACHE.popitem(last=False)
    return grid


def _read_grid_data(data: bytes) -> Grid | None:
    try:
        header, pixels = data.split(b"\n255\n", 1)
        parts = b" ".join(
            line.strip()
            for line in header.splitlines()
            if not line.lstrip().startswith(b"#")
        ).split()
        if len(parts) < 3 or parts[0] != b"P5":
            return None
        width, height = int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if width <= 0 or height <= 0 or len(pixels) != width * height:
        return None
    high = sum(value >= 200 for value in pixels)
    low = sum(value <= 50 for value in pixels)
    free_predicate = (lambda value: value >= 200) if high >= low else (lambda value: value <= 50)
    free = {(index % width, index // width) for index, value in enumerate(pixels) if free_predicate(value)}
    return (width, height, free) if free else None


def _nearest_free_cell(
    point: dict[str, float], width: int, height: int, free: set[tuple[int, int]], origin: list[Any], resolution: float,
    *, virtual_walls: list[WallSegment] = (),
) -> tuple[int, int]:
    x = int((point["x"] - float(origin[0])) / resolution)
    y = height - 1 - int((point["y"] - float(origin[1])) / resolution)
    point_xy = (point["x"], point["y"])

    def usable(cell: tuple[int, int]) -> bool:
        return cell in free and not _crosses_virtual_wall(
            point_xy, _cell_center(cell, height, origin, resolution), virtual_walls,
        )

    # Map markers normally land in a traversable cell.  Returning it directly
    # avoids sorting every free pixel in a multi-megapixel PGM for each route
    # endpoint.  The expanding search below retains the nearest-cell fallback
    # for markers intentionally placed on a wall or occupied pixel.
    preferred = (x, y)
    if usable(preferred):
        return preferred

    max_radius = max(
        abs(x), abs(x - (width - 1)), abs(y), abs(y - (height - 1)),
    )
    best_cell: tuple[int, int] | None = None
    best_distance: int | None = None
    for radius in range(1, max_radius + 1):
        left = x - radius
        right = x + radius
        top = y - radius
        bottom = y + radius
        ring: list[tuple[int, int]] = []
        for column in range(max(0, left), min(width - 1, right) + 1):
            ring.append((column, top))
            if bottom != top:
                ring.append((column, bottom))
        for row in range(max(0, top + 1), min(height - 1, bottom)):
            ring.append((left, row))
            if right != left:
                ring.append((right, row))
        for cell in ring:
            if not usable(cell):
                continue
            distance = (cell[0] - x) ** 2 + (cell[1] - y) ** 2
            if best_distance is None or (distance, cell) < (best_distance, best_cell):
                best_cell = cell
                best_distance = distance
        # A future ring cannot contain a cell nearer than its Chebyshev radius.
        if best_cell is not None and (radius + 1) ** 2 > best_distance:
            return best_cell
    if best_cell is None:
        raise AutomaticRouteError("地图标记被虚拟墙与可通行区域隔断；请检查地图")
    return best_cell


def _astar(
    width: int, height: int, free: set[tuple[int, int]], start: tuple[int, int], end: tuple[int, int], *,
    origin: list[Any] | None = None, resolution: float = 0.0,
    virtual_walls: list[WallSegment] = (),
) -> list[tuple[int, int]] | None:
    frontier: list[tuple[float, int, tuple[int, int]]] = [(0.0, 0, start)]
    previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    score = {start: 0.0}
    counter = 0
    while frontier:
        _, _, current = heappop(frontier)
        if current == end:
            path = []
            while current is not None:
                path.append(current)
                current = previous[current]
            return list(reversed(path))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            nxt = (current[0] + dx, current[1] + dy)
            if not (0 <= nxt[0] < width and 0 <= nxt[1] < height) or nxt not in free:
                continue
            if virtual_walls and origin is not None and resolution > 0 and _crosses_virtual_wall(
                _cell_center(current, height, origin, resolution),
                _cell_center(nxt, height, origin, resolution),
                virtual_walls,
            ):
                continue
            candidate = score[current] + hypot(dx, dy)
            if candidate >= score.get(nxt, float("inf")):
                continue
            previous[nxt] = current
            score[nxt] = candidate
            counter += 1
            heappush(frontier, (candidate + hypot(end[0] - nxt[0], end[1] - nxt[1]), counter, nxt))
    return None


def _cell_center(
    cell: tuple[int, int], height: int, origin: list[Any], resolution: float,
) -> tuple[float, float]:
    return (
        float(origin[0]) + (cell[0] + .5) * resolution,
        float(origin[1]) + (height - cell[1] - .5) * resolution,
    )


def _crosses_virtual_wall(
    start: tuple[float, float], end: tuple[float, float],
    walls: list[WallSegment],
) -> bool:
    edge_min_x = min(start[0], end[0])
    edge_max_x = max(start[0], end[0])
    edge_min_y = min(start[1], end[1])
    edge_max_y = max(start[1], end[1])
    for wall_start, wall_end, wall_min_x, wall_max_x, wall_min_y, wall_max_y in walls:
        if (
            edge_max_x < wall_min_x or wall_max_x < edge_min_x
            or edge_max_y < wall_min_y or wall_max_y < edge_min_y
        ):
            continue
        if _segments_intersect(start, end, wall_start, wall_end):
            return True
    return False


def _wall_segment(start: tuple[float, float], end: tuple[float, float]) -> WallSegment:
    """Attach an axis-aligned bound so most grid edges skip exact geometry."""
    return (
        start,
        end,
        min(start[0], end[0]),
        max(start[0], end[0]),
        min(start[1], end[1]),
        max(start[1], end[1]),
    )


def _segments_intersect(
    first_start: tuple[float, float], first_end: tuple[float, float],
    second_start: tuple[float, float], second_end: tuple[float, float],
) -> bool:
    """Treat touching a virtual wall as blocked, not merely strict crossing."""
    epsilon = 1e-9

    def orientation(
        start: tuple[float, float], end: tuple[float, float], point: tuple[float, float],
    ) -> float:
        return (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])

    def on_segment(
        start: tuple[float, float], end: tuple[float, float], point: tuple[float, float],
    ) -> bool:
        return (
            min(start[0], end[0]) - epsilon <= point[0] <= max(start[0], end[0]) + epsilon
            and min(start[1], end[1]) - epsilon <= point[1] <= max(start[1], end[1]) + epsilon
        )

    first_second_start = orientation(first_start, first_end, second_start)
    first_second_end = orientation(first_start, first_end, second_end)
    second_first_start = orientation(second_start, second_end, first_start)
    second_first_end = orientation(second_start, second_end, first_end)
    if ((first_second_start > epsilon and first_second_end < -epsilon) or (first_second_start < -epsilon and first_second_end > epsilon)) and (
        (second_first_start > epsilon and second_first_end < -epsilon) or (second_first_start < -epsilon and second_first_end > epsilon)
    ):
        return True
    return (
        abs(first_second_start) <= epsilon and on_segment(first_start, first_end, second_start)
        or abs(first_second_end) <= epsilon and on_segment(first_start, first_end, second_end)
        or abs(second_first_start) <= epsilon and on_segment(second_start, second_end, first_start)
        or abs(second_first_end) <= epsilon and on_segment(second_start, second_end, first_end)
    )
