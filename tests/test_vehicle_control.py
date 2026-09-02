from types import SimpleNamespace
import unittest

from autodrive_console.vehicle_control import (
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


class _Twist:
    def __init__(self):
        self.linear = _Vector()
        self.angular = _Vector()


class _String:
    def __init__(self):
        self.data = ""


class _Publisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class _Clock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now


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

    def test_twist_factory_preserves_miniapp_extended_protocol_fields(self):
        message = MiniappTwistFactory().build(_Twist, 0.2, -0.3)
        self.assertEqual(message.linear.x, 0.2)
        self.assertEqual(message.angular.z, -0.3)
        self.assertEqual(message.linear.y, 1400.0)
        self.assertEqual(message.linear.z, 1200.0)
        self.assertEqual(message.angular.x, -1.0)
        self.assertEqual(message.angular.y, -1.0)

    def test_nonzero_motion_requires_actual_miniapp_state_confirmation(self):
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
        self.assertEqual(velocity.linear.z, 1200.0)

    def test_input_watchdog_latches_stop_without_browser_input(self):
        self.control._on_source_state(SimpleNamespace(data="navigation"))
        session_id = self.control.begin_manual_session()["session"]["id"]
        self.control._on_source_state(SimpleNamespace(data="miniapp"))
        self.control.set_command(session_id, "forward")
        self.clock.now += 0.31
        self.control._on_publish_tick()
        message = self.control._velocity_publisher.messages[-1]
        self.assertEqual(message.linear.x, 0.0)
        self.assertEqual(message.angular.z, 0.0)
        self.assertIn("输入超时", self.control.status()["transition_error"])
        published = len(self.control._velocity_publisher.messages)
        self.control._on_publish_tick()
        self.assertEqual(len(self.control._velocity_publisher.messages), published)

    def test_idle_manual_session_does_not_publish_velocity_frames(self):
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
        self.control._on_source_state(SimpleNamespace(data="navigation"))
        session_id = self.control.begin_manual_session()["session"]["id"]
        self.control._on_source_state(SimpleNamespace(data="miniapp"))
        self.control.set_command(session_id, "left")
        self.control.end_manual_session(session_id)
        stop = self.control._velocity_publisher.messages[-1]
        self.assertEqual((stop.linear.x, stop.angular.z), (0.0, 0.0))
        self.assertEqual(self.control._source_command_publisher.messages[-1].data, "navigation")
        self.assertEqual(self.control.status()["transition"], "navigation")
        self.control._on_source_state(SimpleNamespace(data="navigation"))
        self.assertEqual(self.control.status()["actual_source"], "navigation")
        self.assertFalse(self.control.status()["session"]["present"])

    def test_session_interlock_does_not_start_ros_runtime(self):
        self.assertFalse(self.control.has_control_session())
        self.control._on_source_state(SimpleNamespace(data="navigation"))
        self.control.begin_manual_session()
        self.assertTrue(self.control.has_control_session())


if __name__ == "__main__":
    unittest.main()
