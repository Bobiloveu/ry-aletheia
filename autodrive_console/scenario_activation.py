"""Page-independent progress state for a manually applied test scenario."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import logging
import threading
from typing import Callable


LOGGER = logging.getLogger("ry_aletheia.scenario_activation")


class ScenarioActivationTracker:
    """Expose one bounded scenario activation while its runtime settles."""

    _ACTIVE_STATES = frozenset(("running",))

    def __init__(
        self,
        runner: Callable[[str, dict | None, Callable[[str, str, dict | None], None]], dict],
        *,
        thread_factory: Callable[..., object] = threading.Thread,
    ) -> None:
        self._runner = runner
        self._thread_factory = thread_factory
        self._lock = threading.RLock()
        self._status: dict[str, object] = {
            "state": "idle",
            "phase": "idle",
            "message": "当前没有正在应用的场景方案。",
            "stages": [],
        }

    def status(self) -> dict[str, object]:
        with self._lock:
            return deepcopy(self._status)

    def is_active(self) -> bool:
        with self._lock:
            return self._status.get("state") in self._ACTIVE_STATES

    def start(self, profile_id: str, document: dict | None) -> dict[str, object]:
        with self._lock:
            if self.is_active():
                raise ValueError("已有场景方案正在应用，请等待当前操作完成")
            self._status = {
                "state": "running",
                "phase": "queued",
                "message": "已接受启用请求，正在准备应用场景方案。",
                "stages": [],
                "started_at": self._timestamp(),
            }
            worker = self._thread_factory(
                target=lambda: self._run(profile_id, document),
                daemon=True,
                name="scenario-activation",
            )
            LOGGER.info("场景方案应用已接受：profile=%s", profile_id)
            worker.start()
            return deepcopy(self._status)

    def _run(self, profile_id: str, document: dict | None) -> None:
        try:
            result = self._runner(profile_id, document, self._progress)
        except Exception:
            LOGGER.exception("场景方案应用未完成：profile=%s", profile_id)
            self._replace(
                state="failed",
                phase="failed",
                message="场景未完成应用。定位与导航依赖尚未确认就绪；请查看工具日志后恢复常规配置或重试。",
            )
            return
        self._replace(
            state="completed",
            phase="completed",
            message=str(result.get("message") or "场景方案已应用，运行依赖已确认就绪。"),
        )
        LOGGER.info("场景方案应用已完成：profile=%s", profile_id)

    def _progress(self, phase: str, message: str, details: dict | None = None) -> None:
        with self._lock:
            changed = self._status.get("phase") != phase
        fields: dict[str, object] = {"phase": phase, "message": message}
        if isinstance(details, dict) and isinstance(details.get("stages"), list):
            fields["stages"] = deepcopy(details["stages"])
        self._replace(**fields)
        if changed:
            LOGGER.info("场景方案应用阶段：phase=%s message=%s", phase, message)

    def _replace(self, **fields: object) -> None:
        with self._lock:
            self._status.update(fields)
            if fields.get("state") in {"completed", "failed"}:
                self._status["finished_at"] = self._timestamp()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")
