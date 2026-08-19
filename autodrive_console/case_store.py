from __future__ import annotations

import json
import re
from pathlib import Path

from .models import TaskParameters, TestCase


class CaseStore:
    """读取任务文件；兼容旧的“社区_栋_单元_楼层_门牌.json”命名约定。"""

    FILENAME = re.compile(r"^(?P<community>[^_]+)_(?P<building>\d+)_(?P<unit>\d+)_(?P<floor>\d+)_(?P<door>\d+)\.json$")

    def __init__(self, case_dir: Path) -> None:
        self.case_dir = case_dir

    def list_cases(self) -> tuple[list[TestCase], list[dict[str, str]]]:
        cases: list[TestCase] = []
        issues: list[dict[str, str]] = []
        # 点文件属于控制台配置，不是待执行的任务资产。
        for path in sorted(path for path in self.case_dir.glob("*.json") if not path.name.startswith(".")):
            try:
                cases.append(self._load_case(path))
            except ValueError as exc:
                issues.append({"filename": path.name, "message": str(exc)})
        return cases, issues

    def get_case(self, case_id: str) -> TestCase | None:
        return next((case for case in self.list_cases()[0] if case.id == case_id), None)

    @classmethod
    def parse_case(cls, filename: str, contents: str, source: str = "") -> TestCase:
        """校验磁盘文件或上传内容，确保两条入口遵循相同的任务资产规则。"""
        try:
            parsed = json.loads(contents)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 格式错误：第 {exc.lineno} 行") from exc
        if not isinstance(parsed, (dict, list)):
            raise ValueError("JSON 根节点必须是对象或数组")

        match = cls.FILENAME.match(filename)
        if not match:
            raise ValueError("文件名应为：社区_栋_单元_楼层_门牌.json（社区名不能含下划线）")
        values = match.groupdict()
        params = TaskParameters(
            community=values["community"], building=int(values["building"]),
            unit=int(values["unit"]), floor=int(values["floor"]), door=int(values["door"]),
        )
        return TestCase(
            id=filename,
            filename=filename,
            name=f"{params.community} · {params.building}栋{params.unit}单元 · {params.floor}层{params.door}室",
            parameters=params,
            source=source or filename,
        )

    def _load_case(self, path: Path) -> TestCase:
        try:
            contents = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("文件必须使用 UTF-8 编码") from exc
        return self.parse_case(path.name, contents, str(path))
