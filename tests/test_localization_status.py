from __future__ import annotations

from dataclasses import dataclass

from autodrive_console.localization_status import LocalizationStatusMonitor
from autodrive_console.trajectory import TrajectorySession


@dataclass
class FakeLocalizationStatus:
    state: int
    error_code: int = 0
    fault_id: int = 0


def test_resetting_is_counted_once_for_each_fault_id():
    """A repeated RESETTING publish must not inflate one recovery incident."""
    monitor = LocalizationStatusMonitor(clock=lambda: 10.0)

    monitor.observe(FakeLocalizationStatus(state=4, error_code=100, fault_id=42))
    monitor.observe(FakeLocalizationStatus(state=4, error_code=100, fault_id=42))

    cursor, events = monitor.events_since(0)
    assert cursor == 1
    assert events == [
        {
            "sequence": 1,
            "fault_id": 42,
            "received_at": 10.0,
            "state": "relocalizing",
        }
    ]


def test_seen_fault_id_remains_deduplicated_after_event_history_rollover():
    """A bounded report buffer must not make an old recovery count again."""
    monitor = LocalizationStatusMonitor(clock=lambda: 11.0, max_events=2)

    for fault_id in (1, 2, 3, 1):
        monitor.observe(FakeLocalizationStatus(state=4, fault_id=fault_id))

    assert monitor.cursor() == 3
    assert [event["fault_id"] for event in monitor.events_since(0)[1]] == [2, 3]


def test_public_snapshot_uses_readable_status_without_internal_identifiers():
    """The UI boundary must expose a readable cause, not ROS numeric internals."""
    monitor = LocalizationStatusMonitor(clock=lambda: 12.5)

    monitor.observe(FakeLocalizationStatus(state=3, error_code=301, fault_id=99))

    assert monitor.status() == {
        "phase": "error",
        "label": "定位异常",
        "detail": "雷达数据断流",
        "updated_at": 12.5,
    }


def test_non_normal_zero_error_keeps_the_state_specific_explanation():
    """A warning with no concrete error must not misleadingly say no error."""
    monitor = LocalizationStatusMonitor(clock=lambda: 13.0)

    monitor.observe(FakeLocalizationStatus(state=2, error_code=0))

    assert monitor.status()["detail"] == "定位质量需关注"


def test_stale_status_is_not_presented_as_normal():
    """A stopped localization publisher must safely become unavailable."""
    now = [0.0]
    monitor = LocalizationStatusMonitor(clock=lambda: now[0], freshness_s=4.0)
    monitor.observe(FakeLocalizationStatus(state=1))
    now[0] = 4.1

    assert monitor.status() == {
        "phase": "unavailable",
        "label": "定位状态暂不可用",
        "detail": "等待新的定位状态",
        "updated_at": 0.0,
    }


def test_status_identifies_missing_vehicle_interface_without_leaking_paths():
    """A vehicle lacking the optional status type needs an actionable public state."""
    monitor = LocalizationStatusMonitor(clock=lambda: 1.0)
    monitor._runtime_state = "unavailable"
    monitor._runtime_error = (
        "cannot import LocalizationStatus from /tmp/_MEI/master_interfaces/msg"
    )

    snapshot = monitor.status()

    assert snapshot["phase"] == "unavailable"
    assert snapshot["detail"] == "该车不支持实时定位状态"
    assert "/tmp" not in snapshot["detail"]


def test_trajectory_attaches_reset_event_to_the_next_verified_map_sample():
    """A report marker must use a verified map point rather than guessed pose data."""
    monitor = LocalizationStatusMonitor(clock=lambda: 20.0)
    session = TrajectorySession([], localization_monitor=monitor)
    monitor.observe(FakeLocalizationStatus(state=4, fault_id=7))

    session._record_relocalizations_for_sample(
        {"timestamp_ns": 20_000_000_000, "x": 1.25, "y": -0.5, "map_id": "map-a"}
    )

    assert session._relocalizations == [
        {
            "sequence": 1,
            "fault_id": 7,
            "received_at": 20.0,
            "state": "relocalizing",
            "timestamp_ns": 20_000_000_000,
            "x": 1.25,
            "y": -0.5,
            "map_id": "map-a",
            "position_available": True,
        }
    ]


def test_trajectory_retains_an_unlocated_reset_for_the_round_count():
    """Missing map coordinates suppress only the marker, never the incident count."""
    monitor = LocalizationStatusMonitor(clock=lambda: 30.0)
    session = TrajectorySession([], localization_monitor=monitor)
    monitor.observe(FakeLocalizationStatus(state=4, fault_id=8))

    session._record_relocalizations_for_sample(None)

    assert session._relocalizations == [
        {
            "sequence": 1,
            "fault_id": 8,
            "received_at": 30.0,
            "state": "relocalizing",
            "position_available": False,
        }
    ]
    assert session.stop()["relocalization_count"] == 1


def test_stopping_a_round_uses_its_last_verified_sample_for_a_late_reset():
    """A reset just before task completion still receives a truthful map marker."""
    monitor = LocalizationStatusMonitor(clock=lambda: 40.0)
    session = TrajectorySession([], localization_monitor=monitor)
    session._last_verified_map_sample = {
        "timestamp_ns": 39_900_000_000,
        "x": 2.5,
        "y": 1.0,
        "map_id": "map-b",
    }
    monitor.observe(FakeLocalizationStatus(state=4, fault_id=9))

    trajectory = session.stop()

    assert trajectory["relocalizations"][0]["position_available"] is True
    assert trajectory["relocalizations"][0]["map_id"] == "map-b"
