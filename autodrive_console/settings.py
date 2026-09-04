from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


DEFAULT_NODES = [
    {"id": "chassis", "label": "底盘节点", "supervisor": "DRIVERS:102-chassis_node", "required": True},
    {"id": "elevator", "label": "梯控服务节点", "supervisor": "DRIVERS:111-elevator_server", "required": True},
    {"id": "localization", "label": "定位节点", "supervisor": "MODULES:209-lightning", "required": True},
    {"id": "navigation", "label": "Nav2 节点", "supervisor": "MODULES:211-navigate_todoor_server", "required": True},
    {"id": "task", "label": "任务服务节点", "supervisor": "MODULES:212-task_execute_server", "required": True},
    {"id": "bringup", "label": "导航节点", "supervisor": "MODULES:214-fcrp_bringup", "required": True},
]

SUPERVISOR_PROCESS_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}(?::[A-Za-z0-9][A-Za-z0-9_.-]{0,127})?\Z")
ROBOT_LOG_SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}\Z")
ROBOT_LOG_FORBIDDEN_ROOTS = tuple(Path(path) for path in ("/", "/etc", "/proc", "/sys", "/dev", "/run"))


DEFAULT_VEHICLE_MODELS = [
    {
        "id": "ry-standard",
        "name": "RY 标准小车",
        "length_m": 1.00,
        "width_m": 0.68,
    },
]


DEFAULT_VEHICLE_CONTROL_PARAMETERS = {
    "press": 1400,
    "movement_acc": 1000,
    "stop_acc": 1200,
}


DEFAULT_ROBOT_LOG_SOURCES = [
    {
        "id": "drivers",
        "name": "drivers",
        "path": "/opt/ry/Log/supervisor-logs/stdout/today/drivers",
    },
    {
        "id": "modules",
        "name": "modules",
        "path": "/opt/ry/Log/supervisor-logs/stdout/today/modules",
    },
    {
        "id": "lightning",
        "name": "lightning",
        "path": "/opt/ry/workspace/lightning_logs",
    },
]


@dataclass
class RobotSettings:
    task_directory: str = "/opt/ry/data/tasks/origin_tasks"
    # 仅为 Supervisor 查询提权；控制台和 ROS2 客户端必须以普通用户运行。
    supervisor_command: str = "sudo -n supervisorctl status"
    command_timeout_s: int = 8
    nodes: list[dict] = field(default_factory=lambda: list(DEFAULT_NODES))
    # 操作者在编排界面选择的“运行依赖就绪状态”节点；空值时兼容旧配置。
    monitor_nodes: list[str] = field(default_factory=list)
    case_aliases: dict[str, str] = field(default_factory=dict)
    ui_preferences: dict = field(default_factory=lambda: {"case_id": "", "count": 20, "interval_seconds": 3})
    dependency_plan: dict = field(default_factory=lambda: {"enabled": False, "steps": []})
    elevator_wait_timeout_s: int = 180
    # start_execute_tasks 在服务端会一直等到整条任务链结束才返回。电梯、多地图
    # 等用例通常超过五分钟，不能复用“服务就绪等待”的 300 秒阈值。
    task_execution_timeout_s: int = 900
    # 实时观测默认关闭。该功能仅在操作者主动进入页面并启动后运行专用遥测；
    # 不参与任务执行和轨迹取证。
    live_observation: dict = field(default_factory=lambda: {
        "enabled": False,
        "idle_stop_seconds": 45,
        # 车体轮廓仅用于浏览器二维投影，不影响 ROS2 定位、导航或底盘控制。
        "vehicle_models": [dict(item) for item in DEFAULT_VEHICLE_MODELS],
        "active_vehicle_model": "ry-standard",
    })
    # 仅供 Aletheia 已有的 miniapp 手动控制输出 Twist 辅助字段使用；
    # 与物理急停解除报文隔离，不能改变底盘原有安全边界。
    vehicle_control: dict = field(default_factory=lambda: dict(DEFAULT_VEHICLE_CONTROL_PARAMETERS))
    # 当前小车本机业务日志目录；只供 Desktop 日志下载页面消费，不能改动
    # Aletheia 自身 ToolLogStore 的受控诊断目录。
    robot_logs: dict = field(default_factory=lambda: {"sources": [dict(item) for item in DEFAULT_ROBOT_LOG_SOURCES]})


class SettingsStore:
    """部署在机器人本机的控制台配置。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> RobotSettings:
        if not self.path.exists():
            return RobotSettings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw.get("ui_preferences"), dict):
                # RViz was a historical desktop-only convenience. Remove its
                # persisted preference during migration; test trajectory
                # evidence remains mandatory and independent of this field.
                raw["ui_preferences"] = {
                    key: value
                    for key, value in raw["ui_preferences"].items()
                    if key != "open_rviz"
                }
            if "ssh_connect_timeout_s" in raw and "command_timeout_s" not in raw:
                raw["command_timeout_s"] = raw["ssh_connect_timeout_s"]
            if raw.get("supervisor_command") == "supervisorctl status":
                raw["supervisor_command"] = "sudo -n supervisorctl status"
            defaults = asdict(RobotSettings())
            defaults.update({key: value for key, value in raw.items() if key in defaults})
            # 旧版本的 live_observation 是一个较小的字典；深度合并以确保升级后
            # 自动获得车型库等新增字段，而不是被旧字典整体覆盖。
            stored_observation = raw.get("live_observation")
            if isinstance(stored_observation, dict):
                observation = dict(asdict(RobotSettings())["live_observation"])
                observation.update(stored_observation)
                # 旧版通用 ROS-Web 接入项没有等价的运行含义。升级时静默移除，
                # 实时页固定使用本机专用 UDP/WS 遥测，操作者无需再管理端口。
                for key in ("bridge_host", "bridge_port", "map_source", "embed_url"):
                    observation.pop(key, None)
                defaults["live_observation"] = observation
            stored_vehicle_control = raw.get("vehicle_control")
            if isinstance(stored_vehicle_control, dict):
                vehicle_control = dict(asdict(RobotSettings())["vehicle_control"])
                vehicle_control.update(stored_vehicle_control)
                try:
                    self._validate_vehicle_control(vehicle_control)
                except ValueError:
                    # 手工损坏或未来版本遗留的参数不能阻止控制台启动，更不能
                    # 带着未知 profile 进入手动控制器；安全回退到受控默认值。
                    vehicle_control = dict(DEFAULT_VEHICLE_CONTROL_PARAMETERS)
                defaults["vehicle_control"] = vehicle_control
            stored_robot_logs = raw.get("robot_logs")
            if isinstance(stored_robot_logs, dict):
                robot_logs = dict(asdict(RobotSettings())["robot_logs"])
                robot_logs.update(stored_robot_logs)
                try:
                    self._validate_robot_logs(robot_logs)
                except ValueError:
                    robot_logs = {"sources": [dict(item) for item in DEFAULT_ROBOT_LOG_SOURCES]}
                defaults["robot_logs"] = robot_logs
            return RobotSettings(**defaults)
        except (json.JSONDecodeError, TypeError, ValueError):
            return RobotSettings()

    def save(self, data: dict) -> RobotSettings:
        current = asdict(self.load())
        allowed = set(current)
        updates = {key: value for key, value in data.items() if key in allowed}
        observation_update = updates.pop("live_observation", None)
        robot_logs_update = updates.pop("robot_logs", None)
        current.update(updates)
        if isinstance(observation_update, dict):
            current["live_observation"].update(observation_update)
            for key in ("bridge_host", "bridge_port", "map_source", "embed_url"):
                current["live_observation"].pop(key, None)
        elif observation_update is not None:
            current["live_observation"] = observation_update
        if isinstance(robot_logs_update, dict):
            current["robot_logs"].update(robot_logs_update)
        elif robot_logs_update is not None:
            current["robot_logs"] = robot_logs_update
        settings = RobotSettings(**current)
        self._validate(settings)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return settings

    @staticmethod
    def _validate(settings: RobotSettings) -> None:
        if not settings.task_directory.startswith("/") or ".." in Path(settings.task_directory).parts or any(char.isspace() for char in settings.task_directory):
            raise ValueError("任务目录必须是安全的绝对路径")
        if not isinstance(settings.supervisor_command, str) or not settings.supervisor_command.strip():
            raise ValueError("Supervisor 状态命令不能为空")
        if not 1 <= int(settings.command_timeout_s) <= 120:
            raise ValueError("状态命令超时必须介于 1 和 120 秒")
        if not 60 <= int(settings.elevator_wait_timeout_s) <= 1800:
            raise ValueError("电梯等待超时必须介于 60 和 1800 秒")
        if not 60 <= int(settings.task_execution_timeout_s) <= 3600:
            raise ValueError("单轮任务服务超时必须介于 60 和 3600 秒")
        observation = settings.live_observation
        if not isinstance(observation, dict):
            raise ValueError("实时观测配置格式错误")
        if not isinstance(observation.get("enabled", False), bool):
            raise ValueError("实时观测开关格式错误")
        try:
            idle_stop_seconds = int(observation.get("idle_stop_seconds", 45))
        except (TypeError, ValueError) as exc:
            raise ValueError("实时观测自动停止时间无效") from exc
        if not 20 <= idle_stop_seconds <= 600:
            raise ValueError("实时观测自动停止时间必须介于 20 和 600 秒")
        models = observation.get("vehicle_models", [])
        active_model = observation.get("active_vehicle_model", "")
        if not isinstance(models, list) or not 1 <= len(models) <= 40:
            raise ValueError("车型库至少需要保留一个车型，且最多 40 个")
        model_ids = set()
        for model in models:
            if not isinstance(model, dict):
                raise ValueError("车型配置格式错误")
            model_id = model.get("id")
            name = model.get("name")
            if not isinstance(model_id, str) or not model_id or len(model_id) > 64 or not all(char.isalnum() or char in "-_" for char in model_id):
                raise ValueError("车型标识仅允许字母、数字、- 和 _")
            if model_id in model_ids:
                raise ValueError("车型标识不能重复")
            model_ids.add(model_id)
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 48:
                raise ValueError("车型名称不能为空且不能超过 48 个字符")
            try:
                length = float(model.get("length_m"))
                width = float(model.get("width_m"))
            except (TypeError, ValueError) as exc:
                raise ValueError("车型长宽必须为数字") from exc
            if not 0.2 <= length <= 5.0 or not 0.15 <= width <= 3.0:
                raise ValueError("车型长宽超出允许范围")
        if active_model not in model_ids:
            raise ValueError("请选择一个有效的当前车型")
        SettingsStore._validate_vehicle_control(settings.vehicle_control)
        SettingsStore._validate_robot_logs(settings.robot_logs)
        if not isinstance(settings.nodes, list) or not settings.nodes:
            raise ValueError("至少需要配置一个 Supervisor 节点")
        if not isinstance(settings.monitor_nodes, list) or not all(isinstance(name, str) and SUPERVISOR_PROCESS_NAME.fullmatch(name) for name in settings.monitor_nodes):
            raise ValueError("默认监控节点配置格式错误")
        if len(set(settings.monitor_nodes)) != len(settings.monitor_nodes):
            raise ValueError("默认监控节点不能重复")
        if not isinstance(settings.case_aliases, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in settings.case_aliases.items()):
            raise ValueError("用例别名配置格式错误")
        preferences = settings.ui_preferences
        if not isinstance(preferences, dict):
            raise ValueError("界面记忆配置格式错误")
        if not isinstance(preferences.get("case_id", ""), str) or not 1 <= int(preferences.get("count", 20)) <= 1000 or not 0 <= float(preferences.get("interval_seconds", 3)) <= 3600:
            raise ValueError("界面记忆参数无效")
        plan = settings.dependency_plan
        if not isinstance(plan, dict) or not isinstance(plan.get("enabled", False), bool) or not isinstance(plan.get("steps", []), list):
            raise ValueError("测试依赖编排配置格式错误")
        if plan["enabled"] and not plan["steps"]:
            raise ValueError("启用测试依赖编排时，至少需要配置一个启动阶段")
        known = set()
        for step in plan["steps"]:
            if not isinstance(step, dict) or not isinstance(step.get("nodes"), list) or not step["nodes"]:
                raise ValueError("每个依赖步骤必须至少选择一个 Supervisor 节点")
            if not all(isinstance(name, str) and SUPERVISOR_PROCESS_NAME.fullmatch(name) for name in step["nodes"]):
                raise ValueError("依赖步骤中的 Supervisor 节点格式错误")
            if len(set(step["nodes"])) != len(step["nodes"]):
                raise ValueError("同一依赖步骤不能重复选择节点")
            overlap = known.intersection(step["nodes"])
            if overlap:
                raise ValueError(f"节点只能出现在一个启动步骤中：{', '.join(sorted(overlap))}")
            known.update(step["nodes"])
            if not 0 <= int(step.get("wait_seconds", 0)) <= 300:
                raise ValueError("步骤等待时间必须介于 0 和 300 秒")
        for node in settings.nodes:
            if not node.get("label") or not isinstance(node.get("supervisor"), str) or not SUPERVISOR_PROCESS_NAME.fullmatch(node["supervisor"]):
                raise ValueError("每个节点都必须包含 label 和 supervisor")

    @staticmethod
    def _validate_vehicle_control(vehicle_control: object) -> None:
        expected_vehicle_control_keys = set(DEFAULT_VEHICLE_CONTROL_PARAMETERS)
        if not isinstance(vehicle_control, dict) or set(vehicle_control) != expected_vehicle_control_keys:
            raise ValueError("底盘控制参数配置格式错误")
        for key, label, minimum, maximum in (
            ("press", "底盘压力", 20, 2000),
            ("movement_acc", "运动加速度", 10, 1000),
            ("stop_acc", "停止加速度", 20, 2000),
        ):
            value = vehicle_control[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value:
                raise ValueError(f"{label}必须是有限整数")
            if not minimum <= value <= maximum:
                raise ValueError(f"{label}必须介于 {minimum} 和 {maximum}")

    @staticmethod
    def _validate_robot_logs(robot_logs: object) -> None:
        if not isinstance(robot_logs, dict) or set(robot_logs) != {"sources"}:
            raise ValueError("机器人日志配置格式错误")
        sources = robot_logs["sources"]
        if not isinstance(sources, list) or not 1 <= len(sources) <= 30:
            raise ValueError("机器人日志目录数量必须介于 1 和 30")
        source_ids = set()
        for source in sources:
            if not isinstance(source, dict) or set(source) != {"id", "name", "path"}:
                raise ValueError("机器人日志目录配置格式错误")
            source_id = source["id"]
            name = source["name"]
            path = source["path"]
            if not isinstance(source_id, str) or not ROBOT_LOG_SOURCE_ID.fullmatch(source_id):
                raise ValueError("机器人日志目录标识无效")
            if source_id in source_ids:
                raise ValueError("机器人日志目录标识不能重复")
            source_ids.add(source_id)
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 64:
                raise ValueError("机器人日志目录名称不能为空且不能超过 64 个字符")
            if not isinstance(path, str) or not path or len(path) > 512:
                raise ValueError("机器人日志目录路径无效")
            candidate = Path(path)
            if not candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError("机器人日志目录必须是安全的绝对路径")
            resolved = candidate.resolve(strict=False)
            if any(
                resolved == forbidden or (forbidden != Path("/") and forbidden in resolved.parents)
                for forbidden in ROBOT_LOG_FORBIDDEN_ROOTS
            ):
                raise ValueError("机器人日志目录不能是系统敏感目录")
            if ".ssh" in resolved.parts:
                raise ValueError("机器人日志目录不能位于 SSH 私钥目录")
