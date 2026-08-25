from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class MapAssetError(ValueError):
    """任务引用的地图无法安全地加入轨迹功能缓存。"""


@dataclass(frozen=True)
class CachedMapAsset:
    id: str
    label: str
    source_yaml: str
    cache_yaml: str
    cache_image: str
    resolution: float | None
    origin: list[float] | None
    width: int | None
    height: int | None
    cache_walls: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MapAssetCache:
    """缓存任务引用的离线地图，或运行时从 ROS2 /map 得到的实际地图。"""

    ALLOWED_ROOTS = (Path("/opt/ry/data/maps"),)
    _IMAGE = re.compile(r"^(?P<prefix>\s*image\s*:\s*)(?P<value>.+?)\s*$")
    _RESOLUTION = re.compile(r"^\s*resolution\s*:\s*(?P<value>[-+0-9.eE]+)\s*$")
    _ORIGIN = re.compile(r"^\s*origin\s*:\s*\[(?P<value>[^]]+)\]\s*$")

    def __init__(self, cache_dir: Path, allowed_roots: tuple[Path, ...] | None = None) -> None:
        self.cache_dir = cache_dir
        self.allowed_roots = tuple(root.resolve() for root in (allowed_roots or self.ALLOWED_ROOTS))

    def prepare(self, task_source: str) -> list[CachedMapAsset]:
        source = Path(task_source)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MapAssetError(f"无法读取任务地图引用：{exc}") from exc
        map_urls = self._find_map_urls(payload)
        # map_url 是离线预览的辅助信息，不能作为任务执行或轨迹采集的硬前提。
        # 实际运行时会以 ROS2 /map 为准；这里仅尽力缓存仍然有效的本地引用。
        assets: list[CachedMapAsset] = []
        for url in map_urls:
            try:
                assets.append(self._cache_one(Path(url)))
            except MapAssetError:
                continue
        return assets

    def find_matching_map(
        self, *, resolution: float, width: int, height: int, origin: list[float],
    ) -> CachedMapAsset | None:
        """安全定位与当前 ``/map`` 元数据一致的本地地图。

        实时观测页只把 OccupancyGrid 的小型元数据交给后端，绝不回传整张地图。
        这里仅在首次打开或地图切换时扫描受控地图根目录，用于取得同目录的
        ``map_walls.yaml``。若有多个地图元数据相同，宁可拒绝匹配也不叠加错误
        的虚拟墙。
        """
        if not (resolution > 0 and width > 0 and height > 0) or len(origin) < 2:
            raise MapAssetError("实时地图元数据无效")
        matches: list[CachedMapAsset] = []
        for root in self.allowed_roots:
            if not root.is_dir():
                continue
            try:
                candidates = root.rglob("*.yaml")
                for candidate in candidates:
                    try:
                        if not candidate.resolve().is_relative_to(root):
                            continue
                        # 只读地图 YAML 的头部字段；map_walls 等非地图 YAML 会自然跳过。
                        text = candidate.read_text(encoding="utf-8")
                        image_value, candidate_resolution, candidate_origin = self._parse_metadata(text)
                        if not image_value or candidate_resolution is None or candidate_origin is None:
                            continue
                        if not self._metadata_matches(
                            resolution, width, height, origin,
                            candidate_resolution, candidate_origin, candidate,
                        ):
                            continue
                        matches.append(self._cache_one(candidate))
                    except (OSError, UnicodeDecodeError, MapAssetError, ValueError):
                        continue
            except OSError:
                continue
        # 相同几何元数据的不同地图绝不能互认：那会把另一楼层/场景的虚拟墙
        # 叠到当前地图。实车上 gk1 与 gk1_ele_test 的 P2 是一个例外：两个目录
        # 是发布历史留下的镜像副本，底图和墙文件逐字节相同。只在 *每个* 候选
        # 都有墙文件且两份内容完全相同时，把它们视为同一个安全候选；没有墙
        # 或任一文件不同仍按歧义拒绝。
        if len(matches) == 1:
            return matches[0]
        equivalents: dict[tuple[str, str], CachedMapAsset] = {}
        for asset in matches:
            if not asset.cache_walls:
                return None
            try:
                identity = (self._file_sha256(Path(asset.cache_image)), self._file_sha256(Path(asset.cache_walls)))
            except OSError:
                return None
            equivalents.setdefault(identity, asset)
        return next(iter(equivalents.values())) if len(equivalents) == 1 else None

    def _metadata_matches(
        self,
        resolution: float, width: int, height: int, origin: list[float],
        candidate_resolution: float, candidate_origin: list[float], candidate: Path,
    ) -> bool:
        if abs(resolution - candidate_resolution) > max(1e-9, abs(resolution) * 1e-6):
            return False
        try:
            image_value, _, _ = MapAssetCache._parse_metadata(candidate.read_text(encoding="utf-8"))
            image = Path(image_value or "")
            if not image.is_absolute():
                image = candidate.parent / image
            image = image.resolve()
            if not any(image.is_relative_to(root) for root in self.allowed_roots):
                return False
            candidate_width, candidate_height = MapAssetCache._pgm_dimensions(image)
        except OSError:
            return False
        if candidate_width != width or candidate_height != height:
            return False
        # 地图原点由 map_server 原样带出；允许极小 YAML 浮点格式差异，绝不放宽到
        # 一个栅格以上，避免同尺寸不同地图互相误认。
        tolerance = max(1e-6, resolution * 1e-3)
        return abs(float(origin[0]) - float(candidate_origin[0])) <= tolerance and abs(float(origin[1]) - float(candidate_origin[1])) <= tolerance

    def cache_occupancy_grid(
        self, *, resolution: float, width: int, height: int, origin: list[float], frame_id: str,
        data: list[int] | tuple[int, ...], label: str | None = None, wall_source: CachedMapAsset | None = None,
    ) -> CachedMapAsset:
        """把 ROS2 ``nav_msgs/OccupancyGrid`` 缓存为可离线渲染的 PGM/YAML。

        OccupancyGrid 的数据原点在左下，而 PGM 首行对应图像上方；写入时逐行翻转，
        保证世界坐标、轨迹和底图严格一致。此方法不依赖 ROS2，方便独立验证。
        """
        if not (resolution > 0 and width > 0 and height > 0):
            raise MapAssetError("ROS2 /map 元数据无效")
        if len(data) != width * height:
            raise MapAssetError(f"ROS2 /map 栅格长度无效：期望 {width * height}，实际 {len(data)}")
        if len(origin) < 2:
            raise MapAssetError("ROS2 /map 缺少地图原点")
        pixels = bytearray(width * height)
        for row in range(height):
            source_offset = (height - 1 - row) * width
            target_offset = row * width
            for column in range(width):
                value = int(data[source_offset + column])
                if value < 0:
                    pixels[target_offset + column] = 205
                elif value >= 65:
                    pixels[target_offset + column] = 0
                elif value <= 25:
                    pixels[target_offset + column] = 254
                else:
                    pixels[target_offset + column] = round(254 * (100 - value) / 100)
        metadata = f"{resolution:.12g}|{width}|{height}|{float(origin[0]):.12g}|{float(origin[1]):.12g}|{frame_id}".encode("utf-8")
        asset_id = hashlib.sha256(metadata + pixels).hexdigest()[:16]
        target_dir = self.cache_dir / asset_id
        target_dir.mkdir(parents=True, exist_ok=True)
        image_target = target_dir / "map.pgm"
        yaml_target = target_dir / "map.yaml"
        self._write_bytes_if_changed(image_target, f"P5\n{width} {height}\n255\n".encode("ascii") + pixels)
        self._write_if_changed(yaml_target, f"image: map.pgm\nresolution: {resolution:.12g}\norigin: [{float(origin[0]):.12g}, {float(origin[1]):.12g}, 0.0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n")
        walls_target = None
        if wall_source and wall_source.cache_walls and Path(wall_source.cache_walls).is_file():
            walls_target = target_dir / "map_walls.yaml"
            self._copy_if_changed(Path(wall_source.cache_walls), walls_target)
        return CachedMapAsset(
            id=asset_id, label=label or (wall_source.label if wall_source else f"ROS 地图 {asset_id[:6]}"),
            source_yaml=f"ros2:///map/{asset_id}", cache_yaml=str(yaml_target), cache_image=str(image_target),
            resolution=float(resolution), origin=[float(origin[0]), float(origin[1]), 0.0], width=width, height=height,
            cache_walls=str(walls_target) if walls_target else None,
        )

    @staticmethod
    def ideal_routes(task_source: str, assets: list[CachedMapAsset]) -> dict[str, list[dict[str, Any]]]:
        """提取每个子任务的路点序列，保留子任务边界以免错误跨段连线。"""
        try:
            payload = json.loads(Path(task_source).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MapAssetError(f"无法读取任务理想路线：{exc}") from exc
        source_to_id = {str(Path(asset.source_yaml).resolve()): asset.id for asset in assets}
        routes: dict[str, list[dict[str, Any]]] = {}
        for index, subtask in enumerate(payload.get("subtasks", []) if isinstance(payload, dict) else []):
            if not isinstance(subtask, dict) or not isinstance(subtask.get("map_url"), str):
                continue
            try:
                map_id = source_to_id.get(str(Path(subtask["map_url"]).resolve()))
            except OSError:
                map_id = None
            if not map_id:
                continue
            points = []
            for waypoint in subtask.get("waypoints", []):
                try:
                    position = waypoint["pose"]["position"]
                    points.append({"x": float(position["x"]), "y": float(position["y"])})
                except (KeyError, TypeError, ValueError):
                    continue
            if points:
                routes.setdefault(map_id, []).append({"name": str(subtask.get("subtask_name") or f"子任务 {index + 1}"), "points": points})
        return routes

    @staticmethod
    def route_plan(task_source: str, assets: list[CachedMapAsset]) -> list[dict[str, Any]]:
        """按子任务边界返回理想路径，绝不凭空连接相邻子任务。"""
        try:
            payload = json.loads(Path(task_source).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MapAssetError(f"无法读取任务路线：{exc}") from exc
        source_to_asset = {str(Path(asset.source_yaml).resolve()): asset for asset in assets}
        plan = []
        for index, subtask in enumerate(payload.get("subtasks", []) if isinstance(payload, dict) else []):
            if not isinstance(subtask, dict):
                continue
            map_url = subtask.get("map_url")
            try:
                asset = source_to_asset.get(str(Path(map_url).resolve())) if isinstance(map_url, str) else None
            except OSError:
                asset = None
            points = []
            for waypoint in subtask.get("waypoints", []):
                try:
                    position = waypoint["pose"]["position"]
                    points.append({"x": float(position["x"]), "y": float(position["y"])})
                except (KeyError, TypeError, ValueError):
                    continue
            map_id = asset.id if asset else None
            map_label = asset.label if asset else "ROS2 当前地图"
            if len(points) >= 2:
                plan.append({"map_id": map_id, "map_label": map_label, "name": str(subtask.get("subtask_name") or f"子任务 {index + 1}"), "points": points})
        return plan

    @staticmethod
    def ideal_routes_from_plan(route_plan: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """按运行时已经绑定的地图 ID 整理理想路线。"""
        routes: dict[str, list[dict[str, Any]]] = {}
        for route in route_plan:
            map_id, points = route.get("map_id"), route.get("points")
            if not isinstance(map_id, str) or not isinstance(points, list) or len(points) < 2:
                continue
            routes.setdefault(map_id, []).append({"name": str(route.get("name") or "子任务"), "points": points})
        return routes

    @staticmethod
    def virtual_walls(asset: CachedMapAsset) -> list[dict[str, Any]]:
        """读取同地图目录的 map_walls.yaml，兼容本车 segments 与常见点定义。"""
        if not asset.cache_walls:
            return []
        try:
            contents = Path(asset.cache_walls).read_text(encoding="utf-8")
        except OSError:
            return []
        coordinate_mode = "world"
        if match := re.search(r"(?im)^\s*coordinate_mode\s*:\s*([\w-]+)\s*$", contents):
            coordinate_mode = match.group(1).lower()
        segments = MapAssetCache._segment_walls(contents)
        if segments:
            return [{"points": points, "coordinate_mode": coordinate_mode} for points in segments]
        points = MapAssetCache._wall_points(contents)
        return [{"points": points[index:index + 2], "coordinate_mode": coordinate_mode} for index in range(0, len(points) - 1, 2)]

    @staticmethod
    def _segment_walls(contents: str) -> list[list[dict[str, float]]]:
        number = r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
        pattern = re.compile(
            rf"(?ms)^\s*-\s+start:\s*\n\s*-\s*(?P<sx>{number})\s*\n\s*-\s*(?P<sy>{number})\s*\n.*?^\s*end:\s*\n\s*-\s*(?P<ex>{number})\s*\n\s*-\s*(?P<ey>{number})\s*\n"
        )
        return [[{"x": float(match.group("sx")), "y": float(match.group("sy"))}, {"x": float(match.group("ex")), "y": float(match.group("ey"))}] for match in pattern.finditer(contents)]

    @staticmethod
    def _wall_points(contents: str) -> list[dict[str, float]]:
        fields = re.findall(r"(?i)\b([xy])\s*:\s*(-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)", contents)
        points: list[dict[str, float]] = []
        current: dict[str, float] = {}
        for key, value in fields:
            if key.lower() == "x" and "x" in current:
                current = {}
            current[key.lower()] = float(value)
            if "x" in current and "y" in current:
                points.append(current)
                current = {}
        if points:
            return points
        # 有些地图使用二维数组：[[x1, y1], [x2, y2]]。
        pairs = re.findall(r"\[\s*(-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*,\s*(-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*\]", contents)
        return [{"x": float(x), "y": float(y)} for x, y in pairs]

    @staticmethod
    def _find_map_urls(value: Any) -> list[str]:
        found: list[str] = []
        if isinstance(value, dict):
            candidate = value.get("map_url")
            if isinstance(candidate, str) and candidate.strip() and candidate not in found:
                found.append(candidate)
            for child in value.values():
                found.extend(url for url in MapAssetCache._find_map_urls(child) if url not in found)
        elif isinstance(value, list):
            for child in value:
                found.extend(url for url in MapAssetCache._find_map_urls(child) if url not in found)
        return found

    def _cache_one(self, map_yaml: Path) -> CachedMapAsset:
        yaml_path = self._trusted_file(map_yaml, "地图 YAML")
        yaml_text = yaml_path.read_text(encoding="utf-8")
        image_value, resolution, origin = self._parse_metadata(yaml_text)
        if not image_value:
            raise MapAssetError(f"地图 YAML 缺少 image 字段：{yaml_path}")
        image_path = Path(image_value)
        if not image_path.is_absolute():
            image_path = yaml_path.parent / image_path
        image_path = self._trusted_file(image_path, "地图图像")

        asset_id = hashlib.sha256(str(yaml_path).encode("utf-8")).hexdigest()[:16]
        target_dir = self.cache_dir / asset_id
        target_yaml = target_dir / "map.yaml"
        target_image = target_dir / image_path.name
        wall_path = yaml_path.with_name("map_walls.yaml")
        target_walls = target_dir / "map_walls.yaml"
        target_dir.mkdir(parents=True, exist_ok=True)
        self._copy_if_changed(image_path, target_image)
        rewritten_yaml = self._rewrite_image_path(yaml_text, image_path.name)
        self._write_if_changed(target_yaml, rewritten_yaml)
        has_walls = wall_path.is_file()
        if has_walls:
            self._copy_if_changed(self._trusted_file(wall_path, "虚拟墙 YAML"), target_walls)
        width, height = self._pgm_dimensions(image_path)
        return CachedMapAsset(
            id=asset_id,
            label=yaml_path.parent.name,
            source_yaml=str(yaml_path),
            cache_yaml=str(target_yaml),
            cache_image=str(target_image),
            resolution=resolution,
            origin=origin,
            width=width,
            height=height,
            cache_walls=str(target_walls) if has_walls else None,
        )

    def _trusted_file(self, path: Path, description: str) -> Path:
        resolved = path.resolve()
        if not any(resolved.is_relative_to(root) for root in self.allowed_roots):
            raise MapAssetError(f"{description}不在允许目录内：{path}")
        if not resolved.is_file():
            raise MapAssetError(f"{description}不存在：{path}")
        return resolved

    @classmethod
    def _parse_metadata(cls, yaml_text: str) -> tuple[str | None, float | None, list[float] | None]:
        image: str | None = None
        resolution: float | None = None
        origin: list[float] | None = None
        for raw_line in yaml_text.splitlines():
            line = raw_line.split("#", 1)[0].rstrip()
            if match := cls._IMAGE.match(line):
                image = match.group("value").strip().strip("\"'")
            elif match := cls._RESOLUTION.match(line):
                resolution = float(match.group("value"))
            elif match := cls._ORIGIN.match(line):
                try:
                    origin = [float(item.strip()) for item in match.group("value").split(",")]
                except ValueError as exc:
                    raise MapAssetError("地图 YAML 的 origin 格式无效") from exc
        return image, resolution, origin

    @classmethod
    def _rewrite_image_path(cls, yaml_text: str, image_name: str) -> str:
        lines = []
        replaced = False
        for raw_line in yaml_text.splitlines():
            if not replaced and (match := cls._IMAGE.match(raw_line.split("#", 1)[0].rstrip())):
                lines.append(f"{match.group('prefix')}{image_name}")
                replaced = True
            else:
                lines.append(raw_line)
        return "\n".join(lines) + "\n"

    @staticmethod
    def _copy_if_changed(source: Path, target: Path) -> None:
        if target.exists() and target.stat().st_size == source.stat().st_size and target.stat().st_mtime_ns >= source.stat().st_mtime_ns:
            return
        temporary = target.with_suffix(target.suffix + ".tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, target)

    @staticmethod
    def _file_sha256(path: Path) -> str:
        """Return a bounded-memory content identity for rare map-switch matching."""
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_if_changed(target: Path, text: str) -> None:
        if target.exists() and target.read_text(encoding="utf-8") == text:
            return
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)

    @staticmethod
    def _write_bytes_if_changed(target: Path, data: bytes | bytearray) -> None:
        if target.exists() and target.read_bytes() == data:
            return
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, target)

    @staticmethod
    def _pgm_dimensions(image: Path) -> tuple[int | None, int | None]:
        """只读取 PGM 文件头，不将地图像素载入内存。"""
        try:
            tokens: list[bytes] = []
            with image.open("rb") as handle:
                while len(tokens) < 3:
                    line = handle.readline()
                    if not line:
                        return None, None
                    tokens.extend(line.split(b"#", 1)[0].split())
            if tokens[0] not in {b"P2", b"P5"}:
                return None, None
            return int(tokens[1]), int(tokens[2])
        except (OSError, ValueError, IndexError):
            return None, None
