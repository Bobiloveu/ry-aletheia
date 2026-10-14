"""Crash-safe persistence for ordinary test runs.

These snapshots are deliberately report-only.  They can reconstruct an audit
record after a process or vehicle restart, but never contain a task source that
could be used to resume execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .models import AttemptResult, MultiTaskRequest, RunRecord, TaskParameters, TestCase, now_iso


LOGGER = logging.getLogger("ry_aletheia.run_checkpoint")
CHECKPOINT_SCHEMA_VERSION = 1
_RUN_ID = re.compile(r"^[0-9a-f]{12}$")
_ACTIVE_STATUSES = frozenset({"queued", "preparing", "running", "cancelling", "awaiting_recovery", "recovering"})
_ATTEMPT_STATUSES = frozenset({"passed", "failed", "cancelled", "unknown_after_power_loss"})


@dataclass(frozen=True)
class RecoveredRunCheckpoint:
    run: RunRecord
    attempt_in_progress: bool
    saved_at: str


class RunCheckpointStore:
    """Own and validate hidden checkpoints below one report root."""

    def __init__(self, report_dir: Path) -> None:
        self.report_dir = Path(report_dir)
        self.directory = self.report_dir / ".run-checkpoints"

    def save(self, run: RunRecord, *, attempt_in_progress: bool) -> Path:
        if not _RUN_ID.fullmatch(run.id):
            raise ValueError("运行 ID 无法用于检查点")
        payload = {
            "schema": CHECKPOINT_SCHEMA_VERSION,
            "run_id": run.id,
            "saved_at": now_iso(),
            "attempt_in_progress": bool(attempt_in_progress),
            "run": self._serialize_run(run),
        }
        target = self.directory / f"{run.id}.json"
        self._atomic_json(target, payload)
        return target

    def remove(self, run_id: str) -> None:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("运行 ID 无法用于检查点")
        target = self.directory / f"{run_id}.json"
        try:
            target.unlink()
        except FileNotFoundError:
            return
        self._fsync_directory(target.parent)

    def load_recoverable(self) -> list[RecoveredRunCheckpoint]:
        if not self.directory.is_dir():
            return []
        recovered: list[RecoveredRunCheckpoint] = []
        for target in sorted(self.directory.glob("*.json")):
            if not _RUN_ID.fullmatch(target.stem):
                continue
            try:
                value = json.loads(target.read_text(encoding="utf-8"))
                snapshot = self._deserialize(value, target.stem)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                LOGGER.warning("忽略无效运行检查点：file=%s error=%s", target.name, exc)
                continue
            if snapshot.run.status in _ACTIVE_STATUSES:
                recovered.append(snapshot)
        return recovered

    def _serialize_run(self, run: RunRecord) -> dict[str, Any]:
        return {
            "id": run.id,
            "case": self._serialize_case(run.case),
            "requested_count": run.requested_count,
            "interval_s": run.interval_s,
            "prepare_trajectory_maps": run.prepare_trajectory_maps,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "attempts": [self._serialize_attempt(item, run.id) for item in run.attempts],
            "error": run.error,
            "preflight": run.preflight,
            "cancel_requested": run.cancel_requested,
            "active_attempt": run.active_attempt,
            "interventions": run.interventions,
        }

    @staticmethod
    def _serialize_case(case: TestCase) -> dict[str, Any]:
        return {
            "id": case.id,
            "filename": case.filename,
            "name": case.name,
            "parameters": asdict(case.parameters),
            "execution_mode": case.execution_mode,
            "multi_request": case.multi_request.to_dict() if case.multi_request else None,
        }

    def _serialize_attempt(self, item: AttemptResult, run_id: str) -> dict[str, Any]:
        data = asdict(item)
        trajectory = data.get("trajectory")
        if isinstance(trajectory, dict):
            data["trajectory"] = self._serialize_trajectory(trajectory, run_id)
        return data

    def _serialize_trajectory(self, trajectory: dict[str, Any], run_id: str) -> dict[str, Any]:
        value = json.loads(json.dumps(trajectory, ensure_ascii=False))
        if isinstance(value.get("file"), str):
            value["file"] = self._relative_evidence(value["file"], run_id)
        visuals = value.get("visualizations", [])
        if not isinstance(visuals, list):
            raise ValueError("轨迹可视化数据无效")
        for visual in visuals:
            if not isinstance(visual, dict) or not isinstance(visual.get("file"), str):
                raise ValueError("轨迹可视化文件无效")
            visual["file"] = self._relative_evidence(visual["file"], run_id)
        return value

    def _relative_evidence(self, raw: str, run_id: str) -> str:
        candidate = Path(raw)
        resolved = candidate.resolve() if candidate.is_absolute() else (self.report_dir / candidate).resolve()
        root = self.report_dir.resolve()
        expected = (root / f"run_{run_id}_trajectory").resolve()
        if not resolved.is_relative_to(root) or not resolved.is_relative_to(expected):
            raise ValueError("轨迹证据必须位于当前运行的报告目录")
        if resolved.suffix not in {".json", ".svg", ".png"}:
            raise ValueError("轨迹证据文件类型无效")
        return resolved.relative_to(root).as_posix()

    def _deserialize(self, value: object, expected_run_id: str) -> RecoveredRunCheckpoint:
        if not isinstance(value, dict) or set(value) != {"schema", "run_id", "saved_at", "attempt_in_progress", "run"}:
            raise ValueError("检查点字段无效")
        if value["schema"] != CHECKPOINT_SCHEMA_VERSION or value["run_id"] != expected_run_id:
            raise ValueError("检查点版本或运行 ID 无效")
        if not isinstance(value["saved_at"], str) or not isinstance(value["attempt_in_progress"], bool):
            raise ValueError("检查点时间或活动轮次无效")
        datetime.fromisoformat(value["saved_at"].replace("Z", "+00:00"))
        run = self._deserialize_run(value["run"], expected_run_id)
        return RecoveredRunCheckpoint(run, value["attempt_in_progress"], value["saved_at"])

    def _deserialize_run(self, value: object, expected_run_id: str) -> RunRecord:
        if not isinstance(value, dict) or value.get("id") != expected_run_id:
            raise ValueError("检查点运行记录无效")
        if value.get("status") not in _ACTIVE_STATUSES:
            raise ValueError("检查点不是活动普通运行")
        attempts_raw = value.get("attempts")
        if not isinstance(attempts_raw, list) or not isinstance(value.get("requested_count"), int) or not isinstance(value.get("interval_s"), (int, float)):
            raise ValueError("检查点轮次无效")
        attempts = [self._deserialize_attempt(item, expected_run_id) for item in attempts_raw]
        indexes = [item.index for item in attempts]
        if len(indexes) != len(set(indexes)) or any(index < 1 for index in indexes):
            raise ValueError("检查点轮次重复或无效")
        case = self._deserialize_case(value.get("case"))
        return RunRecord(
            id=expected_run_id,
            case=case,
            requested_count=value["requested_count"],
            interval_s=float(value["interval_s"]),
            prepare_trajectory_maps=bool(value.get("prepare_trajectory_maps", True)),
            status=value["status"],
            started_at=value.get("started_at"),
            finished_at=value.get("finished_at"),
            attempts=attempts,
            error=value.get("error"),
            preflight=value.get("preflight"),
            cancel_requested=bool(value.get("cancel_requested", False)),
            active_attempt=value.get("active_attempt"),
            interventions=value.get("interventions") if isinstance(value.get("interventions"), list) else [],
        )

    @staticmethod
    def _deserialize_case(value: object) -> TestCase:
        if not isinstance(value, dict) or set(value) != {"id", "filename", "name", "parameters", "execution_mode", "multi_request"}:
            raise ValueError("检查点用例无效")
        if not all(isinstance(value[key], str) for key in ("id", "filename", "name", "execution_mode")) or not isinstance(value["parameters"], dict):
            raise ValueError("检查点用例字段无效")
        params = TaskParameters(**value["parameters"])
        multi = MultiTaskRequest.from_dict(value["multi_request"]) if value["multi_request"] is not None else None
        return TestCase(value["id"], value["filename"], value["name"], params, "", value["execution_mode"], multi)

    def _deserialize_attempt(self, value: object, run_id: str) -> AttemptResult:
        required = {"index", "status", "message", "duration_s", "started_at", "trajectory", "case_id", "case_filename", "delivery_evidence", "relocalization_count"}
        allowed = required | {"bag_recording"}
        if not isinstance(value, dict) or not required.issubset(value) or not set(value).issubset(allowed):
            raise ValueError("检查点轮次字段无效")
        if value["status"] not in _ATTEMPT_STATUSES or not isinstance(value["index"], int) or not isinstance(value["message"], str) or not isinstance(value["started_at"], str):
            raise ValueError("检查点轮次内容无效")
        trajectory = value["trajectory"]
        if trajectory is not None:
            if not isinstance(trajectory, dict):
                raise ValueError("检查点轨迹无效")
            trajectory = self._restore_trajectory(trajectory, run_id)
        bag_recording = value.get("bag_recording")
        if bag_recording is not None:
            if not isinstance(bag_recording, dict):
                raise ValueError("检查点诊断录包摘要无效")
            try:
                # The audit is display-only evidence.  JSON round-tripping
                # rejects non-persistable objects and detaches the recovered
                # record from the parsed checkpoint payload.
                bag_recording = json.loads(json.dumps(bag_recording, ensure_ascii=False))
            except (TypeError, ValueError) as exc:
                raise ValueError("检查点诊断录包摘要无效") from exc
        return AttemptResult(value["index"], value["status"], value["message"], float(value["duration_s"]), value["started_at"], trajectory, value["case_id"], value["case_filename"], value["delivery_evidence"], int(value["relocalization_count"]), bag_recording)

    def _restore_trajectory(self, trajectory: dict[str, Any], run_id: str) -> dict[str, Any]:
        value = json.loads(json.dumps(trajectory, ensure_ascii=False))
        if isinstance(value.get("file"), str):
            value["file"] = str(self._restore_evidence(value["file"], run_id))
        for visual in value.get("visualizations", []):
            if not isinstance(visual, dict) or not isinstance(visual.get("file"), str):
                raise ValueError("检查点轨迹可视化无效")
            visual["file"] = str(self._restore_evidence(visual["file"], run_id))
        return value

    def _restore_evidence(self, relative: str, run_id: str) -> Path:
        if Path(relative).is_absolute():
            raise ValueError("检查点轨迹路径必须相对报告目录")
        return_path = (self.report_dir / relative).resolve()
        root = self.report_dir.resolve()
        expected = (root / f"run_{run_id}_trajectory").resolve()
        if not return_path.is_relative_to(root) or not return_path.is_relative_to(expected):
            raise ValueError("检查点轨迹越出报告目录")
        return return_path

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        try:
            descriptor = os.open(directory, os.O_DIRECTORY)
        except (AttributeError, OSError):
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _atomic_json(self, target: Path, payload: dict[str, Any]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
            self._fsync_directory(target.parent)
        except Exception:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass
            raise
