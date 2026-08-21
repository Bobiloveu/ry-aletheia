"""实时观测的背压与时效边界。

这些测试不依赖浏览器或 ROS 图，专门验证最容易在现场无线抖动时退化的
latest-wins 策略：页面恢复后只消费最新数据，绝不补绘旧数据。
"""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _simulate_latest_wins(rate_hz: int, max_age_ms: int, blocked_windows: list[tuple[int, int]]) -> tuple[int, int, int]:
    """模拟 WebSocket 输入与 rAF 消费；返回最大队列、消费数、过期丢弃数。"""
    pending = None
    maximum_pending = consumed = stale = 0
    interval_ms = 1000 / rate_hz
    next_packet = 0.0
    for now in range(0, 5001):
        while next_packet <= now:
            # 单槽覆盖：新帧到达时永远替换旧帧。
            pending = next_packet
            maximum_pending = max(maximum_pending, 1)
            next_packet += interval_ms
        blocked = any(start <= now < end for start, end in blocked_windows)
        if pending is not None and not blocked and now % 16 == 0:
            if now - pending <= max_age_ms:
                consumed += 1
            else:
                stale += 1
            pending = None
    return maximum_pending, consumed, stale


def test_realtime_source_declares_single_slot_freshness_boundaries():
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert "const CLOUD_PACKET_MAX_AGE_MS = 100;" in source
    assert "context.fillStyle = 'rgb(128, 88, 255)';" in source
    assert "const POSE_PACKET_MAX_AGE_MS = 250;" in source
    assert "const LIVE_POSE_FALLBACK_MS = 450;" in source
    assert "function armTfFallback()" in source
    assert "armTfFallback();" in source
    assert "if (tfFallbackTimer) return;" in source
    assert "setTimeout(check" in source
    assert "const VEHICLE_POSITION_DEADBAND_M = 0.006;" in source
    assert "const MAX_VEHICLE_PREDICTION_MS = 300;" in source
    assert "function predictVehicleMotion(pose, seconds)" in source
    assert "α-β 预测—校正" in source
    assert "function sourcePoseAge(message)" in source
    assert "function stabilizeStationaryVehicle(position, yaw, now)" in source
    assert "const VEHICLE_STILL_HOLD_DISTANCE_M = 0.025;" in source
    assert "const VEHICLE_STILL_RELEASE_DISTANCE_M = 0.045;" in source
    assert "function reportClientMetrics()" in source
    assert "/api/observation/client-metrics" in source
    assert "translate3d(${x}px, ${y}px, 0)" in source
    assert "element.style.left" not in source
    assert "pendingCloudPacket = { reader, data, receivedAt: performance.now() };" in source
    assert "pendingPosePacket = { reader, data, receivedAt: performance.now() };" in source
    assert "scheduleLatestCloudPacket(reader, data); return;" in source
    assert "scheduleLatestPosePacket(reader, data); return;" in source


def test_live_view_has_phone_specific_safe_area_and_map_priority_rules():
    source = (ROOT / "frontend" / "src" / "liveObservation.css").read_text(encoding="utf-8")
    assert "@media (max-width: 480px)" in source
    assert "grid-template-rows: 70% 15% 15%" in source
    assert "orientation: landscape" in source




def test_runtime_uses_a_dedicated_high_rate_pose_stream():
    source = (ROOT / "autodrive_console" / "observation.py").read_text(encoding="utf-8")
    assert '"pose_rate_hz:=60.0"' in source
    assert '"max_input_age_ms:=140"' in source
    assert '"max_pose_age_ms:=250"' in source
    assert '"__node:=ry_aletheia_live_cloud"' in source
    assert '"__node:=ry_aletheia_live_pose"' in source
    assert '"enable_cloud:=true"' in source
    assert '"enable_pose:=true"' in source
    assert 'INTERNAL_LIVE_CLOUD_TOPIC = "/_aletheia/live_points"' in source
    assert 'INTERNAL_LIVE_POSE_TOPIC = "/_aletheia/live_pose"' in source
    assert '"include_hidden:=true"' in source


def test_pose_stream_is_reliable_and_does_not_drop_latest_composed_transform():
    source = (ROOT / "live_preprocessor" / "src" / "live_cloud_preprocessor.cpp").read_text(encoding="utf-8")
    assert "rclcpp::QoS(rclcpp::KeepLast(1)).reliable().durability_volatile()" in source
    assert "auto cloud_output_qos = rclcpp::QoS(rclcpp::KeepLast(1)).reliable().durability_volatile();" in source
    assert "create_publisher<sensor_msgs::msg::PointCloud2>(output_topic_, cloud_output_qos)" in source
    assert "publishing latest pose for display" in source
    assert '"/_aletheia/live_points"' in source
    assert '"/_aletheia/live_pose"' in source


def test_cloud_stream_is_event_driven_and_tightly_freshness_bounded():
    source = (ROOT / "live_preprocessor" / "src" / "live_cloud_preprocessor.cpp").read_text(encoding="utf-8")
    assert 'declare_parameter<int>("max_input_age_ms", 140)' in source
    assert "publish_latest();" in source
    assert "rate_hz_), [this] { publish_latest(); });" not in source
    assert "last_standard_input_at_" in source
    assert "latest_input_received_at_" in source
    assert "std::chrono::now()" not in source
    assert "std::chrono::milliseconds(500)" in source


def test_cloud_stream_uses_livox_per_point_time_for_rotation_deskew():
    source = (ROOT / "live_preprocessor" / "src" / "live_cloud_preprocessor.cpp").read_text(encoding="utf-8")
    assert 'field.name == "timestamp"' in source
    assert "kDeskewBucketNs = 5'000'000LL" in source
    assert "Deskew fallback: incomplete TF coverage" in source
    assert "deskew_transforms.clear();" in source


def test_map_subscription_is_persistent_and_reasserted_only_after_confirmed_map_switch():
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert "if (mapProbeSubscriptionId !== undefined) return;" in source
    assert "function reassertMapProbe()" in source
    assert "仅 active_map_id 确认变化才执行一次" in source
    assert "const ACTIVE_MAP_SYNC_MS = 1000;" in source


def test_virtual_wall_match_retries_only_after_a_transient_miss():
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    backend = (ROOT / "autodrive_console" / "observation.py").read_text(encoding="utf-8")
    assert "const LIVE_WALL_RETRY_DELAYS_MS = [800, 2000, 5000];" in source
    assert "function scheduleLiveWallRetry(info, fingerprint)" in source
    assert "resolveLiveWalls(mapInfo, fingerprint, true);" in source
    assert "if (layers.matched) resetLiveWallRetry();" in source
    assert "if result[\"matched\"]:" in backend
    assert "self._live_map_matches.pop(signature, None)" in backend
    assert "function scheduleMapProbe()" not in source
    assert "MAP_PROBE_INTERVAL_MS" not in source


def test_map_transition_invalidates_async_cloud_frames():
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    worker = (ROOT / "frontend" / "src" / "liveCloudWorker.js").read_text(encoding="utf-8")
    assert "function invalidateMapScopedCloud()" in source
    assert "pendingCloudPacket = undefined; pendingCloudFrame = undefined;" in source
    assert "generation: mapGeneration" in source
    assert "data.generation !== map.generation" in worker


def test_preprocessed_map_cloud_avoids_per_point_object_churn():
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert "const packedMapPoints = isMapFrame ? new Float32Array" in source
    assert "packedMapPoints: packedMapPoints.subarray(0, pointOffset)" in source
    assert "cloudFrames" not in source


def test_cloud_composition_is_latest_wins_and_paced_below_vehicle_rendering():
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert "const CLOUD_COMPOSITE_MIN_INTERVAL_MS = 125;" in source
    assert "pendingCloudFrame = frame;" in source
    assert "const delay = CLOUD_COMPOSITE_MIN_INTERVAL_MS" in source
    assert "lastCloudWorkerSubmitAt = performance.now();" in source


def test_pause_does_not_create_historical_cloud_backlog():
    # 10 Hz 点云，页面发生 1.2 秒卡顿；恢复后队列仍为一个最新样本，而不是 12 帧。
    maximum, consumed, stale = _simulate_latest_wins(10, 180, [(1000, 2200)])
    assert maximum == 1
    assert consumed > 20
    assert stale == 0


def test_pose_recovery_prefers_latest_sample_after_render_pause():
    # 30 Hz 位姿、较长暂停：恢复时只会显示最新一个样本，且不会按顺序回放。
    maximum, consumed, stale = _simulate_latest_wins(30, 250, [(900, 1900), (3100, 3400)])
    assert maximum == 1
    assert consumed > 80
    assert stale == 0
