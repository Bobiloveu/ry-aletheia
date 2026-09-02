"""车端 miniapp 手动控制状态机。

这个模块刻意不经过 rosbridge，也不把 ROS publisher 放进 HTTP handler。浏览器
只写入一个短生命期的目标输入；所有 ROS2 生命周期、固定 20 Hz 发布、控制源
确认与失联保护均由本机后端维护。
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable


LOGGER = logging.getLogger("ry_aletheia.vehicle_control")


class VehicleControlError(RuntimeError):
    """手动控制请求不能被安全执行。"""


class VehicleControlUnavailable(VehicleControlError):
    """本机 ROS2 控制节点无法启动或已经异常。"""


class VehicleControlConflict(VehicleControlError):
    """当前真实控制状态不允许接管手动控制。"""


@dataclass(frozen=True)
class MiniappTwistProfile:
    """保留 miniapp Twist 的辅助协议字段。

    event_execution_layer 会将它们解释为 press、acc、place 与 ulock，不能按
    标准 Twist 的惯例清零。默认值来自本机已抓取的 miniapp STOP 帧；日后若
    车端协议变化，只应在这里或受控配置中调整，绝不能散落在 Web API 中。
    """

    press: float = 1400.0
    acc: float = 1200.0
    place: float = -1.0
    ulock: float = -1.0


class MiniappTwistFactory:
    """唯一的 /cmd_vel_miniapp 消息构造入口。"""

    def __init__(self, profile: MiniappTwistProfile | None = None) -> None:
        self.profile = profile or MiniappTwistProfile()

    def build(self, twist_type, linear_x: float = 0.0, angular_z: float = 0.0):
        message = twist_type()
        message.linear.x = float(linear_x)
        message.linear.y = self.profile.press
        message.linear.z = self.profile.acc
        message.angular.x = self.profile.place
        message.angular.y = self.profile.ulock
        message.angular.z = float(angular_z)
        return message


@dataclass(frozen=True)
class VehicleControlConfig:
    """固定在车端的安全边界；前端不可覆盖这些值。"""

    publish_hz: float = 20.0
    switch_timeout_s: float = 4.0
    input_timeout_s: float = 0.35
    heartbeat_timeout_s: float = 1.2
    min_speed: float = 0.10
    max_speed: float = 1.00
    # 与现有 keyboard_manual_control 的 base_speed/base_angle 一致的保守默认值。
    linear_speed_mps: float = 0.20
    angular_speed_radps: float = 0.30


class VehicleControlController:
    """本机 ROS2 手动控制器，独立于测试运行与实时观测模块。"""

    SOURCE_COMMAND_TOPIC = "/control_source_cmd"
    SOURCE_STATE_TOPIC = "/control_source_state"
    MINIAPP_VELOCITY_TOPIC = "/cmd_vel_miniapp"
    SOURCE_NAVIGATION = "navigation"
    SOURCE_MINIAPP = "miniapp"

    def __init__(
        self,
        *,
        active_run_guard: Callable[[], bool] | None = None,
        config: VehicleControlConfig | None = None,
        twist_profile: MiniappTwistProfile | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or VehicleControlConfig()
        self._twist_factory = MiniappTwistFactory(twist_profile)
        self._active_run_guard = active_run_guard or (lambda: False)
        self._clock = clock
        self._lock = threading.RLock()
        self._publish_lock = threading.Lock()
        self._state_event = threading.Event()

        self._runtime_state = "idle"
        self._runtime_error = ""
        self._closed = False
        self._node = None
        self._executor = None
        self._thread: threading.Thread | None = None
        self._source_command_publisher = None
        self._velocity_publisher = None
        self._String = None
        self._Twist = None

        self._actual_source = "unknown"
        self._last_source_update_at: float | None = None
        self._pending_source: str | None = None
        self._switch_deadline: float | None = None
        self._last_error = ""
        self._session: dict[str, Any] | None = None
        self._target_linear = 0.0
        self._target_angular = 0.0
        self._target_command: str | None = None
        self._linear_speed = self.config.linear_speed_mps
        self._angular_speed = self.config.angular_speed_radps
        # STOP 是一次性边沿事件。空闲会话不应持续占用 /cmd_vel_miniapp。
        self._stop_pending = False
        self._manual_stop_latched = False

    # ---- Public control contract -------------------------------------------------

    def status(self) -> dict[str, Any]:
        """返回车端已订阅到的实际状态；首次读取时延迟启动 ROS 节点。"""
        try:
            self._ensure_started()
        except VehicleControlUnavailable:
            pass
        with self._lock:
            self._advance_safety_locked(self._clock())
            return self._snapshot_locked()

    def has_control_session(self) -> bool:
        """供既有任务入口做并发互锁；该查询不会启动 ROS2 节点。"""
        with self._lock:
            return self._session is not None or self._pending_source == self.SOURCE_MINIAPP

    def begin_manual_session(self) -> dict[str, Any]:
        self._ensure_started()
        if self._active_run_guard():
            raise VehicleControlConflict("自动化测试正在执行，禁止抢占车辆控制权")
        now = self._clock()
        request_source: str | None = None
        adopted_existing_miniapp = False
        with self._lock:
            self._advance_safety_locked(now)
            if self._session is not None:
                raise VehicleControlConflict("已有 Aletheia 手动控制会话，请先停止并退出")
            if self._actual_source == self.SOURCE_MINIAPP:
                # 手动源可能先由现有 miniapp 或现场控制台切入。此时不能要求
                # 操作员先切回 navigation 再切回来；只要车端 state 已真实确认，
                # Aletheia 就接管为一个新的短生命期安全会话，并先保持 STOP。
                self._session = {
                    "id": uuid.uuid4().hex,
                    "state": "active",
                    "created_at": now,
                    "last_heartbeat_at": now,
                    "last_input_at": now,
                }
                self._target_linear = 0.0
                self._target_angular = 0.0
                self._manual_stop_latched = True
                self._pending_source = None
                self._switch_deadline = None
                self._last_error = ""
                adopted_existing_miniapp = True
                snapshot = self._snapshot_locked(include_session_id=True)
            elif self._actual_source != self.SOURCE_NAVIGATION:
                raise VehicleControlConflict(
                    f"当前实际控制源为 {self._actual_source}；等待 navigation 或 miniapp 的实际状态确认"
                )
            else:
                self._session = {
                    "id": uuid.uuid4().hex,
                    "state": "switching",
                    "created_at": now,
                    "last_heartbeat_at": now,
                    "last_input_at": now,
                }
                self._target_linear = 0.0
                self._target_angular = 0.0
                self._manual_stop_latched = True
                self._pending_source = self.SOURCE_MINIAPP
                self._switch_deadline = now + self.config.switch_timeout_s
                self._last_error = ""
                request_source = self.SOURCE_MINIAPP
                snapshot = self._snapshot_locked(include_session_id=True)
        if adopted_existing_miniapp:
            # 接管一个已经处于 miniapp 的车端时，先立即写入兼容 STOP 帧；绝不
            # 沿用任何外部控制端可能遗留的非零速度。
            self._publish_stop_now()
            LOGGER.info("已接管现有 miniapp 控制源，等待浏览器有效输入")
            return snapshot
        try:
            self._publish_source_command(request_source or self.SOURCE_MINIAPP)
        except Exception as exc:
            with self._lock:
                self._fail_locked(f"无法请求切换到 miniapp：{exc}")
            raise VehicleControlUnavailable(f"无法发布控制源切换命令：{exc}") from exc
        return snapshot

    def heartbeat(self, session_id: str) -> dict[str, Any]:
        self._ensure_started()
        with self._lock:
            self._require_session_locked(session_id, allow_inactive=False)
            self._session["last_heartbeat_at"] = self._clock()
            return self._snapshot_locked()

    def set_command(self, session_id: str, command: str) -> dict[str, Any]:
        self._ensure_started()
        if command not in {"forward", "backward", "left", "right"}:
            raise VehicleControlError("仅支持 forward、backward、left、right 或 stop 控制输入")
        now = self._clock()
        with self._lock:
            self._advance_safety_locked(now)
            session = self._require_session_locked(session_id, allow_inactive=False)
            if self._pending_source is not None or self._actual_source != self.SOURCE_MINIAPP:
                raise VehicleControlConflict("尚未收到 /control_source_state=miniapp 的实际确认，禁止发送运动指令")
            if session["state"] != "active":
                raise VehicleControlConflict("手动控制会话无效，禁止发送运动指令")
            self._target_command = command
            self._apply_target_command_locked()
            self._manual_stop_latched = False
            session["last_input_at"] = now
            session["last_heartbeat_at"] = now
            return self._snapshot_locked()

    def set_speed(self, session_id: str, linear_speed: object, angular_speed: object) -> dict[str, Any]:
        """更新当前会话的速度档位，车端始终执行范围校验。"""
        self._ensure_started()
        linear = self._validated_speed(linear_speed, "直线速度")
        angular = self._validated_speed(angular_speed, "转向速度")
        now = self._clock()
        with self._lock:
            self._advance_safety_locked(now)
            session = self._require_session_locked(session_id, allow_inactive=False)
            if self._pending_source is not None or self._actual_source != self.SOURCE_MINIAPP:
                raise VehicleControlConflict("尚未收到 /control_source_state=miniapp 的实际确认，禁止修改控制速度")
            if session["state"] != "active":
                raise VehicleControlConflict("手动控制会话无效，禁止修改控制速度")
            self._linear_speed = linear
            self._angular_speed = angular
            if self._target_command:
                self._apply_target_command_locked()
            session["last_heartbeat_at"] = now
            return self._snapshot_locked()

    def stop(self, session_id: str) -> dict[str, Any]:
        self._ensure_started()
        with self._lock:
            self._require_session_locked(session_id, allow_inactive=True)
            self._target_linear = 0.0
            self._target_angular = 0.0
            self._target_command = None
            self._manual_stop_latched = True
            if self._session:
                self._session["last_input_at"] = self._clock()
                self._session["last_heartbeat_at"] = self._clock()
            snapshot = self._snapshot_locked()
        self._publish_stop_now()
        return snapshot

    def end_manual_session(self, session_id: str) -> dict[str, Any]:
        """严格退出顺序：STOP -> 禁止非零 -> 请求 navigation -> 等真实反馈。"""
        self._ensure_started()
        now = self._clock()
        with self._lock:
            self._advance_safety_locked(now)
            session = self._require_session_locked(session_id, allow_inactive=True)
            self._target_linear = 0.0
            self._target_angular = 0.0
            self._target_command = None
            self._manual_stop_latched = True
            session["state"] = "exiting"
            session["last_heartbeat_at"] = now
            self._pending_source = self.SOURCE_NAVIGATION
            self._switch_deadline = now + self.config.switch_timeout_s
            self._last_error = ""
            snapshot = self._snapshot_locked()
        # 绝不把仍在运动的 miniapp 会话直接切换到 navigation。
        self._publish_stop_now()
        try:
            self._publish_source_command(self.SOURCE_NAVIGATION)
        except Exception as exc:
            with self._lock:
                self._fail_locked(f"无法请求切回 navigation：{exc}")
            raise VehicleControlUnavailable(f"无法发布 navigation 切换命令：{exc}") from exc
        return snapshot

    def close(self) -> None:
        """服务退出时的最后防线；不关闭共享的全局 rclpy runtime。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            running = self._runtime_state == "ready"
            should_release = self._actual_source == self.SOURCE_MINIAPP or self._session is not None
            self._target_linear = 0.0
            self._target_angular = 0.0
            self._manual_stop_latched = True
        if running and should_release:
            self._publish_stop_now()
            try:
                self._state_event.clear()
                self._publish_source_command(self.SOURCE_NAVIGATION)
                # executor 仍存活时短暂等待真实 state；超时也必须继续销毁以免卡住退出。
                self._state_event.wait(timeout=min(self.config.switch_timeout_s, 2.0))
            except Exception:
                LOGGER.exception("控制器关闭时无法切回 navigation")
        executor, thread, node = self._executor, self._thread, self._node
        if executor:
            try:
                executor.shutdown()
            except Exception:
                LOGGER.exception("关闭车辆控制 ROS executor 失败")
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if node:
            try:
                node.destroy_node()
            except Exception:
                LOGGER.exception("销毁车辆控制 ROS node 失败")

    # ---- ROS2 lifecycle ----------------------------------------------------------

    def _ensure_started(self) -> None:
        with self._lock:
            if self._closed:
                raise VehicleControlUnavailable("车辆控制器已关闭")
            if self._runtime_state == "ready":
                return
            if self._runtime_state == "starting":
                raise VehicleControlUnavailable("车辆控制 ROS2 节点正在启动，请稍后重试")
            self._runtime_state = "starting"
            self._runtime_error = ""
        try:
            import rclpy
            from geometry_msgs.msg import Twist
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
            from std_msgs.msg import String

            if not rclpy.ok():
                rclpy.init()
            node = rclpy.create_node("ry_aletheia_vehicle_control")
            volatile_reliable = QoSProfile(
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.VOLATILE,
            )
            state_reliable_transient = QoSProfile(
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            source_command_publisher = node.create_publisher(String, self.SOURCE_COMMAND_TOPIC, volatile_reliable)
            velocity_publisher = node.create_publisher(Twist, self.MINIAPP_VELOCITY_TOPIC, volatile_reliable)
            node.create_subscription(String, self.SOURCE_STATE_TOPIC, self._on_source_state, state_reliable_transient)
            node.create_timer(1.0 / self.config.publish_hz, self._on_publish_tick)
            executor = SingleThreadedExecutor()
            executor.add_node(node)
            thread = threading.Thread(target=executor.spin, daemon=True, name="vehicle-control")
            with self._lock:
                if self._closed:
                    executor.shutdown()
                    node.destroy_node()
                    raise VehicleControlUnavailable("车辆控制器已关闭")
                self._node = node
                self._executor = executor
                self._thread = thread
                self._source_command_publisher = source_command_publisher
                self._velocity_publisher = velocity_publisher
                self._String = String
                self._Twist = Twist
                self._runtime_state = "ready"
            thread.start()
            LOGGER.info("车辆控制 ROS2 节点已启动：state=%s cmd=%s vel=%s", self.SOURCE_STATE_TOPIC, self.SOURCE_COMMAND_TOPIC, self.MINIAPP_VELOCITY_TOPIC)
        except Exception as exc:
            with self._lock:
                self._runtime_state = "unavailable"
                self._runtime_error = str(exc)
                self._fail_locked(f"ROS2 控制模块启动失败：{exc}")
            raise VehicleControlUnavailable(f"无法启动本机 ROS2 车辆控制模块：{exc}") from exc

    def _on_source_state(self, message) -> None:
        source = str(getattr(message, "data", "")).strip()
        if not source:
            return
        publish_stop = False
        with self._lock:
            previous = self._actual_source
            self._actual_source = source
            self._last_source_update_at = self._clock()
            self._state_event.set()
            if self._pending_source == self.SOURCE_MINIAPP and source == self.SOURCE_MINIAPP and self._session:
                self._pending_source = None
                self._switch_deadline = None
                self._session["state"] = "active"
                self._session["last_heartbeat_at"] = self._clock()
                self._last_error = ""
                LOGGER.info("已由 /control_source_state 确认 miniapp 控制权")
            elif self._pending_source == self.SOURCE_NAVIGATION and source == self.SOURCE_NAVIGATION:
                self._pending_source = None
                self._switch_deadline = None
                self._session = None
                self._manual_stop_latched = False
                self._last_error = ""
                LOGGER.info("已由 /control_source_state 确认 navigation 接管")
            elif source != self.SOURCE_MINIAPP and previous == self.SOURCE_MINIAPP:
                # 外部切源也必须立即清空 Aletheia 的非零目标，不能等待下一帧。
                was_moving = bool(self._target_linear or self._target_angular)
                self._clear_motion_locked()
                self._manual_stop_latched = True
                if self._session and self._pending_source is None:
                    self._session["state"] = "invalid"
                    self._last_error = f"实际控制源已离开 miniapp：{source}"
                publish_stop = was_moving
        if publish_stop:
            self._publish_stop_now()

    def _on_publish_tick(self) -> None:
        try:
            with self._lock:
                self._advance_safety_locked(self._clock())
                ready_for_motion = self._manual_ready_locked()
                linear = self._target_linear if ready_for_motion else 0.0
                angular = self._target_angular if ready_for_motion else 0.0
                should_publish = bool(linear or angular)
                should_stop = self._stop_pending
            if should_publish:
                self._publish_twist(linear, angular)
            elif should_stop:
                self._publish_stop_now()
        except Exception as exc:
            with self._lock:
                self._fail_locked(f"ROS2 控制发布异常：{exc}")
            LOGGER.exception("车辆控制 20 Hz 发布循环异常")

    # ---- State, watchdog and publish helpers ------------------------------------

    def _advance_safety_locked(self, now: float) -> None:
        if self._pending_source and self._switch_deadline and now >= self._switch_deadline:
            target = self._pending_source
            self._pending_source = None
            self._switch_deadline = None
            self._clear_motion_locked()
            self._manual_stop_latched = True
            self._last_error = f"等待 /control_source_state={target} 超时；未确认控制源切换"
            if self._session:
                self._session["state"] = "invalid"
            LOGGER.warning("%s", self._last_error)
        if not self._session:
            return
        heartbeat_age = now - float(self._session["last_heartbeat_at"])
        if heartbeat_age > self.config.heartbeat_timeout_s and self._session["state"] not in {"exiting", "invalid"}:
            self._clear_motion_locked()
            self._manual_stop_latched = True
            self._session["state"] = "expired"
            self._last_error = "前端控制心跳超时，已锁定 STOP"
            LOGGER.warning("手动控制心跳超时，已停止车辆输出")
            return
        if (self._target_linear or self._target_angular) and now - float(self._session["last_input_at"]) > self.config.input_timeout_s:
            self._clear_motion_locked()
            self._manual_stop_latched = True
            self._last_error = "控制输入超时，已锁定 STOP"
            LOGGER.warning("手动控制输入超时，已停止车辆输出")

    def _manual_ready_locked(self) -> bool:
        return bool(
            self._session
            and self._session.get("state") == "active"
            and self._pending_source is None
            and self._actual_source == self.SOURCE_MINIAPP
        )

    def _apply_target_command_locked(self) -> None:
        direction = {
            "forward": (self._linear_speed, 0.0),
            "backward": (-self._linear_speed, 0.0),
            "left": (0.0, self._angular_speed),
            "right": (0.0, -self._angular_speed),
        }.get(self._target_command)
        self._target_linear, self._target_angular = direction or (0.0, 0.0)

    def _clear_motion_locked(self) -> None:
        if self._target_linear or self._target_angular:
            self._stop_pending = True
        self._target_linear = 0.0
        self._target_angular = 0.0
        self._target_command = None

    def _validated_speed(self, value: object, label: str) -> float:
        if isinstance(value, bool):
            raise VehicleControlError(f"{label}必须是数值")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise VehicleControlError(f"{label}必须是数值") from exc
        if not math.isfinite(numeric) or not self.config.min_speed <= numeric <= self.config.max_speed:
            raise VehicleControlError(
                f"{label}必须在 {self.config.min_speed:.1f}–{self.config.max_speed:.1f} 之间"
            )
        return numeric

    def _require_session_locked(self, session_id: str, *, allow_inactive: bool) -> dict[str, Any]:
        if not isinstance(session_id, str) or not session_id or not self._session or session_id != self._session.get("id"):
            raise VehicleControlConflict("手动控制会话无效或已结束")
        if not allow_inactive and self._session.get("state") not in {"switching", "active"}:
            raise VehicleControlConflict("手动控制会话已失效，禁止发送运动指令")
        return self._session

    def _fail_locked(self, message: str) -> None:
        self._clear_motion_locked()
        self._manual_stop_latched = True
        self._last_error = message
        if self._session:
            self._session["state"] = "invalid"

    def _publish_source_command(self, source: str) -> None:
        with self._publish_lock:
            publisher, string_type = self._source_command_publisher, self._String
            if publisher is None or string_type is None:
                raise VehicleControlUnavailable("ROS2 控制源 publisher 尚未就绪")
            message = string_type()
            message.data = source
            publisher.publish(message)

    def _publish_stop_now(self) -> None:
        # 非 miniapp 时底盘链路不会采用该 topic；仍不发布非零值。
        with self._lock:
            permitted = self._runtime_state == "ready" and self._velocity_publisher is not None
        if permitted:
            try:
                self._publish_twist(0.0, 0.0)
                with self._lock:
                    self._stop_pending = False
            except Exception:
                LOGGER.exception("无法立即发布 miniapp STOP")

    def _publish_twist(self, linear: float, angular: float) -> None:
        with self._publish_lock:
            publisher, twist_type = self._velocity_publisher, self._Twist
            if publisher is None or twist_type is None:
                raise VehicleControlUnavailable("ROS2 miniapp velocity publisher 尚未就绪")
            publisher.publish(self._twist_factory.build(twist_type, linear, angular))

    def _snapshot_locked(self, *, include_session_id: bool = False) -> dict[str, Any]:
        session = self._session
        session_data: dict[str, Any] = {
            "present": session is not None,
            "state": session.get("state") if session else "none",
        }
        if include_session_id and session:
            session_data["id"] = session["id"]
        actual = self._actual_source
        display_mode = "手动控制" if actual == self.SOURCE_MINIAPP else "自动驾驶" if actual == self.SOURCE_NAVIGATION else "未知"
        if self._pending_source:
            display_mode = "正在切换"
        return {
            "runtime": self._runtime_state,
            "runtime_error": self._runtime_error,
            "actual_source": actual,
            "display_mode": display_mode,
            "transition": self._pending_source,
            "transition_error": self._last_error,
            "manual_ready": self._manual_ready_locked(),
            # 已经由 /control_source_state 确认的 miniapp 可以安全建立一条新的
            # Aletheia watchdog 会话；不要求现场人员先来回切换控制源。
            "can_begin_manual": self._runtime_state == "ready" and actual in {self.SOURCE_NAVIGATION, self.SOURCE_MINIAPP} and session is None,
            "session": session_data,
            "safety": {
                "publish_hz": self.config.publish_hz,
                "input_timeout_ms": int(self.config.input_timeout_s * 1000),
                "heartbeat_timeout_ms": int(self.config.heartbeat_timeout_s * 1000),
            },
            "speed": {
                "linear_mps": self._linear_speed,
                "angular_radps": self._angular_speed,
                "min": self.config.min_speed,
                "max": self.config.max_speed,
            },
        }
