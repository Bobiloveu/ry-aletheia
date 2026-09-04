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
PREFLIGHT_STATUS_STATES = frozenset({
    "not_selected", "legacy", "pending", "applying_scenario", "settling",
    "restarting_dependencies", "ready", "restoring", "restored", "cancelled", "blocked",
})


def default_execution_preflight() -> dict[str, Any]:
    """Return the only safe default: no script change and no node restart."""
    return {
        "scenario_profile_id": None,
        "scenario_profile_name": None,
        "dependency_plan": {"enabled": False, "steps": []},
    }


def default_execution_preflight_status(value: object = None) -> dict[str, Any]:
    """Return an operator-readable status without exposing process controls."""
    if value is None:
        return {
            "state": "legacy",
            "message": "历史验收计划沿用原有逐项运行方式",
            "updated_at": None,
        }
    normalized = normalize_execution_preflight(value)
    selected = normalized["scenario_profile_id"] or normalized["dependency_plan"]["enabled"]
    return {
        "state": "pending" if selected else "not_selected",
        "message": "已冻结可选运行准备，开始验收时统一执行" if selected else "未启用额外运行准备，按常规验收流程执行",
        "updated_at": None,
    }


def normalize_execution_preflight_status(value: object, *, preflight: object) -> dict[str, Any]:
    """Keep persisted progress small, explicit and safe to render in a browser."""
    if value is None:
        return default_execution_preflight_status(preflight)
    if not isinstance(value, dict) or set(value) != {"state", "message", "updated_at"}:
        raise ValueError("验收计划运行准备状态格式不受支持")
    state, message, updated_at = value["state"], value["message"], value["updated_at"]
    if not isinstance(state, str) or state not in PREFLIGHT_STATUS_STATES:
        raise ValueError("验收计划运行准备状态无效")
    if not isinstance(message, str) or not message.strip() or len(message) > 240 or "\x00" in message:
        raise ValueError("验收计划运行准备说明无效")
    if updated_at is not None and (not isinstance(updated_at, str) or len(updated_at) > 64):
        raise ValueError("验收计划运行准备时间无效")
    return {"state": state, "message": message, "updated_at": updated_at}


def normalize_execution_preflight(value: object) -> dict[str, Any]:
    """Validate frozen, console-owned preflight state from plan storage.

    The browser never supplies the plan or process names directly.  This
    validation still treats persisted state as untrusted so a damaged plan
    cannot turn into arbitrary Supervisor control after an upgrade.
    """
    if value is None:
        return default_execution_preflight()
    if not isinstance(value, dict) or set(value) != {"scenario_profile_id", "scenario_profile_name", "dependency_plan"}:
        raise ValueError("验收计划前置配置格式不受支持")
    profile_id, profile_name = value["scenario_profile_id"], value["scenario_profile_name"]
    if profile_id is not None and (not isinstance(profile_id, str) or not profile_id or len(profile_id) > 64 or "\x00" in profile_id):
        raise ValueError("验收计划场景方案标识无效")
    if profile_name is not None and (not isinstance(profile_name, str) or not profile_name.strip() or len(profile_name) > 80):
        raise ValueError("验收计划场景方案名称无效")
    if (profile_id is None) != (profile_name is None):
        raise ValueError("验收计划场景方案信息不完整")
    dependency_plan = value["dependency_plan"]
    if not isinstance(dependency_plan, dict) or set(dependency_plan) != {"enabled", "steps"} or not isinstance(dependency_plan["enabled"], bool) or not isinstance(dependency_plan["steps"], list):
        raise ValueError("验收计划依赖编排格式无效")
    steps: list[dict[str, Any]] = []
    used_nodes: set[str] = set()
    for step in dependency_plan["steps"]:
        if not isinstance(step, dict) or set(step) - {"nodes", "wait_seconds"} or not isinstance(step.get("nodes"), list):
            raise ValueError("验收计划依赖步骤格式无效")
        nodes = step["nodes"]
        if not nodes or not all(isinstance(node, str) and node and len(node) <= 128 for node in nodes) or len(set(nodes)) != len(nodes):
            raise ValueError("验收计划依赖节点无效")
        if used_nodes.intersection(nodes):
            raise ValueError("验收计划依赖节点不能跨阶段重复")
        used_nodes.update(nodes)
        wait_seconds = step.get("wait_seconds", 0)
        if isinstance(wait_seconds, bool) or not isinstance(wait_seconds, int) or not 0 <= wait_seconds <= 300:
            raise ValueError("验收计划依赖等待时间无效")
        steps.append({"nodes": list(nodes), "wait_seconds": wait_seconds})
    if dependency_plan["enabled"] and not steps:
        raise ValueError("启用验收依赖编排时必须包含启动阶段")
    if not dependency_plan["enabled"] and steps:
        raise ValueError("未启用验收依赖编排时不能保存启动阶段")
    return {
        "scenario_profile_id": profile_id,
        "scenario_profile_name": profile_name,
        "dependency_plan": {"enabled": dependency_plan["enabled"], "steps": steps},
    }


def public_execution_preflight(value: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_execution_preflight(value)
    plan = normalized["dependency_plan"]
    return {
        "scenario_profile_id": normalized["scenario_profile_id"],
        "scenario_profile_name": normalized["scenario_profile_name"],
        "dependency_plan_enabled": plan["enabled"],
        "dependency_stage_count": len(plan["steps"]),
        "dependency_node_count": sum(len(step["nodes"]) for step in plan["steps"]),
    }


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
    min_physical_building_coverage: float | None = None
    min_floor_coverage: float | None = None
    min_door_coverage: float | None = None
    max_failed_tasks: int | None = None
    max_manual_interventions: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "min_pass_rate",
            "min_physical_building_coverage",
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
            "min_pass_rate", "min_physical_building_coverage", "min_floor_coverage",
            "min_door_coverage", "max_failed_tasks", "max_manual_interventions",
        }
        legacy = {"min_building_coverage", "min_unit_coverage"}
        unexpected = set(document) - expected - legacy
        if unexpected:
            raise ValueError(f"验收标准包含未知字段：{', '.join(sorted(unexpected))}")
        # Aletheia 2.0 initially stored connected units as separate
        # "building" / "unit" coverage dimensions.  Keep such saved criteria
        # readable, but use the finer physical-building threshold thereafter.
        values = {name: document.get(name) for name in expected}
        if values["min_physical_building_coverage"] is None:
            values["min_physical_building_coverage"] = document.get("min_unit_coverage", document.get("min_building_coverage"))
        return cls(**values)

    def to_dict(self) -> dict[str, float | int | None]:
        return {
            "min_pass_rate": self.min_pass_rate,
            "min_physical_building_coverage": self.min_physical_building_coverage,
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
    unit: int | None
    mode: str
    random_seed: int
    task_pool_size: int
    items: list[AcceptancePlanItem]
    criteria_snapshot: dict[str, float | int | None]
    # ``None`` is reserved for schema-1 plans created before plan-wide
    # preflight existed. New plans always receive a normalized dictionary.
    execution_preflight: dict[str, Any] | None = field(default_factory=default_execution_preflight)
    execution_preflight_status: dict[str, Any] = field(default_factory=default_execution_preflight_status)
    warnings: list[str] = field(default_factory=list)
    status: str = "ready"
    current_index: int | None = None
    run_id: str | None = None
    manual_interventions: int = 0
    report_filename: str | None = None

    def to_storage_dict(self) -> dict[str, Any]:
        return {
            "schema": 3,
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "scope_type": self.scope_type,
            "community": self.community,
            "building": self.building,
            "unit": self.unit,
            "mode": self.mode,
            "random_seed": self.random_seed,
            "task_pool_size": self.task_pool_size,
            "items": [item.to_storage_dict() for item in self.items],
            "criteria_snapshot": self.criteria_snapshot,
            "execution_preflight": normalize_execution_preflight(self.execution_preflight) if self.execution_preflight is not None else None,
            "execution_preflight_status": normalize_execution_preflight_status(
                self.execution_preflight_status,
                preflight=self.execution_preflight,
            ),
            "warnings": self.warnings,
            "status": self.status,
            "current_index": self.current_index,
            "run_id": self.run_id,
            "manual_interventions": self.manual_interventions,
            "report_filename": self.report_filename,
        }

    @classmethod
    def from_storage_dict(cls, document: dict[str, Any]) -> "AcceptancePlan":
        if document.get("schema") not in {1, 2, 3} or not isinstance(document.get("items"), list):
            raise ValueError("验收计划文件格式不受支持")
        criteria = AcceptanceCriteria.from_dict(dict(document.get("criteria_snapshot") or {}))
        stored_preflight = None if document.get("schema") == 1 else document.get("execution_preflight")
        stored_preflight_status = None if document.get("schema") == 1 else document.get("execution_preflight_status")
        plan = cls(
            plan_id=str(document["plan_id"]),
            created_at=str(document["created_at"]),
            updated_at=str(document["updated_at"]),
            scope_type=str(document["scope_type"]),
            community=str(document["community"]),
            building=int(document["building"]) if document.get("building") is not None else None,
            unit=int(document["unit"]) if document.get("unit") is not None else None,
            mode=str(document["mode"]),
            random_seed=int(document["random_seed"]),
            task_pool_size=int(document["task_pool_size"]),
            items=[AcceptancePlanItem.from_storage_dict(item) for item in document["items"] if isinstance(item, dict)],
            criteria_snapshot=criteria.to_dict(),
            execution_preflight=None if stored_preflight is None else normalize_execution_preflight(stored_preflight),
            execution_preflight_status=normalize_execution_preflight_status(
                stored_preflight_status,
                preflight=stored_preflight,
            ),
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
            "unit": self.unit,
            "mode": self.mode,
            "task_pool_size": self.task_pool_size,
            "selection_summary": selection_summary(self.items),
            "execution_preflight": public_execution_preflight(self.execution_preflight) if self.execution_preflight is not None else None,
            "execution_preflight_status": normalize_execution_preflight_status(
                self.execution_preflight_status,
                preflight=self.execution_preflight,
            ),
            "items": [item.to_public_dict() for item in self.items],
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
        unit: int | None = None,
        execution_preflight: dict[str, Any] | None = None,
    ) -> AcceptancePlan:
        pool = snapshot.select(scope_type, community, building, unit)
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
        normalized_preflight = normalize_execution_preflight(execution_preflight)
        return AcceptancePlan(
            plan_id=uuid.uuid4().hex[:12],
            created_at=timestamp,
            updated_at=timestamp,
            scope_type=scope_type,
            community=community,
            building=building if scope_type == "building" else None,
            unit=unit if scope_type == "building" else None,
            mode=mode,
            random_seed=random_seed,
            task_pool_size=len(pool),
            items=[AcceptancePlanItem.from_task(task) for task in selected],
            criteria_snapshot=criteria.to_dict(),
            execution_preflight=normalized_preflight,
            execution_preflight_status=default_execution_preflight_status(normalized_preflight),
            warnings=_coverage_warnings(pool, selected_size, community_scope=scope_type == "community"),
        )


def _coverage_aware_order(tasks: list[AcceptanceTask], *, community_scope: bool, seed: int) -> list[AcceptanceTask]:
    ordered = sorted(tasks, key=lambda task: (task.parameters.building, task.parameters.unit, task.parameters.floor, task.parameters.door, task.filename))
    randomizer = random.Random(seed)
    tie_break = {task.filename: randomizer.random() for task in ordered}
    selected: list[AcceptanceTask] = []
    remaining = list(ordered)
    physical_building_count: dict[tuple[int, int], int] = {}
    floor_count: dict[tuple[int, int, int], int] = {}
    door_count: dict[tuple[int, int, int, int], int] = {}
    while remaining:
        previous = selected[-1].parameters if selected else None

        def score(task: AcceptanceTask) -> tuple[float, ...]:
            p = task.parameters
            physical_building = (p.building, p.unit)
            floor = (*physical_building, p.floor)
            door = (*floor, p.door)
            return (
                float(physical_building_count.get(physical_building, 0)) if community_scope else 0.0,
                float(floor_count.get(floor, 0)),
                float(door_count.get(door, 0)),
                float(previous is not None and physical_building == (previous.building, previous.unit)),
                float(previous is not None and p.floor == previous.floor),
                tie_break[task.filename],
            )

        chosen = min(remaining, key=score)
        remaining.remove(chosen)
        selected.append(chosen)
        p = chosen.parameters
        physical_building = (p.building, p.unit)
        floor = (*physical_building, p.floor)
        door = (*floor, p.door)
        physical_building_count[physical_building] = physical_building_count.get(physical_building, 0) + 1
        floor_count[floor] = floor_count.get(floor, 0) + 1
        door_count[door] = door_count.get(door, 0) + 1
    return selected


def _coverage_warnings(pool: list[AcceptanceTask], selected_size: int, *, community_scope: bool) -> list[str]:
    # A sample is deliberately not a census: a large community can have
    # thousands of homes.  Coverage counts belong in the neutral plan summary,
    # not as a warning merely because an intentionally small sample cannot
    # visit every floor or door.
    del pool, selected_size, community_scope
    return []


def selection_summary(items: list[AcceptancePlanItem]) -> dict[str, int]:
    return {
        "tasks": len(items),
        "physical_buildings": len({(item.parameters.building, item.parameters.unit) for item in items}),
        "floors": len({(item.parameters.building, item.parameters.unit, item.parameters.floor) for item in items}),
        "doors": len({(item.parameters.building, item.parameters.unit, item.parameters.floor, item.parameters.door) for item in items}),
    }


def coverage_summary(plan: AcceptancePlan) -> CoverageSummary:
    dimensions = {
        "physical_building": lambda item: (item.parameters.building, item.parameters.unit),
        "floor": lambda item: (item.parameters.building, item.parameters.unit, item.parameters.floor),
        "door": lambda item: (item.parameters.building, item.parameters.unit, item.parameters.floor, item.parameters.door),
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
    # Kept as an argument only so previously stored plans and internal callers
    # remain readable.  New deployment acceptance is deliberately not a form
    # of operator-entered percentage thresholds: every planned task must pass.
    del criteria
    coverage = coverage_summary(plan)
    terminal_items = [item for item in plan.items if item.status in {"passed", "failed"}]
    passed = sum(item.status == "passed" for item in terminal_items)
    failed = sum(item.status == "failed" for item in terminal_items)
    pass_rate = round(passed / len(terminal_items) * 100, 1) if terminal_items else 0.0
    if plan.status != "completed":
        return AcceptanceResult(None, "计划尚未完成；完成全部计划任务后才会给出本次验收结论", coverage, pass_rate, failed)

    total = len(plan.items)
    non_passed = total - passed
    summary = selection_summary(plan.items)
    label = "本次抽样" if plan.mode == "sample" else "本次全量验收"
    coverage_text = f"覆盖 {summary['physical_buildings']} 个物理楼宇单元、{summary['floors']} 个楼层、{summary['doors']} 户"
    if total > 0 and non_passed == 0:
        return AcceptanceResult(
            f"{plan.mode}_pass",
            f"{label}通过：{passed}/{total} 项通过，通过率 {pass_rate:.1f}%；{coverage_text}。"
            + ("该结论仅代表本次抽样，不代表全小区全量验收。" if plan.mode == "sample" else ""),
            coverage,
            pass_rate,
            failed,
        )
    return AcceptanceResult(
        f"{plan.mode}_fail",
        f"{label}不通过：{passed}/{total} 项通过，通过率 {pass_rate:.1f}%；存在 {non_passed} 项未通过。{coverage_text}。",
        coverage,
        pass_rate,
        failed,
    )


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
