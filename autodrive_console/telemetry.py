"""Aletheia 的专用实时遥测传输。

这里刻意不是 ROS-Web Bridge。C++ 预处理进程只向各自独立的回环 UDP 端口发送
已经投影/限点后的二维点云、二维位姿或局部代价栅格。本模块在本机完成 UDP 分片重组，
并以三条独立 Binary WebSocket 通道送到浏览器：``/cloud``、``/pose`` 与 ``/costmap``。

设计边界：

* UDP 数据面只有一个未完成 frame；更大的 sequence 到达立刻丢弃旧 frame；
* 每个浏览器连接也只有一个待发送 frame。慢客户端只能丢自己的旧帧；
* UDP 接收线程、客户端发送线程与 ROS C++ 线程完全分离，网络背压不会反馈至
  ROS2 或自动驾驶链路；
* 不接受 ROS 消息、服务或参数，也不暴露任意 ROS 图发现能力。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import math
import os
import select
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Final


LOGGER = logging.getLogger("ry_aletheia.telemetry")

# C++ -> 本机 UDP。所有多字节字段均为 network byte order。
UDP_MAGIC: Final = b"RALT"
UDP_VERSION: Final = 1
KIND_CLOUD: Final = 1
KIND_POSE: Final = 2
KIND_COSTMAP: Final = 3
UDP_HEADER: Final = struct.Struct("!4sBBIIQHHHH")
UDP_HEADER_BYTES: Final = UDP_HEADER.size
UDP_MAX_PAYLOAD: Final = 1152
UDP_MAX_CHUNKS: Final = 64
MAX_CLOUD_POINTS: Final = 3000
MAX_COSTMAP_CELLS: Final = 65535
COSTMAP_META: Final = struct.Struct("!ffffHH")
# 一帧点云在回环 UDP 中通常约 24 KiB。TCP 内核发送队列只允许容纳少量当前帧，
# 配合每连接单槽与 250 ms send timeout，慢浏览器不会在内核里积累秒级历史。
WEBSOCKET_SEND_BUFFER_BYTES: Final = 32 * 1024
PARTIAL_FRAME_TTL_S: Final = 0.30

# 网关 -> 浏览器。payload 保持 C++ 已编码的 network-order float32，避免 Python
# 解包/重打包高频点云。浏览器 DataView 以 big endian 读取。
WIRE_MAGIC: Final = b"ALTM"
WIRE_VERSION: Final = 1
WIRE_HEADER: Final = struct.Struct("!4sBBIQH")


def _sequence_is_newer(candidate: int, previous: int) -> bool:
    """比较 uint32 sequence，并正确处理进程长期运行后的回绕。"""

    delta = (candidate - previous) & 0xFFFFFFFF
    return 0 < delta < 0x80000000


def _websocket_binary(payload: bytes) -> bytes:
    """Build an unmasked server-to-client binary WebSocket record."""

    length = len(payload)
    if length < 126:
        return bytes((0x82, length)) + payload
    if length <= 0xFFFF:
        return b"\x82\x7e" + struct.pack("!H", length) + payload
    return b"\x82\x7f" + struct.pack("!Q", length) + payload


@dataclass
class _PartialFrame:
    stream_id: int
    sequence: int
    timestamp_ns: int
    record_count: int
    chunk_count: int
    chunks: list[bytes | None]
    received: int = 0
    created_at: float = field(default_factory=time.monotonic)


class _LatestFrameAssembler:
    """每种流最多保存一个正在组装的 frame，严格 latest-wins。"""

    def __init__(self, kind: int) -> None:
        self.kind = kind
        self.stream_id: int | None = None
        self.pending: _PartialFrame | None = None
        self.last_complete_sequence: int | None = None

    def expire(self, now: float | None = None) -> None:
        """丢弃缺片的短暂残帧；内存本来有上界，但不能长期保留旧 frame。"""

        if self.pending is None:
            return
        current = time.monotonic() if now is None else now
        if current - self.pending.created_at >= PARTIAL_FRAME_TTL_S:
            self.pending = None

    def push(self, datagram: bytes) -> bytes | None:
        self.expire()
        if len(datagram) < UDP_HEADER_BYTES:
            return None
        try:
            magic, version, kind, stream_id, sequence, timestamp_ns, index, count, record_count, payload_size = UDP_HEADER.unpack_from(datagram)
        except struct.error:
            return None
        payload = datagram[UDP_HEADER_BYTES:]
        if (
            magic != UDP_MAGIC
            or version != UDP_VERSION
            or kind != self.kind
            or count < 1
            or count > UDP_MAX_CHUNKS
            or index >= count
            or payload_size != len(payload)
            or payload_size > UDP_MAX_PAYLOAD
            or self.kind not in (KIND_CLOUD, KIND_POSE, KIND_COSTMAP)
        ):
            return None
        if self.kind == KIND_CLOUD and (record_count > MAX_CLOUD_POINTS or payload_size % 8):
            return None
        if self.kind == KIND_POSE and (count != 1 or record_count != 1 or payload_size != 12):
            return None
        if self.kind == KIND_COSTMAP and record_count > MAX_COSTMAP_CELLS:
            return None

        # 预处理进程重启会生成新的 stream_id；它不是 sequence 回退，应立即接纳。
        if self.stream_id != stream_id:
            self.stream_id = stream_id
            self.pending = None
            self.last_complete_sequence = None

        pending = self.pending
        # 已完整交付的旧 sequence 不能再占用一个残帧槽；即使出现重复/乱序 UDP
        # 包，也只允许它被丢弃，不能等待其余旧片或挤掉当前帧。
        if pending is None and self.last_complete_sequence is not None and not _sequence_is_newer(sequence, self.last_complete_sequence):
            return None
        if pending is None or sequence != pending.sequence:
            if pending is not None and not _sequence_is_newer(sequence, pending.sequence):
                return None
            # 新 sequence 抵达即丢弃上一帧残片；禁止等待旧包补齐。
            self.pending = _PartialFrame(
                stream_id=stream_id,
                sequence=sequence,
                timestamp_ns=timestamp_ns,
                record_count=record_count,
                chunk_count=count,
                chunks=[None] * count,
            )
            pending = self.pending
        if (
            pending.stream_id != stream_id
            or pending.chunk_count != count
            or pending.timestamp_ns != timestamp_ns
            or pending.record_count != record_count
        ):
            return None
        if pending.chunks[index] is None:
            pending.chunks[index] = payload
            pending.received += 1
        if pending.received != pending.chunk_count:
            return None

        raw = b"".join(part for part in pending.chunks if part is not None)
        expected = (
            pending.record_count * 8
            if self.kind == KIND_CLOUD
            else 12
            if self.kind == KIND_POSE
            else COSTMAP_META.size + pending.record_count
        )
        self.pending = None
        if len(raw) != expected:
            return None
        if self.kind == KIND_COSTMAP:
            try:
                origin_x, origin_y, origin_yaw, resolution, width, height = COSTMAP_META.unpack_from(raw)
            except struct.error:
                return None
            if (
                width == 0
                or height == 0
                or width * height != pending.record_count
                or not all(math.isfinite(value) for value in (origin_x, origin_y, origin_yaw, resolution))
                or resolution <= 0.0
            ):
                return None
        if self.last_complete_sequence is not None and not _sequence_is_newer(sequence, self.last_complete_sequence):
            return None
        self.last_complete_sequence = sequence
        return WIRE_HEADER.pack(WIRE_MAGIC, WIRE_VERSION, self.kind, sequence, timestamp_ns, record_count) + raw


class _WebSocketClient:
    """一个连接一个 latest slot；该连接的网络阻塞绝不会影响其他连接。"""

    def __init__(self, owner: "TelemetryGateway", connection: socket.socket, lane: int, address: tuple[str, int]) -> None:
        self.owner = owner
        self.connection = connection
        self.lane = lane
        self.address = address
        self._pending: bytes | None = None
        self._pending_lock = threading.Lock()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._sender = threading.Thread(target=self._send_loop, name=f"aletheia-ws-send-{lane}", daemon=True)

    def start(self) -> None:
        # `sendall` 成功只代表数据进入内核发送队列，不能把默认的 MB 级队列当成
        # latest-wins 缓存。显式收紧缓冲；遇到持续慢客户端由 sender timeout 关闭，
        # 浏览器重连后直接收到当前帧。
        try:
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, WEBSOCKET_SEND_BUFFER_BYTES)
        except OSError:
            pass
        self.connection.settimeout(0.25)
        self._sender.start()
        try:
            # 浏览器通常不会发送应用数据。接收循环仅用于及时发现关闭；任何输入都
            # 被忽略，不允许它驱动 ROS 或改变订阅范围。
            while not self._closed.is_set():
                try:
                    if not self.connection.recv(2048):
                        break
                except TimeoutError:
                    continue
                except OSError:
                    break
        finally:
            self.close()

    def enqueue(self, payload: bytes) -> None:
        if self._closed.is_set():
            return
        with self._pending_lock:
            self._pending = payload
        self._ready.set()

    def _send_loop(self) -> None:
        while not self._closed.is_set():
            self._ready.wait(0.5)
            self._ready.clear()
            if self._closed.is_set():
                break
            with self._pending_lock:
                payload = self._pending
                self._pending = None
            if payload is None:
                continue
            try:
                self.connection.sendall(_websocket_binary(payload))
            except OSError:
                self.close()
                break

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._ready.set()
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.connection.close()
        except OSError:
            pass
        self.owner._remove_client(self)
        if self._sender.is_alive() and self._sender is not threading.current_thread():
            self._sender.join(timeout=0.35)


class TelemetryGateway:
    """Loopback UDP ingress + purpose-built Binary WebSocket lanes."""

    WEBSOCKET_PORT: Final = 8768
    # 点云可在一个 frame 中拆为二十余个 UDP 分片；位姿拥有独立入口、线程和
    # assembler，避免任意点云突发占用位姿的接收/组装时隙。UDP_PORT 保留为云端口
    # 的兼容别名，供既有维护脚本和测试使用。
    CLOUD_UDP_PORT: Final = 8769
    POSE_UDP_PORT: Final = 8770
    COSTMAP_UDP_PORT: Final = 8771
    UDP_PORT: Final = CLOUD_UDP_PORT

    def __init__(self, log_dir: object | None = None) -> None:
        # log_dir 保留为构造参数，便于 ObservationManager 生命周期和测试注入；所有
        # 事件进入统一 ToolLogStore，避免另开无轮换日志文件。
        self.log_dir = log_dir
        # start/stop 可能分别来自 HTTP 请求、空闲计时器与升级路径。它们必须完整
        # 串行：不能让旧 UDP/accept 线程在新 socket 上继续工作。
        self._lifecycle_lock = threading.RLock()
        self._lock = threading.RLock()
        self._running = threading.Event()
        self._generation = 0
        self._udp_sockets: dict[int, socket.socket] = {}
        self._websocket_socket: socket.socket | None = None
        self._udp_threads: dict[int, threading.Thread] = {}
        self._accept_thread: threading.Thread | None = None
        self._clients: set[_WebSocketClient] = set()
        self._assemblers = {
            KIND_CLOUD: _LatestFrameAssembler(KIND_CLOUD),
            KIND_POSE: _LatestFrameAssembler(KIND_POSE),
            KIND_COSTMAP: _LatestFrameAssembler(KIND_COSTMAP),
        }
        self._last_frame_at: dict[int, float] = {KIND_CLOUD: 0.0, KIND_POSE: 0.0, KIND_COSTMAP: 0.0}
        self._last_error_at = 0.0

    def start(self) -> None:
        with self._lifecycle_lock:
            with self._lock:
                if self._running.is_set():
                    return
                websocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                udp_sockets: dict[int, socket.socket] = {}
                try:
                    for kind, port in (
                        (KIND_CLOUD, self.UDP_PORT),
                        (KIND_POSE, self.POSE_UDP_PORT),
                        (KIND_COSTMAP, self.COSTMAP_UDP_PORT),
                    ):
                        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        udp.bind(("127.0.0.1", port))
                        udp.setblocking(False)
                        udp_sockets[kind] = udp
                    websocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    websocket.bind(("0.0.0.0", self.WEBSOCKET_PORT))
                    websocket.listen(16)
                    websocket.settimeout(0.5)
                except OSError:
                    for udp in udp_sockets.values():
                        udp.close()
                    websocket.close()
                    raise
                self._generation += 1
                generation = self._generation
                self._udp_sockets = udp_sockets
                self._websocket_socket = websocket
                assemblers = {
                    KIND_CLOUD: _LatestFrameAssembler(KIND_CLOUD),
                    KIND_POSE: _LatestFrameAssembler(KIND_POSE),
                    KIND_COSTMAP: _LatestFrameAssembler(KIND_COSTMAP),
                }
                self._assemblers = assemblers
                self._last_frame_at = {KIND_CLOUD: 0.0, KIND_POSE: 0.0, KIND_COSTMAP: 0.0}
                self._running.set()
                self._udp_threads = {
                    kind: threading.Thread(target=self._udp_loop, args=(udp, generation, kind, assemblers[kind]), name=f"aletheia-telemetry-udp-{kind}", daemon=True)
                    for kind, udp in udp_sockets.items()
                }
                self._accept_thread = threading.Thread(target=self._accept_loop, args=(websocket, generation), name="aletheia-telemetry-ws", daemon=True)
                for worker in self._udp_threads.values():
                    worker.start()
                self._accept_thread.start()
        LOGGER.info(
            "Aletheia 专用遥测网关已启动：cloud UDP 127.0.0.1:%s，pose UDP 127.0.0.1:%s，costmap UDP 127.0.0.1:%s，Binary WebSocket 0.0.0.0:%s",
            self.UDP_PORT,
            self.POSE_UDP_PORT,
            self.COSTMAP_UDP_PORT,
            self.WEBSOCKET_PORT,
        )

    def stop(self) -> None:
        with self._lifecycle_lock:
            with self._lock:
                if not self._running.is_set():
                    return
                self._running.clear()
                # 旧 worker 即便正在从 select/accept 返回，也绝不能读取随后新建
                # 的 socket 或 assembler。
                self._generation += 1
                udp_sockets, websocket = tuple(self._udp_sockets.values()), self._websocket_socket
                self._udp_sockets, self._websocket_socket = {}, None
                clients = list(self._clients)
                self._clients.clear()
                workers = (*self._udp_threads.values(), self._accept_thread)
                self._udp_threads = {}
            for endpoint in (*udp_sockets, websocket):
                if endpoint is not None:
                    try:
                        endpoint.close()
                    except OSError:
                        pass
            for client in clients:
                client.close()
            for worker in workers:
                if worker is not None and worker is not threading.current_thread():
                    worker.join(timeout=0.8)
            self._accept_thread = None
        LOGGER.info("Aletheia 专用遥测网关已停止")

    def status(self) -> dict[str, object]:
        now = time.monotonic()
        with self._lock:
            clients = {
                "cloud": sum(item.lane == KIND_CLOUD for item in self._clients),
                "pose": sum(item.lane == KIND_POSE for item in self._clients),
                "costmap": sum(item.lane == KIND_COSTMAP for item in self._clients),
            }
            running = self._running.is_set()
            cloud_age = now - self._last_frame_at[KIND_CLOUD] if self._last_frame_at[KIND_CLOUD] else None
            pose_age = now - self._last_frame_at[KIND_POSE] if self._last_frame_at[KIND_POSE] else None
            costmap_age = now - self._last_frame_at[KIND_COSTMAP] if self._last_frame_at[KIND_COSTMAP] else None
        return {
            "online": running,
            "websocket_port": self.WEBSOCKET_PORT,
            "udp_port": self.UDP_PORT,
            "pose_udp_port": self.POSE_UDP_PORT,
            "costmap_udp_port": self.COSTMAP_UDP_PORT,
            "clients": clients,
            "cloud_age_ms": round(cloud_age * 1000) if cloud_age is not None else None,
            "pose_age_ms": round(pose_age * 1000) if pose_age is not None else None,
            "costmap_age_ms": round(costmap_age * 1000) if costmap_age is not None else None,
        }

    def _udp_loop(self, endpoint: socket.socket, generation: int, kind: int, assembler: _LatestFrameAssembler) -> None:
        while self._running.is_set() and generation == self._generation:
            try:
                readable, _, _ = select.select((endpoint,), (), (), 0.5)
            except (OSError, ValueError):
                return
            if not readable:
                assembler.expire()
                continue
            # 即使突发堆积也只处理有限 datagram；下一轮会优先拿内核里较新的包，
            # 不能让异常 UDP 流无限占用 Python 线程。
            for _ in range(96):
                try:
                    packet, source = endpoint.recvfrom(1400)
                except BlockingIOError:
                    break
                except OSError:
                    return
                if source[0] != "127.0.0.1" or len(packet) < UDP_HEADER_BYTES:
                    continue
                if packet[5] != kind:
                    continue
                frame = assembler.push(packet)
                if frame is None:
                    continue
                with self._lock:
                    # stop 之后即使旧线程恰好从 select 返回，也不能给下一代 gateway
                    # 的 client 或状态写入数据。assembler 也是线程私有的旧对象。
                    if not self._running.is_set() or generation != self._generation:
                        return
                    self._last_frame_at[kind] = time.monotonic()
                    clients = tuple(item for item in self._clients if item.lane == kind)
                for client in clients:
                    client.enqueue(frame)

    def _accept_loop(self, endpoint: socket.socket, generation: int) -> None:
        while self._running.is_set() and generation == self._generation:
            try:
                connection, address = endpoint.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._accept_client, args=(connection, address, generation), name="aletheia-telemetry-client", daemon=True).start()

    def _accept_client(self, connection: socket.socket, address: tuple[str, int], generation: int) -> None:
        accepted = False
        try:
            connection.settimeout(2.0)
            request = b""
            while b"\r\n\r\n" not in request and len(request) < 8192:
                block = connection.recv(2048)
                if not block:
                    return
                request += block
            first, headers = self._parse_handshake(request)
            lane = (
                KIND_CLOUD
                if first.startswith("GET /cloud ")
                else KIND_POSE
                if first.startswith("GET /pose ")
                else KIND_COSTMAP
                if first.startswith("GET /costmap ")
                else 0
            )
            key = headers.get("sec-websocket-key")
            upgrade = headers.get("upgrade", "").lower()
            if lane == 0 or not key or upgrade != "websocket":
                connection.sendall(b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n")
                return
            accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode("ascii")
            connection.sendall(response)
            client = _WebSocketClient(self, connection, lane, address)
            with self._lock:
                if not self._running.is_set() or generation != self._generation:
                    return
                self._clients.add(client)
            accepted = True
            LOGGER.info(
                "实时遥测浏览器已连接：lane=%s peer=%s:%s",
                {KIND_CLOUD: "cloud", KIND_POSE: "pose", KIND_COSTMAP: "costmap"}[lane],
                address[0],
                address[1],
            )
            client.start()
        except (OSError, ValueError, UnicodeDecodeError):
            pass
        finally:
            # 握手失败路径没有 _WebSocketClient 接管 socket，必须显式回收文件描述符。
            if not accepted:
                try:
                    connection.close()
                except OSError:
                    pass

    @staticmethod
    def _parse_handshake(request: bytes) -> tuple[str, dict[str, str]]:
        lines = request.decode("iso-8859-1").split("\r\n")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        return lines[0] if lines else "", headers

    def _remove_client(self, client: _WebSocketClient) -> None:
        with self._lock:
            self._clients.discard(client)
