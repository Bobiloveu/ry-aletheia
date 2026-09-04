"""Acceptance-plan lifecycle over the existing RunManager execution boundary."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

from .acceptance_catalog import AcceptanceTaskCatalog
from .acceptance_plan import ACTIVE_PLAN_STATUSES, AcceptanceCriteria, AcceptancePlan, AcceptancePlanFactory, AcceptancePlanStore
from .acceptance_report import AcceptanceReportWriter
from .models import TestCase, now_iso


class AcceptanceConflict(RuntimeError):
    pass


class AcceptanceValidationError(ValueError):
    pass


class AcceptanceOrchestrator:
    def __init__(self, *, catalog: AcceptanceTaskCatalog, plan_store: AcceptancePlanStore, run_manager, report_dir: Path) -> None:
        self.catalog = catalog
        self.plan_store = plan_store
        self.run_manager = run_manager
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
        return {
            "communities": communities,
            "valid_task_count": len(snapshot.valid_tasks),
            "issues": [{"filename": item.filename, "message": item.message} for item in snapshot.issues],
        }

    def current(self) -> dict[str, Any] | None:
        with self._lock:
            plan = self.plan_store.load_current()
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
        expected = {"scope_type", "community", "building", "unit", "mode", "sample_size"}
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
        sample_size = document.get("sample_size")
        if mode == "full":
            sample_size = None
        elif isinstance(sample_size, bool) or not isinstance(sample_size, int):
            raise AcceptanceValidationError("抽样数量必须是整数")
        with self._lock:
            current = self.plan_store.load_current()
            if current and current.status in ACTIVE_PLAN_STATUSES:
                raise AcceptanceConflict("当前验收计划正在执行，不能覆盖")
            try:
                plan = AcceptancePlanFactory.create(
                    self.catalog.scan(), scope_type=scope_type, community=community.strip(), building=building,
                    unit=unit, mode=mode, sample_size=sample_size, random_seed=None, criteria=self.plan_store.load_criteria(),
                )
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
                TestCase(item.filename, item.filename, item.filename, item.parameters, item.source_path)
                for item in plan.items if item.status == "planned"
            ]
            if not cases:
                raise AcceptanceConflict("验收计划没有待执行任务")
            plan.status, plan.current_index = "preparing", 0
            self.plan_store.save(plan)
            try:
                run = self.run_manager.start_sequence(cases, event_callback=lambda event: self._on_run_event(plan.plan_id, event))
            except Exception as exc:
                plan.status = "blocked"
                plan.updated_at = now_iso()
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
            plan.status = "cancelled"
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
            plan.status = "ready"
            plan.run_id = None
            plan.warnings.append("中断任务未被自动重发；已由操作员核对后按失败记录")
            self.plan_store.save(plan)
            return plan.to_public_dict()

    def _require_plan(self, plan_id: str) -> AcceptancePlan:
        plan = self.plan_store.load_current()
        if plan is None or plan.plan_id != plan_id:
            raise AcceptanceConflict("验收计划不存在")
        return plan

    def _verify_sources(self, plan: AcceptancePlan) -> None:
        live = {task.filename: task for task in self.catalog.scan().valid_tasks}
        for item in plan.items:
            task = live.get(item.filename)
            if task is None or str(task.path) != item.source_path or task.sha256 != item.sha256:
                plan.status = "blocked"
                self.plan_store.save(plan)
                raise AcceptanceConflict("正式任务文件已变化或不可用；为保护冻结验收计划，未开始执行")

    def _on_run_event(self, plan_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            plan = self.plan_store.load_current()
            if plan is None or plan.plan_id != plan_id:
                return
            index = int(event.get("item_index", 0)) - 1
            if 0 <= index < len(plan.items):
                plan.current_index = index
            event_type = event.get("type")
            if event_type == "item_preparing":
                plan.status = "preparing"
                if 0 <= index < len(plan.items):
                    plan.items[index].status, plan.items[index].started_at = "running", now_iso()
            elif event_type == "item_finished" and 0 <= index < len(plan.items):
                attempt = dict(event.get("attempt") or {})
                item = plan.items[index]
                item.status = str(attempt.get("status", "failed"))
                item.message = str(attempt.get("message", ""))
                item.duration_s = float(attempt.get("duration_s", 0.0))
                item.trajectory = attempt.get("trajectory") if isinstance(attempt.get("trajectory"), dict) else None
                item.finished_at = now_iso()
                plan.status = "running"
            elif event_type == "awaiting_recovery":
                plan.status = "awaiting_recovery"
            elif event_type == "recovered":
                plan.status = "running"
            elif event_type == "sequence_finished":
                status = str(event.get("status", "failed"))
                plan.status = "completed" if status == "completed" else status
                if plan.status == "completed":
                    report = self.report_writer.write(plan)
                    plan.report_filename = report.html_filename
            self.plan_store.save(plan)
