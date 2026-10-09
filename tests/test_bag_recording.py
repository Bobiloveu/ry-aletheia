from __future__ import annotations

import pytest

from autodrive_console.bag_recording import BagRecordingError, BagRecordingManager, RecordingRequest


def _topics():
    return [
        {"name": "/scan", "type": "sensor_msgs/msg/LaserScan", "publisher_count": 1},
        {"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 2},
        {"name": "/hidden", "type": "std_msgs/msg/String", "publisher_count": 1, "hidden": True},
        {"name": "/ambiguous", "type": "std_msgs/msg/String", "publisher_count": 1, "types": ["std_msgs/msg/String", "std_msgs/msg/Int32"]},
        {"name": "/silent", "type": "std_msgs/msg/String", "publisher_count": 0},
        {"name": "/front/image_raw", "type": "sensor_msgs/msg/Image", "publisher_count": 1},
        {"name": "/lidar/points", "type": "sensor_msgs/msg/PointCloud2", "publisher_count": 1},
    ]


def test_available_topics_only_exposes_active_single_type_nonhidden_topics(tmp_path):
    manager = BagRecordingManager(tmp_path, topic_probe=_topics)

    assert manager.available_topics() == [
        {"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 2},
    ]


def test_validate_request_requires_unique_visible_topics_and_target_round(tmp_path):
    manager = BagRecordingManager(tmp_path, topic_probe=_topics)

    request = manager.validate_request({"attemptIndex": 2, "topics": ["/odom"]}, 3)

    assert request == RecordingRequest(2, ("/odom",))
    with pytest.raises(BagRecordingError, match="重复"):
        manager.validate_request({"attemptIndex": 2, "topics": ["/odom", "/odom"]}, 3)
    with pytest.raises(BagRecordingError, match="轮次"):
        manager.validate_request({"attemptIndex": 4, "topics": ["/odom"]}, 3)
    with pytest.raises(BagRecordingError, match="当前不可录制"):
        manager.validate_request({"attemptIndex": 2, "topics": ["/hidden"]}, 3)


def test_validate_request_accepts_null_and_rejects_unknown_payload_shape(tmp_path):
    manager = BagRecordingManager(tmp_path, topic_probe=_topics)

    assert manager.validate_request(None, 1) is None
    with pytest.raises(BagRecordingError, match="字段"):
        manager.validate_request({"attemptIndex": 1, "topics": ["/odom"], "command": "bad"}, 1)


def test_environment_profile_rejects_missing_ros_prefix_and_never_uses_shell(tmp_path):
    manager = BagRecordingManager(
        tmp_path,
        topic_probe=_topics,
        environment={"ROS_DISTRO": "humble", "PATH": "/definitely/missing"},
    )

    with pytest.raises(BagRecordingError, match="ROS 环境"):
        manager.verify_environment()

class _FakeProcess:
    pid = 4321

    def __init__(self):
        self.returncode = None
        self.wait_calls = []

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        self.returncode = 0
        return 0


class _FakeCounter:
    def __init__(self, counts=None, error=""):
        self.counts = counts or {"/odom": 100}
        self.error = error
        self.started = False
        self.reset_called = False
        self.stopped = False

    def start(self):
        self.started = True

    def reset(self):
        self.reset_called = True

    def snapshot(self):
        return self.counts, self.error

    def stop(self):
        self.stopped = True


def _recording_environment():
    from autodrive_console.bag_recording import RecordingEnvironment

    return RecordingEnvironment("humble", "/opt/ros/humble/bin/ros2", "/opt/ros/humble", "rmw_fastrtps_cpp", "0")


def _metadata(bag_dir):
    return {
        "storage_identifier": "sqlite3",
        "compression_mode": "file",
        "compression_format": "zstd",
        "topics": {"/odom": {"type": "nav_msgs/msg/Odometry", "message_count": 100}},
    }


def test_start_uses_only_fixed_rosbag_argv_and_resets_ready_counter(tmp_path):
    process = _FakeProcess()
    calls = []
    counter = _FakeCounter()
    manager = BagRecordingManager(
        tmp_path,
        topic_probe=lambda: [{"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 1}],
        environment_verifier=_recording_environment,
        popen=lambda argv, **kwargs: calls.append((argv, kwargs)) or process,
        counter_factory=lambda topic_types: counter,
        sleeper=lambda _seconds: None,
    )

    active = manager.start("run123", "夜间巡检", 2, RecordingRequest(2, ("/odom",)))

    argv, kwargs = calls[0]
    assert argv[:4] == ["/opt/ros/humble/bin/ros2", "bag", "record", "--output"]
    assert "--compression-mode" in argv and argv[argv.index("--compression-mode") + 1] == "file"
    assert "--compression-format" in argv and argv[argv.index("--compression-format") + 1] == "zstd"
    assert argv[-1] == "/odom"
    assert kwargs["shell"] is False
    assert kwargs["start_new_session"] is True
    assert kwargs["close_fds"] is True
    assert counter.started and counter.reset_called
    assert active.attempt_index == 2


def test_stop_writes_manifest_with_hashes_metadata_and_audit(tmp_path):
    process = _FakeProcess()
    counter = _FakeCounter()
    manager = BagRecordingManager(
        tmp_path,
        topic_probe=lambda: [{"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 1}],
        environment_verifier=_recording_environment,
        popen=lambda *_args, **_kwargs: process,
        counter_factory=lambda _topic_types: counter,
        metadata_reader=_metadata,
        sleeper=lambda _seconds: None,
    )
    active = manager.start("run123", "夜间巡检", 2, RecordingRequest(2, ("/odom",)))
    (active.bag_dir / "metadata.yaml").write_text("metadata", encoding="utf-8")
    (active.bag_dir / "data_0.db3.zstd").write_bytes(b"bag-data")

    summary = manager.stop(active)

    archive = manager.archive_detail(summary["archive_id"])
    assert summary["audit"]["status"] == "passed"
    assert archive["manifest"]["files"]["bag/data_0.db3.zstd"]["sha256"]
    assert archive["manifest"]["topics"]["/odom"]["recorded_count"] == 100
    assert counter.stopped


@pytest.mark.parametrize(("observed", "recorded", "expected"), [(100, 99, "passed"), (100, 97, "warning"), (100, 94, "failed")])
def test_audit_applies_approved_loss_thresholds(tmp_path, observed, recorded, expected):
    process = _FakeProcess()
    manager = BagRecordingManager(
        tmp_path,
        topic_probe=lambda: [{"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 1}],
        environment_verifier=_recording_environment,
        popen=lambda *_args, **_kwargs: process,
        counter_factory=lambda _topic_types: _FakeCounter({"/odom": observed}),
        metadata_reader=lambda _bag: {**_metadata(_bag), "topics": {"/odom": {"type": "nav_msgs/msg/Odometry", "message_count": recorded}}},
        sleeper=lambda _seconds: None,
    )
    active = manager.start("run123", "case", 1, RecordingRequest(1, ("/odom",)))
    (active.bag_dir / "metadata.yaml").write_text("metadata", encoding="utf-8")

    assert manager.stop(active)["audit"]["status"] == expected


def test_stop_marks_missing_metadata_or_counter_error_as_failed_and_preserves_archive(tmp_path):
    process = _FakeProcess()
    manager = BagRecordingManager(
        tmp_path,
        topic_probe=lambda: [{"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 1}],
        environment_verifier=_recording_environment,
        popen=lambda *_args, **_kwargs: process,
        counter_factory=lambda _topic_types: _FakeCounter(error="subscription disconnected"),
        metadata_reader=_metadata,
        sleeper=lambda _seconds: None,
    )
    active = manager.start("run123", "case", 1, RecordingRequest(1, ("/odom",)))

    summary = manager.stop(active)

    assert summary["audit"]["status"] == "failed"
    assert any("metadata" in item for item in summary["audit"]["errors"])
    assert manager.list_archives()[0]["audit_status"] == "failed"


def test_delete_rejects_active_or_path_escape_archive(tmp_path):
    manager = BagRecordingManager(tmp_path, topic_probe=_topics)

    with pytest.raises(BagRecordingError):
        manager.delete_archive("../../etc")


def test_constructor_preserves_crash_leftover_as_incomplete_archive(tmp_path):
    archive_id = "b" * 32
    stage = tmp_path / ".staging" / archive_id
    stage.mkdir(parents=True)
    (stage / "bag.db3").write_bytes(b"partial")

    manager = BagRecordingManager(tmp_path, topic_probe=_topics)

    archive = manager.archive_detail(archive_id)
    assert archive["archive"]["audit_status"] == "failed"
    assert "未完成" in archive["manifest"]["case_name"]
    assert not stage.exists()
