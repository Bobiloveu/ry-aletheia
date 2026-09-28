"""Pure planning for explicit, map-local deployment task execution chains.

The store owns persistence; this module only turns an already selected order
into directed navigation nodes.  It never infers an order from component draw
order or coordinate proximity.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, hypot, isfinite, sin
import re
from typing import Any

from .task_path import TASK_TRANSITION_SPEED_MODES, return_yaw
from .component_defaults import ComponentDefaultsError, component_speed_profile


class ExecutionChainError(ValueError):
    """The explicit project intent cannot become a safe map traversal."""


NAVIGATION_REGION_SPEEDS = frozenset({"task_point", "single_point", "slow_point", "narrow_point"})
NAVIGATION_REGION_KINDS = frozenset({"slow_zone", "ramp", "narrow_passage"})
# A building entrance is a map-to-map localization anchor, not an executable
# task node.  It must not be expanded into a speed/action waypoint.
UNSUPPORTED_COMPONENT_KINDS = frozenset()
_ANCHOR_COMPONENT_KINDS = frozenset({"start", "target", "elevator", "building_entrance"})


@dataclass(frozen=True)
class ExecutionNode:
    """One generated or saved navigation arrival point in a directed map path."""

    source_kind: str
    source_id: str
    role: str
    x: float
    y: float
    yaw: float
    incoming_speed_mode: str
    generated_by: str | None = None
    action: str | None = None
    return_action: str | None = None
    controller_device_id: str | None = None
    component_kind: str | None = None


@dataclass(frozen=True)
class MapExecutionPlan:
    """The same physical map path projected in outbound and return directions."""

    outbound_nodes: tuple[ExecutionNode, ...]
    return_nodes: tuple[ExecutionNode, ...]


def build_map_execution_plan(
    project: dict[str, Any],
    binding_id: str,
    *,
    start_anchor: dict[str, Any],
    end_anchor: dict[str, Any],
    end_speed_mode: str,
) -> MapExecutionPlan:
    """Resolve one bound map's explicit nodes into forward and reverse segments.

    `incoming_speed_mode` is always attached to the edge ending at the node.
    Return nodes take the next outbound edge's mode, so a region's interior
    edge remains identical even though traversal direction reverses.
    """
    if not isinstance(project, dict):
        raise ExecutionChainError("部署项目格式无效")
    binding = _binding(project, binding_id)
    asset = _asset(project, str(binding["map_asset_id"]))
    refs = _execution_refs(project, binding)
    start = _pose(start_anchor, "路径起点")
    end = _pose(end_anchor, "路径终点")
    if end_speed_mode not in NAVIGATION_REGION_SPEEDS | {"task_point", "backward"}:
        raise ExecutionChainError("路径终点速度模式无效")
    transitions = _indexed(project.get("waypoints"), "过渡点")
    components = _indexed(project.get("components"), "组件")
    raw_nodes: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for ref in refs:
        kind, source_id = ref["kind"], ref["id"]
        source = transitions.get(source_id) if kind == "transition" else components.get(source_id)
        if source is None:
            raise ExecutionChainError("执行链引用的节点不存在")
        if source.get("map_asset_id") != binding["map_asset_id"]:
            raise ExecutionChainError("执行链节点必须位于该定位绑定地图")
        raw_nodes.append((ref, source))

    outbound: list[ExecutionNode] = []
    for index, (ref, source) in enumerate(raw_nodes):
        previous = _source_anchor(raw_nodes[index - 1][1]) if index else start
        following = _source_anchor(raw_nodes[index + 1][1]) if index + 1 < len(raw_nodes) else end
        if ref["kind"] == "transition":
            _require_transition(source)
            point = _pose(source, "任务过渡点")
            _validate_map_point(asset, point, "任务过渡点")
            outbound.append(ExecutionNode(
                source_kind="transition", source_id=ref["id"], role="waypoint",
                x=point["x"], y=point["y"], yaw=point["yaw"],
                incoming_speed_mode=str(source.get("speed_mode") or "single_point"),
            ))
            continue
        component_kind = str(source.get("kind") or "")
        if component_kind in UNSUPPORTED_COMPONENT_KINDS:
            raise ExecutionChainError(
                f"组件“{_label(source)}”在当前实验 profile 尚无批准的执行语义"
            )
        if component_kind in {"gate", "auto_door"}:
            outbound.extend(_access_nodes(asset, source, previous, following))
            continue
        if component_kind not in NAVIGATION_REGION_KINDS:
            raise ExecutionChainError(f"组件“{_label(source)}”不能加入当前地图任务路径顺序")
        if component_kind == "narrow_passage":
            outbound.extend(_narrow_passage_nodes(asset, source, previous, following))
            continue
        if component_kind in NAVIGATION_REGION_KINDS:
            outbound.extend(_area_region_nodes(asset, source, previous, following))
            continue
    returned = _reverse_nodes(outbound, end_speed_mode)
    return MapExecutionPlan(tuple(outbound), tuple(returned))


def _binding(project: dict[str, Any], binding_id: str) -> dict[str, Any]:
    binding = next(
        (item for item in project.get("localization_bindings", [])
         if isinstance(item, dict) and item.get("id") == binding_id),
        None,
    )
    if binding is None:
        raise ExecutionChainError("执行链定位绑定不存在")
    return binding


def _asset(project: dict[str, Any], map_asset_id: str) -> dict[str, Any]:
    asset = next(
        (item for item in project.get("map_assets", [])
         if isinstance(item, dict) and item.get("id") == map_asset_id),
        None,
    )
    if asset is None:
        raise ExecutionChainError("执行链地图不存在")
    return asset


def _execution_refs(project: dict[str, Any], binding: dict[str, Any]) -> list[dict[str, str]]:
    binding_id = str(binding["id"])
    route = next(
        (item for item in project.get("localization_routes", [])
         if isinstance(item, dict) and binding_id in item.get("binding_ids", [])),
        None,
    )
    if route is None:
        raise ExecutionChainError("执行链所属定位路线不存在")
    entries = route.get("execution_nodes")
    if not isinstance(entries, list):
        if _unplanned_refs(project, str(binding["map_asset_id"])):
            raise ExecutionChainError("当前地图尚未编排任务路径顺序")
        return []
    entry = next(
        (item for item in entries if isinstance(item, dict) and item.get("binding_id") == binding_id),
        None,
    )
    if entry is None or not isinstance(entry.get("node_refs"), list):
        raise ExecutionChainError("当前地图尚未编排任务路径顺序")
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in entry["node_refs"]:
        if not isinstance(raw, dict) or set(raw) != {"kind", "id"}:
            raise ExecutionChainError("执行链节点格式无效")
        kind, source_id = str(raw.get("kind") or ""), str(raw.get("id") or "")
        if kind not in {"transition", "component"} or not source_id:
            raise ExecutionChainError("执行链节点类型无效")
        if (kind, source_id) in seen:
            raise ExecutionChainError("执行链节点不能重复")
        seen.add((kind, source_id))
        refs.append({"kind": kind, "id": source_id})
    expected = _unplanned_refs(project, str(binding["map_asset_id"]))
    actual = {(item["kind"], item["id"]) for item in refs}
    if expected != actual:
        raise ExecutionChainError("当前地图存在未编排任务节点；请完善任务路径顺序")
    return refs


def _unplanned_refs(project: dict[str, Any], map_asset_id: str) -> set[tuple[str, str]]:
    values: set[tuple[str, str]] = set()
    handoff_waypoints = _handoff_transition_ids(project, map_asset_id)
    for waypoint in project.get("waypoints", []):
        if (
            isinstance(waypoint, dict) and waypoint.get("map_asset_id") == map_asset_id
            and waypoint.get("kind") == "transition" and not waypoint.get("generated_by")
            and not waypoint.get("exclude_task_export") and isinstance(waypoint.get("id"), str)
            and waypoint.get("id") not in handoff_waypoints
        ):
            values.add(("transition", waypoint["id"]))
    for component in project.get("components", []):
        if (
            isinstance(component, dict) and component.get("map_asset_id") == map_asset_id
            and component.get("kind") not in _ANCHOR_COMPONENT_KINDS
            and isinstance(component.get("id"), str)
        ):
            values.add(("component", component["id"]))
    return values


def _handoff_transition_ids(project: dict[str, Any], map_asset_id: str) -> set[str]:
    """Transition points used as cross-map anchors are not task nodes."""
    waypoint_by_id = {
        item.get("id"): item for item in project.get("waypoints", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    result: set[str] = set()
    for route in project.get("localization_routes", []):
        if not isinstance(route, dict):
            continue
        for link in route.get("links", []):
            anchor = link.get("anchor") if isinstance(link, dict) else None
            if not isinstance(anchor, dict) or anchor.get("kind") != "waypoint":
                continue
            identifier = anchor.get("waypoint_id")
            waypoint = waypoint_by_id.get(identifier)
            if waypoint is not None and waypoint.get("map_asset_id") == map_asset_id and waypoint.get("kind") == "transition":
                result.add(identifier)
    return result


def _indexed(value: object, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise ExecutionChainError(f"{label}列表无效")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            continue
        result[item["id"]] = item
    return result


def _require_transition(waypoint: dict[str, Any]) -> None:
    if waypoint.get("kind") != "transition" or waypoint.get("generated_by") or waypoint.get("exclude_task_export"):
        raise ExecutionChainError("执行链只能引用手动任务过渡点")
    speed = str(waypoint.get("speed_mode") or "single_point")
    if speed not in TASK_TRANSITION_SPEED_MODES:
        raise ExecutionChainError("过渡点速度模式无效")


def _area_region_nodes(
    asset: dict[str, Any], component: dict[str, Any], previous: dict[str, float], following: dict[str, float],
) -> list[ExecutionNode]:
    """Expand a passive region footprint along the actual task travel direction.

    A slow zone, narrow passage or ramp uses yaw only to rotate its rectangular
    coverage area. Unlike a gate or automatic door, it never prescribes which
    way the robot crosses that area.
    """
    entry, exit_point, speed = _area_traversal_points(asset, component, previous, following)
    source_id = str(component["id"])
    return [
        ExecutionNode("component", source_id, "entry", entry["x"], entry["y"], entry["yaw"], "single_point", source_id),
        ExecutionNode("component", source_id, "exit", exit_point["x"], exit_point["y"], exit_point["yaw"], speed, source_id),
    ]


def _narrow_passage_nodes(
    asset: dict[str, Any], component: dict[str, Any], previous: dict[str, float], following: dict[str, float],
) -> list[ExecutionNode]:
    """Cross a narrow passage from one end of its long axis to the other."""
    entry, exit_point, speed = _narrow_passage_traversal_points(asset, component, previous, following)
    source_id = str(component["id"])
    return [
        ExecutionNode("component", source_id, "entry", entry["x"], entry["y"], entry["yaw"], "single_point", source_id),
        ExecutionNode("component", source_id, "exit", exit_point["x"], exit_point["y"], exit_point["yaw"], speed, source_id),
    ]


def _access_nodes(
    asset: dict[str, Any], component: dict[str, Any], previous: dict[str, float], following: dict[str, float],
) -> list[ExecutionNode]:
    attributes = component.get("attributes")
    if not isinstance(attributes, dict):
        raise ExecutionChainError(f"组件“{_label(component)}”属性无效")
    pre_open_distance, post_open_distance = _access_clearance_distances(component, attributes)
    entry, exit_point, speed = _barrier_traversal_points(
        asset, component, previous, following, pre_open_distance, post_open_distance,
    )
    controller_device_id = "".join(str(attributes.get("controller_device_id") or "").split())
    if not re.fullmatch(r"[1-9][0-9]*", controller_device_id):
        raise ExecutionChainError(f"组件“{_label(component)}”必须填写纯数字控制设备号")
    source_id = str(component["id"])
    return [
        ExecutionNode(
            "component", source_id, "entry", entry["x"], entry["y"], entry["yaw"], speed,
            source_id, "open_go", "close_back", controller_device_id, str(component["kind"]),
        ),
        ExecutionNode(
            "component", source_id, "exit", exit_point["x"], exit_point["y"], exit_point["yaw"], speed,
            source_id, "close_go", "open_back", controller_device_id, str(component["kind"]),
        ),
    ]


def _access_clearance_distances(
    component: dict[str, Any], attributes: dict[str, Any],
) -> tuple[float, float]:
    values: list[float] = []
    for key, label in (
        ("pre_open_distance_m", "开门前距离"),
        ("post_open_distance_m", "开门后停靠距离"),
    ):
        try:
            value = float(attributes.get(key, 1.5))
        except (TypeError, ValueError) as exc:
            raise ExecutionChainError(f"组件“{_label(component)}”{label}无效") from exc
        if not isfinite(value) or not .5 <= value <= 5.0:
            raise ExecutionChainError(f"组件“{_label(component)}”{label}应在 0.5 至 5 米之间")
        values.append(value)
    return values[0], values[1]


def _barrier_traversal_points(
    asset: dict[str, Any], component: dict[str, Any], previous: dict[str, float], following: dict[str, float],
    pre_open_distance: float, post_open_distance: float,
) -> tuple[dict[str, float], dict[str, float], str]:
    """Cross a gate or door through the normal of its physical long edge.

    The component's rectangle describes the facility, not an operator-selected
    travel arrow.  Its longest edge is the barrier face; adjacent automatically
    derived nodes select the two sides that the robot must traverse.
    """
    center, width, height, speed = _region_geometry(component)
    if width >= height:
        normal_x, normal_y, half_depth = -sin(center["yaw"]), cos(center["yaw"]), height / 2.0
    else:
        normal_x, normal_y, half_depth = cos(center["yaw"]), sin(center["yaw"]), width / 2.0
    previous_side = (previous["x"] - center["x"]) * normal_x + (previous["y"] - center["y"]) * normal_y
    following_side = (following["x"] - center["x"]) * normal_x + (following["y"] - center["y"]) * normal_y
    if abs(previous_side) <= 1e-7 or abs(following_side) <= 1e-7 or previous_side * following_side >= 0:
        raise ExecutionChainError(
            f"组件“{_label(component)}”门体没有被任务路径从两侧穿过；请回到地图调整位置或尺寸"
        )
    entry_side = -1.0 if previous_side < 0 else 1.0
    exit_side = -entry_side
    entry = {
        "x": center["x"] + normal_x * entry_side * (half_depth + pre_open_distance),
        "y": center["y"] + normal_y * entry_side * (half_depth + pre_open_distance),
    }
    exit_point = {
        "x": center["x"] + normal_x * exit_side * (half_depth + post_open_distance),
        "y": center["y"] + normal_y * exit_side * (half_depth + post_open_distance),
    }
    travel_yaw = atan2(exit_point["y"] - entry["y"], exit_point["x"] - entry["x"])
    entry["yaw"] = travel_yaw
    exit_point["yaw"] = travel_yaw
    _validate_map_point(asset, entry, f"组件“{_label(component)}”入口")
    _validate_map_point(asset, exit_point, f"组件“{_label(component)}”出口")
    return entry, exit_point, speed


def _area_traversal_points(
    asset: dict[str, Any], component: dict[str, Any], previous: dict[str, float], following: dict[str, float],
) -> tuple[dict[str, float], dict[str, float], str]:
    center, width, height, speed = _region_geometry(component)
    entry = _region_boundary_point(
        previous, center, center, width, height, "入口", component, select="entry",
    )
    exit_point = _region_boundary_point(
        center, following, center, width, height, "出口", component, select="exit",
    )
    _validate_map_point(asset, entry, f"区域组件“{_label(component)}”入口")
    _validate_map_point(asset, exit_point, f"区域组件“{_label(component)}”出口")
    return entry, exit_point, speed


def _narrow_passage_traversal_points(
    asset: dict[str, Any], component: dict[str, Any], previous: dict[str, float], following: dict[str, float],
) -> tuple[dict[str, float], dict[str, float], str]:
    """Use the passage's rotated long axis rather than the target-side chord."""
    center, width, height, speed = _region_geometry(component)
    if height >= width:
        axis_x, axis_y, half_length = -sin(center["yaw"]), cos(center["yaw"]), height / 2.0
    else:
        axis_x, axis_y, half_length = cos(center["yaw"]), sin(center["yaw"]), width / 2.0
    negative = {"x": center["x"] - axis_x * half_length, "y": center["y"] - axis_y * half_length}
    positive = {"x": center["x"] + axis_x * half_length, "y": center["y"] + axis_y * half_length}
    previous_to_negative = hypot(previous["x"] - negative["x"], previous["y"] - negative["y"])
    previous_to_positive = hypot(previous["x"] - positive["x"], previous["y"] - positive["y"])
    entry, exit_point = (negative, positive) if previous_to_negative <= previous_to_positive else (positive, negative)
    travel_yaw = atan2(exit_point["y"] - entry["y"], exit_point["x"] - entry["x"])
    entry["yaw"] = travel_yaw
    exit_point["yaw"] = travel_yaw
    _validate_map_point(asset, entry, f"窄通道“{_label(component)}”入口")
    _validate_map_point(asset, exit_point, f"窄通道“{_label(component)}”出口")
    return entry, exit_point, speed


def _region_geometry(component: dict[str, Any]) -> tuple[dict[str, float], float, float, str]:
    center = _pose(component, f"组件“{_label(component)}”")
    attributes = component.get("attributes")
    if not isinstance(attributes, dict):
        raise ExecutionChainError(f"组件“{_label(component)}”属性无效")
    try:
        width = float(attributes.get("width_m"))
        height = float(attributes.get("height_m"))
    except (TypeError, ValueError) as exc:
        raise ExecutionChainError(f"区域组件“{_label(component)}”尺寸无效") from exc
    if not all(isfinite(value) and 0.1 <= value <= 20.0 for value in (width, height)):
        raise ExecutionChainError(f"区域组件“{_label(component)}”尺寸无效")
    try:
        speed = component_speed_profile(str(component.get("kind") or ""), attributes.get("speed_profile")) or ""
    except ComponentDefaultsError as exc:
        raise ExecutionChainError(str(exc)) from exc
    if speed not in NAVIGATION_REGION_SPEEDS:
        raise ExecutionChainError(f"组件“{_label(component)}”速度模式无效")
    return center, width, height, speed


def _region_boundary_point(
    start: dict[str, float], end: dict[str, float], center: dict[str, float], width: float, height: float,
    role: str, component: dict[str, Any], *, select: str,
) -> dict[str, float]:
    """Find one passive-region boundary on a required route leg.

    Derived component order makes the region centre a mandatory intermediate
    anchor. Splitting at that anchor lets an off-line marked region form a safe
    detour, while the two emitted points still bound the speed-controlled area.
    """
    dx, dy = end["x"] - start["x"], end["y"] - start["y"]
    if hypot(dx, dy) < 1e-7:
        raise ExecutionChainError(f"区域组件“{_label(component)}”{role}方向无法确定；请拉开相邻标记")
    entry_ratio, exit_ratio = _segment_area_span(
        _component_local(start, center),
        _component_local(end, center),
        width / 2.0,
        height / 2.0,
    )
    ratio = entry_ratio if select == "entry" else exit_ratio
    if ratio is None:
        raise ExecutionChainError(f"区域组件“{_label(component)}”{role}无法与任务路径连接；请调整区域位置或尺寸")
    return {
        "x": start["x"] + dx * ratio,
        "y": start["y"] + dy * ratio,
        "yaw": atan2(dy, dx),
    }


def _component_local(point: dict[str, float], center: dict[str, float]) -> tuple[float, float]:
    dx, dy = point["x"] - center["x"], point["y"] - center["y"]
    return (
        cos(center["yaw"]) * dx + sin(center["yaw"]) * dy,
        -sin(center["yaw"]) * dx + cos(center["yaw"]) * dy,
    )


def _segment_area_span(
    start: tuple[float, float], end: tuple[float, float], half_width: float, half_height: float,
) -> tuple[float | None, float | None]:
    entry, exit_ = 0.0, 1.0
    for origin, delta, limit in (
        (start[0], end[0] - start[0], half_width),
        (start[1], end[1] - start[1], half_height),
    ):
        if abs(delta) < 1e-9:
            if origin < -limit or origin > limit:
                return None, None
            continue
        low, high = sorted(((-limit - origin) / delta, (limit - origin) / delta))
        entry, exit_ = max(entry, low), min(exit_, high)
        if entry > exit_:
            return None, None
    if entry > 1.0 or exit_ < 0.0:
        return None, None
    return max(0.0, entry), min(1.0, exit_)


def _reverse_nodes(outbound: list[ExecutionNode], end_speed_mode: str) -> list[ExecutionNode]:
    returned: list[ExecutionNode] = []
    for index in range(len(outbound) - 1, -1, -1):
        node = outbound[index]
        incoming = outbound[index + 1].incoming_speed_mode if index + 1 < len(outbound) else end_speed_mode
        returned.append(ExecutionNode(
            source_kind=node.source_kind, source_id=node.source_id, role=node.role,
            x=node.x, y=node.y, yaw=return_yaw(node.yaw), incoming_speed_mode=incoming,
            generated_by=node.generated_by,
            action=node.return_action,
            return_action=node.action,
            controller_device_id=node.controller_device_id,
            component_kind=node.component_kind,
        ))
    return returned


def _source_anchor(source: dict[str, Any]) -> dict[str, float]:
    return _pose(source, f"组件或过渡点“{_label(source)}”")


def _pose(source: object, label: str) -> dict[str, float]:
    if not isinstance(source, dict):
        raise ExecutionChainError(f"{label}坐标无效")
    try:
        point = {key: float(source.get(key, 0.0)) for key in ("x", "y", "yaw")}
    except (TypeError, ValueError) as exc:
        raise ExecutionChainError(f"{label}坐标无效") from exc
    if not all(isfinite(value) and abs(value) < 1e7 for value in point.values()):
        raise ExecutionChainError(f"{label}坐标无效")
    return point


def _validate_map_point(asset: dict[str, Any], point: dict[str, float], label: str) -> None:
    try:
        origin = asset["origin"]
        minimum_x, minimum_y = float(origin[0]), float(origin[1])
        maximum_x = minimum_x + float(asset["width"]) * float(asset["resolution_m"])
        maximum_y = minimum_y + float(asset["height"]) * float(asset["resolution_m"])
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ExecutionChainError("执行链地图范围无效") from exc
    if not minimum_x <= point["x"] <= maximum_x or not minimum_y <= point["y"] <= maximum_y:
        raise ExecutionChainError(f"{label}超出地图边界")

def _label(source: dict[str, Any]) -> str:
    return str(source.get("label") or source.get("id") or "未命名组件")
