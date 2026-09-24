import unittest
import threading
from unittest.mock import patch

from autodrive_console.robot_gateway import RobotGateway
from autodrive_console.settings import RobotSettings
from autodrive_console.supervisor import SupervisorProcess


class SupervisorMonitoringTests(unittest.TestCase):
    def test_health_nodes_follow_dependency_stage_order_before_monitor_only_nodes(self):
        """仪表盘节点顺序必须与已保存编排阶段一致，并且防御性去重。"""
        settings = RobotSettings(
            monitor_nodes=[
                "MODULES:211-navigate_todoor_server",
                "MODULES:212-task_execute_server",
                "MODULES:209-lightning",
                "MODULES:214-fcrp_bringup",
                "DRIVERS:110-elevator_mqtt",
                "DRIVERS:110-elevator_mqtt",
            ],
            dependency_plan={
                "enabled": True,
                "steps": [
                    {"nodes": ["MODULES:209-lightning"], "wait_seconds": 0},
                    {"nodes": ["MODULES:214-fcrp_bringup"], "wait_seconds": 0},
                    {"nodes": ["MODULES:211-navigate_todoor_server", "MODULES:212-task_execute_server"], "wait_seconds": 0},
                ],
            },
        )
        gateway = RobotGateway(settings)

        self.assertEqual(
            [item["supervisor"] for item in gateway._health_nodes()],
            [
                "MODULES:209-lightning",
                "MODULES:214-fcrp_bringup",
                "MODULES:211-navigate_todoor_server",
                "MODULES:212-task_execute_server",
                "DRIVERS:110-elevator_mqtt",
            ],
        )

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

    def test_dependency_restart_reports_frozen_stage_and_node_states(self):
        updates = []
        settings = RobotSettings(dependency_plan={
            "enabled": True,
            "steps": [{"nodes": ["MODULES:209-lightning"], "wait_seconds": 0}],
        })
        gateway = RobotGateway(settings)

        class FakeClient:
            @staticmethod
            def discover():
                return [SupervisorProcess("MODULES:209-lightning", "RUNNING", "")]

            @staticmethod
            def restart(name):
                self.assertEqual(name, "MODULES:209-lightning")

        with patch("autodrive_console.robot_gateway.SupervisorClient", return_value=FakeClient()), patch.object(
            gateway, "_wait_stage_running", return_value=(True, "连续 5 次检查均为 RUNNING")
        ), patch.object(gateway, "_wait_all_dependencies_running", return_value=(True, "全部节点 RUNNING")):
            ok, _message = gateway.restart_configured_dependencies(progress_callback=updates.append)

        self.assertTrue(ok)
        self.assertEqual(updates[0]["stages"][0]["state"], "restarting")
        self.assertEqual(updates[0]["stages"][0]["nodes"], [
            {"name": "MODULES:209-lightning", "status": "RUNNING"},
        ])
        self.assertEqual(updates[-1]["stages"][0]["state"], "ready")

    def test_dependency_orchestration_controls_each_node_once_per_preparation(self):
        """完整编排结束后的总闸只能复查状态，不能再次发起重启。"""
        actions = []
        settings = RobotSettings(
            dependency_plan={
                "enabled": True,
                "steps": [
                    {"nodes": ["MODULES:209-lightning"], "wait_seconds": 0},
                    {"nodes": ["MODULES:214-fcrp_bringup"], "wait_seconds": 0},
                ],
            }
        )
        gateway = RobotGateway(settings)

        class FakeClient:
            @staticmethod
            def discover():
                return [
                    SupervisorProcess("MODULES:209-lightning", "RUNNING", ""),
                    SupervisorProcess("MODULES:214-fcrp_bringup", "RUNNING", ""),
                ]

            @staticmethod
            def restart(name):
                actions.append(("restart", name))

            @staticmethod
            def start(name):
                actions.append(("start", name))

        with patch("autodrive_console.robot_gateway.SupervisorClient", return_value=FakeClient()), patch.object(
            gateway, "_wait_stage_running", return_value=(True, "连续 5 次检查均为 RUNNING")
        ), patch.object(gateway, "_wait_all_dependencies_running", return_value=(True, "全部节点 RUNNING")):
            ok, _message = gateway.restart_configured_dependencies()

        self.assertTrue(ok)
        self.assertEqual(actions, [("restart", "MODULES:209-lightning"), ("restart", "MODULES:214-fcrp_bringup")])


if __name__ == "__main__":
    unittest.main()
