"""Backend-owned Nav2 navigation to an operator-created live-map marker."""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections.abc import Callable

from .manual_map_markers import ManualMapMarkerError, ManualMapMarkerStore


LOGGER = logging.getLogger("ry_aletheia.map_marker_navigation")


class MapMarkerNavigationError(RuntimeError):
    pass


class MapMarkerNavigationConflict(MapMarkerNavigationError):
    pass


class MapMarkerNavigationUnavailable(MapMarkerNavigationError):
    pass


class MapMarkerNavigationController:
    ACTIVE_PHASES = frozenset({"checking", "navigating", "cancelling", "cancellation_unconfirmed"})
    MAX_DURATION_S = 300.0
    MONITOR_INTERVAL_S = 0.2
    CANCEL_CONFIRMATION_TIMEOUT_S = 5.0
    EMERGENCY_CONFIRMATION_WAIT_S = 1.2
    EMERGENCY_CONFIRMATION_POLL_S = 0.05
    ROUTE_FRAME_ID = "map"
    MAX_ROUTE_POINTS = 512
    ROUTE_GOAL_TOLERANCE_M = 0.5

    def __init__(
        self, marker_store: ManualMapMarkerStore, observation: object, vehicle_control: object,
        localization_status: object, *, active_run_guard: Callable[[], bool],
        transport: object | None = None, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._marker_store = marker_store
        self._observation = observation
        self._vehicle_control = vehicle_control
        self._localization_status = localization_status
        self._active_run_guard = active_run_guard
        self._transport = transport or _RosNavigateToPoseTransport()
        self._clock = clock
        self._lock = threading.RLock()
        self._phase = "idle"
        self._detail = "可右键同图地图标记后前往"
        self._goal: object | None = None
        self._started_at: float | None = None
        self._map_id: str | None = None
        self._cancel_requested_at: float | None = None
        self._route: tuple[tuple[float, float], ...] = ()
        self._goal_generation = 0
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._monitor_failed = False

    def blocks_runs(self) -> bool:
        with self._lock:
            return self._phase in self.ACTIVE_PHASES

    def status(self) -> dict[str, object]:
        self._monitor_once()
        with self._lock:
            return self._snapshot_locked()

    def begin_marker(self, marker_id: str) -> dict[str, object]:
        with self._lock:
            if self._phase in self.ACTIVE_PHASES:
                raise MapMarkerNavigationConflict("前往地图标记正在进行")
            self._phase, self._detail = "checking", "正在核验地图标记与车辆状态"
            self._goal_generation += 1
            goal_generation = self._goal_generation
            self._route = ()
        try:
            self._wait_for_safe_to_begin()
            map_id = self._require_active_map_id()
            marker = self._marker_store.resolve(map_id, marker_id)
            self._require_current_map(map_id)
            self._wait_for_safe_to_begin()
            self._require_current_map(map_id)
            handle = self._transport.send_goal(
                self.ROUTE_FRAME_ID, marker.x, marker.y, marker.yaw, self._on_result,
                lambda frame_id, points: self._on_route(
                    goal_generation, marker.x, marker.y, frame_id, points,
                ),
            )
            if handle is None:
                raise MapMarkerNavigationUnavailable("导航服务未接受目标")
        except ManualMapMarkerError as exc:
            self._fail(str(exc))
            LOGGER.warning("前往地图标记失败：%s", exc)
            raise MapMarkerNavigationConflict(str(exc)) from exc
        except MapMarkerNavigationError as exc:
            self._fail(str(exc))
            log = LOGGER.error if isinstance(exc, MapMarkerNavigationUnavailable) else LOGGER.warning
            log("前往地图标记失败：%s", exc)
            raise
        except Exception as exc:
            self._fail("导航服务不可用")
            LOGGER.exception("前往地图标记失败：导航服务不可用")
            raise MapMarkerNavigationUnavailable("导航服务不可用") from exc
        with self._lock:
            self._goal, self._started_at, self._map_id = handle, self._clock(), map_id
            self._cancel_requested_at = None
            self._phase, self._detail = "navigating", "正在前往地图标记"
            self._start_monitor_locked()
            LOGGER.info("前往地图标记已被 Nav2 接受：id=%s", marker.id)
            return self._snapshot_locked()

    def cancel(self) -> dict[str, object]:
        self._request_cancel("操作员请求取消导航")
        with self._lock:
            return self._snapshot_locked()

    def close(self) -> None:
        """Stop the independent monitor after requesting bounded Nav2 cancellation."""
        try:
            with self._lock:
                active = self._phase in {"checking", "navigating"} and self._goal is not None
            if active:
                self._request_cancel("控制台正在关闭，取消导航")
        finally:
            self._monitor_stop.set()
            thread = self._monitor_thread
            if thread and thread is not threading.current_thread():
                thread.join(timeout=self.MONITOR_INTERVAL_S * 2)
            close = getattr(self._transport, "close", None)
            if callable(close):
                close()

    def _require_safe_to_begin(self) -> None:
        if self._active_run_guard():
            raise MapMarkerNavigationConflict("自动化测试正在执行")
        vehicle = self._vehicle_control.status()
        if vehicle.get("actual_source") != "navigation" or vehicle.get("transition") is not None:
            raise MapMarkerNavigationConflict("车辆未确认处于自动驾驶控制源")
        if vehicle.get("relocalization_hold") != "idle" or vehicle.get("session", {}).get("present"):
            raise MapMarkerNavigationConflict("手动控制或手动重定位正在占用车辆")
        if vehicle.get("car_state_sync", {}).get("emergency_stop") != "confirmed":
            raise MapMarkerNavigationConflict("急停状态正在重新确认，暂不能导航")
        emergency = vehicle.get("emergency_stop")
        if not isinstance(emergency, dict) or emergency.get("state") != "normal":
            raise MapMarkerNavigationConflict("急停状态不允许导航")
        status = self._localization_status.status()
        if not isinstance(status, dict) or status.get("phase") != "normal":
            raise MapMarkerNavigationConflict("定位状态未正常")

    def _wait_for_safe_to_begin(self) -> None:
        """Give the backend-owned emergency query one bounded chance to refresh.

        `checking` keeps the map-navigation guard active, so VehicleControl's
        ROS timer is allowed to issue the non-blocking chassis query.  All
        other interlocks remain immediate failures; only a pending emergency
        confirmation is transiently waited for, and no Nav2 goal is sent
        during that interval.
        """
        deadline = time.monotonic() + self.EMERGENCY_CONFIRMATION_WAIT_S
        while True:
            try:
                self._require_safe_to_begin()
                return
            except MapMarkerNavigationConflict as exc:
                if str(exc) != "急停状态正在重新确认，暂不能导航":
                    raise
                if time.monotonic() >= deadline:
                    raise
                time.sleep(self.EMERGENCY_CONFIRMATION_POLL_S)

    def _require_active_map_id(self) -> str:
        map_id = self._observation.active_manual_map_id()
        if not isinstance(map_id, str):
            raise MapMarkerNavigationConflict("当前地图尚未确认")
        return map_id

    def _require_current_map(self, map_id: str) -> None:
        matched, reason = self._observation.verify_active_manual_map_id(map_id)
        if not matched:
            raise MapMarkerNavigationConflict(str(reason))

    def _on_result(self, result: object) -> None:
        success = bool(getattr(result, "success", result is True))
        with self._lock:
            if self._phase not in self.ACTIVE_PHASES:
                return
            self._goal, self._map_id = None, None
            self._route = ()
            cancelled = self._phase in {"cancelling", "cancellation_unconfirmed"}
            self._cancel_requested_at = None
            self._phase = "succeeded" if success else "cancelled" if cancelled else "failed"
            self._detail = "已到达地图标记" if success else "导航已取消" if cancelled else "导航未完成"
            log = LOGGER.error if self._phase == "failed" else LOGGER.info
            log("前往地图标记结束：%s", self._phase)

    def _monitor_once(self) -> None:
        """Backend-owned health check; callers never need a browser status poll."""
        with self._lock:
            phase, started_at, cancel_at = self._phase, self._started_at, self._cancel_requested_at
        if phase == "navigating":
            try:
                self._require_safe_to_begin()
                with self._lock:
                    map_id = self._map_id
                if map_id is None:
                    raise MapMarkerNavigationConflict("当前地图尚未确认")
                self._require_current_map(map_id)
            except MapMarkerNavigationConflict as exc:
                self._request_cancel(str(exc))
                return
            if started_at is not None and self._clock() - started_at >= self.MAX_DURATION_S:
                self._request_cancel("前往地图标记超时")
        elif phase == "cancelling" and cancel_at is not None and self._clock() - cancel_at >= self.CANCEL_CONFIRMATION_TIMEOUT_S:
            with self._lock:
                if self._phase == "cancelling" and self._cancel_requested_at == cancel_at:
                    self._phase = "cancellation_unconfirmed"
                    self._detail = "导航取消尚未获得 Nav2 终态确认，车辆保持互锁"
                    LOGGER.error("地图标记导航取消未获终态确认，继续保持互锁")

    def _request_cancel(self, detail: str) -> None:
        with self._lock:
            if self._phase not in {"checking", "navigating"} or self._goal is None:
                if self._phase in {"cancelling", "cancellation_unconfirmed"}:
                    return
                raise MapMarkerNavigationConflict("当前没有可取消的地图标记导航")
            self._phase, self._detail = "cancelling", detail
            self._cancel_requested_at = self._clock()
            self._route = ()
            goal = self._goal
        LOGGER.warning("地图标记导航请求取消：reason=%s", detail)
        try:
            self._transport.cancel(goal)
        except Exception:
            with self._lock:
                if self._goal is goal and self._phase == "cancelling":
                    self._phase = "cancellation_unconfirmed"
                    self._detail = "无法确认导航已取消，车辆保持互锁"
            LOGGER.exception("地图标记导航取消请求失败，继续保持互锁")

    def _start_monitor_locked(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="map-marker-navigation-monitor",
        )
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        while not self._monitor_stop.wait(self.MONITOR_INTERVAL_S):
            try:
                self._monitor_once()
            except Exception:
                if not self._monitor_failed:
                    self._monitor_failed = True
                    LOGGER.exception("地图标记导航安全监控异常")
            else:
                if self._monitor_failed:
                    self._monitor_failed = False
                    LOGGER.info("地图标记导航安全监控已恢复")

    def _fail(self, detail: str) -> None:
        with self._lock:
            self._goal, self._map_id = None, None
            self._cancel_requested_at = None
            self._route = ()
            self._phase, self._detail = "failed", detail

    def _on_route(
        self, generation: int, goal_x: float, goal_y: float, frame_id: object, points: object,
    ) -> None:
        route = self._validated_route(frame_id, points, goal_x, goal_y)
        if not route:
            return
        with self._lock:
            if generation != self._goal_generation or self._phase not in {"checking", "navigating"}:
                return
            self._route = route

    @classmethod
    def _validated_route(
        cls, frame_id: object, points: object, goal_x: float, goal_y: float,
    ) -> tuple[tuple[float, float], ...]:
        if frame_id != cls.ROUTE_FRAME_ID or not isinstance(points, (list, tuple)):
            return ()
        parsed: list[tuple[float, float]] = []
        for point in points:
            try:
                x, y = point
                x, y = float(x), float(y)
            except (TypeError, ValueError):
                return ()
            if not math.isfinite(x) or not math.isfinite(y):
                return ()
            parsed.append((x, y))
        if len(parsed) < 2:
            return ()
        end_x, end_y = parsed[-1]
        if math.hypot(end_x - goal_x, end_y - goal_y) > cls.ROUTE_GOAL_TOLERANCE_M:
            return ()
        if len(parsed) <= cls.MAX_ROUTE_POINTS:
            return tuple(parsed)
        last_index = len(parsed) - 1
        return tuple(parsed[round(index * last_index / (cls.MAX_ROUTE_POINTS - 1))]
                     for index in range(cls.MAX_ROUTE_POINTS))

    def _snapshot_locked(self) -> dict[str, object]:
        route = None
        if self._route:
            route = {
                "frame_id": self.ROUTE_FRAME_ID,
                "points": [{"x": x, "y": y} for x, y in self._route],
            }
        return {
            "phase": self._phase,
            "detail": self._detail,
            "can_begin": self._phase not in self.ACTIVE_PHASES,
            "can_cancel": self._phase == "navigating",
            "route": route,
        }


class _RosNavigateToPoseTransport:
    """HTTP-facing adapter; the worker exclusively owns the ROS executor."""

    ACTION_NAME = "/navigate_to_pose"
    DISCOVERY_TIMEOUT_S = 10.0

    def __init__(self) -> None:
        self._worker = _RosNavigateToPoseWorker(
            self.ACTION_NAME, discovery_timeout_s=self.DISCOVERY_TIMEOUT_S,
        )

    def send_goal(
        self, frame_id: str, x: float, y: float, yaw: float, done: Callable[[object], None],
        route_callback: Callable[[str, list[tuple[float, float]]], None] | None = None,
    ) -> object:
        return self._worker.send_goal(frame_id, x, y, yaw, done, route_callback)

    def cancel(self, goal: object) -> None:
        self._worker.cancel(goal)

    def close(self) -> None:
        self._worker.close()


class _RosNavigateToPoseWorker:
    """One queue, one node and one executor for the complete Action lifecycle."""

    GOAL_ACCEPT_TIMEOUT_S = 5.0

    def __init__(self, action_name: str, *, discovery_timeout_s: float) -> None:
        self._action_name = action_name
        self._discovery_timeout_s = discovery_timeout_s
        self._commands: queue.Queue[dict[str, object]] = queue.Queue()
        self._started = threading.Event()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_error: Exception | None = None
        self._closed = False
        self._lock = threading.Lock()
        self._active_ticket: dict[str, object] | None = None

    def send_goal(
        self, frame_id: str, x: float, y: float, yaw: float, done: Callable[[object], None],
        route_callback: Callable[[str, list[tuple[float, float]]], None] | None = None,
    ) -> object:
        self._ensure_started()
        ticket: dict[str, object] = {"event": threading.Event(), "done": done, "route_callback": route_callback}
        self._commands.put({"kind": "goal", "ticket": ticket, "frame_id": frame_id, "x": x, "y": y, "yaw": yaw})
        if not ticket["event"].wait(self._discovery_timeout_s + self.GOAL_ACCEPT_TIMEOUT_S):
            raise MapMarkerNavigationUnavailable("Nav2 未在限定时间内确认目标")
        error = ticket.get("error")
        if error:
            if isinstance(error, MapMarkerNavigationError):
                raise error
            raise MapMarkerNavigationUnavailable("Nav2 导航服务不可用") from error
        return ticket

    def cancel(self, ticket: object) -> None:
        if not isinstance(ticket, dict):
            raise MapMarkerNavigationUnavailable("导航目标无效")
        self._commands.put({"kind": "cancel", "ticket": ticket})

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread
        if thread is not None:
            self._commands.put({"kind": "close"})
            thread.join(timeout=2.0)

    def _ensure_started(self) -> None:
        with self._lock:
            if self._closed:
                raise MapMarkerNavigationUnavailable("导航工作器已关闭")
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True, name="map-marker-nav2-worker")
                self._thread.start()
        if not self._started.wait(self.GOAL_ACCEPT_TIMEOUT_S):
            raise MapMarkerNavigationUnavailable("Nav2 工作器启动超时")
        if self._start_error is not None:
            raise MapMarkerNavigationUnavailable("Nav2 导航服务不可用") from self._start_error

    def _run(self) -> None:
        node = executor = None
        try:
            import rclpy
            from geometry_msgs.msg import PoseStamped
            from nav2_msgs.action import NavigateToPose
            from nav_msgs.msg import Path
            from rclpy.action import ActionClient
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.node import Node
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
            if not rclpy.ok():
                rclpy.init(args=None)
            node = Node("ry_aletheia_map_marker_navigation")
            client = ActionClient(node, NavigateToPose, self._action_name)
            plan_qos = QoSProfile(
                depth=10,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.VOLATILE,
            )
            node.create_subscription(Path, "/plan", self._on_plan, plan_qos)
            executor = SingleThreadedExecutor()
            executor.add_node(node)
            self._started.set()
            while True:
                self._drain_commands(client, node, PoseStamped, NavigateToPose)
                if self._closed:
                    break
                executor.spin_once(timeout_sec=0.05)
        except Exception as exc:
            self._start_error = exc
            self._started.set()
            LOGGER.exception("Nav2 Action 工作器异常：action=%s", self._action_name)
        finally:
            if executor is not None:
                try:
                    executor.shutdown()
                except Exception:
                    LOGGER.exception("关闭 Nav2 executor 失败")
            if node is not None:
                node.destroy_node()
            self._stopped.set()

    def _drain_commands(self, client, node, pose_type, action_type) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            kind = command["kind"]
            if kind == "close":
                self._closed = True
                return
            ticket = command.get("ticket")
            if not isinstance(ticket, dict):
                continue
            if kind == "cancel":
                handle = ticket.get("handle")
                if handle is None:
                    continue
                try:
                    future = handle.cancel_goal_async()
                    future.add_done_callback(lambda _future: None)
                except Exception:
                    LOGGER.exception("Nav2 Goal cancel 调用失败")
                continue
            try:
                if not client.wait_for_server(timeout_sec=self._discovery_timeout_s):
                    LOGGER.warning("Nav2 Action 服务发现超时：action=%s timeout_s=%.1f", self._action_name, self._discovery_timeout_s)
                    ticket["error"] = MapMarkerNavigationUnavailable("Nav2 导航服务不可用")
                    ticket["event"].set()
                    continue
                goal = action_type.Goal()
                pose = pose_type()
                pose.header.frame_id = str(command["frame_id"])
                pose.header.stamp = node.get_clock().now().to_msg()
                pose.pose.position.x, pose.pose.position.y = float(command["x"]), float(command["y"])
                yaw = float(command["yaw"])
                pose.pose.orientation.z, pose.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
                goal.pose = pose
                future = client.send_goal_async(goal)
                future.add_done_callback(lambda completed, ticket=ticket: self._on_goal_response(ticket, completed))
            except Exception as exc:
                ticket["error"] = exc
                ticket["event"].set()

    def _on_goal_response(self, ticket: dict[str, object], future: object) -> None:
        try:
            handle = future.result()
            if handle is None or not handle.accepted:
                ticket["error"] = MapMarkerNavigationUnavailable("Nav2 未接受目标")
            else:
                ticket["handle"] = handle
                self._active_ticket = ticket
                result = handle.get_result_async()
                result.add_done_callback(lambda completed, ticket=ticket: self._on_result(ticket, completed))
        except Exception as exc:
            ticket["error"] = exc
        finally:
            ticket["event"].set()

    def _on_plan(self, message: object) -> None:
        """Forward only the current marker goal's valid global plan to the controller."""
        ticket = self._active_ticket
        callback = ticket.get("route_callback") if ticket is not None else None
        if not callable(callback):
            return
        try:
            header = getattr(message, "header")
            frame_id = getattr(header, "frame_id")
            if frame_id != MapMarkerNavigationController.ROUTE_FRAME_ID:
                return
            points: list[tuple[float, float]] = []
            for pose_stamped in getattr(message, "poses"):
                position = pose_stamped.pose.position
                x, y = float(position.x), float(position.y)
                if not math.isfinite(x) or not math.isfinite(y):
                    return
                points.append((x, y))
            if len(points) >= 2:
                callback(frame_id, points)
        except Exception:
            LOGGER.warning("忽略无效的 Nav2 规划路线", exc_info=True)

    def _on_result(self, ticket: dict[str, object], future: object) -> None:
        try:
            result = future.result()
            ticket["done"](bool(result and getattr(result, "status", 0) == 4))
        except Exception:
            ticket["done"](False)
        finally:
            if self._active_ticket is ticket:
                self._active_ticket = None
