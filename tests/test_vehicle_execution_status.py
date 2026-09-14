from __future__ import annotations

from pathlib import Path

from autodrive_console.vehicle_execution_status.classifier import classify_execution_state
from autodrive_console.vehicle_execution_status.model import NavigationState, TaskEvent
from autodrive_console.vehicle_execution_status.monitor import VehicleExecutionStatusMonitor
from autodrive_console.run_manager import RunManager
import pytest


def test_classifier_uses_official_elevator_out_code_over_close_door_filename() -> None:
    """TaskStatus 203 is the source-defined elevator exit state."""
    snapshot = classify_execution_state(
        NavigationState(status="running", current_task="1_1_close_elevdoor_x.xml"),
        TaskEvent(status_code="203"),
        restarting_nodes=False,
    )

    assert snapshot.phase == "exiting_elevator"
    assert snapshot.label == "出梯中"


def test_classifier_uses_official_elevator_out_code_without_filename_context() -> None:
    snapshot = classify_execution_state(
        NavigationState(status="running", current_task="unreviewed_elevator_action.xml"),
        TaskEvent(status_code="203"),
        restarting_nodes=False,
    )

    assert snapshot.phase == "exiting_elevator"
    assert snapshot.label == "出梯中"


def test_classifier_uses_generic_task_only_for_known_active_navigation() -> None:
    """Active navigation without a confirmed stage remains safely generic."""
    snapshot = classify_execution_state(
        NavigationState(status="running"),
        TaskEvent(),
        restarting_nodes=False,
    )

    assert snapshot.phase == "task"
    assert snapshot.label == "任务中"


@pytest.mark.parametrize("status", ["", "idle"])
def test_classifier_represents_a_nonexecuting_vehicle_as_idle(status: str) -> None:
    snapshot = classify_execution_state(
        NavigationState(status=status),
        TaskEvent(),
        restarting_nodes=False,
    )

    assert snapshot.phase == "idle"
    assert snapshot.label == "空闲中"


def test_classifier_recognizes_navigating_as_an_active_navigation_state() -> None:
    snapshot = classify_execution_state(
        NavigationState(status="navigating"),
        TaskEvent(),
        restarting_nodes=False,
    )

    assert snapshot.phase == "task"


def test_classifier_prioritizes_entering_speed_mode_over_next_elevator_behavior() -> None:
    """The route segment into the car is not yet elevator travel."""
    snapshot = classify_execution_state(
        NavigationState(
            status="navigating",
            current_speed_mode="elevator_in",
            current_task="1_1_elevator_out_n_x.xml",
        ),
        TaskEvent(status_code="202"),
        restarting_nodes=False,
    )

    assert snapshot.phase == "entering_elevator"


def test_classifier_uses_backward_exit_segment_before_the_following_door_action() -> None:
    snapshot = classify_execution_state(
        NavigationState(
            status="navigating",
            current_speed_mode="backward",
            current_task="1_1_close_elevdoor_x.xml",
        ),
        TaskEvent(status_code="203"),
        restarting_nodes=False,
    )

    assert snapshot.phase == "exiting_elevator"


def test_classifier_treats_elevator_call_behavior_as_calling_until_entry_is_confirmed() -> None:
    snapshot = classify_execution_state(
        NavigationState(status="task_executing", current_task="1_1_elevator_in_n_x.xml"),
        TaskEvent(status_code="209"),
        restarting_nodes=False,
    )

    assert snapshot.phase == "riding_elevator"


def test_classifier_uses_official_elevator_entry_code_without_filename_context() -> None:
    snapshot = classify_execution_state(
        NavigationState(status="task_executing", current_task="unreviewed_action.xml"),
        TaskEvent(status_code="201"),
        restarting_nodes=False,
    )

    assert snapshot.phase == "entering_elevator"


@pytest.mark.parametrize(
    ("task_name", "expected_phase"),
    [
        ("elevator_in_1.xml", "calling_elevator"),
        ("1_1_elevator_in_x.xml", "calling_elevator"),
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


@pytest.mark.parametrize(
    ("task_name", "expected_phase"),
    [
        ("open_door_go.xml", "opening_access_door"),
        ("5_2_close_door_back.xml", "closing_access_door"),
    ],
)
def test_classifier_accepts_documented_access_door_action_tokens(task_name: str, expected_phase: str) -> None:
    snapshot = classify_execution_state(
        NavigationState(status="task_executing", current_task=task_name),
        TaskEvent(status_code="300"),
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
        ("100", "task"),
        ("101", "task"),
        ("102", "task"),
        ("103", "task"),
        ("109", "completed"),
        ("200", "calling_elevator"),
        ("201", "entering_elevator"),
        ("202", "riding_elevator"),
        ("203", "exiting_elevator"),
        ("209", "riding_elevator"),
        ("600", "task"),
        ("601", "task"),
        ("700", "task"),
        ("701", "task"),
        ("400", "draining_or_unloading"),
        ("401", "draining_or_unloading"),
        ("402", "draining_or_unloading"),
        ("403", "draining_or_unloading"),
        ("500", "task"),
    ],
)
def test_classifier_uses_only_unambiguous_task_status_codes(status_code: str, expected_phase: str) -> None:
    snapshot = classify_execution_state(
        NavigationState(status="running"),
        TaskEvent(status_code=status_code),
        restarting_nodes=False,
    )

    assert snapshot.phase == expected_phase


@pytest.mark.parametrize(
    ("status_code", "expected_phase"),
    [
        ("301", "opening_gate"),
        ("302", "closing_gate"),
        ("303", "opening_access_door"),
        ("304", "closing_access_door"),
    ],
)
def test_classifier_uses_official_door_passage_codes(status_code: str, expected_phase: str) -> None:
    snapshot = classify_execution_state(
        NavigationState(status="task_executing"),
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
    def __init__(self, *, status_code: str, task_uuid: str = "", message: str = "") -> None:
        self.status_code = status_code
        self.task_uuid = task_uuid
        self.message = message


class FakeNavigationHeartbeat:
    def __init__(self, *, data: str) -> None:
        self.data = data


def test_monitor_uses_fresh_navigation_heartbeat_when_detailed_snapshot_is_old() -> None:
    """Detailed status is transition data, while the simple topic proves liveness."""
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0, freshness_s=4.0)
    monitor.observe_navigation(
        FakeNavigation(status="task_executing", current_task="1_1_elevator_in_n_x.xml"),
        received_at=1.0,
    )
    monitor.observe_task(FakeTask(status_code="200"), received_at=9.0)
    monitor.observe_navigation_heartbeat(FakeNavigationHeartbeat(data="执行任务点任务"), received_at=9.0)

    assert monitor.status() == {"phase": "calling_elevator", "label": "呼梯中"}


def test_monitor_retains_a_single_task_event_when_navigation_moves_to_a_new_behavior() -> None:
    """A route transition is not a new TaskStatus event and must not erase it."""
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0, freshness_s=4.0)
    monitor.observe_navigation(
        FakeNavigation(status="task_executing", current_task="1_1_elevator_out_n_x.xml"),
        received_at=8.0,
    )
    monitor.observe_task(FakeTask(status_code="202", task_uuid="task-a"), received_at=9.0)
    monitor.observe_navigation(
        FakeNavigation(status="task_executing", current_task="unreviewed_action.xml"),
        received_at=10.0,
    )

    assert monitor.status() == {"phase": "riding_elevator", "label": "乘梯中"}


def test_monitor_latches_a_single_task_event_beyond_its_old_freshness_window() -> None:
    """TaskStatus is edge-triggered; a live route heartbeat keeps its phase current."""
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 20.0, freshness_s=4.0, task_event_freshness_s=15.0)
    monitor.observe_navigation(FakeNavigation(status="task_executing", current_task="unreviewed_action.xml"), received_at=1.0)
    monitor.observe_task(FakeTask(status_code="202", task_uuid="task-a"), received_at=1.0)
    monitor.observe_navigation_heartbeat(FakeNavigationHeartbeat(data="执行任务点任务"), received_at=19.0)

    assert monitor.status() == {"phase": "riding_elevator", "label": "乘梯中"}


def test_monitor_retains_task_status_protocol_metadata_internally() -> None:
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0)
    monitor.observe_task(
        FakeTask(status_code="200", task_uuid="a1b2", message="Waiting for elevator"),
        received_at=9.0,
    )

    assert monitor._task_event == TaskEvent(
        status_code="200",
        task_uuid="a1b2",
        message="Waiting for elevator",
    )


def test_monitor_returns_unavailable_when_navigation_heartbeat_has_expired() -> None:
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0, freshness_s=4.0)
    monitor.observe_navigation(FakeNavigation(status="task_executing"), received_at=1.0)
    monitor.observe_navigation_heartbeat(FakeNavigationHeartbeat(data="执行任务点任务"), received_at=1.0)

    assert monitor.status() == {"phase": "unavailable", "label": "状态暂不可用"}


def test_monitor_reports_idle_before_the_first_navigation_message() -> None:
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0)

    assert monitor.status() == {"phase": "idle", "label": "空闲中"}


def test_monitor_uses_the_latest_ros_callbacks_without_restarting_subscription() -> None:
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 5.0, freshness_s=4.0)
    monitor.observe_navigation(FakeNavigation(status="running", current_task="elevator_in_1.xml"), received_at=4.0)
    monitor.observe_task(FakeTask(status_code="201"), received_at=5.0)

    assert monitor.status() == {"phase": "entering_elevator", "label": "进梯中"}


def test_monitor_ignores_a_completed_event_without_an_observed_task_session() -> None:
    """控制台刚启动时的孤立 109 不能把空闲车辆误报为任务完成。"""
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0, freshness_s=4.0, task_event_freshness_s=15.0)
    monitor.observe_task(FakeTask(status_code="109", task_uuid="old-task"), received_at=9.0)

    assert monitor.status() == {"phase": "idle", "label": "空闲中"}


def test_monitor_reports_completed_after_the_same_task_session_was_observed() -> None:
    """同一任务 UUID 先活动再完成时，仍应保留短暂的完成提示。"""
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0, freshness_s=4.0, task_event_freshness_s=15.0)
    monitor.observe_task(FakeTask(status_code="100", task_uuid="task-a"), received_at=8.0)
    monitor.observe_task(FakeTask(status_code="109", task_uuid="task-a"), received_at=9.0)

    assert monitor.status() == {"phase": "completed", "label": "任务完成"}


def test_monitor_reports_controlled_restart_without_ros_traffic() -> None:
    monitor = VehicleExecutionStatusMonitor(clock=lambda: 10.0, restarting_nodes=lambda: True)

    assert monitor.status() == {"phase": "restarting_nodes", "label": "节点重启中"}


def test_monitor_prioritizes_a_confirmed_chassis_emergency_over_every_execution_phase() -> None:
    """A latched chassis emergency must replace both manual and task presentation."""
    monitor = VehicleExecutionStatusMonitor(
        clock=lambda: 10.0,
        vehicle_control_status=lambda: {
            "actual_source": "miniapp",
            "car_state_sync": {"control_source": "confirmed"},
            "emergency_stop": {"state": "triggered"},
        },
    )
    monitor.observe_navigation(FakeNavigation(status="running", current_task="elevator_in_1.xml"), received_at=9.0)

    assert monitor.status() == {"phase": "emergency_stop", "label": "急停已触发"}


def test_monitor_reports_confirmed_miniapp_control_before_task_progress() -> None:
    """The real miniapp source, not a browser session, defines manual control display."""
    monitor = VehicleExecutionStatusMonitor(
        clock=lambda: 10.0,
        vehicle_control_status=lambda: {
            "actual_source": "miniapp",
            "car_state_sync": {"control_source": "confirmed"},
            "emergency_stop": {"state": "normal"},
        },
    )
    monitor.observe_navigation(FakeNavigation(status="running", current_task="elevator_in_1.xml"), received_at=9.0)

    assert monitor.status() == {"phase": "manual_control", "label": "手动控制中"}


def test_monitor_does_not_infer_manual_control_until_the_vehicle_source_is_confirmed() -> None:
    """A pending source transition must keep the known robot task phase, never claim manual control."""
    monitor = VehicleExecutionStatusMonitor(
        clock=lambda: 10.0,
        vehicle_control_status=lambda: {
            "actual_source": "miniapp",
            "car_state_sync": {"control_source": "pending"},
            "emergency_stop": {"state": "normal"},
        },
    )
    monitor.observe_navigation(FakeNavigation(status="running", current_task="elevator_in_1.xml"), received_at=9.0)

    assert monitor.status() == {"phase": "calling_elevator", "label": "呼梯中"}


def test_run_manager_keeps_restart_activity_true_until_nested_control_ends() -> None:
    """Overlapping dependency stages cannot briefly show a false idle state."""
    manager = RunManager(Path("unused"), object(), object())

    manager._set_dependency_restart_active(True)
    manager._set_dependency_restart_active(True)
    manager._set_dependency_restart_active(False)

    assert manager.dependency_restart_active() is True

    manager._set_dependency_restart_active(False)

    assert manager.dependency_restart_active() is False
