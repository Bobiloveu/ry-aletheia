"""Pure, experimental compiler for the approved two-map indoor elevator profile.

This module intentionally has no DeploymentStore, HTTP, ROS or runtime-file
ownership.  It transforms a normalized SiteProject document into in-memory
artifacts so a later store layer can review and persist them beneath the
project-owned export root.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import atan2, cos, isfinite, sin
from pathlib import Path
import io
import json
import re
import zipfile
from typing import Any
from xml.sax.saxutils import escape as xml_escape


PROFILE = "indoor_elevator_v1"
PROFILE_VERSION = 1
DEFAULT_MAP_ROOT = Path("/opt/ry/data/maps")
TEMPLATE_ROOT = Path(__file__).with_name("task_templates") / PROFILE
SPEED_MODES = frozenset({"task_point", "single_point", "elevator_in", "backward", "narrow_point", "slow_point"})
_SAFE_SITE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SAFE_DOOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}\Z")
_SAFE_COMMUNITY = re.compile(r"[^/\\\x00-\x1f]{1,80}\Z")
_TOKEN = re.compile(r"\{\{([A-Z_]+)\}\}")


class CompilationError(ValueError):
    """The project lacks a fact required by this deliberately narrow profile."""


@dataclass(frozen=True)
class Artifact:
    relative_path: str
    content: bytes
    sha256: str


@dataclass(frozen=True)
class CompilationInput:
    community: str
    site_id: str
    building: str
    unit: str
    target_floor: int
    door: str
    lobby_map_url: str
    target_map_url: str


@dataclass(frozen=True)
class CompilationPreview:
    input_sha256: str
    task_json: dict[str, Any]
    artifacts: tuple[Artifact, ...]
    manifest: dict[str, Any]
    derived_points: dict[str, dict[str, float]]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def compile_indoor_elevator(project: dict[str, Any], *, map_root: Path = DEFAULT_MAP_ROOT) -> CompilationPreview:
    """Compile the only approved profile without writing any output to disk."""
    if not isinstance(project, dict):
        raise CompilationError("部署项目格式无效")
    if project.get("scene_model") != "indoor":
        raise CompilationError("第一期仅支持室内两图单电梯场景")

    root = Path(map_root).resolve()
    if not root.is_dir():
        raise CompilationError("受控地图根目录不存在")
    assets = _assets(project)
    stage_assets = _stage_assets(project, assets)
    lobby_asset, target_asset = stage_assets["lobby"], stage_assets["target_floor"]
    site_id = _site_id(lobby_asset, root)
    target_asset["source_path"] = _source_path(target_asset, root)
    lobby_instance = _instance_for(project, lobby_asset["id"], "lobby")
    target_instance = _instance_for(project, target_asset["id"], "target_floor")
    building, unit = _same_building_unit(lobby_instance, target_instance)
    community = _community(project)
    components = _components(project, assets)
    start = _one_component(components, lobby_asset["id"], "start", "大厅起点")
    target = _one_component(components, target_asset["id"], "target", "目标点")
    door = _door(target)
    if "physical_elevators" in project:
        lobby_elevator, target_elevator, physical_elevator = _shared_elevator_pair(
            project, components, lobby_asset["id"], target_asset["id"]
        )
        lobby_physical_floor = _shared_physical_floor(physical_elevator, lobby_instance)
        target_physical_floor = _shared_physical_floor(physical_elevator, target_instance)
    else:
        lobby_elevator, target_elevator = _elevator_pair(components, lobby_asset["id"], target_asset["id"])
        lobby_physical_floor = _physical_floor(lobby_elevator, lobby_instance)
        target_physical_floor = _physical_floor(target_elevator, target_instance)

    _validate_point(lobby_asset, start, "起点")
    _validate_point(target_asset, target, "目标点")
    for elevator, asset, label in ((lobby_elevator, lobby_asset, "大厅电梯"), (target_elevator, target_asset, "目标层电梯")):
        _validate_point(asset, elevator, label)

    lobby_wait, lobby_inward = _wait_point(lobby_elevator)
    target_wait, target_inward = _wait_point(target_elevator)
    _validate_point(lobby_asset, lobby_wait, "大厅候梯点")
    _validate_point(target_asset, target_wait, "目标层候梯点")

    input_value = CompilationInput(
        community=community,
        site_id=site_id,
        building=building,
        unit=unit,
        target_floor=target_physical_floor,
        door=door,
        lobby_map_url=str(lobby_asset["source_path"]),
        target_map_url=str(target_asset["source_path"]),
    )
    derived = {
        "start": _point_dict(start),
        "target": _point_dict(target),
        "lobby_wait": _point_dict(lobby_wait, lobby_inward),
        "lobby_elevator_center": _point_dict(lobby_elevator, lobby_inward),
        "target_wait": _point_dict(target_wait, target_inward),
        "target_elevator_center": _point_dict(target_elevator, target_inward),
    }
    input_sha = _input_hash(project, input_value, derived)
    task_json = _task_json(input_value, derived)
    template_hashes: dict[str, str] = {}
    artifacts: list[Artifact] = []

    task_name = f"{community}_{building}_{unit}_{target_instance['floor']}_{door}.json"
    artifacts.append(_artifact(f"tasks/{task_name}", _task_json_bytes(task_json)))
    xml_values = _xml_values(
        input_value, lobby_asset, target_asset, lobby_physical_floor, target_physical_floor, lobby_elevator, lobby_inward
    )
    xml_names = {
        "start_task.xml": "start_task.xml",
        "task_complete.xml": "task_complete.xml",
        "elevator_in_n_x.xml": f"{building}_{unit}_elevator_in_n_x.xml",
        "elevator_in_x_n.xml": f"{building}_{unit}_elevator_in_x_n.xml",
        "elevator_out_n_x.xml": f"{building}_{unit}_elevator_out_n_x.xml",
        "elevator_out_x_n.xml": f"{building}_{unit}_elevator_out_x_n.xml",
        "close_elevdoor_n.xml": f"{building}_{unit}_close_elevdoor_n.xml",
        "close_elevdoor_x.xml": f"{building}_{unit}_close_elevdoor_x.xml",
    }
    for template_name, output_name in xml_names.items():
        template = _template(template_name)
        template_hashes[template_name] = _sha(template.encode("utf-8"))
        values = dict(xml_values)
        if template_name in {"elevator_in_x_n.xml", "elevator_out_x_n.xml"}:
            values["ORIGIN_FLOOR"] = values["TARGET_ORIGIN_FLOOR"]
        content = _render_xml(template, values).encode("utf-8")
        artifacts.append(_artifact(f"waypoint_tasks/{site_id}/{output_name}", content))

    for stage, asset in (("lobby", lobby_asset), ("target_floor", target_asset)):
        base = _template("localization_base.yaml")
        template_hashes.setdefault("localization_base.yaml", _sha(base.encode("utf-8")))
        yaml_text = _render_localization(base, asset["source_path"].parent)
        artifacts.append(_artifact(f"localization/rycx_loc_livox_{building}_{unit}_{stage}.yaml", yaml_text.encode("utf-8")))

    manifest = {
        "compiler_profile": PROFILE,
        "compiler_version": PROFILE_VERSION,
        "validation_status": "experimental_preview",
        "input_sha256": input_sha,
        "template_sha256": dict(sorted(template_hashes.items())),
        "artifacts": [{"path": item.relative_path, "sha256": item.sha256} for item in artifacts],
        "derived_points": derived,
        "robot_runtime_changed": False,
        "statement": "实验预览：未写入任何机器人运行时文件。",
    }
    return CompilationPreview(input_sha, task_json, tuple(artifacts), manifest, derived)


def bundle_zip(preview: CompilationPreview) -> bytes:
    """Package only compiler-owned relative artifacts plus the manifest."""
    members = list(preview.artifacts) + [_artifact("manifest.json", _json_bytes(preview.manifest))]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in members:
            _safe_archive_path(item.relative_path)
            archive.writestr(item.relative_path, item.content)
    return output.getvalue()


def _assets(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = project.get("map_assets")
    if not isinstance(values, list):
        raise CompilationError("地图资产无效")
    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or raw["id"] in result:
            raise CompilationError("地图资产无效")
        # Keep compilation pure: derived resolved paths must not be written
        # back into the caller's persisted project document.
        result[raw["id"]] = dict(raw)
    return result


def _stage_assets(project: dict[str, Any], assets: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    assignments = project.get("map_stage_assignments")
    if not isinstance(assignments, list):
        raise CompilationError("室内场景必须绑定大厅和目标层地图")
    mapping: dict[str, str] = {}
    for item in assignments:
        if not isinstance(item, dict):
            continue
        stage, asset_id = item.get("stage"), item.get("map_asset_id")
        if stage in {"lobby", "target_floor"} and isinstance(asset_id, str):
            if stage in mapping:
                raise CompilationError("大厅和目标层地图必须各唯一一张")
            mapping[stage] = asset_id
    if set(mapping) != {"lobby", "target_floor"} or mapping["lobby"] == mapping["target_floor"]:
        raise CompilationError("室内场景必须绑定唯一的大厅和目标层地图")
    try:
        return {stage: assets[asset_id] for stage, asset_id in mapping.items()}
    except KeyError as exc:
        raise CompilationError("地图阶段引用不存在的地图资产") from exc


def _site_id(asset: dict[str, Any], root: Path) -> str:
    source = _source_path(asset, root)
    configured = asset.get("site_id")
    if isinstance(configured, str) and _SAFE_SITE_ID.fullmatch(configured):
        asset["source_path"] = source
        return configured
    relative = source.relative_to(root)
    if len(relative.parts) < 2 or not _SAFE_SITE_ID.fullmatch(relative.parts[0]):
        raise CompilationError("地图站点目录无效")
    asset["source_path"] = source
    return relative.parts[0]


def _source_path(asset: dict[str, Any], root: Path) -> Path:
    value = asset.get("source_yaml")
    if not isinstance(value, str) or not value:
        raise CompilationError("地图缺少源 YAML")
    source = Path(value).resolve()
    if source.suffix.lower() not in {".yaml", ".yml"} or not source.is_file() or not source.is_relative_to(root):
        raise CompilationError("地图源 YAML 必须位于受控地图目录")
    return source


def _instance_for(project: dict[str, Any], asset_id: str, stage: str) -> dict[str, Any]:
    values = project.get("map_instances")
    if not isinstance(values, list):
        raise CompilationError("地图实例无效")
    expected_roles = {"lobby"} if stage == "lobby" else {"typical_floor", "floor_override"}
    matches = [item for item in values if isinstance(item, dict) and item.get("map_asset_id") == asset_id and item.get("role") in expected_roles]
    if len(matches) != 1:
        raise CompilationError(f"{stage} 缺少唯一地图实例")
    return matches[0]


def _same_building_unit(lobby: dict[str, Any], target: dict[str, Any]) -> tuple[str, str]:
    values = []
    for item in (lobby, target):
        building, unit = item.get("building"), item.get("unit")
        if not isinstance(building, str) or not building.strip() or not isinstance(unit, str) or not unit.strip():
            raise CompilationError("地图实例缺少楼栋或单元")
        values.append((building.strip(), unit.strip()))
    if values[0] != values[1]:
        raise CompilationError("大厅与目标层必须属于同一楼栋和单元")
    return values[0]


def _community(project: dict[str, Any]) -> str:
    value = project.get("task_compiler", {})
    identity = value.get("identity", {}) if isinstance(value, dict) else {}
    community = " ".join(str(identity.get("community") or "").split()) if isinstance(identity, dict) else ""
    if not _SAFE_COMMUNITY.fullmatch(community) or community in {".", ".."}:
        raise CompilationError("任务编译器缺少有效小区名称")
    return community


def _components(project: dict[str, Any], assets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    values = project.get("components")
    if not isinstance(values, list):
        raise CompilationError("组件数据无效")
    result = []
    for item in values:
        if not isinstance(item, dict) or item.get("map_asset_id") not in assets:
            raise CompilationError("组件地图引用无效")
        result.append(item)
    return result


def _one_component(components: list[dict[str, Any]], asset_id: str, kind: str, label: str) -> dict[str, Any]:
    matches = [item for item in components if item.get("map_asset_id") == asset_id and item.get("kind") == kind]
    if len(matches) != 1:
        raise CompilationError(f"{label}必须恰有一个")
    return matches[0]


def _door(target: dict[str, Any]) -> str:
    attributes = target.get("attributes")
    door = str(attributes.get("door") or "").strip() if isinstance(attributes, dict) else ""
    if not _SAFE_DOOR.fullmatch(door):
        raise CompilationError("目标点缺少有效门牌号")
    return door


def _elevator_pair(components: list[dict[str, Any]], lobby_id: str, target_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    elevators = [item for item in components if item.get("kind") == "elevator"]
    lobby = [item for item in elevators if item.get("map_asset_id") == lobby_id]
    target = [item for item in elevators if item.get("map_asset_id") == target_id]
    if len(elevators) != 2 or len(lobby) != 1 or len(target) != 1:
        raise CompilationError("第一期必须恰有两个同一电梯组件，且大厅和目标层各一个")
    ids = []
    for item in (lobby[0], target[0]):
        attrs = item.get("attributes")
        identifier = str(attrs.get("elevator_id") or "").strip() if isinstance(attrs, dict) else ""
        if not identifier:
            raise CompilationError("同一电梯必须填写电梯编号")
        ids.append(identifier)
    if ids[0] != ids[1]:
        raise CompilationError("同一电梯的编号必须一致")
    return lobby[0], target[0]


def _shared_elevator_pair(
    project: dict[str, Any], components: list[dict[str, Any]], lobby_id: str, target_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Resolve two map-local landings to their one project-level lift."""
    raw = project.get("physical_elevators")
    if not isinstance(raw, list):
        raise CompilationError("物理电梯数据无效")
    elevators = [item for item in components if item.get("kind") == "elevator"]
    lobby = [item for item in elevators if item.get("map_asset_id") == lobby_id]
    target = [item for item in elevators if item.get("map_asset_id") == target_id]
    if len(elevators) != 2 or len(lobby) != 1 or len(target) != 1:
        raise CompilationError("第一期必须恰有两个同一物理电梯落点，且大厅和目标层各一个")
    landing_ids: list[str] = []
    for landing in (lobby[0], target[0]):
        attributes = landing.get("attributes")
        identifier = str(attributes.get("physical_elevator_id") or "").strip() if isinstance(attributes, dict) else ""
        if not identifier:
            raise CompilationError("电梯落点必须关联物理电梯")
        landing_ids.append(identifier)
    if landing_ids[0] != landing_ids[1]:
        raise CompilationError("大厅和目标层必须关联同一物理电梯")
    matches = [item for item in raw if isinstance(item, dict) and item.get("id") == landing_ids[0]]
    if len(matches) != 1:
        raise CompilationError("电梯落点关联的物理电梯不存在")
    physical = matches[0]
    if isinstance(physical.get("migration_conflict"), str) and physical["migration_conflict"].strip():
        raise CompilationError(f"物理电梯旧数据冲突：{physical['migration_conflict']}")
    elevator_id = " ".join(str(physical.get("elevator_id") or "").split())
    protocol = " ".join(str(physical.get("elevator_protocol") or "").split())
    if not elevator_id or not protocol:
        raise CompilationError("物理电梯缺少编号或梯控协议")
    return lobby[0], target[0], physical


def _number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CompilationError(f"{label}无效") from exc
    if not isfinite(number) or abs(number) >= 1e7:
        raise CompilationError(f"{label}无效")
    return number


def _point_dict(component: dict[str, Any], yaw: float | None = None) -> dict[str, float]:
    return {"x": _number(component.get("x"), "组件坐标"), "y": _number(component.get("y"), "组件坐标"), "yaw": _number(component.get("yaw") if yaw is None else yaw, "组件朝向")}


def _validate_point(asset: dict[str, Any], point: dict[str, Any], label: str) -> None:
    value = _point_dict(point)
    try:
        origin = asset["origin"]
        min_x, min_y = float(origin[0]), float(origin[1])
        maximum_x = min_x + float(asset["width"]) * float(asset["resolution_m"])
        maximum_y = min_y + float(asset["height"]) * float(asset["resolution_m"])
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise CompilationError("地图尺寸元数据无效") from exc
    if not (min_x <= value["x"] <= maximum_x and min_y <= value["y"] <= maximum_y):
        raise CompilationError(f"{label}位于地图边界外")


def _wait_point(elevator: dict[str, Any]) -> tuple[dict[str, float], float]:
    center = _point_dict(elevator)
    attrs = elevator.get("attributes") if isinstance(elevator.get("attributes"), dict) else {}
    height = _number(attrs.get("height_m"), "电梯门向尺寸")
    wait_distance = _number(attrs.get("wait_distance_m", 1.5), "候梯距离")
    if not 0 < height <= 20 or not 0.5 <= wait_distance <= 5:
        raise CompilationError("电梯尺寸或候梯距离超出允许范围")
    door_out_x, door_out_y = -sin(center["yaw"]), cos(center["yaw"])
    inward_yaw = atan2(-door_out_y, -door_out_x)
    distance = height / 2 + wait_distance
    return {"x": center["x"] + door_out_x * distance, "y": center["y"] + door_out_y * distance, "yaw": inward_yaw}, inward_yaw


def _physical_floor(elevator: dict[str, Any], instance: dict[str, Any]) -> int:
    attrs = elevator.get("attributes") if isinstance(elevator.get("attributes"), dict) else {}
    value = attrs.get("physical_floor")
    try:
        map_floor = int(attrs.get("map_floor"))
        expected_physical = map_floor + 1
        floor = int(value) if value is not None else expected_physical
        logical_floor = int(instance.get("floor"))
    except (TypeError, ValueError) as exc:
        raise CompilationError("电梯或地图实例缺少有效楼层") from exc
    if not -19 <= floor <= 121 or logical_floor < -20 or logical_floor > 120:
        raise CompilationError("电梯楼层超出允许范围")
    if map_floor != logical_floor or floor != expected_physical:
        raise CompilationError("电梯楼层必须与所属地图实例一致")
    return floor


def _shared_physical_floor(physical_elevator: dict[str, Any], instance: dict[str, Any]) -> int:
    try:
        logical_floor = int(instance.get("floor"))
        minimum = int(physical_elevator.get("min_floor"))
        maximum = int(physical_elevator.get("max_floor"))
    except (TypeError, ValueError) as exc:
        raise CompilationError("物理电梯或地图实例缺少有效楼层") from exc
    if not -20 <= minimum <= maximum <= 120 or not -20 <= logical_floor <= 120:
        raise CompilationError("电梯服务楼层范围无效")
    if not minimum <= logical_floor <= maximum:
        raise CompilationError("当前地图楼层不在物理电梯服务楼层范围内")
    return logical_floor + 1


def _pose(point: dict[str, float]) -> dict[str, dict[str, float]]:
    yaw = point["yaw"]
    return {"position": {"x": point["x"], "y": point["y"], "z": 0.0}, "orientation": {"x": 0.0, "y": 0.0, "z": sin(yaw / 2), "w": cos(yaw / 2)}}


def _waypoint(identifier: str, point: dict[str, float], speed_mode: str, task_id: str = "", *, is_task_point: bool = True) -> dict[str, Any]:
    if speed_mode not in SPEED_MODES:
        raise CompilationError("速度模式不在批准列表中")
    return {"waypoint_task_id": task_id, "is_task_point": is_task_point, "speed_mode": speed_mode, "is_backward": False, "is_single_point": True, "pose": _pose(point), "waypoint_id": identifier}


def _task_json(value: CompilationInput, points: dict[str, dict[str, float]]) -> dict[str, Any]:
    b, u = value.building, value.unit
    return {
        "subtasks": [
            {"change_loc": False, "map_url": value.lobby_map_url, "pcd_url": "", "subtask_name": "elevator_hall", "waypoints": [
                _waypoint("lobby_start", points["start"], "task_point", "start_task", is_task_point=False),
                _waypoint("lobby_wait", points["lobby_wait"], "single_point", f"{b}_{u}_elevator_in_n_x"),
                _waypoint("lobby_elevator_center", points["lobby_elevator_center"], "elevator_in", f"{b}_{u}_elevator_out_n_x"),
            ]},
            {"change_loc": False, "map_url": value.target_map_url, "pcd_url": "", "subtask_name": value.door, "waypoints": [
                _waypoint("target_wait", points["target_wait"], "backward", f"{b}_{u}_close_elevdoor_x"),
                _waypoint("target", points["target"], "single_point", "place_water"),
            ]},
            {"change_loc": False, "map_url": value.target_map_url, "pcd_url": "", "subtask_name": f"{value.door}_r", "waypoints": [
                _waypoint("target_return_origin", points["target"], "single_point"),
                _waypoint("target_return_wait", points["target_wait"], "task_point", f"{b}_{u}_elevator_in_x_n"),
                _waypoint("target_return_elevator_center", points["target_elevator_center"], "elevator_in", f"{b}_{u}_elevator_out_x_n"),
            ]},
            {"change_loc": False, "map_url": value.lobby_map_url, "pcd_url": "", "subtask_name": "elevator_hall_r", "waypoints": [
                _waypoint("lobby_return_wait", points["lobby_wait"], "backward", f"{b}_{u}_close_elevdoor_n"),
                _waypoint("lobby_return_start", points["start"], "single_point", "task_complete"),
            ]},
        ],
        # The verified task-editor sample keeps the unit in the filename but
        # omits it from task_group_name.
        "task_group_name": f"{value.community}_{value.building}_{value.target_floor - 1}_{value.door}",
    }


def _xml_values(value: CompilationInput, lobby_asset: dict[str, Any], target_asset: dict[str, Any], lobby_floor: int, target_floor: int, lobby: dict[str, Any], lobby_inward: float) -> dict[str, str]:
    config_root = f"/opt/ry/config/localization/config/{value.site_id.upper()}"
    localization = {
        "lobby": f"{config_root}/rycx_loc_livox_{value.building}_{value.unit}_lobby.yaml",
        "target": f"{config_root}/rycx_loc_livox_{value.building}_{value.unit}_target_floor.yaml",
    }
    return {
        "ORIGIN_FLOOR": str(lobby_floor),
        "TARGET_LOCALIZATION_YAML": localization["target"],
        "TARGET_MAP_YAML": str(target_asset["source_path"]),
        "SOURCE_LOCALIZATION_YAML": localization["lobby"],
        "RELOCALIZE_X": _format_number(_number(lobby.get("x"), "大厅电梯坐标")),
        "RELOCALIZE_Y": _format_number(_number(lobby.get("y"), "大厅电梯坐标")),
        "RELOCALIZE_YAW": _format_number(lobby_inward),
        "TARGET_ORIGIN_FLOOR": str(target_floor),
    }


def _template(name: str) -> str:
    if name not in {"localization_base.yaml", "start_task.xml", "task_complete.xml", "elevator_in_n_x.xml", "elevator_in_x_n.xml", "elevator_out_n_x.xml", "elevator_out_x_n.xml", "close_elevdoor_n.xml", "close_elevdoor_x.xml"}:
        raise CompilationError("未批准的行为树模板")
    path = TEMPLATE_ROOT / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CompilationError(f"受控模板不可用：{name}") from exc


def _render_xml(template: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in values:
            raise CompilationError(f"行为树模板包含未批准的替换标记：{token}")
        return xml_escape(values[token], {'"': "&quot;"})
    rendered = _TOKEN.sub(replace, template)
    if "{{" in rendered or "}}" in rendered:
        raise CompilationError("行为树模板包含未解析替换标记")
    return rendered


def _render_localization(template: str, map_directory: Path) -> str:
    matches = list(re.finditer(r"(?m)^\s*map_path:\s*.*$", template))
    if len(matches) != 1:
        raise CompilationError("定位基线缺少唯一 system.map_path")
    updated, count = re.subn(r"(?m)^(\s*map_path:\s*).*$", lambda match: f"{match.group(1)}{map_directory}", template, count=1)
    if count != 1:
        raise CompilationError("定位基线缺少唯一 system.map_path")
    return updated


def _input_hash(project: dict[str, Any], value: CompilationInput, derived: dict[str, dict[str, float]]) -> str:
    payload = {"profile": PROFILE, "input": value.__dict__, "scene_model": project.get("scene_model"), "components": project.get("components"), "physical_elevators": project.get("physical_elevators"), "map_assets": project.get("map_assets"), "map_instances": project.get("map_instances"), "map_stage_assignments": project.get("map_stage_assignments"), "derived": derived}
    return _sha(_json_bytes(payload))


def _artifact(relative_path: str, content: bytes) -> Artifact:
    _safe_archive_path(relative_path)
    return Artifact(relative_path, content, _sha(content))


def _safe_archive_path(relative_path: str) -> None:
    path = Path(relative_path)
    if not relative_path or path.is_absolute() or ".." in path.parts or path.parts[0] not in {"tasks", "waypoint_tasks", "localization", "manifest.json"}:
        raise CompilationError("导出文件路径无效")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _task_json_bytes(value: dict[str, Any]) -> bytes:
    """Match the readable, field-ordered task JSON used by the task editor."""
    return (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _format_number(value: float) -> str:
    return format(value, ".12g")
