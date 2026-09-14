"""Pure classification of known vehicle execution behaviour."""
from __future__ import annotations

from pathlib import PurePath

from .model import ExecutionSnapshot, NavigationState, TaskEvent, snapshot_for, unavailable_snapshot


ACTIVE_NAVIGATION_STATUSES = frozenset(
    {"navigating", "running", "executing", "task_executing", "task_retrying", "replanning"}
)
COMPLETED_NAVIGATION_STATUSES = frozenset({"completed", "successful"})
IDLE_NAVIGATION_STATUSES = frozenset({"", "idle"})
UNAVAILABLE_NAVIGATION_STATUSES = frozenset({"failed", "error"})
TERMINAL_EVENT_PHASES = {
    "109": "completed",
}
TASK_EVENT_PHASES = {
    "100": "task",
    "101": "task",
    "102": "task",
    "103": "task",
    "200": "calling_elevator",
    "201": "entering_elevator",
    "202": "riding_elevator",
    "203": "exiting_elevator",
    # 电梯到达后仍在跨层切图/出梯衔接，直到物理出梯路段覆盖该状态。
    "209": "riding_elevator",
    "301": "opening_gate",
    "302": "closing_gate",
    "303": "opening_access_door",
    "304": "closing_access_door",
    "500": "task",
    "600": "task",
    "601": "task",
    "700": "task",
    "701": "task",
}
UNAMBIGUOUS_EVENT_PHASES = {
    "400": "draining_or_unloading",
    "401": "draining_or_unloading",
    "402": "draining_or_unloading",
    "403": "draining_or_unloading",
}
APPROVED_ACTION_PREFIXES = (
    ("elevator_in_", "calling_elevator"),
    ("elevator_out_", "riding_elevator"),
    ("close_elevdoor_", "closing_elevator_door"),
    ("e_guard_open_", "opening_gate"),
    ("e_guard_close_", "closing_gate"),
    ("open_door_", "opening_access_door"),
    ("close_door_", "closing_access_door"),
    ("clamp_water", "draining_or_unloading"),
    ("place_water", "draining_or_unloading"),
)


def classify_execution_state(
    navigation: NavigationState,
    task_event: TaskEvent,
    *,
    restarting_nodes: bool,
) -> ExecutionSnapshot:
    """Classify live vehicle behaviour from route movement, event, and action context."""
    if restarting_nodes:
        return snapshot_for("restarting_nodes")

    navigation_status = navigation.status.strip().casefold()
    if navigation_status in COMPLETED_NAVIGATION_STATUSES:
        return snapshot_for("completed")
    if navigation_status in IDLE_NAVIGATION_STATUSES:
        return snapshot_for("idle")
    if navigation_status in UNAVAILABLE_NAVIGATION_STATUSES:
        return unavailable_snapshot()

    semantic_phase = phase_for_approved_behavior(navigation.current_task)
    movement_phase = phase_for_route_motion(navigation, semantic_phase)
    if movement_phase:
        return snapshot_for(movement_phase)

    event_phase = phase_for_task_event(task_event.status_code, semantic_phase)
    if event_phase:
        return snapshot_for(event_phase)
    if semantic_phase:
        return snapshot_for(semantic_phase)
    if navigation_status in ACTIVE_NAVIGATION_STATUSES:
        return snapshot_for("task")
    return unavailable_snapshot()


def phase_for_route_motion(navigation: NavigationState, semantic_phase: str | None) -> str | None:
    """Classify the physical route segment before the next waypoint action file."""
    speed_mode = navigation.current_speed_mode.strip().casefold()
    if speed_mode == "elevator_in":
        return "entering_elevator"
    if speed_mode == "backward" and semantic_phase == "closing_elevator_door":
        return "exiting_elevator"
    return None


def phase_for_task_event(status_code: str, semantic_phase: str | None) -> str | None:
    """Use the source-defined TaskStatus protocol before filename inference."""
    code = status_code.strip()
    terminal_phase = TERMINAL_EVENT_PHASES.get(code)
    if terminal_phase:
        return terminal_phase

    task_phase = TASK_EVENT_PHASES.get(code)
    if task_phase:
        return task_phase

    event_phase = UNAMBIGUOUS_EVENT_PHASES.get(code)
    if event_phase:
        return event_phase

    # Door_Waiting (300) has no direction; the approved behavior filename may
    # refine it below, otherwise the classifier returns the active generic task.
    return None


def phase_for_approved_behavior(current_task: str) -> str | None:
    """Derive a phase from a documented task filename shape, never fuzzy text."""
    filename = PurePath(str(current_task)).name.casefold()
    if not filename.endswith(".xml"):
        return None
    stem = filename.removesuffix(".xml")
    action = _approved_action_token(stem)
    if not action:
        return None
    for prefix, phase in APPROVED_ACTION_PREFIXES:
        if action.startswith(prefix):
            return phase
    return None


def _approved_action_token(stem: str) -> str | None:
    """Accept bare action names or the documented numeric_subtask_action pattern."""
    for prefix, _phase in APPROVED_ACTION_PREFIXES:
        if stem.startswith(prefix):
            return stem
    parts = stem.split("_", 2)
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    return parts[2]
