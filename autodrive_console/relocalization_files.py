"""Read-only selection of a localization configuration."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import ExitStack, contextmanager
import hashlib
import os
from pathlib import Path
import stat

import yaml

from .map_assets import MapAssetCache

from .scenario_setup import ScenarioSetupError, ScenarioSetupStore


class LocalizationConfigFileError(ValueError):
    pass


class _UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        # A different parser must not choose a different map from duplicate keys.
        if any(key.tag == 'tag:yaml.org,2002:merge' for key, _ in node.value):
            raise LocalizationConfigFileError('定位 YAML 包含合并字段，请选择使用明确字段的配置')
        self.flatten_mapping(node)
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in seen:
                    raise LocalizationConfigFileError('定位 YAML 存在重复字段，请选择无歧义的配置')
                seen.add(key)
            except TypeError as exc:
                raise LocalizationConfigFileError('定位 YAML 字段格式无效') from exc
        return super().construct_mapping(node, deep=deep)


def _identity(item: os.stat_result) -> tuple[int, int, int, int]:
    return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns


@contextmanager
def _open_config(path: Path):
    # Canonical paths have no symlink components. Open every directory through
    # its held parent fd so a concurrent ancestor swap cannot escape the root.
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        parent = os.open(path.anchor, directory_flags)
        stack.callback(os.close, parent)
        for component in path.parts[1:-1]:
            parent = os.open(component, directory_flags, dir_fd=parent)
            stack.callback(os.close, parent)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(descriptor, 'rb') as stream:
            yield stream


@dataclass(frozen=True)
class LocalizationConfigSelection:
    path: Path
    identity: tuple[int, int, int, int]
    sha256: str
    map_directory: Path
    map_yaml: Path
    map_identity: tuple[int, int, int, int]
    map_sha256: str


class LocalizationConfigFiles:
    ROOT = Path('/opt/ry/config/localization')
    MAX_BYTES = 512 * 1024

    def __init__(self, root: Path | None = None):
        self.root = root if root is not None else self.ROOT

    def _path(self, raw: str, *, directory: bool = False) -> tuple[Path, Path]:
        try:
            root = self.root.resolve(strict=True)
            path = Path(raw) if raw else root
            if not path.is_absolute() or '..' in path.parts:
                raise LocalizationConfigFileError('只能选择定位配置目录内的路径')
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise LocalizationConfigFileError('只能选择定位配置目录内的路径')
            if directory:
                if not resolved.is_dir():
                    raise LocalizationConfigFileError('所选定位配置目录不可用')
            elif resolved.suffix.lower() not in {'.yaml', '.yml'} or not resolved.is_file():
                raise LocalizationConfigFileError('请选择可读取的定位 YAML 文件')
            return root, resolved
        except (OSError, RuntimeError) as exc:
            raise LocalizationConfigFileError('定位配置路径不存在或不可读取') from exc

    def browse(self, raw: str = '') -> dict:
        if not isinstance(raw, str):
            raise LocalizationConfigFileError('定位配置目录格式无效')
        root, path = self._path(raw, directory=True)
        try:
            return ScenarioSetupStore.browse_at_root(str(path), 'lightning', root)
        except (OSError, RuntimeError, ScenarioSetupError) as exc:
            raise LocalizationConfigFileError('无法浏览定位配置目录，请确认目录可读取') from exc

    def select(self, raw: str, current_map: Path) -> LocalizationConfigSelection:
        if not isinstance(raw, str) or not raw or len(raw) > 4096:
            raise LocalizationConfigFileError('请选择有效的定位 YAML 文件')
        _, path = self._path(raw)
        try:
            with _open_config(path) as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > self.MAX_BYTES:
                    raise LocalizationConfigFileError('定位 YAML 必须是大小不超过 512 KiB 的常规文件')
                content = stream.read(self.MAX_BYTES + 1)
                after = os.fstat(stream.fileno())
            if len(content) > self.MAX_BYTES or _identity(before) != _identity(after):
                raise LocalizationConfigFileError('定位配置读取期间发生变化，请重新选择')
            document = yaml.load(content, Loader=_UniqueLoader)
            system = document.get('system') if isinstance(document, dict) else None
            map_path = system.get('map_path') if isinstance(system, dict) else None
            if not isinstance(map_path, str) or not Path(map_path).is_absolute():
                raise LocalizationConfigFileError('定位 YAML 缺少有效的 system.map_path')
            map_directory = Path(map_path).resolve(strict=True)
            if not map_directory.is_dir():
                raise LocalizationConfigFileError('定位 YAML 的 system.map_path 必须是现有地图目录')
            try:
                map_yaml = (map_directory / 'map.yaml').resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise LocalizationConfigFileError('目标二维地图 map.yaml 不存在或不可读取') from exc
            if map_yaml.parent != map_directory or not any(
                    map_yaml.is_relative_to(root.resolve()) for root in MapAssetCache.ALLOWED_ROOTS):
                raise LocalizationConfigFileError('目标二维地图必须位于受控地图目录')
            with _open_config(map_yaml) as stream:
                map_before = os.fstat(stream.fileno())
                if not stat.S_ISREG(map_before.st_mode) or map_before.st_size > self.MAX_BYTES:
                    raise LocalizationConfigFileError('目标二维地图 YAML 无效')
                map_content = stream.read(self.MAX_BYTES + 1)
                map_after = os.fstat(stream.fileno())
            if len(map_content) > self.MAX_BYTES or _identity(map_before) != _identity(map_after):
                raise LocalizationConfigFileError('目标二维地图读取期间发生变化')
            if map_yaml.resolve(strict=True) != map_yaml or _identity(map_yaml.stat()) != _identity(map_after):
                raise LocalizationConfigFileError('目标二维地图读取期间发生变化')
            if path.resolve(strict=True) != path or _identity(path.stat()) != _identity(after):
                raise LocalizationConfigFileError('定位配置读取期间发生变化，请重新选择')
            return LocalizationConfigSelection(path, _identity(after), hashlib.sha256(content).hexdigest(),
                map_directory, map_yaml, _identity(map_after), hashlib.sha256(map_content).hexdigest())
        except (OSError, RuntimeError, yaml.YAMLError, UnicodeError) as exc:
            raise LocalizationConfigFileError('定位 YAML 无法读取或格式无效，请重新选择') from exc

    def revalidate(self, selection: LocalizationConfigSelection, current_map: Path) -> None:
        current = self.select(str(selection.path), current_map)
        if current != selection:
            raise LocalizationConfigFileError('定位配置已发生变化，请恢复后重新选择')
