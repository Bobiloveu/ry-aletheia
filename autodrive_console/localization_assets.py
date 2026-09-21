"""Validate project-owned point-cloud assets for localization compatibility."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class LocalizationMapError(ValueError):
    """The map snapshot cannot satisfy the localization loader's inputs."""


@dataclass(frozen=True)
class LocalizationMap:
    index_path: Path | None
    index_bytes: bytes | None
    clouds: tuple[Path, ...]


def read_localization_map(directory: Path, *, root: Path) -> LocalizationMap:
    """Read optional compatibility metadata and every controlled PCD beside it.

    ``index.txt`` is retained for compatibility with existing map tools when it
    is present. It is not a required locator input: the runtime consumes the
    controlled PCD files directly, regardless of their filenames. The snapshot
    carries an existing index unchanged plus every non-empty PCD.
    """
    directory, root = directory.resolve(), root.resolve()
    if not directory.is_relative_to(root):
        raise LocalizationMapError("定位地图必须位于受控地图目录")
    index_candidate = directory / "index.txt"
    index = None
    index_bytes = None
    if index_candidate.exists() or index_candidate.is_symlink():
        index = _controlled_file(index_candidate, directory)
        if index.stat().st_size > 8 * 1024 * 1024:
            raise LocalizationMapError("定位 index.txt 超过 8 MiB 上限")
        try:
            index_bytes = index.read_bytes()
        except OSError as exc:
            raise LocalizationMapError("无法读取定位 index.txt") from exc
    clouds = _point_clouds(directory)
    if not clouds:
        raise LocalizationMapError("定位地图至少需要一份有效 PCD；请重新导入完整地图文件夹")
    return LocalizationMap(index, index_bytes, clouds)


def _controlled_file(path: Path, directory: Path) -> Path:
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_relative_to(directory) or not resolved.is_file() or resolved.stat().st_size == 0:
        raise LocalizationMapError(f"定位地图缺少有效 {path.name}；请重新导入完整地图文件夹")
    return resolved


def _point_clouds(directory: Path) -> tuple[Path, ...]:
    """Return usable PCD assets without applying legacy index conventions."""
    clouds: list[Path] = []
    for candidate in directory.iterdir():
        if candidate.suffix.lower() != ".pcd":
            continue
        try:
            clouds.append(_controlled_file(candidate, directory))
        except LocalizationMapError:
            # Ignore unrelated broken uploads; a valid PCD remains usable.
            continue
    return tuple(sorted(clouds, key=lambda cloud: cloud.name.casefold()))
