"""Pure helpers for controlled deployment localization exports.

The deployment editor records elevator *button* labels.  Runtime consumers,
however, require a zero-based physical position where button ``0`` does not
exist.  This module owns that conversion and the safe package layout; it does
not read or write robot runtime directories.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from math import isfinite
from pathlib import PurePosixPath
from pathlib import Path
import re
from typing import Any


class LocationManifestError(ValueError):
    """Raised when a deployment identity or elevator button is unsafe."""


def button_sequence(min_floor: int, max_floor: int) -> tuple[int, ...]:
    """Return served elevator buttons in their physical travel order.

    Floor button ``0`` is intentionally omitted: real panels use the signed
    basement labels followed directly by floor 1, while the physical index is
    zero based.
    """
    if min_floor > max_floor:
        raise LocationManifestError("电梯按钮范围无效")
    values = tuple(value for value in range(min_floor, max_floor + 1) if value != 0)
    if not values:
        raise LocationManifestError("电梯按钮范围不能只包含 0")
    return values


def physical_floor_index(min_floor: int, max_floor: int, button_floor: int) -> int:
    """Resolve one elevator button label to its zero-based physical level."""
    values = button_sequence(min_floor, max_floor)
    if button_floor == 0:
        raise LocationManifestError("电梯按钮 0 不参与物理楼层编号")
    if button_floor not in values:
        raise LocationManifestError("电梯按钮层不在服务范围内")
    return values.index(button_floor)


@dataclass(frozen=True)
class RuntimePath:
    """One package artifact and its fixed installer destination."""

    relative: str
    installed: str


@dataclass(frozen=True)
class LocationArtifact:
    """An in-memory controlled package member."""

    relative_path: str
    content: bytes


@dataclass(frozen=True)
class RenderedLocationManifest:
    """The reviewed location manifest and its package-owned dependencies."""

    json_bytes: bytes
    artifacts: tuple[LocationArtifact, ...]
    summary: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class RuntimeLayout:
    """Build deterministic, non-user-controlled localization artifact paths."""

    project_id: str
    community: str

    LOCALIZATION_ROOT = PurePosixPath("/opt/ry/config/localization/config")
    MAP_ROOT = PurePosixPath("/opt/ry/data/maps")

    def __post_init__(self) -> None:
        validate_path_component(self.project_id, "项目")
        validate_path_component(self.community, "小区")

    def localization_yaml(self, building: str, unit: str, key: str) -> RuntimePath:
        building, unit, key = self._location_parts(building, unit, key)
        relative = PurePosixPath("runtime", "localization", self.community, f"{building}_{unit}", f"{key}.yaml")
        return RuntimePath(relative.as_posix(), (self.LOCALIZATION_ROOT / relative.relative_to("runtime", "localization")).as_posix())

    def map_yaml(self, building: str, unit: str, key: str) -> RuntimePath:
        building, unit, key = self._location_parts(building, unit, key)
        relative = PurePosixPath("runtime", "maps", self.community, f"{building}_{unit}", key, "map.yaml")
        return RuntimePath(relative.as_posix(), (self.MAP_ROOT / relative.relative_to("runtime", "maps")).as_posix())

    @staticmethod
    def _location_parts(building: str, unit: str, key: str) -> tuple[str, str, str]:
        return (
            validate_path_component(building, "楼栋"),
            validate_path_component(unit, "单元"),
            validate_path_component(key, "定位类型"),
        )


def validate_path_component(value: object, label: str) -> str:
    cleaned = " ".join(str(value or "").split())
    if not cleaned or cleaned in {".", ".."}:
        raise LocationManifestError(f"{label}不能为空")
    if "/" in cleaned or "\\" in cleaned or any(ord(char) < 32 for char in cleaned):
        raise LocationManifestError(f"{label}不能包含路径字符")
    if "." in cleaned.split("/"):
        raise LocationManifestError(f"{label}不能包含路径片段")
    return cleaned


_BINDING_TYPES = ("outdoor", "indoor", "ferry", "floor")
_BINDING_ORDER = {value: index for index, value in enumerate(_BINDING_TYPES)}
_IMAGE = re.compile(r"(?m)^\s*image\s*:\s*(\S.*?)\s*$")
_MAP_PATH = re.compile(r"(?m)^\s*map_path\s*:\s*.*$")
_LOCALIZATION_TEMPLATE = Path(__file__).with_name("task_templates") / "indoor_elevator_v1" / "localization_base.yaml"


def compile_location_manifest(
    project: dict[str, Any], *, map_root: Path
) -> RenderedLocationManifest:
    """Render controlled localization files without writing them anywhere.

    All source maps must already be project snapshots below ``map_root``.  The
    returned members are later included in an experimental ZIP; this function
    never invokes ROS and never touches the installer destinations in
    :class:`RuntimePath`.
    """
    if not isinstance(project, dict):
        raise LocationManifestError("部署项目格式无效")
    project_id = validate_path_component(project.get("id"), "项目")
    community = _community(project)
    layout = RuntimeLayout(project_id, community)
    root = Path(map_root).resolve()
    if not root.is_dir():
        raise LocationManifestError("受控地图根目录不存在")
    assets = _assets(project, root)
    bindings = project.get("localization_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise LocationManifestError("缺少定位绑定")
    routes = project.get("localization_routes")
    if not isinstance(routes, list):
        raise LocationManifestError("定位路线无效")
    if not routes:
        if any(
            isinstance(binding, dict) and {"init_go", "init_return"} & set(binding)
            for binding in bindings
        ):
            raise LocationManifestError("定位绑定需要迁移为定位路线")
        raise LocationManifestError("缺少定位路线")
    try:
        localization_template = _LOCALIZATION_TEMPLATE.read_text(encoding="utf-8")
    except OSError as exc:
        raise LocationManifestError("定位基线模板不可用") from exc

    normalized = [_binding(item, assets) for item in bindings]
    _assert_unique(normalized)
    resolved_routes = [_resolve_route(project, route, assets) for route in routes]
    if len({(route["building"], route["unit"]) for route in resolved_routes}) != len(resolved_routes):
        raise LocationManifestError("同一楼栋和单元的定位路线重复")
    resolved_routes.sort(key=lambda route: (route["building"], route["unit"]))
    locations: dict[tuple[str, str], list[dict[str, Any]]] = {}
    artifacts: list[LocationArtifact] = []
    summaries: list[dict[str, str]] = []
    for route in resolved_routes:
        building, unit = route["building"], route["unit"]
        for resolved in route["entries"]:
            binding, asset = resolved["binding"], resolved["asset"]
            key = _runtime_key(binding)
            localization = layout.localization_yaml(building, unit, key)
            map_yaml = layout.map_yaml(building, unit, key)
            artifacts.extend(_map_members(asset, root, map_yaml.relative))
            artifacts.append(
                LocationArtifact(
                    localization.relative,
                    _render_localization(localization_template, str(PurePosixPath(map_yaml.installed).parent)).encode("utf-8"),
                )
            )
            entry: dict[str, Any] = {
                "type": binding["type"],
                "yaml": localization.installed,
                "2D_yaml": map_yaml.installed,
                "init_go": resolved["init_go"],
                "init_return": resolved["init_return"],
            }
            if binding["type"] == "floor":
                entry["floor"] = binding["floor_template"]
            locations.setdefault((building, unit), []).append(entry)
            summaries.append({
                "building": building,
                "unit": unit,
                "type": binding["type"],
                **({"floor_template": binding["floor_template"]} if binding["type"] == "floor" else {}),
            })

    document = {
        "community": community,
        "loc_yaml": [
            {"building": building, "unit": unit, "yaml_index": entries}
            for (building, unit), entries in sorted(locations.items())
        ],
    }
    encoded = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    artifacts.insert(0, LocationArtifact("runtime/loc_yaml_path.json", encoded))
    lift_encoded = (json.dumps(_lift_id_document(project, resolved_routes), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    artifacts.insert(1, LocationArtifact("runtime/lift_id_list.json", lift_encoded))
    return RenderedLocationManifest(encoded, tuple(artifacts), tuple(summaries))


def _community(project: dict[str, Any]) -> str:
    compiler = project.get("task_compiler")
    identity = compiler.get("identity") if isinstance(compiler, dict) else None
    value = identity.get("community") if isinstance(identity, dict) else None
    return validate_path_component(value, "小区")


def _assets(project: dict[str, Any], root: Path) -> dict[str, dict[str, Any]]:
    values = project.get("map_assets")
    if not isinstance(values, list):
        raise LocationManifestError("地图资产无效")
    result: dict[str, dict[str, Any]] = {}
    for asset in values:
        if not isinstance(asset, dict):
            raise LocationManifestError("地图资产无效")
        identifier = str(asset.get("id") or "").strip()
        source_value = asset.get("source_yaml")
        if not identifier or identifier in result or not isinstance(source_value, str):
            raise LocationManifestError("地图资产无效")
        source = Path(source_value).resolve()
        if not source.is_file() or source.suffix.lower() not in {".yaml", ".yml"} or not source.is_relative_to(root):
            raise LocationManifestError("地图源 YAML 必须位于受控地图目录")
        result[identifier] = {
            "source": source,
            "origin": asset.get("origin"),
            "resolution_m": asset.get("resolution_m"),
            "width": asset.get("width"),
            "height": asset.get("height"),
        }
    return result


def _binding(source: object, assets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise LocationManifestError("定位绑定无效")
    map_asset_id = str(source.get("map_asset_id") or "").strip()
    if map_asset_id not in assets:
        raise LocationManifestError("定位绑定引用的地图不存在")
    binding_type = str(source.get("type") or "").strip()
    if binding_type not in _BINDING_TYPES:
        raise LocationManifestError("定位绑定类型无效")
    building = validate_path_component(source.get("building"), "楼栋")
    unit = validate_path_component(source.get("unit"), "单元")
    floor_template = ""
    if binding_type == "floor":
        floor_template = validate_path_component(source.get("floor_template"), "布局模板")
    elif source.get("floor_template") not in (None, ""):
        raise LocationManifestError("仅用户楼层定位绑定可填写布局模板")
    identifier = str(source.get("id") or "").strip()
    if not identifier:
        raise LocationManifestError("定位绑定标识无效")
    return {
        "id": identifier,
        "map_asset_id": map_asset_id,
        "building": building,
        "unit": unit,
        "type": binding_type,
        **({"floor_template": floor_template} if binding_type == "floor" else {}),
    }


def _origin_pose(asset: dict[str, Any]) -> dict[str, float]:
    """Return the map YAML origin in the established runtime pose shape."""
    origin = asset.get("origin")
    if not isinstance(origin, list) or len(origin) != 3:
        raise LocationManifestError("地图 YAML origin 无效")
    try:
        x, y, yaw = (float(value) for value in origin)
    except (TypeError, ValueError) as exc:
        raise LocationManifestError("地图 YAML origin 无效") from exc
    if not all(isfinite(value) for value in (x, y, yaw)):
        raise LocationManifestError("地图 YAML origin 无效")
    return {"x": x, "y": y, "z": 0.0, "yaw": yaw}


def _resolve_route(
    project: dict[str, Any], route: object, assets: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Resolve one persisted route into verified manifest entries and lift anchors."""
    if not isinstance(route, dict):
        raise LocationManifestError("定位路线无效")
    building = validate_path_component(route.get("building"), "楼栋")
    unit = validate_path_component(route.get("unit"), "单元")
    bindings_by_id = {
        item["id"]: item
        for item in (_binding(raw, assets) for raw in project.get("localization_bindings", []))
    }
    binding_ids = route.get("binding_ids")
    if not isinstance(binding_ids, list) or not binding_ids:
        raise LocationManifestError("定位路线缺少绑定")
    normalized_ids = [str(value or "").strip() for value in binding_ids]
    if any(not value for value in normalized_ids) or len(set(normalized_ids)) != len(normalized_ids):
        raise LocationManifestError("定位路线绑定无效")
    try:
        bindings = [bindings_by_id[identifier] for identifier in normalized_ids]
    except KeyError as exc:
        raise LocationManifestError("定位路线引用的绑定不存在") from exc
    if any(item["building"] != building or item["unit"] != unit for item in bindings):
        raise LocationManifestError("定位路线绑定的楼栋或单元不一致")
    if bindings[-1]["type"] != "floor" or any(item["type"] == "floor" for item in bindings[:-1]):
        raise LocationManifestError("定位路线必须以 floor 绑定结束")

    waypoints = _indexed_items(project.get("waypoints"), "Waypoint")
    components = _indexed_items(project.get("components"), "组件")
    start = _route_waypoint(route.get("task_start_waypoint_id"), waypoints, bindings[0], "任务起点")
    target = _route_waypoint(route.get("task_target_waypoint_id"), waypoints, bindings[-1], "任务目标")
    links = route.get("links")
    if not isinstance(links, list) or len(links) != len(bindings) - 1:
        raise LocationManifestError("定位路线链接无效")

    entries: list[dict[str, Any]] = []
    elevator_anchors: list[dict[str, Any]] = []
    for index, binding in enumerate(bindings):
        asset = assets[binding["map_asset_id"]]
        init_go = start if index == 0 else _origin_pose(asset)
        _validate_pose(asset, init_go, "定位初始化位")
        if index == len(bindings) - 1:
            init_return = target
        else:
            init_return, elevator = _route_anchor(
                links[index], binding, bindings[index + 1], assets, waypoints, components
            )
            if elevator is not None:
                elevator_anchors.append(elevator)
        _validate_pose(asset, init_return, "定位返回位")
        entries.append({
            "binding": binding,
            "asset": asset,
            "init_go": init_go,
            "init_return": init_return,
        })
    return {
        "building": building,
        "unit": unit,
        "entries": entries,
        "elevator_anchors": elevator_anchors,
    }


def _indexed_items(source: object, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(source, list):
        raise LocationManifestError(f"{label} 数据无效")
    result: dict[str, dict[str, Any]] = {}
    for item in source:
        identifier = item.get("id") if isinstance(item, dict) else None
        if not isinstance(identifier, str) or not identifier or identifier in result:
            raise LocationManifestError(f"{label} 数据无效")
        result[identifier] = item
    return result


def _route_waypoint(
    identifier: object, waypoints: dict[str, dict[str, Any]], binding: dict[str, Any], label: str
) -> dict[str, float]:
    waypoint = waypoints.get(str(identifier or "").strip())
    if waypoint is None or waypoint.get("map_asset_id") != binding["map_asset_id"]:
        raise LocationManifestError(f"{label}必须位于对应定位地图")
    return _controlled_pose(waypoint, label)


def _route_anchor(
    link: object,
    binding: dict[str, Any],
    next_binding: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    waypoints: dict[str, dict[str, Any]],
    components: dict[str, dict[str, Any]],
) -> tuple[dict[str, float], dict[str, Any] | None]:
    if not isinstance(link, dict):
        raise LocationManifestError("定位路线链接无效")
    if (
        link.get("from_binding_id") != binding["id"]
        or link.get("to_binding_id") != next_binding["id"]
        or not isinstance(link.get("anchor"), dict)
    ):
        raise LocationManifestError("定位路线链接顺序无效")
    anchor = link["anchor"]
    kind = anchor.get("kind")
    if kind == "waypoint" and set(anchor) == {"kind", "waypoint_id"}:
        waypoint = waypoints.get(str(anchor["waypoint_id"] or "").strip())
        if waypoint is None or waypoint.get("map_asset_id") != binding["map_asset_id"]:
            raise LocationManifestError("切图锚点 Waypoint 必须位于来源地图")
        return _controlled_pose(waypoint, "切图锚点"), None
    if kind == "component_center" and set(anchor) == {"kind", "component_id"}:
        component = components.get(str(anchor["component_id"] or "").strip())
        if component is None or component.get("map_asset_id") != binding["map_asset_id"]:
            raise LocationManifestError("切图锚点组件必须位于来源地图")
        pose = _controlled_pose(component, "切图锚点组件")
        _validate_pose(assets[binding["map_asset_id"]], pose, "切图锚点组件")
        return pose, component if component.get("kind") == "elevator" else None
    raise LocationManifestError("定位路线切图锚点无效")


def _controlled_pose(source: dict[str, Any], label: str) -> dict[str, float]:
    try:
        x, y, yaw = (float(source[key]) for key in ("x", "y", "yaw"))
    except (KeyError, TypeError, ValueError) as exc:
        raise LocationManifestError(f"{label}位姿无效") from exc
    if not all(isfinite(value) for value in (x, y, yaw)):
        raise LocationManifestError(f"{label}位姿无效")
    return {"x": x, "y": y, "z": 0.0, "yaw": yaw}


def _validate_pose(asset: dict[str, Any], pose: dict[str, float], label: str) -> None:
    origin = _origin_pose(asset)
    try:
        resolution, width, height = (
            float(asset[key]) for key in ("resolution_m", "width", "height")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LocationManifestError("地图尺寸或分辨率无效") from exc
    if not all(isfinite(value) for value in (resolution, width, height)) or min(resolution, width, height) <= 0:
        raise LocationManifestError("地图尺寸或分辨率无效")
    if not all(isfinite(value) for value in pose.values()):
        raise LocationManifestError(f"{label}无效")
    maximum_x = origin["x"] + width * resolution
    maximum_y = origin["y"] + height * resolution
    if not origin["x"] <= pose["x"] <= maximum_x or not origin["y"] <= pose["y"] <= maximum_y:
        raise LocationManifestError(f"{label}必须位于地图边界内")


def _lift_id_document(project: dict[str, Any], resolved_routes: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the runtime lift list from elevator anchors actually used by routes."""
    community = _community(project)
    physical = _indexed_items(project.get("physical_elevators", []), "物理电梯")
    identities: dict[str, tuple[str, str]] = {}
    lifts: set[tuple[str, str, str]] = set()
    for route in resolved_routes:
        for component in route["elevator_anchors"]:
            attributes = component.get("attributes")
            physical_id = attributes.get("physical_elevator_id") if isinstance(attributes, dict) else None
            elevator = physical.get(str(physical_id or "").strip())
            if elevator is None:
                raise LocationManifestError("电梯锚点未关联有效物理电梯")
            lift_id = " ".join(str(elevator.get("elevator_id") or "").split())
            if not lift_id:
                raise LocationManifestError("物理电梯编号无效")
            identity = (route["building"], route["unit"])
            previous = identities.setdefault(lift_id, identity)
            if previous != identity:
                raise LocationManifestError("同一电梯编号不能属于多个楼栋或单元")
            lifts.add((lift_id, *identity))
    return {
        "community": community,
        "lifts": [
            {"lift_id": lift_id, "building": building, "unit": unit}
            for lift_id, building, unit in sorted(lifts, key=lambda item: (item[1], item[2], item[0]))
        ],
    }


def _assert_unique(bindings: list[dict[str, Any]]) -> None:
    seen: set[tuple[str, str, str, str]] = set()
    for binding in bindings:
        key = (
            binding["building"], binding["unit"], binding["type"],
            binding.get("floor_template", ""),
        )
        if key in seen:
            raise LocationManifestError(f"{binding['type']} 定位绑定重复")
        seen.add(key)


def _runtime_key(binding: dict[str, Any]) -> str:
    return f"floor-{binding['floor_template']}" if binding["type"] == "floor" else binding["type"]


def _map_members(asset: dict[str, Any], root: Path, target_yaml: str) -> list[LocationArtifact]:
    source = asset["source"]
    try:
        yaml_text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LocationManifestError("无法读取受控地图 YAML") from exc
    match = _IMAGE.search(yaml_text)
    if match is None:
        raise LocationManifestError("地图 YAML 缺少 image")
    image_value = match.group(1).strip().strip('"\'')
    image_candidate = Path(image_value)
    if image_candidate.is_absolute():
        # Absolute source paths are never copied into an export package.
        raise LocationManifestError("地图 YAML 的 image 必须是受控相对路径")
    image = (source.parent / image_candidate).resolve()
    if not image.is_file() or not image.is_relative_to(root):
        raise LocationManifestError("地图 YAML 的 image 指向无效")
    target = PurePosixPath(target_yaml).parent
    return [
        LocationArtifact((target / "map.yaml").as_posix(), yaml_text.encode("utf-8")),
        LocationArtifact((target / image.name).as_posix(), image.read_bytes()),
    ]


def _render_localization(template: str, map_directory: str) -> str:
    if len(_MAP_PATH.findall(template)) != 1:
        raise LocationManifestError("定位基线缺少唯一 system.map_path")
    rendered, count = _MAP_PATH.subn(lambda match: f"  map_path: {map_directory}", template, count=1)
    if count != 1:
        raise LocationManifestError("定位基线缺少唯一 system.map_path")
    return rendered
