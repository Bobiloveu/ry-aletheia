from __future__ import annotations

import json
import errno
import logging
import hashlib
import os
import stat
import threading
import time
from collections.abc import Iterable
from contextlib import contextmanager, ExitStack
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .tool_audit import CONTEXT_FIELDS, REQUEST_CONTEXT, safe_message

try:
    import fcntl
except ImportError:  # Desktop development on Windows; robot runtime is Linux.
    fcntl = None


class ToolLogConflict(ValueError):
    """The selected file changed or has an active download lease."""


class ToolLogMissing(ValueError):
    """The requested owned diagnostic file no longer exists."""


class _ManagedRotatingHandler(RotatingFileHandler):
    def __init__(self, store, filename, **kwargs):
        self.store = store
        super().__init__(filename, **kwargs)
        self.lock = store._lock

    def _open(self):
        descriptor = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0), 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError('日志文件无效')
        return os.fdopen(descriptor, 'a', encoding=self.encoding, errors=self.errors)

    def doRollover(self):
        name = Path(self.baseFilename).name
        with self.store._lock, self.store._mutation(name), self.store._family_lease(name, exclusive=True) as available:
            if available:
                super().doRollover()

    def emit(self, record):
        name = Path(self.baseFilename).name
        try:
            with self.store._lock, self.store._mutation(name):
                # A second Python process may have rotated this family's file.
                # Reopen before both size inspection and the next append.
                if self.stream:
                    opened = os.fstat(self.stream.fileno())
                    current = self.store._regular_stat(name)
                    if current is None or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                        self.stream.close()
                        self.stream = self._open()
                super().emit(record)
        except Exception:
            self.handleError(record)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "source": record.name.removeprefix("ry_aletheia."),
            "message": safe_message(record.getMessage(), limit=4000),
        }
        if record.exc_info:
            payload["exception"] = safe_message(self.formatException(record.exc_info), limit=16000)
        context = REQUEST_CONTEXT.get()
        for key in CONTEXT_FIELDS:
            value = getattr(record, key, context.get(key))
            if isinstance(value, str):
                payload[key] = safe_message(value, limit=480)
            elif not isinstance(value, bool) and isinstance(value, (int, float)):
                payload[key] = value
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
        "video-runtime.log": ("视频运行时", "MediaMTX、图像输入、VAAPI / NVENC 与 GStreamer 的原始输出"),
    }
    _MAX_BYTES = 2 * 1024 * 1024
    _BACKUP_COUNT = 3

    DEFAULT_POLICY = {'retention_days': 7, 'max_total_mib': 256, 'max_file_mib': 16}

    def __init__(self, directory: Path, *, policy_path: Path | None = None) -> None:
        self.directory = directory
        self.policy_path = policy_path or directory.parent / 'config' / 'tool_logging.json'
        self._lock = threading.RLock()
        self._leases: dict[str, int] = {}
        self._mutations = threading.local()
        self._policy = dict(self.DEFAULT_POLICY)
        self._policy_valid = True
        self._last_error: str | None = None
        self._last_cleanup_at: int | None = None
        self._maintenance_stop = threading.Event()
        self._maintenance_thread: threading.Thread | None = None
        if self.policy_path.exists():
            try:
                if self.policy_path.is_symlink() or self.policy_path.stat().st_size > 4096:
                    raise ValueError('日志策略文件无效')
                self._policy = self._validate_policy(json.loads(self.policy_path.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                self._policy_valid = False
                self._last_error = '日志保留设置不可读，自动整理已暂停；请重新保存设置。'

    def configure(self) -> logging.Logger:
        self.directory.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("ry_aletheia")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if any(getattr(handler, "_ry_aletheia_log", False) for handler in logger.handlers):
            return logger
        formatter = _JsonFormatter()
        normal = _ManagedRotatingHandler(self, self.directory / self.NORMAL_NAME, encoding="utf-8", maxBytes=self._MAX_BYTES, backupCount=self._BACKUP_COUNT)
        normal.setLevel(logging.INFO)
        normal.setFormatter(formatter)
        normal._ry_aletheia_log = True  # type: ignore[attr-defined]
        errors = _ManagedRotatingHandler(self, self.directory / self.ERROR_NAME, encoding="utf-8", maxBytes=self._MAX_BYTES, backupCount=self._BACKUP_COUNT)
        errors.setLevel(logging.ERROR)
        errors.setFormatter(formatter)
        errors._ry_aletheia_log = True  # type: ignore[attr-defined]
        logger.addHandler(normal)
        logger.addHandler(errors)
        return logger

    def entries(self, errors_only: bool = False, limit: int = 200) -> list[dict]:
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
        items: list[dict] = []
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
                for key in CONTEXT_FIELDS:
                    value = item.get(key)
                    if isinstance(value, str) or not isinstance(value, bool) and isinstance(value, (int, float)):
                        entry[key] = value
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
        for name in self._DIAGNOSTIC_LABELS:
            candidates.append(self.directory / name)
            candidates.extend(self.directory / f"{name}.{index}" for index in range(1, self._BACKUP_COUNT + 1))
        return [path for path in candidates if self._regular_stat(path.name) is not None]

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
                metadata = self._regular_stat(path.name)
                if metadata is None:
                    continue
            except OSError:
                continue
            records.append({
                "name": path.name,
                "label": label,
                "detail": detail,
                "size_bytes": metadata.st_size,
                "modified_at": int(metadata.st_mtime),
                "kind": "current" if path.name in self._DIAGNOSTIC_LABELS else "archive",
                "file_id": self._file_id(path.name, metadata),
                "can_clear": path.name in self._DIAGNOSTIC_LABELS,
                "can_delete": path.name not in self._DIAGNOSTIC_LABELS,
            })
        return records

    def diagnostic_file(self, name: str) -> Path | None:
        """Resolve a user-requested download through the fixed diagnostics list."""

        if not isinstance(name, str):
            return None
        return next((path for path in self.diagnostic_files() if path.name == name), None)

    @classmethod
    def _base_name(cls, name: str) -> str:
        if not isinstance(name, str):
            raise ValueError('日志文件名无效')
        if name in cls._DIAGNOSTIC_LABELS:
            return name
        base, _, suffix = name.rpartition('.')
        if base in cls._DIAGNOSTIC_LABELS and suffix in {'1', '2', '3'}:
            return base
        raise ValueError('日志文件名无效')

    def _regular_stat(self, name: str):
        self._base_name(name)
        try:
            metadata = (self.directory / name).lstat()
            return metadata if stat.S_ISREG(metadata.st_mode) else None
        except FileNotFoundError:
            return None

    @staticmethod
    def _file_id(name: str, metadata) -> str:
        # Current logs change size/mtime on every append; their inode identifies
        # the selected stream. Archives additionally include their stable mtime.
        value = f'{name}:{metadata.st_dev}:{metadata.st_ino}'
        if name.rsplit('.', 1)[-1].isdigit():
            value += f':{metadata.st_mtime_ns}'
        return hashlib.sha256(value.encode()).hexdigest()[:24]

    def _family_busy(self, base: str) -> bool:
        return any(count and self._base_name(name) == base for name, count in self._leases.items())

    def _lock_descriptor(self, base: str, kind: str):
        path = self.directory / f'.{base}.{kind}.lock'
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0), 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError('日志锁文件无效')
        return descriptor

    @contextmanager
    def _mutation(self, name: str):
        base = self._base_name(name)
        held = getattr(self._mutations, 'held', None)
        if held is None:
            held = self._mutations.held = set()
        if base in held or fcntl is None:
            yield
            return
        descriptor = self._lock_descriptor(base, 'write')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            held.add(base)
            try:
                yield
            finally:
                held.remove(base)
        finally:
            os.close(descriptor)

    @contextmanager
    def _family_lease(self, name: str, *, exclusive: bool):
        base = self._base_name(name)
        if fcntl is None:
            yield not exclusive or not self._family_busy(base)
            return
        descriptor = self._lock_descriptor(base, 'lease')
        try:
            try:
                fcntl.flock(descriptor, (fcntl.LOCK_EX | fcntl.LOCK_NB) if exclusive else fcntl.LOCK_SH)
            except BlockingIOError:
                yield False
            else:
                yield True
        finally:
            os.close(descriptor)

    def _open_regular(self, name: str, *, writable=False):
        self._base_name(name)
        flags = (os.O_RDWR if writable else os.O_RDONLY) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        try:
            descriptor = os.open(self.directory / name, flags)
        except FileNotFoundError as exc:
            raise ToolLogMissing('日志文件不存在，请刷新后重试') from exc
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise ValueError('日志文件不可访问') from exc
            raise
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError('日志文件无效')
        return os.fdopen(descriptor, 'r+b' if writable else 'rb', buffering=0)

    @contextmanager
    def open_diagnostic(self, name: str):
        with ExitStack() as ownership:
            with self._lock, self._mutation(name):
                ownership.enter_context(self._family_lease(name, exclusive=False))
                stream = ownership.enter_context(self._open_regular(name))
                size = os.fstat(stream.fileno()).st_size
                self._leases[name] = self._leases.get(name, 0) + 1
            try:
                yield stream, size
            finally:
                with self._lock:
                    self._leases[name] -= 1
                    if not self._leases[name]:
                        del self._leases[name]

    @classmethod
    def _validate_policy(cls, policy):
        if not isinstance(policy, dict) or set(policy) != set(cls.DEFAULT_POLICY):
            raise ValueError('日志保留设置格式无效')
        bounds = {'retention_days': (1, 365), 'max_total_mib': (128, 4096), 'max_file_mib': (2, 32)}
        for key, (minimum, maximum) in bounds.items():
            value = policy[key]
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError('日志保留设置超出允许范围')
        if policy['max_total_mib'] < policy['max_file_mib'] * 6:
            raise ValueError('总容量至少应为六个单文件容量')
        return dict(policy)

    def save_policy(self, policy):
        validated = self._validate_policy(policy)
        with self._lock:
            self.policy_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.policy_path.with_suffix('.json.tmp')
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            try:
                with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                    json.dump(validated, output)
                    output.flush()
                    os.fsync(output.fileno())
                temporary.replace(self.policy_path)
            finally:
                temporary.unlink(missing_ok=True)
            self._policy = validated
            self._policy_valid = True
            self._last_error = None

    def storage_status(self):
        with self._lock:
            return {'total_size_bytes': sum(metadata.st_size for p in self.diagnostic_files() if (metadata := self._regular_stat(p.name)) is not None),
                    'limit_bytes': self._policy['max_total_mib'] * 1024 * 1024,
                    'policy': dict(self._policy), 'last_cleanup_at': self._last_cleanup_at,
                    'last_error': self._last_error}

    def _check_selected(self, name: str, file_id: str):
        metadata = self._regular_stat(name)
        if metadata is None:
            raise ToolLogMissing('日志文件不存在，请刷新后重试')
        if not isinstance(file_id, str) or file_id != self._file_id(name, metadata):
            raise ToolLogConflict('日志文件已更新，请刷新后重试')
        if self._leases.get(name):
            raise ToolLogConflict('日志正在下载，请完成下载后重试')
        return metadata

    def clear_file(self, name: str, file_id: str):
        with self._lock, self._mutation(name), self._family_lease(name, exclusive=True) as available:
            if not available:
                raise ToolLogConflict('该类日志正在下载，请完成下载后重试')
            self._check_selected(name, file_id)
            if name not in self._DIAGNOSTIC_LABELS:
                raise ValueError('历史日志请使用删除操作')
            with self._open_regular(name, writable=True) as output:
                if self._file_id(name, os.fstat(output.fileno())) != file_id:
                    raise ToolLogConflict('日志文件已更新，请刷新后重试')
                size = os.fstat(output.fileno()).st_size
                output.truncate(0)
            return {'cleared': True, 'freed_bytes': size}

    def delete_file(self, name: str, file_id: str):
        with self._lock, self._mutation(name), self._family_lease(name, exclusive=True) as available:
            if not available:
                raise ToolLogConflict('该类日志正在下载，请完成下载后重试')
            metadata = self._check_selected(name, file_id)
            if name in self._DIAGNOSTIC_LABELS:
                raise ValueError('当前日志只能清空，不能删除')
            (self.directory / name).unlink()
            return {'deleted': True, 'freed_bytes': metadata.st_size}

    def _rotate_sidecar(self, name: str, maximum: int):
        staging = self.directory / f'.{name}.rotating'
        if staging.exists():
            if staging.is_symlink() or not staging.is_file():
                raise ValueError('日志轮转暂存文件无效')
            staging.unlink()
        try:
            with self._open_regular(name, writable=True) as source:
                metadata = os.fstat(source.fileno())
                source.seek(max(0, metadata.st_size - maximum))
                remaining = min(maximum, metadata.st_size)
                with staging.open('xb') as output:
                    while remaining:
                        chunk = source.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        output.write(chunk)
                        remaining -= len(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                os.utime(staging, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                for index in range(self._BACKUP_COUNT, 0, -1):
                    archive = self.directory / f'{name}.{index}'
                    if archive.is_symlink():
                        raise ValueError('日志历史文件无效')
                    if index == self._BACKUP_COUNT:
                        archive.unlink(missing_ok=True)
                    elif archive.exists():
                        archive.replace(self.directory / f'{name}.{index + 1}')
                staging.replace(self.directory / f'{name}.1')
                # Never unlink/replace a file held by native O_APPEND writers.
                # Raw output is a best-effort snapshot: concurrent writes in
                # the small copy/truncate interval can be lost. Business/error
                # JSONL handlers keep their independent locked rotation.
                source.truncate(0)
        finally:
            staging.unlink(missing_ok=True)

    def cleanup(self, *, history=False):
        with self._lock:
            if not self._policy_valid:
                raise ValueError(self._last_error)
            before = self.storage_status()['total_size_bytes']
            rotated = removed = skipped = 0
            maximum = self._policy['max_file_mib'] * 1024 * 1024
            for name in (() if history else self.SIDECAR_NAMES):
                with self._mutation(name), self._family_lease(name, exclusive=True) as available:
                    metadata = self._regular_stat(name)
                    if metadata and metadata.st_size > maximum:
                        if not available:
                            skipped += 1
                        else:
                            self._rotate_sidecar(name, maximum)
                            rotated += 1
            cutoff = time.time() - self._policy['retention_days'] * 86400
            archives = sorted(((p, metadata.st_mtime) for p in self.diagnostic_files()
                               if p.name not in self._DIAGNOSTIC_LABELS
                               and (metadata := self._regular_stat(p.name)) is not None), key=lambda item: item[1])
            total = self.storage_status()['total_size_bytes']
            for path, _ in archives:
                with self._mutation(path.name), self._family_lease(path.name, exclusive=True) as available:
                    metadata = self._regular_stat(path.name)
                    if metadata and (history or metadata.st_mtime < cutoff or total > self._policy['max_total_mib'] * 1024 * 1024):
                        if not available:
                            skipped += 1
                        else:
                            path.unlink()
                            total -= metadata.st_size
                            removed += 1
            self._last_cleanup_at = int(time.time())
            self._last_error = None
            after = self.storage_status()['total_size_bytes']
            result = {'removed_count': removed, 'rotated_count': rotated,
                      'skipped_count': skipped, 'freed_bytes': max(0, before - after)}
        if rotated or removed:
            logging.getLogger('ry_aletheia.tool_logging').info('工具日志整理完成：rotated=%s removed=%s freed_bytes=%s', rotated, removed, result['freed_bytes'])
        return result

    def start_maintenance(self, *, interval=5.0):
        with self._lock:
            if self._maintenance_thread and self._maintenance_thread.is_alive():
                return
            self._maintenance_stop.clear()
            def maintain():
                while not self._maintenance_stop.is_set():
                    try:
                        self.cleanup()
                    except (OSError, ValueError):
                        with self._lock:
                            previous = self._last_error
                            self._last_error = self._last_error or '日志自动整理失败，请检查目录权限或剩余空间。'
                        if previous is None:
                            logging.getLogger('ry_aletheia.tool_logging').warning(self._last_error)
                    self._maintenance_stop.wait(interval)
            self._maintenance_thread = threading.Thread(target=maintain, name='tool-log-maintenance', daemon=True)
            self._maintenance_thread.start()

    def stop_maintenance(self):
        self._maintenance_stop.set()
        thread = self._maintenance_thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
