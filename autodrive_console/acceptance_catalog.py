"""Read-only catalog for formal deployment acceptance tasks.

The acceptance flow must never change files in the robot's formal task
directory.  This module deliberately contains only discovery, validation and
selection helpers; execution remains owned by :mod:`run_manager`.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from .models import TaskParameters


FORMAL_FILENAME = re.compile(
    r"^(?P<community>.+)_(?P<building>\d+)_(?P<unit>\d+)_(?P<floor>\d+)_(?P<door>\d+)\.json$"
)
EXCLUDED_NAME = re.compile(r"(?:_bak_|_backup|_old_)", re.IGNORECASE)


@dataclass(frozen=True)
class CatalogIssue:
    filename: str
    message: str


@dataclass(frozen=True)
class AcceptanceTask:
    path: Path
    filename: str
    parameters: TaskParameters
    task_group_name: str | None
    warnings: tuple[str, ...]
    sha256: str


@dataclass(frozen=True)
class CatalogSnapshot:
    valid_tasks: tuple[AcceptanceTask, ...]
    issues: tuple[CatalogIssue, ...]

    def communities(self) -> list[str]:
        return sorted({task.parameters.community for task in self.valid_tasks})

    def physical_buildings(self, community: str) -> list[tuple[int, int]]:
        """Return physical building units, not only a shared connected-block number."""
        return sorted({(task.parameters.building, task.parameters.unit) for task in self.valid_tasks if task.parameters.community == community})

    def select(self, scope_type: str, community: str, building: int | None = None, unit: int | None = None) -> list[AcceptanceTask]:
        if community not in self.communities():
            raise ValueError("所选小区不存在可用正式任务")
        if scope_type == "community":
            return [task for task in self.valid_tasks if task.parameters.community == community]
        if scope_type != "building":
            raise ValueError("验收范围必须是 community 或 building")
        if isinstance(building, bool) or not isinstance(building, int) or isinstance(unit, bool) or not isinstance(unit, int):
            raise ValueError("请选择实际存在的物理楼宇单元")
        selected = [
            task
            for task in self.valid_tasks
            if task.parameters.community == community and task.parameters.building == building and task.parameters.unit == unit
        ]
        if not selected:
            raise ValueError("所选物理楼宇单元不存在可用正式任务")
        return selected


class AcceptanceTaskCatalog:
    """Scan a formal task directory without changing its contents."""

    def __init__(self, task_directory: Path) -> None:
        self.task_directory = Path(task_directory)

    def scan(self) -> CatalogSnapshot:
        if not self.task_directory.is_dir():
            return CatalogSnapshot((), (CatalogIssue(self.task_directory.name, "正式任务目录不存在或不可访问"),))

        tasks: list[AcceptanceTask] = []
        issues: list[CatalogIssue] = []
        try:
            paths = sorted(self.task_directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            return CatalogSnapshot((), (CatalogIssue(self.task_directory.name, f"无法扫描正式任务目录：{exc}"),))

        for path in paths:
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() != ".json" or path.name.endswith("~") or EXCLUDED_NAME.search(path.name):
                continue
            try:
                tasks.append(self._load(path))
            except ValueError as exc:
                issues.append(CatalogIssue(path.name, str(exc)))

        return CatalogSnapshot(tuple(tasks), tuple(issues))

    @staticmethod
    def _parse_filename(filename: str) -> TaskParameters:
        match = FORMAL_FILENAME.fullmatch(filename)
        if not match or not match.group("community"):
            raise ValueError("文件名应以 小区_楼栋_单元_楼层_门牌.json 结尾")
        values = match.groupdict()
        return TaskParameters(
            community=values["community"],
            building=int(values["building"]),
            unit=int(values["unit"]),
            floor=int(values["floor"]),
            door=int(values["door"]),
        )

    def _load(self, path: Path) -> AcceptanceTask:
        parameters = self._parse_filename(path.name)
        try:
            contents = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"无法读取正式任务文件：{exc}") from exc
        try:
            payload = json.loads(contents.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError("任务文件必须使用 UTF-8 编码") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 格式错误：第 {exc.lineno} 行") from exc
        if not isinstance(payload, dict):
            raise ValueError("任务 JSON 根节点必须是对象")
        if not isinstance(payload.get("subtasks"), list) or not payload["subtasks"]:
            raise ValueError("任务 JSON 必须包含非空 subtasks 数组")

        group_name = payload.get("task_group_name")
        warnings: list[str] = []
        if not isinstance(group_name, str) or not group_name.strip():
            group_name = None
            warnings.append("未找到 task_group_name；验收范围仍以文件名为准")
        elif not self._group_name_matches(group_name, parameters):
            warnings.append("task_group_name 与文件名解析结果可能不一致；验收范围仍以文件名为准")

        return AcceptanceTask(
            path=path.resolve(),
            filename=path.name,
            parameters=parameters,
            task_group_name=group_name,
            warnings=tuple(warnings),
            sha256=hashlib.sha256(contents).hexdigest(),
        )

    @staticmethod
    def _group_name_matches(group_name: str, parameters: TaskParameters) -> bool:
        normalized = group_name.replace(" ", "")
        return parameters.community.replace("_", "") in normalized.replace("_", "") and str(parameters.building) in normalized
