import base64
import errno
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
import re
from http import HTTPStatus
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import web_console
from autodrive_console.case_store import CaseStore
from autodrive_console.models import AttemptResult, RunRecord, TaskParameters, TestCase
from autodrive_console.map_assets import CachedMapAsset, MapAssetCache
from autodrive_console.native_report_archive import NativeReportArchive
from autodrive_console.map_snapshot import ObservationMapSnapshot
from autodrive_console.observation import ObservationError, ObservationManager
from autodrive_console.telemetry import TelemetryGateway
from autodrive_console.trajectory import ActiveMap, TrajectorySession
from autodrive_console.trajectory_render import _png_gray
from autodrive_console.run_manager import RunManager
from autodrive_console.scenario_setup import ScenarioSetupError, ScenarioSetupStore
from autodrive_console.robot_gateway import RobotGateway
from autodrive_console.settings import RobotSettings, SettingsStore
from autodrive_console.supervisor import SupervisorClient
from autodrive_console.tool_logging import ToolLogStore
from autodrive_console.upgrade_manager import UpgradeError, UpgradeManager
from autodrive_console import upgrade_signature


def _assert_source_contains(source: str, expected: str) -> None:
    """Keep static semantic checks stable across formatter-only changes."""
    normalize = lambda value: re.sub(
        r",(?=[)\]}])", "", re.sub(r"\s+", "", value).replace('"', "'")
    )
    if normalize(expected) not in normalize(source):
        raise AssertionError(f"Expected semantic source fragment is missing: {expected}")


def _signed_upgrade_manifest(binary: bytes) -> tuple[dict, str]:
    """Create a throwaway Ed25519 release for upgrade boundary tests."""

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        private_key = root / "test-release.pem"
        payload_path = root / "manifest.payload"
        signature_path = root / "manifest.signature"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(private_key)],
            check=True,
            capture_output=True,
            text=True,
        )
        manifest = {
            "schema": UpgradeManager.SCHEMA,
            "version": "0.2",
            "created_at": "2026-08-13T00:00:00+08:00",
            "binary": {
                "path": "ry-aletheia",
                "size": len(binary),
                "md5": hashlib.md5(binary).hexdigest(),
                "sha256": hashlib.sha256(binary).hexdigest(),
            },
        }
        payload_path.write_bytes(upgrade_signature.canonical_manifest_payload(manifest))
        subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-inkey", str(private_key), "-rawin", "-in", str(payload_path), "-out", str(signature_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        public_der = subprocess.run(
            ["openssl", "pkey", "-in", str(private_key), "-pubout", "-outform", "DER"],
            check=True,
            capture_output=True,
        ).stdout
        manifest["signature"] = {
            "algorithm": upgrade_signature.SIGNATURE_ALGORITHM,
            "key_id": upgrade_signature.RELEASE_KEY_ID,
            "value": base64.b64encode(signature_path.read_bytes()).decode("ascii"),
        }
        return manifest, base64.b64encode(public_der[-32:]).decode("ascii")


class _SupervisorClient(SupervisorClient):
    def _run(self, _args):
        from subprocess import CompletedProcess
        return CompletedProcess([], 0, "NODE:1 RUNNING pid 10\nNODE:2 STOPPED Not started\n", "")


class OfflineModuleTests(unittest.TestCase):
    def test_systemd_sigterm_runs_console_cleanup_before_exit(self):
        """systemd 停止控制台时必须主动回收其视频与观测子进程树。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready = root / "ready"
            cleanup = root / "cleanup"
            script = f"""
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import web_console

ready = Path({str(ready)!r})
cleanup = Path({str(cleanup)!r})

def record(name):
    with cleanup.open("a", encoding="utf-8") as output:
        output.write(name + "\\n")

class ProbeServer:
    def __init__(self, *_args):
        self.stop_event = threading.Event()

    def serve_forever(self):
        ready.write_text("ready", encoding="utf-8")
        if not self.stop_event.wait(5):
            raise RuntimeError("console did not receive shutdown")

    def shutdown(self):
        record("shutdown")
        self.stop_event.set()

    def server_close(self):
        record("server")

class VideoRuntime:
    def __init__(self, *_args):
        pass

    def start_if_enabled(self):
        return False

    def stop(self):
        record("video")

web_console.VIDEO = SimpleNamespace(migrate_config=lambda: False)
web_console.VEHICLE_CONTROL = SimpleNamespace(start=lambda: None, close=lambda: record("vehicle"))
web_console.VEHICLE_EXECUTION_STATUS = SimpleNamespace(start=lambda: None, close=lambda: record("execution"))
web_console.LOCALIZATION_STATUS = SimpleNamespace(start=lambda: None, close=lambda: record("localization"))
web_console.MAPPING = SimpleNamespace(close=lambda: record("mapping"))
web_console.OBSERVATION = SimpleNamespace(stop=lambda: record("observation"))
web_console.ConsoleVideoRuntime = VideoRuntime
web_console.ThreadingHTTPServer = ProbeServer
web_console._native_report_backfill_worker = lambda *_args: None
web_console.run_console()
"""
            environment = {**os.environ, "ROVER_QA_ROS_READY": "1"}
            process = subprocess.Popen(
                [sys.executable, "-c", script],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                for _ in range(50):
                    if ready.is_file():
                        break
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        self.fail(f"console exited before the probe became ready: {stdout}\n{stderr}")
                    time.sleep(0.02)
                else:
                    self.fail("console did not begin serving before SIGTERM")

                process.send_signal(__import__("signal").SIGTERM)
                stdout, stderr = process.communicate(timeout=3)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

            self.assertEqual(process.returncode, 0, f"stdout:\n{stdout}\nstderr:\n{stderr}")
            self.assertEqual(
                set(cleanup.read_text(encoding="utf-8").splitlines()),
                {"shutdown", "video", "mapping", "vehicle", "execution", "localization", "observation", "server"},
            )

    def test_upgrade_restart_is_not_skipped_when_one_cleanup_step_fails(self):
        """A failed owned-resource cleanup must not strand an already replaced console."""

        class ProbeServer:
            def __init__(self, *_args):
                self.restart_command = None

            def serve_forever(self):
                self.restart_command = ["/tmp/replaced-ry-aletheia"]

            def server_close(self):
                pass

        class BrokenVideoRuntime:
            def __init__(self, *_args):
                pass

            def start_if_enabled(self):
                return False

            def stop(self):
                raise RuntimeError("video child did not exit")

        harmless = SimpleNamespace(start=lambda: None, close=lambda: None)
        with patch.object(web_console, "VIDEO", SimpleNamespace(migrate_config=lambda: False)), patch.object(
            web_console, "VEHICLE_CONTROL", harmless
        ), patch.object(web_console, "VEHICLE_EXECUTION_STATUS", harmless), patch.object(
            web_console, "LOCALIZATION_STATUS", harmless
        ), patch.object(web_console, "MAPPING", SimpleNamespace(close=lambda: None)), patch.object(
            web_console, "OBSERVATION", SimpleNamespace(stop=lambda: None)
        ), patch.object(web_console, "ConsoleVideoRuntime", BrokenVideoRuntime), patch.object(
            web_console, "ThreadingHTTPServer", ProbeServer
        ), patch.object(web_console, "_native_report_backfill_worker", lambda *_args: None), patch.object(
            web_console, "_install_console_shutdown_signal_handlers", lambda _server: lambda: None
        ), patch.object(web_console, "_spawn_upgrade_restart", return_value=True) as restart:
            web_console.run_console()

        restart.assert_called_once_with(web_console.WORKSPACE, Path("/tmp/replaced-ry-aletheia"))

    def test_systemd_upgrade_hands_off_without_waiting_for_console_cleanup(self):
        """已接受的服务重启不能被旧 ROS 清理路径卡住。"""

        class ProbeServer:
            def __init__(self, *_args):
                self.restart_command = None

            def serve_forever(self):
                self.restart_command = ["/tmp/replaced-ry-aletheia"]

            def server_close(self):
                raise AssertionError("systemd 接管后不应等待旧 HTTP 服务清理")

        class VideoRuntime:
            def __init__(self, *_args):
                pass

            def start_if_enabled(self):
                return False

            def stop(self):
                raise AssertionError("systemd 接管后不应等待旧视频运行时清理")

        class HandoffComplete(Exception):
            pass

        harmless = SimpleNamespace(start=lambda: None, close=lambda: None)
        with patch.object(web_console, "VIDEO", SimpleNamespace(migrate_config=lambda: False)), patch.object(
            web_console, "VEHICLE_CONTROL", harmless
        ), patch.object(web_console, "VEHICLE_EXECUTION_STATUS", harmless), patch.object(
            web_console, "LOCALIZATION_STATUS", harmless), patch.object(
            web_console, "ConsoleVideoRuntime", VideoRuntime
        ), patch.object(web_console, "ThreadingHTTPServer", ProbeServer), patch.object(
            web_console, "_native_report_backfill_worker", lambda *_args: None
        ), patch.object(web_console, "_install_console_shutdown_signal_handlers", lambda _server: lambda: None), patch.object(
            web_console, "_is_systemd_service_context", return_value=True
        ), patch.object(web_console, "_spawn_upgrade_restart", return_value=True) as restart, patch.object(
            web_console, "_handoff_to_systemd_after_upgrade", side_effect=HandoffComplete
        ) as handoff:
            with self.assertRaises(HandoffComplete):
                web_console.run_console()

        restart.assert_called_once_with(web_console.WORKSPACE, Path("/tmp/replaced-ry-aletheia"))
        handoff.assert_called_once_with()

    def test_port_conflict_exits_before_starting_ros_resources(self):
        """A second console must not start ROS threads before discovering 8087 is occupied."""

        def occupied_server(*_args):
            raise OSError(errno.EADDRINUSE, "Address already in use")

        vehicle = SimpleNamespace(start=Mock(), close=Mock())
        execution = SimpleNamespace(start=Mock(), close=Mock())
        localization = SimpleNamespace(start=Mock(), close=Mock())
        with patch.object(web_console, "VIDEO", SimpleNamespace(migrate_config=lambda: False)), patch.object(
            web_console, "VEHICLE_CONTROL", vehicle
        ), patch.object(web_console, "VEHICLE_EXECUTION_STATUS", execution), patch.object(
            web_console, "LOCALIZATION_STATUS", localization
        ), patch.object(web_console, "ThreadingHTTPServer", occupied_server):
            with self.assertRaises(SystemExit) as exited:
                web_console.run_console()

        self.assertEqual(exited.exception.code, 0)
        vehicle.start.assert_not_called()
        execution.start.assert_not_called()
        localization.start.assert_not_called()

    def test_settings_supply_and_validate_manual_relocalization_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "console.json")
            self.assertEqual(
                store.load().live_observation["manual_relocalization"],
                {"z_m": 0.4, "service_timeout_seconds": 12},
            )
            with self.assertRaisesRegex(ValueError, "重定位 z 值"):
                store.save(
                    {
                        "live_observation": {
                            "manual_relocalization": {
                                "z_m": float("nan"),
                                "service_timeout_seconds": 12,
                            }
                        }
                    }
                )

    def test_map_upload_picker_allows_multiple_files_not_directory_only(self):
        """Prevents the desktop chooser from locking operators into folder-only mode."""
        class Inputs(HTMLParser):
            def __init__(self):
                super().__init__()
                self.attributes = {}

            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if tag == "input" and values.get("id") == "mapFolder":
                    self.attributes = values

        parser = Inputs()
        parser.feed((web_console.WEB_ROOT / "deployment.html").read_text(encoding="utf-8"))
        self.assertEqual(parser.attributes.get("type"), "file")
        self.assertIn("multiple", parser.attributes)
        self.assertNotIn("webkitdirectory", parser.attributes)

    def test_mapping_workbench_is_a_dedicated_live_canvas_with_safe_controls(self):
        """建图时不应把表单、画布与遥控混在部署页；工作台要有独立安全控制入口。"""
        workbench = web_console.WEB_ROOT / "mapping-workbench.html"
        self.assertTrue(workbench.is_file())
        page = workbench.read_text(encoding="utf-8")
        self.assertIn('id="liveMappingCanvas"', page)
        self.assertIn('id="enterManual"', page)
        self.assertIn('id="stopMapping"', page)
        self.assertIn('src="/mapping_workbench.js"', page)

    def test_mapping_template_is_selected_from_browser_files_not_robot_paths(self):
        """部署页不得让操作者输入或读取机器人原有 YAML 绝对路径。"""
        page = (web_console.WEB_ROOT / "deployment.html").read_text(encoding="utf-8")
        self.assertIn('id="mappingTemplateFile"', page)
        self.assertIn('type="file"', page)
        self.assertNotIn('id="mappingTemplate" value="/opt/ry/', page)

    def test_theme_shell_uses_document_root_tokens(self):
        """浅色主题必须同步到根节点，避免内容不足一屏时露出深色 html 背景。"""
        shell = (web_console.WEB_ROOT / "app_shell.js").read_text(encoding="utf-8")
        css = (web_console.WEB_ROOT / "app_shell.css").read_text(encoding="utf-8")
        self.assertIn("document.documentElement.dataset.theme", shell)
        self.assertIn('html[data-theme="light"]', css)
        self.assertIn('html[data-theme="light"] body.theme-light', css)
        self.assertIn("min-height: 100dvh", css)
        self.assertIn("main:has(#caseSelect) .monitor { background: var(--surface); }", css)

    def test_desktop_sidebar_declares_all_operator_pages_in_stable_groups(self):
        """防止新增页面重新退化为逐页插入、无层级的长菜单。"""
        shell = (web_console.WEB_ROOT / "app_shell.js").read_text(encoding="utf-8")

        self.assertIn("NAVIGATION_GROUPS", shell)
        for label, routes in {
            "作业": ("/", "/manual-control.html"),
            "部署与验收": ("/deployment.html", "/acceptance-test.html"),
            "测试与诊断": ("/live-observation.html", "/case-library.html"),
            "记录与分析": ("/reports.html", "/robot-logs.html"),
            "系统": ("/runtime-settings.html",),
        }.items():
            self.assertIn(f'label: "{label}"', shell)
            for route in routes:
                self.assertIn(f'href: "{route}"', shell)

    def test_desktop_pages_load_the_shared_theme_shell(self):
        """共享样式必须随共享脚本加载，否则根主题变量不会实际同步。"""
        pages = (
            "index.html", "deployment.html", "manual-control.html", "case-library.html",
            "reports.html", "runtime-settings.html", "tool-logs.html",
            "scenario-setup.html",
        )
        for page_name in pages:
            page = (web_console.WEB_ROOT / page_name).read_text(encoding="utf-8")
            self.assertIn('<script src="/app_shell.js"></script>', page, page_name)

    def test_static_page_injection_does_not_load_the_shared_shell_twice(self):
        """页面已声明共享壳时，HTTP 注入只能补品牌脚本，不能重复绑定主题监听器。"""
        def rendered(root: Path, page: str) -> bytes:
            handler = object.__new__(web_console.ConsoleHandler)
            handler.send_error = Mock()
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            handler.wfile = io.BytesIO()
            handler._static_from(root, page)
            return handler.wfile.getvalue()

        desktop = rendered(web_console.WEB_ROOT, "index.html")
        # `web-vue/` is a generated, ignored release artifact. Backend tests
        # run before the Web build in CI, so exercise the Vue-page injection
        # boundary with a minimal page instead of depending on a local build.
        with tempfile.TemporaryDirectory() as directory:
            vue_root = Path(directory)
            (vue_root / "dashboard.html").write_text(
                "<!doctype html><html><body><main id=\"app\"></main></body></html>",
                encoding="utf-8",
            )
            vue = rendered(vue_root, "dashboard.html")
        shell = b'<script src="/app_shell.js"></script>'
        version = b'<script src="/brand_version.js"></script>'
        self.assertEqual(desktop.count(shell), 1)
        self.assertEqual(desktop.count(version), 1)
        self.assertEqual(vue.count(shell), 1)
        self.assertEqual(vue.count(version), 1)

    def test_execution_status_api_returns_the_read_only_monitor_snapshot(self):
        """The browser endpoint is an adapter, not a second status classifier."""
        handler = object.__new__(web_console.ConsoleHandler)
        handler.path = "/api/vehicle-execution-status"
        handler.headers = {"User-Agent": "desktop-test"}
        handler._json = Mock()
        expected = {"phase": "riding_elevator", "label": "乘梯中"}

        with patch.object(web_console.VEHICLE_EXECUTION_STATUS, "status", return_value=expected):
            handler.do_GET()

        handler._json.assert_called_once_with(expected)

    def test_localization_status_api_returns_the_read_only_monitor_snapshot(self):
        """The live map receives only the normalized localization snapshot."""
        handler = object.__new__(web_console.ConsoleHandler)
        handler.path = "/api/observation/localization-status"
        handler.headers = {"User-Agent": "desktop-test"}
        handler._json = Mock()
        expected = {
            "phase": "relocalizing",
            "label": "重定位中",
            "detail": "NDT 匹配质量低",
            "updated_at": 123.0,
        }

        with patch.object(web_console.LOCALIZATION_STATUS, "status", return_value=expected):
            handler.do_GET()

        handler._json.assert_called_once_with(expected)

    def test_execution_status_page_can_opt_out_of_desktop_shell_injection(self):
        """The dedicated display must not inherit nav or brand scripts from normal pages."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "vehicle-execution-status.html").write_text(
                "<!doctype html><html><body><main></main></body></html>", encoding="utf-8"
            )
            handler = object.__new__(web_console.ConsoleHandler)
            handler.send_error = Mock()
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            handler.wfile = io.BytesIO()

            handler._static_from(root, "vehicle-execution-status.html", inject_console_shell=False)

        rendered = handler.wfile.getvalue()
        self.assertNotIn(b"/app_shell.js", rendered)
        self.assertNotIn(b"/brand_version.js", rendered)

    def test_deployment_page_has_a_dedicated_current_project_status_card(self):
        """Prevents an open project from being visually indistinguishable from a blank new-project form."""
        page = (web_console.WEB_ROOT / "deployment.html").read_text(encoding="utf-8")
        self.assertIn('id="currentProjectCard"', page)
        self.assertIn('id="currentProjectName"', page)
        self.assertIn('id="currentProjectMeta"', page)
        self.assertIn('id="showNewProjectForm"', page)

    def test_mapping_ui_distinguishes_waiting_for_the_first_grid_from_live_mapping(self):
        """A blank canvas needs an actionable state instead of a false progress claim."""
        script = (web_console.WEB_ROOT / "deployment.js").read_text(encoding="utf-8")
        self.assertIn('preview?.state === "waiting"', script)
        self.assertIn("正在等待 Lightning 的第一帧栅格", script)

    def test_preflight_summary_keeps_long_diagnostics_out_of_the_status_badge(self):
        """运行状态卡的长诊断信息必须留在可换行的摘要区，不能撑破标题徽标。"""
        page = (web_console.WEB_ROOT / "index.html").read_text(encoding="utf-8")
        script = (web_console.WEB_ROOT / "app.js").read_text(encoding="utf-8")
        shell = (web_console.WEB_ROOT / "app_shell.css").read_text(encoding="utf-8")

        self.assertIn('id="preflightSummary"', page)
        self.assertIn("$('preflightSummary').textContent", script)
        self.assertIn(".readiness-summary", shell)
        self.assertIn(".readiness .sync-status", shell)

    def test_execution_trend_keeps_many_rounds_inside_its_panel(self):
        """高轮次趋势应在图表内横向查看，不能撑破监控卡片。"""
        script = (web_console.WEB_ROOT / "app.js").read_text(encoding="utf-8")
        css = (web_console.WEB_ROOT / "refinement.css").read_text(encoding="utf-8")

        self.assertIn('class="chart-series"', script)
        self.assertIn("--chart-series-min-width", script)
        self.assertIn("可横向滚动查看全部", script)
        self.assertIn("main:has(#caseSelect) .chart", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("padding: 24px 8px 0", css)
        self.assertIn("height: 100%", css)
        self.assertIn("min-width: max(100%, var(--chart-series-min-width))", css)

    def test_dependency_orchestration_exposes_policy_and_stage_controls_to_assistive_technology(self):
        """依赖策略说明、节点列和阶段操作不能只依赖视觉样式或无名称图标。"""
        page = (web_console.WEB_ROOT / "index.html").read_text(encoding="utf-8")
        script = (web_console.WEB_ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn('class="dependency-policy"', page)
        self.assertIn('id="dependencyPolicyDescription"', page)
        self.assertIn('aria-describedby="dependencyPolicyDescription"', page)
        self.assertIn('class="dependency-process-columns"', page)
        self.assertIn('aria-live="polite"', page)
        self.assertIn('aria-label="将阶段上移"', script)
        self.assertIn('aria-label="将阶段下移"', script)
        self.assertIn('aria-label="移除阶段"', script)

    def test_dependency_orchestration_keeps_the_node_table_within_a_narrow_dialog(self):
        """393px 宽度时节点列必须允许名称列收缩，不能产生整窗横向滚动。"""
        css = (web_console.WEB_ROOT / "refinement.css").read_text(encoding="utf-8")
        self.assertIn('grid-template-columns: 48px 48px 62px minmax(0, 1fr);', css)

    def test_dependency_orchestration_does_not_present_discovery_failures_as_success(self):
        """读取 Supervisor 失败时，默认消息颜色必须是错误语义色而不是成功绿。"""
        css = (web_console.WEB_ROOT / "refinement.css").read_text(encoding="utf-8")
        script = (web_console.WEB_ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('.dependency-dialog > .message {\n  min-height: 18px;\n  margin: 7px 24px 0;\n  color: #eab0b9;', css)
        self.assertIn("$('dependencyMessage').style.color = '#35d69c';", script)

    def test_desktop_shell_serves_the_provided_aletheia_logo_asset(self):
        """Fails when the shared desktop shell cannot load the operator-provided logo."""
        asset = web_console.WEB_ROOT / "aletheia.svg"
        self.assertTrue(asset.is_file())
        self.assertIn(b"viewBox=\"0 0 1254 1254\"", asset.read_bytes())

    def test_expected_client_disconnect_does_not_escape_http_request_thread(self):
        handler = object.__new__(web_console.ConsoleHandler)
        handler.client_address = ("192.168.1.140", 40166)
        with patch("http.server.BaseHTTPRequestHandler.handle", side_effect=ConnectionResetError(104, "Connection reset by peer")):
            # 移动端切换/刷新时的正常断连不能交回 socketserver 输出 Traceback。
            self.assertIsNone(handler.handle())

    def test_safe_shutdown_refuses_active_run_or_unresolved_scenario(self):
        handler = object.__new__(web_console.ConsoleHandler)
        handler.path = "/api/system/shutdown"
        handler._json = Mock()
        handler.server = SimpleNamespace(shutdown=Mock())
        with patch.object(web_console.RUNS, "has_active_run", return_value=True):
            handler.do_POST()
        handler._json.assert_called_once()
        self.assertEqual(handler._json.call_args.args[1], HTTPStatus.CONFLICT)
        handler._json.reset_mock()
        with patch.object(web_console.RUNS, "has_active_run", return_value=False), patch.object(web_console.SCENARIO_SETUP, "has_unresolved_transaction", return_value=True), patch.object(web_console.SCENARIO_SETUP, "status", return_value={"transaction": {"message": "待恢复"}}):
            handler.do_POST()
        self.assertEqual(handler._json.call_args.args[1], HTTPStatus.CONFLICT)
        handler.server.shutdown.assert_not_called()

    def test_safe_shutdown_ui_surfaces_the_server_rejection_reason(self):
        """操作者必须看见安全拦截的实际原因，而不是笼统的“未接受”。"""
        source = (web_console.WEB_ROOT / "app.js").read_text(encoding="utf-8")
        _assert_source_contains(source, "const body = await response.json().catch(() => ({}));")
        _assert_source_contains(source, "if (!response.ok) throw new Error(body.error || '控制台未接受退出请求');")

    def test_resume_refuses_active_manual_control_session(self):
        """恢复验收前必须退出手控会话，避免自动任务抢占手控。"""
        handler = object.__new__(web_console.ConsoleHandler)
        handler.path = "/api/runs/recovery123456/resume"
        handler._json = Mock()
        with patch.object(web_console.VEHICLE_CONTROL, "has_control_session", return_value=True), patch.object(web_console.RUNS, "resume") as resume:
            handler.do_POST()
        resume.assert_not_called()
        handler._json.assert_called_once()
        payload, status = handler._json.call_args.args
        self.assertEqual(status, HTTPStatus.CONFLICT)
        self.assertIn("退出手动控制", payload["error"])

    def test_mobile_console_uses_separate_known_routes_without_changing_desktop_routes(self):
        self.assertTrue(web_console.is_mobile_console_client({"Sec-CH-UA-Mobile": "?1"}))
        self.assertTrue(web_console.is_mobile_console_client({"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"}))
        self.assertFalse(web_console.is_mobile_console_client({"Sec-CH-UA-Mobile": "?0", "User-Agent": "Android"}))
        console_source = Path("web_console.py").read_text(encoding="utf-8")
        self.assertIn('forced_mobile = query.get("mobile", [""])[0] == "1"', console_source)
        self.assertIn("forced_mobile or is_mobile_console_client", console_source)
        self.assertEqual(web_console.mobile_url_for("/"), "/m/")
        self.assertEqual(web_console.mobile_url_for("/vue/dashboard.html"), "/m/")
        self.assertEqual(web_console.mobile_url_for("/live-observation.html"), "/m/live-observation.html")
        self.assertEqual(web_console.mobile_page_name("/m/runtime-settings.html"), "runtime-settings.html")
        self.assertIsNone(web_console.mobile_page_name("/m/../../web_console.py"))
        self.assertIsNone(web_console.mobile_url_for("/api/runs/latest"))
        mobile_shell = (web_console.WEB_ROOT / "mobile_console.js").read_text(encoding="utf-8")
        self.assertIn("NAV_ITEMS", mobile_shell)
        self.assertIn("mobile-shell-generic", mobile_shell)
        self.assertIn("mobile-shell-nav", mobile_shell)
        self.assertIn("dedicatedLiveConsole", mobile_shell)
        self.assertIn("document.querySelector('.mobile-console-bar') && document.querySelector('.mobile-bottom-nav')", mobile_shell)
        self.assertNotIn("mobileRotateGuard", mobile_shell)
        self.assertIn(".mobile-bottom-nav a", mobile_shell)
        self.assertNotIn("mobile-viewer-fullscreen-active", mobile_shell)
        self.assertNotIn("mobile-nav-toggle", mobile_shell)
        mobile_style = (web_console.WEB_ROOT / "mobile_console.css").read_text(encoding="utf-8")
        self.assertIn("orientation: landscape", mobile_style)
        self.assertIn("body.mobile-console.mobile-shell-generic", mobile_style)
        self.assertIn(".mobile-shell-bar", mobile_style)
        self.assertIn(".mobile-shell-nav", mobile_style)
        self.assertNotIn("mobile-viewer-fullscreen-active", mobile_style)
        self.assertNotIn("#08111f", mobile_style)

    def test_status_counts_the_console_process_tree_including_onefile_helpers(self):
        """状态工具不能按安装路径过滤，否则会漏掉 /tmp/_MEI* 的 C++ sidecar。"""
        status_source = Path("packaging/debian/ry-aletheia-status").read_text(encoding="utf-8")
        self.assertIn("tool_tree_pids()", status_source)
        self.assertIn('pgrep -P "$current"', status_source)
        self.assertIn('tool_tick_snapshot "$root_pid"', status_source)
        self.assertIn('print_tool_cpu "$pid"', status_source)
        self.assertNotIn("awk -v prefix=\"$root/\"", status_source)

    def test_scenario_setup_restores_registered_targets_and_preserves_unrelated_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "opt" / "ry" / "config" / "localization"
            config.mkdir(parents=True)
            target = config / "hall.yaml"
            target.write_text("map: hall\n", encoding="utf-8")
            script = root / "handle_modules.sh"
            original = (
                "exec taskset -c 1 ros2 launch fcrp_bringup original.launch.py\n"
                "exec taskset -c 4 ros2 run lightning run_loc_online --config /opt/ry/config/localization/original.yaml\n"
            )
            script.write_text(original, encoding="utf-8")
            store = ScenarioSetupStore(root / "console")
            # 测试环境不含 /opt/ry，绕过路径存在性检查以覆盖事务替换本身。
            with patch.object(store, "_validate_targets", return_value={"fcrp": "corrtest.launch.py", "lightning": "/opt/ry/config/localization/hall.yaml"}):
                store.save({"startup_script": str(script), "profiles": [{"id": "elevator", "name": "电梯场景", "fcrp_launch": "corrtest.launch.py", "lightning_config": "/opt/ry/config/localization/hall.yaml"}], "case_bindings": {}})
                applied = store.apply("elevator")
            self.assertIn("电梯场景", applied["message"])
            self.assertIn("corrtest.launch.py", script.read_text(encoding="utf-8"))
            self.assertTrue(store.status()["active_backup"])
            self.assertTrue(store.restore()["restored"])
            self.assertEqual(script.read_text(encoding="utf-8"), original)
            with patch.object(store, "_validate_targets", return_value={"fcrp": "corrtest.launch.py", "lightning": "/opt/ry/config/localization/hall.yaml"}):
                store.apply("elevator")
            script.write_text(script.read_text(encoding="utf-8") + "# changed elsewhere\n", encoding="utf-8")
            self.assertTrue(store.restore()["restored"])
            self.assertEqual(script.read_text(encoding="utf-8"), original + "# changed elsewhere\n")
            with patch.object(store, "_validate_targets", return_value={"fcrp": "corrtest.launch.py", "lightning": "/opt/ry/config/localization/hall.yaml"}):
                store.apply("elevator")
            script.write_text(script.read_text(encoding="utf-8").replace("corrtest.launch.py", "operator_override.launch.py"), encoding="utf-8")
            with self.assertRaisesRegex(ScenarioSetupError, "被外部改为"):
                store.restore()

    def test_scenario_setup_persists_backup_before_changing_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "handle_modules.sh"
            original = (
                "ros2 launch fcrp_bringup default.launch.py\n"
                "ros2 run lightning run_loc_online --config /opt/ry/config/default.yaml\n"
            )
            script.write_text(original, encoding="utf-8")
            store = ScenarioSetupStore(root / "console")
            store.save({"startup_script": str(script), "profiles": [{"id": "hall", "name": "大厅", "fcrp_launch": "hall.launch.py", "lightning_config": "/opt/ry/config/hall.yaml"}], "case_bindings": {}})
            with patch.object(store, "_validate_targets", return_value={"fcrp": "hall.launch.py", "lightning": "/opt/ry/config/hall.yaml"}), patch.object(store, "_write_active", side_effect=ScenarioSetupError("磁盘写入失败")):
                with self.assertRaisesRegex(ScenarioSetupError, "磁盘写入失败"):
                    store.apply("hall")
            self.assertEqual(script.read_text(encoding="utf-8"), original)
            self.assertFalse((root / "console" / "scenario_backups" / "active.json").exists())

    def test_scenario_setup_unbound_case_refuses_leftover_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "handle_modules.sh"
            original = (
                "ros2 launch fcrp_bringup default.launch.py\n"
                "ros2 run lightning run_loc_online --config /opt/ry/config/default.yaml\n"
            )
            script.write_text(original, encoding="utf-8")
            store = ScenarioSetupStore(root / "console")
            store.save({"startup_script": str(script), "profiles": [{"id": "hall", "name": "大厅", "fcrp_launch": "hall.launch.py", "lightning_config": "/opt/ry/config/hall.yaml"}], "case_bindings": {}})
            with patch.object(store, "_validate_targets", return_value={"fcrp": "hall.launch.py", "lightning": "/opt/ry/config/hall.yaml"}):
                store.apply("hall")
            with self.assertRaisesRegex(ScenarioSetupError, "待恢复事务"):
                store.apply_for_case("unbound.json")
            self.assertNotEqual(script.read_text(encoding="utf-8"), original)
            self.assertTrue(store.has_unresolved_transaction())

    def test_scenario_setup_marks_corrupt_transaction_as_recovery_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ScenarioSetupStore(root / "console")
            store.save({"startup_script": str(root / "handle_modules.sh"), "profiles": [], "case_bindings": {}})
            store.backup_dir.mkdir(parents=True)
            (store.backup_dir / "active.json").write_text('{"state":"applied"}\n', encoding="utf-8")
            status = store.status()
            self.assertEqual(status["transaction"]["state"], "corrupt")
            self.assertTrue(store.has_unresolved_transaction())
            with self.assertRaisesRegex(ScenarioSetupError, "恢复事务不可用"):
                store.save(store.load())

    def test_scenario_setup_restore_completes_without_restarting_robot_nodes(self):
        """恢复常规方案只回写受控脚本并关闭事务。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "handle_modules.sh"
            original = (
                "ros2 launch fcrp_bringup default.launch.py\n"
                "ros2 run lightning run_loc_online --config /opt/ry/config/default.yaml\n"
            )
            script.write_text(original, encoding="utf-8")
            store = ScenarioSetupStore(root / "console")
            store.save({"startup_script": str(script), "profiles": [{"id": "hall", "name": "大厅", "fcrp_launch": "hall.launch.py", "lightning_config": "/opt/ry/config/hall.yaml"}], "case_bindings": {}})
            with patch.object(store, "_validate_targets", return_value={"fcrp": "hall.launch.py", "lightning": "/opt/ry/config/hall.yaml"}):
                store.apply("hall")
            result = store.restore()
            self.assertTrue(result["restored"])
            self.assertFalse(store.has_unresolved_transaction())
            self.assertEqual(script.read_text(encoding="utf-8"), original)

    def test_scenario_setup_rejects_restore_when_same_prefix_position_is_shifted(self):
        """外部插入同类启动命令时，宁可拒绝也不能回退错行。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "handle_modules.sh"
            original = (
                "ros2 launch fcrp_bringup default.launch.py # primary\n"
                "ros2 run lightning run_loc_online --config /opt/ry/config/default.yaml\n"
            )
            script.write_text(original, encoding="utf-8")
            store = ScenarioSetupStore(root / "console")
            store.save({"startup_script": str(script), "profiles": [{"id": "hall", "name": "大厅", "fcrp_launch": "hall.launch.py", "lightning_config": "/opt/ry/config/hall.yaml"}], "case_bindings": {}})
            with patch.object(store, "_validate_targets", return_value={"fcrp": "hall.launch.py", "lightning": "/opt/ry/config/hall.yaml"}):
                store.apply("hall")
            script.write_text("ros2 launch fcrp_bringup external.launch.py # inserted\n" + script.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaisesRegex(ScenarioSetupError, "命令行.*外部修改"):
                store.restore()

    def test_scenario_setup_uses_selected_command_positions_when_script_has_multiple_candidates(self):
        """多个 launch/config 命令时，操作者选中的两处才允许被替换。"""
        text = (
            "ros2 launch unrelated keep.launch.py\n"
            "ros2 launch fcrp_bringup old_fcrp.launch.py\n"
            "ros2 run unrelated worker --config /opt/ry/config/keep.yaml\n"
            "ros2 run lightning run_loc_online --config /opt/ry/config/old_lightning.yaml\n"
        )
        candidates = ScenarioSetupStore._command_candidates(text)
        fcrp = next(item for item in candidates if item["package"] == "fcrp_bringup")
        lightning = next(item for item in candidates if item["package"] == "lightning")
        with tempfile.TemporaryDirectory() as directory:
            updated = ScenarioSetupStore(Path(directory))._replace_targets(
                text,
                {"fcrp": "selected.launch.py", "lightning": "/opt/ry/config/selected.yaml"},
                {
                    "fcrp": {"kind": "launch", "prefix": fcrp["prefix"]},
                    "lightning": {"kind": "config", "prefix": lightning["prefix"]},
                },
            )
        self.assertIn("ros2 launch unrelated keep.launch.py", updated)
        self.assertIn("ros2 run unrelated worker --config /opt/ry/config/keep.yaml", updated)
        self.assertIn("ros2 launch fcrp_bringup selected.launch.py", updated)
        self.assertIn("ros2 run lightning run_loc_online --config /opt/ry/config/selected.yaml", updated)

    def test_scenario_setup_uses_selected_occurrence_when_prefix_repeats(self):
        text = (
            "ros2 launch fcrp_bringup keep.launch.py\n"
            "ros2 launch fcrp_bringup selected.launch.py\n"
            "ros2 run lightning run_loc_online --config /opt/ry/config/old.yaml\n"
        )
        candidates = ScenarioSetupStore._command_candidates(text)
        selected = [item for item in candidates if item["package"] == "fcrp_bringup"][1]
        lightning = next(item for item in candidates if item["package"] == "lightning")
        updated = ScenarioSetupStore(Path(tempfile.gettempdir()))._replace_targets(text, {"fcrp": "changed.launch.py", "lightning": "/opt/ry/config/new.yaml"}, {
            "fcrp": {"kind": "launch", "prefix": selected["prefix"], "occurrence": selected["occurrence"]},
            "lightning": {"kind": "config", "prefix": lightning["prefix"], "occurrence": lightning["occurrence"]},
        })
        self.assertIn("ros2 launch fcrp_bringup keep.launch.py", updated)
        self.assertIn("ros2 launch fcrp_bringup changed.launch.py", updated)

    def test_scenario_setup_previews_changed_startup_script_without_writing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "handle_modules.sh"
            original = (
                "ros2 launch fcrp_bringup old.launch.py\n"
                "ros2 run lightning run_loc_online --config /opt/ry/config/old.yaml\n"
            )
            script.write_text(original, encoding="utf-8")
            document = {
                "startup_script": str(script),
                "profiles": [{"id": "hall", "name": "大厅", "fcrp_launch": "new.launch.py", "lightning_config": "/opt/ry/config/new.yaml"}],
                "case_bindings": {},
            }
            store = ScenarioSetupStore(root / "console")
            with patch.object(store, "_validate_targets", return_value={"fcrp": "new.launch.py", "lightning": "/opt/ry/config/new.yaml"}):
                result = store.preview_application(document, "hall")
            self.assertTrue(result["changed"])
            self.assertIn("new.launch.py", result["content"])
            self.assertIn("/opt/ry/config/new.yaml", result["content"])
            self.assertEqual(script.read_text(encoding="utf-8"), original)

    def test_scenario_setup_previews_only_files_below_selected_script_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "handle_modules.sh"
            script.write_text("#!/bin/bash\necho ready\n", encoding="utf-8")
            allowed = root / "config" / "localization.yaml"
            allowed.parent.mkdir()
            allowed.write_text("map: P1\n", encoding="utf-8")
            outside = root.parent / "outside.yaml"
            outside.write_text("private: no\n", encoding="utf-8")
            store = ScenarioSetupStore(root / "console")
            store.save({"startup_script": str(script), "profiles": [], "case_bindings": {}})
            preview = store.read_file(str(allowed))
            self.assertEqual(preview["content"], "map: P1\n")
            self.assertIn("sha256", preview)
            with self.assertRaisesRegex(ScenarioSetupError, "受控目录"):
                store.read_file(str(outside))

    def test_scenario_setup_binds_each_case_to_one_existing_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ScenarioSetupStore(Path(directory))
            store.save({"startup_script": "/opt/ry/scripts/handle_modules.sh", "profiles": [{"id": "hall", "name": "电梯大厅", "fcrp_launch": "hall.launch.py", "lightning_config": "/opt/ry/config/hall.yaml"}], "case_bindings": {}})
            self.assertEqual(store.bind_case("case_a.json", "hall")["profile_id"], "hall")
            self.assertEqual(store.load()["case_bindings"], {"case_a.json": "hall"})
            store.bind_case("case_a.json", "")
            self.assertEqual(store.load()["case_bindings"], {})
            with self.assertRaisesRegex(ScenarioSetupError, "未找到"):
                store.bind_case("case_a.json", "missing")

    def test_scenario_setup_browses_only_requested_file_type_under_controlled_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "handle_modules.sh"
            script.write_text("#!/bin/bash\n", encoding="utf-8")
            launch_dir = root / "launch"
            launch_dir.mkdir()
            (launch_dir / "demo.launch.py").write_text("# launch\n", encoding="utf-8")
            (launch_dir / "ignored.yaml").write_text("x: 1\n", encoding="utf-8")
            store = ScenarioSetupStore(root / "console")
            store.save({"startup_script": str(script), "profiles": [], "case_bindings": {}})
            launch = store.browse(str(launch_dir), "fcrp")
            self.assertEqual([item["name"] for item in launch["files"]], ["demo.launch.py"])
            self.assertEqual(store.browse(str(launch_dir), "lightning")["files"], [{"name": "ignored.yaml", "path": str((launch_dir / "ignored.yaml").resolve()), "size": (launch_dir / "ignored.yaml").stat().st_size}])
            with self.assertRaisesRegex(ScenarioSetupError, "浏览类型"):
                store.browse(str(launch_dir), "all")

    def test_scenario_setup_save_preserves_search_directories_and_selected_bindings(self):
        """方案、检索范围与人工选定参数位置必须一次原子写入并可重新读取。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "handle_modules.sh"
            script.write_text(
                "ros2 launch fcrp_bringup default.launch.py\n"
                "ros2 run lightning run_loc_online --config /opt/ry/config/default.yaml\n",
                encoding="utf-8",
            )
            profile_dir = root / "profiles"
            profile_dir.mkdir()
            candidates = ScenarioSetupStore._command_candidates(script.read_text(encoding="utf-8"))
            fcrp = next(item for item in candidates if item["package"] == "fcrp_bringup")
            lightning = next(item for item in candidates if item["package"] == "lightning")
            store = ScenarioSetupStore(root / "console")
            saved = store.save({
                "startup_script": str(script),
                "search_directories": [str(profile_dir)],
                "bindings": {
                    "fcrp": {"kind": "launch", "prefix": fcrp["prefix"]},
                    "lightning": {"kind": "config", "prefix": lightning["prefix"]},
                },
                "profiles": [{
                    "id": "elevator", "name": "电梯测试", "fcrp_launch": "elevator.launch.py",
                    "lightning_config": "/opt/ry/config/elevator.yaml",
                }],
                "case_bindings": {},
            })
            self.assertEqual(saved["search_directories"], [str(profile_dir.resolve())])
            self.assertEqual(store.load(), saved)
            on_disk = json.loads((root / "console" / "scenario_setup.json").read_text(encoding="utf-8"))
            self.assertEqual(on_disk, saved)

    def test_scenario_setup_frontend_keeps_inspection_and_serializes_search_directories(self):
        source = (Path(__file__).parents[1] / "autodrive_console" / "web" / "scenario_setup.js").read_text(encoding="utf-8")
        self.assertIn("function renderLocal()", source)
        self.assertIn("search_directories: documentState.search_directories || []", source)
        self.assertIn("result.status || await request('/api/scenario-setup')", source)
        self.assertIn("lastTransaction.state !== 'normal'", source)
        self.assertIn("selectedOccurrence", source)
        self.assertIn("occurrence: candidate.occurrence", source)
        self.assertIn("action: 'apply', profile_id: row.dataset.id, document: collect()", source)
        self.assertIn("/api/scenario-setup/activation", source)
        self.assertIn("startActivationPolling", source)
        self.assertIn("正在等待稳定", source)
        self.assertIn("$('restoreDefault').hidden", source)
        self.assertIn("工具只会恢复已登记的启动参数，不会重启任何服务。", source)
        self.assertNotIn("工具会重启相关服务并确认恢复完成。", source)
        self.assertNotIn("render({ document: documentState, inspection: {}, active_backup: null })", source)

        store_source = (Path(__file__).parents[1] / "autodrive_console" / "scenario_setup.py").read_text(encoding="utf-8")
        self.assertNotIn("retain_transaction", store_source)
        self.assertNotIn("complete_runtime_restore", store_source)
        self.assertNotIn("note_runtime_recovery_failure", store_source)

    def test_manual_scenario_apply_restarts_runtime_and_leaves_recovery_on_failure(self):
        class Gateway:
            def __init__(self, _settings):
                pass

            @staticmethod
            def restart_configured_dependencies(**_kwargs):
                return True, "定位与导航启动节点已重启并稳定 RUNNING"

        with patch.object(web_console.SCENARIO_SETUP, "save") as save, \
             patch.object(web_console.SCENARIO_SETUP, "apply", return_value={"message": "已应用场景前置方案：大厅"}) as apply, \
             patch("web_console.RobotGateway", Gateway), \
             patch.object(web_console.SETTINGS, "load", return_value=object()):
            result = web_console.apply_scenario_runtime("hall", {"profiles": []})
        save.assert_called_once()
        apply.assert_called_once_with("hall")
        self.assertIn("稳定 RUNNING", result["message"])

        class FailedGateway:
            def __init__(self, _settings):
                pass

            @staticmethod
            def restart_configured_dependencies(**_kwargs):
                return False, "MODULES:209-lightning 未稳定 RUNNING"

        with patch.object(web_console.SCENARIO_SETUP, "apply", return_value={"message": "已应用场景前置方案：大厅"}), \
             patch.object(web_console.SCENARIO_SETUP, "note_runtime_activation_failure") as note_failure, \
             patch("web_console.RobotGateway", FailedGateway), \
             patch.object(web_console.SETTINGS, "load", return_value=object()):
            with self.assertRaisesRegex(ScenarioSetupError, "未能读取新参数"):
                web_console.apply_scenario_runtime("hall")
        note_failure.assert_called_once_with("MODULES:209-lightning 未稳定 RUNNING")

    def test_manual_scenario_restore_never_constructs_robot_gateway(self):
        with patch.object(web_console.SCENARIO_SETUP, "restore", return_value={"restored": False, "message": "当前没有待恢复的场景前置配置"}) as restore, \
             patch("web_console.RobotGateway") as gateway:
            result = web_console.restore_scenario_runtime()
        restore.assert_called_once_with()
        gateway.assert_not_called()
        self.assertFalse(result["restored"])

    def test_observation_reuses_cached_map_and_discards_legacy_realtime_bridge_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = MapAssetCache(root / "maps_cache", allowed_roots=(root,))
            asset = cache.cache_occupancy_grid(
                resolution=0.25, width=2, height=2, origin=[1.0, 2.0], frame_id="map",
                data=[0, 100, -1, 50], label="实际地图",
            )
            manager = ObservationManager(root / "maps_cache", root / "logs")
            maps = manager.maps()
            self.assertEqual([item["id"] for item in maps], [asset.id])
            preview = manager.preview(asset.id)
            self.assertIn(b"<svg", preview)
            self.assertTrue((root / "maps_cache" / asset.id / "observation_preview.svg").is_file())
            preview_png = manager.preview_png(asset.id)
            self.assertTrue(preview_png.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertTrue((root / "maps_cache" / asset.id / "observation_preview.png").is_file())
            (root / "maps_cache" / asset.id / "map_walls.yaml").write_text(
                "walls:\n  - x: 1.0\n    y: 2.0\n  - x: 2.0\n    y: 3.0\n", encoding="utf-8",
            )
            layers = manager.layers(asset.id)
            self.assertEqual(layers["virtual_walls"][0]["points"], [{"x": 1.0, "y": 2.0}, {"x": 2.0, "y": 3.0}])
            self.assertEqual(layers["map"]["origin"], [1.0, 2.0, 0.0])
            self.assertEqual(layers["map"]["frame_id"], "map")
            recorder = TrajectorySession([], map_cache_dir=root / "maps_cache")
            recorder._write_active_map_marker(ActiveMap(asset.id, asset.label, 1, 0.25, 2, 2, 1.0, 2.0, "map"), 3)
            self.assertEqual(manager.active_map_id(), asset.id)
            configured = SettingsStore(root / "console.json").save({"live_observation": {"enabled": True, "bridge_host": "192.168.1.20", "bridge_port": 8766}})
            self.assertNotIn("bridge_host", configured.live_observation)
            self.assertNotIn("bridge_port", configured.live_observation)
            old_proxy_path = root / "old-proxy.json"
            old_proxy_path.write_text(json.dumps({"live_observation": {"enabled": True, "bridge_host": "127.0.0.1", "bridge_port": 8765}}), encoding="utf-8")
            self.assertNotIn("bridge_port", SettingsStore(old_proxy_path).load().live_observation)
            # 老版本只保存端口等字段；升级后必须自动补齐车型库，观测页才能安全绘制车体。
            legacy_path = root / "legacy.json"
            legacy_path.write_text(json.dumps({"live_observation": {"enabled": True, "bridge_port": 8767}}), encoding="utf-8")
            legacy = SettingsStore(legacy_path).load()
            self.assertEqual(legacy.live_observation["active_vehicle_model"], "ry-standard")
            self.assertEqual(legacy.live_observation["vehicle_models"][0]["width_m"], 0.68)
            custom = SettingsStore(root / "custom.json").save({"live_observation": {"vehicle_models": [{"id": "compact", "name": "紧凑车型", "length_m": 0.8, "width_m": 0.55}], "active_vehicle_model": "compact"}})
            self.assertEqual(custom.live_observation["active_vehicle_model"], "compact")
            manager.stop()
            with self.assertRaises(ObservationError):
                manager.preview("../not-a-map")

    def test_observation_start_is_serialized_and_stop_reaps_all_three_realtime_sidecars(self):
        """两个页面同时进入不能重复 spawn，停止路径必须 wait 三个受控子进程。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "aletheia_live_cloud"
            executable.write_text("test", encoding="utf-8")

            class FakeTelemetry:
                def __init__(self):
                    self.online = False
                    self.starts = 0
                    self.stops = 0

                def start(self):
                    self.online = True
                    self.starts += 1

                def stop(self):
                    self.online = False
                    self.stops += 1

                def status(self):
                    return {"online": self.online, "clients": {"cloud": 0, "pose": 0}}

            class FakeSnapshot:
                def __init__(self):
                    self.starts = 0
                    self.stops = 0

                def start(self):
                    self.starts += 1

                def stop(self):
                    self.stops += 1

                def status(self):
                    return {"state": "idle"}

            class FakeProcess:
                next_pid = 1000

                def __init__(self):
                    self.pid = FakeProcess.next_pid
                    FakeProcess.next_pid += 1
                    self.returncode = None
                    self.waited = False

                def poll(self):
                    return self.returncode

                def wait(self, timeout=None):
                    self.waited = True
                    self.returncode = 0
                    return 0

            manager = ObservationManager(root / "maps", root / "logs", executable)
            manager._telemetry = FakeTelemetry()
            manager._map_snapshot = FakeSnapshot()
            settings = RobotSettings(live_observation={"enabled": True, "idle_stop_seconds": 45, "vehicle_models": [], "active_vehicle_model": ""})
            created: list[FakeProcess] = []
            commands: list[list[str]] = []
            barrier = threading.Barrier(2)
            failures: list[BaseException] = []

            def enter_page():
                try:
                    barrier.wait(timeout=2)
                    manager.start(settings)
                except BaseException as exc:  # assertion after both callers return
                    failures.append(exc)

            def spawn(command, **_kwargs):
                process = FakeProcess()
                created.append(process)
                commands.append(command)
                return process

            with patch("autodrive_console.observation.subprocess.Popen", side_effect=spawn), patch("autodrive_console.observation.os.killpg"):
                first = threading.Thread(target=enter_page)
                second = threading.Thread(target=enter_page)
                first.start()
                second.start()
                first.join(timeout=5)
                second.join(timeout=5)
                self.assertFalse(first.is_alive())
                self.assertFalse(second.is_alive())
                self.assertEqual(failures, [])
                self.assertEqual(len(created), 3)
                costmap_command = next(command for command in commands if "__node:=ry_aletheia_live_costmap" in command)
                self.assertIn("enable_cloud:=false", costmap_command)
                self.assertIn("enable_pose:=false", costmap_command)
                self.assertIn("enable_costmap:=true", costmap_command)
                self.assertIn(f"telemetry_udp_port:={TelemetryGateway.COSTMAP_UDP_PORT}", costmap_command)
                manager.stop()

            self.assertTrue(all(process.waited for process in created))
            self.assertFalse(manager._telemetry.online)
            self.assertEqual(manager._map_snapshot.stops, 1)

    def test_live_observation_snapshot_caches_transient_ros_map_and_marks_it_active(self):
        """没有轨迹任务时，实时页也能从当前 /map 写入既有地图缓存。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "map_sources"
            source_root.mkdir()
            collector = ObservationMapSnapshot(root / "maps_cache")
            message = SimpleNamespace(
                header=SimpleNamespace(frame_id="map"),
                info=SimpleNamespace(
                    resolution=0.5, width=2, height=2,
                    origin=SimpleNamespace(position=SimpleNamespace(x=-1.0, y=2.0)),
                    map_load_time=SimpleNamespace(sec=12, nanosec=34),
                ),
                data=[0, 100, -1, 50],
            )
            with patch.object(MapAssetCache, "ALLOWED_ROOTS", (source_root,)):
                collector._on_map(message)
                # 同一 Transient Local 回放不能反复重写或生成新的资产。
                collector._on_map(message)
            status = collector.status()
            self.assertEqual(status["state"], "ready")
            self.assertTrue(status["active_map_id"])
            manager = ObservationManager(root / "maps_cache", root / "logs")
            self.assertEqual(manager.active_map_id(), status["active_map_id"])
            layers = manager.layers(status["active_map_id"])
            self.assertEqual(layers["map"]["origin"], [-1.0, 2.0, 0.0])
            self.assertEqual(layers["map"]["width"], 2)

    def test_live_observation_matches_map_walls_from_current_ros_map_metadata(self):
        """实时页不依赖轨迹任务，也能按实际 /map 找到同目录虚拟墙。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            maps = root / "maps" / "P2"
            maps.mkdir(parents=True)
            (maps / "map.pgm").write_bytes(b"P5\n2 2\n255\n\x00\xff\xff\x00")
            (maps / "map.yaml").write_text(
                "image: map.pgm\nresolution: 0.25\norigin: [-3.0, 1.5, 0.0]\n", encoding="utf-8",
            )
            (maps / "map_walls.yaml").write_text(
                "walls:\n  - x: -2.0\n    y: 2.0\n  - x: -1.0\n    y: 2.0\n", encoding="utf-8",
            )
            manager = ObservationManager(root / "cache", root / "logs")
            with patch.object(manager, "_map_server_yaml_path", return_value=maps / "map.yaml"), patch.object(
                MapAssetCache, "ALLOWED_ROOTS", (root / "maps",)
            ):
                # ROS OccupancyGrid 的 resolution 为 float32；浏览器经 CDR
                # 解码后会带出尾差，不能因此遗漏同目录虚拟墙。
                result = manager.live_layers({"width": 2, "height": 2, "resolution": 0.2500000037252903, "origin": [-3.0, 1.5], "frame_id": "map"})
                cached_result = manager.live_layers({"width": 2, "height": 2, "resolution": 0.25, "origin": [-3.0, 1.5], "frame_id": "map"})
            self.assertTrue(result["matched"])
            self.assertEqual(result["virtual_walls"][0]["points"], [{"x": -2.0, "y": 2.0}, {"x": -1.0, "y": 2.0}])
            self.assertEqual(cached_result, result)
            self.assertEqual(manager.active_map_id(), result["map_id"])
            self.assertEqual(manager.active_task_map_path(), (maps / "map.yaml").resolve())

    def test_live_layers_bind_a_runtime_snapshot_to_a_distinct_verified_static_map(self):
        """A /map content hash must not be mistaken for the map_server asset ID."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            maps = root / "maps" / "P2"
            maps.mkdir(parents=True)
            (maps / "map.pgm").write_bytes(b"P5\n2 2\n255\n\x00\xff\xff\x00")
            (maps / "map.yaml").write_text(
                "image: map.pgm\nresolution: 0.25\norigin: [-3.0, 1.5, 0.0]\n", encoding="utf-8",
            )
            cache_dir = root / "cache"
            cache = MapAssetCache(cache_dir, allowed_roots=(root,))
            runtime = cache.cache_occupancy_grid(
                resolution=0.25, width=2, height=2, origin=[-3.0, 1.5], frame_id="map", data=[0, 100, -1, 50],
            )
            static = cache._cache_one(maps / "map.yaml")
            self.assertNotEqual(runtime.id, static.id)
            manager = ObservationManager(cache_dir, root / "logs")
            manager._write_live_map_marker(runtime, "map")

            with patch.object(manager, "_map_server_yaml_path", return_value=maps / "map.yaml"), patch.object(
                MapAssetCache, "ALLOWED_ROOTS", (root,)
            ):
                self.assertTrue(manager.live_layers({"width": 2, "height": 2, "resolution": 0.25, "origin": [-3.0, 1.5], "frame_id": "map"})["matched"])

            self.assertEqual(manager.active_map_id(), runtime.id)
            self.assertEqual(manager.active_manual_map_id(), static.id)
            self.assertEqual(manager.active_task_map_path(), (maps / "map.yaml").resolve())

    def test_active_snapshot_without_walls_uses_verified_map_server_walls(self):
        """当前快照漏拷贝墙时，只能回退到 map_server 已验证的当前地图。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "maps" / "gk1" / "P2"
            source.mkdir(parents=True)
            (source / "map.pgm").write_bytes(b"P5\n2 2\n255\n\x00\xff\xff\x00")
            (source / "map.yaml").write_text(
                "image: map.pgm\nresolution: 0.25\norigin: [-3.0, 1.5, 0.0]\n", encoding="utf-8",
            )
            (source / "map_walls.yaml").write_text(
                "walls:\n  - x: -2.0\n    y: 2.0\n  - x: -1.0\n    y: 2.0\n", encoding="utf-8",
            )
            cache_dir = root / "cache"
            cache = MapAssetCache(cache_dir, allowed_roots=(root,))
            snapshot = cache.cache_occupancy_grid(
                resolution=0.25, width=2, height=2, origin=[-3.0, 1.5], frame_id="map", data=[0, 100, -1, 50],
            )
            historical = cache.cache_occupancy_grid(
                resolution=0.25, width=2, height=2, origin=[-3.0, 1.5], frame_id="map", data=[100, 0, 50, -1],
            )
            manager = ObservationManager(cache_dir, root / "logs")
            manager._write_live_map_marker(snapshot, "map")
            verified_source = MapAssetCache(cache_dir, allowed_roots=(root,))._cache_one(source / "map.yaml")

            with patch.object(manager, "_map_server_asset", return_value=verified_source) as map_server_asset:
                historical_layers = manager.layers(historical.id)
                layers = manager.layers(snapshot.id)

            self.assertEqual(historical_layers["virtual_walls"], [])
            self.assertEqual(layers["virtual_walls"][0]["points"], [{"x": -2.0, "y": 2.0}, {"x": -1.0, "y": 2.0}])
            map_server_asset.assert_called_once_with(
                unittest.mock.ANY, snapshot.resolution, snapshot.width, snapshot.height, snapshot.origin,
            )

    def test_task_start_map_requires_current_yaml_and_live_snapshot_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "maps" / "active"
            source.mkdir(parents=True)
            (source / "map.pgm").write_bytes(b"P5\n2 2\n255\n\x00\xff\xff\x00")
            active_yaml = source / "map.yaml"
            active_yaml.write_text("image: map.pgm\nresolution: 0.25\norigin: [-3.0, 1.5, 0.0]\n", encoding="utf-8")
            other_yaml = root / "maps" / "other.yaml"
            other_yaml.write_text("image: active/map.pgm\nresolution: 0.25\norigin: [-3.0, 1.5, 0.0]\n", encoding="utf-8")
            cache_dir = root / "cache"
            cache = MapAssetCache(cache_dir, allowed_roots=(root,))
            asset = cache._cache_one(active_yaml)
            manager = ObservationManager(cache_dir, root / "logs")
            manager._write_live_map_marker(asset, "map")
            with patch.object(manager, "_map_server_yaml_path", return_value=active_yaml), patch.object(MapAssetCache, "ALLOWED_ROOTS", (root,)):
                self.assertEqual(manager.verify_active_task_map(active_yaml), (True, "当前地图匹配"))
                self.assertEqual(manager.verify_active_task_map(other_yaml)[0], False)
            # 没有活动快照时，即使 YAML 相同也绝不放行。
            (cache_dir / "active_map.json").unlink()
            with patch.object(manager, "_map_server_yaml_path", return_value=active_yaml):
                self.assertEqual(manager.verify_active_task_map(active_yaml), (False, "当前地图尚未确认"))

    def test_map_metadata_ambiguity_never_selects_wrong_virtual_wall(self):
        """同元数据的两张地图无法安全区分时，宁可不显示虚拟墙。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("P1", "P2"):
                folder = root / name
                folder.mkdir()
                (folder / "map.pgm").write_bytes(b"P5\n2 2\n255\n\x00\xff\xff\x00")
                (folder / "map.yaml").write_text("image: map.pgm\nresolution: 0.25\norigin: [0, 0, 0]\n", encoding="utf-8")
            cache = MapAssetCache(root / "cache", allowed_roots=(root,))
            self.assertIsNone(cache.find_matching_map(resolution=0.25, width=2, height=2, origin=[0.0, 0.0]))

    def test_identical_map_and_wall_mirrors_are_safe_to_deduplicate(self):
        """发布历史留下的镜像地图可恢复相同的虚拟墙，不误认不同地图。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            map_bytes = b"P5\n2 2\n255\n\x00\xff\xff\x00"
            walls = "virtual_walls:\n  coordinate_mode: world\n  segments:\n  - start:\n    - 0\n    - 0\n    end:\n    - 1\n    - 1\n"
            for name in ("P2", "P2_mirror"):
                folder = root / name
                folder.mkdir()
                (folder / "map.pgm").write_bytes(map_bytes)
                (folder / "map.yaml").write_text("image: map.pgm\nresolution: 0.25\norigin: [0, 0, 0]\n", encoding="utf-8")
                (folder / "map_walls.yaml").write_text(walls, encoding="utf-8")
            cache = MapAssetCache(root / "cache", allowed_roots=(root,))
            asset = cache.find_matching_map(resolution=0.25, width=2, height=2, origin=[0.0, 0.0])
            self.assertIsNotNone(asset)
            self.assertEqual(MapAssetCache.virtual_walls(asset)[0]["points"], [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}])

    def test_live_observation_frontend_uses_cached_map_and_dedicated_binary_telemetry(self):
        """地图缓存和实时遥测独立，浏览器不再发现或订阅 ROS 图。"""
        source = Path("frontend/src/liveObservation.js").read_text(encoding="utf-8")
        self.assertIn("function connectTelemetry(payload)", source)
        _assert_source_contains(source, "openLane('cloud', '/cloud'")
        _assert_source_contains(source, "openLane('pose', '/pose'")
        self.assertIn("function updateTelemetryCloud(data)", source)
        self.assertIn("function updateTelemetryPose(data)", source)
        self.assertNotIn("FoxgloveClient", source)
        self.assertNotIn("/_aletheia/live_points", source)
        self.assertNotIn("function isDepthTransport(channel)", source)
        self.assertNotIn("isCameraCandidate(channel)", source)
        self.assertNotIn("原始图像（高带宽，可能增加延迟）", source)
        self.assertIn("/api/observation/active-map", source)
        self.assertIn("const ACTIVE_MAP_SYNC_MS = 1000;", source)
        self.assertIn("function invalidateMapScopedCloud()", source)
        self.assertIn("generation: mapGeneration", source)
        self.assertIn("async function refreshActiveMap(observation,", source)
        self.assertIn("if (!mapId || mapId === loadedMapId || mapId === requestedActiveMapId) return;", source)
        self.assertIn("const POINT_LIMIT = 3000;", source)
        self.assertIn("const CLOUD_COMPOSITE_MIN_INTERVAL_MS = 125;", source)
        # PixiJS 世界容器仅更新相机矩阵，可按显示帧合成而不重绘栅格。
        self.assertIn("const MAP_RENDER_INTERVAL_MS = 16;", source)
        # 位姿已不再走 TF/通用协议：只消费专用二进制帧并保持单槽 latest-wins。
        self.assertIn("const TELEMETRY_HEADER_BYTES = 20;", source)
        self.assertIn("const POSE_PACKET_MAX_AGE_MS = 250;", source)
        # 点云历史只保留极短窗口，避免与地图交互争用浏览器主线程。
        _assert_source_contains(source, "import { Application, BufferImageSource, Container, Graphics, Sprite, Texture } from 'pixi.js';")
        self.assertIn("async function initializePixiRenderer()", source)
        self.assertIn("new ResizeObserver(resizeMapViewport).observe(interaction.parentElement);", source)
        _assert_source_contains(source, "lastMapDrawAt = performance.now(); drawMap();")
        self.assertIn("function rebuildCloudRaster()", source)
        self.assertIn("function renderCloudPoints(packedPoints)", source)
        self.assertIn("function renderStaticWorld()", source)
        self.assertIn("pixiWorld.scale.set(layout.ratio, layout.ratio);", source)
        self.assertNotIn("cameraChannels", source)
        self.assertNotIn("cameraSlots", source)
        self.assertNotIn("async function initializeCameraRenderer(slot)", source)
        self.assertNotIn("function presentCameraTexture(slot, texture, width, height, imageBitmap)", source)
        self.assertNotIn("getContext('2d')", source)
        _assert_source_contains(source, "points.fill((mobileConsoleEnabled() ? MAP_PALETTE : DESKTOP_MAP_PALETTE).cloud);")
        self.assertIn("const DESKTOP_MAP_PALETTE", source)
        _assert_source_contains(source, "pixiWorld.addChild(pixiMapLayer, pixiGridLayer, pixiCostmapLayer, pixiWallLayer, pixiNavigationRouteLayer, pixiMapMarkerLayer, pixiCloudLayer);")
        _assert_source_contains(source, "openLane('costmap', '/costmap'")
        self.assertIn("function updateTelemetryCostmap(data)", source)
        self.assertIn("if (!mobileConsoleEnabled())", source)
        self.assertNotIn("liveCloudWorker", source)
        self.assertIn("function followVehicleCenter(vehicle)", source)
        self.assertIn("function hasPendingFollowAdjustment()", source)
        self.assertIn("const FOLLOW_CENTER_SETTLE_DISTANCE_M = 0.008;", source)
        self.assertIn("rotation: 0,", source)
        self.assertIn("const localYaw = Math.PI / 2 - vehicle.yaw;", source)
        self.assertIn("function requestFollowAnimation()", source)
        self.assertIn("!hasPendingFollowAdjustment()", source)
        self.assertIn("PixiJS 仅更新世界容器矩阵", source)
        self.assertIn("function stopRenderScheduling()", source)
        _assert_source_contains(source, "document.addEventListener('visibilitychange'")
        self.assertIn("function vehiclePoseInMap()", source)
        self.assertIn("function flushCloudRenderer()", source)
        self.assertIn("pendingCloudFrame = frame;", source)
        server_source = Path("web_console.py").read_text(encoding="utf-8")
        self.assertIn('path == "/api/observation/active-map"', server_source)

    def test_ros_map_cache_is_independent_of_invalid_json_map_url(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "园区_1_2_3_4.json"
            task.write_text(json.dumps({"subtasks": [{"map_url": "/wrong/map.yaml", "waypoints": [
                {"pose": {"position": {"x": 1, "y": 2}}}, {"pose": {"position": {"x": 3, "y": 4}}},
            ]}]}), encoding="utf-8")
            cache = MapAssetCache(root / "cache", allowed_roots=(root,))
            self.assertEqual(cache.prepare(str(task)), [])
            plan = cache.route_plan(str(task), [])
            self.assertEqual(plan[0]["map_id"], None)
            self.assertEqual(len(plan[0]["points"]), 2)
            asset = cache.cache_occupancy_grid(
                resolution=0.5, width=2, height=2, origin=[-1.0, -2.0], frame_id="map",
                data=[0, 100, -1, 50], label="ROS 实际地图",
            )
            self.assertEqual(MapAssetCache._pgm_dimensions(Path(asset.cache_image)), (2, 2))
            # OccupancyGrid 从左下开始；PGM 文件的第一行必须是原始数据的上行。
            self.assertEqual(Path(asset.cache_image).read_bytes().split(b"255\n", 1)[1], bytes([205, 127, 254, 0]))
            self.assertEqual(asset.origin, [-1.0, -2.0, 0.0])

    def test_tool_logs_keep_error_stream_independent_and_read_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ToolLogStore(Path(directory))
            store.file(False).write_text(
                '{"time":"2026-08-14 10:00:00","level":"INFO","source":"run","message":"计划开始"}\n'
                '{"time":"2026-08-14 10:01:00","level":"ERROR","source":"run","message":"服务异常"}\n', encoding="utf-8")
            store.file(True).write_text(
                '{"time":"2026-08-14 10:01:00","level":"ERROR","source":"run","message":"服务异常"}\n', encoding="utf-8")
            self.assertEqual(len(store.entries()), 2)
            errors = store.entries(errors_only=True)
            self.assertEqual(errors, [{"time": "2026-08-14 10:01:00", "level": "ERROR", "source": "run", "message": "服务异常"}])

            store.file(True).write_text(
                '{"time":"2026-08-14 10:02:00","level":"CRITICAL","source":"console","message":"未处理异常","exception":"Traceback: detail"}\n', encoding="utf-8",
            )
            self.assertEqual(store.entries(errors_only=True)[0]["exception"], "Traceback: detail")
            (Path(directory) / "video-runtime.log").write_text("native encoder detail\n", encoding="utf-8")
            (Path(directory) / "live_preprocessor_cloud.log").write_text("cloud udp detail\n", encoding="utf-8")
            (Path(directory) / "live_preprocessor_costmap.log").write_text("costmap TF detail\n", encoding="utf-8")
            self.assertEqual(
                [path.name for path in store.diagnostic_files()],
                ["ry-aletheia.log", "ry-aletheia-error.log", "live_preprocessor_cloud.log", "live_preprocessor_costmap.log", "video-runtime.log"],
            )
            records = store.diagnostic_records()
            self.assertEqual(records[-1]["name"], "video-runtime.log")
            self.assertEqual(records[-1]["label"], "视频运行时")
            self.assertEqual(store.diagnostic_file("video-runtime.log"), Path(directory) / "video-runtime.log")
            self.assertIsNone(store.diagnostic_file("../../etc/passwd"))
        handler = object.__new__(web_console.ConsoleHandler)
        handler._json = Mock()
        handler.send_error = Mock()
        handler._download_diagnostic_file(None)
        handler._json.assert_called_once_with({"error": "诊断日志不存在"}, HTTPStatus.NOT_FOUND)
        console_source = Path("web_console.py").read_text(encoding="utf-8")
        self.assertIn("LOGS.diagnostic_files()", console_source)
        self.assertIn("ry-aletheia-diagnostics.zip", console_source)
        self.assertIn('path == "/api/tool-logs/files"', console_source)
        self.assertIn("LOGS.diagnostic_records()", console_source)
        self.assertIn("_download_diagnostic_file", console_source)
        log_page = (Path("autodrive_console") / "web" / "tool-logs.html").read_text(encoding="utf-8")
        log_script = (Path("autodrive_console") / "web" / "tool-logs.js").read_text(encoding="utf-8")
        self.assertIn('id="diagnosticFileList"', log_page)
        self.assertIn("下载完整诊断包", log_page)
        self.assertIn("/api/tool-logs/files", log_script)
        self.assertIn("encodeURIComponent(file.name)", log_script)

    def test_upgrade_status_caches_version_without_scanning_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "ry-aletheia"
            binary.write_bytes(b"first binary")
            (root / "VERSION").write_text("0.1\n", encoding="utf-8")
            manager = UpgradeManager(root, binary, True)
            self.assertEqual(manager.status()["current_version"], "0.1")
            self.assertNotIn("current_md5", manager.status())
            (root / "VERSION").write_text("0.2\n", encoding="utf-8")
            self.assertEqual(manager.status()["current_version"], "0.1")
            self.assertEqual(UpgradeManager(root, binary, True).status()["current_version"], "0.2")

    def test_upgrade_status_exposes_pending_scenario_recovery_before_upload(self):
        """升级页必须在选包前指出场景恢复锁，而不是上传后才返回 409。"""
        transaction = {
            "state": "applied",
            "message": "待恢复：玻璃长廊场景 已于 2026-09-30T10:49:43+08:00 应用。",
            "restore_available": True,
        }
        with patch.object(web_console.UPGRADES, "status", return_value={"supported": True, "current_version": "2.5.6"}), patch.object(
            web_console.RUNS, "has_active_run", return_value=False
        ), patch.object(web_console.SCENARIO_SETUP, "has_unresolved_transaction", return_value=True), patch.object(
            web_console.SCENARIO_SETUP, "status", return_value={"transaction": transaction}
        ):
            status = web_console._upgrade_status()

        self.assertEqual(
            status["availability"],
            {
                "ready": False,
                "blocker": {
                    "kind": "scenario_recovery",
                    "message": "待恢复：玻璃长廊场景 已于 2026-09-30T10:49:43+08:00 应用。",
                    "action_label": "前往恢复常规配置",
                    "action_url": "/scenario-setup.html",
                },
            },
        )

    def test_upgrade_refuses_an_unbootable_candidate_before_replacing_current_program(self):
        """签名完整但无法启动的单文件程序不得覆盖当前可用控制台。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "ry-aletheia"
            executable.write_bytes(b"current program")
            candidate = b"signed but unbootable program"
            manifest, test_public_key = _signed_upgrade_manifest(candidate)
            archive = root / "candidate.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("manifest.json", json.dumps(manifest))
                bundle.writestr("ry-aletheia", candidate)
            manager = UpgradeManager(root, executable, True)
            with patch.object(upgrade_signature, "RELEASE_PUBLIC_KEY_B64", test_public_key), patch(
                "autodrive_console.upgrade_manager.subprocess.run",
                return_value=subprocess.CompletedProcess([], 1, "", "PYZ archive entry not found"),
            ):
                with self.assertRaisesRegex(UpgradeError, "无法启动"):
                    manager.apply(io.BytesIO(archive.read_bytes()), archive.stat().st_size, "candidate.zip")
            self.assertEqual(executable.read_bytes(), b"current program")

    def test_self_check_does_not_source_robot_environment(self):
        """升级检查必须在 ROS 环境重启之前返回，避免把运行时初始化计入超时。"""
        with tempfile.TemporaryDirectory() as directory:
            setup = Path(directory) / "slow-robot-setup.bash"
            setup.write_text("exit 93\n", encoding="utf-8")
            environment = {
                **os.environ,
                "ROVER_QA_SETUP_SCRIPT": str(setup),
            }
            environment.pop("ROVER_QA_ROS_READY", None)
            environment.pop("ROVER_QA_ROS_ENV_REEXEC", None)
            environment.pop("AMENT_PREFIX_PATH", None)
            environment.pop("LD_LIBRARY_PATH", None)
            result = subprocess.run(
                [sys.executable, str(Path("web_console.py").resolve()), "--self-check"],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RY Aletheia self-check OK", result.stdout)

    def test_upgrade_boot_check_timeout_hides_internal_command_details(self):
        """升级页面的失败消息不应暴露暂存路径或 subprocess 命令。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "updates" / "staging" / "upload-secret" / "ry-aletheia"
            candidate.parent.mkdir(parents=True)
            candidate.write_bytes(b"candidate")
            manager = UpgradeManager(root, root / "ry-aletheia", True)
            with patch(
                "autodrive_console.upgrade_manager.subprocess.run",
                side_effect=subprocess.TimeoutExpired([str(candidate), "--self-check"], 12),
            ):
                with self.assertRaises(UpgradeError) as raised:
                    manager._verify_candidate_bootable(candidate)

        message = str(raised.exception)
        self.assertIn("启动检查超时", message)
        self.assertNotIn(str(candidate), message)
        self.assertNotIn("Command", message)

    def test_upgrade_frontend_waits_for_the_requested_version_before_reloading(self):
        """旧服务 shutdown 排队期间仍能返回 200，不能据此误判新版本已启动。"""
        source = Path("frontend/src/main.js").read_text(encoding="utf-8")
        self.assertIn('function waitForUpgradeRestart(expectedVersion, previousVersion = "")', source)
        _assert_source_contains(source, "currentVersion === String(expectedVersion)")
        self.assertIn("waitForUpgradeRestart(data.version)", source)

    def test_upgrade_frontend_probes_after_a_post_upload_disconnect(self):
        """重启切断 XHR 时应继续确认版本，不能直接误报“未确认替换”。"""
        source = Path("frontend/src/main.js").read_text(encoding="utf-8")
        _assert_source_contains(source, "const previousVersion = String(upgrade.value.current_version || '');")
        _assert_source_contains(source, "waitForUpgradeRestart('', previousVersion)")
        self.assertIn("升级连接中断，正在确认新版本是否已启动。", source)

    def test_upgrade_restart_uses_systemd_for_user_service_autostart(self):
        """systemd 自启必须由服务管理器重启，不能把子进程留在旧 cgroup。"""
        workspace = Path("/tmp/ry-aletheia-upgrade-workspace")
        executable = workspace / "dist" / "ry-aletheia"
        with patch.dict(os.environ, {"INVOCATION_ID": "test-invocation"}, clear=False), patch(
            "web_console.subprocess.run", return_value=subprocess.CompletedProcess([], 0)
        ) as runner, patch("web_console.subprocess.Popen") as popen, patch(
            "web_console._is_systemd_service_context", return_value=True
        ):
            self.assertTrue(web_console._spawn_upgrade_restart(workspace, executable))
        runner.assert_called_once_with(
            ["systemctl", "--user", "restart", "--no-block", "ry-aletheia.service"],
            cwd=workspace,
            env=runner.call_args.kwargs["env"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        popen.assert_not_called()
        self.assertNotIn("INVOCATION_ID", runner.call_args.kwargs["env"])

    def test_upgrade_restart_does_not_treat_a_terminal_as_the_console_service(self):
        """终端也可能继承 INVOCATION_ID，实际 cgroup 才能确认服务归属。"""
        with patch.dict(os.environ, {"INVOCATION_ID": "terminal-inherited"}, clear=False):
            self.assertFalse(
                web_console._is_systemd_service_context(
                    lambda: "0::/user.slice/user-1000.slice/user@1000.service/app.slice/vte-spawn.scope\\n"
                )
            )
            self.assertTrue(
                web_console._is_systemd_service_context(
                    lambda: "0::/user.slice/user-1000.slice/user@1000.service/app.slice/ry-aletheia.service\\n"
                )
            )

    def test_upgrade_restart_falls_back_to_direct_spawn_for_terminal_with_invocation_id(self):
        """误继承的 INVOCATION_ID 不能把终端控制台送入错误的 systemd 重启路径。"""
        workspace = Path("/tmp/ry-aletheia-upgrade-workspace")
        executable = workspace / "dist" / "ry-aletheia"
        with patch.dict(os.environ, {"INVOCATION_ID": "terminal-inherited"}, clear=False), patch(
            "web_console._is_systemd_service_context", return_value=False
        ), patch("web_console.subprocess.run") as runner, patch("web_console.subprocess.Popen") as popen:
            self.assertTrue(web_console._spawn_upgrade_restart(workspace, executable))
        runner.assert_not_called()
        popen.assert_called_once()

    def test_upgrade_restart_keeps_direct_spawn_for_non_systemd_launch(self):
        """终端/桌面启动没有 systemd 服务上下文时仍直接拉起新二进制。"""
        workspace = Path("/tmp/ry-aletheia-upgrade-workspace")
        executable = workspace / "dist" / "ry-aletheia"
        with patch.dict(os.environ, {}, clear=True), patch("web_console.subprocess.Popen") as popen:
            self.assertTrue(web_console._spawn_upgrade_restart(workspace, executable))
        popen.assert_called_once_with(
            [str(executable)],
            cwd=workspace,
            env=popen.call_args.kwargs["env"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def test_case_library_accepts_valid_case_and_reports_invalid_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "园区_1_2_3_4.json").write_text("{}", encoding="utf-8")
            (root / "不符合命名.json").write_text("{}", encoding="utf-8")
            (root / "园区_1_2_3_5.json").write_text("{", encoding="utf-8")
            cases, issues = CaseStore(root).list_cases()

        self.assertEqual([item.filename for item in cases], ["园区_1_2_3_4.json"])
        self.assertEqual(len(issues), 2)
        self.assertTrue(any("文件名应为" in item["message"] for item in issues))
        self.assertTrue(any("JSON 格式错误" in item["message"] for item in issues))

    def test_uploaded_case_uses_same_filename_and_json_validation(self):
        case = CaseStore.parse_case("高科一号_1_1_15_0.json", '{"tasks": []}')
        self.assertEqual(case.parameters.community, "高科一号")
        self.assertEqual(case.parameters.floor, 15)
        with self.assertRaisesRegex(ValueError, "文件名应为"):
            CaseStore.parse_case("unsafe.json", '{}')
        with self.assertRaisesRegex(ValueError, "JSON 格式错误"):
            CaseStore.parse_case("高科一号_1_1_15_0.json", "{")

    def test_settings_persist_preferences_and_reject_duplicate_dependency_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "console.json")
            saved = store.save({
                "case_aliases": {"园区_1_2_3_4.json": "电梯往返"},
                "ui_preferences": {"case_id": "园区_1_2_3_4.json", "count": 3, "interval_seconds": 2},
                "monitor_nodes": ["NODE:1"],
                "elevator_wait_timeout_s": 240,
                "task_execution_timeout_s": 1200,
                "dependency_plan": {"enabled": True, "steps": [{"nodes": ["NODE:1"], "wait_seconds": 0}]},
            })
            self.assertEqual(saved.case_aliases["园区_1_2_3_4.json"], "电梯往返")
            self.assertEqual(store.load().elevator_wait_timeout_s, 240)
            self.assertEqual(store.load().task_execution_timeout_s, 1200)
            with self.assertRaisesRegex(ValueError, "只能出现在一个启动步骤"):
                store.save({"dependency_plan": {"enabled": True, "steps": [{"nodes": ["NODE:1"]}, {"nodes": ["NODE:1"]}]}})

    def test_vehicle_control_parameters_persist_and_reject_unsafe_values(self):
        """底盘参数必须跨重启保留，且不能写入超过底盘约束的值。"""
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "console.json")
            saved = store.save({"vehicle_control": {
                "press": 20,
                "movement_acc": 1000,
                "stop_acc": 2000,
            }})

            self.assertEqual(saved.vehicle_control["movement_acc"], 1000)
            self.assertEqual(store.load().vehicle_control["press"], 20)
            with self.assertRaisesRegex(ValueError, "运动加速度"):
                store.save({"vehicle_control": {
                    "press": 1400,
                    "movement_acc": 1001,
                    "stop_acc": 1200,
                }})
            store.path.write_text(json.dumps({"vehicle_control": {"press": 1400, "movement_acc": 1001, "stop_acc": 1200}}), encoding="utf-8")
            self.assertEqual(store.load().vehicle_control["movement_acc"], 1000)

    def test_manual_control_exposes_emergency_state_and_bounded_chassis_parameters(self):
        """正式控制页必须可见急停真值、解除入口及浏览器侧参数边界。"""
        page = (web_console.WEB_ROOT / "manual-control.html").read_text(encoding="utf-8")
        script = (web_console.WEB_ROOT / "manual_control.js").read_text(encoding="utf-8")

        self.assertIn('id="emergencyStopState"', page)
        self.assertIn('id="releaseEmergencyStop"', page)
        self.assertRegex(page, r'id="movementAcc"[^>]*min="10"[^>]*max="1000"')
        self.assertRegex(page, r'id="stopAcc"[^>]*min="20"[^>]*max="2000"')
        self.assertIn("/api/vehicle-control/release-emergency-stop", script)
        self.assertIn("/api/vehicle-control/chassis-parameters", script)
        self.assertIn("/api/vehicle-control/navigation", script)
        self.assertIn('requestNavigation.hidden = Boolean(sessionId) || state.actual_source === "navigation";', script)
        self.assertIn("car_state_sync", script)
        self.assertIn("正在读取车端状态", script)
        self.assertIn("已由车端确认切换至", script)
        self.assertLess(script.index("if (pending) {"), script.index('if (state === "normal")'))

    def test_failed_round_recovery_exposes_manual_control_entry(self):
        """现场必须能从等待人工恢复状态直接进入手动控制页面。"""
        page = (web_console.WEB_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="recoveryAction"', page)
        self.assertIn('href="/manual-control.html"', page)
        self.assertIn("退出手动控制，再点击继续", page)

    def test_console_prewarms_vehicle_control_after_port_ownership_before_requests(self):
        """首个浏览器请求不应承担预热，同时端口冲突不得启动 ROS 线程。"""
        source = Path("web_console.py").read_text(encoding="utf-8")
        script = (web_console.WEB_ROOT / "manual_control.js").read_text(encoding="utf-8")
        self.assertLess(source.index("server = ThreadingHTTPServer"), source.index("VEHICLE_CONTROL.start()"))
        self.assertLess(source.index("VEHICLE_CONTROL.start()"), source.index("server.serve_forever()"))
        self.assertIn("外部控制源", script)

    def test_manual_control_uses_paired_range_and_numeric_inputs_for_every_tunable_value(self):
        """现场人员应能拖动粗调，也能直接输入精确值，且五项参数使用同一交互模型。"""
        page = (web_console.WEB_ROOT / "manual-control.html").read_text(encoding="utf-8")
        script = (web_console.WEB_ROOT / "manual_control.js").read_text(encoding="utf-8")

        for element_id in (
            "linearSpeedNumber",
            "angularSpeedNumber",
            "chassisPressRange",
            "movementAccRange",
            "stopAccRange",
        ):
            self.assertIn(f'id="{element_id}"', page)
        self.assertIn("syncPairedParameter", script)
        self.assertIn("setChassisParametersDirty", script)

    def test_task_sync_never_overwrites_robot_existing_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            source.write_text('{"source":true}', encoding="utf-8")
            destination_dir = root / "robot_tasks"
            destination_dir.mkdir()
            destination = destination_dir / "园区_1_2_3_4.json"
            destination.write_text('{"robot":"original"}', encoding="utf-8")
            settings = RobotSettings(task_directory=str(destination_dir))
            case = TestCase("园区_1_2_3_4.json", destination.name, "测试", TaskParameters("园区", 1, 2, 3, 4), str(source))
            ok, message = RobotGateway(settings)._sync_if_missing(case)
            contents = destination.read_text(encoding="utf-8")

        self.assertTrue(ok)
        self.assertIn("未覆盖", message)
        self.assertEqual(contents, '{"robot":"original"}')

    def test_supervisor_parser_and_control_command_boundary(self):
        client = _SupervisorClient("sudo -n supervisorctl status", 1)
        processes = client.discover()
        self.assertEqual([(item.name, item.status) for item in processes], [("NODE:1", "RUNNING"), ("NODE:2", "STOPPED")])
        with self.assertRaisesRegex(RuntimeError, "节点名称不合法"):
            client.restart("NODE:1 invalid")
        with self.assertRaisesRegex(RuntimeError, "节点名称不合法"):
            client.start("--all")
        with self.assertRaisesRegex(RuntimeError, "必须以 status 结尾"):
            SupervisorClient("supervisorctl restart", 1)._base_args()

    def test_supervisor_stdout_tail_uses_only_the_precise_program_and_stdout_stream(self):
        """实时日志不可退化为通配的 Supervisor 命令或 stderr 流。"""

        with patch("autodrive_console.supervisor.subprocess.Popen") as popen:
            SupervisorClient("sudo -n supervisorctl status", 1).tail_stdout("DRIVERS:104-livox_lidar")

        popen.assert_called_once_with(
            ["sudo", "-n", "supervisorctl", "tail", "-f", "DRIVERS:104-livox_lidar", "stdout"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            bufsize=0,
        )
        with self.assertRaisesRegex(RuntimeError, "节点名称不合法"):
            SupervisorClient("sudo -n supervisorctl status", 1).tail_stdout("DRIVERS:* stdout")

    def test_supervisor_sudoers_are_scoped_to_declared_programs(self):
        postinst = Path("packaging/debian/postinst").read_text(encoding="utf-8")
        self.assertIn("SUPERVISOR_NODES=(", postinst)
        self.assertIn("SUPERVISOR_NODES+=(\"$node\")", postinst)
        self.assertIn('sudoers_node="${node//:/\\\\:}"', postinst)
        self.assertIn("%s start %s, %s restart %s", postinst)
        self.assertIn("%s tail -f %s stdout", postinst)
        self.assertIn('"$SUPERVISORCTL" status', postinst)
        self.assertNotIn("%s start *, %s restart *", postinst)
        self.assertNotIn("%s tail -f * stdout", postinst)
        self.assertIn("systemctl disable ry-aletheia.service", postinst)
        self.assertNotIn("systemctl disable --now ry-aletheia.service", postinst)

    def test_upgrade_package_validation_and_report_path_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "VERSION").write_text("0.1\n", encoding="utf-8")
            binary = b"valid binary payload"
            manifest, test_public_key = _signed_upgrade_manifest(binary)
            archive = root / "valid.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("manifest.json", json.dumps(manifest))
                bundle.writestr("ry-aletheia", binary)
            manager = UpgradeManager(root, root / "ry-aletheia", True)
            with patch.object(upgrade_signature, "RELEASE_PUBLIC_KEY_B64", test_public_key):
                self.assertEqual(manager.status()["current_version"], "0.1")
                manifest_result, extracted = manager._validate_package(archive, root)
                self.assertEqual(manifest_result["version"], "0.2")
                self.assertEqual(extracted.read_bytes(), binary)

                bad = root / "bad.zip"
                with zipfile.ZipFile(bad, "w") as bundle:
                    bundle.writestr("manifest.json", json.dumps(manifest))
                    bundle.writestr("ry-aletheia", binary)
                    bundle.writestr("unexpected.txt", "x")
                with self.assertRaisesRegex(UpgradeError, "只能包含"):
                    manager._validate_package(bad, root)

                tampered_manifest = json.loads(json.dumps(manifest))
                tampered_manifest["version"] = "0.3"
                signed_but_tampered = root / "tampered.zip"
                with zipfile.ZipFile(signed_but_tampered, "w") as bundle:
                    bundle.writestr("manifest.json", json.dumps(tampered_manifest))
                    bundle.writestr("ry-aletheia", binary)
                with self.assertRaisesRegex(UpgradeError, "发布签名校验失败"):
                    manager._validate_package(signed_but_tampered, root)

                previous_binary = b"previous binary payload"
                (root / "ry-aletheia").write_bytes(previous_binary)
                old_backups = root / "updates" / "backups"
                old_backups.mkdir(parents=True)
                (old_backups / "ry-aletheia_older.bak").write_bytes(b"obsolete")
                with patch(
                    "autodrive_console.upgrade_manager.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0),
                ):
                    result = manager.apply(io.BytesIO(archive.read_bytes()), archive.stat().st_size, archive.name)
                self.assertEqual(result["version"], "0.2")
                self.assertEqual((root / "ry-aletheia").read_bytes(), binary)
                backups = list(old_backups.glob("*.bak"))
                self.assertEqual([item.name for item in backups], ["ry-aletheia.bak"])
                self.assertEqual(backups[0].read_bytes(), previous_binary)

            reports = root / "reports"
            reports.mkdir()
            report = reports / "run_123456789abc_case.html"
            report.write_text("ok", encoding="utf-8")
            readable_report = reports / "报告_20260814_111530_电梯往返验证_123456789abc.html"
            readable_report.write_text("ok", encoding="utf-8")
            with patch.object(web_console, "WORKSPACE", root):
                self.assertEqual(web_console.ConsoleHandler._archive_report_target(report.name), report)
                self.assertEqual(web_console.ConsoleHandler._archive_report_target(readable_report.name), readable_report)
                with self.assertRaises(ValueError):
                    web_console.ConsoleHandler._archive_report_target("../run_123456789abc_case.html")

    def test_downloadable_report_inlines_trajectory_svg(self):
        """下载的 HTML 不能依赖 reports/ 下的旁路 SVG 文件。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_dir = root / "reports"
            trajectory_dir = report_dir / "run_123456789abc_trajectory"
            trajectory_dir.mkdir(parents=True)
            svg = trajectory_dir / "T-001_map.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,AA=="/></svg>', encoding="utf-8")
            case = TestCase("园区_1_2_3_4.json", "园区_1_2_3_4.json", "测试", TaskParameters("园区", 1, 2, 3, 4), "unused.json")
            run = RunRecord("123456789abc", case, 1, 0, status="completed", started_at="2026-08-13T09:00:00+08:00", finished_at="2026-08-13T09:01:00+08:00")
            run.attempts.append(AttemptResult(1, "passed", "服务成功", 60.0, run.started_at, {"visualizations": [{"map_id": "map", "label": "测试地图", "file": str(svg)}], "segments": [{"map_id": "map", "map": {"resolution": 1, "width": 10, "height": 10, "origin": [0, 0]}, "points": [{"x": 1, "y": 2, "timestamp_ns": 1755046800000000000}]}]}, relocalization_count=2))
            settings = SettingsStore(root / "console.json")
            settings.save({"case_aliases": {case.id: "电梯往返验证"}})
            manager = RunManager(report_dir, object(), settings)
            target = report_dir / "run_123456789abc_园区_1_2_3_4.html"
            manager._write_html_report(run, target, "unused.csv")
            contents = target.read_text(encoding="utf-8")

        self.assertIn('<svg xmlns="http://www.w3.org/2000/svg">', contents)
        self.assertIn("data:image/png;base64,AA==", contents)
        self.assertNotIn(str(svg), contents)
        self.assertIn("用例：电梯往返验证", contents)
        self.assertIn("2026-08-13 09:00:00", contents)
        self.assertNotIn("2026-08-13T09:00:00+08:00", contents)
        self.assertIn('class="report-shell"', contents)
        self.assertIn('class="report-summary"', contents)
        self.assertIn('class="status-badge completed"', contents)
        self.assertIn('trajectory-report-tooltip', contents)
        self.assertIn('data-trajectory-points', contents)
        self.assertIn('>采样点 ${nearest.point.sample_index}', contents)
        self.assertNotIn('磁吸采样点', contents)
        self.assertIn('border: 1px solid rgba(91,186,255,.72)', contents)
        self.assertIn('background: rgba(8,18,31,.92)', contents)
        self.assertIn("重定位次数", contents)
        self.assertIn("本次运行累计", contents)
        self.assertIn("<td>2</td>", contents)
        self.assertNotIn('偏差', contents)
        self.assertIn("@media print", contents)
        self.assertIn("print-color-adjust: exact", contents)
        self.assertNotIn("https://", contents)

    def test_saved_round_trajectory_propagates_relocalization_marker_to_its_map(self):
        """A reset event must render only on the matching evidence map."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "map.pgm"
            image.write_bytes(b"P5\n10 10\n255\n" + bytes([255]) * 100)
            report_dir = root / "reports"
            settings = SettingsStore(root / "console.json")
            case = TestCase("case", "case.json", "测试", TaskParameters("园区", 1, 1, 1, 1), "unused.json")
            run = RunRecord("123456789abc", case, 1, 0)
            asset = CachedMapAsset("map", "P1", "", "", str(image), 1.0, [0.0, 0.0], 10, 10)
            trajectory = {
                "route_plan": [],
                "segments": [{"map_id": "map", "map_label": "P1", "map_epoch": 1, "route_index": 0, "points": [{"x": 1, "y": 1, "timestamp_ns": 1}]}],
                "relocalizations": [{"map_id": "map", "x": 1, "y": 1, "position_available": True}],
            }

            trajectory_file = RunManager(report_dir, object(), settings)._write_trajectory(run, 1, trajectory, [asset])
            svg = next((report_dir / "run_123456789abc_trajectory").glob("*.svg")).read_text(encoding="utf-8")
            saved = json.loads(trajectory_file.read_text(encoding="utf-8"))
            frozen = saved["frozen_maps"]
            frozen_png = trajectory_file.parent / frozen[0]["filename"]
            frozen_body = frozen_png.read_bytes()

        self.assertIn('class="relocalization-marker"', svg)
        self.assertEqual(frozen[0]["map_id"], "map")
        self.assertTrue(frozen_body.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_new_test_report_archives_native_sidecar_after_html_and_csv(self):
        """The Mobile payload must be written only after legacy report files exist."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "map.pgm"
            image.write_bytes(b"P5\n2 2\n255\n\xff\x00\xff\x00")
            report_dir = root / "reports"
            settings = SettingsStore(root / "console.json")
            case = TestCase("case", "case.json", "测试", TaskParameters("园区", 1, 1, 1, 1), "unused.json")
            run = RunRecord("123456789abc", case, 1, 0, status="completed", started_at="2026-09-28T10:00:00+08:00")
            trajectory = {
                "route_plan": [],
                "segments": [{"map_id": "map", "map_label": "P1", "route_name": "去程", "points": [{"x": 0, "y": 0, "timestamp_ns": 1}]}],
            }
            run.attempts.append(AttemptResult(1, "passed", "服务成功", 1.5, run.started_at, trajectory))
            manager = RunManager(report_dir, object(), settings)
            manager._write_trajectory(
                run,
                1,
                trajectory,
                [CachedMapAsset("map", "P1", "", "", str(image), 1.0, [0.0, 0.0], 2, 2)],
            )

            manager._write_report(run)

            html = next(report_dir.glob("*.html"))
            self.assertTrue(html.with_suffix(".csv").is_file())
            self.assertIsNotNone(NativeReportArchive(report_dir).summary_for_filename(html.name))

    def test_native_report_detail_route_returns_only_structured_archive_data(self):
        """Native report routes must never fall through to static report files."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_dir = root / "reports"
            report_dir.mkdir()
            html = report_dir / "报告_20260928_100001_测试_123456789abc.html"
            html.write_text("do not parse this HTML", encoding="utf-8")
            trajectory_dir = report_dir / "run_123456789abc_trajectory"
            trajectory_dir.mkdir()
            trajectory_dir.joinpath("T-001.json").write_text(
                json.dumps({"segments": []}, ensure_ascii=False), encoding="utf-8"
            )
            archive = NativeReportArchive(report_dir)
            self.assertTrue(archive.archive_historic_report(html.name))
            report_id = archive.summary_for_filename(html.name)["report_id"]
            with patch.object(web_console, "WORKSPACE", root):
                index = web_console.ConsoleHandler._reports()
            self.assertEqual(set(index[0]).difference({"native_report"}), {
                "filename", "size", "modified_at", "csv_filename", "report_type", "title"
            })
            self.assertEqual(index[0]["native_report"]["report_id"], report_id)
            handler = object.__new__(web_console.ConsoleHandler)
            handler.path = f"/api/reports/{report_id}/native?limit=1"
            handler.headers = {"User-Agent": "desktop-test"}
            handler._json = Mock()
            handler.send_error = Mock()

            with patch.object(web_console, "WORKSPACE", root):
                handler.do_GET()

            handler._json.assert_called_once()
            payload = handler._json.call_args.args[0]
            self.assertEqual(payload["report"]["report_id"], report_id)
            self.assertNotIn("报告_", json.dumps(payload, ensure_ascii=False))

    def test_native_report_route_distinguishes_invalid_input_from_missing_report(self):
        """Mobile needs a stable 400/404 split without a report-directory leak."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reports").mkdir()
            handler = object.__new__(web_console.ConsoleHandler)
            handler.headers = {"User-Agent": "mobile-test"}
            handler._json = Mock()

            handler.path = "/api/reports/not%2Fa%2Ftoken/native?limit=0"
            with patch.object(web_console, "WORKSPACE", root):
                handler.do_GET()
            self.assertEqual(handler._json.call_args.args[1], HTTPStatus.BAD_REQUEST)

            handler._json.reset_mock()
            handler.path = "/api/reports/rpt_missing/native"
            with patch.object(web_console, "WORKSPACE", root):
                handler.do_GET()
            self.assertEqual(handler._json.call_args.args[1], HTTPStatus.NOT_FOUND)

    def test_native_report_map_route_returns_only_the_report_scoped_frozen_png(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_dir = root / "reports"
            report_dir.mkdir()
            filename = "报告_20260928_100001_测试_123456789abc.html"
            (report_dir / filename).write_text("legacy", encoding="utf-8")
            source_dir = report_dir / "run_123456789abc_trajectory"
            source_dir.mkdir()
            png_name = "T-001_map.map.png"
            (source_dir / png_name).write_bytes(_png_gray(2, 2, b"\xff\x00\xff\x00"))
            (source_dir / "T-001.json").write_text(
                json.dumps(
                    {
                        "segments": [{"map_id": "map", "map_label": "大厅", "route_name": "去程", "points": [{"x": 0, "y": 0, "timestamp_ns": 1}]}],
                        "frozen_maps": [{"map_id": "map", "filename": png_name, "label": "大厅", "resolution_m": 1, "width_cells": 2, "height_cells": 2, "origin_x_m": 0, "origin_y_m": 0}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            archive = NativeReportArchive(report_dir)
            self.assertTrue(archive.archive_historic_report(filename))
            summary = archive.summary_for_filename(filename)
            trajectory_id = archive.detail_page(summary["report_id"], None, 50)["items"][0]["trajectory_refs"][0]["trajectory_id"]
            handler = object.__new__(web_console.ConsoleHandler)
            handler.path = f"/api/reports/{summary['report_id']}/native/trajectories/{trajectory_id}/map.png"
            handler.headers = {"User-Agent": "desktop-test"}
            handler._json = Mock()
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            handler.wfile = io.BytesIO()

            with patch.object(web_console, "WORKSPACE", root):
                handler.do_GET()

            handler.send_response.assert_called_once_with(HTTPStatus.OK)
            self.assertIn(("Content-Type", "image/png"), [call.args for call in handler.send_header.call_args_list])
            self.assertTrue(handler.wfile.getvalue().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_filename_delete_removes_its_native_sidecar_without_touching_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_dir = root / "reports"
            report_dir.mkdir()
            filename = "报告_20260928_100001_测试_123456789abc.html"
            html = report_dir / filename
            html.write_text("legacy", encoding="utf-8")
            source_dir = report_dir / "run_123456789abc_trajectory"
            source_dir.mkdir()
            source = source_dir / "T-001.json"
            source.write_text(json.dumps({"segments": []}), encoding="utf-8")
            archive = NativeReportArchive(report_dir)
            self.assertTrue(archive.archive_historic_report(filename))

            with patch.object(web_console, "WORKSPACE", root):
                web_console.ConsoleHandler._delete_report(filename)

            self.assertFalse(html.exists())
            self.assertIsNone(archive.summary_for_filename(filename))
            # Legacy test-report deletion owns this source directory too; the
            # native archive must not broaden that established deletion scope.
            self.assertFalse(source_dir.exists())

    def test_native_report_backfill_runs_outside_request_handling(self):
        """A finite worker batch upgrades legacy sidecars without a GET request."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_dir = root / "reports"
            report_dir.mkdir()
            filename = "报告_20260928_100001_测试_123456789abc.html"
            (report_dir / filename).write_text("legacy", encoding="utf-8")
            source_dir = report_dir / "run_123456789abc_trajectory"
            source_dir.mkdir()
            (source_dir / "T-001.json").write_text(json.dumps({"segments": []}), encoding="utf-8")

            created = web_console._backfill_native_report_batch(root, maximum=4)

            self.assertEqual(created, 1)
            self.assertIsNotNone(NativeReportArchive(report_dir).summary_for_filename(filename))

    def test_report_filename_prefers_alias_and_keeps_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SettingsStore(root / "console.json")
            case = TestCase("高科一号_1_1_15_1.json", "高科一号_1_1_15_1.json", "测试", TaskParameters("高科一号", 1, 1, 15, 1), "unused.json")
            settings.save({"case_aliases": {case.id: "电梯/往返 验证"}})
            run = RunRecord("681174175ef5", case, 1, 0, started_at="2026-08-14T11:15:30+08:00")
            manager = RunManager(root / "reports", object(), settings)
            self.assertEqual(manager._report_stem(run), "报告_20260814_111530_电梯_往返_验证_681174175ef5")

    def test_live_progress_snapshot_keeps_confirmed_percent_during_map_tf_gap(self):
        case = TestCase("case", "case.json", "测试", TaskParameters("园区", 1, 1, 1, 1), "unused.json")
        run = RunRecord("run", case, 2, 0, status="running")
        run.active_attempt = 1
        RunManager._update_live_progress(run, 1, {"progress_available": True, "percent": 46.8, "route_name": "去程"})
        # 用户返回页面时可能正好遇到地图切换；临时状态仍应携带上一有效百分比。
        RunManager._update_live_progress(run, 1, {"progress_available": False, "state": "等待切换至当前子任务地图"})
        self.assertEqual(run.live_progress["percent"], 46.8)
        self.assertTrue(run.live_progress["progress_available"])
        self.assertTrue(run.live_progress["retained_progress"])

        # 新的一轮必须从自身进度开始，不能继承上一轮。
        run.active_attempt = 2
        run.live_progress = {"visible": True, "attempt": 2, "attempt_total": 2, "progress_available": False, "percent": 0}
        RunManager._update_live_progress(run, 2, {"progress_available": True, "percent": 0})
        self.assertEqual(run.live_progress["percent"], 0)

    def test_manual_control_is_available_only_during_acceptance_recovery(self):
        """A failed round must let the operator drive back, but active execution stays locked."""
        case = TestCase("case", "case.json", "测试", TaskParameters("园区", 1, 1, 1, 1), "unused.json")
        manager = RunManager(Path("unused"), object(), object())
        run = RunRecord("run", case, 1, 0, status="running")
        manager._runs[run.id] = run

        self.assertTrue(manager.has_active_run())
        self.assertTrue(manager.manual_control_blocked())

        run.status = "awaiting_recovery"
        self.assertTrue(manager.has_active_run())
        self.assertFalse(manager.manual_control_blocked())

        run.status = "recovering"
        self.assertTrue(manager.manual_control_blocked())

    def test_manual_map_marker_navigation_contracts_define_pc_only_safe_nav2_boundary(self):
        observation = Path("shared/contracts/realtime_observation.md").read_text(encoding="utf-8")
        control = Path("shared/contracts/robot_control.md").read_text(encoding="utf-8")
        execution = Path("shared/contracts/task_execution.md").read_text(encoding="utf-8")
        console = Path("web_console.py").read_text(encoding="utf-8")

        self.assertIn("/api/observation/map-markers", observation)
        self.assertIn("/api/observation/map-marker-navigation/begin", observation)
        self.assertIn("/api/observation/map-markers", console)
        self.assertIn("/api/observation/map-marker-navigation/begin", console)
        self.assertIn('set(data) != {"alias", "x", "y", "yaw"}', console)
        self.assertIn('set(data) != {"id"}', console)
        self.assertNotIn("/api/observation/task-points", console)
        self.assertNotIn("task-point-navigation", console)
        marker_section = observation.split("## PC 手动地图标记", 1)[1].split("##", 1)[0]
        self.assertNotIn("任务目录", marker_section)
        self.assertNotIn("map_path", marker_section)
        self.assertIn("300 秒", observation)
        self.assertIn("Mobile 不是", observation)
        self.assertIn("navigate_to_pose", control)
        self.assertIn("cancellation_unconfirmed", observation)
        self.assertIn("200 ms", observation)
        self.assertIn("急停", control)
        self.assertIn("受控地图标记前往", execution)
        self.assertIn("`/plan`", observation)
        self.assertIn("最多 512", observation)
        self.assertIn("终态、取消、失效安全条件、切图和新 Goal 都必须清除路线", observation)
        self.assertIn("PC 实时页消费", observation)
        self.assertIn("Mobile 不消费或展示", observation)
        self.assertIn("路线数据", control)

    def test_frozen_build_collects_nav2_action_interfaces(self):
        build = Path("build_binary.sh").read_text(encoding="utf-8")
        self.assertIn("import nav2_msgs.action", build)
        self.assertIn("--collect-all nav2_msgs", build)

    def test_live_progress_rejects_late_attempt_callbacks_and_unknown_zero_percent(self):
        case = TestCase("case", "case.json", "测试", TaskParameters("园区", 1, 1, 1, 1), "unused.json")
        run = RunRecord("run", case, 2, 0, status="running")
        run.active_attempt = 2
        run.live_progress = {"visible": True, "attempt": 2, "attempt_total": 2, "progress_available": False, "percent": 0}
        # 上一轮的延迟回调不能覆盖当前轮。
        RunManager._update_live_progress(run, 1, {"progress_available": True, "percent": 88})
        self.assertEqual(run.live_progress["attempt"], 2)
        # 当前轮未知状态必须保持不可用，而不是伪装为真实 0%。
        RunManager._update_live_progress(run, 2, {"state": "等待 /map", "percent": 0})
        self.assertFalse(run.live_progress["progress_available"])


if __name__ == "__main__":
    unittest.main()
