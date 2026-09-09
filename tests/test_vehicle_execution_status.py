from __future__ import annotations

from pathlib import Path

from autodrive_console.vehicle_execution_status.classifier import classify_execution_state
from autodrive_console.vehicle_execution_status.model import NavigationState, TaskEvent
from autodrive_console.vehicle_execution_status.monitor import VehicleExecutionStatusMonitor
from autodrive_console.run_manager import RunManager
import pytest


def test_classifier_prefers_exact_close_elevator_door_semantics_over_reused_code() -> None:
    """A reused 203 event must not turn a close-door action into elevator exit."""
    snapshot = classify_execution_state(
        NavigationState(status="running", current_task="1_1_close_elevdoor_x.xml"),
        TaskEvent(status_code="203"),
        restarting_nodes=False,
    )

    assert snapshot.phase == "closing_elevator_door"
    assert snapshot.label == "关电梯门"


def test_classifier_rejects_unknown_behavior_for_ambiguous_code() -> None:
    """Unapproved task names may not add robot-action semantics by accident."""
    snapshot = classify_execution_state(
        NavigationState(status="running", current_task="unreviewed_elevator_action.xml"),
        TaskEvent(status_code="203"),
        restarting_nodes=False,
    )

    assert snapshot.phase == "unavailable"
    assert snapshot.label == "状态暂不可用"


def test_classifier_uses_generic_task_only_for_known_active_navigation() -> None:
    """Active navigation without a confirmed stage remains safely generic."""
    snapshot = classify_execution_state(
        NavigationState(status="running"),
        TaskEvent(),
        restarting_nodes=False,
    )

    assert snapshot.phase == "task"
    assert snapshot.label == "任务中"


@pytest.mark.parametrize(
    ("task_name", "expected_phase"),
    [
        ("elevator_in_1.xml", "entering_elevator"),
        ("1_1_elevator_in_x.xml", "entering_elevator"),
        ("elevator_out_1.xml", "riding_elevator"),
        ("close_elevdoor_1.xml", "closing_elevator_door"),
        ("e_guard_open_1.xml", "opening_gate"),
        ("e_guard_close_1.xml", "closing_gate"),
        ("clamp_water.xml", "draining_or_unloading"),
        ("place_water.xml", "draining_or_unloading"),
    ],
)
def test_classifier_accepts_only_documented_behavior_action_tokens(task_name: str, expected_phase: str) -> None:
    snapshot = classify_execution_state(
        NavigationState(status="running", current_task=task_name),
        TaskEvent(),
        restarting_nodes=False,
    )

    assert snapshot.phase == expected_phase


def test_classifier_does_not_match_action_words_inside_an_unapproved_name() -> None:
    snapshot = classify_execution_state(
        NavigationState(status="running", current_task="not_elevator_in.xml"),
        TaskEvent(),
        restarting_nodes=False,
    )

    assert snapshot.phase == "task"


@pytest.mark.parametrize(
    ("status_code", "expected_phase"),
    [
        ("109", "completed"),
        ("200", "calling_elevator"),
        ("201", "entering_elevator"),
        ("202", "riding_elevator"),
        ("400", "draining_or_unloading"),
        ("401", "draining_or_unloading"),
        ("402", "draining_or_unloading"),
        ("403", "draining_or_unloading"),
    ],
)
def test_classifier_uses_only_unambiguous_task_status_codes(status_code: str, expected_phase: str) -> None:
    snapshot = classify_execution_state(
        NavigationState(status="running"),
        TaskEvent(status_code=status_code),
        restarting_nodes=False,
    )

    assert snapshot.phase == expected_phase


def test_classifier_prefers_a_completed_navigation_snapshot_over_old_action_detail() -> None:
    snapshot = classify_execution_state(
        NavigationState(status="completed", current_task="elevator_out_1.xml"),
        TaskEvent(status_code="202"),
        restarting_nodes=False,
    )

    assert snapshot.phase == "completed"


def test_classifier_surfaces_controlled_restart_before_ros_state() -> None:
    snapshot = classify_execution_state(
        NavigationState(status="running", current_task="elevator_in_1.xml"),
        TaskEvent(status_code="201"),
        restarting_nodes=True,
    )

    assert snapshot.phase == "restarting_nodes"


class FakeNavigation:
    def __init__(self, *, status: str, current_task: str = "", current_waypoint_id: str = "", current_speed_mode: str = "") -> None:
        self.status = status
        self.current_task = current_task
        self.current_waypoint_id = current_waypoint_id
        self.current_speed_mode = current_speed_mode


class FakeTask:
    def __init__(self, *, status_code: str) -> None:
        self.status_code = status_code


def test_monitor_returns_unavailable_when_navigation_has_expired() -> None:
    """A recent task event cannot keep a nonterminal robot state alive forever."""
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0, freshness_s=4.0)
    monitor.observe_navigation(FakeNavigation(status="running"), received_at=1.0)
    monitor.observe_task(FakeTask(status_code="200"), received_at=9.0)

    assert monitor.status() == {"phase": "unavailable", "label": "状态暂不可用"}


def test_monitor_uses_the_latest_ros_callbacks_without_restarting_subscription() -> None:
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 5.0, freshness_s=4.0)
    monitor.observe_navigation(FakeNavigation(status="running", current_task="elevator_in_1.xml"), received_at=4.0)
    monitor.observe_task(FakeTask(status_code="201"), received_at=5.0)

    assert monitor.status() == {"phase": "entering_elevator", "label": "进梯中"}


def test_monitor_allows_only_a_fresh_completed_event_without_navigation() -> None:
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0, freshness_s=4.0, task_event_freshness_s=15.0)
    monitor.observe_task(FakeTask(status_code="109"), received_at=9.0)

    assert monitor.status() == {"phase": "completed", "label": "任务完成"}


def test_monitor_reports_controlled_restart_without_ros_traffic() -> None:
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0, restarting_nodes=lambda: True)

    assert monitor.status() == {"phase": "restarting_nodes", "label": "节点重启中"}


def test_run_manager_keeps_restart_activity_true_until_nested_control_ends() -> None:
    """Overlapping dependency stages cannot briefly show a false idle state."""
    manager = RunManager(Path("unused"), object(), object())

    manager._set_dependency_restart_active(True)
    manager._set_dependency_restart_active(True)
    manager._set_dependency_restart_active(False)

    assert manager.dependency_restart_active() is True

    manager._set_dependency_restart_active(False)

    assert manager.dependency_restart_active() is False
