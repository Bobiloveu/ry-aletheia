from __future__ import annotations

import csv
import html
import logging
import re
import threading
import uuid
import shutil
import subprocess
from contextlib import nullcontext
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Callable

from .models import AttemptResult, RunRecord, TestCase, now_iso
from .map_assets import CachedMapAsset, MapAssetCache, MapAssetError
from .robot_gateway import RobotGateway
from .ros_executor import RosTaskExecutor
from .settings import SettingsStore
from .scenario_setup import ScenarioSetupError, ScenarioSetupStore
from .trajectory import TrajectorySession
from .trajectory_render import TrajectoryRenderError, render_svg


LOGGER = logging.getLogger("ry_aletheia.run")
# 方案写入启动脚本后，不应立刻触发 Supervisor 重启。给文件系统、挂载层和
# 读取脚本的守护进程一个确定且足够短的稳定窗口，避免 lightning 读取到旧配置。
SCENARIO_APPLY_SETTLE_SECONDS = 3.0


def _usable_progress_percent(value: object) -> float | None:
    """Return a bounded display percentage, rejecting missing/NaN snapshots."""
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, percent)) if isfinite(percent) else None


def _format_report_time(value: object) -> str:
    """将内部 ISO 时间转换为报告中易读的本地日期时间。"""
    if not value:
        return "—"
    raw = str(value)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        # 历史记录可能不是 ISO 格式；保留原文比让报告生成失败更安全。
        return raw


class RunManager:
    def __init__(self, report_dir: Path, executor: RosTaskExecutor, settings: SettingsStore, scenario_setup: ScenarioSetupStore | None = None) -> None:
        self.report_dir = report_dir
        self.executor = executor
        self.settings = settings
        self.scenario_setup = scenario_setup
        self._scenario_apply_settle_seconds = SCENARIO_APPLY_SETTLE_SECONDS
        self._runs: dict[str, RunRecord] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._resume_events: dict[str, threading.Event] = {}
        self._attempt_interrupt_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._execution_lock = threading.Lock()

    def start(self, case: TestCase, count: int, interval_s: float, prepare_trajectory_maps: bool = True) -> RunRecord:
        if not 1 <= count <= 1000:
            raise ValueError("执行次数必须介于 1 和 1000 之间")
        if not 0 <= interval_s <= 3600:
            raise ValueError("执行间隔必须介于 0 和 3600 秒之间")
        # 轨迹图是正式测试报告的必备证据，不允许创建无轨迹的执行计划。
        run = RunRecord(id=uuid.uuid4().hex[:12], case=case, requested_count=count, interval_s=interval_s, prepare_trajectory_maps=True)
        with self._lock:
            if any(item.status in {"queued", "preparing", "running", "cancelling", "awaiting_recovery", "recovering"} for item in self._runs.values()):
                raise RuntimeError("已有任务正在执行，请等待其完成后再发起新任务")
            self._runs[run.id] = run
            self._cancel_events[run.id] = threading.Event()
            self._resume_events[run.id] = threading.Event()
            self._attempt_interrupt_events[run.id] = threading.Event()
        threading.Thread(target=self._run, args=(run,), daemon=True, name=f"test-run-{run.id}").start()
        LOGGER.info("创建测试计划：run=%s case=%s rounds=%s", run.id, case.filename, count)
        return run

    def start_sequence(
        self,
        cases: list[TestCase],
        *,
        interval_s: float = 0,
        prepare_trajectory_maps: bool = True,
        event_callback: Callable[[dict], None] | None = None,
    ) -> RunRecord:
        """Execute frozen acceptance cases through the existing single-run path.

        The parent record reserves the same active-run slot as ordinary tests.
        Each item then calls ``_run`` with a private one-attempt record, which
        preserves the established scenario, preflight, ROS, trajectory and
        safety-finally behavior without introducing another executor.
        """
        if not cases:
            raise ValueError("验收计划至少需要一个任务")
        if not 0 <= interval_s <= 3600:
            raise ValueError("执行间隔必须介于 0 和 3600 秒之间")
        run = RunRecord(
            id=uuid.uuid4().hex[:12],
            case=cases[0],
            requested_count=len(cases),
            interval_s=interval_s,
            prepare_trajectory_maps=prepare_trajectory_maps,
        )
        with self._lock:
            if any(item.status in {"queued", "preparing", "running", "cancelling", "awaiting_recovery", "recovering"} for item in self._runs.values()):
                raise RuntimeError("已有任务正在执行，请等待其完成后再发起新任务")
            self._runs[run.id] = run
            self._cancel_events[run.id] = threading.Event()
            self._resume_events[run.id] = threading.Event()
            self._attempt_interrupt_events[run.id] = threading.Event()
        threading.Thread(
            target=self._run_sequence,
            args=(run, tuple(cases), event_callback),
            daemon=True,
            name=f"acceptance-run-{run.id}",
        ).start()
        LOGGER.info("创建验收执行序列：run=%s tasks=%s", run.id, len(cases))
        return run

    def _emit_sequence_event(
        self,
        callback: Callable[[dict], None] | None,
        event_type: str,
        run: RunRecord,
        item_index: int,
        case: TestCase,
        **extra: object,
    ) -> None:
        if callback is None:
            return
        payload = {
            "type": event_type,
            "run_id": run.id,
            "item_index": item_index,
            "case": {"id": case.id, "filename": case.filename, "parameters": case.parameters.__dict__},
            **extra,
        }
        try:
            callback(payload)
        except Exception:
            # Persistence/UI observation must never make the robot execution
            # thread fail.  The acceptance orchestrator can recover state from
            # RunRecord after a callback-side error.
            LOGGER.exception("验收执行事件回调失败：run=%s type=%s", run.id, event_type)

    def _run_sequence(
        self,
        run: RunRecord,
        cases: tuple[TestCase, ...],
        event_callback: Callable[[dict], None] | None,
    ) -> None:
        cancel_event = self._cancel_events[run.id]
        resume_event = self._resume_events[run.id]
        run.status, run.started_at = "preparing", now_iso()
        try:
            for item_index, case in enumerate(cases, start=1):
                if cancel_event.is_set():
                    run.status = "cancelled"
                    break
                run.case = case
                run.active_attempt = item_index
                self._emit_sequence_event(event_callback, "item_preparing", run, item_index, case)
                child = RunRecord(
                    id=run.id,
                    case=case,
                    requested_count=1,
                    interval_s=0,
                    prepare_trajectory_maps=run.prepare_trajectory_maps,
                )
                # The parent owns the public status and dedicated acceptance
                # report.  Child runs must not create normal run reports or
                # overwrite trajectory evidence as attempt 1 each time.
                child._skip_report = True
                child._sequence_attempt_index = item_index
                self._run(child)
                run.preflight = child.preflight
                run.live_progress = child.live_progress
                if child.attempts:
                    attempt = child.attempts[-1]
                    attempt.case_id = case.id
                    attempt.case_filename = case.filename
                    run.attempts.append(attempt)
                    self._emit_sequence_event(
                        event_callback,
                        "item_finished",
                        run,
                        item_index,
                        case,
                        attempt={
                            "status": attempt.status,
                            "message": attempt.message,
                            "duration_s": attempt.duration_s,
                            "started_at": attempt.started_at,
                            "trajectory": attempt.trajectory,
                        },
                    )
                if child.status == "cancelled" or cancel_event.is_set():
                    run.status = "cancelled"
                    break
                if child.status not in {"completed"}:
                    run.status, run.error = "blocked", child.error or "验收任务前置检查未通过"
                    self._emit_sequence_event(event_callback, "sequence_finished", run, item_index, case, status=run.status, message=run.error)
                    break
                if child.attempts and child.attempts[-1].status == "failed":
                    failure_message = f"{case.filename} 执行失败，请将车辆人工恢复至安全起点后继续。"
                    while not cancel_event.is_set():
                        run.status, run.error, run.live_progress = "awaiting_recovery", failure_message, None
                        self._emit_sequence_event(event_callback, "awaiting_recovery", run, item_index, case, message=failure_message)
                        if not resume_event.wait(0.5):
                            continue
                        resume_event.clear()
                        run.status = "recovering"
                        self._record_intervention(run, item_index, "recovery_requested", "操作者确认已完成现场恢复，开始恢复预检")
                        recovered, recovery_message = self._recover_after_manual_intervention(child, cancel_event)
                        if cancel_event.is_set():
                            run.status = "cancelled"
                            break
                        if recovered:
                            self._record_intervention(run, item_index, "recovery_ready", recovery_message)
                            run.status, run.error = "running", None
                            self._emit_sequence_event(event_callback, "recovered", run, item_index, case, message=recovery_message)
                            break
                        self._record_intervention(run, item_index, "recovery_blocked", recovery_message)
                        failure_message = f"恢复预检未通过：{recovery_message}。请处理后再次继续。"
                    if run.status == "cancelled":
                        break
                if item_index < len(cases) and cancel_event.wait(run.interval_s):
                    run.status = "cancelled"
                    break
            else:
                run.status = "completed"
            if run.status == "preparing":
                run.status = "completed"
        except Exception as exc:
            run.status, run.error = "failed", f"验收序列中断：{exc}"
            LOGGER.exception("验收执行序列异常：run=%s", run.id)
        finally:
            run.live_progress = None
            run.active_attempt = None
            run.finished_at = now_iso()
            last_case = run.case
            self._emit_sequence_event(
                event_callback,
                "sequence_finished",
                run,
                len(run.attempts),
                last_case,
                status=run.status,
                message=run.error or "验收序列已结束",
            )

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def latest(self) -> RunRecord | None:
        with self._lock:
            return next(reversed(self._runs.values()), None) if self._runs else None

    def has_active_run(self) -> bool:
        """升级或退出前确认没有会被中断的测试计划。"""
        active = {"queued", "preparing", "running", "cancelling", "awaiting_recovery", "recovering"}
        with self._lock:
            return any(run.status in active for run in self._runs.values())

    def cancel(self, run_id: str) -> RunRecord | None:
        with self._lock:
            run = self._runs.get(run_id)
            if not run or run.status not in {"queued", "preparing", "running", "awaiting_recovery", "recovering"}:
                return None
            run.cancel_requested = True
            run.status = "cancelling"
            self._cancel_events[run_id].set()
            LOGGER.info("操作者终止剩余轮次：run=%s", run_id)
            return run

    def resume(self, run_id: str) -> RunRecord | None:
        """由操作者确认车辆回到起点后，恢复失败轮次之后的执行。"""
        with self._lock:
            run = self._runs.get(run_id)
            if not run or run.status != "awaiting_recovery":
                return None
            run.status = "recovering"
            self._resume_events[run_id].set()
            LOGGER.info("操作者确认恢复测试：run=%s", run_id)
            return run

    def handle_stall_action(self, run_id: str, action: str) -> RunRecord | None:
        """记录操作者对停滞提醒的处置；不强杀正在执行的 ROS 服务调用。"""
        descriptions = {
            "released_estop": "已确认解除急停/阻塞，继续当前轮观察",
            "continue_observing": "暂不判定故障，关闭停滞提醒并继续观察",
            "mark_attempt_failed": "人工判定本轮失败；当前服务调用返回后进入人工恢复",
        }
        if action not in descriptions:
            raise ValueError("未知的停滞处置操作")
        with self._lock:
            run = self._runs.get(run_id)
            if not run or run.status != "running" or run.active_attempt is None:
                return None
            record = {"at": now_iso(), "attempt": run.active_attempt, "action": action, "detail": descriptions[action]}
            run.interventions.append(record)
            if action == "mark_attempt_failed":
                # 立即展示并计入本轮失败；服务调用返回后只补充其反馈、耗时与轨迹，不重复新增记录。
                run.attempts.append(AttemptResult(run.active_attempt, "failed", f"人工判定失败：{record['detail']}；等待当前服务调用结束后进行恢复", 0.0, record["at"], None))
                record["attempt_recorded"] = True
                run.forced_attempt_failure = record
                self._attempt_interrupt_events[run_id].set()
            LOGGER.warning("停滞处置：run=%s attempt=%s action=%s", run_id, run.active_attempt, action)
            return run

    def _run(self, run: RunRecord) -> None:
        with self._execution_lock:
            cancel_event = self._cancel_events[run.id]
            resume_event = self._resume_events[run.id]
            attempt_interrupt_event = self._attempt_interrupt_events[run.id]
            trajectory_assets: list[CachedMapAsset] = []
            route_plan: list[dict] = []
            scenario_applied = False
            run.status, run.started_at = "preparing", now_iso()
            LOGGER.info("开始执行测试计划：run=%s", run.id)
            try:
                if cancel_event.is_set():
                    run.status = "cancelled"
                    return
                run.preflight = {"node_states": [], "task_sync": "正在应用场景方案"}
                scenario_state = self._apply_case_scenario(run)
                run.preflight["scenario"] = scenario_state
                scenario_applied = bool(scenario_state.get("applied"))
                if not scenario_state["ok"]:
                    run.status, run.error = "blocked", scenario_state["message"]
                    return
                if scenario_applied:
                    scenario_state["settle_seconds"] = self._scenario_apply_settle_seconds
                    run.preflight["task_sync"] = f"场景方案已应用，稳定等待 {self._scenario_apply_settle_seconds:g} 秒后执行节点编排"
                    if not self._wait_scenario_settle(cancel_event):
                        run.status = "cancelled"
                        return
                run.preflight["task_sync"] = "正在执行运行依赖预检"
                gateway = RobotGateway(self.settings.load(), lambda states: self._update_preflight_nodes(run, states))
                preflight = gateway.preflight(run.case, cancel_event=cancel_event)
                # 网关返回的是节点/同步状态快照；不得覆盖此前已记录的场景方案应用状态。
                run.preflight = {**preflight.to_dict(), "scenario": scenario_state}
                if cancel_event.is_set():
                    run.status = "cancelled"
                    return
                if not preflight.ok:
                    run.status, run.error = "blocked", preflight.message
                    return
                run.preflight["ros_service"] = {"ok": None, "message": "正在等待 ROS2 服务就绪：/start_execute_tasks（最长 300 秒）"}
                service_ok, service_message = self.executor.wait_until_available(
                    timeout_s=300,
                    cancel_event=cancel_event,
                    status_callback=lambda message: self._update_ros_service_status(run, message),
                )
                run.preflight["ros_service"] = {"ok": service_ok, "message": service_message}
                if cancel_event.is_set():
                    run.status = "cancelled"
                    return
                if not service_ok:
                    run.status, run.error = "blocked", service_message
                    return
                dependencies_ok, dependencies_message, states = gateway.confirm_dependencies_ready(cancel_event=cancel_event)
                run.preflight["node_states"] = states
                run.preflight["final_dependency_gate"] = {"ok": dependencies_ok, "message": dependencies_message}
                if cancel_event.is_set():
                    run.status = "cancelled"
                    return
                if not dependencies_ok:
                    run.status, run.error = "blocked", f"ROS2 服务发现后依赖节点未稳定就绪：{dependencies_message}"
                    return
                if run.prepare_trajectory_maps:
                    try:
                        maps = MapAssetCache(self.report_dir.parent / "maps_cache").prepare(run.case.source)
                        trajectory_assets = maps
                        route_plan = MapAssetCache.route_plan(run.case.source, maps)
                        run.preflight["trajectory_maps"] = {
                            "state": "waiting_ros_map",
                            "message": "将以 ROS2 /map 生成实际轨迹底图；本轮以 5 Hz 采集 /odom 轨迹",
                            "maps": [item.to_dict() for item in maps],
                        }
                    except MapAssetError as exc:
                        # /map 是实际地图来源；离线地图解析失败只能降级预览，绝不能阻止 ROS2 任务下发。
                        trajectory_assets, route_plan = [], []
                        run.preflight["trajectory_maps"] = {
                            "state": "waiting_ros_map",
                            "message": f"离线地图引用不可用，将仅等待 ROS2 /map：{exc}",
                            "maps": [],
                        }
                if cancel_event.is_set():
                    run.status = "cancelled"
                    return
                run.status = "running"
                index = 1
                while index <= run.requested_count:
                    if cancel_event.is_set():
                        run.status = "cancelled"
                        break
                    started = now_iso()
                    trajectory_session = None
                    run.active_attempt = index
                    run.forced_attempt_failure = None
                    attempt_interrupt_event.clear()
                    # 0% 与“尚未收到可验证路线投影”不是一回事。后者必须明确
                    # 标记为不可用，避免多轮切换时网页把未知状态误画成卡住的 0%。
                    run.live_progress = {"visible": True, "attempt": index, "attempt_total": run.requested_count, "state": "正在等待 /map 与 /odom", "progress_available": False, "percent": 0, "points": 0}
                    trajectory_start_error = ""
                    if run.prepare_trajectory_maps:
                        try:
                            trajectory_session = TrajectorySession(trajectory_assets, route_plan, lambda progress, attempt=index: self._update_live_progress(run, attempt, progress), elevator_wait_timeout_s=self.settings.load().elevator_wait_timeout_s, map_cache_dir=self.report_dir.parent / "maps_cache")
                            trajectory_session.start()
                        except Exception as exc:
                            # 轨迹是测试证据，而不是任务下发的前置条件。比如 PyInstaller
                            # 漏收 tf2_msgs 时，必须明确记录证据缺失，但不能把正常的 ROS
                            # 任务服务误判为失败、也不能让操作者进入无意义的人工恢复。
                            trajectory_session = None
                            trajectory_start_error = f"轨迹采集未启动：{exc}"
                            LOGGER.exception("轨迹采集启动失败：run=%s attempt=%s", run.id, index)
                            run.live_progress = {"visible": True, "attempt": index, "attempt_total": run.requested_count, "state": "轨迹采集不可用，任务仍将执行", "progress_available": False, "percent": 0, "points": 0, "integrity_warning": trajectory_start_error}
                    # 服务端会在整条任务完成后才返回；该阈值与“服务发现 300 秒”
                    # 完全独立，避免长路径或等电梯任务已完成却被本地误判超时。
                    execution_timeout = getattr(self.settings.load(), "task_execution_timeout_s", 900)
                    try:
                        ok, message, duration = self.executor.execute(
                            run.case.parameters,
                            lambda _msg: None,
                            cancel_event,
                            attempt_interrupt_event,
                            timeout_s=execution_timeout,
                        )
                    except Exception as exc:
                        # ROS 环境、接口包缺失等基础设施错误不能靠重试恢复。
                        ok, message, duration = False, f"执行器异常：{exc}", 0.0
                        LOGGER.exception("任务服务调用异常：run=%s attempt=%s", run.id, index)
                    trajectory = None
                    if trajectory_session:
                        try:
                            trajectory = trajectory_session.stop()
                            # ROS2 /map 可能发现任务 JSON 未能引用到的真实地图；后续渲染必须使用该实际资产。
                            trajectory_assets = trajectory_session.maps
                            # route_plan 在本轮会将离线/空地图 ID 绑定为 ROS 实际
                            # 地图的运行时 asset_id。多轮执行若只带入 maps 而遗漏该
                            # 绑定，下一轮会拿旧 ID 与新 active map 比较，持续停在
                            # “等待切图”，进度因而始终无法从 0% 开始投影。
                            route_plan = [dict(item) for item in trajectory_session.route_plan]
                        except Exception as exc:
                            trajectory_start_error = f"轨迹采集停止失败：{exc}"
                            LOGGER.exception("轨迹采集停止失败：run=%s attempt=%s", run.id, index)
                    if trajectory_start_error:
                        trajectory = {
                            "sample_hz": 5.0,
                            "points": 0,
                            "segments": [],
                            "diagnostics": {"recorder_error": trajectory_start_error, "points_rejected": 0, "tf_errors": 0, "map_unmatched": 0},
                            "integrity_warning": f"轨迹证据不完整：{trajectory_start_error}",
                        }
                    if trajectory is not None:
                        try:
                            diagnostics = trajectory.get("diagnostics", {})
                            if not trajectory.get("integrity_warning") and (diagnostics.get("tf_errors") or diagnostics.get("map_unmatched")):
                                detail = diagnostics.get("tf_last_error") or diagnostics.get("map_last_error") or "坐标变换或地图匹配不可用"
                                trajectory["integrity_warning"] = f"轨迹证据不完整：已拒绝 {diagnostics.get('points_rejected', 0)} 个未验证坐标点；{detail}"
                            self._write_trajectory(run, index, trajectory, trajectory_assets)
                            message = f"{message} · 轨迹 {trajectory['points']} 点"
                            if trajectory.get("integrity_warning"):
                                message = f"{message} · {trajectory['integrity_warning']}"
                        except Exception as exc:
                            message = f"{message} · 轨迹保存失败：{exc}"
                            LOGGER.exception("轨迹证据保存失败：run=%s attempt=%s", run.id, index)
                    forced_failure = run.forced_attempt_failure
                    if forced_failure and forced_failure.get("attempt") == index:
                        ok = False
                        message = f"人工判定失败：{forced_failure['detail']} · 原服务反馈：{message}"
                    existing = next((item for item in run.attempts if item.index == index), None)
                    if cancel_event.is_set():
                        if existing:
                            existing.status, existing.message, existing.duration_s, existing.trajectory = "cancelled", message, duration, trajectory
                        else:
                            run.attempts.append(AttemptResult(index, "cancelled", message, duration, started, trajectory, run.case.id, run.case.filename))
                        run.active_attempt = None
                        run.forced_attempt_failure = None
                        run.status = "cancelled"
                        break
                    if existing:
                        existing.status, existing.message, existing.duration_s, existing.trajectory = "failed", message, duration, trajectory
                    else:
                        run.attempts.append(AttemptResult(index, "passed" if ok else "failed", message, duration, started, trajectory, run.case.id, run.case.filename))
                    run.active_attempt = None
                    run.forced_attempt_failure = None
                    if not ok:
                        if index >= run.requested_count:
                            # 最后一轮已真实记录为失败；计划已结束，不需要人工恢复。
                            index += 1
                            continue
                        failure_message = f"T-{index:03d} 执行失败，已记录为失败。请将车辆人工恢复至测试起点后继续剩余 {run.requested_count - index} 轮。"
                        while not cancel_event.is_set():
                            run.status, run.error, run.live_progress = "awaiting_recovery", failure_message, None
                            if not resume_event.wait(0.5):
                                continue
                            resume_event.clear()
                            if cancel_event.is_set():
                                break
                            run.status = "recovering"
                            self._record_intervention(run, index, "recovery_requested", "操作者确认车辆已回到测试起点，开始恢复预检")
                            recovered, recovery_message = self._recover_after_manual_intervention(run, cancel_event)
                            if cancel_event.is_set():
                                run.status = "cancelled"
                                break
                            if recovered:
                                self._record_intervention(run, index, "recovery_ready", recovery_message)
                                run.status, run.error = "running", None
                                break
                            self._record_intervention(run, index, "recovery_blocked", recovery_message)
                            failure_message = f"恢复预检未通过：{recovery_message}。请处理后再次点击继续。"
                        if cancel_event.is_set():
                            run.status = "cancelled"
                            break
                        index += 1
                        # 人工恢复后直接开始下一轮，避免额外间隔掩盖恢复问题。
                        continue
                    if cancel_event.is_set():
                        run.status = "cancelled"
                        break
                    index += 1
                    if index <= run.requested_count:
                        if cancel_event.wait(run.interval_s):
                            run.status = "cancelled"
                            break
                if run.status != "cancelled":
                    run.status = "completed"
            except Exception as exc:
                run.status, run.error = "failed", f"运行中断：{exc}"
                LOGGER.exception("测试计划异常中断：run=%s", run.id)
            finally:
                run.live_progress = None
                run.active_attempt = None
                if scenario_applied:
                    self._restore_case_scenario(run)
                run.finished_at = now_iso()
                if not getattr(run, "_skip_report", False):
                    try:
                        self._write_report(run)
                    except Exception as exc:
                        run.error = f"{run.error or ''} 报告写入失败：{exc}".strip()
                        LOGGER.exception("测试报告写入失败：run=%s", run.id)
                LOGGER.info("测试计划结束：run=%s status=%s", run.id, run.status)

    def _apply_case_scenario(self, run: RunRecord) -> dict:
        """必须在任何 Supervisor 编排动作前完成，以确保重启读取到新参数。"""
        if not self.scenario_setup:
            return {"ok": True, "bound": False, "applied": False, "state": "not_configured", "message": "场景前置模块未配置，使用常规启动配置"}
        bound = False
        try:
            is_bound = getattr(self.scenario_setup, "is_case_bound", None)
            bound = bool(is_bound(run.case.id)) if callable(is_bound) else False
            result = self.scenario_setup.apply_for_case(run.case.id)
            # 完整依赖编排会在紧随其后的 preflight 中重启全部节点；未启用时
            # 立即重启定位/导航启动消费者，确保本轮确实读取刚写入的场景参数。
            plan = getattr(self.settings.load(), "dependency_plan", {})
            # 仅新版事务存储具备精确绑定/恢复语义，才在“无完整编排”时主动
            # 重启最小消费者集合。旧版注入存根保留原有“后续 preflight 编排”
            # 行为，避免测试/第三方扩展在未声明重启能力时被错误调用。
            if callable(is_bound) and (bound or result.get("bound")) and (not isinstance(plan, dict) or not plan.get("enabled")):
                try:
                    runtime_ok, runtime_message = self._restart_scenario_dependencies()
                except Exception as exc:
                    runtime_ok, runtime_message = False, f"启动场景运行依赖时发生异常：{exc}"
                if not runtime_ok:
                    return {
                        "ok": False,
                        "bound": True,
                        "applied": True,
                        "state": "activation_restart_failed",
                        "message": f"场景启动脚本已写入，但运行依赖未能读取新参数：{runtime_message}。请先恢复常规配置后重试。",
                    }
                result["runtime_restart"] = runtime_message
        except ScenarioSetupError as exc:
            LOGGER.error("场景方案应用失败：run=%s case=%s error=%s", run.id, run.case.id, exc)
            # apply 的顺序是“先持久化恢复事务、再改脚本、最后标记 applied”。
            # 最后一步恰好失败时，脚本可能已经改变；不能因异常直接跳过 finally
            # 的自动恢复。只要事务仍在，就让本次计划进入受控恢复路径。
            pending = getattr(self.scenario_setup, "has_unresolved_transaction", None)
            recovery_required = bool(pending()) if callable(pending) else False
            return {
                "ok": False,
                "bound": bool(bound),
                "applied": recovery_required,
                "state": "apply_recovery_required" if recovery_required else "apply_failed",
                "message": (
                    f"场景方案写入过程未完全确认：{exc}。将自动尝试恢复常规配置。"
                    if recovery_required else f"场景方案应用失败：{exc}"
                ),
            }
        except Exception as exc:
            LOGGER.exception("场景方案应用发生未预期异常：run=%s case=%s", run.id, run.case.id)
            pending = getattr(self.scenario_setup, "has_unresolved_transaction", None)
            recovery_required = bool(pending()) if callable(pending) else False
            return {
                "ok": False,
                "bound": bool(bound),
                "applied": recovery_required,
                "state": "apply_recovery_required" if recovery_required else "apply_failed",
                "message": (
                    f"场景方案写入过程发生异常：{exc}。将自动尝试恢复常规配置。"
                    if recovery_required else f"场景方案应用异常：{exc}"
                ),
            }
        if not result["bound"]:
            return {"ok": True, "bound": False, "applied": False, "state": "not_bound", "message": result["message"]}
        self._record_intervention(run, 0, "scenario_applied", f"测试前已应用场景方案：{result['profile_name']}")
        LOGGER.info("场景方案已先于依赖编排应用：run=%s profile=%s", run.id, result["profile_id"])
        return {"ok": True, "bound": True, "applied": True, "state": "applied", "profile_id": result["profile_id"], "profile_name": result["profile_name"], "message": result["message"]}

    def _wait_scenario_settle(self, cancel_event: threading.Event) -> bool:
        """给文件替换后的 shell/文件系统一个短暂稳定窗口，等待可被取消。"""
        return not cancel_event.wait(self._scenario_apply_settle_seconds)

    def _restore_case_scenario(self, run: RunRecord) -> None:
        """测试结束后只恢复受控启动脚本，绝不重启 Supervisor 节点。"""
        scenario = (run.preflight or {}).setdefault("scenario", {})
        try:
            # 与网页手动恢复共用锁，防止计划结束与网页重复点击交叉回写同一
            # 启动脚本。恢复常规方案只影响下一次机器人系统自行加载该脚本的
            # 时机；它不是依赖编排，也不得停止、启动或重启 Supervisor 节点。
            runtime_lock = getattr(self.scenario_setup, "runtime_lock", None) if self.scenario_setup else None
            with runtime_lock if runtime_lock is not None else nullcontext():
                result = self.scenario_setup.restore() if self.scenario_setup else {"restored": False, "message": "场景前置模块未配置"}
            scenario.update({"restore_state": "restored" if result.get("restored") else "not_needed", "restore_message": result["message"]})
            self._record_intervention(run, 0, "scenario_restored", result["message"])
            LOGGER.info("测试结束后已恢复场景方案：run=%s", run.id)
        except ScenarioSetupError as exc:
            message = f"场景方案自动恢复失败：{exc}"
            scenario.update({"restore_state": "restore_failed", "restore_message": message})
            self._record_intervention(run, 0, "scenario_restore_failed", message)
            run.error = f"{run.error}；{message}" if run.error else message
            # 所有行驶轮次即使通过，受控启动配置未能恢复也不能被标记为完全完成。
            if run.status == "completed":
                run.status = "failed"
            LOGGER.exception("测试结束后恢复场景方案失败：run=%s", run.id)

    def _restart_scenario_dependencies(self) -> tuple[bool, str]:
        settings = self.settings.load()
        gateway = RobotGateway(settings)
        return gateway.restart_configured_dependencies()

    @staticmethod
    def _update_live_progress(run: RunRecord, attempt: int, progress: dict) -> None:
        # 由轨迹采集线程低频更新，仅用于网页展示，不参与任何执行判定。
        # 页面切换会重新加载浏览器内存；因此服务端快照本身也必须保留同一轮
        # 已确认的最大进度。/map 或 TF 短暂切换期间的“不可计算”不能把
        # 操作者返回页面后看到的线路进度重置为 0%。
        # ROS executor 在收尾时可能仍派发最后一个回调。它属于旧轮次，绝不能
        # 覆盖已经开始的下一轮，否则网页会偶发看到整轮进度一直为 0%。
        if run.active_attempt != attempt or run.status != "running":
            return
        previous = run.live_progress or {}
        previous_available = previous.get("attempt") == attempt and previous.get("progress_available") is True
        previous_percent = _usable_progress_percent(previous.get("percent")) if previous_available else None
        progress_available = progress.get("progress_available") is True
        incoming_percent = _usable_progress_percent(progress.get("percent")) if progress_available else None
        merged = {"visible": True, "attempt": attempt, "attempt_total": run.requested_count, **progress}
        if previous_percent is not None and (incoming_percent is None or incoming_percent < previous_percent):
            merged["percent"] = round(previous_percent, 1)
            # 仍保留“等待切图/TF”的文字，但继续展示已确认的总进度而非空条。
            if not progress_available:
                merged["progress_available"] = True
                merged["retained_progress"] = True
        elif progress_available:
            merged["progress_available"] = True
        else:
            # 轨迹尚未得到 /map→/odom 的可信投影时，保留内部 0 作为数值占位，
            # 但明确告诉前端不要将它渲染为真实的 0% 路线进度。
            merged["progress_available"] = False
        run.live_progress = merged

    @staticmethod
    def _update_preflight_nodes(run: RunRecord, states: list[dict]) -> None:
        """每次 supervisorctl status 快照立即写入运行状态，供网页下一次轮询显示。"""
        run.preflight = run.preflight or {}
        run.preflight["node_states"] = states

    @staticmethod
    def _update_ros_service_status(run: RunRecord, message: str) -> None:
        """发布服务发现阶段，避免节点预检完成后前端长期没有新的可见状态。"""
        run.preflight = run.preflight or {}
        run.preflight["ros_service"] = {"ok": None, "message": message}
        run.preflight["node_states_checked_at"] = now_iso()

    @staticmethod
    def _update_recovery_nodes(run: RunRecord, states: list[dict]) -> None:
        run.preflight = run.preflight or {}
        recovery = run.preflight.setdefault("recovery", {})
        recovery["node_states"] = states
        recovery["node_states_checked_at"] = now_iso()
        # 主面板在人工恢复时展示当前快照，而不是恢复前的旧节点状态。
        run.preflight["node_states"] = states
        run.preflight["node_states_checked_at"] = recovery["node_states_checked_at"]

    @staticmethod
    def _record_intervention(run: RunRecord, attempt: int, action: str, detail: str) -> None:
        run.interventions.append({"at": now_iso(), "attempt": attempt, "action": action, "detail": detail})

    def _recover_after_manual_intervention(self, run: RunRecord, cancel_event: threading.Event | None = None) -> tuple[bool, str]:
        """继续前完整重做依赖编排、服务发现与最终节点总闸。"""
        gateway = RobotGateway(self.settings.load(), lambda states: self._update_recovery_nodes(run, states))
        preflight = gateway.preflight(run.case, cancel_event=cancel_event)
        recovery = preflight.to_dict()
        run.preflight = run.preflight or {}
        run.preflight["recovery"] = recovery
        if not preflight.ok:
            return False, preflight.message
        recovery["ros_service"] = {"ok": None, "message": "正在等待 ROS2 服务恢复：/start_execute_tasks（最长 300 秒）"}
        service_ok, service_message = self.executor.wait_until_available(
            timeout_s=300,
            cancel_event=cancel_event,
            status_callback=lambda message: recovery.__setitem__("ros_service", {"ok": None, "message": message}),
        )
        recovery["ros_service"] = {"ok": service_ok, "message": service_message}
        if cancel_event and cancel_event.is_set():
            return False, "测试已取消"
        if not service_ok:
            return False, service_message
        dependencies_ok, dependencies_message, states = gateway.confirm_dependencies_ready(cancel_event=cancel_event)
        recovery["node_states"] = states
        recovery["final_dependency_gate"] = {"ok": dependencies_ok, "message": dependencies_message}
        if not dependencies_ok:
            return False, f"依赖节点未稳定就绪：{dependencies_message}"
        return True, "依赖节点与 ROS2 服务已恢复就绪"

    def _write_report(self, run: RunRecord) -> None:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        stem = self._report_stem(run)
        csv_target = self.report_dir / f"{stem}.csv"
        with csv_target.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Run_ID", "Test_ID", "Config_File", "Community", "Building", "Unit", "Floor", "Door", "Status", "Message", "Duration_s", "Started_At"])
            for item in run.attempts:
                p = run.case.parameters
                writer.writerow([run.id, f"T-{item.index:03d}", run.case.filename, p.community, p.building, p.unit, p.floor, p.door, item.status, item.message, item.duration_s, item.started_at])
        self._write_html_report(run, self.report_dir / f"{stem}.html", csv_target.name)

    def _report_stem(self, run: RunRecord) -> str:
        """生成面向测试人员可读且可安全落盘的报告文件名。"""
        alias = self._case_alias(run.case.id)
        label = alias or Path(run.case.filename).stem
        label = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", label)
        label = re.sub(r"\s+", "_", label).strip("._ ")[:60] or "测试用例"
        try:
            timestamp = datetime.fromisoformat(str(run.started_at).replace("Z", "+00:00")).strftime("%Y%m%d_%H%M%S")
        except (TypeError, ValueError):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"报告_{timestamp}_{label}_{run.id}"

    def _write_html_report(self, run: RunRecord, target: Path, csv_name: str) -> None:
        """生成单文件报告：轨迹 SVG（及其内嵌地图 PNG）直接写入 HTML。"""
        summary = run.to_dict()["summary"]
        success_percent = float(summary["passRate"])
        esc = lambda value: html.escape(str(value or "—"))
        case_alias = self._case_alias(run.case.id)
        case_display_name = case_alias or run.case.filename
        status_text = {"completed": "已完成", "failed": "失败已终止", "cancelled": "已取消", "blocked": "已拦截"}.get(run.status, run.status)
        rows = "".join(
            f"<tr><td>T-{item.index:03d}</td><td>{esc(_format_report_time(item.started_at))}</td><td class=\"{esc(item.status)}\">{esc(item.status.upper())}</td><td>{item.duration_s / 60:.2f} 分钟</td><td>{esc(item.message)}</td></tr>"
            for item in run.attempts
        ) or "<tr><td colspan=\"5\">未执行到任务调用阶段。</td></tr>"
        action_labels = {
            "released_estop": "解除急停后继续",
            "continue_observing": "关闭提醒并继续观察",
            "mark_attempt_failed": "人工判定本轮失败",
            "recovery_requested": "请求人工恢复后的预检",
            "recovery_ready": "恢复预检通过",
            "recovery_blocked": "恢复预检未通过",
            "scenario_applied": "测试前应用场景方案",
            "scenario_restored": "测试结束后恢复常规方案",
            "scenario_restore_failed": "场景方案自动恢复失败",
        }
        intervention_rows = "".join(
            f"<tr><td>{esc(_format_report_time(item.get('at')))}</td><td>T-{int(item.get('attempt') or 0):03d}</td><td>{esc(action_labels.get(item.get('action'), item.get('action')))}</td><td>{esc(item.get('detail'))}</td></tr>"
            for item in run.interventions
        ) or "<tr><td colspan=\"4\">本次运行未发生人工干预。</td></tr>"
        evidence = []
        for item in run.attempts:
            visuals = (item.trajectory or {}).get("visualizations", [])
            cards = []
            for view in visuals:
                if not isinstance(view.get("file"), str):
                    continue
                svg_target = Path(view["file"]).resolve()
                report_root = self.report_dir.resolve()
                if not svg_target.is_relative_to(report_root) or svg_target.suffix != ".svg" or not svg_target.is_file():
                    continue
                # SVG 本身已以内嵌 PNG 保存 PGM 底图；直接嵌入后，下载的 HTML 不再依赖旁路图片文件。
                cards.append(f"<figure><figcaption>{esc(view.get('label', view.get('map_id')))}</figcaption>{svg_target.read_text(encoding='utf-8')}</figure>")
            integrity_warning = (item.trajectory or {}).get("integrity_warning")
            warning = f"<p class=\"notice\">{esc(integrity_warning)}</p>" if integrity_warning else ""
            body = warning + ("".join(cards) or "<p class=\"notice\">未采集到可验证的地图坐标轨迹；该轮证据不完整。</p>")
            evidence.append(f"<section class=\"attempt\"><h3>T-{item.index:03d} 轨迹证据 <span>{esc(item.status.upper())}</span></h3>{body}</section>")
        evidence_html = "".join(evidence) or "<p class=\"notice\">测试未进入轨迹采集阶段，因此没有运行轨迹。</p>"
        p = run.case.parameters
        status_class = run.status if run.status in {"completed", "failed", "cancelled", "blocked"} else "unknown"
        target.write_text(f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>运行验证报告 {esc(run.id)}</title>
  <style>
    :root {{
      color-scheme: light;
      --canvas: #f5f5f7;
      --surface: #ffffff;
      --surface-subtle: #f5f5f7;
      --line: #d2d2d7;
      --line-subtle: #e5e5ea;
      --ink: #1d1d1f;
      --muted: #6e6e73;
      --blue: #0071e3;
      --blue-soft: #e8f2ff;
      --success: #248a3d;
      --success-soft: #e9f8ed;
      --warning: #a86600;
      --warning-soft: #fff6e0;
      --danger: #c5221f;
      --danger-soft: #fff0ef;
      --shadow: 0 10px 30px rgba(0, 0, 0, .06);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--canvas); color: var(--ink); font: 14px/1.55 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Noto Sans SC", "Microsoft YaHei", sans-serif; }}
    .report-shell {{ max-width: 1240px; margin: 0 auto; padding: 42px 28px 56px; }}
    .report-header {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 30px 32px; border: 1px solid var(--line); border-radius: 18px; background: var(--surface); box-shadow: var(--shadow); }}
    .eyebrow {{ margin: 0 0 8px; color: var(--blue); font: 700 11px/1.2 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; letter-spacing: .1em; }}
    h1 {{ margin: 0; font-size: clamp(28px, 4vw, 38px); line-height: 1.15; letter-spacing: -.035em; }}
    .header-copy {{ max-width: 760px; margin: 12px 0 0; color: var(--muted); }}
    .status-badge {{ display: inline-flex; flex: none; align-items: center; gap: 7px; padding: 7px 10px; border: 1px solid currentColor; border-radius: 999px; font-size: 12px; font-weight: 700; white-space: nowrap; }}
    .status-badge::before {{ content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }}
    .status-badge.completed {{ color: var(--success); background: var(--success-soft); }}
    .status-badge.failed, .status-badge.blocked {{ color: var(--danger); background: var(--danger-soft); }}
    .status-badge.cancelled {{ color: var(--warning); background: var(--warning-soft); }}
    .status-badge.unknown {{ color: var(--muted); background: var(--surface-subtle); }}
    .report-summary {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }}
    .summary-metric {{ min-height: 116px; padding: 18px; border: 1px solid var(--line); border-radius: 15px; background: var(--surface); }}
    .summary-metric small {{ display: block; color: var(--muted); font-size: 12px; }}
    .summary-metric strong {{ display: block; margin-top: 8px; font-size: 28px; line-height: 1; letter-spacing: -.035em; font-variant-numeric: tabular-nums; }}
    .summary-metric .metric-detail {{ display: block; margin-top: 8px; color: var(--muted); font-size: 12px; }}
    .pass-rate {{ margin-top: 16px; padding: 20px; border: 1px solid var(--line); border-radius: 15px; background: var(--surface); }}
    .pass-rate-head {{ display: flex; align-items: baseline; justify-content: space-between; gap: 16px; }}
    .pass-rate h2, .section-title h2 {{ margin: 0; font-size: 17px; letter-spacing: -.02em; }}
    .pass-rate b {{ color: var(--success); font-size: 22px; font-variant-numeric: tabular-nums; }}
    .progress-track {{ height: 8px; margin-top: 14px; overflow: hidden; border-radius: 999px; background: var(--line-subtle); }}
    .progress-value {{ width: {success_percent:.2f}%; height: 100%; border-radius: inherit; background: var(--success); }}
    .pass-rate p {{ margin: 10px 0 0; color: var(--muted); font-size: 12px; }}
    .section-card {{ margin-top: 16px; padding: 24px; border: 1px solid var(--line); border-radius: 16px; background: var(--surface); }}
    .section-title {{ display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 17px; }}
    .section-title p {{ margin: 0; color: var(--muted); font-size: 12px; }}
    .context-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 0; }}
    .context-item {{ min-width: 0; padding: 13px 14px; border-radius: 12px; background: var(--surface-subtle); }}
    .context-item dt {{ color: var(--muted); font-size: 11px; }}
    .context-item dd {{ margin: 4px 0 0; overflow-wrap: anywhere; color: var(--ink); font-weight: 650; }}
    .table-scroll {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 12px; }}
    table {{ width: 100%; min-width: 720px; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 13px 14px; border-bottom: 1px solid var(--line-subtle); text-align: left; vertical-align: top; }}
    tr:last-child td {{ border-bottom: 0; }}
    th {{ background: var(--surface-subtle); color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: .04em; white-space: nowrap; }}
    td {{ overflow-wrap: anywhere; }}
    td.passed {{ color: var(--success); font-weight: 700; }}
    td.failed {{ color: var(--danger); font-weight: 700; }}
    td.cancelled {{ color: var(--warning); font-weight: 700; }}
    .evidence-card {{ break-inside: avoid; margin-top: 16px; padding: 22px; border: 1px solid var(--line); border-radius: 16px; background: var(--surface); }}
    .evidence-card:first-of-type {{ margin-top: 0; }}
    .evidence-card h3 {{ display: flex; align-items: center; gap: 8px; margin: 0 0 14px; font-size: 16px; letter-spacing: -.015em; }}
    .evidence-card h3 span {{ padding: 3px 7px; border-radius: 999px; background: var(--surface-subtle); color: var(--muted); font: 700 10px/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    figure {{ break-inside: avoid; margin: 14px 0 0; padding: 14px; border: 1px solid var(--line-subtle); border-radius: 12px; background: var(--surface-subtle); }}
    figcaption {{ margin-bottom: 10px; color: var(--muted); font-size: 12px; font-weight: 700; }}
    figure svg {{ display: block; width: 100%; height: auto; border: 1px solid var(--line); border-radius: 8px; background: #fff; }}
    .notice {{ margin: 0; padding: 12px 14px; border-left: 3px solid var(--warning); border-radius: 8px; background: var(--warning-soft); color: #684400; }}
    .report-footer {{ margin: 22px 2px 0; color: var(--muted); font-size: 12px; }}
    @media (max-width: 760px) {{
      .report-shell {{ padding: 20px 14px 36px; }}
      .report-header {{ display: block; padding: 24px 21px; }}
      .status-badge {{ margin-top: 16px; }}
      .report-summary {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .section-card, .evidence-card {{ padding: 18px; }}
      .context-grid {{ grid-template-columns: 1fr; }}
    }}
    @media print {{
      @page {{ margin: 14mm; }}
      body {{ background: #fff; font-size: 11pt; print-color-adjust: exact; -webkit-print-color-adjust: exact; }}
      .report-shell {{ max-width: none; padding: 0; }}
      .report-header, .summary-metric, .pass-rate, .section-card, .evidence-card {{ box-shadow: none; break-inside: avoid; }}
      .report-summary {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
      .section-card {{ break-inside: auto; }}
      thead {{ display: table-header-group; }}
      tr {{ break-inside: avoid; }}
      .table-scroll {{ overflow: visible; }}
    }}
  </style>
</head>
<body>
  <main class="report-shell">
    <header class="report-header">
      <div>
        <p class="eyebrow">RY ALETHEIA / RUN EVIDENCE</p>
        <h1>自动测试运行报告</h1>
        <p class="header-copy">运行 ID：{esc(run.id)} · 用例：{esc(case_display_name)} · 开始：{esc(_format_report_time(run.started_at))}</p>
      </div>
      <span class="status-badge {status_class}">{esc(status_text)}</span>
    </header>

    <section class="report-summary" aria-label="运行摘要">
      <article class="summary-metric"><small>计划轮次</small><strong>{run.requested_count}</strong><span class="metric-detail">本次计划执行总数</span></article>
      <article class="summary-metric"><small>已执行轮次</small><strong>{summary['completed']}</strong><span class="metric-detail">已产生结果的轮次</span></article>
      <article class="summary-metric"><small>通过 / 失败</small><strong>{summary['passed']} / {summary['failed']}</strong><span class="metric-detail">取消 {summary['cancelled']} 轮</span></article>
      <article class="summary-metric"><small>通过率</small><strong>{summary['passRate']}%</strong><span class="metric-detail">取消与未执行不计入</span></article>
    </section>

    <section class="pass-rate" aria-label="通过率构成">
      <div class="pass-rate-head"><h2>已执行轮次通过率</h2><b>{summary['passRate']}%</b></div>
      <div class="progress-track" role="img" aria-label="通过率 {summary['passRate']}%"><div class="progress-value"></div></div>
      <p>通过 {summary['passed']} 轮；失败 {summary['failed']} 轮；已取消 {summary['cancelled']} 轮不计入通过率。</p>
    </section>

    <section class="section-card">
      <div class="section-title"><h2>运行信息</h2><p>随报告归档 CSV：{esc(csv_name)}</p></div>
      <dl class="context-grid">
        <div class="context-item"><dt>用例</dt><dd>用例：{esc(case_display_name)}</dd></div>
        <div class="context-item"><dt>任务文件</dt><dd>{esc(run.case.filename)}</dd></div>
        <div class="context-item"><dt>场景</dt><dd>{esc(run.case.name)}</dd></div>
        <div class="context-item"><dt>配送目标</dt><dd>{esc(p.community)} · {p.building} 栋 {p.unit} 单元 {p.floor} 楼 {p.door}</dd></div>
        <div class="context-item"><dt>开始时间</dt><dd>{esc(_format_report_time(run.started_at))}</dd></div>
        <div class="context-item"><dt>结束时间</dt><dd>{esc(_format_report_time(run.finished_at))}</dd></div>
      </dl>
    </section>

    <section class="section-card">
      <div class="section-title"><h2>轮次结果</h2><p>每轮服务反馈与执行耗时</p></div>
      <div class="table-scroll"><table><thead><tr><th>轮次</th><th>开始时间</th><th>结果</th><th>耗时</th><th>服务反馈</th></tr></thead><tbody>{rows}</tbody></table></div>
    </section>

    <section class="section-card">
      <div class="section-title"><h2>人工干预与停滞处置记录</h2><p>本次执行过程的可追溯人工操作</p></div>
      <div class="table-scroll"><table><thead><tr><th>时间</th><th>关联轮次</th><th>操作</th><th>说明</th></tr></thead><tbody>{intervention_rows}</tbody></table></div>
    </section>

    <section class="section-card">
      <div class="section-title"><h2>地图运行轨迹证据</h2><p>蓝线为实际轨迹，黄虚线为理想路线，红线为虚拟墙</p></div>
      {evidence_html.replace('class="attempt"', 'class="evidence-card"')}
    </section>
    <footer class="report-footer">由 RY Aletheia 自动生成。该文件可与 CSV 伴随文件一起离线归档。</footer>
  </main>
</body>
</html>''', encoding="utf-8")

    def _case_alias(self, case_id: str) -> str:
        """报告在生成时读取当前别名；配置不可读时仍可可靠回退为任务文件名。"""
        try:
            alias = self.settings.load().case_aliases.get(case_id, "")
        except (AttributeError, OSError, ValueError):
            return ""
        return alias.strip() if isinstance(alias, str) else ""

    def _write_trajectory(self, run: RunRecord, index: int, trajectory: dict, assets: list[CachedMapAsset]) -> Path:
        import json
        index = int(getattr(run, "_sequence_attempt_index", index))
        target_dir = self.report_dir / f"run_{run.id}_trajectory"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"T-{index:03d}.json"
        asset_by_id = {asset.id: asset for asset in assets}
        saved_plan = trajectory.get("route_plan")
        ideal_routes = MapAssetCache.ideal_routes_from_plan(saved_plan) if isinstance(saved_plan, list) else MapAssetCache.ideal_routes(run.case.source, assets)
        visualizations = []
        render_errors = []
        virtual_walls: dict[str, list[dict]] = {}
        # 同一轮可出现 P1→P2→P1。按地图汇总多个独立路径，不能只保留最后一段，也不能跨切图强连直线。
        segments_by_asset: dict[str, dict] = {}
        for source_segment in trajectory.get("segments", []):
            map_id = source_segment.get("map_id")
            if map_id not in asset_by_id:
                continue
            aggregate = segments_by_asset.setdefault(map_id, {"map_id": map_id, "map_label": source_segment.get("map_label"), "paths": []})
            points = source_segment.get("points", [])
            if points:
                # 保留地图进入批次及 JSON 路线段。渲染器据此分别着色，
                # 不能把同地图的去程与返程混成一条轨迹。
                aggregate["paths"].append({
                    "points": points,
                    "map_epoch": source_segment.get("map_epoch"),
                    "route_index": source_segment.get("route_index"),
                    "route_name": source_segment.get("route_name"),
                    "started_ns": points[0].get("timestamp_ns", 0),
                    "ended_ns": points[-1].get("timestamp_ns", 0),
                })
        for aggregate in segments_by_asset.values():
            aggregate["paths"].sort(key=lambda item: (item.get("started_ns", 0), item.get("map_epoch", 0)))
        # 即使 /odom 尚未出现有效点，也输出地图、理想路线和虚拟墙图层，确保报告有可审阅的轨迹证据版面。
        for asset in assets:
            segment = segments_by_asset.get(asset.id, {"map_id": asset.id, "map_label": asset.label, "paths": []})
            svg_target = target_dir / f"T-{index:03d}_{asset.id}.svg"
            try:
                walls = MapAssetCache.virtual_walls(asset)
                virtual_walls[asset.id] = walls
                render_svg(asset, segment, svg_target, ideal_routes.get(asset.id, []), walls)
                point_count = sum(len(path.get("points", [])) for path in segment["paths"])
                visualizations.append({
                    "map_id": asset.id, "label": asset.label, "file": str(svg_target),
                    "point_count": point_count, "has_actual_trajectory": point_count > 0,
                })
            except (OSError, TrajectoryRenderError) as exc:
                render_errors.append(f"{asset.label}：{exc}")
        trajectory["file"] = str(target)
        trajectory["ideal_routes"] = ideal_routes
        trajectory["virtual_walls"] = virtual_walls
        trajectory["visualizations"] = visualizations
        if render_errors:
            trajectory["render_errors"] = render_errors
        target.write_text(json.dumps(trajectory, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return target
