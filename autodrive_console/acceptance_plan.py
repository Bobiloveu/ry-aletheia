"""Frozen deployment-acceptance plans, criteria and local persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import random
import secrets
import tempfile
import uuid
from typing import Any

from .acceptance_catalog import AcceptanceTask, CatalogSnapshot
from .models import TaskParameters, now_iso


ACTIVE_PLAN_STATUSES = frozenset({"preparing", "running", "awaiting_recovery", "recovering"})
TERMINAL_ITEM_STATUSES = frozenset({"passed", "failed", "cancelled"})


def _number(value: object, name: str, *, minimum: float, maximum: float, integer: bool = False) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name}必须是数字")
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}必须是数字") from exc
    if not math.isfinite(converted) or not minimum <= converted <= maximum:
        raise ValueError(f"{name}必须介于 {minimum:g} 和 {maximum:g}")
    if integer and not converted.is_integer():
        raise ValueError(f"{name}必须是整数")
    return int(converted) if integer else converted


@dataclass(frozen=True)
class AcceptanceCriteria:
    min_pass_rate: float | None = None
    min_building_coverage: float | None = None
    min_unit_coverage: float | None = None
    min_floor_coverage: float | None = None
    min_door_coverage: float | None = None
    max_failed_tasks: int | None = None
    max_manual_interventions: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "min_pass_rate",
            "min_building_coverage",
            "min_unit_coverage",
            "min_floor_coverage",
            "min_door_coverage",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), name, minimum=0, maximum=100))
        for name in ("max_failed_tasks", "max_manual_interventions"):
            object.__setattr__(self, name, _number(getattr(self, name), name, minimum=0, maximum=100000, integer=True))

    @classmethod
    def empty(cls) -> "AcceptanceCriteria":
        return cls()

    @classmethod
    def from_dict(cls, document: dict[str, object]) -> "AcceptanceCriteria":
        expected = {
            "min_pass_rate", "min_building_coverage", "min_unit_coverage", "min_floor_coverage",
            "min_door_coverage", "max_failed_tasks", "max_manual_interventions",
        }
        unexpected = set(document) - expected
        if unexpected:
            raise ValueError(f"验收标准包含未知字段：{', '.join(sorted(unexpected))}")
        return cls(**{name: document.get(name) for name in expected})

    def to_dict(self) -> dict[str, float | int | None]:
        return {
            "min_pass_rate": self.min_pass_rate,
            "min_building_coverage": self.min_building_coverage,
            "min_unit_coverage": self.min_unit_coverage,
            "min_floor_coverage": self.min_floor_coverage,
            "min_door_coverage": self.min_door_coverage,
            "max_failed_tasks": self.max_failed_tasks,
            "max_manual_interventions": self.max_manual_interventions,
        }

    def is_complete(self) -> bool:
        return all(value is not None for value in self.to_dict().values())


@dataclass
class AcceptancePlanItem:
    filename: str
    source_path: str
    parameters: TaskParameters
    task_group_name: str | None
    warnings: list[str]
    sha256: str
    status: str = "planned"
    message: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None
    trajectory: dict[str, Any] | None = None

    @classmethod
    def from_task(cls, task: AcceptanceTask) -> "AcceptancePlanItem":
        return cls(
            filename=task.filename,
            source_path=str(task.path),
            parameters=task.parameters,
            task_group_name=task.task_group_name,
            warnings=list(task.warnings),
            sha256=task.sha256,
        )

    def to_storage_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "source_path": self.source_path,
            "parameters": self.parameters.__dict__,
            "task_group_name": self.task_group_name,
            "warnings": self.warnings,
            "sha256": self.sha256,
            "status": self.status,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": self.duration_s,
            "trajectory": self.trajectory,
        }

    @classmethod
    def from_storage_dict(cls, document: dict[str, Any]) -> "AcceptancePlanItem":
        parameters = document.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError("冻结任务缺少参数")
        return cls(
            filename=str(document["filename"]),
            source_path=str(document["source_path"]),
            parameters=TaskParameters(**{name: int(parameters[name]) if name != "community" else str(parameters[name]) for name in ("community", "building", "unit", "floor", "door")}),
            task_group_name=document.get("task_group_name") if isinstance(document.get("task_group_name"), str) else None,
            warnings=[str(value) for value in document.get("warnings", [])],
            sha256=str(document["sha256"]),
            status=str(document.get("status", "planned")),
            message=str(document.get("message", "")),
            started_at=document.get("started_at") if isinstance(document.get("started_at"), str) else None,
            finished_at=document.get("finished_at") if isinstance(document.get("finished_at"), str) else None,
            duration_s=float(document["duration_s"]) if document.get("duration_s") is not None else None,
            trajectory=document.get("trajectory") if isinstance(document.get("trajectory"), dict) else None,
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "parameters": self.parameters.__dict__,
            "task_group_name": self.task_group_name,
            "warnings": self.warnings,
            "sha256": self.sha256,
            "status": self.status,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": self.duration_s,
            "trajectory": self.trajectory,
        }


@dataclass(frozen=True)
class CoverageSummary:
    planned: dict[str, float]
    executed: dict[str, float]
    passed: dict[str, float]

    def to_dict(self) -> dict[str, dict[str, float]]:
        return {"planned": self.planned, "executed": self.executed, "passed": self.passed}


@dataclass(frozen=True)
class AcceptanceResult:
    status: str | None
    message: str
    coverage: CoverageSummary
    pass_rate: float
    failed_tasks: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "coverage": self.coverage.to_dict(),
            "pass_rate": self.pass_rate,
            "failed_tasks": self.failed_tasks,
        }


@dataclass
class AcceptancePlan:
    plan_id: str
    created_at: str
    updated_at: str
    scope_type: str
    community: str
    building: int | None
    mode: str
    random_seed: int
    task_pool_size: int
    items: list[AcceptancePlanItem]
    criteria_snapshot: dict[str, float | int | None]
    warnings: list[str] = field(default_factory=list)
    status: str = "ready"
    current_index: int | None = None
    run_id: str | None = None
    manual_interventions: int = 0
    report_filename: str | None = None

    def to_storage_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "scope_type": self.scope_type,
            "community": self.community,
            "building": self.building,
            "mode": self.mode,
            "random_seed": self.random_seed,
            "task_pool_size": self.task_pool_size,
            "items": [item.to_storage_dict() for item in self.items],
            "criteria_snapshot": self.criteria_snapshot,
            "warnings": self.warnings,
            "status": self.status,
            "current_index": self.current_index,
            "run_id": self.run_id,
            "manual_interventions": self.manual_interventions,
            "report_filename": self.report_filename,
        }

    @classmethod
    def from_storage_dict(cls, document: dict[str, Any]) -> "AcceptancePlan":
        if document.get("schema") != 1 or not isinstance(document.get("items"), list):
            raise ValueError("验收计划文件格式不受支持")
        criteria = AcceptanceCriteria.from_dict(dict(document.get("criteria_snapshot") or {}))
        plan = cls(
            plan_id=str(document["plan_id"]),
            created_at=str(document["created_at"]),
            updated_at=str(document["updated_at"]),
            scope_type=str(document["scope_type"]),
            community=str(document["community"]),
            building=int(document["building"]) if document.get("building") is not None else None,
            mode=str(document["mode"]),
            random_seed=int(document["random_seed"]),
            task_pool_size=int(document["task_pool_size"]),
            items=[AcceptancePlanItem.from_storage_dict(item) for item in document["items"] if isinstance(item, dict)],
            criteria_snapshot=criteria.to_dict(),
            warnings=[str(value) for value in document.get("warnings", [])],
            status=str(document.get("status", "ready")),
            current_index=int(document["current_index"]) if document.get("current_index") is not None else None,
            run_id=document.get("run_id") if isinstance(document.get("run_id"), str) else None,
            manual_interventions=int(document.get("manual_interventions", 0)),
            report_filename=document.get("report_filename") if isinstance(document.get("report_filename"), str) else None,
        )
        if not re_plan_id(plan.plan_id):
            raise ValueError("验收计划 ID 无效")
        return plan

    def to_public_dict(self) -> dict[str, Any]:
        result = evaluate_conclusion(self, AcceptanceCriteria.from_dict(self.criteria_snapshot))
        return {
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "scope_type": self.scope_type,
            "community": self.community,
            "building": self.building,
            "mode": self.mode,
            "random_seed": self.random_seed,
            "task_pool_size": self.task_pool_size,
            "items": [item.to_public_dict() for item in self.items],
            "criteria_snapshot": self.criteria_snapshot,
            "warnings": self.warnings,
            "status": self.status,
            "current_index": self.current_index,
            "run_id": self.run_id,
            "manual_interventions": self.manual_interventions,
            "report_filename": self.report_filename,
            "conclusion": result.to_dict(),
        }


def re_plan_id(value: str) -> bool:
    return bool(__import__("re").fullmatch(r"[0-9a-f]{12}", value))


class AcceptancePlanFactory:
    @staticmethod
    def create(
        snapshot: CatalogSnapshot,
        *,
        scope_type: str,
        community: str,
        building: int | None,
        mode: str,
        sample_size: int | None,
        random_seed: int | None,
        criteria: AcceptanceCriteria,
    ) -> AcceptancePlan:
        pool = snapshot.select(scope_type, community, building)
        if mode not in {"full", "sample"}:
            raise ValueError("计划模式必须是 full 或 sample")
        if mode == "full":
            if sample_size is not None:
                raise ValueError("全量计划不接受抽样数量")
            selected_size = len(pool)
        else:
            if isinstance(sample_size, bool) or not isinstance(sample_size, int) or not 1 <= sample_size <= len(pool):
                raise ValueError("抽样数量必须介于 1 和可用任务数之间")
            selected_size = sample_size
        if random_seed is None:
            random_seed = secrets.randbits(63)
        if isinstance(random_seed, bool) or not isinstance(random_seed, int) or random_seed < 0:
            raise ValueError("随机种子无效")
        ordered = _coverage_aware_order(pool, community_scope=scope_type == "community", seed=random_seed)
        selected = ordered[:selected_size]
        timestamp = now_iso()
        return AcceptancePlan(
            plan_id=uuid.uuid4().hex[:12],
            created_at=timestamp,
            updated_at=timestamp,
            scope_type=scope_type,
            community=community,
            building=building if scope_type == "building" else None,
            mode=mode,
            random_seed=random_seed,
            task_pool_size=len(pool),
            items=[AcceptancePlanItem.from_task(task) for task in selected],
            criteria_snapshot=criteria.to_dict(),
            warnings=_coverage_warnings(pool, selected_size, community_scope=scope_type == "community"),
        )


def _coverage_aware_order(tasks: list[AcceptanceTask], *, community_scope: bool, seed: int) -> list[AcceptanceTask]:
    ordered = sorted(tasks, key=lambda task: (task.parameters.building, task.parameters.unit, task.parameters.floor, task.parameters.door, task.filename))
    randomizer = random.Random(seed)
    tie_break = {task.filename: randomizer.random() for task in ordered}
    selected: list[AcceptanceTask] = []
    remaining = list(ordered)
    building_count: dict[int, int] = {}
    unit_count: dict[int, int] = {}
    floor_count: dict[int, int] = {}
    door_count: dict[int, int] = {}
    while remaining:
        previous = selected[-1].parameters if selected else None

        def score(task: AcceptanceTask) -> tuple[float, ...]:
            p = task.parameters
            return (
                float(building_count.get(p.building, 0)) if community_scope else 0.0,
                float(unit_count.get(p.unit, 0)),
                float(floor_count.get(p.floor, 0)),
                float(door_count.get(p.door, 0)),
                float(previous is not None and p.building == previous.building),
                float(previous is not None and p.unit == previous.unit),
                float(previous is not None and p.floor == previous.floor),
                tie_break[task.filename],
            )

        chosen = min(remaining, key=score)
        remaining.remove(chosen)
        selected.append(chosen)
        p = chosen.parameters
        building_count[p.building] = building_count.get(p.building, 0) + 1
        unit_count[p.unit] = unit_count.get(p.unit, 0) + 1
        floor_count[p.floor] = floor_count.get(p.floor, 0) + 1
        door_count[p.door] = door_count.get(p.door, 0) + 1
    return selected


def _coverage_warnings(pool: list[AcceptanceTask], selected_size: int, *, community_scope: bool) -> list[str]:
    dimensions: list[tuple[str, set[int]]] = [
        ("单元", {item.parameters.unit for item in pool}),
        ("楼层", {item.parameters.floor for item in pool}),
        ("户", {item.parameters.door for item in pool}),
    ]
    if community_scope:
        dimensions.insert(0, ("楼栋", {item.parameters.building for item in pool}))
    warnings: list[str] = []
    for label, values in dimensions:
        if len(values) > selected_size:
            warnings.append(f"抽样数量不足以覆盖全部{label}（可用 {len(values)} 类，计划 {selected_size} 项）")
        elif len(values) <= 1:
            warnings.append(f"正式任务池仅含 {len(values)} 类{label}，无法扩大该维度覆盖")
    return warnings


def coverage_summary(plan: AcceptancePlan) -> CoverageSummary:
    dimensions = {
        "building": lambda item: item.parameters.building,
        "unit": lambda item: item.parameters.unit,
        "floor": lambda item: item.parameters.floor,
        "door": lambda item: item.parameters.door,
    }
    planned = plan.items
    executed = [item for item in plan.items if item.status in TERMINAL_ITEM_STATUSES]
    passed = [item for item in plan.items if item.status == "passed"]

    def percentages(items: list[AcceptancePlanItem]) -> dict[str, float]:
        output: dict[str, float] = {}
        for name, field_getter in dimensions.items():
            denominator = len({field_getter(item) for item in planned})
            numerator = len({field_getter(item) for item in items})
            output[name] = round(numerator / denominator * 100, 1) if denominator else 0.0
        return output

    return CoverageSummary(planned=percentages(planned), executed=percentages(executed), passed=percentages(passed))


def evaluate_conclusion(plan: AcceptancePlan, criteria: AcceptanceCriteria) -> AcceptanceResult:
    coverage = coverage_summary(plan)
    terminal_items = [item for item in plan.items if item.status in {"passed", "failed"}]
    passed = sum(item.status == "passed" for item in terminal_items)
    failed = sum(item.status == "failed" for item in terminal_items)
    pass_rate = round(passed / len(terminal_items) * 100, 1) if terminal_items else 0.0
    if plan.status != "completed":
        return AcceptanceResult(None, "计划尚未完成，不能生成正式验收结论", coverage, pass_rate, failed)

    violations: list[str] = []
    threshold_checks = {
        "最低任务通过率": (criteria.min_pass_rate, pass_rate),
        "最低楼栋覆盖率": (criteria.min_building_coverage, coverage.passed["building"]),
        "最低单元覆盖率": (criteria.min_unit_coverage, coverage.passed["unit"]),
        "最低楼层覆盖率": (criteria.min_floor_coverage, coverage.passed["floor"]),
        "最低户覆盖率": (criteria.min_door_coverage, coverage.passed["door"]),
    }
    for label, (expected, actual) in threshold_checks.items():
        if expected is not None and actual < expected:
            violations.append(f"{label} {actual:g}% 未达到 {expected:g}%")
    if criteria.max_failed_tasks is not None and failed > criteria.max_failed_tasks:
        violations.append(f"失败任务数 {failed} 超过 {criteria.max_failed_tasks}")
    if criteria.max_manual_interventions is not None and plan.manual_interventions > criteria.max_manual_interventions:
        violations.append(f"人工干预次数 {plan.manual_interventions} 超过 {criteria.max_manual_interventions}")
    if violations:
        return AcceptanceResult("FAIL", "；".join(violations), coverage, pass_rate, failed)
    if criteria.is_complete():
        return AcceptanceResult("PASS", "所有已配置验收标准均已达到", coverage, pass_rate, failed)
    return AcceptanceResult("CONDITIONAL_PASS", "验收执行完成，等待官方阈值确认", coverage, pass_rate, failed)


class AcceptancePlanStore:
    """Persist only Aletheia-owned acceptance state with atomic replacement."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.plan_path = self.directory / "current-plan.json"
        self.criteria_path = self.directory / "criteria.json"

    def save(self, plan: AcceptancePlan) -> None:
        plan.updated_at = now_iso()
        self._write_json(self.plan_path, plan.to_storage_dict())

    def load_current(self) -> AcceptancePlan | None:
        document = self._read_json(self.plan_path)
        return AcceptancePlan.from_storage_dict(document) if document is not None else None

    def load_criteria(self) -> AcceptanceCriteria:
        document = self._read_json(self.criteria_path)
        return AcceptanceCriteria.from_dict(document) if document is not None else AcceptanceCriteria.empty()

    def save_criteria(self, criteria: AcceptanceCriteria) -> AcceptanceCriteria:
        self._write_json(self.criteria_path, criteria.to_dict())
        return criteria

    def mark_interrupted_runs(self) -> list[AcceptancePlan]:
        plan = self.load_current()
        if plan is None or plan.status not in ACTIVE_PLAN_STATUSES:
            return []
        plan.status = "interrupted"
        if plan.current_index is not None and 0 <= plan.current_index < len(plan.items):
            item = plan.items[plan.current_index]
            if item.status not in TERMINAL_ITEM_STATUSES:
                item.status = "unknown_after_restart"
                item.message = "后端重启前该任务结果未知；必须由操作员核对后处理"
        self.save(plan)
        return [plan]

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"无法读取验收状态文件：{exc}") from exc
        if not isinstance(document, dict):
            raise ValueError("验收状态文件必须是对象")
        return document

    def _write_json(self, target: Path, document: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary_name).replace(target)
        except Exception:
            Path(temporary_name).unlink(missing_ok=True)
            raise
