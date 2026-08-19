import threading
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from autodrive_console.models import RunRecord, TaskParameters, TestCase
from autodrive_console.run_manager import RunManager
from autodrive_console.ros_executor import RosTaskExecutor
from autodrive_console.runtime_env import clear_legacy_fastdds_override


class _Preflight:
    ok = True
    message = "节点已就绪"

    @staticmethod
    def to_dict():
        return {"node_states": [], "message": "节点已就绪"}


class _Gateway:
    def __init__(self, *_args):
        pass

    @staticmethod
    def preflight(_case):
        return _Preflight()

    @staticmethod
    def confirm_dependencies_ready():
        return True, "全部 RUNNING", []


class _Maps:
    def __init__(self, *_args):
        pass

    @staticmethod
    def prepare(_source):
        return []

    @staticmethod
    def route_plan(_source, _assets):
        return []


class _BrokenTrajectory:
    def __init__(self, *_args):
        pass

    @staticmethod
    def start():
        raise RuntimeError("Could not import 'rosidl_typesupport_c' for package 'tf2_msgs'")


class _Executor:
    def __init__(self):
        self.executed = False

    @staticmethod
    def wait_until_available(**_kwargs):
        return True, "ROS2 服务已就绪"

    def execute(self, *_args, **_kwargs):
        self.executed = True
        return True, "任务服务执行成功", 1.0


class _Settings:
    @staticmethod
    def load():
        return object()


class _CancelledWaitingExecutor:
    def __init__(self):
        self.wait_called = False
        self.executed = False

    def wait_until_available(self, *, cancel_event=None, status_callback=None, **_kwargs):
        self.wait_called = True
        status_callback("正在等待 ROS2 服务就绪：/start_execute_tasks（0/300 秒）")
        cancel_event.set()
        return False, "操作员已终止：不再等待 ROS2 服务 /start_execute_tasks"

    def execute(self, *_args, **_kwargs):
        self.executed = True
        return True, "不应执行", 0.0


class TrajectoryFallbackTests(unittest.TestCase):
    def test_bound_scenario_is_applied_before_orchestration_and_restored_after_run(self):
        """启动脚本必须先切换，Supervisor 重启才会读取到该方案的参数。"""
        events = []

        class ScenarioStore:
            @staticmethod
            def apply_for_case(case_id):
                events.append(("scenario_apply", case_id))
                return {"bound": True, "profile_id": "hall", "profile_name": "电梯大厅", "message": "方案已应用"}

            @staticmethod
            def restore():
                events.append(("scenario_restore", ""))
                return {"restored": True, "message": "常规启动配置已恢复"}

        class Gateway:
            def __init__(self, *_args):
                pass

            @staticmethod
            def preflight(_case):
                events.append(("orchestration", ""))
                return _Preflight()

            @staticmethod
            def confirm_dependencies_ready():
                return True, "全部 RUNNING", []

        class Executor:
            @staticmethod
            def wait_until_available(**_kwargs):
                events.append(("service_wait", ""))
                return True, "ROS2 服务已就绪"

            @staticmethod
            def execute(*_args, **_kwargs):
                events.append(("task_execute", ""))
                return True, "任务服务执行成功", 0.1

        case = TestCase("case", "case.json", "测试用例", TaskParameters("社区", 1, 1, 1, 1), "unused.json")
        with tempfile.TemporaryDirectory() as directory:
            manager = RunManager(Path(directory), Executor(), _Settings(), ScenarioStore())
            manager._scenario_apply_settle_seconds = 0
            run = RunRecord("run", case, 1, 0, prepare_trajectory_maps=False)
            manager._runs[run.id] = run
            manager._cancel_events[run.id] = threading.Event()
            manager._resume_events[run.id] = threading.Event()
            manager._attempt_interrupt_events[run.id] = threading.Event()
            with patch("autodrive_console.run_manager.RobotGateway", Gateway), patch.object(manager, "_write_report"):
                manager._run(run)

        self.assertEqual([item[0] for item in events], ["scenario_apply", "orchestration", "service_wait", "task_execute", "scenario_restore"])
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.preflight["scenario"]["profile_id"], "hall")
        self.assertEqual(run.preflight["scenario"]["restore_state"], "restored")
        self.assertEqual([item["action"] for item in run.interventions], ["scenario_applied", "scenario_restored"])

    def test_clears_only_legacy_udp_override_inherited_from_0614(self):
        inherited = {"ROVER_QA_ROS_READY": "1", "FASTDDS_BUILTIN_TRANSPORTS": "UDPv4"}
        self.assertTrue(clear_legacy_fastdds_override(inherited))
        self.assertNotIn("FASTDDS_BUILTIN_TRANSPORTS", inherited)

        operator_config = {"FASTDDS_BUILTIN_TRANSPORTS": "UDPv4"}
        self.assertFalse(clear_legacy_fastdds_override(operator_config))
        self.assertEqual(operator_config["FASTDDS_BUILTIN_TRANSPORTS"], "UDPv4")

    def test_service_discovery_wait_can_be_cancelled_before_task_is_sent(self):
        """节点预检完成后等待 ROS 服务时，终止必须立即结束计划而非误报拦截。"""
        case = TestCase("case", "case.json", "测试用例", TaskParameters("社区", 1, 1, 1, 1), "unused.json")
        executor = _CancelledWaitingExecutor()
        with tempfile.TemporaryDirectory() as directory:
            manager = RunManager(Path(directory), executor, _Settings())
            run = RunRecord("run", case, 1, 0, prepare_trajectory_maps=True)
            manager._runs[run.id] = run
            manager._cancel_events[run.id] = threading.Event()
            manager._resume_events[run.id] = threading.Event()
            manager._attempt_interrupt_events[run.id] = threading.Event()
            with patch("autodrive_console.run_manager.RobotGateway", _Gateway), patch.object(manager, "_write_report"):
                manager._run(run)

        self.assertTrue(executor.wait_called)
        self.assertFalse(executor.executed)
        self.assertEqual(run.status, "cancelled")
        self.assertIn("操作员已终止", run.preflight["ros_service"]["message"])

    def test_ros_service_wait_honors_preexisting_cancel_without_ros_import(self):
        cancel = threading.Event()
        cancel.set()
        ok, message = RosTaskExecutor().wait_until_available(cancel_event=cancel)
        self.assertFalse(ok)
        self.assertIn("操作员已终止", message)

    def test_service_graph_detail_distinguishes_visible_service_from_domain_mismatch(self):
        executor = RosTaskExecutor()

        class VisibleNode:
            @staticmethod
            def get_service_names_and_types():
                return [("/start_execute_tasks", ["master_interfaces/srv/StartExecuteTasks"])]

        class MissingNode:
            @staticmethod
            def get_service_names_and_types():
                return [("/cancel_task", ["std_srvs/srv/Trigger"])]

        previous = os.environ.get("ROS_DOMAIN_ID")
        os.environ["ROS_DOMAIN_ID"] = "42"
        try:
            self.assertIn("已发现同名服务", executor._service_graph_detail(VisibleNode()))
            missing = executor._service_graph_detail(MissingNode())
            self.assertIn("未发现 /start_execute_tasks", missing)
            self.assertIn("域=42", missing)
        finally:
            if previous is None:
                os.environ.pop("ROS_DOMAIN_ID", None)
            else:
                os.environ["ROS_DOMAIN_ID"] = previous

    def test_trajectory_start_failure_does_not_block_task_service(self):
        """TF 轨迹依赖异常必须仅降级证据，不能误触发人工恢复。"""
        case = TestCase("case", "case.json", "测试用例", TaskParameters("社区", 1, 1, 1, 1), "unused.json")
        executor = _Executor()
        with tempfile.TemporaryDirectory() as directory:
            manager = RunManager(Path(directory), executor, _Settings())
            run = RunRecord("run", case, 1, 0, prepare_trajectory_maps=True)
            manager._runs[run.id] = run
            manager._cancel_events[run.id] = threading.Event()
            manager._resume_events[run.id] = threading.Event()
            manager._attempt_interrupt_events[run.id] = threading.Event()
            saved = []

            def save_trajectory(_run, _index, trajectory, _assets):
                saved.append(trajectory)
                return Path(directory) / "trace.json"

            with patch("autodrive_console.run_manager.RobotGateway", _Gateway), \
                 patch("autodrive_console.run_manager.MapAssetCache", _Maps), \
                 patch("autodrive_console.run_manager.TrajectorySession", _BrokenTrajectory), \
                 patch.object(manager, "_write_trajectory", save_trajectory), \
                 patch.object(manager, "_write_report"):
                manager._run(run)

        self.assertTrue(executor.executed)
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.attempts[0].status, "passed")
        self.assertIn("轨迹采集未启动", run.attempts[0].message)
        self.assertIn("轨迹证据不完整", saved[0]["integrity_warning"])


if __name__ == "__main__":
    unittest.main()
