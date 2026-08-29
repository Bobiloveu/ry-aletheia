import base64
import hashlib
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
import zipfile
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import web_console
from autodrive_console.case_store import CaseStore
from autodrive_console.models import AttemptResult, RunRecord, TaskParameters, TestCase
from autodrive_console.map_assets import MapAssetCache
from autodrive_console.map_snapshot import ObservationMapSnapshot
from autodrive_console.observation import ObservationError, ObservationManager
from autodrive_console.trajectory import ActiveMap, TrajectorySession
from autodrive_console.run_manager import RunManager
from autodrive_console.scenario_setup import ScenarioSetupError, ScenarioSetupStore
from autodrive_console.robot_gateway import RobotGateway
from autodrive_console.settings import RobotSettings, SettingsStore
from autodrive_console.supervisor import SupervisorClient
from autodrive_console.tool_logging import ToolLogStore
from autodrive_console.upgrade_manager import UpgradeError, UpgradeManager
from autodrive_console import upgrade_signature


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

    def test_scenario_setup_keeps_transaction_until_runtime_restore_is_confirmed(self):
        """脚本回写并不等于运行中节点已切回常规参数。"""
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
            result = store.restore(retain_transaction=True)
            self.assertTrue(result["runtime_pending"])
            self.assertTrue(store.has_unresolved_transaction())
            self.assertEqual(store.status()["transaction"]["phase"], "script_restored")
            completed = store.complete_runtime_restore("定位节点已稳定 RUNNING")
            self.assertTrue(completed["restored"])
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
        self.assertIn("$('restoreDefault').hidden", source)
        self.assertNotIn("render({ document: documentState, inspection: {}, active_backup: null })", source)

    def test_manual_scenario_apply_restarts_runtime_and_leaves_recovery_on_failure(self):
        class Gateway:
            def __init__(self, _settings):
                pass

            @staticmethod
            def restart_configured_dependencies():
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
            def restart_configured_dependencies():
                return False, "MODULES:209-lightning 未稳定 RUNNING"

        with patch.object(web_console.SCENARIO_SETUP, "apply", return_value={"message": "已应用场景前置方案：大厅"}), \
             patch.object(web_console.SCENARIO_SETUP, "note_runtime_activation_failure") as note_failure, \
             patch("web_console.RobotGateway", FailedGateway), \
             patch.object(web_console.SETTINGS, "load", return_value=object()):
            with self.assertRaisesRegex(ScenarioSetupError, "未能读取新参数"):
                web_console.apply_scenario_runtime("hall")
        note_failure.assert_called_once_with("MODULES:209-lightning 未稳定 RUNNING")

    def test_manual_scenario_restore_without_transaction_does_not_restart_robot_nodes(self):
        with patch.object(web_console.SCENARIO_SETUP, "restore", return_value={"restored": False, "message": "当前没有待恢复的场景前置配置"}) as restore, \
             patch("web_console.RobotGateway") as gateway:
            result = web_console.restore_scenario_runtime()
        restore.assert_called_once_with(retain_transaction=True)
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

    def test_observation_start_is_serialized_and_stop_reaps_both_sidecars(self):
        """两个页面同时进入不能重复 spawn，停止路径必须 wait 两个受控子进程。"""
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
            barrier = threading.Barrier(2)
            failures: list[BaseException] = []

            def enter_page():
                try:
                    barrier.wait(timeout=2)
                    manager.start(settings)
                except BaseException as exc:  # assertion after both callers return
                    failures.append(exc)

            def spawn(*_args, **_kwargs):
                process = FakeProcess()
                created.append(process)
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
                self.assertEqual(len(created), 2)
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
            with patch.object(MapAssetCache, "ALLOWED_ROOTS", (root / "maps",)):
                # ROS OccupancyGrid 的 resolution 为 float32；浏览器经 CDR
                # 解码后会带出尾差，不能因此遗漏同目录虚拟墙。
                result = manager.live_layers({"width": 2, "height": 2, "resolution": 0.2500000037252903, "origin": [-3.0, 1.5], "frame_id": "map"})
                cached_result = manager.live_layers({"width": 2, "height": 2, "resolution": 0.25, "origin": [-3.0, 1.5], "frame_id": "map"})
            self.assertTrue(result["matched"])
            self.assertEqual(result["virtual_walls"][0]["points"], [{"x": -2.0, "y": 2.0}, {"x": -1.0, "y": 2.0}])
            self.assertEqual(cached_result, result)
            self.assertEqual(manager.active_map_id(), result["map_id"])

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
        self.assertIn("openLane('cloud', '/cloud'", source)
        self.assertIn("openLane('pose', '/pose'", source)
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
        self.assertIn("async function refreshActiveMap(observation)", source)
        self.assertIn("if (!mapId || mapId === loadedMapId || mapId === requestedActiveMapId) return;", source)
        self.assertIn("const POINT_LIMIT = 3000;", source)
        self.assertIn("const CLOUD_COMPOSITE_MIN_INTERVAL_MS = 125;", source)
        # PixiJS 世界容器仅更新相机矩阵，可按显示帧合成而不重绘栅格。
        self.assertIn("const MAP_RENDER_INTERVAL_MS = 16;", source)
        # 位姿已不再走 TF/通用协议：只消费专用二进制帧并保持单槽 latest-wins。
        self.assertIn("const TELEMETRY_HEADER_BYTES = 20;", source)
        self.assertIn("const POSE_PACKET_MAX_AGE_MS = 250;", source)
        # 点云历史只保留极短窗口，避免与地图交互争用浏览器主线程。
        self.assertIn("import { Application, BufferImageSource, Container, Graphics, Sprite, Texture } from 'pixi.js';", source)
        self.assertIn("async function initializePixiRenderer()", source)
        self.assertIn("new ResizeObserver(resizeMapViewport).observe(interaction.parentElement);", source)
        self.assertIn("lastMapDrawAt = performance.now(); drawMap();", source)
        self.assertIn("function rebuildCloudRaster()", source)
        self.assertIn("function renderCloudPoints(packedPoints)", source)
        self.assertIn("function renderStaticWorld()", source)
        self.assertIn("pixiWorld.scale.set(layout.ratio, layout.ratio);", source)
        self.assertNotIn("cameraChannels", source)
        self.assertNotIn("cameraSlots", source)
        self.assertNotIn("async function initializeCameraRenderer(slot)", source)
        self.assertNotIn("function presentCameraTexture(slot, texture, width, height, imageBitmap)", source)
        self.assertNotIn("getContext('2d')", source)
        self.assertIn("points.fill((mobileConsoleEnabled() ? MAP_PALETTE : DESKTOP_MAP_PALETTE).cloud);", source)
        self.assertIn("const DESKTOP_MAP_PALETTE", source)
        self.assertIn("pixiWorld.addChild(pixiMapLayer, pixiGridLayer, pixiWallLayer, pixiCloudLayer);", source)
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
        self.assertIn("document.addEventListener('visibilitychange'", source)
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
            self.assertEqual(
                [path.name for path in store.diagnostic_files()],
                ["ry-aletheia.log", "ry-aletheia-error.log", "live_preprocessor_cloud.log", "video-runtime.log"],
            )
            records = store.diagnostic_records()
            self.assertEqual(records[-1]["name"], "video-runtime.log")
            self.assertEqual(records[-1]["label"], "视频运行时")
            self.assertEqual(store.diagnostic_file("video-runtime.log"), Path(directory) / "video-runtime.log")
            self.assertIsNone(store.diagnostic_file("../../etc/passwd"))
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

    def test_upgrade_frontend_waits_for_the_requested_version_before_reloading(self):
        """旧服务 shutdown 排队期间仍能返回 200，不能据此误判新版本已启动。"""
        source = Path("frontend/src/main.js").read_text(encoding="utf-8")
        self.assertIn("function waitForUpgradeRestart(expectedVersion)", source)
        self.assertIn("body.current_version || '') === String(expectedVersion || '')", source)
        self.assertIn("waitForUpgradeRestart(data.version)", source)

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
                "ui_preferences": {"case_id": "园区_1_2_3_4.json", "count": 3, "interval_seconds": 2, "open_rviz": True},
                "monitor_nodes": ["NODE:1"],
                "elevator_wait_timeout_s": 240,
                "task_execution_timeout_s": 1200,
                "dependency_plan": {"enabled": True, "steps": [{"nodes": ["NODE:1"], "wait_seconds": 0}]},
            })
            self.assertEqual(saved.case_aliases["园区_1_2_3_4.json"], "电梯往返")
            self.assertTrue(store.load().ui_preferences["open_rviz"])
            self.assertEqual(store.load().elevator_wait_timeout_s, 240)
            self.assertEqual(store.load().task_execution_timeout_s, 1200)
            with self.assertRaisesRegex(ValueError, "只能出现在一个启动步骤"):
                store.save({"dependency_plan": {"enabled": True, "steps": [{"nodes": ["NODE:1"]}, {"nodes": ["NODE:1"]}]}})

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

    def test_supervisor_sudoers_are_scoped_to_declared_programs(self):
        postinst = Path("packaging/debian/postinst").read_text(encoding="utf-8")
        self.assertIn("SUPERVISOR_NODES=(", postinst)
        self.assertIn("SUPERVISOR_NODES+=(\"$node\")", postinst)
        self.assertIn('sudoers_node="${node//:/\\\\:}"', postinst)
        self.assertIn("%s start %s, %s restart %s", postinst)
        self.assertNotIn("%s start *, %s restart *", postinst)
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
            run.attempts.append(AttemptResult(1, "passed", "服务成功", 60.0, run.started_at, {"visualizations": [{"map_id": "map", "label": "测试地图", "file": str(svg)}]}))
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
