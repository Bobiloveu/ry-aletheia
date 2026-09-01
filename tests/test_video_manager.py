import json
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import web_console
from autodrive_console.video import ConsoleVideoRuntime, GatewayHealth, VideoManager, VideoRuntime


ROOT = Path(__file__).parents[1]


class VideoManagerTests(unittest.TestCase):
    def _config(self, root: Path, **overrides) -> Path:
        document = json.loads((ROOT / "config" / "video.json").read_text(encoding="utf-8"))
        document.update(overrides)
        target = root / "video.json"
        target.write_text(json.dumps(document), encoding="utf-8")
        return target

    def test_default_video_config_is_disabled_without_gateway_probe(self):
        manager = VideoManager(ROOT / "config" / "video.json")
        with patch.object(manager, "_probe_gateway") as probe:
            status = manager.status("192.168.10.42:8087")
        probe.assert_not_called()
        self.assertFalse(status["enabled"])
        self.assertFalse(status["gateway"]["online"])
        self.assertEqual([stream["status"] for stream in status["streams"]], ["disabled"] * 6)
        self.assertEqual(status["streams"][0]["url"], "http://192.168.10.42:8889/front_camera/whep")
        self.assertIsNone(status["streams"][0]["source_topic"])
        self.assertEqual(status["streams"][0]["source_label"], "ShmSDK/CamFront")
        self.assertEqual(status["streams"][0]["resolution"], "640x480")
        self.assertEqual(status["streams"][0]["fps"], 15)
        self.assertEqual(status["streams"][-2]["name"], "detection_camera")
        self.assertEqual(status["streams"][-2]["source_topic"], "/rfdetr_detect")
        self.assertEqual(status["streams"][-2]["encoding"], "bgr8")
        self.assertEqual(status["streams"][-2]["fps"], 10)
        self.assertEqual(status["streams"][-1]["name"], "segmentation_overlay")
        self.assertEqual(status["streams"][-1]["source_topic"], "/segmentation/overlay")
        self.assertTrue(all(stream["enabled"] is False for stream in status["streams"]))
        self.assertTrue(all("camera_pair" not in stream for stream in status["streams"]))
        self.assertEqual(status["gateway"]["management"], "console")

    def test_missing_runtime_config_falls_back_to_the_bundled_safe_default(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = VideoManager(Path(directory) / "runtime-video.json", ROOT / "config" / "video.json")
            status = manager.status()
        self.assertFalse(status["enabled"])
        self.assertEqual(status["gateway"]["detail"], "视频功能未启用，未探测 MediaMTX")

    def test_migration_removes_unused_legacy_camera_pair_without_changing_stream_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = json.loads((ROOT / "config" / "video.json").read_text(encoding="utf-8"))
            document["enabled"] = True
            document["streams"][0]["enabled"] = True
            document["streams"][0]["camera_pair"] = {"source": "/dev/video0", "virtual": "/dev/video20"}
            path = root / "config" / "video.json"
            path.parent.mkdir()
            path.write_text(json.dumps(document), encoding="utf-8")
            manager = VideoManager(path, ROOT / "config" / "video.json")
            self.assertTrue(manager.migrate_config())
            migrated = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(migrated["enabled"])
        self.assertTrue(migrated["streams"][0]["enabled"])
        self.assertNotIn("camera_pair", migrated["streams"][0])

    def test_upgrade_migrates_only_the_four_shipped_dead_ros_camera_topics_to_shmsdk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = json.loads((ROOT / "config" / "video.json").read_text(encoding="utf-8"))
            for stream, topic in zip(document["streams"][:4], [
                "/front_camera/image_raw", "/back_camera/image_raw", "/left_camera/image_raw", "/right_camera/image_raw",
            ]):
                stream.pop("input")
                stream["source_topic"] = topic
            # A deliberately customised ROS source is not auto-rewired.
            document["streams"][0]["source_topic"] = "/custom/front/image_raw"
            path = root / "config" / "video.json"
            path.parent.mkdir()
            path.write_text(json.dumps(document), encoding="utf-8")
            manager = VideoManager(path, ROOT / "config" / "video.json")
            self.assertTrue(manager.migrate_config())
            migrated = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(migrated["streams"][0]["source_topic"], "/custom/front/image_raw")
        self.assertNotIn("input", migrated["streams"][0])
        self.assertEqual(migrated["streams"][1]["input"], {"kind": "shmsdk", "channel": "CamBack"})
        self.assertEqual(migrated["streams"][2]["input"], {"kind": "shmsdk", "channel": "CamLeft"})
        self.assertEqual(migrated["streams"][3]["input"], {"kind": "shmsdk", "channel": "CamRight"})
        self.assertNotIn("source_topic", migrated["streams"][1])

    def test_shmsdk_input_is_limited_to_its_fixed_physical_camera_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid_stream = {
                "name": "detection_camera", "path": "detection_camera", "enabled": True,
                "input": {"kind": "shmsdk", "channel": "CamFront"}, "encoding": "bgr8", "resolution": "640x480",
                "fps": 10, "bitrate_kbps": 800,
            }
            status = VideoManager(self._config(Path(directory), streams=[invalid_stream])).status()
        self.assertIn("只能使用固定的 ShmSDK 通道", status["gateway"]["detail"])

    def test_web_switch_seeds_all_validated_streams_on_first_enable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_path = root / "config" / "video.json"
            manager = VideoManager(runtime_path, ROOT / "config" / "video.json")
            manager.set_enabled(True)
            saved = json.loads(runtime_path.read_text(encoding="utf-8"))
            manager.set_enabled(False)
            disabled = manager.load_config()
        default = json.loads((ROOT / "config" / "video.json").read_text(encoding="utf-8"))
        self.assertTrue(saved["enabled"])
        self.assertTrue(all(stream["enabled"] for stream in saved["streams"]))
        self.assertEqual([stream["name"] for stream in saved["streams"]], [stream["name"] for stream in default["streams"]])
        self.assertFalse(disabled["enabled"])

    def test_web_switch_preserves_a_deliberate_subset_of_enabled_streams(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = json.loads((ROOT / "config" / "video.json").read_text(encoding="utf-8"))
            document["streams"][0]["enabled"] = True
            path = root / "video.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            manager = VideoManager(path)
            manager.set_enabled(True)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([stream["enabled"] for stream in saved["streams"]], [True, False, False, False, False, False])

    def test_each_configured_stream_can_be_toggled_independently_and_last_one_stops_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = VideoManager(self._config(Path(directory)))
            first = manager.set_stream_enabled("front_camera", True)
            second = manager.set_stream_enabled("detection_camera", True)
            last = manager.set_stream_enabled("front_camera", False)
            stopped = manager.set_stream_enabled("detection_camera", False)
            with self.assertRaisesRegex(Exception, "未找到已配置的视频流"):
                manager.set_stream_enabled("not_configured", True)
        self.assertTrue(first["enabled"])
        self.assertEqual([stream["enabled"] for stream in first["streams"]], [True, False, False, False, False, False])
        self.assertEqual([stream["enabled"] for stream in second["streams"]], [True, False, False, False, True, False])
        self.assertTrue(last["enabled"])
        self.assertFalse(stopped["enabled"])
        self.assertEqual([stream["enabled"] for stream in stopped["streams"]], [False, False, False, False, False, False])

    def test_zip_upgrade_migration_appends_new_video_streams_without_replacing_existing_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = json.loads((ROOT / "config" / "video.json").read_text(encoding="utf-8"))
            old["enabled"] = True
            old["streams"] = old["streams"][:4]
            old["streams"][0]["enabled"] = True
            target = root / "config" / "video.json"
            target.parent.mkdir()
            target.write_text(json.dumps(old), encoding="utf-8")
            manager = VideoManager(target, ROOT / "config" / "video.json")
            migrated = manager.migrate_config()
            saved = json.loads(target.read_text(encoding="utf-8"))
        self.assertTrue(migrated)
        self.assertTrue(saved["enabled"])
        self.assertEqual([stream["name"] for stream in saved["streams"]], ["front_camera", "back_camera", "left_camera", "right_camera", "detection_camera", "segmentation_overlay"])
        self.assertEqual([stream["enabled"] for stream in saved["streams"]], [True, False, False, False, False, False])

    def test_video_config_uses_the_vehicle_ros_domain_and_rejects_invalid_domains(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configured = VideoManager(self._config(root, ros_domain_id=66)).load_config()
            invalid = VideoManager(self._config(root, ros_domain_id=233)).status()
        self.assertEqual(configured["ros_domain_id"], 66)
        self.assertIn("ros_domain_id", invalid["gateway"]["detail"])

    def test_video_config_accepts_bgr8_detection_images_and_rejects_other_encodings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            supported = VideoManager(self._config(root, streams=[
                {"name": "detection_camera", "path": "detection_camera", "enabled": True,
                 "source_topic": "/rfdetr_detect", "encoding": "bgr8", "resolution": "640x480", "fps": 10,
                 "bitrate_kbps": 800},
            ])).load_config()
            unsupported = VideoManager(self._config(root, streams=[
                {"name": "detection_camera", "path": "detection_camera", "enabled": True,
                 "source_topic": "/rfdetr_detect", "encoding": "mono8", "resolution": "640x480", "fps": 10,
                 "bitrate_kbps": 800},
            ])).status()
        self.assertEqual(supported["streams"][0]["encoding"], "bgr8")
        self.assertIn("rgb8 或 bgr8", unsupported["gateway"]["detail"])

    def test_online_gateway_marks_only_published_paths_online(self):
        with tempfile.TemporaryDirectory() as directory:
            streams = [
                {"name": "front_camera", "path": "front_camera", "enabled": True, "source_topic": "/front_camera/image_raw", "encoding": "rgb8", "resolution": "640x480", "fps": 20, "bitrate_kbps": 1200},
                {"name": "rear_camera", "path": "rear_camera", "enabled": True, "source_topic": "/back_camera/image_raw", "encoding": "rgb8", "resolution": "640x480", "fps": 20, "bitrate_kbps": 1200},
            ]
            path = self._config(Path(directory), enabled=True, streams=streams)
            manager = VideoManager(path)
            with patch.object(manager, "_probe_gateway", return_value=GatewayHealth(True, "ok", frozenset({"front_camera"}))):
                status = manager.status("[fd00::42]:8087")
        self.assertTrue(status["gateway"]["online"])
        self.assertEqual(status["streams"][0]["status"], "online")
        self.assertEqual(status["streams"][1]["status"], "waiting")
        self.assertEqual(status["streams"][0]["url"], "http://[fd00::42]:8889/front_camera/whep")

    def test_configured_but_not_ready_mediamtx_path_is_waiting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._config(Path(directory), enabled=True, streams=[
                {"name": "front_camera", "path": "front_camera", "enabled": True, "source_topic": "/front_camera/image_raw", "encoding": "rgb8", "resolution": "640x480", "fps": 20, "bitrate_kbps": 1200},
            ])
            manager = VideoManager(path)
            with patch.object(manager, "_probe_gateway", wraps=manager._probe_gateway):
                with patch("autodrive_console.video.urlopen") as urlopen:
                    response = urlopen.return_value.__enter__.return_value
                    response.status = 200
                    response.read.return_value = b'{"items":[{"name":"front_camera","ready":false}]}'
                    status = manager.status("192.168.1.5:8087")
        self.assertEqual(status["streams"][0]["status"], "waiting")

    def test_invalid_or_duplicate_streams_are_reported_without_raising_from_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._config(Path(directory), streams=[
                {"name": "front_camera", "path": "same", "enabled": True, "source_topic": "/front_camera/image_raw", "encoding": "rgb8", "resolution": "640x480", "fps": 20, "bitrate_kbps": 1200},
                {"name": "rear_camera", "path": "same", "enabled": True, "source_topic": "/back_camera/image_raw", "encoding": "rgb8", "resolution": "640x480", "fps": 20, "bitrate_kbps": 1200},
            ])
            status = VideoManager(path).status()
        self.assertFalse(status["enabled"])
        self.assertIn("配置无效", status["gateway"]["detail"])

    def test_invalid_gateway_port_is_reported_without_escaping_the_status_api(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._config(Path(directory), gateway={
                "kind": "mediamtx", "management": "supervisor", "supervisor_program": "ry_aletheia_video:mediamtx",
                "api_url": "http://127.0.0.1:not-a-port/v3/paths/list", "whep_port": 8889,
            })
            status = VideoManager(path).status()
        self.assertFalse(status["enabled"])
        self.assertIn("端口无效", status["gateway"]["detail"])

    def test_http_server_exposes_a_restricted_video_toggle_endpoint(self):
        source = (ROOT / "web_console.py").read_text(encoding="utf-8")
        self.assertIn('elif path == "/api/video/status":', source)
        self.assertIn('self._json(VIDEO.status(self.headers.get("Host")))', source)
        self.assertIn('path == "/api/video/control"', source)
        self.assertIn('runtime.set_enabled(data["enabled"])', source)
        self.assertIn('runtime.set_stream_enabled(stream, data["enabled"])', source)
        self.assertIn('not isinstance(data.get("enabled"), bool)', source)
        self.assertNotIn('path == "/api/video/start"', source)
        self.assertIsInstance(web_console.VIDEO, VideoManager)

    def test_video_runner_reconciles_only_ingest_children_while_mediamtx_paths_stay_declared(self):
        source = (ROOT / "autodrive_console" / "video.py").read_text(encoding="utf-8")
        self.assertIn('self._write_media_config(media_config, config, config["streams"])', source)
        self.assertIn("def _reconcile_streams", source)
        self.assertIn("self.ingest_processes", source)
        self.assertIn("without recreating MediaMTX or peers", source)

    def test_runner_stops_only_the_disabled_ingest_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = VideoManager(self._config(root, enabled=True))
            runtime = VideoRuntime(manager, root, root / "aletheia_video_ingest")
            config = manager.load_config()
            config["streams"][0]["enabled"] = True
            config["streams"][1]["enabled"] = True
            first = unittest.mock.Mock()
            second = unittest.mock.Mock()
            first.poll.return_value = None
            second.poll.return_value = None
            with patch("autodrive_console.video.subprocess.Popen", side_effect=[first, second]) as popen:
                self.assertTrue(runtime._reconcile_streams(config, root / "aletheia_video_ingest", root / "gst-launch-1.0"))
                config["streams"][1]["enabled"] = False
                self.assertTrue(runtime._reconcile_streams(config, root / "aletheia_video_ingest", root / "gst-launch-1.0"))
        self.assertEqual(popen.call_count, 2)
        first.terminate.assert_not_called()
        second.terminate.assert_called_once()

    def test_native_ingest_receives_the_configured_bgr8_format(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = VideoManager(self._config(root))
            runtime = VideoRuntime(manager, root, root / "aletheia_video_ingest")
            detection = next(stream for stream in manager.load_config()["streams"] if stream["name"] == "detection_camera")
            process = unittest.mock.Mock(pid=4321)
            with patch("autodrive_console.video.subprocess.Popen", return_value=process) as popen:
                runtime._start_ingest(detection, manager.load_config(), root / "aletheia_video_ingest", root / "gst-launch-1.0")
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--topic") + 1], "/rfdetr_detect")
        self.assertEqual(command[command.index("--input-kind") + 1], "ros")
        self.assertEqual(command[command.index("--encoding") + 1], "bgr8")

    def test_native_ingest_receives_a_fixed_shmsdk_channel_for_a_physical_camera(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = VideoManager(self._config(root))
            runtime = VideoRuntime(manager, root, root / "aletheia_video_ingest")
            front = manager.load_config()["streams"][0]
            process = unittest.mock.Mock(pid=4321)
            with patch("autodrive_console.video.subprocess.Popen", return_value=process) as popen:
                runtime._start_ingest(front, manager.load_config(), root / "aletheia_video_ingest", root / "gst-launch-1.0")
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--input-kind") + 1], "shmsdk")
        self.assertEqual(command[command.index("--shm-channel") + 1], "CamFront")
        self.assertNotIn("--topic", command)

    def test_console_owns_an_enabled_video_runtime_and_stops_it_on_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = VideoManager(self._config(root, enabled=True))
            controller = ConsoleVideoRuntime(manager, root, ["ry-aletheia", "--video-runner"])
            process = unittest.mock.Mock()
            process.poll.return_value = None
            with patch.object(manager, "_probe_gateway", return_value=GatewayHealth(False, "offline")):
                with patch("autodrive_console.video.subprocess.Popen", return_value=process) as popen, patch("autodrive_console.video.os.killpg") as killpg:
                    self.assertTrue(controller.start_if_enabled())
                    controller.stop()
        self.assertEqual(popen.call_args.args[0], ["ry-aletheia", "--video-runner"])
        self.assertEqual(popen.call_args.kwargs["cwd"], root.resolve())
        self.assertEqual(popen.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        killpg.assert_called_once_with(process.pid, signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=5)

    def test_console_video_switch_stops_its_own_child_and_persists_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = VideoManager(self._config(root, enabled=True))
            controller = ConsoleVideoRuntime(manager, root, ["ry-aletheia", "--video-runner"])
            process = unittest.mock.Mock()
            process.poll.return_value = None
            with patch.object(manager, "_probe_gateway", return_value=GatewayHealth(False, "offline")):
                with patch("autodrive_console.video.subprocess.Popen", return_value=process), patch("autodrive_console.video.os.killpg") as killpg:
                    controller.start_if_enabled()
                    controller.set_enabled(False)
                    killpg.assert_called_once_with(process.pid, signal.SIGTERM)
            disabled = manager.load_config()
        self.assertFalse(disabled["enabled"])

    def test_console_reconciles_each_stream_toggle_and_stops_after_the_last_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = VideoManager(self._config(root))
            controller = ConsoleVideoRuntime(manager, root, ["ry-aletheia", "--video-runner"])
            process = unittest.mock.Mock()
            process.poll.return_value = None
            with patch.object(manager, "_probe_gateway", return_value=GatewayHealth(False, "offline")):
                with patch("autodrive_console.video.subprocess.Popen", return_value=process) as popen, patch("autodrive_console.video.os.killpg") as killpg:
                    enabled = controller.set_stream_enabled("detection_camera", True)
                    disabled = controller.set_stream_enabled("detection_camera", False)
        self.assertTrue(enabled["enabled"])
        self.assertFalse(disabled["enabled"])
        self.assertEqual(popen.call_count, 1)
        killpg.assert_called_once_with(process.pid, signal.SIGTERM)

    def test_enabling_one_stream_keeps_the_existing_video_runtime_and_peer_streams_alive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = json.loads((ROOT / "config" / "video.json").read_text(encoding="utf-8"))
            document["enabled"] = True
            document["streams"][0]["enabled"] = True
            config = root / "video.json"
            config.write_text(json.dumps(document), encoding="utf-8")
            manager = VideoManager(config)
            controller = ConsoleVideoRuntime(manager, root, ["ry-aletheia", "--video-runner"])
            running = unittest.mock.Mock()
            running.poll.return_value = None
            controller.process = running
            with patch("autodrive_console.video.subprocess.Popen") as popen, patch("autodrive_console.video.os.killpg") as killpg:
                changed = controller.set_stream_enabled("back_camera", True)
        self.assertTrue(changed["enabled"])
        self.assertEqual([stream["enabled"] for stream in changed["streams"]], [True, True, False, False, False, False])
        popen.assert_not_called()
        killpg.assert_not_called()

    def test_video_default_is_embedded_and_deb_install_preserves_runtime_overrides(self):
        binary_script = (ROOT / "build_binary.sh").read_text(encoding="utf-8")
        deb_script = (ROOT / "build_deb_package.sh").read_text(encoding="utf-8")
        postinst = (ROOT / "packaging" / "debian" / "postinst").read_text(encoding="utf-8")
        self.assertIn('--add-data "config/video.json:config"', binary_script)
        self.assertIn('--add-data "$VIDEO_RUNTIME:runtime/video"', binary_script)
        self.assertIn('build_video_runtime.sh" --output-dir "$VIDEO_RUNTIME"', binary_script)
        self.assertIn('defaults/config/video.json', deb_script)
        self.assertIn('[[ -e "$ROOT/config/video.json" ]] || install', postinst)

    def test_native_video_ingest_is_latest_wins_and_uses_private_vaapi_gstreamer(self):
        source = (ROOT / "live_preprocessor" / "src" / "video_ingest.cpp").read_text(encoding="utf-8")
        cmake = (ROOT / "live_preprocessor" / "CMakeLists.txt").read_text(encoding="utf-8")
        build = (ROOT / "build_binary.sh").read_text(encoding="utf-8")
        self.assertIn('rclcpp::SensorDataQoS().keep_last(1)', source)
        self.assertIn('"--node-name"', source)
        self.assertIn('"--input-kind"', source)
        self.assertIn('"--shm-channel"', source)
        self.assertIn('GetLastCamImage', source)
        self.assertIn('std::thread shm_reader_', source)
        self.assertIn('find_package(JPEG REQUIRED)', cmake)
        self.assertIn('Node(options.node_name)', source)
        self.assertIn('std::this_thread::sleep_until(next_frame_at)', source)
        self.assertIn('latest_frame_ = std::move(image);', source)
        self.assertIn('const std::string raw_format = options_.encoding == "bgr8" ? "bgr" : "rgb";', source)
        self.assertIn('"rawvideoparse", "format=" + raw_format', source)
        self.assertIn('"vaapih264enc"', source)
        self.assertIn('"rtspclientsink"', source)
        self.assertIn("视频输入等待首帧", source)
        self.assertIn("视频输入已中断", source)
        self.assertIn("视频输入已收到 %llu 个%s图像但没有兼容帧", source)
        self.assertIn("视频输入已就绪", source)
        self.assertIn("GStreamer 输入管道已中断：errno=%d", source)
        self.assertNotIn('const std::string device = "device="', source)
        self.assertIn('"/dev/dri/renderD128"', (ROOT / "config" / "video.json").read_text(encoding="utf-8"))
        self.assertIn('add_executable(aletheia_video_ingest', cmake)
        self.assertIn('--add-binary "$VIDEO_INGEST:."', build)

    def test_native_runtime_only_emits_validated_mediamtx_paths_and_never_uses_a_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._config(root, enabled=True, streams=[
                {"name": "front_camera", "path": "front_camera", "enabled": True, "source_topic": "/front_camera/image_raw", "encoding": "rgb8", "resolution": "640x480", "fps": 20, "bitrate_kbps": 1200},
            ])
            runtime = VideoRuntime(VideoManager(config), root, ROOT / "build" / "live_preprocessor" / "aletheia_video_ingest")
            target = root / "runtime" / "video" / "mediamtx" / "ry-aletheia-mediamtx.yml"
            target.parent.mkdir(parents=True)
            runtime._write_media_config(target, runtime.manager.load_config(), runtime.manager.load_config()["streams"])
            document = target.read_text(encoding="utf-8")
        self.assertIn("apiAddress: 127.0.0.1:9997", document)
        self.assertIn("rtspAddress: 127.0.0.1:8554", document)
        self.assertIn("webrtcAddress: :8889", document)
        self.assertIn("  front_camera: {}", document)
        self.assertNotIn("/front_camera/image_raw", document)
        source = (ROOT / "autodrive_console" / "video.py").read_text(encoding="utf-8")
        self.assertIn("subprocess.Popen([str(media_binary), str(media_config)]", source)
        self.assertIn('ingest_environment["ROS_DOMAIN_ID"] = str(config["ros_domain_id"])', source)
        self.assertIn("已启动视频输入：stream=%s", source)
        self.assertIn("视频输入进程意外退出：stream=%s", source)
        self.assertNotIn("shell=True", source)

    def test_embedded_zip_runtime_refreshes_workspace_before_starting_video(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            bundled = root / "bundled-video"
            bundled.mkdir()
            (bundled / "ry-aletheia-runtime.json").write_text('{"plugins":["rawparse"]}\n', encoding="utf-8")
            (bundled / "required-plugin").write_text("new runtime", encoding="utf-8")
            stale = workspace / "runtime" / "video"
            stale.mkdir(parents=True)
            (stale / "ry-aletheia-runtime.json").write_text('{"plugins":[]}\n', encoding="utf-8")
            runtime = VideoRuntime(VideoManager(self._config(root)), workspace, ROOT / "build" / "live_preprocessor" / "aletheia_video_ingest", bundled)
            refreshed = runtime._runtime_root()
            plugin = (refreshed / "required-plugin").read_text(encoding="utf-8")
            marker = (refreshed / "ry-aletheia-runtime.json").read_text(encoding="utf-8")
        self.assertEqual(plugin, "new runtime")
        self.assertEqual(marker, '{"plugins":["rawparse"]}\n')

    def test_runtime_uses_the_validated_local_api_port_and_rejects_other_api_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gateway = {"kind": "mediamtx", "management": "supervisor", "supervisor_program": "ry_aletheia_video:mediamtx", "api_url": "http://127.0.0.1:19997/v3/paths/list", "whep_port": 19089, "rtsp_port": 19054}
            config = self._config(root, enabled=True, gateway=gateway)
            manager = VideoManager(config)
            target = root / "runtime" / "video" / "mediamtx.yml"
            target.parent.mkdir(parents=True)
            loaded = manager.load_config()
            VideoRuntime._write_media_config(target, loaded, [loaded["streams"][0]])
            document = target.read_text(encoding="utf-8")
            bad_gateway = {**gateway, "api_url": "http://127.0.0.1:19997/other"}
            bad = self._config(root, gateway=bad_gateway)
            bad_detail = VideoManager(bad).status()["gateway"]["detail"]
        self.assertIn("apiAddress: 127.0.0.1:19997", document)
        self.assertIn("moq: false", document)
        self.assertIn("必须是 /v3/paths/list", bad_detail)

    def test_full_deb_embeds_private_video_runtime_and_postinst_copies_it_to_workspace(self):
        deb_script = (ROOT / "build_deb_package.sh").read_text(encoding="utf-8")
        postinst = (ROOT / "packaging" / "debian" / "postinst").read_text(encoding="utf-8")
        runtime_builder = (ROOT / "build_video_runtime.sh").read_text(encoding="utf-8")
        self.assertIn('build_video_runtime.sh" --output-dir "$VIDEO_RUNTIME"', deb_script)
        self.assertIn('video_runtime', deb_script)
        self.assertIn('"$ROOT/runtime/video/"', postinst)
        self.assertIn('mediamtx_v${MEDIAMTX_VERSION}_linux_${ARCH}.tar.gz', runtime_builder)
        self.assertIn('libgstrawparse.so', runtime_builder)
        self.assertIn('libgstapp.so', runtime_builder)
        self.assertIn('libgstrtp.so', runtime_builder)
        self.assertIn('libgstrtpmanager.so', runtime_builder)
        self.assertIn('GST_PLUGIN_SYSTEM_PATH_1_0="$RUNTIME/plugins"', runtime_builder)
        self.assertIn('export LD_LIBRARY_PATH="$RUNTIME/lib"', runtime_builder)
        self.assertNotIn('export LD_LIBRARY_PATH="$RUNTIME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"', runtime_builder)

    def test_video_runtime_is_console_owned_and_has_a_manual_maintenance_launcher(self):
        launcher = (ROOT / "packaging" / "debian" / "ry-aletheia-video-launcher").read_text(encoding="utf-8")
        deb_script = (ROOT / "build_deb_package.sh").read_text(encoding="utf-8")
        postinst = (ROOT / "packaging" / "debian" / "postinst").read_text(encoding="utf-8")
        self.assertIn("start|stop|status|restart", launcher)
        self.assertIn("--video-runner", launcher)
        self.assertIn("$HOME/.bashrc", launcher)
        self.assertIn('setsid "$RUNNER" --video-runner', launcher)
        self.assertIn("runner_has_private_process_group", launcher)
        self.assertIn('kill "-$signal" -- "-$pid"', launcher)
        self.assertNotIn("supervisorctl", launcher)
        self.assertIn('ry-aletheia-video-launcher" "$PKG/usr/bin/ry-aletheia-video"', deb_script)
        self.assertFalse((ROOT / "packaging" / "debian" / "ry-aletheia-video-supervisor.conf").exists())
        self.assertIn('ry-aletheia-video.conf', postinst)
        self.assertIn('rm -f /etc/supervisor/conf.d/ry-aletheia-video.conf', postinst)
        self.assertIn('SUPERVISORCTL="$(command -v supervisorctl || true)"', postinst)
        self.assertIn('if [[ -n "$SUPERVISORCTL" ]]; then', postinst)
        console = (ROOT / "web_console.py").read_text(encoding="utf-8")
        self.assertIn("video_runtime.start_if_enabled()", console)
        self.assertIn("video_runtime.stop()", console)


if __name__ == "__main__":
    unittest.main()
