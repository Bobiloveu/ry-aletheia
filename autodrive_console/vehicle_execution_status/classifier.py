"""Pure classification of known vehicle execution behaviour."""
from __future__ import annotations

from pathlib import PurePath

from .model import ExecutionSnapshot, NavigationState, TaskEvent, snapshot_for, unavailable_snapshot


ACTIVE_NAVIGATION_STATUSES = frozenset({"running", "executing", "task_executing", "task_retrying"})
COMPLETED_NAVIGATION_STATUSES = frozenset({"completed", "successful"})
UNAVAILABLE_NAVIGATION_STATUSES = frozenset({"", "idle", "failed", "error"})
UNAMBIGUOUS_EVENT_PHASES = {
    "109": "completed",
    "200": "calling_elevator",
    "201": "entering_elevator",
    "202": "riding_elevator",
    "400": "draining_or_unloading",
    "401": "draining_or_unloading",
    "402": "draining_or_unloading",
    "403": "draining_or_unloading",
}
AMBIGUOUS_EVENT_CODES = frozenset({"203", "209", "300", "301", "302", "303", "304"})
APPROVED_ACTION_PREFIXES = (
    ("elevator_in_", "entering_elevator"),
    ("elevator_out_", "riding_elevator"),
    ("close_elevdoor_", "closing_elevator_door"),
    ("e_guard_open_", "opening_gate"),
    ("e_guard_close_", "closing_gate"),
    ("clamp_water", "draining_or_unloading"),
    ("place_water", "draining_or_unloading"),
)


def classify_execution_state(
    navigation: NavigationState,
    task_event: TaskEvent,
    *,
    restarting_nodes: bool,
) -> ExecutionSnapshot:
    """Classify only confirmed state; ambiguous robot actions deliberately hide."""
    if restarting_nodes:
        return snapshot_for("restarting_nodes")

    navigation_status = navigation.status.strip().casefold()
    if navigation_status in COMPLETED_NAVIGATION_STATUSES:
        return snapshot_for("completed")
    if navigation_status in UNAVAILABLE_NAVIGATION_STATUSES:
        return unavailable_snapshot()

    semantic_phase = phase_for_approved_behavior(navigation.current_task)
    if semantic_phase:
        return snapshot_for(semantic_phase)

    event_phase = UNAMBIGUOUS_EVENT_PHASES.get(task_event.status_code.strip())
    if event_phase:
        return snapshot_for(event_phase)
    if task_event.status_code.strip() in AMBIGUOUS_EVENT_CODES:
        return unavailable_snapshot()
    if navigation_status in ACTIVE_NAVIGATION_STATUSES:
        return snapshot_for("task")
    return unavailable_snapshot()


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
