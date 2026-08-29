from __future__ import annotations

import shutil
import threading
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .models import TestCase
from .settings import RobotSettings
from .supervisor import SupervisorClient

DEPENDENCY_STABILITY_TIMEOUT_SECONDS = 300.0


@dataclass
class PreflightResult:
    ok: bool
    message: str
    node_states: list[dict]
    task_sync: str
    orchestration: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class RobotGateway:
    """本机运行网关：节点健康检查与任务文件同步均通过此处完成。"""

    def __init__(self, settings: RobotSettings, status_callback: Callable[[list[dict]], None] | None = None) -> None:
        self.settings = settings
        self.status_callback = status_callback

    def preflight(self, case: TestCase, cancel_event: threading.Event | None = None) -> PreflightResult:
        if cancel_event and cancel_event.is_set():
            return PreflightResult(False, "测试已取消", [], "未执行")
        orchestration = None
        if self.settings.dependency_plan.get("enabled"):
            orchestration, error = self._apply_dependency_plan(cancel_event)
            all_ready, ready_detail = (False, error) if error else self._wait_all_dependencies_running(cancel_event)
            orchestration["all_ready"] = all_ready
            orchestration["all_ready_detail"] = ready_detail
            states, status_error = self._check_supervisor()
            if error:
                return PreflightResult(False, error, states, "未执行", orchestration)
            if not all_ready:
                return PreflightResult(False, f"运行依赖未全部稳定就绪：{ready_detail}", states, "未执行", orchestration)
            if status_error:
                return PreflightResult(False, status_error, states, "未执行", orchestration)
        states, error = self._check_supervisor()
        required_failed = [item for item in states if item["required"] and item["status"] != "RUNNING"]
        if error:
            return PreflightResult(False, error, states, "未执行", orchestration)
        if required_failed:
            return PreflightResult(False, "必需 Supervisor 节点未全部处于 RUNNING 状态", states, "未执行", orchestration)
        sync_ok, sync_message = self._sync_if_missing(case)
        return PreflightResult(sync_ok, sync_message if sync_ok else f"任务同步失败：{sync_message}", states, sync_message, orchestration)

    def confirm_dependencies_ready(self, cancel_event: threading.Event | None = None) -> tuple[bool, str, list[dict]]:
        """ROS 服务就绪后再次执行总闸，防止节点在初始化过程中回落到 STARTING。"""
        if cancel_event and cancel_event.is_set():
            return False, "测试已取消", []
        if not self.settings.dependency_plan.get("enabled"):
            states, error = self._check_supervisor()
            failed = [item for item in states if item["required"] and item["status"] != "RUNNING"]
            return not error and not failed, error or ("必需节点未全部 RUNNING" if failed else "全部节点 RUNNING"), states
        ready, detail = self._wait_all_dependencies_running(cancel_event)
        states, error = self._check_supervisor()
        return ready and not error, error or detail, states

    def restart_configured_dependencies(self) -> tuple[bool, str]:
        """重启已配置的测试依赖，使恢复后的启动脚本真正重新被读取。

        该操作只复用操作者已保存的受控依赖编排，绝不猜测或控制未登记的
        Supervisor 节点。没有完整编排时只重启已配置的定位/导航启动消费者；
        若消费者也无法识别，必须明确失败，不能把“脚本已恢复”伪装成
        “车辆已恢复常规参数”。
        """
        if self.settings.dependency_plan.get("enabled"):
            _orchestration, error = self._apply_dependency_plan()
            if error:
                return False, error
            ready, detail = self._wait_all_dependencies_running()
            if not ready:
                return False, detail
            _states, status_error = self._check_supervisor()
            return (False, status_error) if status_error else (True, "依赖节点已按已保存编排重启并稳定 RUNNING")
        # 未配置完整测试编排时，仍可根据本车已配置的“定位/导航启动”节点
        # 重启最小消费者集合。这样场景脚本不会只在磁盘恢复、运行中却仍保留旧参数。
        consumers = [
            str(item["supervisor"])
            for item in self.settings.nodes
            if item.get("id") in {"localization", "bringup"}
            or re.search(r"(?:lightning|fcrp)", str(item.get("supervisor", "")), re.IGNORECASE)
        ]
        consumers = list(dict.fromkeys(consumers))
        if not consumers:
            return False, "未配置可识别的定位或导航启动 Supervisor 节点；请在运行依赖中登记 localization/bringup 节点"
        client = SupervisorClient(self.settings.supervisor_command, self.settings.command_timeout_s)
        try:
            statuses = {item.name: item.status for item in client.discover()}
        except RuntimeError as exc:
            return False, str(exc)
        errors = []
        with ThreadPoolExecutor(max_workers=min(2, len(consumers))) as pool:
            futures = {
                pool.submit(getattr(client, "restart" if statuses.get(name) == "RUNNING" else "start"), name): name
                for name in consumers
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except RuntimeError as exc:
                    errors.append(f"{futures[future]}：{exc}")
        ready, detail = self._wait_stage_running(client, consumers)
        if not ready:
            return False, f"最小场景依赖未稳定就绪：{detail}"
        if errors:
            return True, f"最小场景依赖已稳定 RUNNING（控制命令反馈：{'；'.join(errors)}）"
        return True, "定位与导航启动节点已重启并稳定 RUNNING"

    def _check_supervisor(self) -> tuple[list[dict], str | None]:
        try:
            parsed = {item.name: item.status for item in SupervisorClient(self.settings.supervisor_command, self.settings.command_timeout_s).discover()}
        except RuntimeError as exc:
            return [], str(exc)
        states = self._states_from_parsed(parsed)
        self._publish_states(states)
        return states, None

    def _states_from_parsed(self, parsed: dict[str, str]) -> list[dict]:
        states: list[dict] = []
        for node in self._health_nodes():
            name = str(node["supervisor"])
            states.append({"id": node.get("id", name), "label": node["label"], "supervisor": name, "required": bool(node.get("required", True)), "status": parsed.get(name, "MISSING")})
        return states

    def _publish_states(self, states: list[dict]) -> None:
        if self.status_callback:
            self.status_callback(states)

    def _apply_dependency_plan(self, cancel_event: threading.Event | None = None) -> tuple[dict, str | None]:
        """按当前状态选择 restart/start，并等待每个阶段稳定就绪。"""
        plan = self.settings.dependency_plan
        stages = []
        if not plan.get("steps"):
            return {"enabled": True, "stages": stages}, "测试依赖编排已启用，但未配置启动阶段"
        client = SupervisorClient(self.settings.supervisor_command, self.settings.command_timeout_s)
        for index, step in enumerate(plan["steps"], start=1):
            if cancel_event and cancel_event.is_set():
                return {"enabled": True, "stages": stages}, "测试已取消"
            nodes = list(step["nodes"])
            stage = {"index": index, "nodes": nodes, "actions": {}, "restart": "pending", "ready": False, "wait_seconds": int(step.get("wait_seconds", 0))}
            stages.append(stage)
            try:
                current_statuses = {item.name: item.status for item in client.discover()}
                self._publish_states(self._states_from_parsed(current_statuses))
            except RuntimeError as exc:
                return {"enabled": True, "stages": stages}, f"依赖编排第 {index} 阶段无法读取节点状态：{exc}"
            actions = {node: "restart" if current_statuses.get(node) == "RUNNING" else "start" for node in nodes}
            stage["actions"] = actions
            control_errors = []
            with ThreadPoolExecutor(max_workers=min(8, len(nodes))) as pool:
                futures = {pool.submit(getattr(client, action), node): node for node, action in actions.items()}
                for future in as_completed(futures):
                    try:
                        future.result()
                    except RuntimeError as exc:
                        node = futures[future]
                        control_errors.append(f"{node}（{actions[node]}）：{exc}")
            if cancel_event and cancel_event.is_set():
                return {"enabled": True, "stages": stages}, "测试已取消"
            # Supervisor 可能在拉起、重试或超时时返回控制命令错误；不据此抢先判失败，仍以实际 status 持续等待。
            stage["control_errors"] = control_errors
            stage["restart"] = "accepted_with_feedback" if control_errors else "accepted"
            ready, detail = self._wait_stage_running(client, nodes, cancel_event)
            if not ready:
                stage["restart"] = "timeout"
                return {"enabled": True, "stages": stages}, f"依赖编排第 {index} 阶段未就绪：{detail}"
            stage["ready"] = True
            if stage["wait_seconds"]:
                if cancel_event and cancel_event.wait(stage["wait_seconds"]):
                    return {"enabled": True, "stages": stages}, "测试已取消"
        return {"enabled": True, "stages": stages}, None

    def _wait_stage_running(self, client: SupervisorClient, nodes: list[str], cancel_event: threading.Event | None = None, timeout_s: float = DEPENDENCY_STABILITY_TIMEOUT_SECONDS) -> tuple[bool, str]:
        """只有连续 5 次全部 RUNNING 才放行；取消和超时都必须结束等待。"""
        interval_s, required_samples = 1.0, 5
        last_statuses: dict[str, str] = {}
        stable_samples = 0
        deadline = time.monotonic() + max(1.0, float(timeout_s))
        while True:
            if cancel_event and cancel_event.is_set():
                return False, "测试已取消"
            if time.monotonic() >= deadline:
                pending = ", ".join(f"{name}={last_statuses.get(name, 'MISSING')}" for name in nodes if last_statuses.get(name) != "RUNNING")
                return False, f"等待依赖节点稳定 RUNNING 超时（{int(timeout_s)} 秒）：{pending or '状态未稳定'}"
            try:
                last_statuses = {item.name: item.status for item in client.discover()}
                self._publish_states(self._states_from_parsed(last_statuses))
            except RuntimeError as exc:
                return False, str(exc)
            pending = [f"{name}={last_statuses.get(name, 'MISSING')}" for name in nodes if last_statuses.get(name) != "RUNNING"]
            if not pending:
                stable_samples += 1
                if stable_samples >= required_samples:
                    return True, f"连续 {required_samples} 次检查均为 RUNNING"
            else:
                stable_samples = 0
            wait_s = min(interval_s, max(0.0, deadline - time.monotonic()))
            if cancel_event:
                if cancel_event.wait(wait_s):
                    return False, "测试已取消"
            else:
                time.sleep(wait_s)

    def _wait_all_dependencies_running(self, cancel_event: threading.Event | None = None) -> tuple[bool, str]:
        """最终总闸：页面依赖状态中的每个节点都必须稳定 RUNNING 才可执行。"""
        nodes = [str(item["supervisor"]) for item in self._health_nodes() if item.get("required", True)]
        client = SupervisorClient(self.settings.supervisor_command, self.settings.command_timeout_s)
        return self._wait_stage_running(client, nodes, cancel_event)

    def _health_nodes(self) -> list[dict]:
        """优先使用操作者选择的默认监控节点，兼容旧版本配置。"""
        plan = self.settings.dependency_plan
        if self.settings.monitor_nodes:
            return [{"id": name, "label": name, "supervisor": name, "required": True} for name in self.settings.monitor_nodes]
        if plan.get("enabled") and plan.get("steps"):
            return [
                {"id": name, "label": name, "supervisor": name, "required": True}
                for step in plan["steps"]
                for name in step["nodes"]
            ]
        return self.settings.nodes

    def _sync_if_missing(self, case: TestCase) -> tuple[bool, str]:
        destination_dir = Path(self.settings.task_directory)
        destination = destination_dir / case.filename
        if destination.is_file():
            return True, "本机任务目录已存在同名文件，未覆盖"
        if not destination_dir.is_dir():
            return False, f"本机任务目录不存在：{self.settings.task_directory}"
        try:
            # copy2 保留时间戳，且 destination 已确认不存在，避免覆盖机器人现有资产。
            shutil.copy2(case.source, destination)
        except OSError as exc:
            return False, str(exc)
        return True, "已复制到本机任务目录"
