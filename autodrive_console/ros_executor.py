from __future__ import annotations

import os
import time
import threading
from typing import Callable

from .models import TaskParameters


class RosTaskExecutor:
    """唯一负责 ROS 服务调用，避免 Web 层耦合 ROS 细节。"""

    def __init__(self, service_name: str = "/start_execute_tasks", timeout_s: float = 300.0) -> None:
        self.service_name = service_name
        self.timeout_s = timeout_s

    def wait_until_available(self, timeout_s: float = 300.0, cancel_event: threading.Event | None = None, status_callback: Callable[[str], None] | None = None) -> tuple[bool, str]:
        """在执行前确认 ROS2 服务已经完成 DDS 注册，避免重启后的发现竞态。

        服务发现可能需要数分钟；每秒上报一次等待阶段，并允许操作者在尚未下发
        任务前安全终止，避免网页只显示节点已就绪而看似卡住。
        """
        if cancel_event and cancel_event.is_set():
            return False, f"操作员已终止：不等待 ROS2 服务 {self.service_name}"
        import rclpy
        from rclpy.node import Node
        from master_interfaces.srv import StartExecuteTasks

        if not rclpy.ok():
            rclpy.init()
        node = Node("autodrive_test_console_readiness")
        started = time.monotonic()
        try:
            client = node.create_client(StartExecuteTasks, self.service_name)
            last_graph_detail = ""
            while time.monotonic() - started < timeout_s:
                if cancel_event and cancel_event.is_set():
                    return False, f"操作员已终止：不再等待 ROS2 服务 {self.service_name}"
                elapsed = time.monotonic() - started
                if status_callback:
                    status_callback(f"正在等待 ROS2 服务就绪：{self.service_name}（{elapsed:.0f}/{timeout_s:.0f} 秒）")
                if client.wait_for_service(timeout_sec=min(1.0, max(0.1, timeout_s - elapsed))):
                    return True, f"ROS2 服务已就绪：{self.service_name}"
                # 每 10 秒读取一次 ROS 图，不增加高频负担；同名服务出现在图中并不
                # 等于当前客户端已经可调用，不能据此提前下发真实任务。
                if int(elapsed) % 10 == 0:
                    last_graph_detail = self._service_graph_detail(node)
                    if self._service_visible_in_graph(node):
                        last_graph_detail = f"ROS 图已发现 {self.service_name}，但内置客户端尚未可调用；将继续等待，不会提前下发任务"
                    if status_callback and last_graph_detail:
                        status_callback(f"正在等待 ROS2 服务就绪：{self.service_name}（{elapsed:.0f}/{timeout_s:.0f} 秒；{last_graph_detail}）")
            detail = last_graph_detail or self._service_graph_detail(node)
            suffix = f"；{detail}" if detail else ""
            return False, f"等待 ROS2 服务就绪超时（{timeout_s:.0f}s）：{self.service_name}{suffix}"
        finally:
            node.destroy_node()

    def _service_graph_detail(self, node) -> str:
        """服务发现失败时给出可操作的 DDS 诊断，不调用 ROS2 CLI 或 daemon。"""
        try:
            services = dict(node.get_service_names_and_types())
        except Exception as exc:
            return f"无法读取 ROS 服务图：{exc}"
        types = services.get(self.service_name)
        domain = os.environ.get("ROS_DOMAIN_ID", "0（默认）")
        rmw = os.environ.get("RMW_IMPLEMENTATION", "默认 rmw_fastrtps_cpp")
        transport = os.environ.get("FASTDDS_BUILTIN_TRANSPORTS", "默认")
        if types:
            return f"ROS 图已发现同名服务，类型={','.join(types)}；客户端仍未就绪（域={domain}，RMW={rmw}，传输={transport}）"
        related = [name for name in services if "task" in name.lower() or "execute" in name.lower()]
        related_text = ", ".join(sorted(related)[:4]) if related else "无任务类服务"
        return f"ROS 图未发现 {self.service_name}（域={domain}，RMW={rmw}，传输={transport}；可见任务服务：{related_text}）"

    def _service_visible_in_graph(self, node) -> bool:
        try:
            services = dict(node.get_service_names_and_types())
        except Exception:
            return False
        types = services.get(self.service_name, [])
        return "master_interfaces/srv/StartExecuteTasks" in types

    def execute(self, params: TaskParameters, log: Callable[[str], None], cancel_event: threading.Event | None = None, interrupt_event: threading.Event | None = None, timeout_s: float | None = None) -> tuple[bool, str, float]:
        # 延迟导入，允许在没有 ROS 环境时仍可启动 UI 和维护用例。
        import rclpy
        from rclpy.node import Node
        from master_interfaces.srv import StartExecuteTasks

        if not rclpy.ok():
            rclpy.init()
        node = Node("autodrive_test_console_executor")
        started = time.monotonic()
        effective_timeout = self.timeout_s if timeout_s is None else float(timeout_s)
        try:
            client = node.create_client(StartExecuteTasks, self.service_name)
            if not client.wait_for_service(timeout_sec=10.0):
                return False, f"服务不可用：{self.service_name}", round(time.monotonic() - started, 2)
            request = StartExecuteTasks.Request()
            request.community = params.community
            request.building = params.building
            request.unit = params.unit
            request.floor = params.floor
            request.door = params.door
            request.task_uuid = ""
            future = client.call_async(request)
            while rclpy.ok() and not future.done():
                if cancel_event and cancel_event.is_set():
                    future.cancel()
                    return False, "操作员已终止本次测试：已取消本地服务等待", round(time.monotonic() - started, 2)
                if interrupt_event and interrupt_event.is_set():
                    future.cancel()
                    return False, "人工判定本轮失败：已取消本地服务等待，等待车辆恢复", round(time.monotonic() - started, 2)
                if time.monotonic() - started > effective_timeout:
                    return False, f"服务调用超时（{effective_timeout:.0f}s）", round(time.monotonic() - started, 2)
                rclpy.spin_once(node, timeout_sec=0.1)
            try:
                response = future.result()
                return bool(response.success), str(response.message), round(time.monotonic() - started, 2)
            except Exception as exc:
                return False, f"服务调用异常：{exc}", round(time.monotonic() - started, 2)
        finally:
            node.destroy_node()
