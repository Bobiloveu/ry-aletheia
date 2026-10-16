from __future__ import annotations

from pathlib import Path

import pytest

from autodrive_console.bag_recording import BagRecordingError, BagRecordingManager, RecordingRequest
from autodrive_console.models import AttemptResult, RunRecord, TaskParameters, TestCase
from autodrive_console.run_checkpoint import RunCheckpointStore


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


def test_topic_probe_merges_multiple_dds_graph_snapshots_before_filtering(tmp_path):
    snapshots = iter([
        [{"name": "/odom", "type": "nav_msgs/msg/Odometry", "types": ["nav_msgs/msg/Odometry"], "publisher_count": 0, "hidden": False}],
        [
            {"name": "/odom", "type": "nav_msgs/msg/Odometry", "types": ["nav_msgs/msg/Odometry"], "publisher_count": 1, "hidden": False},
            {"name": "/task_status", "type": "std_msgs/msg/Int32", "types": ["std_msgs/msg/Int32"], "publisher_count": 2, "hidden": False},
        ],
        [{"name": "/task_status", "type": "std_msgs/msg/Int32", "types": ["std_msgs/msg/Int32"], "publisher_count": 2, "hidden": False}],
    ])
    waits = []

    records = BagRecordingManager._collect_topic_snapshots(
        lambda: next(snapshots), samples=3, sleep=lambda seconds: waits.append(seconds), interval_s=0.2,
    )
    manager = BagRecordingManager(tmp_path, topic_probe=lambda: records)

    assert waits == [0.2, 0.2]
    assert manager.available_topics() == [
        {"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 1},
        {"name": "/task_status", "type": "std_msgs/msg/Int32", "publisher_count": 2},
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


def test_counter_executor_failure_is_retained_for_archive_audit():
    from autodrive_console.bag_recording import _RclpyTopicCounter

    counter = _RclpyTopicCounter({"/odom": "nav_msgs/msg/Odometry"})
    counter._counts["/odom"] = 42

    class BrokenExecutor:
        def spin(self):
            raise RuntimeError("simulated DDS counter failure")

    with pytest.raises(RuntimeError, match="simulated DDS counter failure"):
        counter._spin(BrokenExecutor())

    counts, error = counter.snapshot()
    assert counts == {"/odom": 42}
    assert error, "A dead audit counter must not silently look healthy"
    assert "simulated DDS counter failure" not in error


def _metadata(bag_dir):
    return {
        "storage_identifier": "sqlite3",
        "compression_mode": "file",
        "compression_format": "zstd",
        "topics": {"/odom": {"type": "nav_msgs/msg/Odometry", "message_count": 100}},
    }


def _rosbag_output(active):
    """Model rosbag2 creating its own output directory after process spawn."""
    active.bag_dir.mkdir()
    return active.bag_dir


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


def test_start_manual_uses_the_same_recorder_boundary_and_marks_manual_archive(tmp_path):
    from autodrive_console.manual_bag_recording import ManualRecordingRequest

    process = _FakeProcess()
    counter = _FakeCounter()
    manager = BagRecordingManager(
        tmp_path,
        topic_probe=lambda: [{"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 1}],
        environment_verifier=_recording_environment,
        popen=lambda *_args, **_kwargs: process,
        counter_factory=lambda _topic_types: counter,
        sleeper=lambda _seconds: None,
    )

    active = manager.start_manual(ManualRecordingRequest(("/odom",), 15, "窄通道避障"))

    assert active.source == "manual"
    assert active.label == "窄通道避障"
    assert active.duration_limit_seconds == 900
    assert active.attempt_index is None


def test_manual_archive_keeps_its_scene_label_limit_and_actual_duration(tmp_path):
    from autodrive_console.manual_bag_recording import ManualRecordingRequest

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
    active = manager.start_manual(ManualRecordingRequest(("/odom",), 15, "窄通道避障"))
    (_rosbag_output(active) / "metadata.yaml").write_text("metadata", encoding="utf-8")
    (active.bag_dir / "data_0.db3.zstd").write_bytes(b"bag-data")

    summary = manager.stop(active)
    manifest = manager.archive_detail(summary["archive_id"])["manifest"]

    assert manifest["source"] == "manual"
    assert manifest["label"] == "窄通道避障"
    assert manifest["duration_limit_seconds"] == 900
    assert isinstance(manifest["actual_duration_seconds"], int)
    assert manifest["actual_duration_seconds"] >= 0
    assert summary["display_name"] == "窄通道避障"
    assert manager.archive_path(active.archive_id).name == f"bag_{active.archive_id}"


@pytest.mark.parametrize("source,label,case,attempt,expected", [
    ("manual", "窄通道避障", "窄通道避障", None, "窄通道避障"),
    ("manual", "", "手动场景", None, "手动录制"),
    ("test_attempt", "", "夜间巡检", 2, "夜间巡检 · 第 2 轮"),
    ("test_attempt", "", "未完成录制", None, "未完成录制"),
])
def test_legacy_archive_titles_are_readable_without_rewriting_files(tmp_path, source, label, case, attempt, expected):
    import json

    archive_id = "a" * 32
    directory = tmp_path / f"bag_20261015_092825_manual_QA_{archive_id}"
    directory.mkdir()
    original = json.dumps({"archive_id": archive_id, "display_name": directory.name,
        "source": source, "label": label, "case_name": case, "attempt_index": attempt,
        "started_at": "2026-10-15T09:28:25+08:00"}, ensure_ascii=False)
    (directory / "manifest.json").write_text(original)
    manager = BagRecordingManager(tmp_path, topic_probe=_topics)

    assert manager.list_archives()[0]["display_name"] == expected
    assert manager.archive_detail(archive_id)["archive"]["display_name"] == expected
    assert manager.archive_path(archive_id) == directory
    assert manager.archive_download_name(archive_id) == "bag_20261015_092825_aaaaaaaa.tar"
    assert (directory / "manifest.json").read_text() == original


@pytest.mark.parametrize("started_at", [None, "bad\r\nInjected: header"])
def test_bag_download_name_has_safe_fallback_for_missing_or_invalid_time(tmp_path, started_at):
    import json

    archive_id = "a" * 32
    directory = tmp_path / "legacy"
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps({"archive_id": archive_id, "started_at": started_at}))
    manager = BagRecordingManager(tmp_path, topic_probe=_topics)
    assert manager.archive_download_name(archive_id) == "bag_undated_aaaaaaaa.tar"


def test_manual_and_test_attempt_recorders_cannot_overlap_at_the_process_boundary(tmp_path):
    from autodrive_console.manual_bag_recording import ManualRecordingRequest

    manager = BagRecordingManager(
        tmp_path,
        topic_probe=lambda: [{"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 1}],
        environment_verifier=_recording_environment,
        popen=lambda *_args, **_kwargs: _FakeProcess(),
        counter_factory=lambda _topic_types: _FakeCounter(),
        sleeper=lambda _seconds: None,
    )
    manager.start_manual(ManualRecordingRequest(("/odom",), 15, "遥控复现"))

    with pytest.raises(BagRecordingError, match="录包"):
        manager.start("run123", "case", 1, RecordingRequest(1, ("/odom",)))


def test_same_scene_archives_keep_separate_data_and_ids(tmp_path):
    from autodrive_console.manual_bag_recording import ManualRecordingRequest

    manager = BagRecordingManager(tmp_path, topic_probe=_topics,
        environment_verifier=_recording_environment, popen=lambda *_args, **_kwargs: _FakeProcess(),
        counter_factory=lambda _types: _FakeCounter(), metadata_reader=_metadata, sleeper=lambda _seconds: None)
    ids = []
    for _ in range(2):
        active = manager.start_manual(ManualRecordingRequest(("/odom",), 5, "../窄通道"))
        _rosbag_output(active)
        summary = manager.stop(active)
        assert summary["display_name"] == "../窄通道"
        assert manager.archive_path(active.archive_id).parent == tmp_path
        ids.append(active.archive_id)
    assert ids[0] != ids[1]
    assert len(manager.list_archives()) == 2
    manager.delete_archive(ids[0])
    assert manager.archive_path(ids[1]).is_dir()


def test_start_failure_after_spawn_stops_the_owned_recorder_before_cleanup(tmp_path):
    from unittest.mock import Mock

    class BrokenCounter(_FakeCounter):
        def reset(self):
            raise RuntimeError("counter reset failed")

    process = _FakeProcess()
    counter = BrokenCounter()
    manager = BagRecordingManager(tmp_path, topic_probe=_topics,
        environment_verifier=_recording_environment, popen=lambda *_args, **_kwargs: process,
        counter_factory=lambda _types: counter, sleeper=lambda _seconds: None)
    manager._stop_process = Mock(return_value=0)
    with pytest.raises(BagRecordingError, match="counter reset failed"):
        manager.start("run", "case", 1, RecordingRequest(1, ("/odom",)))
    manager._stop_process.assert_called_once_with(process)
    assert counter.stopped
    assert not manager._active
    assert not manager._starting
    assert not list((tmp_path / ".staging").iterdir())


def test_failed_startup_process_cleanup_preserves_data_and_blocks_another_recorder(tmp_path):
    from unittest.mock import Mock

    class BrokenCounter(_FakeCounter):
        def reset(self):
            raise RuntimeError("counter reset failed")

    popen = Mock(return_value=_FakeProcess())
    manager = BagRecordingManager(tmp_path, topic_probe=_topics,
        environment_verifier=_recording_environment, popen=popen,
        counter_factory=lambda _types: BrokenCounter(), sleeper=lambda _seconds: None)
    manager._stop_process = Mock(side_effect=OSError("stop failed"))
    with pytest.raises(BagRecordingError, match="进程清理未完成"):
        manager.start("run", "case", 1, RecordingRequest(1, ("/odom",)))
    assert len(list((tmp_path / ".staging").iterdir())) == 1
    with pytest.raises(BagRecordingError, match="已有诊断录包"):
        manager.start("run", "case", 1, RecordingRequest(1, ("/odom",)))
    assert popen.call_count == 1


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
    (_rosbag_output(active) / "metadata.yaml").write_text("metadata", encoding="utf-8")
    (active.bag_dir / "data_0.db3.zstd").write_bytes(b"bag-data")

    summary = manager.stop(active)

    archive = manager.archive_detail(summary["archive_id"])
    assert summary["audit"]["status"] == "passed"
    assert archive["manifest"]["files"]["bag/data_0.db3.zstd"]["sha256"]
    assert archive["manifest"]["topics"]["/odom"]["recorded_count"] == 100
    assert counter.stopped


@pytest.mark.parametrize("compression_mode", ["FILE", "CompressionMode.FILE"])
def test_audit_accepts_rosbag2_file_compression_mode_variants(tmp_path, compression_mode):
    """ROS 2 Humble writes FILE in metadata.yaml for file-level Zstd bags."""
    process = _FakeProcess()
    manager = BagRecordingManager(
        tmp_path,
        topic_probe=lambda: [{"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 1}],
        environment_verifier=_recording_environment,
        popen=lambda *_args, **_kwargs: process,
        counter_factory=lambda _topic_types: _FakeCounter(),
        metadata_reader=lambda bag_dir: {**_metadata(bag_dir), "compression_mode": compression_mode},
        sleeper=lambda _seconds: None,
    )
    active = manager.start("run123", "case", 1, RecordingRequest(1, ("/odom",)))
    (_rosbag_output(active) / "metadata.yaml").write_text("metadata", encoding="utf-8")

    audit = manager.stop(active)["audit"]

    assert audit["status"] == "passed"
    assert "rosbag 压缩 profile 不符合固定 Zstd file 策略" not in audit["errors"]


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
    (_rosbag_output(active) / "metadata.yaml").write_text("metadata", encoding="utf-8")

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


def test_checkpoint_recovers_a_completed_bag_recording_audit(tmp_path):
    case = TestCase("case", "case.json", "诊断测试", TaskParameters("园区", 1, 1, 1, 101), "unused.json")
    run = RunRecord(
        "123456789abc",
        case,
        2,
        0,
        status="running",
        attempts=[AttemptResult(
            1,
            "passed",
            "已完成",
            1.0,
            "2026-10-09T18:00:01+08:00",
            bag_recording={"archive_id": "a" * 32, "audit": {"status": "passed", "topics": {"/odom": {"loss_percent": 0.0}}}},
        )],
    )
    store = RunCheckpointStore(tmp_path)

    store.save(run, attempt_in_progress=False)

    [recovered] = store.load_recoverable()
    assert recovered.run.attempts[0].bag_recording == run.attempts[0].bag_recording


def test_recorder_receives_a_new_output_path_that_rosbag_can_create(tmp_path):
    """ros2 bag record owns creation of its --output directory."""
    process = _FakeProcess()
    output_existed_when_spawned = []
    manager = BagRecordingManager(
        tmp_path,
        topic_probe=lambda: [{"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 1}],
        environment_verifier=_recording_environment,
        popen=lambda argv, **_kwargs: output_existed_when_spawned.append(Path(argv[4]).exists()) or process,
        counter_factory=lambda _topic_types: _FakeCounter(),
        sleeper=lambda _seconds: None,
    )

    manager.start("run123", "case", 1, RecordingRequest(1, ("/odom",)))

    assert output_existed_when_spawned == [False]
