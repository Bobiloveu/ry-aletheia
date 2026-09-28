"""Validated, deterministic ``map_walls.yaml`` support for deployment maps."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import hypot, isfinite
from typing import Any

import yaml


class VirtualWallError(ValueError):
    """Raised when virtual-wall data cannot safely describe line segments."""


_MAX_WALL_FILE_BYTES = 2 * 1024 * 1024
_SUPPORTED_COORDINATE_MODES = frozenset({"world", "image_relative"})
_THICKNESS_M = 0.1


def validate_segment(
    start: Mapping[str, object], end: Mapping[str, object]
) -> dict[str, dict[str, float]]:
    """Return one finite, non-zero world-coordinate wall segment."""
    cleaned_start = _point(start, "起点")
    cleaned_end = _point(end, "终点")
    if hypot(
        cleaned_end["x"] - cleaned_start["x"],
        cleaned_end["y"] - cleaned_start["y"],
    ) <= 1e-9:
        raise VirtualWallError("虚拟墙起点和终点不能重合")
    return {"start": cleaned_start, "end": cleaned_end}


def validate_polyline(points: object) -> list[dict[str, float]]:
    """Return finite, non-overlapping adjacent vertices for one wall line."""
    if isinstance(points, (str, bytes)) or not isinstance(points, Sequence) or len(points) < 2:
        raise VirtualWallError("虚拟墙至少需要两个点")
    cleaned = [_point(point, "点位") for point in points]
    for start, end in zip(cleaned, cleaned[1:]):
        if hypot(end["x"] - start["x"], end["y"] - start["y"]) <= 1e-9:
            raise VirtualWallError("虚拟墙相邻点不能重合")
    return cleaned


def polyline_segments(points: object) -> list[dict[str, dict[str, float]]]:
    """Split a validated polyline into runtime-compatible wall segments."""
    cleaned = validate_polyline(points)
    return [validate_segment(start, end) for start, end in zip(cleaned, cleaned[1:])]


def parse_virtual_wall_segments(
    contents: bytes, origin: Sequence[float]
) -> list[dict[str, dict[str, float]]]:
    """Read supported wall YAML and return validated world-coordinate segments."""
    if not isinstance(contents, bytes) or len(contents) > _MAX_WALL_FILE_BYTES:
        raise VirtualWallError("虚拟墙文件无效或超过 2 MiB 限制")
    base_x, base_y, _ = _origin(origin)
    try:
        document = yaml.safe_load(contents.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise VirtualWallError("虚拟墙 YAML 无法解析") from exc
    if not isinstance(document, dict):
        raise VirtualWallError("虚拟墙 YAML 根节点无效")
    walls = document.get("virtual_walls")
    if not isinstance(walls, dict):
        raise VirtualWallError("虚拟墙 YAML 缺少 virtual_walls")
    mode = str(walls.get("coordinate_mode") or "world").strip().lower()
    if mode not in _SUPPORTED_COORDINATE_MODES:
        raise VirtualWallError("虚拟墙坐标模式必须是 world 或 image_relative")
    raw_segments = walls.get("segments", [])
    if not isinstance(raw_segments, list):
        raise VirtualWallError("虚拟墙 segments 必须是数组")

    result: list[dict[str, dict[str, float]]] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, dict):
            raise VirtualWallError("虚拟墙线段无效")
        start = _yaml_point(raw_segment.get("start"), "起点")
        end = _yaml_point(raw_segment.get("end"), "终点")
        if mode == "image_relative":
            start = {"x": start["x"] + base_x, "y": start["y"] + base_y}
            end = {"x": end["x"] + base_x, "y": end["y"] + base_y}
        result.append(validate_segment(start, end))
    return result


def render_virtual_wall_file(
    origin: Sequence[float], segments: Sequence[Mapping[str, Mapping[str, object]]]
) -> bytes:
    """Render the robot-compatible companion file with relative endpoints."""
    origin_x, origin_y, origin_yaw = _origin(origin)
    rendered_segments = []
    for segment in segments:
        if not isinstance(segment, Mapping):
            raise VirtualWallError("虚拟墙线段无效")
        cleaned = validate_segment(
            _mapping(segment.get("start"), "起点"),
            _mapping(segment.get("end"), "终点"),
        )
        rendered_segments.append(
            {
                "start": [
                    cleaned["start"]["x"] - origin_x,
                    cleaned["start"]["y"] - origin_y,
                    0.0,
                ],
                "end": [
                    cleaned["end"]["x"] - origin_x,
                    cleaned["end"]["y"] - origin_y,
                    0.0,
                ],
                "thickness": _THICKNESS_M,
            }
        )
    document = {
        "virtual_walls": {
            "coordinate_mode": "image_relative",
            "frame_id": "map",
            "map_origin": [origin_x, origin_y, origin_yaw],
            "thickness": _THICKNESS_M,
            "segments": rendered_segments,
        }
    }
    return yaml.safe_dump(
        document, allow_unicode=True, default_flow_style=False, sort_keys=False
    ).encode("utf-8")


def _origin(origin: Sequence[float]) -> tuple[float, float, float]:
    if isinstance(origin, (str, bytes)) or not isinstance(origin, Sequence) or len(origin) < 3:
        raise VirtualWallError("地图 origin 无效")
    values = tuple(_number(value, "地图 origin") for value in origin[:3])
    return values[0], values[1], values[2]


def _yaml_point(value: object, label: str) -> dict[str, float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) < 2:
        raise VirtualWallError(f"虚拟墙{label}无效")
    return {"x": _number(value[0], f"虚拟墙{label}"), "y": _number(value[1], f"虚拟墙{label}")}


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise VirtualWallError(f"虚拟墙{label}无效")
    return value


def _point(value: Mapping[str, object] | object, label: str) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise VirtualWallError(f"虚拟墙{label}无效")
    return {
        "x": _number(value.get("x"), f"虚拟墙{label}"),
        "y": _number(value.get("y"), f"虚拟墙{label}"),
    }


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise VirtualWallError(f"{label}坐标必须是有限数值")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise VirtualWallError(f"{label}坐标必须是有限数值") from exc
    if not isfinite(number):
        raise VirtualWallError(f"{label}坐标必须是有限数值")
    return number
