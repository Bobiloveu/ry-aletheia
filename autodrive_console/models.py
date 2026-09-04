from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class TaskParameters:
    community: str
    building: int
    unit: int
    floor: int
    door: int


@dataclass(frozen=True)
class TestCase:
    id: str
    filename: str
    name: str
    parameters: TaskParameters
    source: str


@dataclass
class AttemptResult:
    index: int
    status: str
    message: str
    duration_s: float
    started_at: str
    trajectory: dict[str, Any] | None = None
    case_id: str | None = None
    case_filename: str | None = None


@dataclass
class RunRecord:
    id: str
    case: TestCase
    requested_count: int
    interval_s: float
    prepare_trajectory_maps: bool = True
    status: str = "queued"
    started_at: str | None = None
    finished_at: str | None = None
    attempts: list[AttemptResult] | None = None
    error: str | None = None
    preflight: dict[str, Any] | None = None
    live_progress: dict[str, Any] | None = None
    cancel_requested: bool = False
    active_attempt: int | None = None
    forced_attempt_failure: dict[str, Any] | None = None
    interventions: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.attempts is None:
            self.attempts = []
        if self.interventions is None:
            self.interventions = []

    def to_dict(self) -> dict[str, Any]:
        completed = len(self.attempts)
        passed = sum(item.status == "passed" for item in self.attempts)
        failed = sum(item.status == "failed" for item in self.attempts)
        cancelled = sum(item.status == "cancelled" for item in self.attempts)
        return {
            "id": self.id,
            "case": {
                "id": self.case.id,
                "filename": self.case.filename,
                "name": self.case.name,
                "parameters": asdict(self.case.parameters),
            },
            "requestedCount": self.requested_count,
            "intervalSeconds": self.interval_s,
            "prepareTrajectoryMaps": self.prepare_trajectory_maps,
            "status": self.status,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "error": self.error,
            "preflight": self.preflight,
            "liveProgress": self.live_progress,
            "cancelRequested": self.cancel_requested,
            "activeAttempt": self.active_attempt,
            "interventions": self.interventions,
            "summary": {
                "completed": completed,
                "passed": passed,
                "failed": failed,
                "cancelled": cancelled,
                "passRate": round(passed / (passed + failed) * 100, 1) if passed + failed else 0,
            },
            "attempts": [asdict(item) for item in self.attempts],
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
