"""Frozen deployment-acceptance plans, criteria and local persistence."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
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
from .location_manifest import LocationManifestError, button_sequence
from .models import MultiDestination, MultiTaskRequest, TaskParameters, now_iso


ACTIVE_PLAN_STATUSES = frozenset({"preparing", "running", "awaiting_recovery", "recovering", "cancelling"})
TERMINAL_ITEM_STATUSES = frozenset({"passed", "failed", "cancelled"})
PREFLIGHT_STATUS_STATES = frozenset({
    "not_selected", "legacy", "pending", "applying_scenario", "settling",
    "restarting_dependencies", "ready", "restoring", "restored", "cancelled", "blocked",
})
DEPENDENCY_PROGRESS_STATES = frozenset({
    "pending", "restarting", "waiting_stable", "settling", "ready", "blocked", "cancelled",
})
SUPERVISOR_PROGRESS_STATUSES = frozenset({
    "PENDING", "RUNNING", "STARTING", "STOPPED", "BACKOFF", "EXITED", "FATAL", "MISSING", "UNKNOWN",
})
EXECUTION_MODES = frozenset({"single_r6s", "multi_r6b"})
MULTI_CHAIN_MODES = frozenset({"single", "chain", "combined"})


def normalize_execution_mode(value: object) -> str:
    if not isinstance(value, str) or value not in EXECUTION_MODES:
        raise ValueError("任务执行模式必须是 single_r6s 或 multi_r6b")
    return value


def normalize_multi_options(value: object, *, require_frozen_chains: bool = False) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("多点任务配置字段不受支持")
    compact_keys = {"out_eguard", "return_origin", "chain_mode", "floor_ranges", "max_points_per_task"}
    preview_keys = {"task_uuid", "destinations"}
    keys = set(value)
    required_keys = {"out_eguard", "return_origin", "chain_mode"}
    if not required_keys.issubset(keys) or keys - compact_keys - preview_keys - {"chains"}:
        raise ValueError("多点任务配置字段不受支持")
    if not isinstance(value["out_eguard"], bool) or not isinstance(value["return_origin"], bool):
        raise ValueError("多点任务摆渡和返程选项必须是布尔值")
    if value["chain_mode"] not in MULTI_CHAIN_MODES:
        raise ValueError("多点任务编排模式无效")
    max_points_per_task = value.get("max_points_per_task", 10)
    if isinstance(max_points_per_task, bool) or not isinstance(max_points_per_task, int) or not 1 <= max_points_per_task <= 10:
        raise ValueError("单任务最多配送点必须是 1 到 10 的整数")
    floor_ranges = _normalize_multi_floor_ranges(value.get("floor_ranges", []))
    if "chains" not in value or (keys & preview_keys and not require_frozen_chains):
        if require_frozen_chains:
            raise ValueError("多点任务计划缺少已冻结任务链")
        return {
            "out_eguard": value["out_eguard"],
            "return_origin": value["return_origin"],
            "chain_mode": value["chain_mode"],
            "max_points_per_task": max_points_per_task,
            "floor_ranges": floor_ranges,
        }
    chains = value["chains"]
    if not isinstance(chains, list) or not chains:
        raise ValueError("多点任务至少需要一条任务链")
    normalized_chains: list[dict[str, Any]] = []
    for chain in chains:
        if not isinstance(chain, dict) or set(chain) != {"task_uuid", "destinations"}:
            raise ValueError("多点任务链字段不受支持")
        task_uuid = chain["task_uuid"]
        destinations = chain["destinations"]
        if not isinstance(task_uuid, str) or not task_uuid.strip() or not isinstance(destinations, list):
            raise ValueError("多点任务链格式无效")
        parsed_destinations = tuple(MultiDestination.from_dict(item) for item in destinations)
        if not parsed_destinations:
            raise ValueError("多点任务链至少需要一个配送点")
        if value["chain_mode"] == "single" and len(parsed_destinations) != 1:
            raise ValueError("单点链路只能包含一个配送点")
        if len({item.delivery_code for item in parsed_destinations}) != len(parsed_destinations):
            raise ValueError("同一多点任务中的配送码必须唯一")
        normalized_chains.append({"task_uuid": task_uuid, "destinations": [item.to_dict() for item in parsed_destinations]})
    if value["chain_mode"] == "combined" and len(normalized_chains) < 2:
        raise ValueError("组合验收至少需要单点基线和一条多点链路")
    return {
        "out_eguard": value["out_eguard"],
        "return_origin": value["return_origin"],
        "chain_mode": value["chain_mode"],
        "max_points_per_task": max_points_per_task,
        "floor_ranges": floor_ranges,
        "chains": normalized_chains,
    }


def _normalize_multi_floor_ranges(value: object) -> list[dict[str, int]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("模板楼层范围必须是数组")
    normalized: list[dict[str, int]] = []
    seen: set[tuple[int, int]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"building", "unit", "min_floor", "max_floor"}:
            raise ValueError("模板楼层范围字段无效")
        values: dict[str, int] = {}
        for key in ("building", "unit", "min_floor", "max_floor"):
            raw = item[key]
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise ValueError("模板楼层范围必须使用整数")
            values[key] = raw
        key = (values["building"], values["unit"])
        if key in seen:
            raise ValueError(f"{key[0]}栋{key[1]}单元模板楼层范围重复")
        try:
            button_sequence(values["min_floor"], values["max_floor"])
        except LocationManifestError as exc:
            raise ValueError(str(exc).replace("电梯按钮范围无效", "最低层和最高层范围无效")) from exc
        seen.add(key)
        normalized.append(values)
    return sorted(normalized, key=lambda item: (item["building"], item["unit"]))


def default_execution_preflight() -> dict[str, Any]:
    """Return the only safe default: no script change and no node restart."""
    return {
        "scenario_profile_id": None,
        "scenario_profile_name": None,
        "dependency_plan": {"enabled": False, "steps": []},
        "automatic_return": False,
    }


def default_execution_preflight_status(value: object = None) -> dict[str, Any]:
    """Return an operator-readable status without exposing process controls."""
    if value is None:
        return {
            "state": "legacy",
            "message": "历史验收计划沿用原有逐项运行方式",
            "updated_at": None,
            "dependency_progress": None,
        }
    normalized = normalize_execution_preflight(value)
    selected = (
        normalized["scenario_profile_id"]
        or normalized["dependency_plan"]["enabled"]
        or normalized["automatic_return"]
    )
    return {
        "state": "pending" if selected else "not_selected",
        "message": "已冻结可选运行准备，开始验收时统一执行" if selected else "未启用额外运行准备，按常规验收流程执行",
        "updated_at": None,
        "dependency_progress": _default_dependency_progress(normalized),
    }


def _default_dependency_progress(preflight: dict[str, Any]) -> dict[str, Any] | None:
    """Expose only frozen names and a pre-start state for dependency plans."""
    plan = preflight["dependency_plan"]
    if not plan["enabled"]:
        return None
    return {"stages": [
        {
            "index": index,
            "state": "pending",
            "nodes": [{"name": name, "status": "PENDING"} for name in step["nodes"]],
        }
        for index, step in enumerate(plan["steps"], start=1)
    ]}


def _normalize_dependency_progress(value: object, *, preflight: dict[str, Any]) -> dict[str, Any] | None:
    """Accept only snapshots that exactly match the frozen dependency plan."""
    expected = _default_dependency_progress(preflight)
    if expected is None:
        if value is not None:
            raise ValueError("未启用依赖编排时不能保存节点准备状态")
        return None
    if value is None:
        return expected
    if not isinstance(value, dict) or set(value) != {"stages"} or not isinstance(value["stages"], list):
        raise ValueError("验收计划依赖准备状态格式无效")
    stages = value["stages"]
    expected_stages = expected["stages"]
    if len(stages) != len(expected_stages):
        raise ValueError("验收计划依赖准备阶段数量无效")
    normalized_stages: list[dict[str, Any]] = []
    for source, frozen in zip(stages, expected_stages):
        if not isinstance(source, dict) or set(source) != {"index", "state", "nodes"}:
            raise ValueError("验收计划依赖准备阶段格式无效")
        if (
            source["index"] != frozen["index"]
            or not isinstance(source["state"], str)
            or source["state"] not in DEPENDENCY_PROGRESS_STATES
        ):
            raise ValueError("验收计划依赖准备阶段无效")
        nodes = source["nodes"]
        frozen_nodes = frozen["nodes"]
        if not isinstance(nodes, list) or len(nodes) != len(frozen_nodes):
            raise ValueError("验收计划依赖准备节点数量无效")
        normalized_nodes: list[dict[str, str]] = []
        for node, frozen_node in zip(nodes, frozen_nodes):
            if not isinstance(node, dict) or set(node) != {"name", "status"}:
                raise ValueError("验收计划依赖准备节点格式无效")
            if (
                node["name"] != frozen_node["name"]
                or not isinstance(node["status"], str)
                or node["status"] not in SUPERVISOR_PROGRESS_STATUSES
            ):
                raise ValueError("验收计划依赖准备节点无效")
            normalized_nodes.append({"name": node["name"], "status": node["status"]})
        normalized_stages.append({"index": frozen["index"], "state": source["state"], "nodes": normalized_nodes})
    return {"stages": normalized_stages}


def normalize_execution_preflight_status(value: object, *, preflight: object) -> dict[str, Any]:
    """Keep persisted progress small, explicit and safe to render in a browser."""
    if value is None:
        return default_execution_preflight_status(preflight)
    if not isinstance(value, dict) or set(value) not in ({"state", "message", "updated_at"}, {"state", "message", "updated_at", "dependency_progress"}):
        raise ValueError("验收计划运行准备状态格式不受支持")
    normalized_preflight = normalize_execution_preflight(preflight)
    state, message, updated_at = value["state"], value["message"], value["updated_at"]
    if not isinstance(state, str) or state not in PREFLIGHT_STATUS_STATES:
        raise ValueError("验收计划运行准备状态无效")
    if not isinstance(message, str) or not message.strip() or len(message) > 240 or "\x00" in message:
        raise ValueError("验收计划运行准备说明无效")
    if updated_at is not None and (not isinstance(updated_at, str) or len(updated_at) > 64):
        raise ValueError("验收计划运行准备时间无效")
    return {
        "state": state,
        "message": message,
        "updated_at": updated_at,
        "dependency_progress": _normalize_dependency_progress(value.get("dependency_progress"), preflight=normalized_preflight),
    }


def normalize_execution_preflight(value: object) -> dict[str, Any]:
    """Validate frozen, console-owned preflight state from plan storage.

    The browser never supplies the plan or process names directly.  This
    validation still treats persisted state as untrusted so a damaged plan
    cannot turn into arbitrary Supervisor control after an upgrade.
    """
    if value is None:
        return default_execution_preflight()
    allowed_keys = {
        frozenset({"scenario_profile_id", "scenario_profile_name", "dependency_plan"}),
        frozenset({"scenario_profile_id", "scenario_profile_name", "dependency_plan", "automatic_return"}),
    }
    if not isinstance(value, dict) or frozenset(value) not in allowed_keys:
        raise ValueError("验收计划前置配置格式不受支持")
    profile_id, profile_name = value["scenario_profile_id"], value["scenario_profile_name"]
    if profile_id is not None and (not isinstance(profile_id, str) or not profile_id or len(profile_id) > 64 or "\x00" in profile_id):
        raise ValueError("验收计划场景方案标识无效")
    if profile_name is not None and (not isinstance(profile_name, str) or not profile_name.strip() or len(profile_name) > 80):
        raise ValueError("验收计划场景方案名称无效")
    if (profile_id is None) != (profile_name is None):
        raise ValueError("验收计划场景方案信息不完整")
    dependency_plan = value["dependency_plan"]
    automatic_return = value.get("automatic_return", False)
    if not isinstance(automatic_return, bool):
        raise ValueError("验收计划自动返程配置无效")
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
        "automatic_return": automatic_return,
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
        "automatic_return_enabled": normalized["automatic_return"],
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
    multi_request: MultiTaskRequest | None = None
    source_paths: tuple[str, ...] = ()
    source_hashes: tuple[str, ...] = ()
    delivery_evidence: list[dict[str, str]] | None = None

    @classmethod
    def from_task(cls, task: AcceptanceTask) -> "AcceptancePlanItem":
        return cls(
            filename=task.filename,
            source_path=str(task.path),
            parameters=task.parameters,
            task_group_name=task.task_group_name,
            warnings=list(task.warnings),
            sha256=task.sha256,
            source_paths=(str(task.path),),
            source_hashes=(task.sha256,),
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
            "multi_request": self.multi_request.to_dict() if self.multi_request is not None else None,
            "source_paths": list(self.source_paths),
            "source_hashes": list(self.source_hashes),
            "delivery_evidence": self.delivery_evidence,
        }

    @classmethod
    def from_storage_dict(cls, document: dict[str, Any]) -> "AcceptancePlanItem":
        parameters = document.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError("冻结任务缺少参数")
        stored_request = document.get("multi_request")
        multi_request = MultiTaskRequest.from_dict(stored_request) if stored_request is not None else None
        parameter_values = {
            name: int(parameters[name]) if name != "community" else str(parameters[name])
            for name in ("community", "building", "unit", "floor", "door")
        }
        parameter_values["execution_mode"] = str(parameters.get("execution_mode", "single_r6s"))
        source_paths = tuple(str(item) for item in document.get("source_paths", []) if isinstance(item, str))
        source_hashes = tuple(str(item) for item in document.get("source_hashes", []) if isinstance(item, str))
        if not source_paths:
            source_paths = (str(document["source_path"]),)
        if not source_hashes:
            source_hashes = (str(document["sha256"]),)
        return cls(
            filename=str(document["filename"]),
            source_path=str(document["source_path"]),
            parameters=TaskParameters(**parameter_values),
            task_group_name=document.get("task_group_name") if isinstance(document.get("task_group_name"), str) else None,
            warnings=[str(value) for value in document.get("warnings", [])],
            sha256=str(document["sha256"]),
            status=str(document.get("status", "planned")),
            message=str(document.get("message", "")),
            started_at=document.get("started_at") if isinstance(document.get("started_at"), str) else None,
            finished_at=document.get("finished_at") if isinstance(document.get("finished_at"), str) else None,
            duration_s=float(document["duration_s"]) if document.get("duration_s") is not None else None,
            trajectory=document.get("trajectory") if isinstance(document.get("trajectory"), dict) else None,
            multi_request=multi_request,
            source_paths=source_paths,
            source_hashes=source_hashes,
            delivery_evidence=document.get("delivery_evidence") if isinstance(document.get("delivery_evidence"), list) else None,
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
            "multi_request": self.multi_request.to_dict() if self.multi_request is not None else None,
            "source_paths": list(self.source_paths),
            "delivery_evidence": self.delivery_evidence,
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
    execution_mode: str = "single_r6s"
    multi_options: dict[str, Any] | None = None

    def to_storage_dict(self) -> dict[str, Any]:
        return {
            "schema": 5,
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
            "execution_mode": normalize_execution_mode(self.execution_mode),
            "multi_options": normalize_multi_options(self.multi_options),
        }

    @classmethod
    def from_storage_dict(cls, document: dict[str, Any]) -> "AcceptancePlan":
        if document.get("schema") not in {1, 2, 3, 4, 5} or not isinstance(document.get("items"), list):
            raise ValueError("验收计划文件格式不受支持")
        criteria = AcceptanceCriteria.from_dict(dict(document.get("criteria_snapshot") or {}))
        stored_preflight = None if document.get("schema") == 1 else document.get("execution_preflight")
        stored_preflight_status = None if document.get("schema") == 1 else document.get("execution_preflight_status")
        execution_mode = normalize_execution_mode(document.get("execution_mode", "single_r6s"))
        multi_options = normalize_multi_options(document.get("multi_options"), require_frozen_chains=True)
        if execution_mode == "single_r6s" and multi_options is not None:
            raise ValueError("单点任务计划不能包含多点任务配置")
        if execution_mode == "multi_r6b" and multi_options is None:
            raise ValueError("多点任务计划缺少多点任务配置")
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
            execution_mode=execution_mode,
            multi_options=multi_options,
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
            "execution_mode": normalize_execution_mode(self.execution_mode),
            "multi_options": normalize_multi_options(self.multi_options),
            "conclusion": result.to_dict(),
        }


def re_plan_id(value: str) -> bool:
    return bool(__import__("re").fullmatch(r"[0-9a-f]{12}", value))


def select_multi_requests(
    requests: list[MultiTaskRequest] | tuple[MultiTaskRequest, ...],
    *,
    scope_type: str,
    community: str,
    building: int | None = None,
    unit: int | None = None,
) -> list[MultiTaskRequest]:
    """Filter frozen R6B chains by the same community/building scope as R6S."""
    if scope_type not in {"community", "building"}:
        raise ValueError("验收范围必须是 community 或 building")
    if scope_type == "building" and (
        isinstance(building, bool) or not isinstance(building, int)
        or isinstance(unit, bool) or not isinstance(unit, int)
    ):
        raise ValueError("请选择实际存在的物理楼宇单元")
    selected: list[MultiTaskRequest] = []
    for request in requests:
        if request.community != community:
            continue
        if scope_type == "building":
            if not all(
                destination.building == str(building) and destination.unit == str(unit)
                for destination in request.destinations
            ):
                continue
        selected.append(request)
    if not selected:
        raise ValueError("所选范围不存在可用多点任务")
    return selected


def _random_delivery_point(
    *,
    building: int,
    unit: int,
    floor: int,
    door_suffix: str,
    cargo_type: int,
    door: str | None = None,
) -> MultiDestination:
    return MultiDestination(
        building=str(building),
        unit=str(unit),
        floor=str(floor),
        door=door or f"{floor}{door_suffix}",
        cargo_type=cargo_type,
        delivery_code="pending",
    )


def _generated_multi_requests(
    snapshot: Any,
    *,
    scope_type: str,
    community: str,
    building: int | None,
    unit: int | None,
    chain_mode: str,
    mode: str,
    sample_size: int | None,
    max_points_per_task: int,
    out_eguard: bool,
    return_origin: bool,
    floor_ranges: list[dict[str, int]],
    seed: int,
) -> tuple[list[MultiTaskRequest], int]:
    """Generate valid R6B destinations from route templates in the frozen catalog.

    The directory stores route capabilities, not business addresses. Generic
    ``n_nXX`` templates are expanded across the operator-supplied elevator
    button range while retaining the template's door suffix; special
    physical-floor files retain their documented physical-floor mapping.
    """
    if scope_type not in {"community", "building"}:
        raise ValueError("验收范围必须是 community 或 building")
    statuses = [status for status in snapshot.buildings if status.community == community]
    if scope_type == "building":
        statuses = [status for status in statuses if status.building == building and status.unit == unit]
    if not statuses:
        raise ValueError("所选范围不存在可用多点任务楼宇")
    randomizer = random.Random(seed)
    ranges = {(item["building"], item["unit"]): item for item in floor_ranges}
    status_keys = {(status.building, status.unit) for status in statuses}
    unknown_ranges = sorted(set(ranges) - status_keys)
    if unknown_ranges:
        building_number, unit_number = unknown_ranges[0]
        raise ValueError(f"{building_number}栋{unit_number}单元不在当前验收范围内")
    destination_pools: list[list[MultiDestination]] = []
    for status in statuses:
        if not status.available:
            raise ValueError(f"{status.building}栋{status.unit}单元多点任务目录不可用：{'；'.join(status.issues)}")
        destinations: list[MultiDestination] = []
        special_destinations: set[tuple[int, int]] = set()
        for point in status.special_points:
            if not point.available:
                continue
            special_destinations.add((point.physical_floor, point.door))
            destinations.append(_random_delivery_point(
                building=status.building,
                unit=status.unit,
                floor=point.physical_floor,
                door_suffix=str(point.door),
                cargo_type=randomizer.choice([1, 2, 0, -1]),
                door=str(point.door),
            ))
        for template in status.templates:
            if not template.available:
                continue
            range_config = ranges.get((status.building, status.unit))
            if range_config is None:
                raise ValueError(f"{status.building}栋{status.unit}单元缺少模板楼层范围配置")
            for floor in button_sequence(range_config["min_floor"], range_config["max_floor"]):
                door = int(f"{floor}{template.door_suffix}")
                if (floor, door) in special_destinations:
                    continue
                destinations.append(_random_delivery_point(
                    building=status.building,
                    unit=status.unit,
                    floor=floor,
                    door_suffix=template.door_suffix,
                    cargo_type=randomizer.choice([1, 2, 0, -1]),
                    door=str(door),
                ))
        if not destinations:
            raise ValueError(f"{status.building}栋{status.unit}单元未找到可用楼层任务")
        destinations.sort(key=lambda item: (int(item.floor), int(item.door)))
        destination_pools.append(destinations)

    point_count = sum(len(pool) for pool in destination_pools)
    if mode == "sample" and sample_size is not None and sample_size > point_count:
        raise ValueError(f"当前范围最多可生成 {point_count} 条不重复任务")

    groups: list[list[MultiDestination]] = []
    if chain_mode == "single":
        groups = [[destination] for pool in destination_pools for destination in pool]
        randomizer.shuffle(groups)
        if mode == "sample":
            assert sample_size is not None
            groups = groups[:sample_size]
    elif mode == "full":
        for pool in destination_pools:
            randomizer.shuffle(pool)
            groups.extend(
                pool[index:index + max_points_per_task]
                for index in range(0, len(pool), max_points_per_task)
            )
    else:
        assert sample_size is not None
        remaining_pools = [list(pool) for pool in destination_pools]
        for pool in remaining_pools:
            randomizer.shuffle(pool)
        for group_index in range(sample_size):
            remaining_task_count = sample_size - group_index
            available_pool_indexes = [index for index, pool in enumerate(remaining_pools) if pool]
            pool = remaining_pools[randomizer.choice(available_pool_indexes)]
            available_point_count = sum(len(candidate_pool) for candidate_pool in remaining_pools)
            group_limit = min(
                max_points_per_task,
                len(pool),
                available_point_count - (remaining_task_count - 1),
            )
            group_size = randomizer.randint(1, group_limit)
            groups.append([pool.pop() for _ in range(group_size)])

    request_groups = groups
    if chain_mode == "combined":
        request_groups = [request_group for group in groups for request_group in ([group[0]], group)]

    requests: list[MultiTaskRequest] = []
    for group in request_groups:
        frozen_group = tuple(
            replace(destination, delivery_code=f"{index:02d}")
            for index, destination in enumerate(group, 1)
        )
        requests.append(MultiTaskRequest(
            community=community,
            out_eguard=out_eguard,
            return_origin=return_origin,
            destinations=frozen_group,
            task_uuid=f"task-{len(requests) + 1:03d}",
        ))
    return requests, point_count


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

    @staticmethod
    def create_multi(
        snapshot: Any,
        *,
        scope_type: str,
        community: str,
        building: int | None,
        unit: int | None,
        mode: str,
        sample_size: int | None,
        random_seed: int | None,
        criteria: AcceptanceCriteria,
        multi_options: dict[str, Any],
        execution_preflight: dict[str, Any] | None = None,
    ) -> AcceptancePlan:
        normalized = normalize_multi_options(multi_options)
        assert normalized is not None
        if mode not in {"full", "sample"}:
            raise ValueError("计划模式必须是 full 或 sample")
        if mode == "full":
            if sample_size is not None:
                raise ValueError("全量计划不接受抽样数量")
        elif isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size < 1:
            raise ValueError("抽样数量必须是大于等于 1 的整数")
        if random_seed is None:
            random_seed = secrets.randbits(63)
        if isinstance(random_seed, bool) or not isinstance(random_seed, int) or random_seed < 0:
            raise ValueError("随机种子无效")
        requests, point_count = _generated_multi_requests(
            snapshot,
            scope_type=scope_type,
            community=community,
            building=building,
            unit=unit,
            chain_mode=normalized["chain_mode"],
            mode=mode,
            sample_size=sample_size,
            max_points_per_task=normalized["max_points_per_task"],
            out_eguard=normalized["out_eguard"],
            return_origin=normalized["return_origin"],
            floor_ranges=normalized["floor_ranges"],
            seed=random_seed,
        )
        for request in requests:
            if len({(item.building, item.unit) for item in request.destinations}) != 1:
                raise ValueError("同一多点任务链必须属于同一栋同一单元")
        if len({request.task_uuid for request in requests}) != len(requests):
            raise ValueError("多点任务链的任务 UUID 必须唯一")
        selected = select_multi_requests(requests, scope_type=scope_type, community=community, building=building, unit=unit)
        items: list[AcceptancePlanItem] = []
        for request in selected:
            first = request.destinations[0]
            try:
                parameters = TaskParameters(
                    community=community,
                    building=int(first.building),
                    unit=int(first.unit),
                    floor=int(first.floor),
                    door=int(first.door),
                    execution_mode="multi_r6b",
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("多点目的地的栋、单元、楼层和门牌必须是数字") from exc
            source_paths: list[str] = []
            floor_source_paths: list[str] = []
            template_names: list[str] = []
            for destination in request.destinations:
                match = snapshot.validate_destination(
                    community, int(destination.building), int(destination.unit), destination.floor, destination.door
                )
                if not match.available or match.forward_path is None or match.return_path is None:
                    raise ValueError(f"目的地 {destination.floor} 楼 {destination.door} 不可用：{match.reason}")
                floor_source_paths.append(str(match.forward_path))
                template_names.append(match.forward_path.name)
                source_paths.extend((str(match.forward_path), str(match.return_path)))
            gate = snapshot.gate_status(community)
            if request.out_eguard and not gate.forward:
                raise ValueError("已选择摆渡层去程，但 sub_outdoor_eguard.json 不可用")
            if request.out_eguard and gate.forward:
                source_paths.append(str(gate.forward))
            unique_paths = tuple(dict.fromkeys(source_paths))
            hashes = tuple(hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in unique_paths)
            display_names = tuple(dict.fromkeys(template_names))
            if not display_names:
                raise ValueError("多点任务缺少楼层模板来源")
            primary_source = floor_source_paths[0]
            primary_hash = hashlib.sha256(Path(primary_source).read_bytes()).hexdigest()
            items.append(
                AcceptancePlanItem(
                    filename=" + ".join(display_names),
                    source_path=primary_source,
                    parameters=parameters,
                    task_group_name=None,
                    warnings=[],
                    sha256=primary_hash,
                    multi_request=request,
                    source_paths=unique_paths,
                    source_hashes=hashes,
                )
            )
        timestamp = now_iso()
        normalized_preflight = normalize_execution_preflight(execution_preflight)
        frozen_options = {
            "out_eguard": normalized["out_eguard"],
            "return_origin": normalized["return_origin"],
            "chain_mode": normalized["chain_mode"],
            "max_points_per_task": normalized["max_points_per_task"],
            "floor_ranges": normalized["floor_ranges"],
            "chains": [{
                "task_uuid": request.task_uuid,
                "destinations": [destination.to_dict() for destination in request.destinations],
            } for request in selected],
        }
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
            task_pool_size=point_count,
            items=items,
            criteria_snapshot=criteria.to_dict(),
            execution_preflight=normalized_preflight,
            execution_preflight_status=default_execution_preflight_status(normalized_preflight),
            execution_mode="multi_r6b",
            multi_options=frozen_options,
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


def _item_locations(item: AcceptancePlanItem) -> list[tuple[str, str, str, str]]:
    if item.multi_request is not None:
        return [
            (destination.building, destination.unit, destination.floor, destination.door)
            for destination in item.multi_request.destinations
        ]
    parameters = item.parameters
    return [(str(parameters.building), str(parameters.unit), str(parameters.floor), str(parameters.door))]


def selection_summary(items: list[AcceptancePlanItem]) -> dict[str, int]:
    locations = [location for item in items for location in _item_locations(item)]
    return {
        "tasks": len(items),
        "delivery_points": len(locations),
        "physical_buildings": len({location[:2] for location in locations}),
        "floors": len({location[:3] for location in locations}),
        "doors": len(set(locations)),
    }


def coverage_summary(plan: AcceptancePlan) -> CoverageSummary:
    dimensions = {
        "physical_building": lambda location: location[:2],
        "floor": lambda location: location[:3],
        "door": lambda location: location,
    }
    planned = plan.items
    executed = [item for item in plan.items if item.status in TERMINAL_ITEM_STATUSES]
    passed = [item for item in plan.items if item.status == "passed"]

    def percentages(items: list[AcceptancePlanItem]) -> dict[str, float]:
        item_locations = [location for item in items for location in _item_locations(item)]
        planned_locations = [location for item in planned for location in _item_locations(item)]
        output: dict[str, float] = {}
        for name, field_getter in dimensions.items():
            denominator = len({field_getter(location) for location in planned_locations})
            numerator = len({field_getter(location) for location in item_locations})
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
    if plan.status in {"cancelled", "blocked", "failed"}:
        labels = {
            "cancelled": "本次验收已取消",
            "blocked": "本次验收已拦截",
            "failed": "本次验收异常结束",
        }
        not_run = sum(item.status == "planned" for item in plan.items)
        return AcceptanceResult(
            plan.status,
            f"{labels[plan.status]}：已记录 {len(terminal_items)} 项终态任务，{not_run} 项未执行；可依据本报告的已采集结果、反馈与轨迹证据继续分析。",
            coverage,
            pass_rate,
            failed,
        )
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
        # A process restart invalidates its in-memory run ID and every live
        # preflight message.  Do not present either as active robot work.
        plan.run_id = None
        plan.execution_preflight_status = default_execution_preflight_status(plan.execution_preflight)
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
