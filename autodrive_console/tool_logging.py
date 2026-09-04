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
    """低开销的本地工具日志与受控子进程诊断归档。"""

    NORMAL_NAME = "ry-aletheia.log"
    ERROR_NAME = "ry-aletheia-error.log"
    # 这些文件均由本工具启动的受控进程写入。使用固定白名单而非扫描 logs/
    # 目录，下载诊断包时不会意外带走部署者放入的任意文件。
    SIDECAR_NAMES = (
        "live_preprocessor_cloud.log",
        "live_preprocessor_pose.log",
        "live_preprocessor_costmap.log",
        "video-runtime.log",
    )
    _DIAGNOSTIC_LABELS = {
        NORMAL_NAME: ("控制台运行日志", "控制台、任务、配置与运行事件（JSONL）"),
        ERROR_NAME: ("控制台错误日志", "控制台 ERROR/CRITICAL 事件与异常堆栈（JSONL）"),
        "live_preprocessor_cloud.log": ("点云预处理", "点云输入、TF 投影、过滤、降采样与 UDP 发送的原始输出"),
        "live_preprocessor_pose.log": ("位姿预处理", "map → base TF 获取、位姿编码与 UDP 发送的原始输出"),
        "live_preprocessor_costmap.log": ("局部代价地图预处理", "局部代价地图输入、时间戳 TF 投影、时效丢弃与 UDP 发送的原始输出"),
        "video-runtime.log": ("视频运行时", "MediaMTX、ROS 图像输入、VAAPI 与 GStreamer 的原始输出"),
    }
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

    def diagnostic_files(self) -> list[Path]:
        """Return only known, existing diagnostic files in a stable order.

        The normal/error handlers rotate their files, so include their bounded
        history as well.  Native ROS and media children use their own plain
        logs; their current files are deliberately included in the same
        support bundle instead of forcing a maintainer to guess which one is
        relevant to a map or video failure.
        """

        candidates: list[Path] = []
        for name in (self.NORMAL_NAME, self.ERROR_NAME):
            candidates.append(self.directory / name)
            candidates.extend(self.directory / f"{name}.{index}" for index in range(1, self._BACKUP_COUNT + 1))
        candidates.extend(self.directory / name for name in self.SIDECAR_NAMES)
        return [path for path in candidates if path.is_file()]

    def diagnostic_records(self) -> list[dict[str, object]]:
        """Describe every downloadable diagnostic file without exposing paths."""

        records: list[dict[str, object]] = []
        for path in self.diagnostic_files():
            base_name, dot, rotation = path.name.rpartition(".")
            if dot and rotation.isdigit() and base_name in self._DIAGNOSTIC_LABELS:
                label, detail = self._DIAGNOSTIC_LABELS[base_name]
                label = f"{label}（轮转 {rotation}）"
            else:
                label, detail = self._DIAGNOSTIC_LABELS[path.name]
            try:
                stat = path.stat()
            except OSError:
                continue
            records.append({
                "name": path.name,
                "label": label,
                "detail": detail,
                "size_bytes": stat.st_size,
                "modified_at": int(stat.st_mtime),
            })
        return records

    def diagnostic_file(self, name: str) -> Path | None:
        """Resolve a user-requested download through the fixed diagnostics list."""

        if not isinstance(name, str):
            return None
        return next((path for path in self.diagnostic_files() if path.name == name), None)
