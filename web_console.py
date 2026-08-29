from __future__ import annotations

import json
import errno
import io
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from autodrive_console.case_store import CaseStore
from autodrive_console.case_workspace import CasePackageError, CaseWorkspace
from autodrive_console.observation import ObservationError, ObservationManager
from autodrive_console.robot_gateway import RobotGateway
from autodrive_console.ros_executor import RosTaskExecutor
from autodrive_console.runtime_env import clear_legacy_fastdds_override
from autodrive_console.run_manager import RunManager
from autodrive_console.scenario_setup import ScenarioSetupError, ScenarioSetupStore
from autodrive_console.settings import SettingsStore
from autodrive_console.supervisor import SupervisorClient
from autodrive_console.tool_logging import ToolLogStore
from autodrive_console.upgrade_manager import UpgradeError, UpgradeManager
from autodrive_console.video import ConsoleVideoRuntime, VideoConfigurationError, VideoManager, VideoRuntime


def ensure_ros_environment() -> None:
    """让双击/直接执行二进制也使用机器人原有 ROS2 环境。"""
    setup_script = os.environ.get("ROVER_QA_SETUP_SCRIPT", "/opt/ry/install/setup.bash")
    robot_prefix = str(Path(setup_script).parent)
    loaded_prefixes = os.environ.get("AMENT_PREFIX_PATH", "").split(os.pathsep)
    required_library_path = str(Path(robot_prefix) / "master_interfaces" / "lib")
    loaded_libraries = os.environ.get("LD_LIBRARY_PATH", "").split(os.pathsep)
    if os.environ.get("ROVER_QA_ROS_READY") == "1" or (robot_prefix in loaded_prefixes and required_library_path in loaded_libraries):
        return
    if not Path(setup_script).is_file():
        return
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).resolve()))
    command.extend(sys.argv[1:])
    environment = {**os.environ, "ROVER_QA_ROS_READY": "1"}
    os.execvpe("/bin/bash", ["bash", "-c", 'source "$1" && shift && exec "$@"', "--", setup_script, *command], environment)


clear_legacy_fastdds_override()
ensure_ros_environment()

ROOT = Path(getattr(__import__("sys"), "_MEIPASS", Path(__file__).resolve().parent))
# 运行数据必须落在可写的工程目录；打包时不能写入 _MEIPASS。
WORKSPACE = Path.cwd()
if not getattr(__import__("sys"), "frozen", False):
    WORKSPACE = Path(__file__).resolve().parent
TASK_DIR = WORKSPACE / "tasks"
CONFIG_DIR = WORKSPACE / "config"
MAX_CASE_UPLOAD_BYTES = 8 * 1024 * 1024
REPORT_FILENAME = re.compile(r"(?:run_[0-9a-f]{12}_[^/]+|报告_\d{8}_\d{6}_[^/]+_[0-9a-f]{12})\.html")
STORE = CaseStore(TASK_DIR)
CASE_WORKSPACE = CaseWorkspace(CONFIG_DIR, TASK_DIR)
SETTINGS = SettingsStore(CONFIG_DIR / "console.json")
SCENARIO_SETUP = ScenarioSetupStore(CONFIG_DIR)
RUNS = RunManager(WORKSPACE / "reports", RosTaskExecutor(), SETTINGS, SCENARIO_SETUP)
WEB_ROOT = ROOT / "autodrive_console" / "web"
VUE_WEB_ROOT = ROOT / "autodrive_console" / "web-vue"
UPGRADES = UpgradeManager(WORKSPACE, Path(sys.executable), getattr(sys, "frozen", False))
LOGS = ToolLogStore(WORKSPACE / "logs")
LOGGER = LOGS.configure()
_LIVE_PREPROCESSOR = ROOT / "aletheia_live_cloud" if getattr(sys, "frozen", False) else ROOT / "build" / "live_preprocessor" / "aletheia_live_cloud"
_VIDEO_INGEST = ROOT / "aletheia_video_ingest" if getattr(sys, "frozen", False) else ROOT / "build" / "live_preprocessor" / "aletheia_video_ingest"
OBSERVATION = ObservationManager(WORKSPACE / "maps_cache", WORKSPACE / "logs", _LIVE_PREPROCESSOR)
VIDEO = VideoManager(CONFIG_DIR / "video.json", ROOT / "config" / "video.json")
SCENARIO_RUNTIME_LOCK = SCENARIO_SETUP.runtime_lock


def restore_scenario_runtime() -> dict:
    """完成“脚本恢复 + 依赖重启验证”的闭环，不能只改文件就宣称常规已恢复。"""
    # ThreadingHTTPServer 可同时处理重复点击/多个网页标签。整个“回写脚本 →
    # 重启 → 确认 → 关闭事务”必须串行，否则两个请求可能交叉重启同一批节点。
    with SCENARIO_RUNTIME_LOCK:
        result = SCENARIO_SETUP.restore(retain_transaction=True)
        if not result.get("restored"):
            return result
        try:
            gateway = RobotGateway(SETTINGS.load())
            runtime_ok, runtime_message = gateway.restart_configured_dependencies()
        except Exception as exc:
            runtime_ok, runtime_message = False, f"恢复运行依赖时发生异常：{exc}"
        if not runtime_ok:
            SCENARIO_SETUP.note_runtime_recovery_failure(runtime_message)
            raise ScenarioSetupError(f"常规启动脚本已恢复，但运行依赖未能切回常规参数：{runtime_message}")
        return SCENARIO_SETUP.complete_runtime_restore(runtime_message)


def apply_scenario_runtime(profile_id: str, document: dict | None = None) -> dict:
    """应用场景并使相应运行依赖实际重新读取参数。"""
    with SCENARIO_RUNTIME_LOCK:
        if document is not None:
            SCENARIO_SETUP.save(document)
        result = SCENARIO_SETUP.apply(profile_id)
        try:
            gateway = RobotGateway(SETTINGS.load())
            runtime_ok, runtime_message = gateway.restart_configured_dependencies()
        except Exception as exc:
            runtime_ok, runtime_message = False, f"启动运行依赖时发生异常：{exc}"
        if not runtime_ok:
            SCENARIO_SETUP.note_runtime_activation_failure(runtime_message)
            raise ScenarioSetupError(f"场景启动脚本已写入，但运行依赖未能读取新参数：{runtime_message}。请恢复常规配置后重试")
        result["runtime_restart"] = runtime_message
        result["message"] = f"{result['message']}；{runtime_message}"
        return result

# 移动端使用独立入口（/m/），但继续调用完全相同的受控 API 与页面控制器。
# 不依据单一 UA 字段：优先采用浏览器 Client Hint，再兼容常见移动浏览器标识。
MOBILE_PAGE_NAMES = frozenset({
    "index.html", "case-library.html", "reports.html", "scenario-setup.html",
    "tool-logs.html", "runtime-settings.html", "live-observation.html",
})
MOBILE_VUE_PAGES = frozenset({"runtime-settings.html", "live-observation.html"})
_MOBILE_USER_AGENT = re.compile(r"android|iphone|ipod|iemobile|opera mini|mobile", re.IGNORECASE)


def is_mobile_console_client(headers) -> bool:
    """Return whether the initial console page should use the mobile shell."""
    client_hint = str(headers.get("Sec-CH-UA-Mobile", "")).strip().lower()
    if client_hint in {"?1", "1", "true"}:
        return True
    if client_hint in {"?0", "0", "false"}:
        return False
    return bool(_MOBILE_USER_AGENT.search(str(headers.get("User-Agent", ""))))


def mobile_page_name(path: str) -> str | None:
    """Map an explicit /m/ URL to a known console page, never to arbitrary files."""
    if path in {"/m", "/m/"}:
        return "index.html"
    if not path.startswith("/m/"):
        return None
    candidate = path.removeprefix("/m/")
    return candidate if candidate in MOBILE_PAGE_NAMES else None


def mobile_url_for(path: str) -> str | None:
    """Return the mobile equivalent of a first-class console route."""
    if path in {"/", "/vue/dashboard.html"}:
        return "/m/"
    candidate = path.lstrip("/")
    return f"/m/{candidate}" if candidate in MOBILE_PAGE_NAMES else None


def _log_unhandled_exception(exc_type, exc_value, traceback) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        return sys.__excepthook__(exc_type, exc_value, traceback)
    LOGGER.critical("未处理的控制台异常", exc_info=(exc_type, exc_value, traceback))
    sys.__excepthook__(exc_type, exc_value, traceback)


def _log_unhandled_thread_exception(args) -> None:
    LOGGER.critical("后台线程发生未处理异常：%s", args.thread.name if args.thread else "unknown", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


sys.excepthook = _log_unhandled_exception
threading.excepthook = _log_unhandled_thread_exception


class ConsoleHandler(BaseHTTPRequestHandler):
    server_version = "RY-Aletheia/1.0"

    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            # 浏览器刷新、切页、移动网络切换导致的连接关闭不属于工具错误。
            # 必须在这里吞掉；重新抛出会被 socketserver 打印为整段 Traceback，
            # 淹没真正需要处理的服务端异常。
            return
        except Exception:
            LOGGER.exception("HTTP 请求处理发生未处理异常：client=%s", self.client_address[0] if self.client_address else "unknown")
            raise

    def do_GET(self) -> None:
        request = urlparse(self.path)
        path = request.path
        explicit_mobile_page = mobile_page_name(path)
        query = parse_qs(request.query)
        preferred_view = query.get("view", [""])[0].lower()
        # ``?mobile=1`` is the supported visual-acceptance entry point.  It
        # must use the real /m/ shell (including its tokens and bottom nav),
        # rather than merely adding a class to desktop HTML.  ``view=desktop``
        # remains an explicit escape hatch for support diagnostics.
        forced_mobile = query.get("mobile", [""])[0] == "1"
        if explicit_mobile_page:
            self._mobile_page(explicit_mobile_page)
        elif preferred_view != "desktop" and (forced_mobile or is_mobile_console_client(self.headers)) and (target := mobile_url_for(path)):
            # 每个顶级页面都可直接从手机收藏夹打开；不是只有根路径才会分流。
            # API、报告下载等非页面路由不参与重定向，保持接口语义不变。
            self._redirect(target)
        elif path == "/runtime-settings.html":
            self._static_from(VUE_WEB_ROOT, "index.html")
        elif path == "/live-observation.html":
            self._static_from(VUE_WEB_ROOT, "live-observation.html")
        elif path == "/vue/dashboard.html":
            self._static_from(VUE_WEB_ROOT, "dashboard.html")
        elif path.startswith("/vue/"):
            self._static_from(VUE_WEB_ROOT, path.removeprefix("/vue/"))
        elif path == "/api/cases":
            cases, issues = STORE.list_cases()
            self._json({"cases": [self._case(case) for case in cases], "validationIssues": issues})
        elif path.startswith("/api/cases/") and path.endswith("/export"):
            self._export_case_package(unquote(path.removeprefix("/api/cases/").removesuffix("/export").rstrip("/")))
        elif path == "/api/settings":
            self._json(self._settings())
        elif path == "/api/scenario-setup":
            self._json(SCENARIO_SETUP.status())
        elif path == "/api/scenario-setup/file":
            try:
                selected = parse_qs(request.query).get("path", [""])[0]
                self._json(SCENARIO_SETUP.read_file(selected))
            except ScenarioSetupError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        elif path == "/api/scenario-setup/browse":
            try:
                query = parse_qs(request.query)
                self._json(SCENARIO_SETUP.browse(query.get("path", [""])[0], query.get("kind", [""])[0]))
            except ScenarioSetupError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        elif path == "/api/supervisor/processes":
            try:
                item = SETTINGS.load()
                self._json({"processes": [process.to_dict() for process in SupervisorClient(item.supervisor_command, item.command_timeout_s).discover()]})
            except RuntimeError as exc:
                LOGGER.error("读取 Supervisor 进程失败：%s", exc)
                self._json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
        elif path == "/api/runs/latest":
            run = RUNS.latest()
            self._json({"run": run.to_dict() if run else None})
        elif path == "/api/reports":
            self._json({"reports": self._reports()})
        elif path == "/api/system/upgrade":
            self._json(UPGRADES.status())
        elif path == "/api/observation/active-map":
            # 地图切换标记只有一个短 ID，供实时页快速发现 map_server 生命周期
            # 切换；绝不通过此接口传输或轮询 OccupancyGrid 栅格数据。
            self._json({"active_map_id": OBSERVATION.active_map_id()})
        elif path == "/api/observation":
            self._json(OBSERVATION.status(SETTINGS.load()))
        elif path == "/api/video/status":
            # 仅回传控制面状态；视频帧不会经过 Python 或此 HTTP 服务。
            self._json(VIDEO.status(self.headers.get("Host")))
        elif path.startswith("/api/observation/maps/") and path.endswith("/preview.svg"):
            asset_id = path.removeprefix("/api/observation/maps/").removesuffix("/preview.svg").strip("/")
            self._observation_map_preview(asset_id, "svg")
        elif path.startswith("/api/observation/maps/") and path.endswith("/preview.png"):
            asset_id = path.removeprefix("/api/observation/maps/").removesuffix("/preview.png").strip("/")
            self._observation_map_preview(asset_id, "png")
        elif path.startswith("/api/observation/maps/") and path.endswith("/layers"):
            asset_id = path.removeprefix("/api/observation/maps/").removesuffix("/layers").strip("/")
            self._observation_map_layers(asset_id)
        elif path == "/api/tool-logs":
            query = request.query
            errors_only = query == "scope=errors"
            if query and not errors_only and query != "scope=all":
                self._json({"error": "日志范围无效"}, HTTPStatus.BAD_REQUEST)
            else:
                self._json({"entries": LOGS.entries(errors_only), "scope": "errors" if errors_only else "all"})
        elif path == "/api/tool-logs/files":
            self._json({"files": LOGS.diagnostic_records()})
        elif path == "/api/tool-logs/download":
            self._download_tool_log(request.query == "scope=errors")
        elif path.startswith("/api/tool-logs/files/") and path.endswith("/download"):
            name = unquote(path.removeprefix("/api/tool-logs/files/").removesuffix("/download").strip("/"))
            self._download_diagnostic_file(LOGS.diagnostic_file(name))
        elif path.startswith("/api/reports/") and path.endswith("/download"):
            requested = unquote(path.removeprefix("/api/reports/").removesuffix("/download").rstrip("/"))
            self._download_report(requested)
        elif path.startswith("/api/report-files/"):
            self._report_file(unquote(path.removeprefix("/api/report-files/")))
        elif path.startswith("/api/runs/") and "/attempts/" in path and "/trajectory/" in path:
            self._trajectory_svg(path)
        elif path.startswith("/api/runs/"):
            run = RUNS.get(path.rsplit("/", 1)[-1])
            self._json({"run": run.to_dict() if run else None}, HTTPStatus.OK if run else HTTPStatus.NOT_FOUND)
        else:
            self._static_from(WEB_ROOT, "index.html" if path == "/" else path.lstrip("/"))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/system/shutdown":
            if RUNS.has_active_run():
                self._json({"error": "当前存在执行中、取消中或等待人工恢复的测试计划。请先终止并等待场景方案恢复后再退出控制台。"}, HTTPStatus.CONFLICT)
                return
            if SCENARIO_SETUP.has_unresolved_transaction():
                transaction = SCENARIO_SETUP.status().get("transaction", {})
                self._json({"error": f"当前存在未完成的场景恢复事务。{transaction.get('message', '请先恢复常规启动配置后再退出。')}"}, HTTPStatus.CONFLICT)
                return
            LOGGER.info("操作者请求安全退出控制台")
            self._json({"message": "控制台正在安全退出"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/api/system/upgrade":
            self._apply_upgrade()
            return
        if path == "/api/video/control":
            self._video_control()
            return
        if path.startswith("/api/observation/"):
            self._observation_action(path)
            return
        if path == "/api/cases/upload":
            self._upload_case()
            return
        if path == "/api/case-packages/import":
            self._import_case_package()
            return
        if path.startswith("/api/cases/") and path.endswith("/management"):
            self._update_case_management(unquote(path.removeprefix("/api/cases/").removesuffix("/management").rstrip("/")))
            return
        if path == "/api/settings":
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                settings = SETTINGS.save(data)
                self._json(self._settings(settings))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                LOGGER.warning("保存运行配置失败：%s", exc)
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/scenario-setup":
            self._scenario_setup_action()
            return
        if path.startswith("/api/runs/") and path.endswith("/cancel"):
            run = RUNS.cancel(path.split("/")[-2])
            if not run:
                self._json({"error": "该运行不存在或已结束，无法取消"}, HTTPStatus.CONFLICT)
            else:
                self._json({"run": run.to_dict()}, HTTPStatus.ACCEPTED)
            return
        if path.startswith("/api/runs/") and path.endswith("/resume"):
            run = RUNS.resume(path.split("/")[-2])
            if not run:
                self._json({"error": "该运行当前不处于等待人工恢复状态"}, HTTPStatus.CONFLICT)
            else:
                self._json({"run": run.to_dict()}, HTTPStatus.ACCEPTED)
            return
        if path.startswith("/api/runs/") and path.endswith("/stall-action"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                run = RUNS.handle_stall_action(path.split("/")[-2], str(data.get("action", "")))
                if not run:
                    self._json({"error": "当前没有可处置的运行中停滞提醒"}, HTTPStatus.CONFLICT)
                else:
                    self._json({"run": run.to_dict()}, HTTPStatus.ACCEPTED)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path != "/api/runs":
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            if getattr(self.server, "upgrade_pending", False):
                raise RuntimeError("控制台正在应用升级，暂时不能创建测试计划")
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            case = STORE.get_case(str(data["caseId"]))
            if not case:
                raise ValueError("未找到指定测试用例，请刷新列表后重试")
            run = RUNS.start(case, int(data.get("count", 1)), float(data.get("intervalSeconds", 3)), True)
            self._json({"run": run.to_dict()}, HTTPStatus.ACCEPTED)
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            LOGGER.warning("创建测试计划失败：%s", exc)
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _video_control(self) -> None:
        """Persist the optional video switch and reconcile console-owned children.

        This endpoint never accepts a command, path, topic, or executable from
        the browser.  It only accepts the global boolean switch, or a
        validated configured stream name plus its boolean switch.
        """

        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            if not isinstance(data, dict) or not isinstance(data.get("enabled"), bool):
                raise ValueError("enabled 必须是布尔值")
            runtime = getattr(self.server, "video_runtime", None)
            if not isinstance(runtime, ConsoleVideoRuntime):
                raise RuntimeError("视频控制器尚未初始化")
            stream = data.get("stream")
            if stream is None:
                runtime.set_enabled(data["enabled"])
                state = "启用" if data["enabled"] else "关闭"
                LOGGER.info("操作者已%s低延迟相机流", state)
            elif isinstance(stream, str):
                runtime.set_stream_enabled(stream, data["enabled"])
                state = "启用" if data["enabled"] else "关闭"
                LOGGER.info("操作者已%s低延迟相机流：%s", state, stream)
            else:
                raise ValueError("stream 必须是字符串")
            self._json(VIDEO.status(self.headers.get("Host")), HTTPStatus.ACCEPTED)
        except (TypeError, ValueError, json.JSONDecodeError, VideoConfigurationError, RuntimeError) as exc:
            LOGGER.warning("切换低延迟相机流失败：%s", exc)
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _apply_upgrade(self) -> None:
        if RUNS.has_active_run():
            self._json({"error": "当前存在执行中、取消中或等待人工恢复的测试计划。请先安全结束测试后再升级。"}, HTTPStatus.CONFLICT)
            return
        if SCENARIO_SETUP.has_unresolved_transaction():
            transaction = SCENARIO_SETUP.status().get("transaction", {})
            self._json({"error": f"当前存在未完成的场景恢复事务。{transaction.get('message', '请先恢复常规启动配置后再升级。')}"}, HTTPStatus.CONFLICT)
            return
        if getattr(self.server, "upgrade_pending", False):
            self._json({"error": "升级已在处理，请等待控制台重启。"}, HTTPStatus.CONFLICT)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        try:
            result = UPGRADES.apply(self.rfile, content_length, self.headers.get("X-Upgrade-Filename", ""))
        except UpgradeError as exc:
            LOGGER.warning("离线升级校验失败：%s", exc)
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.server.upgrade_pending = True
        self.server.restart_command = [str(UPGRADES.executable)]
        # 升级后的新进程无法安全认领旧进程创建的 Bridge；先由原进程回收。
        OBSERVATION.stop()
        LOGGER.info("离线升级校验通过，准备重启至版本 %s", result["version"])
        self._json(result, HTTPStatus.ACCEPTED)
        threading.Timer(0.4, self.server.shutdown).start()

    def _scenario_setup_action(self) -> None:
        """场景前置配置的受控操作入口；不接受任意脚本或 Shell 命令。"""
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            action = str(data.get("action", ""))
            if action == "save":
                payload = SCENARIO_SETUP.save(data.get("document"))
                result = {"message": "场景前置方案已保存", "document": payload}
            elif action == "preview":
                result = SCENARIO_SETUP.preview_application(data.get("document"), str(data.get("profile_id", "")))
                result["message"] = f"已生成方案“{result['profile_name']}”的启动脚本模拟预览（未写入机器人）"
            elif action == "apply":
                if RUNS.has_active_run():
                    raise ScenarioSetupError("存在执行中测试计划，不能修改启动配置")
                # “应用”必须以页面当前经过校验的内容为准。过去只应用磁盘中旧
                # 方案，用户修改字段后直接点应用会得到与页面不一致的实际参数。
                # 应用也必须让相关运行依赖重新读取脚本；否则页面会显示“已
                # 应用”，车辆却仍运行上一套参数。
                result = apply_scenario_runtime(str(data.get("profile_id", "")), data.get("document"))
            elif action == "restore":
                if RUNS.has_active_run():
                    raise ScenarioSetupError("存在执行中测试计划，不能恢复启动配置")
                result = restore_scenario_runtime()
            elif action == "bind-case":
                case_id = str(data.get("case_id", ""))
                if not STORE.get_case(case_id):
                    raise ScenarioSetupError("未找到要绑定的测试用例")
                result = SCENARIO_SETUP.bind_case(case_id, str(data.get("profile_id", "")))
            else:
                raise ScenarioSetupError("未知的场景前置配置操作")
            LOGGER.info("场景前置配置操作完成：%s", action)
            self._json({**result, "status": SCENARIO_SETUP.status()})
        except (TypeError, ValueError, json.JSONDecodeError, ScenarioSetupError) as exc:
            LOGGER.warning("场景前置配置操作被拒绝：%s", exc)
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _observation_action(self, path: str) -> None:
        settings = SETTINGS.load()
        try:
            if path == "/api/observation/start":
                payload = OBSERVATION.start(settings)
            elif path == "/api/observation/heartbeat":
                payload = OBSERVATION.heartbeat(settings)
            elif path == "/api/observation/stop":
                OBSERVATION.stop()
                payload = OBSERVATION.status(settings)
            elif path == "/api/observation/live-layers":
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                self._json(OBSERVATION.live_layers(data), HTTPStatus.OK)
                return
            elif path == "/api/observation/client-log":
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                level = str(data.get("level", "INFO")).upper()
                message = " ".join(str(data.get("message", "")).split())[:800]
                if level not in {"INFO", "WARNING", "ERROR"} or not message:
                    raise ValueError("观测日志内容无效")
                OBSERVATION.record_client_event(level, message)
                self._json({"recorded": True}, HTTPStatus.ACCEPTED)
                return
            elif path == "/api/observation/client-metrics":
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if not isinstance(data, dict):
                    raise ValueError("观测性能指标格式无效")
                OBSERVATION.record_client_metrics(data)
                self._json({"recorded": True}, HTTPStatus.ACCEPTED)
                return
            else:
                self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
            self._json(payload, HTTPStatus.ACCEPTED)
        except (ObservationError, TypeError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.warning("实时观测操作被拒绝：%s", exc)
            self._json({"error": str(exc)}, HTTPStatus.CONFLICT)

    def _observation_map_preview(self, asset_id: str, kind: str) -> None:
        try:
            body = OBSERVATION.preview_png(asset_id) if kind == "png" else OBSERVATION.preview(asset_id)
        except ObservationError as exc:
            self.send_error(HTTPStatus.NOT_FOUND, str(exc))
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/png" if kind == "png" else "image/svg+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # 预览文件以缓存地图 ID 为键，地图切换才会产生新 ID；允许浏览器复用，
        # 避免每次打开观测页都重复进行 PGM→PNG 转换。
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _observation_map_layers(self, asset_id: str) -> None:
        try:
            self._json(OBSERVATION.layers(asset_id))
        except ObservationError as exc:
            self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)

    def _upload_case(self) -> None:
        """接收资产库拖入的单个 JSON；只允许新文件，绝不覆盖已有任务。"""
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        filename = unquote(self.headers.get("X-Case-Filename", "")).strip()
        if not 1 <= content_length <= MAX_CASE_UPLOAD_BYTES:
            self._json({"error": "用例文件大小无效或超过 8 MiB 限制"}, HTTPStatus.BAD_REQUEST)
            return
        if not filename or Path(filename).name != filename or len(filename) > 180:
            self._json({"error": "用例文件名不安全"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            contents = self.rfile.read(content_length).decode("utf-8")
            case = STORE.parse_case(filename, contents, str(TASK_DIR / filename))
        except UnicodeDecodeError:
            LOGGER.warning("导入用例失败：文件不是 UTF-8：%s", filename)
            self._json({"error": "用例文件必须使用 UTF-8 编码"}, HTTPStatus.BAD_REQUEST)
            return
        except ValueError as exc:
            LOGGER.warning("导入用例校验失败：%s", exc)
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        TASK_DIR.mkdir(parents=True, exist_ok=True)
        target = TASK_DIR / filename
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(contents)
        except FileExistsError:
            self._json({"error": "tasks/ 中已存在同名用例，已拒绝覆盖"}, HTTPStatus.CONFLICT)
            return
        except OSError as exc:
            LOGGER.error("保存用例文件失败：%s", exc)
            self._json({"error": f"保存用例文件失败：{exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        # 为普通 JSON 导入创建最小可追溯元数据；任务 JSON 仍是唯一执行来源。
        CASE_WORKSPACE.describe(case)
        self._json({"message": "用例已导入测试用例管理工作区", "case": self._case(case)}, HTTPStatus.CREATED)

    def _import_case_package(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if not 1 <= content_length <= MAX_CASE_UPLOAD_BYTES:
            self._json({"error": "用例包大小无效或超过 8 MiB 限制"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            result = CASE_WORKSPACE.import_package(self.rfile.read(content_length))
            LOGGER.info("导入测试用例包：%s，结果=%s", result["case"].id, result["status"])
            status = HTTPStatus.CREATED if result["status"] == "imported" else HTTPStatus.OK
            self._json({"message": result["message"], "status": result["status"], "case": self._case(result["case"])}, status)
        except (CasePackageError, OSError) as exc:
            LOGGER.warning("导入测试用例包失败：%s", exc)
            self._json({"error": str(exc)}, HTTPStatus.CONFLICT)

    def _export_case_package(self, case_id: str) -> None:
        case = STORE.get_case(case_id)
        if not case:
            self._json({"error": "未找到指定测试用例"}, HTTPStatus.NOT_FOUND)
            return
        try:
            filename, body = CASE_WORKSPACE.export_package(case, SETTINGS.load().case_aliases.get(case.id, ""))
        except (CasePackageError, OSError) as exc:
            LOGGER.warning("导出测试用例包失败：%s", exc)
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f"attachment; filename=ry-aletheia-case.rycase.zip; filename*=UTF-8''{quote(filename)}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _update_case_management(self, case_id: str) -> None:
        try:
            case = STORE.get_case(case_id)
            if not case:
                raise CasePackageError("未找到指定测试用例")
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(content_length))
            metadata = CASE_WORKSPACE.update(case, payload)
            self._json({"message": "用例管理信息已保存", "case": self._case(case), "management": metadata})
        except (CasePackageError, TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
            LOGGER.warning("保存用例管理信息失败：%s", exc)
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if not path.startswith("/api/reports/"):
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            self._delete_report(unquote(path.removeprefix("/api/reports/")))
            self._json({"message": "报告及其 CSV、轨迹证据文件已删除"})
        except ValueError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except OSError as exc:
            self._json({"error": f"删除报告失败：{exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _case(self, case):
        alias = SETTINGS.load().case_aliases.get(case.id, "")
        try:
            management = CASE_WORKSPACE.describe(case)
        except OSError as exc:
            LOGGER.warning("读取用例管理信息失败：%s", exc)
            management = {"lifecycle": "draft", "tags": [], "summary": "", "version": "0.1.0", "fingerprint": {}}
        return {"id": case.id, "filename": case.filename, "name": case.name, "alias": alias, "parameters": case.parameters.__dict__, "management": management}

    def _settings(self, settings=None):
        item = settings or SETTINGS.load()
        monitor_nodes = item.monitor_nodes or [str(node["supervisor"]) for node in item.nodes if node.get("required", True)]
        return {"task_directory": item.task_directory, "command_timeout_s": item.command_timeout_s, "elevator_wait_timeout_s": item.elevator_wait_timeout_s, "task_execution_timeout_s": item.task_execution_timeout_s, "case_aliases": item.case_aliases, "ui_preferences": item.ui_preferences, "dependency_plan": item.dependency_plan, "monitor_nodes": monitor_nodes, "live_observation": item.live_observation}

    @staticmethod
    def _reports() -> list[dict]:
        report_dir = WORKSPACE / "reports"
        if not report_dir.is_dir():
            return []
        records = []
        report_files = (target for target in report_dir.glob("*.html") if REPORT_FILENAME.fullmatch(target.name))
        for target in sorted(report_files, key=lambda item: item.stat().st_mtime, reverse=True):
            stat = target.stat()
            csv_target = target.with_suffix(".csv")
            records.append({
                "filename": target.name,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
                "csv_filename": csv_target.name if csv_target.is_file() else None,
            })
        return records[:200]

    def _report_file(self, requested: str) -> None:
        report_root = (WORKSPACE / "reports").resolve()
        target = (report_root / requested).resolve()
        if report_root not in target.parents or not target.is_file() or target.suffix not in {".html", ".csv", ".svg", ".json"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif target.suffix == ".svg":
            content_type = "image/svg+xml; charset=utf-8"
        elif target.suffix == ".csv":
            content_type = "text/csv; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _archive_report_target(requested: str) -> Path:
        """仅允许操作 reports/ 根目录下由本工具生成的单份 HTML 报告。"""
        report_root = (WORKSPACE / "reports").resolve()
        if not REPORT_FILENAME.fullmatch(requested):
            raise ValueError("报告文件名不合法")
        target = (report_root / requested).resolve()
        if target.parent != report_root or not target.is_file():
            raise ValueError("报告不存在")
        return target

    def _download_report(self, requested: str) -> None:
        try:
            target = self._archive_report_target(requested)
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Disposition", f"attachment; filename=ry-aletheia-report.html; filename*=UTF-8''{quote(target.name)}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _download_tool_log(self, errors_only: bool) -> None:
        if not errors_only:
            # 现场诊断不能只给出 Python 主日志：点云、位姿和视频的真实故障通常在
            # 预处理节点或原生编码器的 stderr 中。所有条目来自
            # ToolLogStore 的固定白名单，不打包 logs/ 下的任意用户文件。
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                files = LOGS.diagnostic_files()
                if files:
                    for target in files:
                        bundle.writestr(target.name, target.read_bytes())
                else:
                    bundle.writestr("README.txt", "尚无 Aletheia 诊断日志。\n")
            body = archive.getvalue()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", "attachment; filename=ry-aletheia-diagnostics.zip")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            return
        target = LOGS.file(errors_only)
        if not target.is_file():
            body = b""
        else:
            body = target.read_bytes()
        filename = "ry-aletheia-error.log"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", f"attachment; filename={filename}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _download_diagnostic_file(self, target: Path | None) -> None:
        """Download exactly one whitelisted diagnostic file, never a raw path."""
        if target is None:
            self.send_error(HTTPStatus.NOT_FOUND, "诊断日志不存在")
            return
        try:
            body = target.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "诊断日志不可读")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", f"attachment; filename={target.name}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _delete_report(requested: str) -> None:
        target = ConsoleHandler._archive_report_target(requested)
        report_root = target.parent
        match = re.search(r"_([0-9a-f]{12})\.html$", target.name)
        if not match:
            raise ValueError("报告文件名不合法")
        run_id = match.group(1)
        csv_target = target.with_suffix(".csv")
        trajectory_dir = (report_root / f"run_{run_id}_trajectory").resolve()
        target.unlink()
        if csv_target.is_file():
            csv_target.unlink()
        if trajectory_dir.is_dir() and trajectory_dir.parent == report_root:
            shutil.rmtree(trajectory_dir)

    def _static_from(self, root: Path, requested: str) -> None:
        target = (root / requested).resolve()
        if root not in target.parents or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix == ".html":
            # 所有控制台页面共享品牌版本提示，避免四个独立页面重复维护同一段标记。
            body = body.replace(b"</body>", b'<script src="/brand_version.js"></script></body>')
            content_type = "text/html; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        # 控制台升级会整体替换带哈希的 Vue 分块。若浏览器复用旧 HTML/JS，入口会引用
        # 已不存在的旧分块并导致 #app 空白；控制台资源很小，优先保证版本一致性。
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _mobile_page(self, requested: str) -> None:
        """Serve the dedicated mobile shell without changing desktop HTML/CSS."""
        root = VUE_WEB_ROOT if requested in MOBILE_VUE_PAGES else WEB_ROOT
        target = (root / requested).resolve()
        if root not in target.parents or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        if target.suffix != ".html":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        shell_head = b'<link rel="stylesheet" href="/mobile_console.css">'
        shell_body = b'<script src="/brand_version.js"></script><script defer src="/mobile_console.js"></script>'
        # 构建产物和传统页面均有标准 head/body。若未来模板异常，宁可保留页面
        # 功能也不注入不完整的移动壳层。
        if b"</head>" in body and b"</body>" in body:
            body = body.replace(b"</head>", shell_head + b"</head>", 1)
            body = body.replace(b"</body>", shell_body + b"</body>", 1)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Vary", "User-Agent, Sec-CH-UA-Mobile")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Vary", "User-Agent, Sec-CH-UA-Mobile")
        self.end_headers()

    def _trajectory_svg(self, path: str) -> None:
        parts = path.split("/")
        if len(parts) != 8 or parts[4] != "attempts" or parts[6] != "trajectory":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            attempt_index = int(parts[5])
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        run = RUNS.get(parts[3])
        attempt = next((item for item in (run.attempts if run else []) if item.index == attempt_index), None)
        views = attempt.trajectory.get("visualizations", []) if attempt and attempt.trajectory else []
        view = next((item for item in views if item.get("map_id") == parts[7]), None)
        target = Path(view["file"]).resolve() if view and isinstance(view.get("file"), str) else None
        report_root = (WORKSPACE / "reports").resolve()
        if not target or not target.is_relative_to(report_root) or target.suffix != ".svg" or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status=HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # 配置、状态和用例列表均会在同一浏览器会话内被写入后立即回读；禁止启发式
        # 缓存，避免旧状态覆盖刚保存的受控配置。
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def run_console() -> None:
    try:
        if VIDEO.migrate_config():
            LOGGER.info("已补充离线升级新增的视频流默认配置")
    except VideoConfigurationError as exc:
        # Do not prevent the normal console from exposing an actionable
        # configuration error merely because an optional video migration could
        # not run.  VideoManager.status() reports the same error to the page.
        LOGGER.warning("视频配置迁移未执行：%s", exc)
    try:
        server = ThreadingHTTPServer(("0.0.0.0", 8087), ConsoleHandler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print("RY Aletheia 未启动：TCP 8087 已被现有控制台占用。")
            print("请直接访问 http://<小车IP>:8087；无需重复启动工具。")
            print("如需重新启动，请先在现有网页中点击“安全退出”，再以普通账户运行 ry-aletheia。")
            raise SystemExit(0)
        raise
    server.upgrade_pending = False
    server.restart_command = None
    # 长连接代理不应拖住安全退出或离线升级后的新版本启动。
    server.daemon_threads = True
    video_command = [str(sys.executable), "--video-runner"]
    if not getattr(sys, "frozen", False):
        video_command = [sys.executable, str(Path(__file__).resolve()), "--video-runner"]
    video_runtime = ConsoleVideoRuntime(VIDEO, WORKSPACE, video_command)
    # The HTTP handler may start/stop only this parent-owned controller; no
    # Supervisor or system service participates in the optional video path.
    server.video_runtime = video_runtime
    video_runtime.start_if_enabled()
    print("RY Aletheia 自动测试平台：http://0.0.0.0:8087")
    print("局域网访问：http://<小车IP>:8087")
    print("按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        video_runtime.stop()
        OBSERVATION.stop()
        server.server_close()
    if server.restart_command:
        # 工具不再由系统服务托管。无论终端、双击还是历史环境中是否残留
        # INVOCATION_ID，升级后一律派生新版本，避免误判后退出而不重启。
        # onefile 程序会继承父进程的 _MEI 解包环境；不重置会错误复用即将删除的目录。
        restart_environment = os.environ.copy()
        restart_environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        restart_environment.pop("INVOCATION_ID", None)
        subprocess.Popen(server.restart_command, cwd=WORKSPACE, env=restart_environment, start_new_session=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--video-runner"]:
        raise SystemExit(VideoRuntime(VIDEO, WORKSPACE, _VIDEO_INGEST, ROOT / "runtime" / "video").run())
    run_console()
