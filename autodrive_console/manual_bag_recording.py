"""Backend-owned manual diagnostic bag recording lifecycle."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import threading
import time
from typing import Callable

from .bag_recording import BagRecordingError, BagRecordingManager

LOGGER = logging.getLogger("ry_aletheia.manual_bag_recording")


class ManualRecordingError(BagRecordingError):
    """A manual diagnostic capture request is invalid or conflicts with one in progress."""


@dataclass(frozen=True)
class ManualRecordingRequest:
    topics: tuple[str, ...]
    duration_minutes: int
    label: str = ""

    DURATIONS = frozenset((5, 10, 15, 20))
    MAX_TOPICS = 32
    MAX_LABEL_LENGTH = 80

    @classmethod
    def from_payload(cls, payload: object) -> "ManualRecordingRequest":
        if not isinstance(payload, dict) or set(payload) not in ({"topics", "durationMinutes"}, {"topics", "durationMinutes", "label"}):
            raise ManualRecordingError("手动录制请求字段无效")
        topics = payload.get("topics")
        duration = payload.get("durationMinutes")
        label = payload.get("label", "")
        if not isinstance(topics, list) or not 1 <= len(topics) <= cls.MAX_TOPICS or not all(isinstance(topic, str) and topic.startswith("/") for topic in topics) or len(set(topics)) != len(topics):
            raise ManualRecordingError(f"请选择 1 至 {cls.MAX_TOPICS} 个不重复 Topic")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration not in cls.DURATIONS:
            raise ManualRecordingError("手动录制时长仅支持 5、10、15 或 20 分钟")
        if not isinstance(label, str):
            raise ManualRecordingError("场景名称无效")
        label = " ".join(label.split())
        if len(label) > cls.MAX_LABEL_LENGTH or any(ord(character) < 32 for character in label):
            raise ManualRecordingError("场景名称无效")
        return cls(tuple(topics), duration, label)


class ManualRecordingController:
    """Own exactly one page-independent manual recording and its deadline."""

    def __init__(
        self,
        recordings: BagRecordingManager,
        *,
        test_recording_active: Callable[[], bool] | None = None,
        timer_factory: Callable[[float, Callable[[], None]], object] = threading.Timer,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._recordings = recordings
        self._test_recording_active = test_recording_active or (lambda: False)
        self._timer_factory = timer_factory
        self._monotonic = monotonic
        self._lock = threading.RLock()
        self._active = None
        self._request: ManualRecordingRequest | None = None
        self._deadline = 0.0
        self._timer = None
        self._finalizing = False

    def has_active_recording(self) -> bool:
        with self._lock:
            return self._active is not None or self._finalizing

    def status(self) -> dict[str, object]:
        with self._lock:
            if self._finalizing:
                return {"state": "finalizing"}
            if self._active is None or self._request is None:
                return {"state": "idle"}
            remaining = max(0, int(self._deadline - self._monotonic()))
            return {
                "state": "recording",
                "label": self._request.label,
                "topic_count": len(self._request.topics),
                "duration_minutes": self._request.duration_minutes,
                "started_at": self._active.started_at,
                "remaining_seconds": remaining,
                "deadline_at": (datetime.now().astimezone() + timedelta(seconds=remaining)).isoformat(timespec="seconds"),
            }

    def start(self, payload: object) -> dict[str, object]:
        request = ManualRecordingRequest.from_payload(payload)
        with self._lock:
            if self._active is not None or self._finalizing:
                raise ManualRecordingError("已有手动录制正在处理")
            if self._test_recording_active():
                raise ManualRecordingError("自动化测试录包正在进行，暂不能开始手动录制")
            try:
                active = self._recordings.start_manual(request)
            except BagRecordingError as exc:
                raise ManualRecordingError(str(exc)) from exc
            self._active = active
            self._request = request
            self._deadline = self._monotonic() + request.duration_minutes * 60
            timer = self._timer_factory(request.duration_minutes * 60, self._deadline_reached)
            self._timer = timer
            timer.start()
            LOGGER.info("Manual recording deadline scheduled archive=%s duration_minutes=%d topics=%d",
                        active.archive_id, request.duration_minutes, len(request.topics))
            return self.status()

    def stop(self) -> dict[str, object]:
        self._finish()
        return self.status()

    def close(self) -> None:
        try:
            self._finish()
        except ManualRecordingError:
            pass

    def _deadline_reached(self) -> None:
        LOGGER.info("Manual recording deadline reached")
        try:
            self._finish()
        except ManualRecordingError:
            pass

    def _finish(self) -> None:
        with self._lock:
            if self._active is None:
                if self._finalizing:
                    return
                raise ManualRecordingError("没有正在录制的手动场景")
            active = self._active
            timer = self._timer
            self._active = None
            self._request = None
            self._timer = None
            self._deadline = 0.0
            self._finalizing = True
        if timer is not None:
            timer.cancel()
        try:
            LOGGER.info("Manual recording finalizing archive=%s", active.archive_id)
            result = self._recordings.stop(active)
            LOGGER.info("Manual recording finalized archive=%s audit=%s",
                        active.archive_id, result.get("audit", {}).get("status", "unknown"))
        except Exception:
            LOGGER.exception("Manual recording finalization failed archive=%s", active.archive_id)
            raise
        finally:
            with self._lock:
                self._finalizing = False
