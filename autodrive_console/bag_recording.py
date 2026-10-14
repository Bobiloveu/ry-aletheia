"""Controlled, auditable ROS 2 diagnostic bag recording.

This module intentionally owns the ROS recording subprocess boundary.  HTTP
callers only provide a selected attempt and discovered topic names; they never
provide a command, an output path, compression flags, or ROS environment.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
from typing import Callable, Mapping
import uuid

LOGGER = logging.getLogger("ry_aletheia.bag_recording")


class BagRecordingError(RuntimeError):
    """A diagnostic capture cannot safely be started or managed."""


@dataclass(frozen=True)
class RecordingRequest:
    """One operator-selected capture target within a normal test run."""

    attempt_index: int
    topics: tuple[str, ...]


@dataclass(frozen=True)
class RecordingEnvironment:
    """Minimal, non-secret ROS environment fingerprint used by one capture."""

    ros_distro: str
    ros2_path: str
    ament_prefix_path: str
    rmw_implementation: str
    ros_domain_id: str

    def to_manifest(self) -> dict[str, str]:
        return {
            "ros_distro": self.ros_distro,
            "ros2_path": self.ros2_path,
            "ament_prefix_path": self.ament_prefix_path,
            "rmw_implementation": self.rmw_implementation,
            "ros_domain_id": self.ros_domain_id,
        }


@dataclass
class ActiveRecording:
    """Resources owned by one in-progress recorder process."""

    archive_id: str
    display_name: str
    run_id: str
    case_name: str
    attempt_index: int | None
    request: RecordingRequest
    topic_types: dict[str, str]
    environment: RecordingEnvironment
    stage_dir: Path
    bag_dir: Path
    process: object
    counter: object
    log_handle: object
    started_at: str
    source: str = "test_attempt"
    label: str = ""
    duration_limit_seconds: int | None = None


class _RclpyTopicCounter:
    """One isolated, receive-only counter for the selected DDS Topics."""

    def __init__(self, topic_types: dict[str, str]) -> None:
        self._topic_types = dict(topic_types)
        self._counts = {topic: 0 for topic in topic_types}
        self._error = ""
        self._context = None
        self._node = None
        self._executor = None
        self._thread = None
        self._lock = threading.Lock()

    def start(self) -> None:
        try:
            import rclpy
            from rclpy.context import Context
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.node import Node
            from rclpy.qos import QoSProfile, ReliabilityPolicy
            from rosidl_runtime_py.utilities import get_message

            context = Context()
            rclpy.init(context=context)
            node = Node("ry_aletheia_bag_audit_counter", context=context)
            qos = QoSProfile(depth=1000, reliability=ReliabilityPolicy.BEST_EFFORT)
            for topic, message_type in self._topic_types.items():
                message_class = get_message(message_type)

                def received(_message: object, *, _topic: str = topic) -> None:
                    with self._lock:
                        self._counts[_topic] += 1

                node.create_subscription(message_class, topic, received, qos)
            executor = SingleThreadedExecutor(context=context)
            executor.add_node(node)
            thread = threading.Thread(target=self._spin, args=(executor,), daemon=True, name="bag-recording-counter")
            self._context, self._node, self._executor, self._thread = context, node, executor, thread
            thread.start()
        except Exception as exc:
            LOGGER.exception("Bag counter startup failed topics=%d", len(self._topic_types))
            self.stop()
            raise BagRecordingError(f"诊断录包计数器无法启动：{exc}") from exc

    def _spin(self, executor: object) -> None:
        try:
            executor.spin()
        except Exception:
            LOGGER.exception("Bag counter executor failed topics=%d", len(self._topic_types))
            raise

    def reset(self) -> None:
        with self._lock:
            self._counts = {topic: 0 for topic in self._topic_types}

    def snapshot(self) -> tuple[dict[str, int], str]:
        with self._lock:
            return dict(self._counts), self._error

    def stop(self) -> None:
        executor, node, context, thread = self._executor, self._node, self._context, self._thread
        self._executor = self._node = self._context = self._thread = None
        if executor is not None:
            try:
                executor.shutdown(timeout_sec=2)
            except Exception:
                LOGGER.warning("Bag counter executor shutdown failed", exc_info=True)
                pass
        if node is not None:
            try:
                node.destroy_node()
            except Exception:
                LOGGER.warning("Bag counter node cleanup failed", exc_info=True)
                pass
        if context is not None:
            try:
                import rclpy
                if context.ok():
                    rclpy.shutdown(context=context)
            except Exception:
                LOGGER.warning("Bag counter ROS context cleanup failed", exc_info=True)
                pass
        if thread is not None:
            thread.join(timeout=2)


class BagRecordingManager:
    """Validate operator selections before a recorder lifecycle is created."""

    MAX_TOPICS = 32
    _TOPIC_NAME = re.compile(r"/(?:[A-Za-z][A-Za-z0-9_]*)(?:/[A-Za-z][A-Za-z0-9_]*)*\Z")
    _SHARED_MEMORY_ONLY_TYPES = frozenset({
        "sensor_msgs/msg/Image",
        "sensor_msgs/msg/CompressedImage",
        "sensor_msgs/msg/CameraInfo",
        "stereo_msgs/msg/DisparityImage",
        "sensor_msgs/msg/PointCloud",
        "sensor_msgs/msg/PointCloud2",
        "sensor_msgs/msg/LaserScan",
    })

    def __init__(
        self,
        root: Path,
        *,
        topic_probe: Callable[[], list[dict[str, object]]] | None = None,
        environment: Mapping[str, str] | None = None,
        environment_verifier: Callable[[], RecordingEnvironment] | None = None,
        popen: Callable[..., object] | None = None,
        counter_factory: Callable[[dict[str, str]], object] | None = None,
        metadata_reader: Callable[[Path], dict[str, object]] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self._topic_probe = topic_probe or self._ros_topic_probe
        self._environment = dict(os.environ if environment is None else environment)
        self._environment_verifier = environment_verifier or self.verify_environment
        self._popen = popen or subprocess.Popen
        self._counter_factory = counter_factory or _RclpyTopicCounter
        self._metadata_reader = metadata_reader or self._read_metadata
        self._sleep = sleeper or time.sleep
        self._active: dict[str, ActiveRecording] = {}
        self._lock = threading.RLock()
        self._starting = False
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".staging").mkdir(exist_ok=True)
        self._recover_staging()

    def available_topics(self) -> list[dict[str, object]]:
        """Return only Topics which can be selected and subsequently audited."""
        try:
            raw_topics = self._topic_probe()
        except BagRecordingError:
            raise
        except Exception as exc:
            raise BagRecordingError(f"无法读取当前 ROS Topic：{exc}") from exc
        if not isinstance(raw_topics, list):
            raise BagRecordingError("当前 ROS Topic 查询结果无效")
        result: list[dict[str, object]] = []
        for item in raw_topics:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            message_type = item.get("type")
            types = item.get("types", [message_type])
            publisher_count = item.get("publisher_count")
            if (
                not isinstance(name, str)
                or not self._TOPIC_NAME.fullmatch(name)
                or bool(item.get("hidden"))
                or not isinstance(message_type, str)
                or not message_type
                or not isinstance(types, list)
                or len(types) != 1
                or types[0] != message_type
                or self._is_shared_memory_only_type(message_type)
                or isinstance(publisher_count, bool)
                or not isinstance(publisher_count, int)
                or publisher_count < 1
            ):
                continue
            result.append({"name": name, "type": message_type, "publisher_count": publisher_count})
        return sorted(result, key=lambda item: str(item["name"]))

    @classmethod
    def _is_shared_memory_only_type(cls, message_type: str) -> bool:
        """Never offer streams migrated to ShmSDK rather than DDS."""
        return message_type in cls._SHARED_MEMORY_ONLY_TYPES or message_type.endswith("/Image") or "PointCloud" in message_type

    def validate_request(self, request: object, count: int) -> RecordingRequest | None:
        """Validate an optional request against this instant's visible graph."""
        if request is None:
            return None
        if not isinstance(request, dict) or set(request) != {"attemptIndex", "topics"}:
            raise BagRecordingError("诊断录包请求字段无效")
        attempt_index = request.get("attemptIndex")
        topics = request.get("topics")
        if isinstance(attempt_index, bool) or not isinstance(attempt_index, int) or not 1 <= attempt_index <= count:
            raise BagRecordingError("诊断录包目标轮次无效")
        if not isinstance(topics, list) or not 1 <= len(topics) <= self.MAX_TOPICS or not all(isinstance(topic, str) for topic in topics):
            raise BagRecordingError(f"请选择 1 至 {self.MAX_TOPICS} 个 Topic")
        if len(set(topics)) != len(topics):
            raise BagRecordingError("诊断录包 Topic 不能重复")
        available = {str(item["name"]): str(item["type"]) for item in self.available_topics()}
        unavailable = [topic for topic in topics if topic not in available]
        if unavailable:
            raise BagRecordingError(f"当前不可录制 Topic：{', '.join(unavailable)}")
        return RecordingRequest(attempt_index, tuple(topics))

    def verify_environment(self) -> RecordingEnvironment:
        """Return the exact inherited ROS environment or reject the capture."""
        ros_distro = self._environment.get("ROS_DISTRO", "")
        ament_prefix_path = self._environment.get("AMENT_PREFIX_PATH", "")
        ros2_path = shutil.which("ros2", path=self._environment.get("PATH", ""))
        if ros_distro != "humble":
            raise BagRecordingError("ROS 环境无效：需要 ROS_DISTRO=humble")
        prefixes = {Path(value).resolve() for value in ament_prefix_path.split(os.pathsep) if value}
        if Path("/opt/ros/humble") not in prefixes:
            raise BagRecordingError("ROS 环境无效：AMENT_PREFIX_PATH 缺少 /opt/ros/humble")
        if not ros2_path or not os.access(ros2_path, os.X_OK):
            raise BagRecordingError("ROS 环境无效：PATH 中没有可执行的 ros2")
        return RecordingEnvironment(
            ros_distro=ros_distro,
            ros2_path=str(Path(ros2_path).resolve()),
            ament_prefix_path=ament_prefix_path,
            rmw_implementation=self._environment.get("RMW_IMPLEMENTATION", ""),
            ros_domain_id=self._environment.get("ROS_DOMAIN_ID", ""),
        )

    def start(
        self,
        run_id: str,
        case_name: str,
        attempt_index: int,
        request: RecordingRequest,
    ) -> ActiveRecording:
        """Start an owned recorder only after every capture precondition holds."""
        if attempt_index != request.attempt_index:
            raise BagRecordingError("诊断录包目标轮次与当前执行轮次不一致")
        return self._start(
            run_id, case_name, attempt_index, request,
            source="test_attempt", label="", duration_limit_seconds=None,
        )

    def start_manual(self, request: object) -> ActiveRecording:
        """Start a user-owned scene capture through the normal recorder boundary."""
        topics = getattr(request, "topics", None)
        duration_minutes = getattr(request, "duration_minutes", None)
        label = getattr(request, "label", "")
        if (
            not isinstance(topics, tuple)
            or not topics
            or not all(isinstance(topic, str) for topic in topics)
            or len(topics) > self.MAX_TOPICS
            or len(set(topics)) != len(topics)
            or isinstance(duration_minutes, bool)
            or duration_minutes not in {5, 10, 15, 20}
            or not isinstance(label, str)
        ):
            raise BagRecordingError("手动录制请求无效")
        return self._start(
            "manual", label or "手动场景", None, RecordingRequest(0, topics),
            source="manual", label=label, duration_limit_seconds=duration_minutes * 60,
        )

    def _start(
        self,
        run_id: str,
        case_name: str,
        attempt_index: int | None,
        request: RecordingRequest,
        *,
        source: str,
        label: str,
        duration_limit_seconds: int | None,
    ) -> ActiveRecording:
        """Start a recorder with a validated, Backend-owned capture context."""
        # Both manual and test-attempt capture reach this boundary.  Reserve
        # it before graph/environment checks so a near-simultaneous request
        # cannot start a second rosbag process in the validation window.
        with self._lock:
            if self._active or self._starting:
                raise BagRecordingError("已有诊断录包正在准备、录制或归档")
            self._starting = True
        counter = None
        log_handle = None
        stage_dir = None
        try:
            LOGGER.info("Bag recording starting run=%s attempt=%s source=%s topics=%d",
                        run_id, attempt_index, source, len(request.topics))
            topic_types = self._current_topic_types(request.topics)
            environment = self._environment_verifier()
            archive_id = uuid.uuid4().hex
            display_name = self._display_name(case_name, attempt_index, archive_id, source=source)
            stage_dir = (self.root / ".staging" / archive_id).resolve()
            if stage_dir.parent != (self.root / ".staging").resolve():
                raise BagRecordingError("诊断录包暂存目录无效")
            bag_dir = stage_dir / "bag"
            stage_dir.mkdir(parents=True, exist_ok=False)
            # rosbag2 rejects an existing --output path.  Only the enclosing
            # staging directory belongs to us; the recorder creates ``bag``.
            counter = self._counter_factory(topic_types)
            counter.start()
            log_handle = (stage_dir / "recorder.log").open("ab", buffering=0)
            argv = self._recorder_argv(environment, bag_dir, request.topics)
            process = self._popen(
                argv,
                cwd=str(self.root),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                shell=False,
                start_new_session=True,
                close_fds=True,
                env=dict(self._environment),
            )
            # The selected task must never be dispatched while the recorder is
            # already dead.  The short grace also lets its subscriptions begin
            # before monitor counts are reset to the comparable interval.
            self._sleep(0.25)
            if process.poll() is not None:
                raise BagRecordingError(f"诊断录包进程启动后立即退出（退出码 {process.poll()}）")
            counter.reset()
            active = ActiveRecording(
                archive_id=archive_id,
                display_name=display_name,
                run_id=run_id,
                case_name=case_name,
                attempt_index=attempt_index,
                request=request,
                topic_types=topic_types,
                environment=environment,
                stage_dir=stage_dir,
                bag_dir=bag_dir,
                process=process,
                counter=counter,
                log_handle=log_handle,
                started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                source=source,
                label=label,
                duration_limit_seconds=duration_limit_seconds,
            )
            with self._lock:
                self._active[archive_id] = active
            LOGGER.info("Bag recording started archive=%s run=%s attempt=%s source=%s topics=%d",
                        archive_id, run_id, attempt_index, source, len(request.topics))
            return active
        except Exception as exc:
            LOGGER.log(logging.WARNING if isinstance(exc, BagRecordingError) else logging.ERROR,
                       "Bag recording start failed run=%s attempt=%s source=%s reason=%s",
                       run_id, attempt_index, source, type(exc).__name__,
                       exc_info=not isinstance(exc, BagRecordingError))
            if log_handle is not None:
                log_handle.close()
            if counter is not None:
                try:
                    counter.stop()
                except Exception:
                    pass
            if stage_dir is not None:
                shutil.rmtree(stage_dir, ignore_errors=True)
            if isinstance(exc, BagRecordingError):
                raise
            raise BagRecordingError(f"无法启动诊断录包：{exc}") from exc
        finally:
            with self._lock:
                self._starting = False

    def stop(self, active: ActiveRecording) -> dict[str, object]:
        """Stop an owned recorder, audit its output, and atomically archive it."""
        with self._lock:
            if self._active.get(active.archive_id) is not active:
                raise BagRecordingError("诊断录包会话不存在或已结束")
        errors: list[str] = []
        LOGGER.info("Bag recording finalizing archive=%s run=%s attempt=%s", active.archive_id, active.run_id, active.attempt_index)
        try:
            returncode = self._stop_process(active.process)
        except Exception as exc:
            LOGGER.exception("Bag recorder stop failed archive=%s", active.archive_id)
            returncode = None
            errors.append(f"recorder 停止失败：{exc}")
        try:
            counts, counter_error = active.counter.snapshot()
        except Exception as exc:
            LOGGER.exception("Bag counter snapshot failed archive=%s", active.archive_id)
            counts, counter_error = {}, f"计数器读取失败：{exc}"
        try:
            active.counter.stop()
        except Exception as exc:
            LOGGER.exception("Bag counter stop failed archive=%s", active.archive_id)
            errors.append(f"计数器停止失败：{exc}")
        try:
            active.log_handle.close()
        except Exception:
            pass
        if returncode not in (0, None):
            errors.append(f"recorder 非正常退出（退出码 {returncode}）")
        try:
            audit = self._audit(active, counts, str(counter_error or ""), errors)
            manifest = self._manifest(active, audit)
            final_dir = self._finalize(active, manifest)
        except Exception:
            LOGGER.exception("Bag recording finalization failed archive=%s run=%s attempt=%s",
                             active.archive_id, active.run_id, active.attempt_index)
            raise
        with self._lock:
            self._active.pop(active.archive_id, None)
        LOGGER.log(logging.INFO if audit['status'] == 'passed' else logging.WARNING,
                   "Bag recording finalized archive=%s run=%s attempt=%s audit=%s errors=%d exit_code=%s loss_rate_percent=%s",
                   active.archive_id, active.run_id, active.attempt_index, audit['status'],
                   len(audit['errors']), returncode, audit['loss_rate_percent'])
        return self._summary(manifest, final_dir)

    def list_archives(self) -> list[dict[str, object]]:
        """List only finalized, manifest-backed directories in descending time."""
        records: list[dict[str, object]] = []
        for directory, manifest in self._archive_manifests():
            records.append(self._summary(manifest, directory))
        return sorted(records, key=lambda item: str(item.get("started_at", "")), reverse=True)

    def archive_detail(self, archive_id: str) -> dict[str, object]:
        directory, manifest = self._archive_by_id(archive_id)
        return {"archive": self._summary(manifest, directory), "manifest": manifest}

    def archive_path(self, archive_id: str) -> Path:
        """Return a verified archive directory for the HTTP download boundary."""
        return self._archive_by_id(archive_id)[0]

    def delete_archive(self, archive_id: str) -> None:
        directory, manifest = self._archive_by_id(archive_id)
        with self._lock:
            if archive_id in self._active:
                raise BagRecordingError("正在录制的数据包不能删除")
        if directory.is_symlink() or directory.parent != self.root or manifest.get("archive_id") != archive_id:
            raise BagRecordingError("诊断数据包目录无效")
        shutil.rmtree(directory)
        LOGGER.info("Bag archive deleted archive=%s", archive_id)

    def _current_topic_types(self, topics: tuple[str, ...]) -> dict[str, str]:
        available = {str(item["name"]): str(item["type"]) for item in self.available_topics()}
        missing = [topic for topic in topics if topic not in available]
        if missing:
            raise BagRecordingError(f"目标轮开始前 Topic 已不可录制：{', '.join(missing)}")
        return {topic: available[topic] for topic in topics}

    @staticmethod
    def _recorder_argv(environment: RecordingEnvironment, bag_dir: Path, topics: tuple[str, ...]) -> list[str]:
        return [
            environment.ros2_path, "bag", "record", "--output", str(bag_dir),
            "--storage", "sqlite3", "--compression-mode", "file",
            "--compression-format", "zstd", "--compression-queue-size", "8",
            "--compression-threads", "2", "--max-cache-size", str(512 * 1024 * 1024),
            *topics,
        ]

    @staticmethod
    def _stop_process(process: object) -> int | None:
        poll = getattr(process, "poll")
        result = poll()
        if result is not None:
            return result
        try:
            os.killpg(process.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
        try:
            return process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return process.wait(timeout=3)

    def _audit(
        self,
        active: ActiveRecording,
        observed_counts: object,
        counter_error: str,
        inherited_errors: list[str],
    ) -> dict[str, object]:
        errors = list(inherited_errors)
        if counter_error:
            errors.append(f"计数器不可用：{counter_error}")
        metadata: dict[str, object] | None = None
        metadata_path = active.bag_dir / "metadata.yaml"
        if not metadata_path.is_file():
            errors.append("缺少 rosbag metadata.yaml，无法验证录包")
        else:
            try:
                metadata = self._metadata_reader(active.bag_dir)
            except Exception as exc:
                LOGGER.exception("Bag metadata read failed archive=%s", active.archive_id)
                errors.append(f"无法读取 rosbag 元数据：{exc}")
        if not isinstance(observed_counts, dict):
            observed_counts = {}
            errors.append("计数器结果无效")
        topic_results: dict[str, dict[str, object]] = {}
        total_observed = total_lost = 0
        if metadata is not None:
            if metadata.get("storage_identifier") != "sqlite3":
                errors.append("rosbag storage 不是 sqlite3")
            if (
                self._metadata_value(metadata.get("compression_mode")) != "file"
                or self._metadata_value(metadata.get("compression_format")) != "zstd"
            ):
                errors.append("rosbag 压缩 profile 不符合固定 Zstd file 策略")
            stored_topics = metadata.get("topics")
            if not isinstance(stored_topics, dict):
                errors.append("rosbag Topic 统计无效")
                stored_topics = {}
            for topic, message_type in active.topic_types.items():
                stored = stored_topics.get(topic)
                try:
                    recorded = int(stored.get("message_count")) if isinstance(stored, dict) else -1
                    stored_type = str(stored.get("type")) if isinstance(stored, dict) else ""
                    observed = int(observed_counts.get(topic, -1))
                except (TypeError, ValueError):
                    recorded, stored_type, observed = -1, "", -1
                if stored_type != message_type:
                    errors.append(f"Topic {topic} 类型或元数据缺失")
                if recorded <= 0:
                    errors.append(f"Topic {topic} 未写入有效消息")
                if observed < 0:
                    errors.append(f"Topic {topic} 缺少计数器结果")
                lost = max(0, observed - recorded) if observed >= 0 and recorded >= 0 else 0
                topic_results[topic] = {
                    "type": message_type,
                    "observed_count": observed,
                    "recorded_count": recorded,
                    "estimated_lost": lost,
                    "loss_rate_percent": round(lost / observed * 100, 3) if observed > 0 else 0.0,
                }
                if observed > 0:
                    total_observed += observed
                    total_lost += lost
        loss_rate = round(total_lost / total_observed * 100, 3) if total_observed else 0.0
        status = "failed" if errors else "passed" if loss_rate <= 1 else "warning" if loss_rate <= 5 else "failed"
        if status == "failed" and not errors and loss_rate > 5:
            errors.append(f"估算丢失率 {loss_rate}% 超过 5%")
        return {
            "status": status,
            "basis": "同窗口只读计数器接收数与 rosbag2 元数据写入数之差；不代表上游发布端的绝对无损证明。",
            "loss_rate_percent": loss_rate,
            "topics": topic_results,
            "errors": errors,
        }

    def _manifest(self, active: ActiveRecording, audit: dict[str, object]) -> dict[str, object]:
        files = self._file_hashes(active.stage_dir)
        finished_at = datetime.now().astimezone()
        try:
            started_at = datetime.fromisoformat(active.started_at)
            actual_duration_seconds = max(0, int((finished_at - started_at).total_seconds()))
        except (TypeError, ValueError):
            actual_duration_seconds = 0
        return {
            "schema_version": 1,
            "archive_id": active.archive_id,
            "display_name": active.display_name,
            "run_id": active.run_id,
            "case_name": active.case_name,
            "attempt_index": active.attempt_index,
            "source": active.source,
            "label": active.label,
            "duration_limit_seconds": active.duration_limit_seconds,
            "started_at": active.started_at,
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "actual_duration_seconds": actual_duration_seconds,
            "topics": audit["topics"],
            "recording_profile": {
                "storage": "sqlite3", "compression_mode": "file", "compression_format": "zstd",
                "compression_queue_size": 8, "compression_threads": 2, "max_cache_size_bytes": 512 * 1024 * 1024,
            },
            "environment": active.environment.to_manifest(),
            "audit": audit,
            "files": files,
            "total_size_bytes": sum(int(item["size_bytes"]) for item in files.values()),
        }

    def _finalize(self, active: ActiveRecording, manifest: dict[str, object]) -> Path:
        temporary = active.stage_dir / "manifest.json.tmp"
        final_manifest = active.stage_dir / "manifest.json"
        encoded = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, final_manifest)
        final_dir = (self.root / str(manifest["display_name"])).resolve()
        if final_dir.parent != self.root or final_dir.exists():
            raise BagRecordingError("诊断数据包最终目录无效或冲突")
        active.stage_dir.replace(final_dir)
        return final_dir

    @staticmethod
    def _file_hashes(root: Path) -> dict[str, dict[str, object]]:
        files: dict[str, dict[str, object]] = {}
        resolved_root = root.resolve()
        for candidate in sorted(root.rglob("*")):
            if candidate.is_symlink():
                raise BagRecordingError("诊断数据包中不能包含符号链接")
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if not resolved.is_relative_to(resolved_root):
                raise BagRecordingError("诊断数据包文件越出暂存目录")
            digest = hashlib.sha256()
            with candidate.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            files[str(candidate.relative_to(root))] = {"size_bytes": candidate.stat().st_size, "sha256": digest.hexdigest()}
        return files

    @staticmethod
    def _display_name(case_name: str, attempt_index: int | None, archive_id: str, *, source: str = "test_attempt") -> str:
        safe_case = re.sub(r"[^\w-]+", "_", case_name, flags=re.UNICODE).strip("_")[:32] or "case"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if source == "manual":
            return f"bag_{timestamp}_manual_{safe_case}_{archive_id}"
        return f"bag_{timestamp}_{safe_case}_T-{attempt_index:03d}_{archive_id}"

    def _archive_manifests(self) -> list[tuple[Path, dict[str, object]]]:
        found: list[tuple[Path, dict[str, object]]] = []
        if not self.root.is_dir():
            return found
        for directory in self.root.iterdir():
            if directory.name.startswith(".") or directory.is_symlink() or not directory.is_dir():
                continue
            resolved = directory.resolve()
            if resolved.parent != self.root:
                continue
            manifest_path = resolved / "manifest.json"
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and isinstance(data.get("archive_id"), str):
                found.append((resolved, data))
        return found

    def _archive_by_id(self, archive_id: str) -> tuple[Path, dict[str, object]]:
        if not re.fullmatch(r"[0-9a-f]{32}", archive_id):
            raise BagRecordingError("诊断数据包标识无效")
        for directory, manifest in self._archive_manifests():
            if manifest.get("archive_id") == archive_id:
                return directory, manifest
        raise BagRecordingError("诊断数据包不存在")

    @staticmethod
    def _summary(manifest: dict[str, object], directory: Path) -> dict[str, object]:
        audit = manifest.get("audit") if isinstance(manifest.get("audit"), dict) else {}
        return {
            "archive_id": manifest.get("archive_id"),
            "display_name": manifest.get("display_name"),
            "case_name": manifest.get("case_name"),
            "attempt_index": manifest.get("attempt_index"),
            "source": manifest.get("source", "test_attempt"),
            "label": manifest.get("label", ""),
            "duration_limit_seconds": manifest.get("duration_limit_seconds"),
            "actual_duration_seconds": manifest.get("actual_duration_seconds"),
            "started_at": manifest.get("started_at"),
            "finished_at": manifest.get("finished_at"),
            "total_size_bytes": manifest.get("total_size_bytes", 0),
            "compression": "Zstd（文件级）",
            "audit": audit,
            "audit_status": audit.get("status", "failed"),
            "directory": directory.name,
        }

    def _recover_staging(self) -> None:
        """Retain crash leftovers as explicitly incomplete evidence."""
        staging = self.root / ".staging"
        for candidate in staging.iterdir() if staging.is_dir() else ():
            if candidate.is_symlink() or not candidate.is_dir() or not re.fullmatch(r"[0-9a-f]{32}", candidate.name):
                continue
            archive_id = candidate.name
            manifest = {
                "schema_version": 1, "archive_id": archive_id,
                "display_name": f"bag_incomplete_{archive_id}", "case_name": "未完成录制",
                "attempt_index": None, "started_at": None,
                "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "topics": {}, "recording_profile": {}, "environment": {},
                "audit": {"status": "failed", "basis": "控制台启动恢复", "loss_rate_percent": 0.0, "topics": {}, "errors": ["录包进程或控制台异常终止，数据包未完成。"]},
                "files": self._file_hashes(candidate), "total_size_bytes": sum(item.stat().st_size for item in candidate.rglob("*") if item.is_file() and not item.is_symlink()),
            }
            temporary = candidate / "manifest.json.tmp"
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, candidate / "manifest.json")
            candidate.replace(self.root / str(manifest["display_name"]))
            LOGGER.warning("Bag incomplete archive recovered archive=%s audit=failed", archive_id)

    @staticmethod
    def _read_metadata(bag_dir: Path) -> dict[str, object]:
        try:
            from rosbag2_py import Info
        except Exception as exc:
            raise BagRecordingError(f"rosbag2 元数据读取不可用：{exc}") from exc
        metadata = Info().read_metadata(str(bag_dir), "sqlite3")
        topics: dict[str, dict[str, object]] = {}
        for item in metadata.topics_with_message_count:
            topics[str(item.topic_metadata.name)] = {
                "type": str(item.topic_metadata.type),
                "message_count": int(item.message_count),
            }
        return {
            "storage_identifier": str(metadata.storage_identifier),
            "compression_mode": BagRecordingManager._metadata_value(metadata.compression_mode),
            "compression_format": BagRecordingManager._metadata_value(metadata.compression_format),
            "topics": topics,
        }

    @staticmethod
    def _metadata_value(value: object) -> str:
        """Normalize rosbag2 enum fields across Humble bindings and YAML output."""

        named = getattr(value, "name", value)
        return str(named).strip().rsplit(".", 1)[-1].casefold()

    @staticmethod
    def _collect_topic_snapshots(
        snapshot: Callable[[], list[dict[str, object]]],
        *,
        samples: int = 9,
        sleep: Callable[[float], None] = time.sleep,
        interval_s: float = 0.25,
    ) -> list[dict[str, object]]:
        """Merge a short DDS-discovery window into one conservative graph view."""
        if samples < 1:
            raise ValueError("DDS 图采样次数必须大于零")
        records: dict[str, dict[str, object]] = {}
        for index in range(samples):
            for item in snapshot():
                if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                    continue
                name = item["name"]
                previous = records.setdefault(name, {
                    "name": name, "type": "", "types": [], "publisher_count": 0, "hidden": bool(item.get("hidden")),
                })
                previous["hidden"] = bool(previous["hidden"]) or bool(item.get("hidden"))
                value_types = item.get("types", [item.get("type")])
                if isinstance(value_types, (list, tuple)):
                    for message_type in value_types:
                        if isinstance(message_type, str) and message_type and message_type not in previous["types"]:
                            previous["types"].append(message_type)
                publisher_count = item.get("publisher_count")
                if isinstance(publisher_count, int) and not isinstance(publisher_count, bool):
                    previous["publisher_count"] = max(int(previous["publisher_count"]), publisher_count)
                types = previous["types"]
                previous["type"] = types[0] if len(types) == 1 else ""
            if index + 1 < samples:
                sleep(interval_s)
        return list(records.values())

    @staticmethod
    def _ros_topic_probe() -> list[dict[str, object]]:
        """Read one ROS graph snapshot using an isolated, read-only node."""
        try:
            import rclpy
            from rclpy.context import Context
            from rclpy.node import Node
            from rclpy.topic_or_service_is_hidden import topic_or_service_is_hidden
        except Exception as exc:
            raise BagRecordingError(f"ROS 2 图查询不可用：{exc}") from exc
        context = Context()
        node = None
        try:
            rclpy.init(context=context)
            node = Node("ry_aletheia_bag_topic_probe", context=context)

            def snapshot() -> list[dict[str, object]]:
                records: list[dict[str, object]] = []
                for name, types in node.get_topic_names_and_types():
                    names = list(types)
                    records.append({
                        "name": name,
                        "type": names[0] if len(names) == 1 else "",
                        "types": names,
                        "publisher_count": len(node.get_publishers_info_by_topic(name)),
                        "hidden": topic_or_service_is_hidden(name),
                    })
                return records

            # A freshly-created DDS participant can see an empty graph for a
            # short interval.  Keep the HTTP response bounded while letting
            # discovery settle, then retain the highest observed publisher
            # count for every stable Topic.
            return BagRecordingManager._collect_topic_snapshots(snapshot)
        except Exception as exc:
            raise BagRecordingError(f"无法读取当前 ROS Topic：{exc}") from exc
        finally:
            if node is not None:
                node.destroy_node()
            if context.ok():
                rclpy.shutdown(context=context)
