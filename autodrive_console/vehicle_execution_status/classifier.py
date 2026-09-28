"""Pure classification of known vehicle execution behaviour."""
from __future__ import annotations

from pathlib import PurePath

from ..task_status_codes import TaskStatusCodeError, task_status_code, task_status_phase_by_code
from .model import ExecutionSnapshot, NavigationState, TaskEvent, snapshot_for, unavailable_snapshot


ACTIVE_NAVIGATION_STATUSES = frozenset(
    {"navigating", "running", "executing", "task_executing", "task_retrying", "replanning"}
)
COMPLETED_NAVIGATION_STATUSES = frozenset({"completed", "successful"})
IDLE_NAVIGATION_STATUSES = frozenset({"", "idle"})
UNAVAILABLE_NAVIGATION_STATUSES = frozenset({"failed", "error"})
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
    try:
        code = status_code.strip()
        # The registry deliberately gives this directionless wait event the
        # generic `task` phase.  The approved action filename is the existing
        # source for its open/close direction and must remain able to refine it.
        if code == task_status_code("door_waiting"):
            return None
        return task_status_phase_by_code().get(code)
    except TaskStatusCodeError:
        # Filename semantics and a generic active-navigation state remain safe
        # when a local profile registry cannot be read.
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
