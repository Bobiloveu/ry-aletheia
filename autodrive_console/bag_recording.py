"""Controlled, auditable ROS 2 diagnostic bag recording.

This module intentionally owns the ROS recording subprocess boundary.  HTTP
callers only provide a selected attempt and discovered topic names; they never
provide a command, an output path, compression flags, or ROS environment.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
from typing import Callable, Mapping


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


class BagRecordingManager:
    """Validate operator selections before a recorder lifecycle is created."""

    MAX_TOPICS = 32
    _TOPIC_NAME = re.compile(r"/(?:[A-Za-z][A-Za-z0-9_]*)(?:/[A-Za-z][A-Za-z0-9_]*)*\Z")

    def __init__(
        self,
        root: Path,
        *,
        topic_probe: Callable[[], list[dict[str, object]]] | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self._topic_probe = topic_probe or self._ros_topic_probe
        self._environment = dict(os.environ if environment is None else environment)

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
                or isinstance(publisher_count, bool)
                or not isinstance(publisher_count, int)
                or publisher_count < 1
            ):
                continue
            result.append({"name": name, "type": message_type, "publisher_count": publisher_count})
        return sorted(result, key=lambda item: str(item["name"]))

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
        except Exception as exc:
            raise BagRecordingError(f"无法读取当前 ROS Topic：{exc}") from exc
        finally:
            if node is not None:
                node.destroy_node()
            if context.ok():
                rclpy.shutdown(context=context)
