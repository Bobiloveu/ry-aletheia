import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from autodrive_console.map_assets import CachedMapAsset
from autodrive_console.trajectory import ActiveMap, TrajectorySession, _apply_planar_transform, _is_future_extrapolation, _transform_lag_ns
from autodrive_console.trajectory_render import render_svg
from autodrive_console.navigation_status import NavigationStatusMonitor


class TrajectoryIntegrityTests(unittest.TestCase):
    def test_session_retains_sampling_watchdog_and_progress_methods(self):
        # 防止后续重构时缩进错误让这些运行时关键方法脱离 TrajectorySession。
        for name in ("_on_sample", "_on_watchdog", "_observe_motion", "_estimate_progress", "_match_asset"):
            self.assertTrue(callable(getattr(TrajectorySession, name, None)), name)

    def test_map_switch_signature_is_not_only_load_time(self):
        # 两张图即使 map_load_time 都为 0，也必须被视为不同地图。
        p1 = ActiveMap("p1", "P1", 0, 0.05, 100, 100, -1.0, -1.0, "map")
        p2 = ActiveMap("p2", "P2", 0, 0.05, 100, 100, -1.0, -1.0, "map")
        self.assertNotEqual(p1, p2)

    def test_ros_map_binds_route_when_json_map_reference_is_unavailable(self):
        route_plan = [{"map_id": None, "map_label": "ROS2 当前地图", "name": "测试路线", "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}]}]
        with tempfile.TemporaryDirectory() as directory:
            session = TrajectorySession([], route_plan=route_plan, map_cache_dir=Path(directory))
            message = SimpleNamespace(
                header=SimpleNamespace(frame_id="map"), data=[0, 100, -1, 50],
                info=SimpleNamespace(
                    map_load_time=SimpleNamespace(sec=0, nanosec=0), resolution=0.5, width=2, height=2,
                    origin=SimpleNamespace(position=SimpleNamespace(x=0.0, y=0.0)),
                ),
            )
            session._on_map(message)
            active = session._active_map
            self.assertIsNotNone(active)
            self.assertTrue(active.asset_id)
            session._estimate_progress(active, 0.1, 0.0, 1)
            self.assertEqual(session.route_plan[0]["map_id"], active.asset_id)
            self.assertTrue(Path(next(item.cache_image for item in session.maps if item.id == active.asset_id)).is_file())

    def test_ros_map_replaces_equivalent_offline_asset_instead_of_creating_empty_duplicate_view(self):
        """实际 /map 与同几何离线 PGM 不能在报告中生成两个同名地图选项。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            offline = CachedMapAsset("offline-p2", "P2", "", "", "", 0.5, [0.0, 0.0], 2, 2)
            session = TrajectorySession([offline], route_plan=[{
                "map_id": "offline-p2", "map_label": "P2", "name": "路线", "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}],
            }], map_cache_dir=root)
            message = SimpleNamespace(
                header=SimpleNamespace(frame_id="map"), data=[0, 100, -1, 50],
                info=SimpleNamespace(
                    map_load_time=SimpleNamespace(sec=0, nanosec=0), resolution=0.5, width=2, height=2,
                    origin=SimpleNamespace(position=SimpleNamespace(x=0.0, y=0.0)),
                ),
            )
            session._on_map(message)
            self.assertEqual(len(session.maps), 1)
            self.assertNotEqual(session.maps[0].id, "offline-p2")
            self.assertEqual(session.route_plan[0]["map_id"], session.maps[0].id)

    def test_reentered_map_requires_a_new_segment_epoch(self):
        # 户外→电梯厅→楼层→电梯厅，且所有 map_load_time 都为 0 时，仍要识别每一次切图。
        assets = [
            CachedMapAsset("p1", "户外 P1", "", "", "", 0.05, [-1.0, -1.0], 100, 100),
            CachedMapAsset("p2", "电梯厅 P2", "", "", "", 0.05, [-1.0, -1.0], 120, 100),
            CachedMapAsset("p3", "用户楼层 P3", "", "", "", 0.05, [-1.0, -1.0], 140, 100),
        ]
        session = TrajectorySession(assets)

        def map_message(width):
            return SimpleNamespace(
                header=SimpleNamespace(frame_id="map"),
                info=SimpleNamespace(
                    map_load_time=SimpleNamespace(sec=0, nanosec=0), resolution=0.05, width=width, height=100,
                    origin=SimpleNamespace(position=SimpleNamespace(x=-1.0, y=-1.0)),
                ),
            )

        session._on_map(map_message(100))
        session._on_map(map_message(120))
        session._on_map(map_message(140))
        session._on_map(map_message(120))
        self.assertEqual(session._map_epoch, 4)
        self.assertEqual(session._active_map.asset_id, "p2")

    def test_map_from_odom_planar_transform(self):
        # map←odom：绕原点逆时针 90°，再平移 (10, 20)。odom (2, 3) 必须落在 map (7, 22)。
        translation = SimpleNamespace(x=10.0, y=20.0)
        rotation = SimpleNamespace(x=0.0, y=0.0, z=math.sqrt(0.5), w=math.sqrt(0.5))
        mapped = _apply_planar_transform(translation, rotation, 2.0, 3.0)
        self.assertAlmostEqual(mapped[0], 7.0, places=6)
        self.assertAlmostEqual(mapped[1], 22.0, places=6)

    def test_short_future_tf_extrapolation_can_use_latest_transform(self):
        self.assertTrue(_is_future_extrapolation(RuntimeError("Lookup would require extrapolation into the future.")))
        self.assertFalse(_is_future_extrapolation(RuntimeError("Frame map does not exist")))
        transform = SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=100, nanosec=800_000_000)))
        request = SimpleNamespace(sec=101, nanosec=0)
        self.assertEqual(_transform_lag_ns(transform, request), 200_000_000)
        self.assertIsNone(_transform_lag_ns(SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=0, nanosec=0))), request))

    def test_high_frequency_odom_is_processed_only_at_sample_rate(self):
        session = TrajectorySession([])
        session._active_map = ActiveMap("map", "地图", 0, 0.05, 100, 100, 0.0, 0.0, "odom")

        def odom(x):
            return SimpleNamespace(
                header=SimpleNamespace(frame_id="odom", stamp=SimpleNamespace(sec=1, nanosec=int(x))),
                pose=SimpleNamespace(pose=SimpleNamespace(position=SimpleNamespace(x=float(x), y=2.0))),
            )

        # 高频消息不会在回调中触发 TF、路线投影或轨迹落盘；只保留最新坐标。
        for x in (1, 2, 3):
            session._on_odom(odom(x))
        self.assertEqual(session._odom_received, 3)
        self.assertEqual(session._segments, {})

        session._on_sample()
        points = next(iter(session._segments.values()))["points"]
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["x"], 3.0)
        self.assertEqual(session._samples_processed, 1)

        # 未收到新消息时，后续定时器不会重复写入相同轨迹点。
        session._on_sample()
        self.assertEqual(len(next(iter(session._segments.values()))["points"]), 1)

    def test_temporary_tf_loss_keeps_last_route_percent(self):
        session = TrajectorySession([])
        session._active_map = ActiveMap("map", "地图", 0, 0.05, 100, 100, 0.0, 0.0, "map")
        session._reported_percent = 42.3
        session._last_progress = {"route_name": "前一有效路线", "route_index": 2, "route_total": 3, "map_label": "地图"}
        observed = []
        session.progress_callback = observed.append
        session._to_map_coordinates = lambda *_args: None
        message = SimpleNamespace(
            header=SimpleNamespace(frame_id="odom", stamp=SimpleNamespace(sec=1, nanosec=0)),
            pose=SimpleNamespace(pose=SimpleNamespace(position=SimpleNamespace(x=1.0, y=2.0))),
        )

        session._on_odom(message)
        session._on_sample()

        self.assertEqual(observed[-1]["percent"], 42.3)
        self.assertEqual(observed[-1]["route_name"], "前一有效路线")
        self.assertEqual(observed[-1]["state"], "等待 map←odom 坐标变换")

    def test_same_map_route_segments_are_recorded_separately(self):
        """同一张图内的去程/回程子任务不能因未切图而被合并成同色轨迹。"""
        asset = CachedMapAsset("map", "P1", "", "", "", 1.0, [0.0, 0.0], 20, 20)
        route_plan = [
            {"map_id": "map", "map_label": "P1", "name": "去程", "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}]},
            {"map_id": "map", "map_label": "P1", "name": "回程", "points": [{"x": 1.0, "y": 0.0}, {"x": 0.0, "y": 0.0}]},
        ]
        session = TrajectorySession([asset], route_plan=route_plan)
        session._active_map = ActiveMap("map", "P1", 0, 1.0, 20, 20, 0.0, 0.0, "odom")
        session._to_map_coordinates = lambda _active, _source, _stamp, x, y: (x, y)

        def odom(sequence, x):
            return SimpleNamespace(
                header=SimpleNamespace(frame_id="odom", stamp=SimpleNamespace(sec=1, nanosec=sequence)),
                pose=SimpleNamespace(pose=SimpleNamespace(position=SimpleNamespace(x=x, y=0.0))),
            )

        session._on_odom(odom(1, 1.0))  # 到达去程终点，随后路线推进至回程。
        session._on_sample()
        session._on_odom(odom(2, 0.0))
        session._on_sample()

        segments = sorted(session._segments.values(), key=lambda item: item["route_index"])
        self.assertEqual([item["route_index"] for item in segments], [0, 1])
        self.assertEqual([item["route_name"] for item in segments], ["去程", "回程"])

    def test_map_mismatch_does_not_report_false_zero_progress(self):
        """当前 /map 尚未切到子任务地图时，网页必须显示不可计算而非假 0%。"""
        session = TrajectorySession([], route_plan=[{
            "map_id": "expected-p1", "map_label": "P1", "name": "去程",
            "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}],
        }])
        active = ActiveMap("actual-p2", "P2", 0, 1.0, 20, 20, 0.0, 0.0, "map")
        progress = session._estimate_progress(active, 0.2, 0.0, 10)

        self.assertFalse(progress["progress_available"])
        self.assertEqual(progress["state"], "等待切换至当前子任务地图")
        self.assertEqual(progress["expected_map_label"], "P1")

    def test_elevator_status_suppresses_normal_stall_then_alerts_once_on_timeout(self):
        monitor = NavigationStatusMonitor(timeout_s=60)
        elevator = SimpleNamespace(status="task_executing", current_speed_mode="elevator_in", current_waypoint_id="elevator_in", current_task="等待电梯")
        self.assertTrue(monitor.observe(elevator, now=10).active)
        self.assertFalse(monitor.snapshot(now=69).timed_out)
        self.assertTrue(monitor.snapshot(now=70).timed_out)
        # 连续非电梯状态须持续一小段时间才退出，避免状态消息抖动导致误告警。
        normal = SimpleNamespace(status="navigating", current_speed_mode="task_point", current_waypoint_id="normal", current_task="")
        self.assertTrue(monitor.observe(normal, now=71).active)
        self.assertFalse(monitor.snapshot(now=76).active)

        session = TrajectorySession([])
        monitor.observe(elevator, now=100)
        wait = monitor.snapshot(now=160)
        first, second = {}, {}
        session._apply_elevator_wait(first, wait)
        session._apply_elevator_wait(second, monitor.snapshot(now=160))
        self.assertTrue(first["alert"])
        self.assertEqual(first["alert_id"], second["alert_id"])

    def test_multiple_paths_remain_disconnected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "map.pgm"
            image.write_bytes(b"P5\n10 10\n255\n" + bytes([255]) * 100)
            target = root / "result.svg"
            asset = CachedMapAsset("map", "P1", "", "", str(image), 1.0, [0.0, 0.0], 10, 10)
            render_svg(asset, {"paths": [{"map_epoch": 1, "route_index": 0, "points": [{"x": 1, "y": 1}, {"x": 2, "y": 1}]}, {"map_epoch": 4, "route_index": 1, "points": [{"x": 8, "y": 8}, {"x": 9, "y": 8}]}]}, target)
            svg = target.read_text(encoding="utf-8")
            self.assertIn('points="1.00,9.00 2.00,9.00"', svg)
            self.assertIn('points="8.00,2.00 9.00,2.00"', svg)
            self.assertNotIn('2.00,9.00 8.00,2.00', svg)
            self.assertIn("轨迹 1 · 任务段 1", svg)
            self.assertIn("轨迹 2 · 任务段 2", svg)
            self.assertIn("#168cff", svg)
            self.assertIn("#9b6dff", svg)
            self.assertNotIn("marker-end=", svg)
            self.assertNotIn("<marker", svg)
            self.assertIn('<g transform="translate(0 110)">', svg)
            self.assertNotIn('>1S</text>', svg)


if __name__ == "__main__":
    unittest.main()
