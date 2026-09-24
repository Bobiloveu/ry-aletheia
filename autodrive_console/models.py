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
    execution_mode: str = "single_r6s"

    def __post_init__(self) -> None:
        if self.execution_mode not in {"single_r6s", "multi_r6b"}:
            raise ValueError("任务执行模式无效")


@dataclass(frozen=True)
class MultiDestination:
    """One business delivery point in an R6B multi-point chain."""

    building: str
    unit: str
    floor: str
    door: str
    cargo_type: int
    delivery_code: str

    def __post_init__(self) -> None:
        for name in ("building", "unit", "floor", "door", "delivery_code"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name}不能为空")
        if isinstance(self.cargo_type, bool) or self.cargo_type not in {1, 2, 0, -1}:
            raise ValueError("货舱类型必须是 1、2、0 或 -1")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "building": self.building,
            "unit": self.unit,
            "floor": self.floor,
            "door": self.door,
            "cargo_type": self.cargo_type,
            "delivery_code": self.delivery_code,
        }

    @classmethod
    def from_dict(cls, value: object) -> "MultiDestination":
        if not isinstance(value, dict):
            raise ValueError("多点目的地必须是对象")
        expected = {"building", "unit", "floor", "door", "cargo_type", "delivery_code"}
        if set(value) != expected:
            raise ValueError("多点目的地字段不完整")
        for name in ("building", "unit", "floor", "door", "delivery_code"):
            if not isinstance(value[name], str) or not value[name].strip():
                raise ValueError(f"{name}不能为空")
        return cls(
            building=value["building"],
            unit=value["unit"],
            floor=value["floor"],
            door=value["door"],
            cargo_type=value["cargo_type"],
            delivery_code=value["delivery_code"],
        )


@dataclass(frozen=True)
class MultiTaskRequest:
    """Frozen request payload for ``StartMultiTasksExecute``."""

    community: str
    out_eguard: bool
    return_origin: bool
    destinations: tuple[MultiDestination, ...]
    task_uuid: str

    def __post_init__(self) -> None:
        if not isinstance(self.community, str) or not self.community.strip():
            raise ValueError("小区不能为空")
        if not isinstance(self.out_eguard, bool) or not isinstance(self.return_origin, bool):
            raise ValueError("摆渡和返程选项必须是布尔值")
        destinations = tuple(self.destinations)
        if not destinations:
            raise ValueError("多点任务至少需要一个目的地")
        if not all(isinstance(item, MultiDestination) for item in destinations):
            raise ValueError("多点任务目的地格式无效")
        delivery_codes = [item.delivery_code for item in destinations]
        if len(set(delivery_codes)) != len(delivery_codes):
            raise ValueError("同一多点任务中的配送码必须唯一")
        if not isinstance(self.task_uuid, str) or not self.task_uuid.strip():
            raise ValueError("任务 UUID 不能为空")
        object.__setattr__(self, "destinations", destinations)

    def to_dict(self) -> dict[str, object]:
        return {
            "community": self.community,
            "out_eguard": self.out_eguard,
            "return_origin": self.return_origin,
            "tasks_seqs": [item.to_dict() for item in self.destinations],
            "task_uuid": self.task_uuid,
        }

    @classmethod
    def from_dict(cls, value: object) -> "MultiTaskRequest":
        if not isinstance(value, dict):
            raise ValueError("多点任务请求必须是对象")
        expected = {"community", "out_eguard", "return_origin", "tasks_seqs", "task_uuid"}
        if set(value) != expected or not isinstance(value["tasks_seqs"], list):
            raise ValueError("多点任务请求字段不完整")
        if not isinstance(value["community"], str) or not value["community"].strip() or not isinstance(value["task_uuid"], str) or not value["task_uuid"].strip():
            raise ValueError("小区或任务 UUID 不能为空")
        return cls(
            community=value["community"],
            out_eguard=value["out_eguard"],
            return_origin=value["return_origin"],
            destinations=tuple(MultiDestination.from_dict(item) for item in value["tasks_seqs"]),
            task_uuid=value["task_uuid"],
        )


@dataclass(frozen=True)
class TestCase:
    id: str
    filename: str
    name: str
    parameters: TaskParameters
    source: str
    execution_mode: str = "single_r6s"
    multi_request: MultiTaskRequest | None = None


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
    delivery_evidence: list[dict[str, str]] | None = None


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
                "executionMode": self.case.execution_mode,
                "multiRequest": self.case.multi_request.to_dict() if self.case.multi_request is not None else None,
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
