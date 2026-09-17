"""Validate the project-owned tiled point-cloud files needed by localization."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path


class LocalizationMapError(ValueError):
    """The map snapshot cannot satisfy the localization loader's inputs."""


@dataclass(frozen=True)
class LocalizationMap:
    index_path: Path
    index_bytes: bytes
    clouds: tuple[Path, ...]


def read_localization_map(directory: Path, *, root: Path) -> LocalizationMap:
    """Read index.txt and only its numbered static/optional dynamic chunks.

    The native loader ignores stored chunk paths and reads <id>.pcd beside
    index.txt. Exported index paths are therefore rebased to those filenames;
    original robot paths never become package dependencies.
    """
    directory, root = directory.resolve(), root.resolve()
    if not directory.is_relative_to(root):
        raise LocalizationMapError("定位地图必须位于受控地图目录")
    index = _controlled_file(directory / "index.txt", directory)
    if index.stat().st_size > 8 * 1024 * 1024:
        raise LocalizationMapError("定位 index.txt 超过 8 MiB 上限")
    try:
        lines = [line.strip() for line in index.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeDecodeError) as exc:
        raise LocalizationMapError("无法读取定位 index.txt") from exc
    if not lines or not _finite_fields(lines[0].split(), 3):
        raise LocalizationMapError("定位 index.txt 缺少有效原点")
    rendered = [lines[0]]
    clouds: list[Path] = []
    identifiers: set[int] = set()
    grids: set[tuple[int, int]] = set()
    functional = False
    for line in lines[1:]:
        if line == "# functional points":
            if functional:
                raise LocalizationMapError("定位 index.txt 功能点区域重复")
            functional = True
            rendered.append(line)
            continue
        if functional:
            fields = line.split()
            if len(fields) != 8 or not _finite_fields(fields[1:], 7):
                raise LocalizationMapError("定位 index.txt 功能点无效")
            rendered.append(line)
            continue
        fields = line.split(maxsplit=3)
        try:
            if len(fields) != 4:
                raise ValueError
            identifier, grid_x, grid_y = (int(value) for value in fields[:3])
            if identifier < 0 or identifier in identifiers or (grid_x, grid_y) in grids:
                raise ValueError
        except ValueError as exc:
            raise LocalizationMapError("定位 index.txt 区块索引无效或重复") from exc
        identifiers.add(identifier)
        grids.add((grid_x, grid_y))
        cloud = _controlled_file(directory / f"{identifier}.pcd", directory)
        clouds.append(cloud)
        dynamic = directory / f"{identifier}_dyn.pcd"
        if dynamic.exists() or dynamic.is_symlink():
            clouds.append(_controlled_file(dynamic, directory))
        rendered.append(f"{identifier} {grid_x} {grid_y} {identifier}.pcd")
    if not identifiers:
        raise LocalizationMapError("定位 index.txt 没有点云区块；请导入完整定位地图")
    return LocalizationMap(index, ("\n".join(rendered) + "\n").encode("utf-8"), tuple(clouds))


def _controlled_file(path: Path, directory: Path) -> Path:
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_relative_to(directory) or not resolved.is_file() or resolved.stat().st_size == 0:
        raise LocalizationMapError(f"定位地图缺少有效 {path.name}；请重新导入完整地图文件夹")
    return resolved


def _finite_fields(fields: list[str], count: int) -> bool:
    try:
        return len(fields) == count and all(isfinite(float(value)) for value in fields)
    except ValueError:
        return False
