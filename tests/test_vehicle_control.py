import io
import json
import tempfile
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import web_console
from autodrive_console.settings import SettingsStore
from autodrive_console.vehicle_control import (
    MiniappTwistProfile,
    MiniappTwistFactory,
    VehicleControlConfig,
    VehicleControlConflict,
    VehicleControlController,
    VehicleControlError,
)


class _Vector:
    x = y = z = 0.0

    def __init__(self):
        self.x = self.y = self.z = 0.0


class _StrictFloatVector:
    """模拟 ROS 2 generated Vector3 对 float64 字段的严格类型约束。"""

    def __init__(self):
        self._x = self._y = self._z = 0.0

    @staticmethod
    def _float_only(value):
        if not isinstance(value, float):
            raise AssertionError("ROS Vector3 field must be float")
        return value

    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, value):
        self._x = self._float_only(value)

    @property
    def y(self):
        return self._y

    @y.setter
    def y(self, value):
        self._y = self._float_only(value)

    @property
    def z(self):
        return self._z

    @z.setter
    def z(self, value):
        self._z = self._float_only(value)


class _Twist:
    def __init__(self):
        self.linear = _Vector()
        self.angular = _Vector()


class _StrictTwist:
    def __init__(self):
        self.linear = _StrictFloatVector()
        self.angular = _StrictFloatVector()


class _String:
    def __init__(self):
        self.data = ""


class _Publisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class _EmergencyService:
    class Request:
        pass


class _QueryFuture:
    def __init__(self):
        self._callbacks = []
        self._response = None

    def add_done_callback(self, callback):
        self._callbacks.append(callback)

    def result(self):
        return self._response

    def resolve(self, response):
        self._response = response
        for callback in self._callbacks:
            callback(self)


class _EmergencyClient:
    def __init__(self):
        self.calls = []
        self.future = _QueryFuture()

    def service_is_ready(self):
        return True

    def call_async(self, request):
        self.calls.append(request)
        return self.future


class _Clock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now


def _vehicle_control_handler(path: str, payload: dict):
    handler = object.__new__(web_console.ConsoleHandler)
    encoded = json.dumps(payload).encode("utf-8")
    handler.path = path
    handler.headers = {"Content-Length": str(len(encoded))}
    handler.rfile = io.BytesIO(encoded)
    handler._json = Mock()
    return handler


class VehicleControlTests(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self.control = VehicleControlController(
            clock=self.clock,
            config=VehicleControlConfig(input_timeout_s=0.3, heartbeat_timeout_s=1.0),
        )
        # 纯状态机测试：绝不初始化 rclpy 或向真实 topic 发送数据。
        self.control._runtime_state = "ready"
        self.control._String = _String
        self.control._Twist = _Twist
        self.control._source_command_publisher = _Publisher()
        self.control._velocity_publisher = _Publisher()
        self.control._command_publisher = _Publisher()

    def _confirm_emergency_normal(self):
        self.control._on_emergency_stop(SimpleNamespace(data=False))

    def test_twist_factory_preserves_miniapp_extended_protocol_fields(self):
        message = MiniappTwistFactory().build(_Twist, 0.2, -0.3)
        self.assertEqual(message.linear.x, 0.2)
        self.assertEqual(message.angular.z, -0.3)
        self.assertEqual(message.linear.y, 1400.0)
        self.assertEqual(message.linear.z, 1000.0)
        self.assertEqual(message.angular.x, -1.0)
        self.assertEqual(message.angular.y, -1.0)

    def test_twist_factory_converts_integer_chassis_parameters_to_ros_float_fields(self):
        """持久化配置恢复为整数时，STOP 也必须能写入严格的 ROS float64 字段。"""
        message = MiniappTwistFactory(
            MiniappTwistProfile(press=1400, movement_acc=1000, stop_acc=1200, place=-1, ulock=-1)
        ).build(_StrictTwist, 0.0, 0.0)

        self.assertEqual((message.linear.y, message.linear.z, message.angular.x, message.angular.y),
                         (1400.0, 1200.0, -1.0, -1.0))

    def test_nonzero_motion_requires_actual_miniapp_state_confirmation(self):
        self._confirm_emergency_normal()
        self.control._on_source_state(SimpleNamespace(data="navigation"))
        pending = self.control.begin_manual_session()
        session_id = pending["session"]["id"]
        self.assertEqual(self.control._source_command_publisher.messages[-1].data, "miniapp")
        self.assertFalse(pending["manual_ready"])
        with self.assertRaises(VehicleControlConflict):
            self.control.set_command(session_id, "forward")

        self.control._on_source_state(SimpleNamespace(data="miniapp"))
        self.assertTrue(self.control.status()["manual_ready"])
        self.control.set_command(session_id, "forward")
        self.control._on_publish_tick()
        velocity = self.control._velocity_publisher.messages[-1]
        self.assertEqual(velocity.linear.x, 0.2)
        self.assertEqual(velocity.angular.z, 0.0)
        self.assertEqual(velocity.linear.y, 1400.0)
        self.assertEqual(velocity.linear.z, 1000.0)

    def test_unknown_or_triggered_emergency_stop_blocks_motion_and_uses_stop_acc(self):
        """不能把未收到急停消息当作安全，触发后必须立即走统一 STOP。"""
        self.control._on_source_state(SimpleNamespace(data="miniapp"))
        self.assertFalse(self.control.status()["manual_ready"])
        with self.assertRaises(VehicleControlConflict):
            self.control.begin_manual_session()

        self.control._on_emergency_stop(SimpleNamespace(data=False))
        session_id = self.control.begin_manual_session()["session"]["id"]
        self.control.set_command(session_id, "forward")
        self.control._on_publish_tick()
        self.assertEqual(self.control._velocity_publisher.messages[-1].linear.z, 1000.0)

        self.control._on_emergency_stop(SimpleNamespace(data=True))
        stop = self.control._velocity_publisher.messages[-1]
        self.assertEqual((stop.linear.x, stop.angular.z, stop.linear.z), (0.0, 0.0, 1200.0))
        with self.assertRaises(VehicleControlConflict):
            self.control.set_command(session_id, "forward")

    def test_emergency_query_bootstraps_unknown_without_overwriting_topic_state(self):
        """底盘查询只补齐启动盲区，实时 Topic 已确认的状态始终优先。"""
        self.assertEqual(self.control.status()["emergency_stop"]["state"], "unknown")

        self.control._on_emergency_query_response(
            SimpleNamespace(is_emergency_stop=False),
            generation=0,
        )
        self.assertEqual(self.control.status()["emergency_stop"]["state"], "normal")

        self.control._on_emergency_stop(SimpleNamespace(data=True))
        self.control._on_emergency_query_response(
            SimpleNamespace(is_emergency_stop=False),
            generation=0,
        )
        self.assertEqual(self.control.status()["emergency_stop"]["state"], "triggered")

    def test_unknown_state_uses_one_nonblocking_service_query_until_response(self):
        """服务调用在 timer 中发起，未返回前不能堆积请求或阻塞状态机。"""
        client = _EmergencyClient()
        self.control._emergency_state_client = client
        self.control._GetEmergencyStop = _EmergencyService

        self.control._request_emergency_state_if_needed()
        self.control._request_emergency_state_if_needed()

        self.assertEqual(len(client.calls), 1)
        self.assertIsInstance(client.calls[0], _EmergencyService.Request)
        self.assertEqual(self.control.status()["emergency_stop"]["state"], "unknown")

        client.future.resolve(SimpleNamespace(is_emergency_stop=False))

        self.assertEqual(self.control.status()["emergency_stop"]["state"], "normal")
        self.control._request_emergency_state_if_needed()
        self.assertEqual(len(client.calls), 1)

    def test_release_emergency_stop_requires_false_feedback_after_fixed_command(self):
        """发布解除报文不是成功，唯一成功条件是急停 Topic 返回 false。"""
        self.control._on_emergency_stop(SimpleNamespace(data=True))

        pending = self.control.release_emergency_stop()

        self.assertEqual(pending["emergency_stop"]["release"], "waiting_confirmation")
        self.assertEqual(
            self.control._command_publisher.messages[-1].data,
            '{"speed":0.0,"angle":0.0,"acc":2000,"press":1400,"place":-1,"ulock":0}',
        )
        self.assertFalse(self.control._source_command_publisher.messages)
        self.assertNotEqual(pending["emergency_stop"]["release"], "confirmed")
        self.control._on_emergency_stop(SimpleNamespace(data=False))
        self.assertEqual(self.control.status()["emergency_stop"]["release"], "confirmed")

    def test_release_emergency_stop_times_out_without_false_feedback(self):
        """持续 true 不能因为时间流逝被误报为解除成功。"""
        self.control._on_emergency_stop(SimpleNamespace(data=True))
        self.control.release_emergency_stop()
        self.clock.now += self.control.config.emergency_release_timeout_s + 0.01

        status = self.control.status()

        self.assertEqual(status["emergency_stop"]["state"], "triggered")
        self.assertEqual(status["emergency_stop"]["release"], "failed")

    def test_chassis_parameters_select_motion_and_stop_acceleration(self):
        """新参数应由唯一 Twist 工厂同时覆盖运动和每条共享 STOP 路径。"""
        self._confirm_emergency_normal()
        self.control.update_chassis_parameters({"press": 1500, "movement_acc": 700, "stop_acc": 1800})
        self.control._on_source_state(SimpleNamespace(data="miniapp"))
        session_id = self.control.begin_manual_session()["session"]["id"]
        self.control.set_command(session_id, "forward")
        self.control._on_publish_tick()
        moving = self.control._velocity_publisher.messages[-1]
        self.assertEqual((moving.linear.y, moving.linear.z), (1500.0, 700.0))

        self.control.stop(session_id)
        stopped = self.control._velocity_publisher.messages[-1]
        self.assertEqual((stopped.linear.x, stopped.angular.z, stopped.linear.z), (0.0, 0.0, 1800.0))
        with self.assertRaisesRegex(VehicleControlError, "运动加速度"):
            self.control.update_chassis_parameters({"press": 1500, "movement_acc": 1001, "stop_acc": 1800})

    def test_external_source_takeover_uses_the_same_stop_acceleration(self):
        """外部切源不能绕过共享 STOP 构造路径而留下旧的运动 acceleration。"""
        self._confirm_emergency_normal()
        self.control.update_chassis_parameters({"press": 1500, "movement_acc": 700, "stop_acc": 1800})
        self.control._on_source_state(SimpleNamespace(data="miniapp"))
        session_id = self.control.begin_manual_session()["session"]["id"]
        self.control.set_command(session_id, "forward")
        self.control._on_publish_tick()

        self.control._on_source_state(SimpleNamespace(data="navigation"))

        stop = self.control._velocity_publisher.messages[-1]
        self.assertEqual((stop.linear.x, stop.angular.z, stop.linear.z), (0.0, 0.0, 1800.0))

    def test_chassis_parameters_action_persists_before_updating_controller(self):
        """网页请求必须先通过配置保存，保存失败不能让运行控制器进入新参数。"""
        handler = _vehicle_control_handler(
            "/api/vehicle-control/chassis-parameters",
            {"press": 1500, "movement_acc": 700, "stop_acc": 1800},
        )
        controller = Mock()
        controller.normalize_chassis_parameters.side_effect = VehicleControlController.normalize_chassis_parameters
        controller.update_chassis_parameters.return_value = {"runtime": "ready"}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(web_console, "SETTINGS", SettingsStore(Path(directory) / "console.json")), \
             patch.object(web_console, "VEHICLE_CONTROL", controller):
            handler._vehicle_control_action(handler.path)

        self.assertEqual(
            controller.update_chassis_parameters.call_args.args[0],
            {"press": 1500, "movement_acc": 700, "stop_acc": 1800},
        )
        self.assertEqual(handler._json.call_args.args[1], HTTPStatus.OK)

    def test_release_emergency_stop_action_returns_accepted_while_waiting(self):
        """HTTP 202 只表示等待真实 Bool 确认，不伪造解除成功。"""
        handler = _vehicle_control_handler("/api/vehicle-control/release-emergency-stop", {})
        controller = Mock()
        controller.release_emergency_stop.return_value = {
            "transition": None,
            "emergency_stop": {"state": "triggered", "release": "waiting_confirmation"},
        }
        with patch.object(web_console, "VEHICLE_CONTROL", controller):
            handler._vehicle_control_action(handler.path)

        controller.release_emergency_stop.assert_called_once_with()
        self.assertEqual(handler._json.call_args.args[1], HTTPStatus.ACCEPTED)

    def test_input_watchdog_latches_stop_without_browser_input(self):
        self._confirm_emergency_normal()
        self.control._on_source_state(SimpleNamespace(data="navigation"))
        session_id = self.control.begin_manual_session()["session"]["id"]
        self.control._on_source_state(SimpleNamespace(data="miniapp"))
        self.control.set_command(session_id, "forward")
        self.clock.now += 0.31
        self.control._on_publish_tick()
        message = self.control._velocity_publisher.messages[-1]
        self.assertEqual(message.linear.x, 0.0)
        self.assertEqual(message.angular.z, 0.0)
        self.assertEqual(message.linear.z, 1200.0)
        self.assertIn("输入超时", self.control.status()["transition_error"])
        published = len(self.control._velocity_publisher.messages)
        self.control._on_publish_tick()
        self.assertEqual(len(self.control._velocity_publisher.messages), published)

    def test_idle_manual_session_does_not_publish_velocity_frames(self):
        self._confirm_emergency_normal()
        self.control._on_source_state(SimpleNamespace(data="navigation"))
        session_id = self.control.begin_manual_session()["session"]["id"]
        self.control._on_source_state(SimpleNamespace(data="miniapp"))
        self.control._velocity_publisher.messages.clear()
        self.control._on_publish_tick()
        self.assertFalse(self.control._velocity_publisher.messages)
        self.control.set_command(session_id, "forward")
        self.control._on_publish_tick()
        self.assertEqual(self.control._velocity_publisher.messages[-1].linear.x, 0.2)
        self.control.stop(session_id)
        published = len(self.control._velocity_publisher.messages)
        self.control._on_publish_tick()
        self.assertEqual(len(self.control._velocity_publisher.messages), published)

    def test_existing_confirmed_miniapp_is_adopted_as_a_new_safe_session(self):
        self._confirm_emergency_normal()
        self.control._on_source_state(SimpleNamespace(data="miniapp"))
        state = self.control.begin_manual_session()
        session_id = state["session"]["id"]
        self.assertTrue(state["manual_ready"])
        self.assertEqual(state["session"]["state"], "active")
        self.assertFalse(self.control._source_command_publisher.messages)
        stop = self.control._velocity_publisher.messages[-1]
        self.assertEqual((stop.linear.x, stop.angular.z), (0.0, 0.0))
        self.control.set_command(session_id, "forward")
        self.control._on_publish_tick()
        self.assertEqual(self.control._velocity_publisher.messages[-1].linear.x, 0.2)

    def test_speed_is_car_side_bounded_and_updates_held_direction(self):
        self._confirm_emergency_normal()
        self.control._on_source_state(SimpleNamespace(data="navigation"))
        session_id = self.control.begin_manual_session()["session"]["id"]
        self.control._on_source_state(SimpleNamespace(data="miniapp"))
        self.control.set_command(session_id, "forward")
        state = self.control.set_speed(session_id, 0.8, 0.7)
        self.assertEqual(state["speed"], {"linear_mps": 0.8, "angular_radps": 0.7, "min": 0.1, "max": 1.0})
        self.control._on_publish_tick()
        self.assertEqual(self.control._velocity_publisher.messages[-1].linear.x, 0.8)
        with self.assertRaises(VehicleControlError):
            self.control.set_speed(session_id, 1.1, 0.5)

    def test_exit_stops_before_requesting_navigation_and_waits_for_state(self):
        self._confirm_emergency_normal()
        self.control._on_source_state(SimpleNamespace(data="navigation"))
        session_id = self.control.begin_manual_session()["session"]["id"]
        self.control._on_source_state(SimpleNamespace(data="miniapp"))
        self.control.set_command(session_id, "left")
        self.control.end_manual_session(session_id)
        stop = self.control._velocity_publisher.messages[-1]
        self.assertEqual((stop.linear.x, stop.angular.z), (0.0, 0.0))
        self.assertEqual(stop.linear.z, 1200.0)
        self.assertEqual(self.control._source_command_publisher.messages[-1].data, "navigation")
        self.assertEqual(self.control.status()["transition"], "navigation")
        self.control._on_source_state(SimpleNamespace(data="navigation"))
        self.assertEqual(self.control.status()["actual_source"], "navigation")
        self.assertFalse(self.control.status()["session"]["present"])

    def test_session_interlock_does_not_start_ros_runtime(self):
        self.assertFalse(self.control.has_control_session())
        self._confirm_emergency_normal()
        self.control._on_source_state(SimpleNamespace(data="navigation"))
        self.control.begin_manual_session()
        self.assertTrue(self.control.has_control_session())


if __name__ == "__main__":
    unittest.main()
