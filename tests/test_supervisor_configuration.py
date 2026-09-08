import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autodrive_console.models import TaskParameters, TestCase as RobotTestCase
from autodrive_console.robot_gateway import RobotGateway
from autodrive_console.settings import RobotSettings, SettingsStore


LEGACY_VEHICLE_NODES = [
    {"id": "chassis", "label": "底盘节点", "supervisor": "DRIVERS:102-chassis_node", "required": True},
    {"id": "elevator", "label": "梯控服务节点", "supervisor": "DRIVERS:111-elevator_server", "required": True},
    {"id": "localization", "label": "定位节点", "supervisor": "MODULES:209-lightning", "required": True},
    {"id": "navigation", "label": "Nav2 节点", "supervisor": "MODULES:211-navigate_todoor_server", "required": True},
    {"id": "task", "label": "任务服务节点", "supervisor": "MODULES:212-task_execute_server", "required": True},
    {"id": "bringup", "label": "导航节点", "supervisor": "MODULES:214-fcrp_bringup", "required": True},
]


class SupervisorConfigurationTests(unittest.TestCase):
    def test_first_run_has_no_vehicle_specific_required_nodes(self):
        """新车未配置时不得继承开发车的 Supervisor 节点名。"""
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "console.json")

            self.assertEqual(store.load().nodes, [])
            self.assertEqual(store.save({"nodes": []}).nodes, [])

    def test_exact_legacy_vehicle_template_is_removed_on_load(self):
        """升级时只清除旧版内置模板，避免不同车辆被判定缺失必需节点。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "console.json"
            path.write_text(
                json.dumps({"nodes": LEGACY_VEHICLE_NODES, "monitor_nodes": ["MODULES:209-lightning"]}),
                encoding="utf-8",
            )

            loaded = SettingsStore(path).load()

        self.assertEqual(loaded.nodes, [])
        self.assertEqual(loaded.monitor_nodes, [])

    def test_vehicle_specific_custom_nodes_are_preserved(self):
        """实施人员显式保存的本车配置不得被迁移逻辑误删。"""
        custom_nodes = [
            {"id": "localization", "label": "本车定位", "supervisor": "ROBOT_B:localizer", "required": True}
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "console.json"
            path.write_text(
                json.dumps({"nodes": custom_nodes, "monitor_nodes": ["ROBOT_B:localizer"]}),
                encoding="utf-8",
            )

            loaded = SettingsStore(path).load()

        self.assertEqual(loaded.nodes, custom_nodes)
        self.assertEqual(loaded.monitor_nodes, ["ROBOT_B:localizer"])

    def test_preflight_skips_supervisor_when_no_health_nodes_are_configured(self):
        """未启用依赖编排且未选择监控节点时，Supervisor 不应阻断任务预检。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_directory = root / "tasks"
            task_directory.mkdir()
            source = root / "source.json"
            source.write_text("{}", encoding="utf-8")
            case = RobotTestCase(
                id="园区_1_1_1_1.json",
                filename="园区_1_1_1_1.json",
                name="预检测试",
                parameters=TaskParameters("园区", 1, 1, 1, 1),
                source=str(source),
            )
            gateway = RobotGateway(RobotSettings(task_directory=str(task_directory), nodes=[]))

            with patch(
                "autodrive_console.robot_gateway.SupervisorClient.discover",
                side_effect=AssertionError("未配置监控节点时不应查询 Supervisor"),
            ):
                result = gateway.preflight(case)

        self.assertTrue(result.ok)
        self.assertEqual(result.node_states, [])
        self.assertEqual(result.task_sync, "已复制到本机任务目录")

    def test_dashboard_explains_that_unconfigured_supervisor_monitoring_is_optional(self):
        """空监控集不能在界面上被误报成即将执行的必需 Supervisor 预检。"""
        page = Path("autodrive_console/web/index.html").read_text(encoding="utf-8")
        script = Path("autodrive_console/web/app.js").read_text(encoding="utf-8")

        self.assertIn("正在读取可选的 Supervisor 监控配置", page)
        self.assertIn("function supervisorEmptyState()", script)
        self.assertIn("未配置 Supervisor 监控节点；常规测试不会因该项阻断", script)


if __name__ == "__main__":
    unittest.main()
