import hashlib
import io
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import web_console
from autodrive_console.case_store import CaseStore
from autodrive_console.models import AttemptResult, RunRecord, TaskParameters, TestCase
from autodrive_console.map_assets import MapAssetCache
from autodrive_console.observation import ObservationError, ObservationManager
from autodrive_console.trajectory import ActiveMap, TrajectorySession
from autodrive_console.run_manager import RunManager
from autodrive_console.scenario_setup import ScenarioSetupError, ScenarioSetupStore
from autodrive_console.robot_gateway import RobotGateway
from autodrive_console.settings import RobotSettings, SettingsStore
from autodrive_console.supervisor import SupervisorClient
from autodrive_console.tool_logging import ToolLogStore
from autodrive_console.upgrade_manager import UpgradeError, UpgradeManager


class _SupervisorClient(SupervisorClient):
    def _run(self, _args):
        from subprocess import CompletedProcess
        return CompletedProcess([], 0, "NODE:1 RUNNING pid 10\nNODE:2 STOPPED Not started\n", "")


class OfflineModuleTests(unittest.TestCase):
    def test_scenario_setup_applies_only_registered_targets_and_refuses_unsafe_restore(self):
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
            script.write_text("# changed elsewhere\n", encoding="utf-8")
            with self.assertRaisesRegex(ScenarioSetupError, "外部修改"):
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
            self.assertEqual(store.browse(str(launch_dir), "lightning")["files"], [{"name": "ignored.yaml", "path": str((launch_dir / "ignored.yaml").resolve()), "size": 5}])
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
        self.assertNotIn("render({ document: documentState, inspection: {}, active_backup: null })", source)

    def test_observation_reuses_cached_map_and_migrates_legacy_bridge_host(self):
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
            self.assertEqual(manager._options(configured)["bridge_port"], 8766)
            self.assertNotIn("bridge_host", configured.live_observation)
            old_proxy_path = root / "old-proxy.json"
            old_proxy_path.write_text(json.dumps({"live_observation": {"enabled": True, "bridge_host": "127.0.0.1", "bridge_port": 8765}}), encoding="utf-8")
            self.assertEqual(SettingsStore(old_proxy_path).load().live_observation["bridge_port"], 8767)
            # 老版本只保存端口等字段；升级后必须自动补齐车型库，观测页才能安全绘制车体。
            legacy_path = root / "legacy.json"
            legacy_path.write_text(json.dumps({"live_observation": {"enabled": True, "bridge_port": 8767}}), encoding="utf-8")
            legacy = SettingsStore(legacy_path).load()
            self.assertEqual(legacy.live_observation["active_vehicle_model"], "ry-standard")
            self.assertEqual(legacy.live_observation["vehicle_models"][0]["width_m"], 0.68)
            custom = SettingsStore(root / "custom.json").save({"live_observation": {"vehicle_models": [{"id": "compact", "name": "紧凑车型", "length_m": 0.8, "width_m": 0.55}], "active_vehicle_model": "compact"}})
            self.assertEqual(custom.live_observation["active_vehicle_model"], "compact")
            with self.assertRaisesRegex(ValueError, "8765"):
                SettingsStore(root / "reserved-port.json").save({"live_observation": {"enabled": True, "bridge_port": 8765}})
            manager._port_open = lambda _host, _port: True
            with self.assertRaisesRegex(ObservationError, "外部进程占用"):
                manager.start(configured)
            manager.stop()
            with self.assertRaises(ObservationError):
                manager.preview("../not-a-map")

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
                result = manager.live_layers({"width": 2, "height": 2, "resolution": 0.25, "origin": [-3.0, 1.5], "frame_id": "map"})
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

    def test_live_observation_frontend_subscribes_to_transient_map(self):
        """避免直连模式只收到 TF、却因白名单遗漏而永远不请求 /map。"""
        source = Path("frontend/src/liveObservation.js").read_text(encoding="utf-8")
        self.assertIn("const TOPICS = new Set(['/map', '/amcl_pose'", source)
        self.assertIn("else if (channel.topic === '/map') { mapChannel = channel; beginMapProbe(); }", source)
        self.assertIn("function isDepthTransport(channel)", source)
        self.assertIn("isCameraCandidate(channel)", source)
        self.assertIn("原始图像（高带宽，可能增加延迟）", source)
        self.assertIn("/api/observation/live-layers", source)
        self.assertIn("if (mapInfo) return;", source)
        self.assertIn("const POINT_LIMIT = 3000;", source)
        self.assertIn("const PREPROCESSED_CLOUD_MIN_INTERVAL_MS = 100;", source)
        self.assertIn("const RAW_CLOUD_MIN_INTERVAL_MS = 250;", source)
        # 全图合成上限为 30 FPS，避免移动时强制 60 FPS 重绘造成位姿积压。
        self.assertIn("const MAP_RENDER_INTERVAL_MS = 33;", source)
        self.assertIn("const TF_MIN_INTERVAL_MS = 33;", source)
        # 点云历史只保留极短窗口，避免与地图交互争用浏览器主线程。
        self.assertIn("const CLOUD_HISTORY_MS = 90;", source)
        self.assertIn("new ResizeObserver(resizeCanvas).observe(canvas.parentElement);", source)
        self.assertIn("lastMapDrawAt = performance.now(); drawMap();", source)
        self.assertIn("function rebuildCloudRaster()", source)
        self.assertIn("const canvas = $('cloudCanvas');", source)
        self.assertIn("function renderStaticWorld()", source)
        self.assertIn("mapStaticCanvas", source)
        self.assertIn("回退到原始点云时仍保持保守限速", source)
        self.assertIn("function mapHeadingForVehicle(yaw)", source)
        self.assertIn("const MAP_REORIENT_THRESHOLD_RAD = Math.PI / 2;", source)
        self.assertIn("function followVehicleCenter(vehicle)", source)
        self.assertIn("function hasPendingFollowAdjustment()", source)
        self.assertIn("const FOLLOW_CENTER_SETTLE_DISTANCE_M = 0.008;", source)
        self.assertIn("Math.abs(normalizeAngle(vehicle.yaw - lockedMapYaw)) >= MAP_REORIENT_THRESHOLD_RAD", source)
        self.assertIn("function requestFollowAnimation()", source)
        self.assertIn("!hasPendingFollowAdjustment()", source)
        self.assertIn("禁止运动时额外启动 60 FPS 全图循环", source)
        self.assertIn("function stopRenderScheduling()", source)
        self.assertIn("document.addEventListener('visibilitychange'", source)
        self.assertIn("const VEHICLE_BASE_FRAMES = ['base_footprint', 'base_link', 'base_footprint_link'];", source)
        self.assertIn("function vehiclePoseInMap()", source)
        self.assertIn("function subscribeVisualizationStream(kind, channel)", source)
        self.assertNotIn("const STREAM_PROBE_INTERVAL_MS", source)
        self.assertIn("function activateVisualizationStreams()", source)
        self.assertIn("else if (channel.topic === '/amcl_pose') subscriptions.set(client.subscribe(channel.id)", source)
        self.assertIn("else if (channel.topic === '/tf') { tfChannel = channel;", source)
        self.assertIn("'/aletheia/live_points'", source)
        self.assertIn("else if (channel.topic === cloudTopic) { cloudChannel = channel;", source)

    def test_private_bridge_runtime_only_changes_bridge_child_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = root / "runtime" / "foxglove_bridge"
            marker = prefix / "share" / "ament_index" / "resource_index" / "packages" / "foxglove_bridge"
            marker.parent.mkdir(parents=True)
            marker.write_text("", encoding="utf-8")
            (prefix / "lib").mkdir()
            manager = ObservationManager(root / "maps_cache", root / "logs")
            environment = manager._bridge_environment()
            self.assertEqual(manager._private_bridge_prefix(), prefix)
            self.assertTrue(environment["AMENT_PREFIX_PATH"].split(":")[0] == str(prefix))
            self.assertTrue(environment["CMAKE_PREFIX_PATH"].split(":")[0] == str(prefix))
            self.assertTrue(environment["LD_LIBRARY_PATH"].split(":")[0] == str(prefix / "lib"))

    def test_observation_private_bridge_listens_on_lan_and_is_checked_locally(self):
        """性能模式直连浏览器，Bridge 必须监听全部网卡但仅用回环检查健康。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = ObservationManager(root / "maps_cache", root / "logs")
            settings = RobotSettings(live_observation={"enabled": True, "bridge_port": 8767})

            class Process:
                pid = 4242

                @staticmethod
                def poll():
                    return None

            with patch.object(manager, "_bridge_package", return_value=(True, "available")), \
                 patch.object(manager, "_port_open", side_effect=[False, True]) as port_open, \
                 patch("autodrive_console.observation.shutil.which", return_value="/opt/ros/humble/bin/ros2"), \
                 patch("autodrive_console.observation.subprocess.Popen", return_value=Process()) as popen, \
                 patch("autodrive_console.observation.threading.Timer"):
                status = manager.start(settings)
            command = popen.call_args.args[0]
            self.assertIn("address:=0.0.0.0", command)
            self.assertIn("max_qos_depth:=1", command)
            self.assertEqual(port_open.call_args_list[0].args[0], "127.0.0.1")
            self.assertEqual(status["bridge"]["access_mode"], "direct")
            manager._process = None

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
        with self.assertRaisesRegex(RuntimeError, "必须以 status 结尾"):
            SupervisorClient("supervisorctl restart", 1)._base_args()

    def test_upgrade_package_validation_and_report_path_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "VERSION").write_text("0.1\n", encoding="utf-8")
            binary = b"valid binary payload"
            manifest = {
                "schema": UpgradeManager.SCHEMA,
                "version": "0.2",
                "created_at": "2026-08-13T00:00:00+08:00",
                "binary": {"path": "ry-aletheia", "size": len(binary), "md5": hashlib.md5(binary).hexdigest()},
            }
            archive = root / "valid.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("manifest.json", json.dumps(manifest))
                bundle.writestr("ry-aletheia", binary)
            manager = UpgradeManager(root, root / "ry-aletheia", True)
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


if __name__ == "__main__":
    unittest.main()
