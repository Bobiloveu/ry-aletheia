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
    ]


def test_available_topics_only_exposes_active_single_type_nonhidden_topics(tmp_path):
    manager = BagRecordingManager(tmp_path, topic_probe=_topics)

    assert manager.available_topics() == [
        {"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 2},
        {"name": "/scan", "type": "sensor_msgs/msg/LaserScan", "publisher_count": 1},
    ]


def test_validate_request_requires_unique_visible_topics_and_target_round(tmp_path):
    manager = BagRecordingManager(tmp_path, topic_probe=_topics)

    request = manager.validate_request({"attemptIndex": 2, "topics": ["/scan", "/odom"]}, 3)

    assert request == RecordingRequest(2, ("/scan", "/odom"))
    with pytest.raises(BagRecordingError, match="重复"):
        manager.validate_request({"attemptIndex": 2, "topics": ["/scan", "/scan"]}, 3)
    with pytest.raises(BagRecordingError, match="轮次"):
        manager.validate_request({"attemptIndex": 4, "topics": ["/scan"]}, 3)
    with pytest.raises(BagRecordingError, match="当前不可录制"):
        manager.validate_request({"attemptIndex": 2, "topics": ["/hidden"]}, 3)


def test_validate_request_accepts_null_and_rejects_unknown_payload_shape(tmp_path):
    manager = BagRecordingManager(tmp_path, topic_probe=_topics)

    assert manager.validate_request(None, 1) is None
    with pytest.raises(BagRecordingError, match="字段"):
        manager.validate_request({"attemptIndex": 1, "topics": ["/scan"], "command": "bad"}, 1)


def test_environment_profile_rejects_missing_ros_prefix_and_never_uses_shell(tmp_path):
    manager = BagRecordingManager(
        tmp_path,
        topic_probe=_topics,
        environment={"ROS_DISTRO": "humble", "PATH": "/definitely/missing"},
    )

    with pytest.raises(BagRecordingError, match="ROS 环境"):
        manager.verify_environment()
