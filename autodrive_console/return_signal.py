"""One-shot, acceptance-only publication of the existing return signal."""

from __future__ import annotations

import logging
import threading


LOGGER = logging.getLogger("ry_aletheia.return_signal")


class ReturnSignalGate:
    """Allow one return publication for each explicitly armed acceptance item."""

    WAITING_RETURN_CODE = "103"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._armed_item: int | None = None
        self._sent_item: int | None = None

    def arm(self, item_index: int) -> None:
        if isinstance(item_index, bool) or not isinstance(item_index, int) or item_index < 1:
            raise ValueError("验收任务序号无效")
        with self._lock:
            self._armed_item = item_index

    def disarm(self, item_index: int) -> None:
        """Stop accepting statuses for a task that has already returned."""
        if isinstance(item_index, bool) or not isinstance(item_index, int) or item_index < 1:
            raise ValueError("验收任务序号无效")
        with self._lock:
            if self._armed_item == item_index:
                self._armed_item = None

    def accept(self, status_code: object) -> bool:
        """Return true only for the first 103 belonging to the armed item."""
        if str(status_code).strip() != self.WAITING_RETURN_CODE:
            return False
        with self._lock:
            if self._armed_item is None or self._sent_item == self._armed_item:
                return False
            self._sent_item = self._armed_item
            return True


class RosReturnSignalBridge:
    """Own a short-lived ROS subscription/publisher pair for one acceptance run."""

    TASK_STATUS_TOPIC = "/task_status"
    RETURN_TOPIC = "/start_return"

    def __init__(self) -> None:
        self._gate = ReturnSignalGate()
        self._lock = threading.RLock()
        self._node = None
        self._executor = None
        self._thread: threading.Thread | None = None
        self._publisher = None
        self._bool_message = None
        self._closed = False

    def start(self) -> None:
        """Start receiving TaskStatus before the acceptance task is dispatched."""
        with self._lock:
            if self._closed:
                raise RuntimeError("自动返程 ROS bridge 已关闭")
            if self._node is not None:
                return
        node = None
        executor = None
        managed = False
        try:
            import rclpy
            from master_interfaces.msg import TaskStatus
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
            from std_msgs.msg import Bool

            if not rclpy.ok():
                rclpy.init()
            node = rclpy.create_node("ry_aletheia_acceptance_return_signal")
            qos = QoSProfile(
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.VOLATILE,
            )
            publisher = node.create_publisher(Bool, self.RETURN_TOPIC, qos)
            node.create_subscription(TaskStatus, self.TASK_STATUS_TOPIC, self._on_task_status, qos)
            executor = SingleThreadedExecutor()
            executor.add_node(node)
            thread = threading.Thread(target=executor.spin, daemon=True, name="acceptance-return-signal")
            with self._lock:
                if self._closed:
                    raise RuntimeError("自动返程 ROS bridge 已关闭")
                self._node = node
                self._executor = executor
                self._thread = thread
                self._publisher = publisher
                self._bool_message = Bool
                managed = True
            thread.start()
            LOGGER.info("自动返程 ROS bridge 已启动：status=%s return=%s", self.TASK_STATUS_TOPIC, self.RETURN_TOPIC)
        except Exception as exc:
            if managed:
                self.close()
            else:
                # Construction can fail before ownership moves to ``self``.
                # The local node/executor pair must then be released here.
                if executor is not None:
                    try:
                        executor.shutdown()
                    except Exception:
                        LOGGER.exception("清理未接管的自动返程 ROS executor 失败")
                if node is not None:
                    try:
                        node.destroy_node()
                    except Exception:
                        LOGGER.exception("清理未接管的自动返程 ROS node 失败")
            raise RuntimeError(f"自动返程 ROS 通道初始化失败：{exc}") from exc

    def arm(self, item_index: int) -> None:
        self._gate.arm(item_index)

    def disarm(self, item_index: int) -> None:
        self._gate.disarm(item_index)

    def close(self) -> None:
        """Release only this bridge; never shut down process-wide rclpy."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            executor, thread, node = self._executor, self._thread, self._node
            self._executor = self._thread = self._node = self._publisher = self._bool_message = None
        if executor is not None:
            try:
                executor.shutdown()
            except Exception:
                LOGGER.exception("关闭自动返程 ROS executor 失败")
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if node is not None:
            try:
                node.destroy_node()
            except Exception:
                LOGGER.exception("销毁自动返程 ROS node 失败")

    def _on_task_status(self, message) -> None:
        if not self._gate.accept(getattr(message, "status_code", "")):
            return
        with self._lock:
            publisher, bool_message = self._publisher, self._bool_message
        if publisher is None or bool_message is None:
            return
        try:
            command = bool_message()
            command.data = True
            publisher.publish(command)
            LOGGER.info("验收任务进入等待返程状态，已下发返程信号")
        except Exception:
            LOGGER.exception("验收任务等待返程时发布返程信号失败")
