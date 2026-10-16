from __future__ import annotations

import json
import errno
import io
import mimetypes
import os
import queue
import re
import signal
import shutil
import subprocess
import sys
import threading
import tempfile
import tarfile
import zipfile
import cgi
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import parse_qs, quote, unquote, urlparse

# Keep the upgrade probe independent from ROS setup and console construction.
# It validates that the packaged entry point can be unpacked and started;
# importing runtime modules or re-executing into the robot environment here
# would make deployment performance part of the bootloader health check.
if __name__ == "__main__" and sys.argv[1:] == ["--self-check"]:
    print("RY Aletheia self-check OK")
    raise SystemExit(0)

from autodrive_console.case_store import CaseStore
from autodrive_console.bag_recording import BagRecordingError, BagRecordingManager
from autodrive_console.manual_bag_recording import ManualRecordingController, ManualRecordingError
from autodrive_console.acceptance_catalog import AcceptanceTaskCatalog
from autodrive_console.multi_task_catalog import MultiTaskCatalog
from autodrive_console.acceptance_orchestrator import AcceptanceConflict, AcceptanceOrchestrator, AcceptanceValidationError
from autodrive_console.acceptance_plan import AcceptancePlanStore
from autodrive_console.autostart import AutostartError, AutostartManager
from autodrive_console.case_workspace import CasePackageError, CaseWorkspace
from autodrive_console.deployment import DeploymentError, DeploymentStore
from autodrive_console.map_projection_jobs import MapProjectionJobs, MapProjectionError, MapProjectionConflict
from autodrive_console.component_defaults import ComponentDefaultsError, component_speed_defaults
from autodrive_console.mapping import MappingError, MappingSessionController, MappingUnavailable
from autodrive_console.localization_status import LocalizationStatusMonitor
from autodrive_console.manual_relocalization import (
    ManualRelocalizationConflict,
    ManualRelocalizationController,
    ManualRelocalizationError,
    ManualRelocalizationUnavailable,
)
from autodrive_console.observation import ObservationError, ObservationManager
from autodrive_console.manual_map_markers import ManualMapMarkerStore
from autodrive_console.map_marker_navigation import (
    MapMarkerNavigationConflict,
    MapMarkerNavigationController,
    MapMarkerNavigationError,
    MapMarkerNavigationUnavailable,
)
from autodrive_console.task_compiler import CompilationError
from autodrive_console.robot_gateway import RobotGateway
from autodrive_console.ros_executor import RosTaskExecutor
from autodrive_console.runtime_env import clear_legacy_fastdds_override, should_resource_robot_setup
from autodrive_console.robot_logs import (
    RobotLogError,
    RobotLogDownloadTracker,
    RobotLogStore,
    RobotLogTailTracker,
    ensure_utf8_text_stream,
    iter_ros_time_converted_bytes,
)
from autodrive_console.run_manager import RunManager
from autodrive_console.native_report_archive import (
    NativeReportArchive,
    NativeReportArchiveError,
    NativeReportNotFound,
)
from autodrive_console.scenario_setup import ScenarioSetupError, ScenarioSetupStore
from autodrive_console.scenario_activation import ScenarioActivationTracker
from autodrive_console.settings import SettingsStore
from autodrive_console.software_inventory import SoftwareInventory, SoftwareInventoryError, SoftwareInventoryUnavailable
from autodrive_console.supervisor import SupervisorClient
from autodrive_console.tool_logging import ToolLogConflict, ToolLogMissing, ToolLogStore
from autodrive_console.tool_audit import BrowserEventRecorder, audit_request, inject_client_diagnostics
from autodrive_console.upgrade_manager import UpgradeError, UpgradeManager
from autodrive_console.video import ConsoleVideoRuntime, VideoConfigurationError, VideoManager, VideoRuntime
from autodrive_console.trajectory_render import _png_gray, _read_pgm
from autodrive_console.vehicle_control import (
    MiniappTwistProfile,
    VehicleControlConflict,
    VehicleControlController,
    VehicleControlError,
    VehicleControlUnavailable,
)
from autodrive_console.vehicle_execution_status import VehicleExecutionStatusMonitor


ROS_ENVIRONMENT_REEXEC_MARKER = "ROVER_QA_ROS_ENV_REEXEC"


def ensure_ros_environment(*, force_source: bool = False) -> None:
    """让双击/直接执行二进制也使用机器人原有 ROS2 环境。"""
    setup_script = os.environ.get("ROVER_QA_SETUP_SCRIPT", "/opt/ry/install/setup.bash")
    if not should_resource_robot_setup(os.environ, setup_script, force=force_source):
        return
    if not Path(setup_script).is_file():
        return
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).resolve()))
    command.extend(sys.argv[1:])
    environment = {
        **os.environ,
        "ROVER_QA_ROS_READY": "1",
        ROS_ENVIRONMENT_REEXEC_MARKER: "1",
    }
    os.execvpe("/bin/bash", ["bash", "-c", 'source "$1" && shift && exec "$@"', "--", setup_script, *command], environment)


legacy_fastdds_removed = False
if os.environ.get(ROS_ENVIRONMENT_REEXEC_MARKER) != "1":
    legacy_fastdds_removed = clear_legacy_fastdds_override()
ensure_ros_environment(force_source=legacy_fastdds_removed)

ROOT = Path(getattr(__import__("sys"), "_MEIPASS", Path(__file__).resolve().parent))
# 运行数据必须落在可写的工程目录；打包时不能写入 _MEIPASS。
WORKSPACE = Path.cwd()
if not getattr(__import__("sys"), "frozen", False):
    WORKSPACE = Path(__file__).resolve().parent
TASK_DIR = WORKSPACE / "tasks"
CONFIG_DIR = WORKSPACE / "config"
MAX_CASE_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_MAP_UPLOAD_BYTES = DeploymentStore.MAX_MAP_BYTES + 64 * 1024 * 1024
MAX_MAPPING_TEMPLATE_BYTES = 2 * 1024 * 1024
TEST_REPORT_FILENAME = re.compile(r"(?:run_[0-9a-f]{12}_[^/]+|报告_\d{8}_\d{6}_[^/]+_[0-9a-f]{12})\.html")
ACCEPTANCE_REPORT_FILENAME = re.compile(r"acceptance_[0-9a-f]{12}_\d{8}_\d{6}\.html")
REPORT_FILENAME = re.compile(
    r"(?:run_[0-9a-f]{12}_[^/]+|报告_\d{8}_\d{6}_[^/]+_[0-9a-f]{12}|acceptance_[0-9a-f]{12}_\d{8}_\d{6})\.html"
)
LOGS = ToolLogStore(WORKSPACE / "logs", policy_path=CONFIG_DIR / "tool_logging.json")
LOGGER = LOGS.configure()
CLIENT_DIAGNOSTICS = BrowserEventRecorder()
# Configure before constructors recover persisted jobs/runs and emit diagnostics.
STORE = CaseStore(TASK_DIR)
CASE_WORKSPACE = CaseWorkspace(CONFIG_DIR, TASK_DIR)
DEPLOYMENTS = DeploymentStore(WORKSPACE / "deployments")
MAP_PROJECTIONS = MapProjectionJobs(DEPLOYMENTS)
SETTINGS = SettingsStore(CONFIG_DIR / "console.json")
SOFTWARE_INVENTORY = SoftwareInventory(SETTINGS)
LOCALIZATION_STATUS = LocalizationStatusMonitor()


def _autostart_launcher() -> list[str]:
    """Resolve the operator-owned launcher without trusting request data."""
    packaged_launcher = Path("/usr/bin/ry-aletheia")
    if packaged_launcher.is_file():
        return [str(packaged_launcher)]
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve())]


AUTOSTART = AutostartManager(WORKSPACE, launcher=_autostart_launcher())
ROBOT_LOGS = RobotLogStore(SETTINGS)
ROBOT_LOG_DOWNLOADS = RobotLogDownloadTracker()
ROBOT_LOG_TAILS = RobotLogTailTracker()
SCENARIO_SETUP = ScenarioSetupStore(CONFIG_DIR)
BAG_RECORDINGS = BagRecordingManager(WORKSPACE / "bag_recordings")
RUNS = RunManager(
    WORKSPACE / "reports", RosTaskExecutor(), SETTINGS, SCENARIO_SETUP,
    localization_monitor=LOCALIZATION_STATUS, bag_recordings=BAG_RECORDINGS,
)
MANUAL_BAG_RECORDINGS = ManualRecordingController(
    BAG_RECORDINGS,
    test_recording_active=lambda: RUNS.has_active_bag_recording(),
)
RUNS.set_manual_bag_recording_guard(MANUAL_BAG_RECORDINGS.has_active_recording)
ACCEPTANCE = AcceptanceOrchestrator(
    catalog=AcceptanceTaskCatalog(Path(SETTINGS.load().task_directory)),
    multi_catalog=MultiTaskCatalog(Path("/opt/ry/data/tasks/multi_tasks")),
    plan_store=AcceptancePlanStore(CONFIG_DIR / "acceptance"),
    run_manager=RUNS,
    report_dir=WORKSPACE / "reports",
    scenario_setup=SCENARIO_SETUP,
    settings=SETTINGS,
)
# 不复用运行测试的 ROS service client：手动控制有自己的 node/executor/timer，
# 但与现有模块共用同一进程内 rclpy runtime，避免创建任何转发层。
VEHICLE_CONTROL = VehicleControlController(
    active_run_guard=RUNS.manual_control_blocked,
    twist_profile=MiniappTwistProfile(**SETTINGS.load().vehicle_control),
)
MANUAL_RELOCALIZATION = ManualRelocalizationController(
    VEHICLE_CONTROL,
    SCENARIO_SETUP,
    localization_status=LOCALIZATION_STATUS,
)
# 执行状态是只读的全局车辆事实，不附着到按轮创建/停止的 TrajectorySession。
# 即使没有浏览器打开，其 volatile ROS 话题也必须被持续接收。
VEHICLE_EXECUTION_STATUS = VehicleExecutionStatusMonitor(
    restarting_nodes=RUNS.dependency_restart_active,
    vehicle_control_status=VEHICLE_CONTROL.status,
)
# 建图会话不复用测试执行器或手动控制 node。它只管理 Lightning 进程与本机
# 栅格预览订阅，所有临时 YAML/预览都写入部署工作区，绝不覆盖机器人配置。
MAPPING = MappingSessionController(WORKSPACE / "deployments" / ".mapping-sessions", active_run_guard=RUNS.has_active_run)
WEB_ROOT = ROOT / "autodrive_console" / "web"
VUE_WEB_ROOT = ROOT / "autodrive_console" / "web-vue"
UPGRADES = UpgradeManager(WORKSPACE, Path(sys.executable), getattr(sys, "frozen", False))
SYSTEMD_USER_SERVICE = "ry-aletheia.service"
_LIVE_PREPROCESSOR = ROOT / "aletheia_live_cloud" if getattr(sys, "frozen", False) else ROOT / "build" / "live_preprocessor" / "aletheia_live_cloud"
_VIDEO_INGEST = ROOT / "aletheia_video_ingest" if getattr(sys, "frozen", False) else ROOT / "build" / "live_preprocessor" / "aletheia_video_ingest"
OBSERVATION = ObservationManager(WORKSPACE / "maps_cache", WORKSPACE / "logs", _LIVE_PREPROCESSOR)
MAP_MARKERS = ManualMapMarkerStore(CONFIG_DIR / "live_map_markers.json")
MAP_MARKER_NAVIGATION = MapMarkerNavigationController(
    MAP_MARKERS, OBSERVATION,
    VEHICLE_CONTROL, LOCALIZATION_STATUS, active_run_guard=RUNS.has_active_run,
)
RUNS.set_map_marker_navigation_guard(MAP_MARKER_NAVIGATION.blocks_runs)
VEHICLE_CONTROL.set_map_marker_navigation_guard(MAP_MARKER_NAVIGATION.blocks_runs)
VIDEO = VideoManager(CONFIG_DIR / "video.json", ROOT / "config" / "video.json")
SCENARIO_RUNTIME_LOCK = SCENARIO_SETUP.runtime_lock


def _is_systemd_service_context(cgroup_reader: Callable[[], str] | None = None) -> bool:
    """Return whether this process is owned by Aletheia's user service.

    ``INVOCATION_ID`` alone is not a service-ownership proof: desktop terminals
    can inherit it from their session.  Aletheia may ask systemd to replace its
    own cgroup only when both the invocation marker and the concrete service
    cgroup agree.  Otherwise a direct launch must retain the detached-spawn
    restart path.
    """

    if not os.environ.get("INVOCATION_ID"):
        return False
    try:
        cgroups = (cgroup_reader or (lambda: Path("/proc/self/cgroup").read_text(encoding="utf-8")))()
    except OSError:
        return False
    return any(f"/{SYSTEMD_USER_SERVICE}" in line for line in cgroups.splitlines())


def _spawn_upgrade_restart(workspace: Path, executable: Path) -> bool:
    """Hand the upgraded process back to its owner without a cgroup race.

    A user systemd service uses ``KillMode=control-group`` by default.  A
    child process started by the old service therefore dies when the old main
    process exits, even when it has a new session.  Ask systemd to restart its
    own unit in that case; direct launches keep the detached executable path.
    """
    restart_environment = os.environ.copy()
    restart_environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    restart_environment.pop("INVOCATION_ID", None)
    if _is_systemd_service_context():
        command = ["systemctl", "--user", "restart", "--no-block", SYSTEMD_USER_SERVICE]
        try:
            result = subprocess.run(
                command,
                cwd=workspace,
                env=restart_environment,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            LOGGER.exception("离线升级后无法请求 systemd 重启：command=%s", command)
            return False
        if result.returncode != 0:
            LOGGER.error("systemd 未接受离线升级重启请求：returncode=%s", result.returncode)
            return False
        return True
    else:
        command = [str(executable)]
    try:
        subprocess.Popen(
            command,
            cwd=workspace,
            env=restart_environment,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        LOGGER.exception("离线升级后无法安排控制台重启：command=%s", command)
        return False
    return True


def _handoff_to_systemd_after_upgrade() -> None:
    """End a replaced service immediately after systemd accepts its restart.

    The user service owns every console child in its cgroup.  During an
    upgrade systemd's restart job will terminate that cgroup before starting
    the new binary.  Waiting for Python/ROS cleanup here has previously held
    the stop job until ``TimeoutStopSec`` and left operators with no console.
    This path is deliberately limited to the verified service cgroup; direct
    terminal launches still take the normal bounded cleanup path below.
    """

    os._exit(0)


def _install_console_shutdown_signal_handlers(server: ThreadingHTTPServer):
    """Route process termination through the console's owned-resource cleanup.

    ``BaseServer.shutdown`` must run outside the thread currently serving
    requests.  POSIX invokes Python signal handlers on that serving main
    thread, so the handler only starts the orderly shutdown in a small daemon
    thread.  Repeated systemd signals are intentionally idempotent: the first
    one has already begun releasing the video and observation process trees.
    """

    shutdown_requested = threading.Event()
    previous_handlers = {}

    def request_shutdown(signum, _frame) -> None:
        if shutdown_requested.is_set():
            return
        shutdown_requested.set()
        LOGGER.info("收到退出信号 %s，正在受控关闭 Aletheia", signum)
        threading.Thread(
            target=server.shutdown,
            name="console-signal-shutdown",
            daemon=True,
        ).start()

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, request_shutdown)

    def restore() -> None:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)

    return restore


def _close_console_resources(
    native_backfill_stop: threading.Event,
    video_runtime: ConsoleVideoRuntime,
    server: ThreadingHTTPServer,
) -> None:
    """Release owned resources without letting one failed child strand an upgrade."""

    # The binary replacement has already completed before shutdown begins.
    # Each owner provides its own bounded stop path; an unexpected exception
    # here must be recorded, but cannot be allowed to skip the new binary's
    # restart below.
    def close_one(label: str, operation) -> None:
        try:
            operation()
        except Exception:
            LOGGER.exception("关闭控制台资源失败：%s", label)

    close_one("原生报告回填", native_backfill_stop.set)
    close_one("工具日志维护", LOGS.stop_maintenance)
    # Keep the console-owned video lifecycle explicit: this is the only
    # process family whose shutdown may briefly wait for encoder children.
    # Failure is isolated so an already replaced binary is still restarted.
    try:
        video_runtime.stop()
    except Exception:
        LOGGER.exception("关闭控制台资源失败：视频运行时")

    for label, operation in (
        ("手动场景录制", MANUAL_BAG_RECORDINGS.close),
        ("在线建图", MAPPING.close),
        ("地图标记导航", MAP_MARKER_NAVIGATION.close),
        ("手动重定位地图查询", MANUAL_RELOCALIZATION.close),
        ("车辆控制", VEHICLE_CONTROL.close),
        ("车辆执行状态", VEHICLE_EXECUTION_STATUS.close),
        ("定位状态", LOCALIZATION_STATUS.close),
        ("实时观测", OBSERVATION.stop),
        ("HTTP 服务", server.server_close),
    ):
        close_one(label, operation)


def _upgrade_status() -> dict:
    """Expose upgrade readiness before an operator commits an upload."""

    status = UPGRADES.status()
    if not status.get("supported"):
        status["availability"] = {
            "ready": False,
            "blocker": {
                "kind": "unsupported",
                "message": str(status.get("message") or "当前运行方式不支持离线升级。"),
                "action_label": "",
                "action_url": "",
            },
        }
        return status
    if RUNS.has_active_run():
        status["availability"] = {
            "ready": False,
            "blocker": {
                "kind": "active_run",
                "message": "当前存在执行中、取消中或等待人工恢复的测试计划。请先安全结束测试后再升级。",
                "action_label": "前往任务指挥台",
                "action_url": "/",
            },
        }
        return status
    if SCENARIO_SETUP.has_unresolved_transaction():
        transaction = SCENARIO_SETUP.status().get("transaction", {})
        status["availability"] = {
            "ready": False,
            "blocker": {
                "kind": "scenario_recovery",
                "message": str(transaction.get("message") or "当前存在未完成的场景恢复事务。请先恢复常规启动配置后再升级。"),
                "action_label": "前往恢复常规配置",
                "action_url": "/scenario-setup.html",
            },
        }
        return status
    status["availability"] = {"ready": True, "blocker": None}
    return status


def restore_scenario_runtime() -> dict:
    """只恢复受控启动脚本，不操作任何 Supervisor 节点。"""
    # ThreadingHTTPServer 可同时处理重复点击/多个网页标签。恢复事务的“读取 →
    # 定向回写 → 校验 → 清理”必须串行，避免两个请求交叉覆盖同一受控参数。
    # 常规配置只在下次由机器人系统自行启动相关进程时生效；手动恢复不应
    # 打断当前运行节点，也不应借此扩大 Aletheia 的节点控制范围。
    with SCENARIO_RUNTIME_LOCK:
        return SCENARIO_SETUP.restore()


def apply_scenario_runtime(
    profile_id: str,
    document: dict | None = None,
    progress_callback: Callable[[str, str, dict | None], None] | None = None,
) -> dict:
    """应用场景并使相应运行依赖实际重新读取参数。"""
    def progress(phase: str, message: str, details: dict | None = None) -> None:
        if progress_callback is not None:
            progress_callback(phase, message, details)

    with SCENARIO_RUNTIME_LOCK:
        progress("writing", "正在校验并写入场景启动参数。")
        if document is not None:
            SCENARIO_SETUP.save(document)
        result = SCENARIO_SETUP.apply(profile_id)
        progress("restarting", "启动参数已写入，正在重启定位与导航依赖。")

        def runtime_progress(details: dict) -> None:
            stages = details.get("stages") if isinstance(details, dict) else []
            active = next((stage for stage in stages if stage.get("state") not in {"pending", "ready"}), None)
            label = f"第 {active['index']} 阶段" if isinstance(active, dict) and active.get("index") else "定位与导航依赖"
            progress("waiting", f"正在等待{label}稳定就绪。", details)

        try:
            gateway = RobotGateway(SETTINGS.load())
            runtime_ok, runtime_message = gateway.restart_configured_dependencies(progress_callback=runtime_progress)
        except Exception as exc:
            runtime_ok, runtime_message = False, f"启动运行依赖时发生异常：{exc}"
        if not runtime_ok:
            SCENARIO_SETUP.note_runtime_activation_failure(runtime_message)
            raise ScenarioSetupError(f"场景启动脚本已写入，但运行依赖未能读取新参数：{runtime_message}。请恢复常规配置后重试")
        result["runtime_restart"] = runtime_message
        result["message"] = f"{result['message']}；{runtime_message}"
        return result


SCENARIO_ACTIVATIONS = ScenarioActivationTracker(
    lambda profile_id, document, progress: apply_scenario_runtime(profile_id, document, progress),
)

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


def _backfill_native_report_batch(workspace: Path, *, maximum: int = 4) -> int:
    """Upgrade a small number of legacy report sidecars outside HTTP requests."""
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
        raise ValueError("原生报告回填批次无效")
    archive = NativeReportArchive(Path(workspace) / "reports")
    created = 0
    for filename in archive.historic_filenames()[:maximum]:
        if archive.archive_historic_report(filename):
            created += 1
    return created


def _native_report_backfill_worker(stop_event: threading.Event, workspace: Path) -> None:
    """Yield between bounded legacy batches so startup and tests stay responsive."""
    archive = NativeReportArchive(Path(workspace) / "reports")
    try:
        filenames = archive.historic_filenames()
        for offset in range(0, len(filenames), 4):
            if stop_event.is_set():
                return
            for filename in filenames[offset:offset + 4]:
                if stop_event.is_set():
                    return
                archive.archive_historic_report(filename)
            stop_event.wait(0.05)
    except OSError as exc:
        LOGGER.warning("原生报告历史回填失败：%s", exc)


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
            if not getattr(self, "_tool_exception_logged", False):
                LOGGER.exception("HTTP 请求处理发生未处理异常：client=%s", self.client_address[0] if self.client_address else "unknown")
            raise

    def send_response(self, code, message=None) -> None:
        audit = getattr(self, "_tool_audit", None)
        if audit is not None:
            audit.status = int(code)
        super().send_response(code, message)
        if audit is not None and audit.is_api:
            self.send_header("X-Request-ID", audit.request_id)

    def send_error(self, code, message=None, explain=None) -> None:
        audit = getattr(self, "_tool_audit", None)
        if audit is not None:
            audit.response(code, {"error": message} if isinstance(message, str) else None)
        super().send_error(code, message, explain)

    @audit_request
    def do_GET(self) -> None:
        request = urlparse(self.path)
        path = request.path
        if path.startswith("/api/deployments/") and "/map-projections" in path:
            self._map_projection_request("GET", path, request.query)
            return
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
        elif path == "/deployment.html":
            self._static_from(WEB_ROOT, "deployment.html")
        elif path == "/mapping-workbench.html":
            self._static_from(WEB_ROOT, "mapping-workbench.html")
        elif path == "/manual-control.html":
            self._static_from(WEB_ROOT, "manual-control.html")
        elif path == "/vehicle-execution-status.html":
            self._static_from(WEB_ROOT, "vehicle-execution-status.html", inject_console_shell=False)
        elif path == "/acceptance-test.html":
            self._static_from(WEB_ROOT, "acceptance-test.html")
        elif path == "/vue/dashboard.html":
            self._static_from(VUE_WEB_ROOT, "dashboard.html")
        elif path.startswith("/vue/"):
            self._static_from(VUE_WEB_ROOT, path.removeprefix("/vue/"))
        elif path == "/api/cases":
            cases, issues = STORE.list_cases()
            self._json({"cases": [self._case(case) for case in cases], "validationIssues": issues})
        elif path == "/api/vehicle-control":
            # 返回的是订阅 /control_source_state 得到的实际源状态，不由前端点击推断。
            self._json(VEHICLE_CONTROL.status())
        elif path == "/api/vehicle-execution-status":
            self._json(VEHICLE_EXECUTION_STATUS.status())
        elif path == "/api/acceptance/catalog":
            self._json(ACCEPTANCE.catalog_summary())
        elif path == "/api/acceptance/criteria":
            self._json(ACCEPTANCE.criteria())
        elif path == "/api/acceptance/plans/current":
            plan = ACCEPTANCE.current()
            self._json({"plan": plan}, HTTPStatus.OK if plan else HTTPStatus.NOT_FOUND)
        elif path.startswith("/api/acceptance/plans/") and path.endswith("/report"):
            self._acceptance_report(path.removeprefix("/api/acceptance/plans/").removesuffix("/report").strip("/"))
        elif path.startswith("/api/acceptance/plans/"):
            plan_id = path.removeprefix("/api/acceptance/plans/").strip("/")
            plan = ACCEPTANCE.current()
            self._json({"plan": plan}, HTTPStatus.OK if plan and plan["plan_id"] == plan_id else HTTPStatus.NOT_FOUND)
        elif path == "/api/mapping":
            self._json(MAPPING.status())
        elif path == "/api/deployment-component-defaults":
            try:
                self._json({"component_speed_defaults": component_speed_defaults()})
            except ComponentDefaultsError as exc:
                self._json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
        elif path.startswith("/api/mapping/sessions/") and path.endswith("/preview.png"):
            session_id = unquote(path.removeprefix("/api/mapping/sessions/").removesuffix("/preview.png").strip("/"))
            self._mapping_preview(session_id)
        elif path == "/api/deployments":
            self._json({"projects": DEPLOYMENTS.list_projects(), "mapping": MAPPING.status()})
        elif path.startswith("/api/deployments/") and path.endswith("/task-compiler/preview"):
            try:
                project_id = self._task_compiler_project_id(path, "/task-compiler/preview")
                self._json({"preview": DEPLOYMENTS.task_compiler_preview(project_id)})
            except CompilationError as exc:
                self._json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        elif path.startswith("/api/deployments/") and path.endswith("/task-compiler/download"):
            try:
                project_id = self._task_compiler_project_id(path, "/task-compiler/download")
                filename, body = DEPLOYMENTS.task_compiler_bundle(project_id)
            except CompilationError as exc:
                self._json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            else:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f"attachment; filename=task-compiler-experimental.zip; filename*=UTF-8''{quote(filename)}")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
        elif path.startswith("/api/deployments/") and path.endswith("/preview.png"):
            parts = path.split("/")
            if len(parts) != 7 or parts[4] != "maps":
                self.send_error(HTTPStatus.NOT_FOUND)
            else:
                self._deployment_map_preview(parts[3], parts[5])
        elif path.startswith("/api/deployments/") and path.endswith("/topology"):
            try:
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/topology").strip("/"))
                self._json({"topology": DEPLOYMENTS.validate_topology(project_id)})
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        elif path.startswith("/api/deployments/"):
            try:
                self._json({"project": DEPLOYMENTS.get(unquote(path.removeprefix("/api/deployments/").strip("/")))})
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        elif path.startswith("/api/cases/") and path.endswith("/export"):
            self._export_case_package(unquote(path.removeprefix("/api/cases/").removesuffix("/export").rstrip("/")))
        elif path == "/api/settings":
            self._json(self._settings())
        elif path == "/api/software-inventory":
            self._json(SOFTWARE_INVENTORY.snapshot())
        elif path == "/api/scenario-setup/activation":
            self._json({"operation": SCENARIO_ACTIVATIONS.status()})
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
        elif path == "/api/bag-recordings/topics":
            try:
                self._json({"topics": BAG_RECORDINGS.available_topics()})
            except BagRecordingError as exc:
                self._json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
        elif path == "/api/bag-recordings/manual":
            self._json({"manual": MANUAL_BAG_RECORDINGS.status()})
        elif path == "/api/bag-recordings":
            self._json({"archives": BAG_RECORDINGS.list_archives()})
        elif match := re.fullmatch(r"/api/bag-recordings/([0-9a-f]{32})/download", path):
            self._download_bag_archive(match.group(1))
        elif match := re.fullmatch(r"/api/bag-recordings/([0-9a-f]{32})", path):
            try:
                self._json(BAG_RECORDINGS.archive_detail(match.group(1)))
            except BagRecordingError as exc:
                self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        elif path.startswith("/api/reports/") and "/native" in path:
            self._native_report_route(path, parse_qs(request.query, keep_blank_values=True))
        elif path == "/api/reports":
            self._json({"reports": self._reports()})
        elif path == "/api/system/upgrade":
            self._json(_upgrade_status())
        elif path == "/api/observation/active-map":
            # 地图切换标记只有一个短 ID，供实时页快速发现 map_server 生命周期
            # 切换；绝不通过此接口传输或轮询 OccupancyGrid 栅格数据。
            map_id = OBSERVATION.active_map_id()
            payload = {"active_map_id": map_id}
            if parse_qs(request.query).get("include_route") == ["true"]:
                payload["navigation_route"] = OBSERVATION.navigation_route(map_id)
            self._json(payload)
        elif path == "/api/observation/localization-status":
            self._json(LOCALIZATION_STATUS.status())
        elif path == "/api/observation/relocalization":
            try:
                query = parse_qs(request.query, keep_blank_values=True)
                if "request_id" in query:
                    self._json(MANUAL_RELOCALIZATION.operation_status(query["request_id"][0]))
                else:
                    self._json(MANUAL_RELOCALIZATION.status(SETTINGS.load()))
            except ManualRelocalizationError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        elif path == "/api/observation/relocalization/configs":
            try:
                query = parse_qs(request.query, keep_blank_values=True)
                self._json(MANUAL_RELOCALIZATION.browse_configs(query.get("path", [""])[0]))
            except ManualRelocalizationError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        elif path == "/api/observation/map-markers":
            active_map_id = OBSERVATION.active_manual_map_id()
            if active_map_id is None:
                self._json({"map_ready": False, "points": []})
            else:
                self._json({"map_ready": True, "points": MAP_MARKERS.list_for_map(active_map_id)})
        elif path == "/api/observation/map-marker-navigation":
            self._json(MAP_MARKER_NAVIGATION.status())
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
            self._json({"files": LOGS.diagnostic_records(), "storage": LOGS.storage_status()})
        elif path == "/api/tool-logs/download":
            self._download_tool_log(request.query == "scope=errors")
        elif path.startswith("/api/tool-logs/files/") and path.endswith("/download"):
            name = unquote(path.removeprefix("/api/tool-logs/files/").removesuffix("/download").strip("/"))
            self._download_diagnostic_file(LOGS.diagnostic_file(name))
        elif path == "/api/robot-logs/sources":
            self._json({"sources": ROBOT_LOGS.sources()})
        elif match := re.fullmatch(r"/api/robot-logs/downloads/([0-9a-f]{32})", path):
            try:
                self._json({"download": ROBOT_LOG_DOWNLOADS.status(match.group(1))})
            except RobotLogError as exc:
                self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        elif match := re.fullmatch(r"/api/robot-logs/downloads/([0-9a-f]{32})/file", path):
            self._download_tracked_robot_log_file(match.group(1))
        elif match := re.fullmatch(r"/api/robot-logs/sources/([a-z0-9_-]{1,32})/files/([0-9a-f]{24})/download", path):
            self._download_robot_log_file(*match.groups(), convert_ros_time=query.get("ros_time", [""])[0] == "beijing")
        elif path == "/api/robot-logs/tail":
            streams = []
            for value in query.get("stream", []):
                match = re.fullmatch(r"([a-z0-9_-]{1,32}):([0-9a-f]{24})", value)
                if not match:
                    self.send_error(HTTPStatus.BAD_REQUEST, "实时日志标识无效")
                    return
                stream = match.groups()
                if stream not in streams:
                    streams.append(stream)
            if not streams:
                self.send_error(HTTPStatus.BAD_REQUEST, "请至少选择一条实时日志")
                return
            self._tail_robot_logs_stdout(streams)
        elif match := re.fullmatch(r"/api/robot-logs/sources/([a-z0-9_-]{1,32})/files/([0-9a-f]{24})/tail", path):
            self._tail_robot_log_stdout(*match.groups())
        elif match := re.fullmatch(r"/api/robot-logs/sources/([a-z0-9_-]{1,32})/files", path):
            try:
                query = parse_qs(request.query).get("query", [""])[0]
                self._json({"files": ROBOT_LOGS.list_files(match.group(1), query=query)})
            except RobotLogError as exc:
                self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
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

    @audit_request
    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/tool-logs/cleanup" or (path.startswith("/api/tool-logs/files/") and path.endswith("/clear")):
            self._manage_tool_log("POST", path)
            return
        if path == "/api/tool-logs/client-events":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if not 2 <= content_length <= 8192:
                    self.close_connection = True
                    raise ValueError("浏览器诊断请求大小无效")
                payload = json.loads(self.rfile.read(content_length))
                recorded = CLIENT_DIAGNOSTICS.record(payload, self.client_address[0])
                self._json({"recorded": recorded}, HTTPStatus.ACCEPTED)
            except OverflowError as exc:
                self._json({"error": str(exc)}, HTTPStatus.TOO_MANY_REQUESTS)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/map-projections" in path:
            self._map_projection_request("POST", path)
            return
        if path == "/api/bag-recordings/manual":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if not 2 <= content_length <= 8192:
                    raise ManualRecordingError("手动录制请求无效")
                payload = json.loads(self.rfile.read(content_length))
                self._json({"manual": MANUAL_BAG_RECORDINGS.start(payload)}, HTTPStatus.ACCEPTED)
            except (ManualRecordingError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
        if path == "/api/bag-recordings/manual/stop":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length:
                    payload = json.loads(self.rfile.read(content_length))
                    if payload != {}:
                        raise ManualRecordingError("停止手动录制不接受参数")
                self._json({"manual": MANUAL_BAG_RECORDINGS.stop()}, HTTPStatus.ACCEPTED)
            except (ManualRecordingError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
        if path == "/api/robot-logs/downloads":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= content_length <= 2048:
                    raise RobotLogError("下载请求无效")
                payload = json.loads(self.rfile.read(content_length))
                if not isinstance(payload, dict) or set(payload) != {"source_id", "file_id", "ros_time"}:
                    raise RobotLogError("下载请求无效")
                source_id = payload["source_id"]
                file_id = payload["file_id"]
                ros_time = payload["ros_time"]
                if not isinstance(source_id, str) or not isinstance(file_id, str) or ros_time not in {"beijing", "raw"}:
                    raise RobotLogError("下载请求无效")
                record = next((item for item in ROBOT_LOGS.list_files(source_id) if item["id"] == file_id), None)
                if record is None:
                    raise RobotLogError("日志文件已变化或不存在")
                download = ROBOT_LOG_DOWNLOADS.prepare(
                    source_id, file_id, record["name"], record["size_bytes"], convert_ros_time=ros_time == "beijing",
                )
                self._json({"download": download}, HTTPStatus.CREATED)
            except (TypeError, ValueError, json.JSONDecodeError, RobotLogError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/acceptance/"):
            self._acceptance_action(path)
            return
        if path.startswith("/api/vehicle-control/"):
            self._vehicle_control_action(path)
            return
        if path == "/api/mapping/sessions":
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = str(data.get("project_id", ""))
                # Validate the project before allocating any mapping session directory.
                DEPLOYMENTS.get(project_id)
                session = MAPPING.prepare(
                    project_id,
                    template_id=data.get("template_id"), label=data.get("label"), kind=data.get("kind"),
                )
                self._json({"session": session}, HTTPStatus.CREATED)
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError, MappingError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/mapping/sessions/") and path.endswith("/start"):
            try:
                session_id = unquote(path.removeprefix("/api/mapping/sessions/").removesuffix("/start").strip("/"))
                self._json({"session": MAPPING.start(session_id)}, HTTPStatus.ACCEPTED)
            except MappingUnavailable as exc:
                self._json({"error": str(exc), "mapping": MAPPING.status()}, HTTPStatus.SERVICE_UNAVAILABLE)
            except MappingError as exc:
                self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
        if path.startswith("/api/mapping/sessions/") and path.endswith("/stop"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                session_id = unquote(path.removeprefix("/api/mapping/sessions/").removesuffix("/stop").strip("/"))
                session = MAPPING.stop(session_id, save=bool(data.get("save", True)))
                payload = {"session": session}
                if session["state"] == "saved":
                    try:
                        asset = DEPLOYMENTS.import_captured_map(
                            session["project_id"], Path(session["output_dir"]) / "map.yaml",
                            session["label"], session["kind"], MAPPING.root,
                        )
                        payload["map"] = asset
                        payload["project"] = DEPLOYMENTS.get(session["project_id"])
                    except DeploymentError as exc:
                        # The session record and generated files remain for
                        # diagnosis; never pretend a failed capture is ready
                        # to edit or deploy.
                        payload["capture_error"] = str(exc)
                self._json(payload)
            except (TypeError, ValueError, json.JSONDecodeError, MappingError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
        if path.startswith("/api/mapping/sessions/") and path.endswith("/discard"):
            try:
                session_id = unquote(path.removeprefix("/api/mapping/sessions/").removesuffix("/discard").strip("/"))
                self._json({"session": MAPPING.discard(session_id)})
            except MappingError as exc:
                self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
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
        if path == "/api/deployments":
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if (
                    not isinstance(data, dict)
                    or set(data) != {"name", "task_mode"}
                    or not isinstance(data["name"], str)
                    or not isinstance(data["task_mode"], str)
                    or data["task_mode"] not in DeploymentStore.TASK_MODES
                ):
                    raise DeploymentError("创建项目仅接受项目名称和任务模式")
                self._json(
                    {"project": DEPLOYMENTS.create(data["name"], data["task_mode"])},
                    HTTPStatus.CREATED,
                )
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/settings"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                parts = path.split("/")
                if len(parts) != 5 or parts[4] != "settings":
                    raise DeploymentError("项目设置路径无效")
                project_id = unquote(parts[3])
                self._json({"project": DEPLOYMENTS.update_project_settings(project_id, data)})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/task-compiler/config"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if not isinstance(data, dict) or set(data) != {"community"} or not isinstance(data["community"], str):
                    raise DeploymentError("任务编译器配置仅接受小区名称")
                project_id = self._task_compiler_project_id(path, "/task-compiler/config")
                self._json({"task_compiler": DEPLOYMENTS.update_task_compiler_config(project_id, data)})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/task-compiler/preview"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if not isinstance(data, dict) or data:
                    raise DeploymentError("任务编译预览请求必须为空对象")
                project_id = self._task_compiler_project_id(path, "/task-compiler/preview")
                self._json({"preview": DEPLOYMENTS.task_compiler_preview(project_id)})
            except CompilationError as exc:
                self._json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/task-lines" in path:
            try:
                parts = path.split("/")
                if len(parts) not in {5, 6, 7} or parts[4] != "task-lines":
                    raise DeploymentError("任务线路路径无效")
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(parts[3])
                if len(parts) == 7:
                    if parts[6] != "select" or not isinstance(data, dict) or data:
                        raise DeploymentError("选择任务线路请求必须为空对象")
                    project = DEPLOYMENTS.select_task_line(project_id, unquote(parts[5]))
                    self._json({"project": project})
                else:
                    line = DEPLOYMENTS.save_task_line(project_id, data, unquote(parts[5]) if len(parts) == 6 else None)
                    self._json({"task_line": line, "project": DEPLOYMENTS.get(project_id)})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/localization-routes/derive"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if not isinstance(data, dict) or data:
                    raise DeploymentError("自动路线派生请求必须为空对象")
                project_id = unquote(
                    path.removeprefix("/api/deployments/").removesuffix("/localization-routes/derive").strip("/")
                )
                project = DEPLOYMENTS.derive_localization_routes(project_id)
                self._json({"project": project, "localization_routes": project.get("localization_routes", [])})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/localization-routes"):
            try:
                raise DeploymentError("定位路线由系统自动派生；请完成地图标记后使用 /localization-routes/derive")
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/localization-routes/" in path:
            try:
                raise DeploymentError("定位路线由系统自动派生，不能人工修改")
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/localization-bindings"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(
                    path.removeprefix("/api/deployments/").removesuffix("/localization-bindings").strip("/")
                )
                binding = DEPLOYMENTS.create_localization_binding(project_id, data)
                self._json(
                    {"localization_binding": binding, "project": DEPLOYMENTS.get(project_id)},
                    HTTPStatus.CREATED,
                )
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/localization-bindings/" in path:
            try:
                parts = path.split("/")
                if len(parts) != 6 or parts[4] != "localization-bindings":
                    raise DeploymentError("定位绑定路径无效")
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(parts[3])
                binding = DEPLOYMENTS.update_localization_binding(project_id, unquote(parts[5]), data)
                self._json({"localization_binding": binding, "project": DEPLOYMENTS.get(project_id)})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/maps/import"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/maps/import").strip("/"))
                asset = DEPLOYMENTS.import_map(project_id, data.get("source_yaml"), data.get("label"), data.get("kind"))
                self._json({"map": asset, "project": DEPLOYMENTS.get(project_id)}, HTTPStatus.CREATED)
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/maps/upload"):
            project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/maps/upload").strip("/"))
            self._upload_deployment_map(project_id)
            return
        if path.startswith("/api/deployments/") and path.endswith("/mapping-template"):
            project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/mapping-template").strip("/"))
            self._upload_mapping_template(project_id)
            return
        if path.startswith("/api/deployments/") and path.endswith("/localization-template"):
            project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/localization-template").strip("/"))
            self._upload_localization_template(project_id)
            return
        if path.startswith("/api/deployments/") and path.endswith("/map-stages"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/map-stages").strip("/"))
                plan = DEPLOYMENTS.assign_map_stage(project_id, data.get("map_asset_id"), data.get("stage"))
                self._json({"stage_plan": plan, "project": DEPLOYMENTS.get(project_id)})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/transitions"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/transitions").strip("/"))
                transition = DEPLOYMENTS.add_map_transition(project_id, data)
                self._json({"transition": transition, "project": DEPLOYMENTS.get(project_id)}, HTTPStatus.CREATED)
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/routes"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/routes").strip("/"))
                route = DEPLOYMENTS.save_route(project_id, data)
                self._json({"route": route, "project": DEPLOYMENTS.get(project_id)}, HTTPStatus.CREATED)
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/scene-model"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/scene-model").strip("/"))
                self._json({"project": DEPLOYMENTS.set_scene_model(project_id, data.get("scene_model"))})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/deployment-flow"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/deployment-flow").strip("/"))
                project = DEPLOYMENTS.set_deployment_flow(project_id, data.get("flow"))
                self._json({"project": project, "stage_plan": DEPLOYMENTS.stage_plan(project_id)})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/map-instances"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/map-instances").strip("/"))
                instance = DEPLOYMENTS.add_map_instance(project_id, data)
                self._json({"map_instance": instance, "project": DEPLOYMENTS.get(project_id)}, HTTPStatus.CREATED)
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/waypoints/" in path:
            try:
                parts = path.split("/")
                if len(parts) != 6 or parts[4] != "waypoints":
                    raise DeploymentError("部署 Waypoint 路径无效")
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                waypoint = DEPLOYMENTS.update_waypoint(unquote(parts[3]), unquote(parts[5]), data)
                self._json({"waypoint": waypoint, "project": DEPLOYMENTS.get(unquote(parts[3]))})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/waypoints"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/waypoints").strip("/"))
                waypoint = DEPLOYMENTS.add_waypoint(project_id, data)
                self._json({"waypoint": waypoint, "project": DEPLOYMENTS.get(project_id)}, HTTPStatus.CREATED)
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/component-templates"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/component-templates").strip("/"))
                if data.get("action") == "add":
                    project = DEPLOYMENTS.add_component_protocol(project_id, data.get("category"), data.get("label"))
                elif data.get("action") == "remove":
                    project = DEPLOYMENTS.remove_component_protocol(project_id, data.get("category"), data.get("protocol_id"))
                else:
                    raise DeploymentError("协议模板操作无效")
                self._json({"project": project})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/map-edits"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/map-edits").strip("/"))
                self._json({"project": DEPLOYMENTS.update_map_edits(project_id, data)})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/components"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/components").strip("/"))
                component = DEPLOYMENTS.add_component(project_id, data)
                self._json({"component": component, "project": DEPLOYMENTS.get(project_id)}, HTTPStatus.CREATED)
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/physical-elevators"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/physical-elevators").strip("/"))
                elevator = DEPLOYMENTS.add_physical_elevator(project_id, data)
                self._json({"physical_elevator": elevator, "project": DEPLOYMENTS.get(project_id)}, HTTPStatus.CREATED)
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/physical-elevators/" in path:
            try:
                parts = path.split("/")
                if len(parts) != 6 or parts[4] != "physical-elevators": raise DeploymentError("物理电梯路径无效")
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(parts[3])
                elevator = DEPLOYMENTS.update_physical_elevator(project_id, unquote(parts[5]), data)
                self._json({"physical_elevator": elevator, "project": DEPLOYMENTS.get(project_id)})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/components/" in path:
            try:
                parts = path.split("/")
                if len(parts) != 6 or parts[4] != "components": raise DeploymentError("组件路径无效")
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(parts[3]); component = DEPLOYMENTS.update_component(project_id, unquote(parts[5]), data)
                self._json({"component": component, "project": DEPLOYMENTS.get(project_id)})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/virtual-walls/" in path:
            try:
                parts = path.split("/")
                if len(parts) != 6 or parts[4] != "virtual-walls":
                    raise DeploymentError("虚拟墙路径无效")
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(parts[3])
                wall = DEPLOYMENTS.update_virtual_wall(project_id, unquote(parts[5]), data)
                self._json({"virtual_wall": wall, "project": DEPLOYMENTS.get(project_id)})
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and path.endswith("/virtual-walls"):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                project_id = unquote(path.removeprefix("/api/deployments/").removesuffix("/virtual-walls").strip("/"))
                wall = DEPLOYMENTS.add_virtual_wall(project_id, data)
                self._json({"virtual_wall": wall, "project": DEPLOYMENTS.get(project_id)}, HTTPStatus.CREATED)
            except (TypeError, ValueError, json.JSONDecodeError, DeploymentError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
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
        if path == "/api/software-inventory":
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                self._json(SOFTWARE_INVENTORY.save(data))
            except SoftwareInventoryUnavailable as exc:
                self._json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
            except (SoftwareInventoryError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/settings":
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if isinstance(data, dict) and "vehicle_control" in data:
                    raise ValueError("底盘控制参数只能通过手动控制页的受控接口保存")
                if not isinstance(data, dict):
                    raise ValueError("配置请求必须是 JSON 对象")
                requested_autostart = data.pop("autostart_enabled", None)
                if requested_autostart is not None:
                    autostart = AUTOSTART.apply(requested_autostart)
                    data["autostart_enabled"] = bool(autostart["enabled"])
                settings = SETTINGS.save(data)
                self._json(self._settings(settings))
            except (AutostartError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
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
            if VEHICLE_CONTROL.has_control_session():
                self._json({"error": "请先退出手动控制，再继续验收"}, HTTPStatus.CONFLICT)
                return
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
            if VEHICLE_CONTROL.has_control_session():
                raise RuntimeError("Aletheia 手动控制会话仍存在或正在切换，不能同时启动自动化测试")
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            case = STORE.get_case(str(data["caseId"]))
            if not case:
                raise ValueError("未找到指定测试用例，请刷新列表后重试")
            run = RUNS.start(
                case, int(data.get("count", 1)), float(data.get("intervalSeconds", 3)), True,
                bag_recording=data.get("bagRecording"),
            )
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
                if SCENARIO_ACTIVATIONS.is_active():
                    raise ScenarioSetupError("场景方案正在应用，请等待运行依赖确认完成")
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
                operation = SCENARIO_ACTIVATIONS.start(str(data.get("profile_id", "")), data.get("document"))
                self._json({"operation": operation}, HTTPStatus.ACCEPTED)
                return
            elif action == "restore":
                if RUNS.has_active_run():
                    raise ScenarioSetupError("存在执行中测试计划，不能恢复启动配置")
                if SCENARIO_ACTIVATIONS.is_active():
                    raise ScenarioSetupError("场景方案正在应用，请等待运行依赖确认完成")
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
            elif path == "/api/observation/relocalization/begin":
                payload = MANUAL_RELOCALIZATION.begin(settings)
            elif path == "/api/observation/relocalization/apply":
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length < 2 or content_length > 16 * 1024:
                    raise ValueError("重定位请求大小无效")
                data = json.loads(self.rfile.read(content_length))
                if not isinstance(data, dict):
                    raise ValueError("重定位请求必须是 JSON 对象")
                if set(data) - {"x", "y", "yaw", "config_path", "source_map_id", "request_id"}:
                    raise ManualRelocalizationError("重定位请求包含不支持的字段")
                values = {key: data.get(key) for key in ("x", "y", "yaw")}
                if "config_path" in data:
                    values["config_path"] = data["config_path"]
                if "source_map_id" in data:
                    values["source_map_id"] = data["source_map_id"]
                if "request_id" in data:
                    values["request_id"] = data["request_id"]
                payload = MANUAL_RELOCALIZATION.apply(settings, values)
            elif path == "/api/observation/relocalization/cancel":
                payload = MANUAL_RELOCALIZATION.cancel()
            elif path == "/api/observation/relocalization/resolve":
                content_length = int(self.headers.get("Content-Length", 0))
                if not 2 <= content_length <= 1024:
                    raise ManualRelocalizationError("重定位请求大小无效")
                data = json.loads(self.rfile.read(content_length))
                if not isinstance(data, dict) or set(data) != {"request_id"}:
                    raise ManualRelocalizationError("重定位结果查询格式无效")
                payload = MANUAL_RELOCALIZATION.resolve_operation(data["request_id"])
            elif path == "/api/observation/relocalization/recover-navigation":
                payload = MANUAL_RELOCALIZATION.recover_navigation()
            elif path == "/api/observation/map-markers":
                content_length = int(self.headers.get("Content-Length", 0))
                if not 2 <= content_length <= 16 * 1024:
                    raise ValueError("地图标记请求大小无效")
                data = json.loads(self.rfile.read(content_length))
                if not isinstance(data, dict) or set(data) != {"alias", "x", "y", "yaw"}:
                    raise ValueError("地图标记请求格式无效")
                active_map_id = OBSERVATION.active_manual_map_id()
                if active_map_id is None:
                    raise ValueError("当前地图尚未确认")
                point = MAP_MARKERS.create(active_map_id, **data)
                LOGGER.info("地图标记已创建：id=%s", point["id"])
                payload = {"ok": True, "point": point}
            elif path == "/api/observation/map-markers/remove":
                content_length = int(self.headers.get("Content-Length", 0))
                if not 2 <= content_length <= 16 * 1024:
                    raise ValueError("地图标记请求大小无效")
                data = json.loads(self.rfile.read(content_length))
                if not isinstance(data, dict) or set(data) != {"id"}:
                    raise ValueError("地图标记请求格式无效")
                active_map_id = OBSERVATION.active_manual_map_id()
                if active_map_id is None:
                    raise ValueError("当前地图尚未确认")
                marker_id = str(data["id"])
                MAP_MARKERS.remove(active_map_id, marker_id)
                LOGGER.info("地图标记已删除：id=%s", marker_id)
                payload = {"ok": True}
            elif path == "/api/observation/map-marker-navigation/begin":
                content_length = int(self.headers.get("Content-Length", 0))
                if not 2 <= content_length <= 16 * 1024:
                    raise ValueError("前往地图标记请求大小无效")
                data = json.loads(self.rfile.read(content_length))
                if not isinstance(data, dict) or set(data) != {"id"}:
                    raise ValueError("前往地图标记请求格式无效")
                payload = MAP_MARKER_NAVIGATION.begin_marker(str(data["id"]))
            elif path == "/api/observation/map-marker-navigation/cancel":
                payload = MAP_MARKER_NAVIGATION.cancel()
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
            pending = payload.get("phase") in {"switching_to_miniapp", "calling_service", "switching_to_navigation"}
            self._json(payload, HTTPStatus.ACCEPTED if pending else HTTPStatus.OK)
        except ManualRelocalizationUnavailable as exc:
            LOGGER.warning("手动重定位服务不可用：%s", exc)
            self._json({"error": str(exc), "status": MANUAL_RELOCALIZATION.status(settings)}, HTTPStatus.SERVICE_UNAVAILABLE)
        except ManualRelocalizationConflict as exc:
            LOGGER.warning("手动重定位被安全策略拒绝：%s", exc)
            self._json({"error": str(exc), "status": MANUAL_RELOCALIZATION.status(settings)}, HTTPStatus.CONFLICT)
        except ManualRelocalizationError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except MapMarkerNavigationUnavailable as exc:
            self._json({"error": str(exc), "status": MAP_MARKER_NAVIGATION.status()}, HTTPStatus.SERVICE_UNAVAILABLE)
        except MapMarkerNavigationConflict as exc:
            self._json({"error": str(exc), "status": MAP_MARKER_NAVIGATION.status()}, HTTPStatus.CONFLICT)
        except MapMarkerNavigationError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except (ObservationError, TypeError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.warning("实时观测操作被拒绝：%s", exc)
            self._json({"error": str(exc)}, HTTPStatus.CONFLICT)

    @audit_request
    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/tool-logs/retention":
            self._manage_tool_log("PUT", path)
            return
        if path == "/api/robot-logs/sources":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= content_length <= 16 * 1024:
                    raise RobotLogError("机器人日志配置请求大小无效")
                payload = json.loads(self.rfile.read(content_length))
                if not isinstance(payload, dict) or set(payload) != {"sources"}:
                    raise RobotLogError("机器人日志配置格式错误")
                ROBOT_LOGS.save_sources(payload["sources"])
                self._json({"sources": ROBOT_LOGS.sources()})
            except (TypeError, ValueError, json.JSONDecodeError, RobotLogError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path != "/api/acceptance/criteria":
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            data = self._acceptance_payload()
            self._json(ACCEPTANCE.save_criteria(data))
        except AcceptanceValidationError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _acceptance_payload(self) -> dict:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise AcceptanceValidationError("请求长度无效") from exc
        if not 0 <= content_length <= 16 * 1024:
            raise AcceptanceValidationError("部署验收请求大小无效")
        try:
            payload = json.loads(self.rfile.read(content_length) if content_length else b"{}")
        except json.JSONDecodeError as exc:
            raise AcceptanceValidationError("部署验收请求必须是 JSON") from exc
        if not isinstance(payload, dict):
            raise AcceptanceValidationError("部署验收请求必须是 JSON 对象")
        return payload

    def _acceptance_action(self, path: str) -> None:
        try:
            data = self._acceptance_payload()
            if path == "/api/acceptance/plans":
                self._json({"plan": ACCEPTANCE.create_plan(data)}, HTTPStatus.CREATED)
                return
            match = re.fullmatch(r"/api/acceptance/plans/([0-9a-f]{12})/(start|resume|cancel|reroll|resolve-interruption)", path)
            if not match:
                self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
            plan_id, action = match.groups()
            if action == "start":
                payload, status = ACCEPTANCE.start(plan_id), HTTPStatus.ACCEPTED
            elif action == "resume":
                payload, status = ACCEPTANCE.resume(plan_id), HTTPStatus.ACCEPTED
            elif action == "cancel":
                payload, status = ACCEPTANCE.cancel(plan_id), HTTPStatus.ACCEPTED
            elif action == "resolve-interruption":
                payload, status = ACCEPTANCE.resolve_interruption(plan_id, str(data.get("resolution", ""))), HTTPStatus.OK
            else:
                raise AcceptanceValidationError("重新抽样仅允许在生成新计划时进行")
            self._json({"plan": payload}, status)
        except AcceptanceConflict as exc:
            self._json({"error": str(exc), "plan": ACCEPTANCE.current()}, HTTPStatus.CONFLICT)
        except AcceptanceValidationError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _acceptance_report(self, plan_id: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{12}", plan_id):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        plan = ACCEPTANCE.current()
        if not plan or plan["plan_id"] != plan_id or not isinstance(plan.get("report_filename"), str):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        filename = plan["report_filename"]
        if not re.fullmatch(r"acceptance_[0-9a-f]{12}_\d{8}_\d{6}\.html", filename):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        target = (WORKSPACE / "reports" / filename).resolve()
        if target.parent != (WORKSPACE / "reports").resolve() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _vehicle_control_action(self, path: str) -> None:
        """HTTP 层只验证请求并调用控制器；不直接接触 ROS publisher 或定时器。"""
        try:
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("请求长度无效") from exc
            if not 0 <= content_length <= 16 * 1024:
                raise ValueError("手动控制请求大小无效")
            raw = self.rfile.read(content_length) if content_length else b"{}"
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("手动控制请求必须是 JSON 对象")
            if path == "/api/vehicle-control/enter":
                payload = VEHICLE_CONTROL.begin_manual_session()
            elif path == "/api/vehicle-control/navigation":
                payload = VEHICLE_CONTROL.request_navigation()
            elif path == "/api/vehicle-control/heartbeat":
                payload = VEHICLE_CONTROL.heartbeat(str(data.get("session_id", "")))
            elif path == "/api/vehicle-control/command":
                session_id = str(data.get("session_id", ""))
                command = str(data.get("command", ""))
                payload = VEHICLE_CONTROL.stop(session_id) if command == "stop" else VEHICLE_CONTROL.set_command(session_id, command)
            elif path == "/api/vehicle-control/vector":
                payload = VEHICLE_CONTROL.set_vector(
                    str(data.get("session_id", "")),
                    data.get("linear_ratio"),
                    data.get("angular_ratio"),
                    data.get("input_sequence"),
                )
            elif path == "/api/vehicle-control/speed":
                payload = VEHICLE_CONTROL.set_speed(
                    str(data.get("session_id", "")),
                    data.get("linear_speed"),
                    data.get("angular_speed"),
                )
            elif path == "/api/vehicle-control/stop":
                payload = VEHICLE_CONTROL.stop(str(data.get("session_id", "")))
            elif path == "/api/vehicle-control/release":
                payload = VEHICLE_CONTROL.release_manual_session(str(data.get("session_id", "")))
            elif path == "/api/vehicle-control/exit":
                payload = VEHICLE_CONTROL.end_manual_session(str(data.get("session_id", "")))
            elif path == "/api/vehicle-control/release-emergency-stop":
                payload = VEHICLE_CONTROL.release_emergency_stop()
            elif path == "/api/vehicle-control/chassis-parameters":
                parameters = VEHICLE_CONTROL.normalize_chassis_parameters(data)
                settings = SETTINGS.save({"vehicle_control": parameters})
                payload = VEHICLE_CONTROL.update_chassis_parameters(settings.vehicle_control)
            else:
                self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
            waiting_release = payload.get("emergency_stop", {}).get("release") == "waiting_confirmation"
            status = HTTPStatus.ACCEPTED if payload.get("transition") or waiting_release else HTTPStatus.OK
            self._json(payload, status)
        except VehicleControlUnavailable as exc:
            self._json({"error": str(exc), "status": VEHICLE_CONTROL.status()}, HTTPStatus.SERVICE_UNAVAILABLE)
        except VehicleControlConflict as exc:
            payload = {"error": str(exc), "status": VEHICLE_CONTROL.status()}
            if getattr(exc, "code", None):
                payload["code"] = exc.code
            self._json(payload, HTTPStatus.CONFLICT)
        except (VehicleControlError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

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

    def _deployment_map_preview(self, project_id: str, map_id: str) -> None:
        try:
            width, height, pixels = _read_pgm(DEPLOYMENTS.map_image(project_id, map_id))
            body = _png_gray(width, height, pixels)
        except (DeploymentError, OSError, ValueError) as exc:
            self.send_error(HTTPStatus.NOT_FOUND, str(exc))
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _projection_payload(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise MapProjectionError("请求长度无效") from exc
        if not 1 <= length <= 16 * 1024:
            raise MapProjectionError("地图预览请求大小无效")
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError) as exc:
            raise MapProjectionError("地图预览请求必须是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise MapProjectionError("地图预览请求必须是 JSON 对象")
        return payload

    def _map_projection_request(self, method: str, path: str, query: str = "") -> None:
        match = re.fullmatch(r"/api/deployments/([^/]+)/map-projections(?:/([^/]+))?(?:/(preview|confirm|preview\.png|source-preview\.bin|source-detail\.bin|trajectory-preview\.bin))?", path)
        if not match:
            self._json({"error": "地图生成请求路径无效"}, HTTPStatus.NOT_FOUND)
            return
        project, job, action = match.groups()
        project = unquote(project)
        job = unquote(job) if job else None
        try:
            if method == "POST" and job is None:
                self._upload_map_projection(project)
                return
            if method == "GET" and job == "latest" and action is None:
                self._json({"projection": MAP_PROJECTIONS.latest(project)})
                return
            if job and job != "latest":
                if method == "POST" and action == "trajectory-preview.bin":
                    if query:
                        raise MapProjectionError("轨迹预览请求不接受查询参数")
                    MAP_PROJECTIONS.get(project, job)
                    self._upload_map_projection(project, trajectory_job=job)
                    return
                if method == "GET" and action is None:
                    self._json({"projection": MAP_PROJECTIONS.get(project, job)})
                    return
                if method == "GET" and action == "preview.png":
                    options = parse_qs(query, keep_blank_values=True, strict_parsing=True, max_num_fields=3)
                    if set(options) - {"revision", "display"}:
                        raise MapProjectionError("地图预览查询参数无效")
                    display = options.get("display")
                    if display is not None and display != ["monochrome"]:
                        raise MapProjectionError("地图预览显示模式无效")
                    values = options.get("revision", [])
                    if len(values) != 1 or not re.fullmatch(r"[1-9][0-9]{0,8}", values[0]):
                        raise MapProjectionError("请指定当前地图预览版本")
                    source = MAP_PROJECTIONS.preview_path(project, job, int(values[0]))
                    width, height, pixels = _read_pgm(source)
                    if display is not None:
                        pixels = pixels.translate(bytes([0] + [255] * 255))
                    body = _png_gray(width, height, pixels)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if method == "GET" and action in {"source-preview.bin", "source-detail.bin"}:
                    if query:
                        raise MapProjectionError("点云样本请求不接受查询参数")
                    sample = (MAP_PROJECTIONS.source_detail(project, job) if action == "source-detail.bin"
                              else MAP_PROJECTIONS.source_preview(project, job))
                    if sample is None:
                        self._json({"state": "preparing"}, HTTPStatus.ACCEPTED)
                        return
                    body, metadata = sample
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    for header, key in (("X-Point-Count", "point_count"),
                                        ("X-Source-Point-Count", "source_point_count"),
                                        ("X-Finite-Point-Count", "finite_point_count")):
                        self.send_header(header, str(metadata[key]))
                    self.send_header("X-Point-Origin", json.dumps(metadata["origin"], separators=(",", ":"), allow_nan=False))
                    self.send_header("X-Point-Bounds", json.dumps(metadata["bounds"], separators=(",", ":"), allow_nan=False))
                    if action == "source-detail.bin":
                        self.send_header("X-Point-Format", metadata["format"])
                        self.send_header("X-Point-Attributes", json.dumps(metadata["attributes"], separators=(",", ":"), allow_nan=False))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if method == "POST" and action == "preview":
                    projection = MAP_PROJECTIONS.preview(project, job, self._projection_payload())
                    self._json({"projection": projection}, HTTPStatus.ACCEPTED)
                    return
                if method == "POST" and action == "confirm":
                    payload = self._projection_payload()
                    if set(payload) != {"label", "revision"}:
                        raise MapProjectionError("确认地图仅接受名称和当前预览版本")
                    asset = MAP_PROJECTIONS.confirm(project, job, payload["label"], payload["revision"])
                    self._json({"map": asset, "project": DEPLOYMENTS.get(project)}, HTTPStatus.CREATED)
                    return
                if method == "DELETE" and action is None:
                    self._json({"projection": MAP_PROJECTIONS.cancel(project, job)})
                    return
            self._json({"error": "地图生成请求不存在"}, HTTPStatus.NOT_FOUND)
        except MapProjectionConflict as exc:
            self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
        except (MapProjectionError, DeploymentError, OSError, ValueError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _upload_map_projection(self, project_id: str, *, trajectory_job=None) -> None:
        # Validate ownership before consuming a potentially large upload.
        DEPLOYMENTS.get(project_id)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise MapProjectionError("上传长度无效") from exc
        content_type = self.headers.get("Content-Type", "")
        if not 1 <= length <= MAX_MAP_UPLOAD_BYTES:
            raise MapProjectionError("地图上传大小无效或超过 2 GiB 限制")
        if not content_type.startswith("multipart/form-data"):
            raise MapProjectionError("请选择一份 PCD 文件上传")
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={
            "REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type, "CONTENT_LENGTH": str(length),
        })
        if set(form.keys()) != {"file"} or isinstance(form["file"], list):
            raise MapProjectionError("请只上传一份 PCD 文件")
        item = form["file"]
        name = str(item.filename or "")
        if not name or name != Path(name).name or "\\" in name or Path(name).suffix.lower() != ".pcd" or len(name) > 180:
            raise MapProjectionError("请选择文件名有效的 PCD 文件")
        staging = DEPLOYMENTS.root / ".map-projection-uploads"
        staging.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="pcd-", dir=staging) as directory:
            source = Path(directory) / name
            written = 0
            with source.open("xb") as output:
                while chunk := item.file.read(1024 * 1024):
                    written += len(chunk)
                    if written > DeploymentStore.MAX_MAP_BYTES:
                        raise MapProjectionError("点云文件超过 2 GiB 限制")
                    output.write(chunk)
            if not written:
                raise MapProjectionError("点云文件为空")
            if trajectory_job:
                body, metadata = MAP_PROJECTIONS.trajectory_preview(project_id, trajectory_job, source)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Point-Format", metadata['format'])
                self.send_header("X-Point-Count", str(metadata['point_count']))
                self.send_header("X-Point-Origin", json.dumps(metadata['origin'], separators=(',', ':'), allow_nan=False))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"projection": MAP_PROJECTIONS.create(project_id, source)}, HTTPStatus.ACCEPTED)

    def _mapping_preview(self, session_id: str) -> None:
        try:
            width, height, pixels = _read_pgm(MAPPING.preview_pgm(session_id))
            body = _png_gray(width, height, pixels)
        except (MappingError, OSError, ValueError) as exc:
            self.send_error(HTTPStatus.NOT_FOUND, str(exc))
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        # Revisions are appended by the client; never cache a running map.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _observation_map_layers(self, asset_id: str) -> None:
        try:
            self._json(OBSERVATION.layers(asset_id))
        except ObservationError as exc:
            self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)

    @staticmethod
    def _uploaded_relative_path(value: str) -> Path:
        """Validate a browser-supplied directory upload path before staging it."""
        candidate = PurePosixPath(value.replace("\\", "/"))
        if not value or candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
            raise DeploymentError("上传文件路径不安全")
        return Path(*candidate.parts)

    def _upload_deployment_map(self, project_id: str) -> None:
        """Receive a browser-selected map directory and snapshot it into a project."""
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        content_type = self.headers.get("Content-Type", "")
        if not 1 <= content_length <= MAX_MAP_UPLOAD_BYTES:
            self._json({"error": "地图上传大小无效或超过 2 GiB 限制"}, HTTPStatus.BAD_REQUEST)
            return
        if not content_type.startswith("multipart/form-data"):
            self._json({"error": "地图导入必须使用浏览器文件夹上传"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type, "CONTENT_LENGTH": str(content_length)},
            )
            raw_files = form["files"] if "files" in form else []
            files = raw_files if isinstance(raw_files, list) else [raw_files]
            source_relative = self._uploaded_relative_path(str(form.getfirst("map_yaml", "")))
            label = form.getfirst("label", "")
            kind = form.getfirst("kind", "custom")
            if not files:
                raise DeploymentError("请选择包含 map.yaml 与 PGM 的地图文件夹")
            staging_parent = DEPLOYMENTS.root / ".map-uploads"
            staging_parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="browser-map-", dir=staging_parent) as directory:
                root = Path(directory)
                written = 0
                seen: set[Path] = set()
                for item in files:
                    if not getattr(item, "filename", None) or not getattr(item, "file", None):
                        continue
                    relative = self._uploaded_relative_path(str(item.filename))
                    if relative in seen:
                        raise DeploymentError("地图文件夹中存在重名文件")
                    seen.add(relative)
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as output:
                        while chunk := item.file.read(1024 * 1024):
                            written += len(chunk)
                            if written > DeploymentStore.MAX_MAP_BYTES:
                                raise DeploymentError("地图资产超过 2 GiB 导入上限")
                            output.write(chunk)
                source = root / source_relative
                asset = DEPLOYMENTS.import_uploaded_map(project_id, source, label, kind, root)
                self._json({"map": asset, "project": DEPLOYMENTS.get(project_id)}, HTTPStatus.CREATED)
        except (DeploymentError, OSError, ValueError, KeyError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _upload_mapping_template(self, project_id: str) -> None:
        """Stage exactly one browser-selected mapping YAML inside its project.

        Unlike an old path-input workflow this never reads from /opt/ry or any
        other robot configuration directory.  The following mapping session
        receives only the stored tool-owned copy.
        """
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        content_type = self.headers.get("Content-Type", "")
        if not 1 <= content_length <= MAX_MAPPING_TEMPLATE_BYTES:
            self._json({"error": "建图模板大小无效或超过 2 MiB 限制"}, HTTPStatus.BAD_REQUEST)
            return
        if not content_type.startswith("multipart/form-data"):
            self._json({"error": "建图模板必须从浏览器本机文件选择器上传"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            DEPLOYMENTS.get(project_id)
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type, "CONTENT_LENGTH": str(content_length)},
            )
            item = form["template"] if "template" in form else None
            if item is None or isinstance(item, list) or not getattr(item, "filename", None) or not getattr(item, "file", None):
                raise MappingError("请选择一个 YAML 建图模板文件")
            contents = item.file.read(MAX_MAPPING_TEMPLATE_BYTES + 1)
            template = MAPPING.store_template(project_id, str(item.filename), contents)
            self._json({"template": template}, HTTPStatus.CREATED)
        except (DeploymentError, MappingError, OSError, ValueError, KeyError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _upload_localization_template(self, project_id: str) -> None:
        """Store one operator-selected localization YAML in the project workspace."""
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        content_type = self.headers.get("Content-Type", "")
        if not 1 <= content_length <= 2 * 1024 * 1024:
            self._json({"error": "定位配置模板大小无效或超过 2 MiB 限制"}, HTTPStatus.BAD_REQUEST)
            return
        if not content_type.startswith("multipart/form-data"):
            self._json({"error": "定位配置模板必须从浏览器本机文件选择器上传"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            DEPLOYMENTS.get(project_id)
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type, "CONTENT_LENGTH": str(content_length)},
            )
            item = form["template"] if "template" in form else None
            if item is None or isinstance(item, list) or not getattr(item, "filename", None) or not getattr(item, "file", None):
                raise DeploymentError("请选择一个定位配置 YAML 模板文件")
            contents = item.file.read(2 * 1024 * 1024 + 1)
            template = DEPLOYMENTS.upload_localization_template(project_id, str(item.filename), contents)
            self._json({"template": template, "project": DEPLOYMENTS.get(project_id)}, HTTPStatus.CREATED)
        except (DeploymentError, OSError, ValueError, KeyError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

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

    @staticmethod
    def _task_compiler_project_id(path: str, suffix: str) -> str:
        """Extract one project id without allowing a nested client path."""
        prefix = "/api/deployments/"
        if not path.startswith(prefix) or not path.endswith(suffix):
            raise DeploymentError("任务编译器路径无效")
        project_id = unquote(path[len(prefix):-len(suffix)])
        if not project_id or "/" in project_id:
            raise DeploymentError("任务编译器项目标识无效")
        return project_id

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

    def _delete_case(self, case_id: str) -> dict[str, str]:
        """Delete one inactive local case and retire only its local references."""
        if RUNS.has_active_run():
            raise CasePackageError("测试任务正在执行，不能删除用例")
        case = STORE.get_case(case_id)
        if not case:
            raise CasePackageError("未找到指定测试用例")

        # Clear optional local references before the irreversible task deletion.
        # None of these operations can alter the task payload or robot runtime.
        SCENARIO_SETUP.bind_case(case.id, "")
        settings = SETTINGS.load()
        aliases = dict(settings.case_aliases)
        aliases.pop(case.id, None)
        SETTINGS.save({"case_aliases": aliases})
        CASE_WORKSPACE.remove(case)
        STORE.delete_case(case.id)
        LOGGER.info("已删除测试用例：%s", case.filename)
        return {"id": case.id, "filename": case.filename}

    @audit_request
    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/tool-logs/files/"):
            self._manage_tool_log("DELETE", path)
            return
        if path.startswith("/api/deployments/") and "/map-projections" in path:
            self._map_projection_request("DELETE", path)
            return
        if match := re.fullmatch(r"/api/bag-recordings/([0-9a-f]{32})", path):
            try:
                BAG_RECORDINGS.delete_archive(match.group(1))
                self._json({"deleted": True})
            except BagRecordingError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/cases/"):
            case_id = unquote(path.removeprefix("/api/cases/").rstrip("/"))
            if not case_id or "/" in case_id or "\\" in case_id:
                self._json({"error": "用例路径无效"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                case = self._delete_case(case_id)
                self._json({"message": "用例已删除", "case": case})
            except CasePackageError as exc:
                status = HTTPStatus.CONFLICT if "正在执行" in str(exc) else HTTPStatus.NOT_FOUND
                self._json({"error": str(exc)}, status)
            except ValueError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except OSError as exc:
                LOGGER.error("删除测试用例失败：%s", exc)
                self._json({"error": f"删除用例失败：{exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path.startswith("/api/deployments/"):
            parts = path.split("/")
            if len(parts) == 4 and parts[:3] == ["", "api", "deployments"] and parts[3]:
                try:
                    DEPLOYMENTS.delete_project(unquote(parts[3]))
                    self._json({"deleted": True})
                except DeploymentError as exc:
                    self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
                return
        if path.startswith("/api/deployments/") and "/transitions/" in path:
            try:
                parts = path.split("/")
                if len(parts) != 6 or parts[4] != "transitions":
                    raise DeploymentError("Transition 路径无效")
                DEPLOYMENTS.delete_map_transition(unquote(parts[3]), unquote(parts[5]))
                self._json({"deleted": True})
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/routes/" in path:
            try:
                parts = path.split("/")
                if len(parts) != 6 or parts[4] != "routes":
                    raise DeploymentError("路线路径无效")
                DEPLOYMENTS.delete_route(unquote(parts[3]), unquote(parts[5]))
                self._json({"deleted": True})
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/components/" in path:
            try:
                parts = path.split("/")
                if len(parts) != 6 or parts[4] != "components": raise DeploymentError("组件路径无效")
                DEPLOYMENTS.delete_component(unquote(parts[3]), unquote(parts[5]))
                self._json({"deleted": True})
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/virtual-walls/" in path:
            try:
                parts = path.split("/")
                if len(parts) != 6 or parts[4] != "virtual-walls":
                    raise DeploymentError("虚拟墙路径无效")
                project_id = unquote(parts[3])
                DEPLOYMENTS.delete_virtual_wall(project_id, unquote(parts[5]))
                self._json({"deleted": True, "project": DEPLOYMENTS.get(project_id)})
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/physical-elevators/" in path:
            try:
                parts = path.split("/")
                if len(parts) != 6 or parts[4] != "physical-elevators":
                    raise DeploymentError("物理电梯路径无效")
                DEPLOYMENTS.delete_physical_elevator(unquote(parts[3]), unquote(parts[5]))
                self._json({"deleted": True})
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/task-lines/" in path:
            try:
                parts = path.split("/")
                if len(parts) != 6 or parts[4] != "task-lines":
                    raise DeploymentError("任务线路路径无效")
                project_id = unquote(parts[3])
                DEPLOYMENTS.delete_task_line(project_id, unquote(parts[5]))
                self._json({"project": DEPLOYMENTS.get(project_id)})
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/localization-bindings/" in path:
            try:
                parts = path.split("/")
                if len(parts) != 6 or parts[4] != "localization-bindings":
                    raise DeploymentError("定位绑定路径无效")
                DEPLOYMENTS.delete_localization_binding(unquote(parts[3]), unquote(parts[5]))
                self._json({"deleted": True})
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/localization-routes/" in path:
            try:
                raise DeploymentError("定位路线由系统自动派生，不能人工删除")
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/deployments/") and "/waypoints/" in path:
            try:
                parts = path.split("/")
                if len(parts) != 6 or parts[4] != "waypoints":
                    raise DeploymentError("部署 Waypoint 路径无效")
                DEPLOYMENTS.delete_waypoint(unquote(parts[3]), unquote(parts[5]))
                self._json({"deleted": True})
            except DeploymentError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
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
        autostart = AUTOSTART.status()
        autostart["enabled"] = bool(item.autostart_enabled and autostart["enabled"])
        if not autostart["enabled"]:
            autostart["mode"] = "none"
            autostart["message"] = "未启用开机自启"
        return {"task_directory": item.task_directory, "command_timeout_s": item.command_timeout_s, "elevator_wait_timeout_s": item.elevator_wait_timeout_s, "task_execution_timeout_s": item.task_execution_timeout_s, "case_aliases": item.case_aliases, "ui_preferences": item.ui_preferences, "dependency_plan": item.dependency_plan, "monitor_nodes": monitor_nodes, "live_observation": item.live_observation, "vehicle_control": item.vehicle_control, "autostart_enabled": bool(autostart["enabled"]), "autostart": autostart}

    @staticmethod
    def _native_report_archive() -> NativeReportArchive:
        """Bind each request to the current workspace (tests patch it)."""
        return NativeReportArchive(WORKSPACE / "reports")

    @staticmethod
    def _native_page_query(
        query: dict[str, list[str]],
        *,
        default_limit: int,
        maximum_limit: int,
        require_cursor: bool = False,
    ) -> tuple[str | None, int]:
        if set(query) - {"cursor", "limit"}:
            raise NativeReportArchiveError("原生报告查询参数无效")
        for name in ("cursor", "limit"):
            if len(query.get(name, [])) > 1:
                raise NativeReportArchiveError("原生报告查询参数无效")
        cursor_values = query.get("cursor", [])
        cursor = cursor_values[0] if cursor_values else None
        if require_cursor and not cursor:
            raise NativeReportArchiveError("分页标识无效")
        if cursor == "":
            raise NativeReportArchiveError("分页标识无效")
        raw_limit = query.get("limit", [None])[0]
        if raw_limit is None:
            return cursor, default_limit
        if not isinstance(raw_limit, str) or not re.fullmatch(r"[1-9][0-9]*", raw_limit):
            raise NativeReportArchiveError("分页数量无效")
        limit = int(raw_limit)
        if limit > maximum_limit:
            raise NativeReportArchiveError("分页数量无效")
        return cursor, limit

    def _native_report_route(self, path: str, query: dict[str, list[str]]) -> None:
        """Serve only fixed, report-scoped Mobile native-report resources."""
        detail = re.fullmatch(r"/api/reports/([^/]+)/native", path)
        trajectory = re.fullmatch(r"/api/reports/([^/]+)/native/trajectories/([^/]+)", path)
        map_png = re.fullmatch(r"/api/reports/([^/]+)/native/trajectories/([^/]+)/map\.png", path)
        samples = re.fullmatch(r"/api/reports/([^/]+)/native/trajectories/([^/]+)/samples", path)
        archive = self._native_report_archive()
        try:
            if detail:
                report_id = unquote(detail.group(1))
                cursor, limit = self._native_page_query(query, default_limit=50, maximum_limit=100)
                self._json(archive.detail_page(report_id, cursor, limit))
                return
            if trajectory:
                if query:
                    raise NativeReportArchiveError("原生报告查询参数无效")
                self._json(archive.trajectory(unquote(trajectory.group(1)), unquote(trajectory.group(2))))
                return
            if map_png:
                if query:
                    raise NativeReportArchiveError("原生报告查询参数无效")
                body = archive.trajectory_map_png(unquote(map_png.group(1)), unquote(map_png.group(2)))
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
                return
            if samples:
                report_id, trajectory_id = unquote(samples.group(1)), unquote(samples.group(2))
                cursor, limit = self._native_page_query(query, default_limit=1000, maximum_limit=1000, require_cursor=True)
                self._json(archive.sample_page(report_id, trajectory_id, cursor, limit))
                return
            raise NativeReportArchiveError("原生报告路径无效")
        except NativeReportNotFound as exc:
            self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except NativeReportArchiveError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    @staticmethod
    def _reports() -> list[dict]:
        report_dir = WORKSPACE / "reports"
        if not report_dir.is_dir():
            return []
        archive = NativeReportArchive(report_dir)
        records = []
        report_files = (target for target in report_dir.glob("*.html") if REPORT_FILENAME.fullmatch(target.name))
        for target in sorted(report_files, key=lambda item: item.stat().st_mtime, reverse=True):
            stat = target.stat()
            csv_target = target.with_suffix(".csv")
            is_acceptance = bool(ACCEPTANCE_REPORT_FILENAME.fullmatch(target.name))
            record = {
                "filename": target.name,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
                "csv_filename": csv_target.name if csv_target.is_file() else None,
                "report_type": "acceptance" if is_acceptance else "test",
                "title": "部署验收报告" if is_acceptance else "自动测试运行报告",
            }
            native = archive.summary_for_filename(target.name)
            if native is not None:
                record["native_report"] = native
            records.append(record)
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

    def _download_bag_archive(self, archive_id: str) -> None:
        """Stream one manifest-backed bag directory without accepting a path."""
        try:
            directory = BAG_RECORDINGS.archive_path(archive_id)
            filename = BAG_RECORDINGS.archive_download_name(archive_id)
        except BagRecordingError as exc:
            self.send_error(HTTPStatus.NOT_FOUND, str(exc))
            return
        if directory.is_symlink() or not directory.is_dir():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-tar")
        self.send_header("Content-Disposition", f"attachment; filename={filename}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            with tarfile.open(fileobj=self.wfile, mode="w|") as bundle:
                for target in sorted(directory.rglob("*")):
                    if target.is_symlink() or not target.is_file():
                        continue
                    resolved = target.resolve()
                    if not resolved.is_relative_to(directory):
                        continue
                    bundle.add(str(target), arcname=str(Path(filename).stem / target.relative_to(directory)), recursive=False)
        except (OSError, tarfile.TarError, BrokenPipeError):
            LOGGER.warning("诊断录包下载中断：archive=%s", archive_id)

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

    def _manage_tool_log(self, method: str, path: str) -> None:
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 2 <= length <= 4096:
                self.close_connection = True
                raise ValueError('日志管理请求大小无效')
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('日志管理请求格式无效')
            if method == 'PUT':
                if set(payload) != {'policy'}:
                    raise ValueError('日志保留设置格式无效')
                LOGS.save_policy(payload['policy'])
                result = LOGS.cleanup()
            else:
                if payload.get('confirm') is not True:
                    raise ValueError('请先确认日志清理操作')
                if path == '/api/tool-logs/cleanup':
                    if set(payload) != {'mode', 'confirm'} or payload['mode'] not in {'expired', 'history'}:
                        raise ValueError('日志整理范围无效')
                    result = LOGS.cleanup(history=payload['mode'] == 'history')
                else:
                    if set(payload) != {'file_id', 'confirm'}:
                        raise ValueError('日志文件确认信息无效')
                    name = unquote(path.removeprefix('/api/tool-logs/files/'))
                    if method == 'POST':
                        name = name.removesuffix('/clear')
                        result = LOGS.clear_file(name, payload['file_id'])
                    else:
                        result = LOGS.delete_file(name, payload['file_id'])
            LOGGER.info('工具日志管理完成：method=%s freed_bytes=%s', method, result.get('freed_bytes', 0))
            self._json({**result, 'storage': LOGS.storage_status()})
        except ToolLogConflict as exc:
            self._json({'error': str(exc)}, HTTPStatus.CONFLICT)
        except ToolLogMissing as exc:
            self._json({'error': str(exc)}, HTTPStatus.NOT_FOUND)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({'error': str(exc)}, HTTPStatus.BAD_REQUEST)
        except OSError:
            LOGGER.exception('工具日志管理失败')
            self._json({'error': '日志管理失败，请检查目录权限或剩余空间。'}, HTTPStatus.INTERNAL_SERVER_ERROR)

    @staticmethod
    def _copy_log_snapshot(source, output, size: int) -> None:
        remaining = size
        while remaining:
            chunk = source.read(min(64 * 1024, remaining))
            if not chunk:
                raise OSError('日志快照已改变')
            output.write(chunk)
            remaining -= len(chunk)

    def _stream_tool_log(self, source, size: int, filename: str, content_type='text/plain; charset=utf-8') -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Disposition', f'attachment; filename={filename}')
        self.send_header('Content-Length', str(size))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self._copy_log_snapshot(source, self.wfile, size)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
            audit = getattr(self, '_tool_audit', None)
            if audit is not None:
                audit.interrupted = True
        except OSError:
            self.close_connection = True
            audit = getattr(self, '_tool_audit', None)
            if audit is not None:
                audit.response(HTTPStatus.OK, {'error': '工具日志快照传输未完成'})
            LOGGER.warning('工具日志下载未完成：file=%s', filename)

    def _download_tool_log(self, errors_only: bool) -> None:
        if errors_only:
            target = LOGS.diagnostic_file(LOGS.ERROR_NAME)
            if target is None:
                self._stream_tool_log(io.BytesIO(), 0, 'ry-aletheia-error.log')
            else:
                self._download_diagnostic_file(target)
            return
        try:
            # Disk-backed staging bounds RAM even for a legacy gigabyte log.
            # Each file has a read lease and an opening-length snapshot.
            with tempfile.TemporaryFile(mode='w+b') as temporary:
                with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
                    files = LOGS.diagnostic_files()
                    if not files:
                        bundle.writestr('README.txt', '尚无 Aletheia 诊断日志。\n')
                    for target in files:
                        try:
                            with LOGS.open_diagnostic(target.name) as (source, size):
                                with bundle.open(target.name, 'w', force_zip64=True) as output:
                                    self._copy_log_snapshot(source, output, size)
                        except ToolLogMissing:
                            continue  # A history file may expire between list/open.
                size = temporary.tell()
                temporary.seek(0)
                self._stream_tool_log(temporary, size, 'ry-aletheia-diagnostics.zip', 'application/zip')
        except (OSError, ValueError):
            LOGGER.exception('工具诊断包生成失败')
            self._json({'error': '诊断包生成失败，请检查日志权限或临时空间。'}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _download_diagnostic_file(self, target: Path | None) -> None:
        """Download exactly one whitelisted diagnostic file, never a raw path."""
        if target is None:
            # BaseHTTPRequestHandler.send_error() 会把中文 reason phrase 写进
            # Latin-1 HTTP status line，反而抛 UnicodeEncodeError。API 统一用
            # UTF-8 JSON 返回受控错误，浏览器和日志页都能安全显示。
            self._json({"error": "诊断日志不存在"}, HTTPStatus.NOT_FOUND)
            return
        try:
            # Release the live-file lease before a slow Wi-Fi client receives
            # bytes. Network stalls must not pin an ever-growing active log.
            with tempfile.TemporaryFile(mode='w+b') as snapshot:
                with LOGS.open_diagnostic(target.name) as (source, size):
                    self._copy_log_snapshot(source, snapshot, size)
                snapshot.seek(0)
                self._stream_tool_log(snapshot, size, target.name)
        except (OSError, ValueError):
            self._json({"error": "诊断日志不可读"}, HTTPStatus.NOT_FOUND)

    def _download_tracked_robot_log_file(self, download_id: str) -> None:
        """Serve one short-lived browser download while exposing metadata-only progress."""
        try:
            tracked = ROBOT_LOG_DOWNLOADS.start(download_id)
        except RobotLogError as exc:
            self.send_error(HTTPStatus.NOT_FOUND, str(exc))
            return
        completed = self._download_robot_log_file(
            tracked.source_id,
            tracked.file_id,
            convert_ros_time=tracked.convert_ros_time,
            progress=lambda sent_bytes: ROBOT_LOG_DOWNLOADS.advance(download_id, sent_bytes),
            failed=lambda message: ROBOT_LOG_DOWNLOADS.fail(download_id, message),
        )
        if completed:
            ROBOT_LOG_DOWNLOADS.complete(download_id)
        else:
            audit = getattr(self, "_tool_audit", None)
            if audit is not None and audit.status < 400 and not audit.interrupted:
                audit.response(audit.status, {"error": "机器人日志下载未完成"})

    def _tail_robot_log_stdout(self, source_id: str, file_id: str) -> None:
        """Proxy one selected Supervisor stdout stream to its current browser.

        The browser supplies only opaque source/file identifiers.  The current
        filesystem identity is rechecked before the filename is matched to a
        process discovered from Supervisor; arbitrary process names and the
        protected Supervisor HTTP port are never exposed to the browser.
        """

        try:
            selected = ROBOT_LOGS.open_file(source_id, file_id)
        except RobotLogError as exc:
            self.send_error(HTTPStatus.NOT_FOUND, str(exc))
            return
        try:
            filename = selected.name
        finally:
            selected.stream.close()

        program_name = filename.removesuffix(".out.log")
        if program_name == filename or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", program_name):
            self.send_error(HTTPStatus.UNPROCESSABLE_ENTITY, "该日志不是可跟随的 Supervisor stdout 日志")
            return

        supervisor = SupervisorClient(SETTINGS.load().supervisor_command, SETTINGS.load().command_timeout_s)
        tail_token = None
        tail_process = None
        try:
            matching_processes = [
                process.name
                for process in supervisor.discover()
                if process.name.rsplit(":", 1)[-1] == program_name
            ]
            if len(matching_processes) != 1:
                raise RobotLogError("未找到对应的 Supervisor 进程")
            tail_token = ROBOT_LOG_TAILS.reserve()
            tail_process = supervisor.tail_stdout(matching_processes[0])
        except RobotLogError as exc:
            self.send_error(HTTPStatus.NOT_FOUND, str(exc))
            return
        except RuntimeError as exc:
            if tail_token is not None:
                ROBOT_LOG_TAILS.release(tail_token)
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
            return

        try:
            if tail_process.stdout is None:
                raise RuntimeError("Supervisor 日志跟随未提供 stdout")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            while True:
                chunk = tail_process.stdout.read(4096)
                if chunk:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    continue
                if tail_process.poll() is not None:
                    return_code = tail_process.poll()
                    if return_code:
                        LOGGER.error("Supervisor 日志跟随进程异常退出：source=%s file=%s returncode=%s", source_id, file_id, return_code)
                        audit = getattr(self, "_tool_audit", None)
                        if audit is not None:
                            audit.response(audit.status, {"error": "Supervisor 日志跟随进程异常退出"})
                    break
        except (BrokenPipeError, ConnectionResetError):
            # 切换/关闭一个实时卡片就是正常的流生命周期，不记录为服务错误。
            audit = getattr(self, "_tool_audit", None)
            if audit is not None:
                audit.interrupted = True
            pass
        except RuntimeError as exc:
            LOGGER.exception("Supervisor 日志跟随失败：source=%s file=%s error=%s", source_id, file_id, exc)
            audit = getattr(self, "_tool_audit", None)
            if audit is not None:
                audit.response(audit.status, {"error": str(exc)})
        finally:
            if tail_process is not None and tail_process.poll() is None:
                tail_process.terminate()
                try:
                    tail_process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    tail_process.kill()
                    tail_process.wait(timeout=1)
            if tail_token is not None:
                ROBOT_LOG_TAILS.release(tail_token)

    def _tail_robot_logs_stdout(self, streams: list[tuple[str, str]]) -> None:
        """Multiplex selected stdout followers into one browser connection.

        Browsers limit concurrent HTTP/1.1 connections per origin.  A separate
        long-poll for every visible card can therefore starve normal navigation;
        this endpoint keeps every Supervisor tail server-side but emits tagged
        NDJSON through a single, opaque-ID-only client stream.
        """

        tails: list[tuple[str, object, object]] = []
        try:
            supervisor = SupervisorClient(SETTINGS.load().supervisor_command, SETTINGS.load().command_timeout_s)
            for source_id, file_id in streams:
                selected = ROBOT_LOGS.open_file(source_id, file_id)
                try:
                    filename = selected.name
                finally:
                    selected.stream.close()
                program_name = filename.removesuffix(".out.log")
                if program_name == filename or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", program_name):
                    raise RobotLogError("该日志不是可跟随的 Supervisor stdout 日志")
                matching_processes = [
                    process.name
                    for process in supervisor.discover()
                    if process.name.rsplit(":", 1)[-1] == program_name
                ]
                if len(matching_processes) != 1:
                    raise RobotLogError("未找到对应的 Supervisor 进程")
                tail_token = ROBOT_LOG_TAILS.reserve()
                try:
                    tail_process = supervisor.tail_stdout(matching_processes[0])
                except RuntimeError:
                    ROBOT_LOG_TAILS.release(tail_token)
                    raise
                if tail_process.stdout is None:
                    ROBOT_LOG_TAILS.release(tail_token)
                    raise RuntimeError("Supervisor 日志跟随未提供 stdout")
                tails.append((f"{source_id}:{file_id}", tail_token, tail_process))
        except RobotLogError as exc:
            self.send_error(HTTPStatus.NOT_FOUND, str(exc))
            return
        except RuntimeError as exc:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
            return
        finally:
            if len(tails) != len(streams):
                for _, tail_token, tail_process in tails:
                    if tail_process.poll() is None:
                        tail_process.terminate()
                    ROBOT_LOG_TAILS.release(tail_token)

        events: queue.Queue[tuple[str, str | None]] = queue.Queue(maxsize=64)
        closed = threading.Event()

        def follow(stream_id: str, tail_process: object) -> None:
            try:
                while not closed.is_set():
                    chunk = tail_process.stdout.read(4096)
                    if chunk:
                        while not closed.is_set():
                            try:
                                events.put((stream_id, chunk.decode("utf-8", errors="replace")), timeout=0.2)
                                break
                            except queue.Full:
                                continue
                    elif tail_process.poll() is not None:
                        return_code = tail_process.poll()
                        if return_code:
                            LOGGER.error("Supervisor 合并日志跟随进程异常退出：stream=%s returncode=%s", stream_id, return_code)
                            audit = getattr(self, "_tool_audit", None)
                            if audit is not None:
                                audit.response(audit.status, {"error": "Supervisor 合并日志跟随进程异常退出"})
                        break
            except (OSError, RuntimeError):
                LOGGER.exception("Supervisor 合并日志跟随读取失败：stream=%s", stream_id)
                audit = getattr(self, "_tool_audit", None)
                if audit is not None:
                    audit.response(audit.status, {"error": "Supervisor 合并日志跟随读取失败"})
            finally:
                while not closed.is_set():
                    try:
                        events.put((stream_id, None), timeout=0.2)
                        break
                    except queue.Full:
                        continue

        workers = [threading.Thread(target=follow, args=(stream_id, tail_process), daemon=True) for stream_id, _, tail_process in tails]
        for worker in workers:
            worker.start()
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            remaining = len(workers)
            while remaining:
                stream_id, text = events.get()
                if text is None:
                    remaining -= 1
                    continue
                self.wfile.write((json.dumps({"stream": stream_id, "text": text}, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            audit = getattr(self, "_tool_audit", None)
            if audit is not None:
                audit.interrupted = True
            pass
        finally:
            closed.set()
            for _, tail_token, tail_process in tails:
                if tail_process.poll() is None:
                    tail_process.terminate()
                    try:
                        tail_process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        tail_process.kill()
                        tail_process.wait(timeout=1)
                ROBOT_LOG_TAILS.release(tail_token)

    def _download_robot_log_file(
        self,
        source_id: str,
        file_id: str,
        *,
        convert_ros_time: bool = False,
        progress=None,
        failed=None,
    ) -> bool:
        """Stream one revalidated robot log; never aggregate logs in memory or ZIPs."""
        try:
            download = ROBOT_LOGS.open_file(source_id, file_id)
        except RobotLogError as exc:
            self.send_error(HTTPStatus.NOT_FOUND, str(exc))
            if failed:
                failed(str(exc))
            return False
        safe_name = download.name if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,180}", download.name) else "robot-log.txt"
        disposition = f"attachment; filename={safe_name}"
        if safe_name != download.name:
            disposition += f"; filename*=UTF-8''{quote(download.name)}"
        content_type = mimetypes.guess_type(download.name)[0] or "text/plain"
        if content_type.startswith("text/"):
            content_type += "; charset=utf-8"
        try:
            # 从 open_file() 返回后就由此处独占 stream；即使浏览器在写响应头时
            # 断开，也必须关闭 fd，不能让重复下载耗尽小车的文件句柄。
            with download.stream:
                if convert_ros_time:
                    try:
                        # 先完整验证 UTF-8，保证在 HTTP 响应头尚未写出时就能给出
                        # 清晰失败，而不是让浏览器拿到中断或半截的转换文件。
                        ensure_utf8_text_stream(download.stream, maximum_bytes=download.size_bytes)
                    except UnicodeDecodeError:
                        message = "日志不是 UTF-8 文本，无法转换 ROS 时间；请关闭转换后下载原始文件"
                        self.send_error(HTTPStatus.UNPROCESSABLE_ENTITY, message)
                        if failed:
                            failed(message)
                        return False
                    except OSError:
                        message = "日志在下载开始前已缩小，请刷新文件清单后重试"
                        self.send_error(HTTPStatus.CONFLICT, message)
                        if failed:
                            failed(message)
                        return False
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Disposition", disposition)
                if not convert_ros_time:
                    self.send_header("Content-Length", str(download.size_bytes))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if convert_ros_time:
                    for chunk in iter_ros_time_converted_bytes(download.stream, maximum_bytes=download.size_bytes):
                        self.wfile.write(chunk)
                        if progress:
                            progress(download.stream.tell())
                else:
                    remaining = download.size_bytes
                    while remaining:
                        chunk = download.stream.read(min(64 * 1024, remaining))
                        if not chunk:
                            raise OSError("日志文件在下载开始后缩小")
                        remaining -= len(chunk)
                        self.wfile.write(chunk)
                        if progress:
                            progress(download.size_bytes - remaining)
                return True
        except (BrokenPipeError, ConnectionResetError):
            LOGGER.info("机器人日志下载连接关闭：source=%s file=%s", source_id, file_id)
            audit = getattr(self, "_tool_audit", None)
            if audit is not None:
                audit.interrupted = True
            if failed:
                failed("浏览器连接中断或日志读取失败")
            return False
        except OSError as exc:
            LOGGER.exception("机器人日志下载读取失败：source=%s file=%s error=%s", source_id, file_id, exc)
            audit = getattr(self, "_tool_audit", None)
            if audit is not None:
                audit.response(audit.status, {"error": "机器人日志下载读取失败"})
            if failed:
                failed("浏览器连接中断或日志读取失败")
            return False

    @staticmethod
    def _delete_report(requested: str) -> None:
        target = ConsoleHandler._archive_report_target(requested)
        report_root = target.parent
        csv_target = target.with_suffix(".csv")
        is_acceptance = bool(ACCEPTANCE_REPORT_FILENAME.fullmatch(target.name))
        manifest = target.with_suffix(".assets.json") if is_acceptance else None
        trajectory_dirs: list[Path] = []
        if manifest and manifest.is_file() and not manifest.is_symlink():
            try:
                document = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                document = None
            raw_directories = document.get("trajectory_directories") if isinstance(document, dict) and document.get("schema") == 1 else []
            if isinstance(raw_directories, list):
                for name in raw_directories:
                    if not isinstance(name, str) or not re.fullmatch(r"run_[0-9a-f]{12}_trajectory", name):
                        continue
                    candidate = (report_root / name).resolve()
                    if candidate.parent == report_root and candidate.is_dir() and not candidate.is_symlink():
                        trajectory_dirs.append(candidate)
        elif not is_acceptance:
            match = re.search(r"_([0-9a-f]{12})\.html$", target.name)
            if not match:
                raise ValueError("报告文件名不合法")
            candidate = (report_root / f"run_{match.group(1)}_trajectory").resolve()
            if candidate.parent == report_root and candidate.is_dir() and not candidate.is_symlink():
                trajectory_dirs.append(candidate)
        target.unlink()
        if csv_target.is_file():
            csv_target.unlink()
        if manifest and manifest.is_file():
            manifest.unlink()
        for trajectory_dir in trajectory_dirs:
            shutil.rmtree(trajectory_dir)
        NativeReportArchive(report_root).delete_for_filename(target.name)

    def _static_from(self, root: Path, requested: str, *, inject_console_shell: bool = True) -> None:
        target = (root / requested).resolve()
        if root not in target.parents or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix == ".html":
            body = inject_client_diagnostics(body)
        if target.suffix == ".html" and inject_console_shell:
            # 所有控制台页面共享品牌版本提示，避免四个独立页面重复维护同一段标记。
            shell_scripts = b'<script src="/brand_version.js"></script>'
            # 传统页面已直接引用公共壳层；重复注入会让品牌主题与导航监听器
            # 被注册两次。Vue 构建页没有该标签时仍由服务端补齐。
            if b'<script src="/app_shell.js"></script>' not in body:
                shell_scripts += b'<script src="/app_shell.js"></script>'
            body = body.replace(b"</body>", shell_scripts + b"</body>")
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
        body = inject_client_diagnostics(body)
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
        audit = getattr(self, "_tool_audit", None)
        if audit is not None:
            audit.response(status, payload)
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
    try:
        # 手动控制首次页面请求不能承担 ROS2 节点创建和锁存状态回放的延迟。
        # 仅在已确认本进程拥有监听端口后创建 ROS 资源；否则第二个进程退出时
        # 会遗留初始化中的线程，冻结程序可能因此异常终止并被 systemd 反复重启。
        VEHICLE_CONTROL.start()
    except VehicleControlUnavailable as exc:
        LOGGER.warning("车辆控制 ROS2 模块预热失败：%s", exc)
    # 状态监控始终只读；ROS 不可用时页面安全显示“状态暂不可用”，不能阻塞控制台。
    VEHICLE_EXECUTION_STATUS.start()
    LOCALIZATION_STATUS.start()
    server.upgrade_pending = False
    server.restart_command = None
    native_backfill_stop = threading.Event()
    # The socket is already listening after ThreadingHTTPServer construction.
    # Historical evidence is therefore strictly post-listen, daemonized work.
    threading.Thread(
        target=_native_report_backfill_worker,
        args=(native_backfill_stop, WORKSPACE),
        daemon=True,
        name="native-report-backfill",
    ).start()
    # 长连接代理不应拖住安全退出或离线升级后的新版本启动。
    server.daemon_threads = True
    video_command = [str(sys.executable), "--video-runner"]
    if not getattr(sys, "frozen", False):
        video_command = [sys.executable, str(Path(__file__).resolve()), "--video-runner"]
    video_runtime = ConsoleVideoRuntime(VIDEO, WORKSPACE, video_command)
    # The HTTP handler may start/stop only this parent-owned controller; no
    # Supervisor or system service participates in the optional video path.
    server.video_runtime = video_runtime
    LOGS.start_maintenance()
    video_runtime.start_if_enabled()
    print("RY Aletheia 自动测试平台：http://0.0.0.0:8087")
    print("局域网访问：http://<小车IP>:8087")
    print("按 Ctrl+C 停止服务")
    restore_signal_handlers = _install_console_shutdown_signal_handlers(server)
    restart_scheduled: bool | None = None
    try:
        server.serve_forever()
    finally:
        # A successful systemd restart owns the whole console cgroup.  Do not
        # wait for arbitrary ROS executor teardown after the replacement has
        # already committed: systemd would otherwise hold this restart in its
        # stop phase until TimeoutStopSec, then launch too late or collide with
        # a manual recovery process.  This does not apply to terminal starts.
        if server.restart_command and _is_systemd_service_context():
            restart_scheduled = _spawn_upgrade_restart(WORKSPACE, Path(server.restart_command[0]))
            if restart_scheduled:
                LOGGER.info("离线升级已交由 systemd 重启控制台")
                _handoff_to_systemd_after_upgrade()
        try:
            _close_console_resources(native_backfill_stop, video_runtime, server)
        finally:
            restore_signal_handlers()
    if server.restart_command:
        if restart_scheduled is None:
            restart_scheduled = _spawn_upgrade_restart(WORKSPACE, Path(server.restart_command[0]))
        if not restart_scheduled and _is_systemd_service_context():
            # 让 Restart=on-failure 接管 systemctl 不可用的异常路径，避免
            # 服务正常退出后留下“已替换但无人启动”的新二进制。
            raise SystemExit(1)


if __name__ == "__main__":
    if sys.argv[1:] == ["--video-runner"]:
        raise SystemExit(VideoRuntime(VIDEO, WORKSPACE, _VIDEO_INGEST, ROOT / "runtime" / "video").run())
    run_console()
