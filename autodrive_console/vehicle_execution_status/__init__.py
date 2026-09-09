"""Read-only vehicle execution-status collection and classification."""

from .classifier import classify_execution_state
from .model import ExecutionSnapshot, NavigationState, TaskEvent

__all__ = [
    "ExecutionSnapshot",
    "NavigationState",
    "TaskEvent",
    "classify_execution_state",
]
