"""Read-only discovery for the R6B ``multi_tasks`` directory.

The directory contains route fragments rather than one JSON file per business
address.  This module reports what is present and keeps the distinction
between generic floor templates and physical-floor exceptions.  It never
creates, edits, or deletes task files.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


_TEMPLATE_NAME = re.compile(r"^(?P<building>\d+)_(?P<unit>\d+)_n_n(?P<door_suffix>\d+)(?P<return>_r)?\.json$")
_SPECIAL_NAME = re.compile(
    r"^(?P<building>\d+)_(?P<unit>\d+)_(?P<physical_floor>\d+)_(?P<door>\d+)(?P<return>_r)?\.json$"
)
_BUILDING_NAME = re.compile(r"^(?P<building>\d+)_(?P<unit>\d+)(?P<return>_r)?\.json$")
_GATE_NAMES = {"sub_outdoor_eguard.json", "sub_outdoor_eguard_r.json"}


@dataclass(frozen=True)
class MultiCatalogIssue:
    filename: str
    message: str


@dataclass(frozen=True)
class MultiFloorFile:
    path: Path
    filename: str
    building: int
    unit: int
    direction: str
    sha256: str
    door_suffix: str | None = None
    physical_floor: int | None = None
    door: int | None = None


@dataclass(frozen=True)
class MultiFloorTemplate:
    door_suffix: str
    forward: MultiFloorFile | None
    return_file: MultiFloorFile | None

    @property
    def available(self) -> bool:
        return self.forward is not None and self.return_file is not None


@dataclass(frozen=True)
class MultiSpecialPoint:
    physical_floor: int
    door: int
    forward: MultiFloorFile | None
    return_file: MultiFloorFile | None

    @property
    def available(self) -> bool:
        return self.forward is not None and self.return_file is not None


@dataclass(frozen=True)
class MultiBuildingStatus:
    community: str
    building: int
    unit: int
    indoor_forward: Path | None
    indoor_return: Path | None
    outdoor_forward: Path | None
    outdoor_return: Path | None
    templates: tuple[MultiFloorTemplate, ...]
    special_points: tuple[MultiSpecialPoint, ...]
    available: bool
    issues: tuple[str, ...]


@dataclass(frozen=True)
class MultiGateStatus:
    forward: Path | None
    return_file: Path | None

    @property
    def available(self) -> bool:
        return self.forward is not None and self.return_file is not None


@dataclass(frozen=True)
class DestinationValidation:
    available: bool
    reason: str = ""
    source_kind: str | None = None
    forward_path: Path | None = None
    return_path: Path | None = None
    physical_floor: int | None = None


@dataclass(frozen=True)
class MultiCatalogSnapshot:
    root: Path
    buildings: tuple[MultiBuildingStatus, ...]
    gates: tuple[tuple[str, MultiGateStatus], ...]
    issues: tuple[MultiCatalogIssue, ...]

    def communities(self) -> list[str]:
        return sorted({item.community for item in self.buildings} | {name for name, _ in self.gates})

    def physical_buildings(self, community: str) -> list[tuple[int, int]]:
        return sorted(
            (item.building, item.unit)
            for item in self.buildings
            if item.community == community
        )

    def building_status(self, community: str, building: int, unit: int) -> MultiBuildingStatus:
        for item in self.buildings:
            if item.community == community and item.building == building and item.unit == unit:
                return item
        raise ValueError("所选小区或物理楼宇单元不存在多点任务目录")

    def templates(self, community: str, building: int, unit: int) -> tuple[MultiFloorTemplate, ...]:
        return self.building_status(community, building, unit).templates

    def special_points(self, community: str, building: int, unit: int) -> tuple[MultiSpecialPoint, ...]:
        return self.building_status(community, building, unit).special_points

    def gate_status(self, community: str) -> MultiGateStatus:
        for name, status in self.gates:
            if name == community:
                return status
        return MultiGateStatus(None, None)

    def validate_destination(
        self,
        community: str,
        building: int,
        unit: int,
        floor: str | int,
        door: str | int,
    ) -> DestinationValidation:
        try:
            status = self.building_status(community, building, unit)
        except ValueError as exc:
            return DestinationValidation(False, str(exc))
        if not status.available:
            return DestinationValidation(False, "；".join(status.issues))
        try:
            floor_number = int(str(floor))
        except (TypeError, ValueError):
            return DestinationValidation(False, "楼层必须是数字")
        try:
            door_number = int(str(door))
        except (TypeError, ValueError):
            return DestinationValidation(False, "门牌必须是数字")

        special = [item for item in status.special_points if item.door == door_number and item.available]
        matched_special = [item for item in special if item.physical_floor == floor_number]
        if len(matched_special) == 1:
            item = matched_special[0]
            return DestinationValidation(
                True,
                source_kind="special",
                forward_path=item.forward.path if item.forward else None,
                return_path=item.return_file.path if item.return_file else None,
                physical_floor=item.physical_floor,
            )
        if len(matched_special) > 1:
            return DestinationValidation(False, "专用门牌对应多个物理楼层，无法自动确定")
        if special:
            floors = "、".join(str(item.physical_floor) for item in special)
            return DestinationValidation(False, f"门牌 {door_number} 仅支持文件中定义的楼层：{floors}")

        suffix = str(door_number).zfill(2)[-2:]
        templates = [item for item in status.templates if item.door_suffix == suffix and item.available]
        if len(templates) == 1:
            item = templates[0]
            return DestinationValidation(
                True,
                source_kind="template",
                forward_path=item.forward.path if item.forward else None,
                return_path=item.return_file.path if item.return_file else None,
            )
        if not templates:
            return DestinationValidation(False, f"未找到门牌后缀 n_n{suffix} 的楼层任务模板或专用文件")
        return DestinationValidation(False, "门牌后缀对应多个楼层任务模板，无法自动确定")


class MultiTaskCatalog:
    """Scan the R6B task root without touching its contents."""

    def __init__(self, task_directory: Path = Path("/opt/ry/data/tasks/multi_tasks")) -> None:
        self.task_directory = Path(task_directory)

    def scan(self) -> MultiCatalogSnapshot:
        root = self.task_directory
        if not root.is_dir():
            return MultiCatalogSnapshot(root.resolve(), (), (), (MultiCatalogIssue(root.name, "多点任务目录不存在或不可访问"),))
        try:
            community_paths = sorted((path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")), key=lambda item: item.name)
        except OSError as exc:
            return MultiCatalogSnapshot(root.resolve(), (), (), (MultiCatalogIssue(root.name, f"无法扫描多点任务目录：{exc}"),))

        buildings: list[MultiBuildingStatus] = []
        gates: list[tuple[str, MultiGateStatus]] = []
        issues: list[MultiCatalogIssue] = []
        for community_path in community_paths:
            community_root = community_path.resolve()
            try:
                community_root.relative_to(root.resolve())
            except ValueError:
                issues.append(MultiCatalogIssue(community_path.name, "社区目录越过多点任务根目录，已忽略"))
                continue
            community_buildings, community_issues = self._scan_community(community_path)
            buildings.extend(community_buildings)
            issues.extend(community_issues)
            gates.append((community_path.name, self._scan_gate(community_path, issues)))

        return MultiCatalogSnapshot(root.resolve(), tuple(buildings), tuple(gates), tuple(issues))

    def _scan_community(
        self, community_path: Path
    ) -> tuple[list[MultiBuildingStatus], list[MultiCatalogIssue]]:
        issues: list[MultiCatalogIssue] = []
        floor_path = community_path / "floor"
        indoor_path = community_path / "indoor"
        outdoor_path = community_path / "outdoor"
        floor_files: dict[tuple[int, int, str, int | None, int | None], dict[str, MultiFloorFile]] = {}
        building_files: dict[tuple[int, int, str], dict[str, Path]] = {}
        if floor_path.is_dir():
            for path in sorted(floor_path.iterdir(), key=lambda item: item.name):
                if not path.is_file() or path.name.startswith("."):
                    continue
                if not self._is_within(path, community_path):
                    issues.append(MultiCatalogIssue(path.name, "任务文件越过多点任务根目录，已忽略"))
                    continue
                match = _TEMPLATE_NAME.fullmatch(path.name) or _SPECIAL_NAME.fullmatch(path.name)
                if not match:
                    continue
                try:
                    parsed = self._read_file(path)
                except ValueError as exc:
                    issues.append(MultiCatalogIssue(str(path.relative_to(community_path)), str(exc)))
                    continue
                values = match.groupdict()
                is_template = "door_suffix" in values and values.get("door_suffix") is not None
                key = (
                    int(values["building"]),
                    int(values["unit"]),
                    "template" if is_template else "special",
                    None if is_template else int(values["physical_floor"]),
                    int(values["door"]) if not is_template else int(values["door_suffix"]),
                )
                item = MultiFloorFile(
                    path=path.resolve(),
                    filename=path.name,
                    building=key[0],
                    unit=key[1],
                    direction="return" if values.get("return") else "forward",
                    sha256=parsed,
                    door_suffix=values.get("door_suffix") if is_template else None,
                    physical_floor=None if is_template else int(values["physical_floor"]),
                    door=None if is_template else int(values["door"]),
                )
                floor_files.setdefault(key, {})[item.direction] = item
        elif floor_path.exists():
            issues.append(MultiCatalogIssue("floor", "floor 必须是目录"))

        for kind, directory in (("indoor", indoor_path), ("outdoor", outdoor_path)):
            if not directory.is_dir():
                if directory.exists():
                    issues.append(MultiCatalogIssue(kind, f"{kind} 必须是目录"))
                continue
            for path in sorted(directory.iterdir(), key=lambda item: item.name):
                if not path.is_file() or path.name.startswith("."):
                    continue
                if not self._is_within(path, community_path):
                    issues.append(MultiCatalogIssue(path.name, "任务文件越过多点任务根目录，已忽略"))
                    continue
                match = _BUILDING_NAME.fullmatch(path.name)
                if not match:
                    continue
                try:
                    self._read_file(path)
                except ValueError as exc:
                    issues.append(MultiCatalogIssue(str(path.relative_to(community_path)), str(exc)))
                    continue
                key = (int(match.group("building")), int(match.group("unit")), kind)
                direction = "return" if match.group("return") else "forward"
                building_files.setdefault(key, {})[direction] = path.resolve()

        building_keys = {(key[0], key[1]) for key in floor_files} | {(key[0], key[1]) for key in building_files}
        result: list[MultiBuildingStatus] = []
        for building, unit in sorted(building_keys):
            templates: list[MultiFloorTemplate] = []
            specials: list[MultiSpecialPoint] = []
            for key, files in sorted(floor_files.items()):
                if key[:2] != (building, unit):
                    continue
                if key[2] == "template":
                    templates.append(MultiFloorTemplate(key[4] and str(key[4]).zfill(2), files.get("forward"), files.get("return")))
                else:
                    specials.append(MultiSpecialPoint(key[3], key[4], files.get("forward"), files.get("return")))
            building_issues: list[str] = []
            indoor = building_files.get((building, unit, "indoor"), {})
            outdoor = building_files.get((building, unit, "outdoor"), {})
            for item in (*templates, *specials):
                if not item.available:
                    building_issues.append(f"楼层文件 {self._floor_key(item)} 正返程文件不成对")
            if not templates and not specials:
                building_issues.append("未找到 floor 楼层任务文件")
            result.append(
                MultiBuildingStatus(
                    community=community_path.name,
                    building=building,
                    unit=unit,
                    indoor_forward=indoor.get("forward"),
                    indoor_return=indoor.get("return"),
                    outdoor_forward=outdoor.get("forward"),
                    outdoor_return=outdoor.get("return"),
                    templates=tuple(templates),
                    special_points=tuple(specials),
                    available=not building_issues,
                    issues=tuple(building_issues),
                )
            )
        return result, issues

    @staticmethod
    def _floor_key(item: MultiFloorTemplate | MultiSpecialPoint) -> str:
        if isinstance(item, MultiFloorTemplate):
            return f"n_n{item.door_suffix}"
        return f"{item.physical_floor}_{item.door}"

    @staticmethod
    def _read_file(path: Path) -> str:
        try:
            contents = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"无法读取任务文件：{exc}") from exc
        try:
            payload = json.loads(contents.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError("任务文件必须使用 UTF-8 编码") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 格式错误：第 {exc.lineno} 行") from exc
        if not isinstance(payload, dict):
            raise ValueError("任务 JSON 根节点必须是对象")
        return hashlib.sha256(contents).hexdigest()

    def _scan_gate(self, community_path: Path, issues: list[MultiCatalogIssue]) -> MultiGateStatus:
        files: dict[str, Path] = {}
        for name in _GATE_NAMES:
            path = community_path / name
            if not path.is_file():
                continue
            if not self._is_within(path, community_path):
                issues.append(MultiCatalogIssue(name, "任务文件越过多点任务根目录，已忽略"))
                continue
            try:
                self._read_file(path)
            except ValueError as exc:
                issues.append(MultiCatalogIssue(name, str(exc)))
                continue
            files["return" if name.endswith("_r.json") else "forward"] = path.resolve()
        return MultiGateStatus(files.get("forward"), files.get("return"))

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            return False
        return True
