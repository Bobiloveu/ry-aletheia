from __future__ import annotations

import codecs
import hashlib
import os
import re
import secrets
import stat
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator

from .settings import SettingsStore


# 与旧 Qt RYLog 的识别范围一致：10 位 Unix 秒、小数秒，以及 ROS2 常见的
# 19 位纳秒时间戳。仅转换日志正文中的完整 token，避免改动普通数字字段。
ROS_TIME_PATTERN = re.compile(r"\b(1[0-9]{9})(?:\.(\d{1,9}))?\b|\b(1[0-9]{18})\b")
BEIJING_TIMEZONE = timezone(timedelta(hours=8), name="CST")
_STREAM_CHUNK_BYTES = 64 * 1024
_ROS_TIME_TAIL_CHARS = 64


class RobotLogError(ValueError):
    """A requested robot log operation cannot be completed safely."""


@dataclass
class _RobotLogDownload:
    source_id: str
    file_id: str
    name: str
    total_bytes: int
    convert_ros_time: bool
    state: str
    sent_bytes: int
    error: str | None
    updated_at: float


class RobotLogDownloadTracker:
    """Short-lived, metadata-only transfer state for browser-visible progress."""

    MAX_RECORDS = 100
    TTL_SECONDS = 15 * 60

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._records: dict[str, _RobotLogDownload] = {}

    def prepare(self, source_id: str, file_id: str, name: str, total_bytes: int, *, convert_ros_time: bool) -> dict[str, Any]:
        if not isinstance(total_bytes, int) or total_bytes < 0:
            raise RobotLogError("日志文件大小无效")
        with self._lock:
            now = self._clock()
            self._purge_locked(now)
            if len(self._records) >= self.MAX_RECORDS:
                raise RobotLogError("当前下载任务过多，请稍后重试")
            while (download_id := secrets.token_hex(16)) in self._records:
                pass
            self._records[download_id] = _RobotLogDownload(
                source_id=source_id,
                file_id=file_id,
                name=name,
                total_bytes=total_bytes,
                convert_ros_time=convert_ros_time,
                state="prepared",
                sent_bytes=0,
                error=None,
                updated_at=now,
            )
            return self._public(download_id, self._records[download_id])

    def status(self, download_id: str) -> dict[str, Any]:
        with self._lock:
            self._purge_locked(self._clock())
            record = self._records.get(download_id)
            if record is None:
                raise RobotLogError("下载进度不存在或已过期")
            return self._public(download_id, record)

    def start(self, download_id: str) -> _RobotLogDownload:
        with self._lock:
            self._purge_locked(self._clock())
            record = self._records.get(download_id)
            if record is None:
                raise RobotLogError("下载进度不存在或已过期")
            if record.state != "prepared":
                raise RobotLogError("下载已开始或已结束")
            record.state = "streaming"
            record.updated_at = self._clock()
            return record

    def advance(self, download_id: str, sent_bytes: int) -> None:
        with self._lock:
            record = self._records.get(download_id)
            if record is None or record.state != "streaming":
                return
            record.sent_bytes = max(record.sent_bytes, min(max(0, sent_bytes), record.total_bytes))
            record.updated_at = self._clock()

    def complete(self, download_id: str) -> None:
        with self._lock:
            record = self._records.get(download_id)
            if record is None or record.state != "streaming":
                return
            record.sent_bytes = record.total_bytes
            record.state = "completed"
            record.updated_at = self._clock()

    def fail(self, download_id: str, message: str) -> None:
        with self._lock:
            record = self._records.get(download_id)
            if record is None or record.state not in {"prepared", "streaming"}:
                return
            record.state = "failed"
            record.error = message
            record.updated_at = self._clock()

    def _purge_locked(self, now: float) -> None:
        expired = [download_id for download_id, record in self._records.items() if now - record.updated_at > self.TTL_SECONDS]
        for download_id in expired:
            self._records.pop(download_id, None)

    @staticmethod
    def _public(download_id: str, record: _RobotLogDownload) -> dict[str, Any]:
        return {
            "id": download_id,
            "name": record.name,
            "state": record.state,
            "sent_bytes": record.sent_bytes,
            "total_bytes": record.total_bytes,
            "convert_ros_time": record.convert_ros_time,
            "error": record.error,
        }


def convert_ros_time_to_beijing(text: str) -> str:
    """Convert legacy RYLog's recognised ROS/Unix timestamp forms in text."""

    def replacement(match: re.Match[str]) -> str:
        seconds_text = match.group(3)
        seconds = int(seconds_text) // 1_000_000_000 if seconds_text else int(match.group(1))
        return datetime.fromtimestamp(seconds, timezone.utc).astimezone(BEIJING_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

    return ROS_TIME_PATTERN.sub(replacement, text)


def ensure_utf8_text_stream(stream: BinaryIO, *, maximum_bytes: int | None = None) -> None:
    """Reject binary/invalid UTF-8 input before a converted HTTP response starts."""

    if maximum_bytes is not None and (not isinstance(maximum_bytes, int) or maximum_bytes < 0):
        raise ValueError("日志快照大小无效")
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    remaining = maximum_bytes
    try:
        while remaining is None or remaining:
            chunk = stream.read(_STREAM_CHUNK_BYTES if remaining is None else min(_STREAM_CHUNK_BYTES, remaining))
            if not chunk:
                if remaining:
                    raise OSError("日志文件在下载开始后缩小")
                break
            decoder.decode(chunk)
            if remaining is not None:
                remaining -= len(chunk)
        decoder.decode(b"", final=True)
    finally:
        stream.seek(0)


def iter_ros_time_converted_bytes(stream: BinaryIO, *, maximum_bytes: int | None = None) -> Iterator[bytes]:
    """Yield UTF-8 output without buffering a whole user-selected log in memory."""

    if maximum_bytes is not None and (not isinstance(maximum_bytes, int) or maximum_bytes < 0):
        raise ValueError("日志快照大小无效")
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    pending = ""
    remaining = maximum_bytes
    while remaining is None or remaining:
        chunk = stream.read(_STREAM_CHUNK_BYTES if remaining is None else min(_STREAM_CHUNK_BYTES, remaining))
        if not chunk:
            if remaining:
                raise OSError("日志文件在下载开始后缩小")
            break
        if remaining is not None:
            remaining -= len(chunk)
        pending += decoder.decode(chunk)
        if len(pending) <= _ROS_TIME_TAIL_CHARS:
            continue
        # Keep enough trailing characters to avoid splitting the longest supported
        # timestamp token across two I/O chunks before applying the regular expression.
        cut = len(pending) - _ROS_TIME_TAIL_CHARS
        earliest_candidate = pending.find("1", max(0, cut - 24))
        if earliest_candidate != -1:
            cut = min(cut, earliest_candidate)
        if cut:
            yield convert_ros_time_to_beijing(pending[:cut]).encode("utf-8")
            pending = pending[cut:]
    pending += decoder.decode(b"", final=True)
    if pending:
        yield convert_ros_time_to_beijing(pending).encode("utf-8")


@dataclass
class RobotLogFile:
    name: str
    size_bytes: int
    stream: BinaryIO


class RobotLogStore:
    """Expose only direct regular files from explicitly saved robot log sources."""

    MAX_FILE_BYTES = 256 * 1024 * 1024

    def __init__(self, settings: SettingsStore) -> None:
        self._settings = settings

    def list_files(self, source_id: str, *, query: str = "") -> list[dict[str, Any]]:
        if not isinstance(query, str) or len(query) > 100:
            raise RobotLogError("文件名关键词无效")
        normalized_query = query.strip().casefold()
        records = [
            self._record(source_id, path, metadata)
            for path, metadata in self._direct_regular_files(source_id)
            if not normalized_query or normalized_query in path.name.casefold()
        ]
        return sorted(records, key=lambda item: (item["modified_at"], item["name"]), reverse=True)

    def sources(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for source in self._settings.load().robot_logs["sources"]:
            record = dict(source)
            try:
                record["file_count"] = len(self._direct_regular_files(source["id"]))
                record["status"] = "available"
                record["message"] = "可读取"
            except RobotLogError as exc:
                record["file_count"] = 0
                record["status"] = "missing" if str(exc) == "日志目录不存在" else "unavailable"
                record["message"] = "目录不存在" if record["status"] == "missing" else "目录不可读取"
            records.append(record)
        return records

    def save_sources(self, sources: object) -> list[dict[str, str]]:
        if not isinstance(sources, list):
            raise RobotLogError("机器人日志目录配置格式错误")
        existing = {source["id"] for source in self._settings.load().robot_logs["sources"]}
        assigned = set(existing)
        normalized: list[dict[str, str]] = []
        for source in sources:
            if not isinstance(source, dict) or set(source) - {"id", "name", "path"}:
                raise RobotLogError("机器人日志目录配置格式错误")
            source_id = source.get("id")
            if source_id is None:
                source_id = self._new_source_id(assigned)
            elif not isinstance(source_id, str) or source_id not in existing:
                raise RobotLogError("新增日志目录不能指定标识")
            assigned.add(source_id)
            normalized.append({
                "id": source_id,
                "name": source.get("name"),
                "path": source.get("path"),
            })
        try:
            saved = self._settings.save({"robot_logs": {"sources": normalized}})
        except ValueError as exc:
            raise RobotLogError(str(exc)) from exc
        return saved.robot_logs["sources"]

    def open_file(self, source_id: str, file_id: str) -> RobotLogFile:
        if not isinstance(file_id, str) or len(file_id) != 24:
            raise RobotLogError("日志文件不存在")
        for path, metadata in self._direct_regular_files(source_id):
            record = self._record(source_id, path, metadata)
            if record["id"] != file_id:
                continue
            try:
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                stream = os.fdopen(descriptor, "rb")
            except OSError as exc:
                raise RobotLogError("日志文件无法读取") from exc
            try:
                current = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(current.st_mode)
                    or current.st_dev != metadata.st_dev
                    or current.st_ino != metadata.st_ino
                    or current.st_size > self.MAX_FILE_BYTES
                ):
                    raise RobotLogError("日志文件已变化，无法安全下载")
                return RobotLogFile(name=path.name, size_bytes=current.st_size, stream=stream)
            except Exception:
                stream.close()
                raise
        raise RobotLogError("日志文件已变化或不存在")

    def _direct_regular_files(self, source_id: str) -> list[tuple[Path, os.stat_result]]:
        source = self._source(source_id)
        root = Path(source["path"])
        try:
            root = root.resolve(strict=True)
        except FileNotFoundError as exc:
            raise RobotLogError("日志目录不存在") from exc
        except OSError as exc:
            raise RobotLogError("日志目录不可读取") from exc
        if not root.is_dir():
            raise RobotLogError("日志目录不可读取")
        try:
            children = list(root.iterdir())
        except OSError as exc:
            raise RobotLogError("日志目录不可读取") from exc
        records: list[tuple[Path, os.stat_result]] = []
        for child in children:
            try:
                metadata = child.lstat()
                resolved = child.resolve(strict=True)
            except OSError:
                continue
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                continue
            if not resolved.is_relative_to(root):
                continue
            records.append((child, metadata))
        return records

    def _source(self, source_id: str) -> dict[str, str]:
        if not isinstance(source_id, str):
            raise RobotLogError("日志目录不存在")
        sources = self._settings.load().robot_logs["sources"]
        source = next((item for item in sources if item["id"] == source_id), None)
        if source is None:
            raise RobotLogError("日志目录不存在")
        return source

    @staticmethod
    def _new_source_id(existing: set[str]) -> str:
        while True:
            source_id = f"log_{secrets.token_hex(6)}"
            if source_id not in existing:
                return source_id

    @staticmethod
    def _record(source_id: str, path: Path, metadata: os.stat_result) -> dict[str, Any]:
        # 日志追加会自然更新 mtime/ctime；把它们放进 opaque ID 会让操作者
        # 刚选择文件就无法下载。dev + inode 才是本机同一文件的稳定身份，
        # 删除后重建/轮转会得到新的 inode，并继续被 open_file() 拒绝。
        digest = hashlib.blake2s(
            (
                f"{source_id}\0{path.name}\0{metadata.st_dev}\0{metadata.st_ino}"
            ).encode("utf-8"),
            digest_size=12,
        ).hexdigest()
        return {
            "id": digest,
            "name": path.name,
            "size_bytes": metadata.st_size,
            "modified_at": int(metadata.st_mtime),
        }
