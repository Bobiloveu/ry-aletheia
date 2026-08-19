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
    assert "const CLOUD_PACKET_MAX_AGE_MS = 180;" in source
    assert "const POSE_PACKET_MAX_AGE_MS = 120;" in source
    assert "pendingCloudPacket = { reader, data, receivedAt: performance.now() };" in source
    assert "pendingPosePacket = { reader, data, receivedAt: performance.now() };" in source
    assert "scheduleLatestCloudPacket(reader, data); return;" in source
    assert "scheduleLatestPosePacket(reader, data); return;" in source


def test_pause_does_not_create_historical_cloud_backlog():
    # 10 Hz 点云，页面发生 1.2 秒卡顿；恢复后队列仍为一个最新样本，而不是 12 帧。
    maximum, consumed, stale = _simulate_latest_wins(10, 180, [(1000, 2200)])
    assert maximum == 1
    assert consumed > 20
    assert stale == 0


def test_pose_recovery_prefers_latest_sample_after_render_pause():
    # 30 Hz 位姿、较长暂停：恢复时只会显示最新一个样本，且不会按顺序回放。
    maximum, consumed, stale = _simulate_latest_wins(30, 120, [(900, 1900), (3100, 3400)])
    assert maximum == 1
    assert consumed > 80
    assert stale == 0

