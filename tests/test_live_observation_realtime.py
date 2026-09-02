"""实时观测的背压与时效边界。

这些测试不依赖浏览器或 ROS 图，专门验证最容易在现场无线抖动时退化的
latest-wins 策略：页面恢复后只消费最新数据，绝不补绘旧数据。
"""

from pathlib import Path
import re


ROOT = Path(__file__).parents[1]


def _assert_source_contains(source: str, expected: str) -> None:
    """Assert source semantics without treating formatter output as a regression."""
    normalize = lambda value: re.sub(
        r",(?=[)\]}])", "", re.sub(r"\s+", "", value).replace('"', "'")
    )
    assert normalize(expected) in normalize(source)


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
    _assert_source_contains(source, "import { Application, BufferImageSource, Container, Graphics, Sprite, Texture } from 'pixi.js';")
    assert "cameraSlots" not in source
    assert "function initializeCameraRenderer(slot)" not in source
    assert "getContext('2d')" not in source
    assert "function renderCloudPoints(packedPoints)" in source
    assert "const DESKTOP_MAP_PALETTE" in source
    _assert_source_contains(source, "points.fill((mobileConsoleEnabled() ? MAP_PALETTE : DESKTOP_MAP_PALETTE).cloud);")
    assert "points.fill(0x8058ff);" not in source
    assert "const POSE_PACKET_MAX_AGE_MS = 250;" in source
    assert "const LIVE_POSE_FALLBACK_MS = 450;" in source
    assert "const VEHICLE_POSITION_DEADBAND_M = 0.012;" in source
    assert "const MAX_VEHICLE_PREDICTION_MS = 300;" in source
    assert "function predictVehicleMotion(pose, seconds)" in source
    assert "α-β 预测—校正" in source
    assert "function telemetrySourceAgeMs(timestampNs)" in source
    assert "function estimateLiveMotion(position, yaw, now)" in source
    assert "const STATIC_POSE_POSITION_HOLD_M = 0.03;" in source
    assert "const STATIC_POSE_YAW_HOLD_RAD = 0.02;" in source
    assert "vehicleStillAnchor" not in source
    # 高频轻量 Pose 会重复发布同一位置以维持链路；外推必须以最后一次实际测量
    # 为起点，不能被每个心跳包的 receivedAt 反复归零。
    assert "motionMeasuredAt: latestLiveMotion.measuredAt" in source
    _assert_source_contains(source, "const motionMeasuredAt = target.source === 'live' ? target.motionMeasuredAt : target.receivedAt;")
    assert "function reportClientMetrics()" in source
    assert "/api/observation/client-metrics" in source
    assert "视频输入等待超时" in source
    _assert_source_contains(source, "window.addEventListener('unhandledrejection'")
    assert "translate3d(${x}px, ${y}px, 0)" in source
    assert "element.style.left" not in source
    assert "pendingCloudPacket = { data, receivedAt: performance.now() };" in source
    assert "pendingPosePacket = { data, receivedAt: performance.now() };" in source
    assert "function connectTelemetry(payload)" in source
    _assert_source_contains(source, "openLane('cloud', '/cloud'")
    _assert_source_contains(source, "openLane('pose', '/pose'")
    assert "telemetryReconnectTimers" in source
    assert "closeTelemetryConnections()" in source
    assert "@foxglove/" not in source


def test_live_view_has_phone_specific_safe_area_and_map_priority_rules():
    source = (ROOT / "frontend" / "src" / "liveObservation.css").read_text(encoding="utf-8")
    assert "@media (orientation: portrait)" in source
    assert "grid-template: minmax(0, 1fr) / minmax(0, 1fr)" in source
    assert "orientation: landscape" in source


def test_mobile_console_supports_both_orientations_and_scopes_zoom_to_the_map():
    html = (ROOT / "frontend" / "live-observation.html").read_text(encoding="utf-8")
    stylesheet = (ROOT / "frontend" / "src" / "liveObservation.css").read_text(encoding="utf-8")
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert "viewport-fit=cover" in html
    assert "user-scalable=no" in html
    assert "interactive-widget=resizes-content" in html
    assert 'id="mobileRotateGuard"' not in html
    assert 'id="mobileFullscreenToggle"' not in html
    assert 'data-mobile-view-target="map"' in html
    assert 'data-mobile-view-target="camera"' in html
    assert 'class="mobile-bottom-nav"' in html
    assert "html.mobile-console #app" in stylesheet
    assert "var(--mobile-viewport-width, 100dvw)" in stylesheet
    assert "var(--mobile-viewport-height, 100dvh)" in stylesheet
    assert "env(safe-area-inset-left)" in stylesheet
    assert "html.mobile-console.mobile-portrait .page-main" in stylesheet
    assert "html.mobile-console.mobile-portrait .webrtc-video-grid[data-count]" in stylesheet
    assert "touch-action: pan-y" in stylesheet
    assert 'html.mobile-console .webrtc-video-grid[data-count="5"]' in stylesheet
    assert 'html.mobile-console .webrtc-video-grid[data-count="6"]' in stylesheet
    assert "screen.orientation.lock('landscape')" not in source
    assert "window.visualViewport" in source
    assert "function setupMobileZoomPolicy()" in source
    _assert_source_contains(source, "['gesturestart', 'gesturechange', 'gestureend']")
    assert "event.touches.length > 1 && !insideMap(event.target)" in source
    assert "function setMobileConsoleView(view" in source
    assert "mobileWebRtcPlaybackAllowed()" in source
    assert "stopVisualizationStreams();" not in source
    assert "相机页未显示，浏览器解码已暂停" in source
    assert "const shallowLandscape" in source
    assert "focusedLandscapeScale" in source
    assert "优先可读性而不是留出大量无效背景" in source
    assert "@media (orientation: landscape) and (max-height: 430px)" in stylesheet


def test_map_removes_legacy_settings_entry_without_a_duplicate_status_header():
    html = (ROOT / "frontend" / "live-observation.html").read_text(encoding="utf-8")
    stylesheet = (ROOT / "frontend" / "src" / "liveObservation.css").read_text(encoding="utf-8")
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert 'id="toggleWorkspaceControls"' not in html
    assert 'id="workspaceControlsBody"' not in html
    assert '<article class="workspace-widget map-widget" data-widget="map">\n            <header class="widget-header">' not in html
    assert "$('toggleWorkspaceControls')" not in source
    # 地图标题条已移除，移动端顶部状态仍须独立镜像更新。
    _assert_source_contains(source, "const target = $(id); if (target) target.textContent = value;")
    assert "mirrorMobileConnection(id, value);" in source


def test_map_uses_an_adaptive_metric_grid_and_restrained_industrial_palette():
    html = (ROOT / "frontend" / "live-observation.html").read_text(encoding="utf-8")
    stylesheet = (ROOT / "frontend" / "src" / "liveObservation.css").read_text(encoding="utf-8")
    mobile_stylesheet = (ROOT / "autodrive_console" / "web" / "mobile_console.css").read_text(encoding="utf-8")
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert 'id="mapScale"' in html
    assert 'id="mapGridLabel"' in html
    assert "let pixiGridLayer;" in source
    _assert_source_contains(source, "pixiWorld.addChild(pixiMapLayer, pixiGridLayer, pixiWallLayer, pixiCloudLayer);")
    assert "function metricGridStep(pixelsPerMeter)" in source
    assert "function renderMetricGrid(layout)" in source
    assert "renderMetricGrid(layout);" in source
    assert "gridStep * 5" in source
    assert "width: 0.65 / layout.ratio" in source
    assert "width: 1.1 / layout.ratio" in source
    assert "virtualWall: 0xd63142" in source
    assert "cloud: 0x8b5cf6" in source
    assert "virtualWall: 0xd63142" in source
    assert "cloud: 0x6426d9" in source
    assert "if (!mobileConsoleEnabled())" in source
    assert ".map-scale" in stylesheet
    assert "--ui-accent: #f28c28" in mobile_stylesheet
    assert "color: var(--ui-accent-strong)" in stylesheet
    assert "const pointRadius = mobile ? 0.82 : 0.52;" in source


def test_vehicle_marker_has_a_minimal_rotating_front_line_without_an_arrow():
    stylesheet = (ROOT / "frontend" / "src" / "liveObservation.css").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "live-observation.html").read_text(encoding="utf-8")
    assert "#vehicleLayer i" in stylesheet
    _assert_source_contains(stylesheet, "top:9%; left:20%; right:20%; height:4px")
    assert "#vehicleLayer::before" not in stylesheet
    assert "clip-path:polygon" not in stylesheet
    assert "map-legend" not in html


def test_industrial_video_uses_whep_html_video_and_pixi_texture_without_a_frame_relay():
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "live-observation.html").read_text(encoding="utf-8")
    _assert_source_contains(source, "request('/api/video/status')")
    _assert_source_contains(source, "request('/api/video/control'")
    assert "function toggleWebRtcVideo()" in source
    assert "function toggleWebRtcStream(stream)" in source
    assert "function renderWebRtcStreamControls(streams)" in source
    assert "webrtcStreamTogglesInFlight" in source
    assert 'id="webrtcVideoToggle"' in html
    assert 'id="webrtcStreamControls"' in html
    _assert_source_contains(source, "document.createElement('video')")
    _assert_source_contains(source, "peer.addTransceiver('video', { direction: 'recvonly' })")
    _assert_source_contains(source, "method: 'POST'")
    assert "application/sdp" in source
    assert "Texture.from(state.video)" in source
    assert "new Sprite(state.texture)" in source
    assert "WebSocket(stream.url" not in source
    assert 'id="webrtcVideoGrid"' in html
    stylesheet = (ROOT / "frontend" / "src" / "liveObservation.css").read_text(encoding="utf-8")
    assert '.webrtc-video-grid[data-count="5"]' in stylesheet
    assert '.webrtc-video-grid[data-count="6"]' in stylesheet
    assert '.webrtc-stream-controls' in stylesheet
    assert "mobilePrimaryWebRtcStream" in source
    assert "setMobilePrimaryWebRtcStream(stream.name)" in source
    assert '.webrtc-video-card[data-primary="true"]' in stylesheet
    # 手机端六路卡片本身就是逐路开关。即使全局视频未启用，也必须保留
    # 已配置的六路入口；不能让顶部开关条挤压任何一张画面。
    assert "const streams = mobileConsoleEnabled() ? configuredStreams : activeStreams;" in source
    assert "state.card.dataset.active = String(active);" in source
    _assert_source_contains(source, "toggle.addEventListener('click', () => toggleWebRtcStream(state.stream));")
    _assert_source_contains(stylesheet, "html.mobile-console .webrtc-stream-controls { display: none !important; }")
    assert 'html.mobile-console .webrtc-video-card[data-active="false"]' in stylesheet
    _assert_source_contains(stylesheet, 'html.mobile-console .webrtc-video-grid[data-count="5"] > .webrtc-video-card[data-primary="true"]')
    _assert_source_contains(stylesheet, 'html.mobile-console .webrtc-video-grid[data-count="6"] > .webrtc-video-card[data-primary="true"]')
    assert 'object-fit: contain;' in stylesheet
    assert 'html.mobile-console #mobileConnectionSignal::before' in stylesheet
    # 顶部旧开关条在手机端必须从布局树移除；多路栅格要显式复位历史 span 规则，
    # 防止在横竖屏切换后把视频卡压成细条。
    assert "root.hidden = mobile;" in source
    _assert_source_contains(stylesheet, 'html.mobile-console .webrtc-stream-controls[hidden] { display: none !important; }')
    assert 'html.mobile-console .webrtc-video-grid[data-count] > .webrtc-video-card {' in stylesheet
    assert 'grid-column: auto;' in stylesheet
    _assert_source_contains(stylesheet, 'grid-template: minmax(0, 1fr) repeat(2, minmax(68px, 0.36fr)) / repeat(2, minmax(0, 1fr)) !important;')
    assert "const pointRadius = mobile ? 0.82 : 0.52;" in source


def test_desktop_map_has_no_redundant_foxglove_image_splitter_or_image_subscription():
    html = (ROOT / "frontend" / "live-observation.html").read_text(encoding="utf-8")
    stylesheet = (ROOT / "frontend" / "src" / "liveObservation.css").read_text(encoding="utf-8")
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert 'id="cameraSelectA"' not in html
    assert 'id="cameraSelectB"' not in html
    assert 'id="verticalSplitter"' not in html
    assert 'id="horizontalSplitter"' not in html
    assert 'aria-label="实时二维地图工作区"' in html
    _assert_source_contains(stylesheet, ".local-viewer-workspace { position: relative; display: grid;")
    assert "grid-template: minmax(0, 1fr) / minmax(0, 1fr);" in stylesheet
    assert "cameraChannels" not in source
    assert "cameraSlots" not in source
    assert "function connectTelemetry(payload)" in source




def test_runtime_uses_a_dedicated_high_rate_pose_stream():
    source = (ROOT / "autodrive_console" / "observation.py").read_text(encoding="utf-8")
    assert '"pose_rate_hz:=60.0"' in source
    assert '"max_input_age_ms:=140"' in source
    assert '"max_pose_age_ms:=250"' in source
    assert '"__node:=ry_aletheia_live_cloud"' in source
    assert '"__node:=ry_aletheia_live_pose"' in source
    assert '"enable_cloud:=true"' in source
    assert '"enable_pose:=true"' in source
    assert 'f"telemetry_udp_port:={TelemetryGateway.UDP_PORT}"' in source
    assert 'f"telemetry_udp_port:={TelemetryGateway.POSE_UDP_PORT}"' in source
    assert 'foxglove_bridge' not in source


def test_static_pose_noise_is_held_before_the_vehicle_render_filter():
    """静止 TF 微扰不能绕过前端的可信姿态锚点直接驱动车体。"""
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert "const STATIC_POSE_POSITION_HOLD_M = 0.03;" in source
    assert "const STATIC_POSE_YAW_HOLD_RAD = 0.02;" in source
    assert "const positionChanged = distance >= STATIC_POSE_POSITION_HOLD_M;" in source
    assert "position: latestLiveMotion.position," in source
    assert "yaw: latestLiveMotion.yaw," in source


def test_pose_stream_uses_a_separate_latest_wins_udp_sender_without_a_hidden_ros_topic():
    source = (ROOT / "live_preprocessor" / "src" / "live_cloud_preprocessor.cpp").read_text(encoding="utf-8")
    assert "class UdpLatestSender final" in source
    assert "std::optional<QueuedFrame> latest_" in source
    assert "if (superseded(frame.sequence)) return;" in source
    assert "MSG_DONTWAIT" in source
    assert "kUdpPayloadBytes = 1152" in source
    assert "publishing latest pose for display" in source
    assert '"/_aletheia/live_points"' not in source
    assert '"/_aletheia/live_pose"' not in source


def test_cloud_stream_is_event_driven_and_tightly_freshness_bounded():
    source = (ROOT / "live_preprocessor" / "src" / "live_cloud_preprocessor.cpp").read_text(encoding="utf-8")
    assert 'declare_parameter<std::string>("input_topic", "/collision_voxel_layer/points")' in source
    assert '"preserve_primary_density", input_topic_ == "/collision_voxel_layer/points"' in source
    assert 'declare_parameter<int>("max_points", 3000), 500, 3000' in source
    assert "preserve_primary_density_ && input_count <= point_budget" in source
    assert "const size_t point_budget = static_cast<size_t>(max_points_);" in source
    assert 'declare_parameter<int>("max_input_age_ms", 140)' in source
    assert "maybe_publish_latest();" in source
    assert "rate_hz_), [this] { publish_latest(); });" not in source
    assert "last_primary_input_at_" in source
    assert "latest_input_received_at_" in source
    assert "std::chrono::now()" not in source
    assert "std::chrono::milliseconds(500)" in source


def test_cloud_stream_uses_livox_per_point_time_for_rotation_deskew():
    source = (ROOT / "live_preprocessor" / "src" / "live_cloud_preprocessor.cpp").read_text(encoding="utf-8")
    assert 'field.name == "timestamp"' in source
    assert "kDeskewBucketNs = 5'000'000LL" in source
    assert "Deskew fallback: incomplete TF coverage" in source
    assert "deskew_transforms.clear();" in source


def test_map_cache_refresh_is_independent_of_realtime_telemetry():
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert "async function refreshActiveMap(observation)" in source
    assert "function loadCachedMap(mapId, metadata)" in source
    assert "function connectTelemetry(payload)" in source
    assert "const ACTIVE_MAP_SYNC_MS = 1000;" in source


def test_virtual_wall_matching_stays_in_the_existing_map_cache_backend():
    backend = (ROOT / "autodrive_console" / "observation.py").read_text(encoding="utf-8")
    assert "if result[\"matched\"]:" in backend
    assert "self._live_map_matches.pop(signature, None)" in backend


def test_map_transition_invalidates_async_cloud_frames():
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert "function invalidateMapScopedCloud()" in source
    _assert_source_contains(source, "pendingCloudPacket = undefined; pendingCloudFrame = undefined;")
    assert "generation: mapGeneration" in source
    assert "if (frame.generation === mapGeneration) renderCloudPoints(frame.points);" in source


def test_preprocessed_map_cloud_avoids_per_point_object_churn():
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert "const packedMapPoints = new Float32Array(header.pointCount * 2);" in source
    assert "packedMapPoints[index * 2]" in source
    assert "cloudFrames" not in source


def test_cloud_composition_is_latest_wins_and_paced_below_vehicle_rendering():
    source = (ROOT / "frontend" / "src" / "liveObservation.js").read_text(encoding="utf-8")
    assert "const CLOUD_COMPOSITE_MIN_INTERVAL_MS = 125;" in source
    assert "pendingCloudFrame = frame;" in source
    _assert_source_contains(source, "const delay = CLOUD_COMPOSITE_MIN_INTERVAL_MS")
    assert "lastCloudRenderAt = performance.now();" in source


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
