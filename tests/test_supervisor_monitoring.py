import unittest
import threading
from unittest.mock import patch

from autodrive_console.robot_gateway import RobotGateway
from autodrive_console.settings import RobotSettings
from autodrive_console.supervisor import SupervisorProcess


class SupervisorMonitoringTests(unittest.TestCase):
    def test_each_supervisor_query_publishes_current_snapshot(self):
        snapshots = []
        settings = RobotSettings(monitor_nodes=["MODULES:209-lightning"])
        gateway = RobotGateway(settings, snapshots.append)
        with patch("autodrive_console.robot_gateway.SupervisorClient.discover", return_value=[SupervisorProcess("MODULES:209-lightning", "STARTING", "pid 1")]):
            states, error = gateway._check_supervisor()
        self.assertIsNone(error)
        self.assertEqual(states[0]["status"], "STARTING")
        self.assertEqual(snapshots, [states])

    def test_waiting_stage_publishes_transition_before_running_stable(self):
        snapshots = []
        gateway = RobotGateway(RobotSettings(monitor_nodes=["MODULES:209-lightning"]), snapshots.append)
        results = iter([
            [SupervisorProcess("MODULES:209-lightning", "STARTING", "")],
            *[[SupervisorProcess("MODULES:209-lightning", "RUNNING", "")] for _ in range(5)],
        ])
        class FakeClient:
            @staticmethod
            def discover():
                return next(results)

        with patch("autodrive_console.robot_gateway.time.sleep"):
            ready, _ = gateway._wait_stage_running(FakeClient(), ["MODULES:209-lightning"])
        self.assertTrue(ready)
        self.assertEqual(snapshots[0][0]["status"], "STARTING")
        self.assertEqual(snapshots[-1][0]["status"], "RUNNING")
        self.assertEqual(len(snapshots), 6)

    def test_waiting_stage_honors_cancel_without_waiting_for_supervisor(self):
        cancelled = threading.Event()
        cancelled.set()
        gateway = RobotGateway(RobotSettings(monitor_nodes=["MODULES:209-lightning"]))

        class FakeClient:
            @staticmethod
            def discover():
                raise AssertionError("取消后的等待不应继续查询 Supervisor")

        ready, detail = gateway._wait_stage_running(FakeClient(), ["MODULES:209-lightning"], cancelled)
        self.assertFalse(ready)
        self.assertEqual(detail, "测试已取消")

    def test_minimal_dependency_restart_signals_only_the_real_control_interval(self):
        """The status display may announce restart only while Aletheia controls nodes."""
        activity = []
        settings = RobotSettings(nodes=[
            {"id": "localization", "label": "定位", "supervisor": "localizer", "required": True},
        ])
        gateway = RobotGateway(settings, dependency_restart_callback=activity.append)

        class FakeClient:
            @staticmethod
            def discover():
                return [SupervisorProcess("localizer", "RUNNING", "")]

            @staticmethod
            def restart(name):
                self.assertEqual(name, "localizer")

        with patch("autodrive_console.robot_gateway.SupervisorClient", return_value=FakeClient()), patch.object(
            gateway, "_wait_stage_running", return_value=(True, "连续 5 次检查均为 RUNNING")
        ):
            ok, _message = gateway.restart_configured_dependencies()

        self.assertTrue(ok)
        self.assertEqual(activity, [True, False])


if __name__ == "__main__":
    unittest.main()
