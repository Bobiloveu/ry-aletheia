from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "source": record.name.removeprefix("ry_aletheia."),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class ToolLogStore:
    """低开销的本地工具日志：常规与 ERROR 级别分别滚动保存。"""

    NORMAL_NAME = "ry-aletheia.log"
    ERROR_NAME = "ry-aletheia-error.log"
    _MAX_BYTES = 2 * 1024 * 1024
    _BACKUP_COUNT = 3

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def configure(self) -> logging.Logger:
        self.directory.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("ry_aletheia")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if any(getattr(handler, "_ry_aletheia_log", False) for handler in logger.handlers):
            return logger
        formatter = _JsonFormatter()
        normal = RotatingFileHandler(self.directory / self.NORMAL_NAME, encoding="utf-8", maxBytes=self._MAX_BYTES, backupCount=self._BACKUP_COUNT)
        normal.setLevel(logging.INFO)
        normal.setFormatter(formatter)
        normal._ry_aletheia_log = True  # type: ignore[attr-defined]
        errors = RotatingFileHandler(self.directory / self.ERROR_NAME, encoding="utf-8", maxBytes=self._MAX_BYTES, backupCount=self._BACKUP_COUNT)
        errors.setLevel(logging.ERROR)
        errors.setFormatter(formatter)
        errors._ry_aletheia_log = True  # type: ignore[attr-defined]
        logger.addHandler(normal)
        logger.addHandler(errors)
        return logger

    def entries(self, errors_only: bool = False, limit: int = 200) -> list[dict[str, str]]:
        limit = min(max(int(limit), 1), 500)
        target = self.directory / (self.ERROR_NAME if errors_only else self.NORMAL_NAME)
        if not target.is_file():
            return []
        # 每次页面刷新仅取末尾 256 KiB，避免历史日志变大后拖慢小车。
        with target.open("rb") as source:
            source.seek(0, 2)
            start = max(source.tell() - 256 * 1024, 0)
            source.seek(start)
            body = source.read().decode("utf-8", errors="replace")
        lines = body.splitlines()
        if start and lines:
            lines = lines[1:]
        items: list[dict[str, str]] = []
        for line in reversed(lines):
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and all(isinstance(item.get(key), str) for key in ("time", "level", "source", "message")):
                entry = {key: item[key] for key in ("time", "level", "source", "message")}
                # 完整堆栈只在用户主动展开时展示；列表默认仍保持紧凑。
                if isinstance(item.get("exception"), str) and item["exception"]:
                    entry["exception"] = item["exception"]
                items.append(entry)
            if len(items) >= limit:
                break
        return items

    def file(self, errors_only: bool = False) -> Path:
        return self.directory / (self.ERROR_NAME if errors_only else self.NORMAL_NAME)

    def files(self) -> Iterable[Path]:
        return (self.directory / self.NORMAL_NAME, self.directory / self.ERROR_NAME)
