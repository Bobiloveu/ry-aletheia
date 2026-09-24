"""Acceptance-plan lifecycle over the existing RunManager execution boundary."""

from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import logging
import threading
from typing import Any

from .acceptance_catalog import AcceptanceTaskCatalog
from .multi_task_catalog import MultiTaskCatalog
from .acceptance_plan import (
    ACTIVE_PLAN_STATUSES,
    AcceptanceCriteria,
    AcceptancePlan,
    AcceptancePlanFactory,
    AcceptancePlanStore,
    default_execution_preflight,
    default_execution_preflight_status,
    normalize_execution_preflight_status,
)
from .acceptance_report import AcceptanceReportWriter
from .models import TestCase, now_iso


LOGGER = logging.getLogger(__name__)
_REPORTABLE_TERMINAL_STATUSES = frozenset({"completed", "cancelled", "blocked", "failed"})


class AcceptanceConflict(RuntimeError):
    pass


class AcceptanceValidationError(ValueError):
    pass


class AcceptanceOrchestrator:
    def __init__(self, *, catalog: AcceptanceTaskCatalog, plan_store: AcceptancePlanStore, run_manager, report_dir: Path, scenario_setup=None, settings=None, multi_catalog: MultiTaskCatalog | None = None) -> None:
        self.catalog = catalog
        self.multi_catalog = multi_catalog or MultiTaskCatalog()
        self.plan_store = plan_store
        self.run_manager = run_manager
        self.scenario_setup = scenario_setup
        self.settings = settings
        self.report_writer = AcceptanceReportWriter(report_dir)
        self._lock = threading.RLock()
        self.plan_store.mark_interrupted_runs()

    def catalog_summary(self) -> dict[str, Any]:
        snapshot = self.catalog.scan()
        communities = []
        for community in snapshot.communities():
            selected = snapshot.select("community", community)
            communities.append({
                "name": community,
                "physical_buildings": [
                    {"building": building, "unit": unit, "label": f"{building}栋{unit}单元"}
                    for building, unit in snapshot.physical_buildings(community)
                ],
                "task_count": len(selected),
                "physical_building_count": len({(item.parameters.building, item.parameters.unit) for item in selected}),
                "floor_count": len({(item.parameters.building, item.parameters.unit, item.parameters.floor) for item in selected}),
            })
        multi_snapshot = self.multi_catalog.scan()
        multi_communities = []
        for community in multi_snapshot.communities():
            buildings = []
            for building, unit in multi_snapshot.physical_buildings(community):
                status = multi_snapshot.building_status(community, building, unit)
                buildings.append({
                    "building": building,
                    "unit": unit,
                    "label": f"{building}栋{unit}单元",
                    "available": status.available,
                    "issues": list(status.issues),
                    "template_count": len(status.templates),
                    "template_suffixes": [item.door_suffix for item in status.templates],
                    "requires_floor_range": bool(status.templates),
                    "special_point_count": len(status.special_points),
                })
            multi_communities.append({
                "name": community,
                "physical_buildings": buildings,
                "gate_available": multi_snapshot.gate_status(community).available,
            })
        return {
            "communities": communities,
            "valid_task_count": len(snapshot.valid_tasks),
            "issues": [{"filename": item.filename, "message": item.message} for item in snapshot.issues],
            "modes": {
                "single_r6s": {"communities": communities, "valid_task_count": len(snapshot.valid_tasks)},
                "multi_r6b": {
                    "communities": multi_communities,
                    "issues": [{"filename": item.filename, "message": item.message} for item in multi_snapshot.issues],
                },
            },
        }

    def current(self) -> dict[str, Any] | None:
        with self._lock:
            plan = self.plan_store.load_current()
            if plan is not None:
                self._repair_legacy_terminal_ready_plan(plan)
            return plan.to_public_dict() if plan else None

    def criteria(self) -> dict[str, Any]:
        return self.plan_store.load_criteria().to_dict()

    def save_criteria(self, document: dict[str, object]) -> dict[str, Any]:
        try:
            criteria = AcceptanceCriteria.from_dict(document)
        except ValueError as exc:
            raise AcceptanceValidationError(str(exc)) from exc
        return self.plan_store.save_criteria(criteria).to_dict()

    def create_plan(self, document: dict[str, object]) -> dict[str, Any]:
        expected = {
            "scope_type", "community", "building", "unit", "mode", "sample_size",
            "scenario_profile_id", "use_dependency_plan", "use_automatic_return",
            "execution_mode", "multi_options",
        }
        unexpected = set(document) - expected
        if unexpected:
            raise AcceptanceValidationError(f"创建计划包含未知字段：{', '.join(sorted(unexpected))}")
        scope_type, community, mode = document.get("scope_type"), document.get("community"), document.get("mode")
        if scope_type not in {"community", "building"} or not isinstance(community, str) or not community.strip() or mode not in {"full", "sample"}:
            raise AcceptanceValidationError("验收范围或计划模式无效")
        building = document.get("building")
        unit = document.get("unit")
        if scope_type == "building" and (
            isinstance(building, bool) or not isinstance(building, int)
            or isinstance(unit, bool) or not isinstance(unit, int)
        ):
            raise AcceptanceValidationError("指定楼宇验收必须选择实际栋号和单元")
        if scope_type == "community":
            building, unit = None, None
        execution_mode = document.get("execution_mode", "single_r6s")
        if execution_mode not in {"single_r6s", "multi_r6b"}:
            raise AcceptanceValidationError("任务执行模式无效")
        if execution_mode == "single_r6s" and document.get("multi_options") is not None:
            raise AcceptanceValidationError("单点任务计划不能包含多点任务配置")
        if execution_mode == "multi_r6b" and not isinstance(document.get("multi_options"), dict):
            raise AcceptanceValidationError("多点任务计划缺少多点任务配置")
        if execution_mode == "multi_r6b" and document.get("use_automatic_return", False):
            raise AcceptanceValidationError("R6B 多点任务使用 return_origin，不能提交 R6S 自动返程配置")
        sample_size = document.get("sample_size")
        if mode == "full":
            sample_size = None
        elif isinstance(sample_size, bool) or not isinstance(sample_size, int):
            raise AcceptanceValidationError("抽样数量必须是整数")
        execution_preflight = self._freeze_execution_preflight(document)
        with self._lock:
            current = self.plan_store.load_current()
            if current and current.status == "interrupted":
                raise AcceptanceConflict("当前验收计划因重启中断，请先完成现场核对后再创建新计划")
            if current and current.status in ACTIVE_PLAN_STATUSES:
                raise AcceptanceConflict("当前验收计划正在执行，不能覆盖")
            try:
                if execution_mode == "multi_r6b":
                    plan = AcceptancePlanFactory.create_multi(
                        self.multi_catalog.scan(), scope_type=scope_type, community=community.strip(), building=building,
                        unit=unit, mode=mode, sample_size=sample_size, random_seed=None,
                        criteria=self.plan_store.load_criteria(), multi_options=document["multi_options"],
                        execution_preflight=execution_preflight,
                    )
                else:
                    plan = AcceptancePlanFactory.create(
                        self.catalog.scan(), scope_type=scope_type, community=community.strip(), building=building,
                        unit=unit, mode=mode, sample_size=sample_size, random_seed=None, criteria=self.plan_store.load_criteria(),
                        execution_preflight=execution_preflight,
                    )
                plan.execution_preflight_status = default_execution_preflight_status(execution_preflight)
            except ValueError as exc:
                raise AcceptanceValidationError(str(exc)) from exc
            self.plan_store.save(plan)
            return plan.to_public_dict()

    def start(self, plan_id: str) -> dict[str, Any]:
        with self._lock:
            plan = self._require_plan(plan_id)
            if plan.status != "ready":
                raise AcceptanceConflict("验收计划不是可开始状态")
            self._verify_sources(plan)
            cases = [
                TestCase(
                    item.filename,
                    item.filename,
                    item.filename,
                    item.parameters,
                    item.source_path,
                    execution_mode=plan.execution_mode,
                    multi_request=item.multi_request,
                )
                for item in plan.items if item.status == "planned"
            ]
            if not cases:
                raise AcceptanceConflict("验收计划没有待执行任务")
            plan.status, plan.current_index = "preparing", 0
            self.plan_store.save(plan)
            try:
                arguments = {"event_callback": lambda event: self._on_run_event(plan.plan_id, event)}
                if plan.execution_preflight is not None:
                    arguments["execution_preflight"] = deepcopy(plan.execution_preflight)
                run = self.run_manager.start_sequence(cases, **arguments)
            except Exception as exc:
                plan.status = "blocked"
                plan.updated_at = now_iso()
                self._archive_terminal_report(plan)
                self.plan_store.save(plan)
                raise AcceptanceConflict(str(exc)) from exc
            plan.status, plan.run_id = "running", run.id
            self.plan_store.save(plan)
            return plan.to_public_dict()

    def resume(self, plan_id: str) -> dict[str, Any]:
        with self._lock:
            plan = self._require_plan(plan_id)
            if plan.status != "awaiting_recovery" or not plan.run_id:
                raise AcceptanceConflict("当前计划不在等待人工恢复状态")
            if self.run_manager.resume(plan.run_id) is None:
                raise AcceptanceConflict("原执行会话已不可恢复；请先处理重启中断项")
            plan.status = "recovering"
            plan.manual_interventions += 1
            self.plan_store.save(plan)
            return plan.to_public_dict()

    def cancel(self, plan_id: str) -> dict[str, Any]:
        with self._lock:
            plan = self._require_plan(plan_id)
            if not plan.run_id or self.run_manager.cancel(plan.run_id) is None:
                raise AcceptanceConflict("当前计划不可取消")
            # Cancellation is immediately requested, but a ROS call or
            # recovery preflight may still be unwinding.  Keep the execution
            # slot reserved until the worker sends its terminal callback.
            plan.status = "cancelling"
            self.plan_store.save(plan)
            return plan.to_public_dict()

    def resolve_interruption(self, plan_id: str, resolution: str) -> dict[str, Any]:
        """Require an operator to account for a task unknown at process restart.

        A previous in-memory RunManager cannot safely be resumed after restart.
        The operator therefore records the unknown item as failed, completes
        any physical recovery, then explicitly starts only the remaining
        still-planned items through a new managed sequence.
        """
        if resolution not in {"mark_failed", "recover"}:
            raise AcceptanceValidationError("中断项处理方式无效")
        with self._lock:
            plan = self._require_plan(plan_id)
            if plan.status != "interrupted" or plan.current_index is None:
                raise AcceptanceConflict("当前计划没有待核对的中断任务")
            item = plan.items[plan.current_index]
            if item.status != "unknown_after_restart":
                raise AcceptanceConflict("当前中断任务已被处理")
            item.status = "failed"
            item.message = "后端重启前任务结果未知；操作员已核对现场并按失败记录"
            item.finished_at = now_iso()
            plan.manual_interventions += 1
            plan.run_id = None
            plan.current_index = None
            plan.execution_preflight_status = default_execution_preflight_status(plan.execution_preflight)
            plan.warnings.append("中断任务未被自动重发；已由操作员核对后按失败记录")
            if any(candidate.status == "planned" for candidate in plan.items):
                plan.status = "ready"
            else:
                # There is no remaining work to restart.  Leaving the plan
                # "ready" would lock every browser to a dead frozen scope,
                # falsely imply a new task is about to start, and skip the
                # required terminal report.
                plan.status = "failed"
                self._archive_terminal_report(plan)
            self.plan_store.save(plan)
            return plan.to_public_dict()

    def _require_plan(self, plan_id: str) -> AcceptancePlan:
        plan = self.plan_store.load_current()
        if plan is None or plan.plan_id != plan_id:
            raise AcceptanceConflict("验收计划不存在")
        return plan

    def _repair_legacy_terminal_ready_plan(self, plan: AcceptancePlan) -> None:
        """Finalize only the old, impossible state left by pre-fix restart recovery.

        Older versions marked an interrupted task failed but still persisted the
        whole plan as ``ready``.  A ready plan that contains *only* terminal
        items cannot be started safely, so it must be converted into the
        corresponding terminal result when first read after an upgrade.
        """
        terminal_items = {"passed", "failed", "cancelled"}
        if plan.status != "ready" or not plan.items or any(item.status not in terminal_items for item in plan.items):
            return
        if all(item.status == "passed" for item in plan.items):
            plan.status = "completed"
        elif any(item.status == "failed" for item in plan.items):
            plan.status = "failed"
        else:
            plan.status = "cancelled"
        plan.run_id = None
        plan.current_index = None
        plan.execution_preflight_status = default_execution_preflight_status(plan.execution_preflight)
        plan.warnings.append("已归档旧版本遗留的终态验收计划，未重新下发任何任务")
        self._archive_terminal_report(plan)
        self.plan_store.save(plan)

    def _verify_sources(self, plan: AcceptancePlan) -> None:
        if plan.execution_mode == "multi_r6b":
            for item in plan.items:
                paths = item.source_paths or (item.source_path,)
                hashes = item.source_hashes or (item.sha256,)
                if len(paths) != len(hashes):
                    plan.status = "blocked"
                    self._archive_terminal_report(plan)
                    self.plan_store.save(plan)
                    raise AcceptanceConflict("多点任务来源指纹不完整；为保护冻结验收计划，未开始执行")
                for source_path, expected_hash in zip(paths, hashes):
                    path = Path(source_path)
                    try:
                        actual_hash = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
                    except OSError:
                        actual_hash = None
                    if actual_hash != expected_hash:
                        plan.status = "blocked"
                        self._archive_terminal_report(plan)
                        self.plan_store.save(plan)
                        raise AcceptanceConflict("多点任务文件已变化或不可用；为保护冻结验收计划，未开始执行")
            return
        live = {task.filename: task for task in self.catalog.scan().valid_tasks}
        for item in plan.items:
            task = live.get(item.filename)
            if task is None or str(task.path) != item.source_path or task.sha256 != item.sha256:
                plan.status = "blocked"
                self._archive_terminal_report(plan)
                self.plan_store.save(plan)
                raise AcceptanceConflict("正式任务文件已变化或不可用；为保护冻结验收计划，未开始执行")

    def _freeze_execution_preflight(self, document: dict[str, object]) -> dict[str, Any]:
        """Freeze only existing, operator-saved runtime options into a plan."""
        raw_profile_id = document.get("scenario_profile_id")
        if raw_profile_id is None:
            profile_id = None
        elif isinstance(raw_profile_id, str) and raw_profile_id.strip() and len(raw_profile_id.strip()) <= 64 and "\x00" not in raw_profile_id:
            profile_id = raw_profile_id.strip()
        else:
            raise AcceptanceValidationError("场景前置方案选择无效")
        use_dependencies = document.get("use_dependency_plan", False)
        if not isinstance(use_dependencies, bool):
            raise AcceptanceValidationError("是否执行 Supervisor 依赖编排必须为布尔值")
        automatic_return = document.get("use_automatic_return", False)
        if not isinstance(automatic_return, bool):
            raise AcceptanceValidationError("是否自动返程必须为布尔值")
        frozen = default_execution_preflight()
        frozen["automatic_return"] = automatic_return
        if profile_id:
            if self.scenario_setup is None:
                raise AcceptanceValidationError("场景前置模块不可用，不能选择场景方案")
            profiles = self.scenario_setup.load().get("profiles", [])
            profile = next((item for item in profiles if isinstance(item, dict) and item.get("id") == profile_id), None)
            if not profile or not isinstance(profile.get("name"), str):
                raise AcceptanceValidationError("所选场景前置方案不存在，请刷新后重试")
            frozen["scenario_profile_id"] = profile_id
            frozen["scenario_profile_name"] = profile["name"]
        if use_dependencies:
            if self.settings is None:
                raise AcceptanceValidationError("运行配置不可用，不能执行 Supervisor 依赖编排")
            dependency_plan = deepcopy(getattr(self.settings.load(), "dependency_plan", None))
            if not isinstance(dependency_plan, dict) or dependency_plan.get("enabled") is not True or not dependency_plan.get("steps"):
                raise AcceptanceValidationError("当前没有已启用的 Supervisor 依赖编排，请先在任务指挥台保存编排")
            frozen["dependency_plan"] = dependency_plan
        return frozen

    def _on_run_event(self, plan_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            plan = self.plan_store.load_current()
            if plan is None or plan.plan_id != plan_id:
                return
            index = int(event.get("item_index", 0)) - 1
            if 0 <= index < len(plan.items):
                plan.current_index = index
            event_type = event.get("type")
            lifecycle_locked = plan.status == "cancelling" or plan.status in _REPORTABLE_TERMINAL_STATUSES
            if event_type in {"preflight_progress", "preflight_restore"}:
                progress = event.get("preflight")
                if not isinstance(progress, dict):
                    return
                try:
                    dependency_progress = progress.get(
                        "dependency_progress",
                        plan.execution_preflight_status.get("dependency_progress"),
                    )
                    plan.execution_preflight_status = normalize_execution_preflight_status(
                        {
                            "state": progress.get("state"),
                            "message": progress.get("message"),
                            "updated_at": now_iso(),
                            "dependency_progress": dependency_progress,
                        },
                        preflight=plan.execution_preflight,
                    )
                except ValueError:
                    return
                if event_type == "preflight_progress" and not lifecycle_locked:
                    plan.status = "preparing"
            elif event_type == "item_preparing":
                if not lifecycle_locked:
                    plan.status = "preparing"
                if not lifecycle_locked and 0 <= index < len(plan.items):
                    plan.items[index].status, plan.items[index].started_at = "running", now_iso()
            elif event_type == "item_finished" and 0 <= index < len(plan.items):
                attempt = dict(event.get("attempt") or {})
                item = plan.items[index]
                item.status = str(attempt.get("status", "failed"))
                item.message = str(attempt.get("message", ""))
                item.duration_s = float(attempt.get("duration_s", 0.0))
                item.trajectory = attempt.get("trajectory") if isinstance(attempt.get("trajectory"), dict) else None
                item.delivery_evidence = attempt.get("delivery_evidence") if isinstance(attempt.get("delivery_evidence"), list) else None
                item.finished_at = now_iso()
                if not lifecycle_locked:
                    plan.status = "running"
            elif event_type == "awaiting_recovery":
                if not lifecycle_locked:
                    plan.status = "awaiting_recovery"
            elif event_type == "recovered":
                if not lifecycle_locked:
                    plan.status = "running"
            elif event_type == "sequence_finished":
                status = str(event.get("status", "failed"))
                plan.status = "completed" if status == "completed" else status
                plan.run_id = None
                plan.current_index = None
                self._archive_terminal_report(plan)
            self.plan_store.save(plan)

    def _archive_terminal_report(self, plan: AcceptancePlan) -> None:
        """Write exactly one report once a plan has reached a final outcome."""
        if plan.status not in _REPORTABLE_TERMINAL_STATUSES or plan.report_filename:
            return
        try:
            report = self.report_writer.write(plan)
        except Exception as exc:
            LOGGER.exception("验收报告写入失败：plan=%s status=%s", plan.plan_id, plan.status)
            plan.warnings.append(f"验收报告写入失败：{exc}")
            return
        plan.report_filename = report.html_filename
