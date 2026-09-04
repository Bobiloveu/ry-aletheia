"""专用实时遥测的协议与 latest-wins 边界测试。"""

from __future__ import annotations

import struct
import socket
import threading
import time

from autodrive_console.telemetry import (
    KIND_CLOUD,
    KIND_COSTMAP,
    KIND_POSE,
    PARTIAL_FRAME_TTL_S,
    UDP_HEADER,
    UDP_MAGIC,
    UDP_MAX_CHUNKS,
    UDP_MAX_PAYLOAD,
    UDP_VERSION,
    WIRE_HEADER,
    WIRE_MAGIC,
    WIRE_VERSION,
    _LatestFrameAssembler,
    _WebSocketClient,
    TelemetryGateway,
)


def _packet(kind: int, stream: int, sequence: int, timestamp: int, index: int, count: int, points: int, payload: bytes) -> bytes:
    return UDP_HEADER.pack(UDP_MAGIC, UDP_VERSION, kind, stream, sequence, timestamp, index, count, points, len(payload)) + payload


def test_cloud_reassembly_discards_an_incomplete_old_frame_as_soon_as_newer_sequence_arrives():
    assembler = _LatestFrameAssembler(KIND_CLOUD)
    old = struct.pack("!ff", 1.0, 2.0) + struct.pack("!ff", 3.0, 4.0)
    current = struct.pack("!ff", 9.0, 10.0)

    assert assembler.push(_packet(KIND_CLOUD, 7, 20, 100, 0, 2, 2, old[:8])) is None
    # 新帧的第一个分片已到达，旧帧剩余分片必须不能再完成。
    assert assembler.push(_packet(KIND_CLOUD, 7, 21, 101, 0, 1, 1, current)) is not None
    assert assembler.push(_packet(KIND_CLOUD, 7, 20, 100, 1, 2, 2, old[8:])) is None

    frame = assembler.push(_packet(KIND_CLOUD, 7, 22, 102, 0, 1, 1, current))
    assert frame is not None
    magic, version, kind, sequence, timestamp, points = WIRE_HEADER.unpack_from(frame)
    assert (magic, version, kind, sequence, timestamp, points) == (WIRE_MAGIC, WIRE_VERSION, KIND_CLOUD, 22, 102, 1)
    assert frame[WIRE_HEADER.size:] == current


def test_pose_requires_one_complete_small_datagram_and_accepts_preprocessor_restart():
    assembler = _LatestFrameAssembler(KIND_POSE)
    pose = struct.pack("!fff", 1.25, -2.5, 0.75)
    assert assembler.push(_packet(KIND_POSE, 12, 1, 1000, 0, 2, 1, pose[:6])) is None
    # 流进程重启后 sequence 可回到 1；新的 stream id 必须立即恢复。
    frame = assembler.push(_packet(KIND_POSE, 13, 1, 1001, 0, 1, 1, pose))
    assert frame is not None
    assert WIRE_HEADER.unpack_from(frame)[2:] == (KIND_POSE, 1, 1001, 1)
    assert frame[WIRE_HEADER.size:] == pose


def test_costmap_reassembly_preserves_map_metadata_and_raw_occupancy_cells():
    """Costmap 是独立 kind；raw int8 cells 原样保持到浏览器二进制记录。"""

    assembler = _LatestFrameAssembler(KIND_COSTMAP)
    cells = bytes((0, 1, 127, 253, 254, 255))
    payload = struct.pack("!ffffHH", -2.5, -7.8, 0.25, 0.05, 3, 2) + cells

    frame = assembler.push(_packet(KIND_COSTMAP, 31, 7, 99, 0, 1, len(cells), payload))

    assert frame is not None
    assert WIRE_HEADER.unpack_from(frame) == (
        WIRE_MAGIC,
        WIRE_VERSION,
        KIND_COSTMAP,
        7,
        99,
        len(cells),
    )
    assert frame[WIRE_HEADER.size:] == payload


def test_costmap_out_of_order_fragments_keep_only_the_newest_complete_grid():
    assembler = _LatestFrameAssembler(KIND_COSTMAP)
    old_cells = bytes((0, 1, 2, 3))
    old = struct.pack("!ffffHH", 0.0, 0.0, 0.0, 0.05, 2, 2) + old_cells
    current_cells = bytes((253, 254, 255, 0))
    current = struct.pack("!ffffHH", 4.0, -1.0, 0.5, 0.05, 2, 2) + current_cells

    assert assembler.push(_packet(KIND_COSTMAP, 4, 10, 1, 0, 2, 4, old[:12])) is None
    # 新 frame 的尾分片先到达；它应立即淘汰旧帧，且重复尾片不提前完成。
    assert assembler.push(_packet(KIND_COSTMAP, 4, 11, 2, 1, 2, 4, current[12:])) is None
    assert assembler.push(_packet(KIND_COSTMAP, 4, 11, 2, 1, 2, 4, current[12:])) is None
    frame = assembler.push(_packet(KIND_COSTMAP, 4, 11, 2, 0, 2, 4, current[:12]))

    assert frame is not None
    assert WIRE_HEADER.unpack_from(frame)[2:] == (KIND_COSTMAP, 11, 2, 4)
    assert frame[WIRE_HEADER.size:] == current
    assert assembler.push(_packet(KIND_COSTMAP, 4, 10, 1, 1, 2, 4, old[12:])) is None


def test_costmap_rejects_invalid_grid_metadata_without_retaining_a_partial_frame():
    assembler = _LatestFrameAssembler(KIND_COSTMAP)
    # 宽高必须恰好对应 header record count；NaN/非正分辨率也不允许进入浏览器。
    mismatch = struct.pack("!ffffHH", 0.0, 0.0, 0.0, 0.05, 3, 2) + bytes(4)
    invalid_resolution = struct.pack("!ffffHH", 0.0, 0.0, 0.0, float("nan"), 2, 2) + bytes(4)

    assert assembler.push(_packet(KIND_COSTMAP, 9, 1, 1, 0, 1, 4, mismatch)) is None
    assert assembler.pending is None
    assert assembler.push(_packet(KIND_COSTMAP, 9, 2, 2, 0, 1, 4, invalid_resolution)) is None
    assert assembler.pending is None


def test_costmap_missing_fragment_expires_and_a_new_grid_immediately_recovers():
    """缺片的局部代价图没有补片等待；TTL 后只接受新的完整栅格。"""

    assembler = _LatestFrameAssembler(KIND_COSTMAP)
    old = struct.pack("!ffffHH", -2.5, -7.8, 0.0, 0.05, 2, 2) + bytes((0, 1, 253, 254))

    assert assembler.push(_packet(KIND_COSTMAP, 5, 71, 1, 0, 2, 4, old[:12])) is None
    assert assembler.pending is not None
    assembler.expire(assembler.pending.created_at + PARTIAL_FRAME_TTL_S + 0.01)
    assert assembler.pending is None

    # 迟到的旧尾片绝不能补出陈旧图；下一张完整图直接成为当前图。
    assert assembler.push(_packet(KIND_COSTMAP, 5, 71, 1, 1, 2, 4, old[12:])) is None
    current = struct.pack("!ffffHH", -2.0, -7.5, 0.1, 0.05, 2, 2) + bytes((0, 254, 255, 0))
    frame = assembler.push(_packet(KIND_COSTMAP, 5, 72, 2, 0, 1, 4, current))

    assert frame is not None
    assert WIRE_HEADER.unpack_from(frame)[3] == 72
    assert frame[WIRE_HEADER.size:] == current


def test_protocol_rejects_malformed_payload_without_retaining_history():
    assembler = _LatestFrameAssembler(KIND_CLOUD)
    # 点云 payload 必须是完整 x/y float32 对，且 header payload-size 必须一致。
    assert assembler.push(_packet(KIND_CLOUD, 1, 1, 1, 0, 1, 1, b"1234567")) is None
    malformed = bytearray(_packet(KIND_CLOUD, 1, 2, 2, 0, 1, 1, b"12345678"))
    malformed[-1] = 0
    malformed[UDP_HEADER.size - 2 : UDP_HEADER.size] = struct.pack("!H", 9)
    assert assembler.push(bytes(malformed)) is None
    assert assembler.push(_packet(KIND_CLOUD, 1, 3, 3, 0, UDP_MAX_CHUNKS + 1, 1, b"12345678")) is None
    assert assembler.push(_packet(KIND_CLOUD, 1, 4, 4, 1, 1, 1, b"12345678")) is None
    assert assembler.push(_packet(KIND_CLOUD, 1, 5, 5, 0, 1, 3001, b"12345678")) is None
    assert assembler.push(_packet(KIND_CLOUD, 1, 6, 6, 0, 1, 145, b"x" * (UDP_MAX_PAYLOAD + 1))) is None
    assert assembler.pending is None


def test_cloud_reassembly_accepts_out_of_order_fragments_and_ignores_duplicates():
    assembler = _LatestFrameAssembler(KIND_CLOUD)
    payload = b"".join(struct.pack("!ff", float(index), -float(index)) for index in range(3))
    fragments = (payload[:8], payload[8:16], payload[16:])

    assert assembler.push(_packet(KIND_CLOUD, 7, 9, 99, 2, 3, 3, fragments[2])) is None
    assert assembler.push(_packet(KIND_CLOUD, 7, 9, 99, 0, 3, 3, fragments[0])) is None
    # 重复 datagram 不得增加 received 计数，也不能提前完成帧。
    assert assembler.push(_packet(KIND_CLOUD, 7, 9, 99, 0, 3, 3, fragments[0])) is None
    frame = assembler.push(_packet(KIND_CLOUD, 7, 9, 99, 1, 3, 3, fragments[1]))

    assert frame is not None
    assert WIRE_HEADER.unpack_from(frame)[2:] == (KIND_CLOUD, 9, 99, 3)
    assert frame[WIRE_HEADER.size:] == payload


def test_missing_fragment_expires_without_waiting_for_old_frame_completion():
    assembler = _LatestFrameAssembler(KIND_CLOUD)
    payload = struct.pack("!ff", 1.0, 2.0) + struct.pack("!ff", 3.0, 4.0)
    assert assembler.push(_packet(KIND_CLOUD, 3, 40, 400, 0, 2, 2, payload[:8])) is None
    assert assembler.pending is not None
    assembler.expire(assembler.pending.created_at + PARTIAL_FRAME_TTL_S + 0.01)
    assert assembler.pending is None
    # 延迟到达的旧尾片只能形成新的残片；新帧应立即覆盖它并完整交付。
    assert assembler.push(_packet(KIND_CLOUD, 3, 40, 400, 1, 2, 2, payload[8:])) is None
    current = struct.pack("!ff", 9.0, 10.0)
    frame = assembler.push(_packet(KIND_CLOUD, 3, 41, 401, 0, 1, 1, current))
    assert frame is not None
    assert WIRE_HEADER.unpack_from(frame)[3] == 41


def test_client_pending_slot_replaces_unsent_history_for_slow_client():
    server, peer = socket.socketpair()

    class Owner:
        def _remove_client(self, _client):
            pass

    client = _WebSocketClient(Owner(), server, KIND_CLOUD, ("127.0.0.1", 1))
    try:
        client.enqueue(b"old-frame")
        client.enqueue(b"new-frame")
        with client._pending_lock:
            assert client._pending == b"new-frame"
    finally:
        client.close()
        peer.close()


def _free_port(kind: int) -> int:
    endpoint = socket.socket(socket.AF_INET, kind)
    try:
        endpoint.bind(("127.0.0.1", 0))
        return endpoint.getsockname()[1]
    finally:
        endpoint.close()


def _recv_until(endpoint: socket.socket, marker: bytes) -> bytes:
    data = b""
    deadline = time.monotonic() + 2.0
    while marker not in data and time.monotonic() < deadline:
        data += endpoint.recv(4096)
    return data


def _open_browser_lane(port: int, lane: str) -> socket.socket:
    browser = socket.create_connection(("127.0.0.1", port), timeout=2)
    browser.settimeout(2)
    browser.sendall(
        f"GET /{lane} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
        "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
        "Sec-WebSocket-Key: dGVzdC1hbGV0aGVpYQ==\r\n\r\n".encode("ascii")
    )
    assert b"101 Switching Protocols" in _recv_until(browser, b"\r\n\r\n")
    return browser


def test_gateway_delivers_a_reassembled_latest_cloud_frame_over_its_binary_websocket(monkeypatch):
    """UDP 仅作本机数据面，浏览器只收到紧凑的 ALTM Binary WebSocket 帧。"""
    websocket_port = _free_port(socket.SOCK_STREAM)
    udp_port = _free_port(socket.SOCK_DGRAM)
    pose_udp_port = _free_port(socket.SOCK_DGRAM)
    monkeypatch.setattr(TelemetryGateway, "WEBSOCKET_PORT", websocket_port)
    monkeypatch.setattr(TelemetryGateway, "UDP_PORT", udp_port)
    monkeypatch.setattr(TelemetryGateway, "POSE_UDP_PORT", pose_udp_port)
    gateway = TelemetryGateway()
    gateway.start()
    browser = _open_browser_lane(websocket_port, "cloud")
    try:
        deadline = time.monotonic() + 1.0
        while gateway.status()["clients"]["cloud"] != 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert gateway.status()["clients"]["cloud"] == 1

        payload = struct.pack("!ff", 3.0, -4.0)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sender.sendto(_packet(KIND_CLOUD, 42, 7, 1234, 0, 1, 1, payload), ("127.0.0.1", udp_port))
        finally:
            sender.close()
        record = browser.recv(4096)
        assert record[:2] == bytes((0x82, WIRE_HEADER.size + len(payload)))
        magic, version, kind, sequence, timestamp, points = WIRE_HEADER.unpack_from(record, 2)
        assert (magic, version, kind, sequence, timestamp, points) == (WIRE_MAGIC, WIRE_VERSION, KIND_CLOUD, 7, 1234, 1)
        assert record[2 + WIRE_HEADER.size:] == payload
    finally:
        browser.close()
        gateway.stop()


def test_gateway_delivers_costmap_only_to_its_dedicated_binary_websocket_lane(monkeypatch):
    websocket_port = _free_port(socket.SOCK_STREAM)
    cloud_udp_port = _free_port(socket.SOCK_DGRAM)
    pose_udp_port = _free_port(socket.SOCK_DGRAM)
    costmap_udp_port = _free_port(socket.SOCK_DGRAM)
    monkeypatch.setattr(TelemetryGateway, "WEBSOCKET_PORT", websocket_port)
    monkeypatch.setattr(TelemetryGateway, "UDP_PORT", cloud_udp_port)
    monkeypatch.setattr(TelemetryGateway, "POSE_UDP_PORT", pose_udp_port)
    monkeypatch.setattr(TelemetryGateway, "COSTMAP_UDP_PORT", costmap_udp_port)
    gateway = TelemetryGateway()
    gateway.start()
    browser = _open_browser_lane(websocket_port, "costmap")
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        deadline = time.monotonic() + 1.0
        while gateway.status()["clients"]["costmap"] != 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert gateway.status()["clients"] == {"cloud": 0, "pose": 0, "costmap": 1}

        cells = bytes((0, 253, 254, 255))
        payload = struct.pack("!ffffHH", -2.5, -7.8, 0.0, 0.05, 2, 2) + cells
        sender.sendto(
            _packet(KIND_COSTMAP, 42, 7, 1234, 0, 1, len(cells), payload),
            ("127.0.0.1", costmap_udp_port),
        )
        record = browser.recv(4096)
        assert record[:2] == bytes((0x82, WIRE_HEADER.size + len(payload)))
        assert WIRE_HEADER.unpack_from(record, 2)[2:] == (KIND_COSTMAP, 7, 1234, len(cells))
        assert record[2 + WIRE_HEADER.size :] == payload
    finally:
        sender.close()
        browser.close()
        gateway.stop()


def test_gateway_reconnect_releases_the_old_client_and_delivers_current_pose(monkeypatch):
    websocket_port = _free_port(socket.SOCK_STREAM)
    cloud_udp_port = _free_port(socket.SOCK_DGRAM)
    pose_udp_port = _free_port(socket.SOCK_DGRAM)
    monkeypatch.setattr(TelemetryGateway, "WEBSOCKET_PORT", websocket_port)
    monkeypatch.setattr(TelemetryGateway, "UDP_PORT", cloud_udp_port)
    monkeypatch.setattr(TelemetryGateway, "POSE_UDP_PORT", pose_udp_port)
    gateway = TelemetryGateway()
    gateway.start()
    first = _open_browser_lane(websocket_port, "pose")
    second = None
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        deadline = time.monotonic() + 1.0
        while gateway.status()["clients"]["pose"] != 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        first.close()
        deadline = time.monotonic() + 1.0
        while gateway.status()["clients"]["pose"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert gateway.status()["clients"]["pose"] == 0

        second = _open_browser_lane(websocket_port, "pose")
        pose = struct.pack("!fff", 1.0, -2.0, 0.5)
        sender.sendto(_packet(KIND_POSE, 55, 8, 800, 0, 1, 1, pose), ("127.0.0.1", pose_udp_port))
        record = second.recv(4096)
        assert record[:2] == bytes((0x82, WIRE_HEADER.size + len(pose)))
        assert WIRE_HEADER.unpack_from(record, 2)[2:] == (KIND_POSE, 8, 800, 1)
        assert record[2 + WIRE_HEADER.size:] == pose
    finally:
        sender.close()
        first.close()
        if second is not None:
            second.close()
        gateway.stop()


def test_cloud_and_pose_have_separate_loopback_udp_ingress_threads(monkeypatch):
    """错误发到另一条本机 UDP 入口不能跨 lane，点云突发不占位姿入口。"""
    websocket_port = _free_port(socket.SOCK_STREAM)
    cloud_udp_port = _free_port(socket.SOCK_DGRAM)
    pose_udp_port = _free_port(socket.SOCK_DGRAM)
    monkeypatch.setattr(TelemetryGateway, "WEBSOCKET_PORT", websocket_port)
    monkeypatch.setattr(TelemetryGateway, "UDP_PORT", cloud_udp_port)
    monkeypatch.setattr(TelemetryGateway, "POSE_UDP_PORT", pose_udp_port)
    gateway = TelemetryGateway()
    gateway.start()
    cloud_browser = _open_browser_lane(websocket_port, "cloud")
    pose_browser = _open_browser_lane(websocket_port, "pose")
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        deadline = time.monotonic() + 1.0
        while sum(gateway.status()["clients"].values()) != 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert gateway.status()["clients"] == {"cloud": 1, "pose": 1, "costmap": 0}
        cloud_browser.settimeout(0.15)
        payload = struct.pack("!ff", 1.0, 2.0)
        sender.sendto(_packet(KIND_CLOUD, 91, 1, 1, 0, 1, 1, payload), ("127.0.0.1", pose_udp_port))
        try:
            cloud_browser.recv(4096)
            assert False, "cloud packet must not cross the dedicated pose UDP ingress"
        except TimeoutError:
            pass

        pose = struct.pack("!fff", 1.0, -2.0, 0.25)
        sender.sendto(_packet(KIND_POSE, 92, 1, 2, 0, 1, 1, pose), ("127.0.0.1", pose_udp_port))
        record = pose_browser.recv(4096)
        assert WIRE_HEADER.unpack_from(record, 2)[2:] == (KIND_POSE, 1, 2, 1)
        sender.sendto(_packet(KIND_CLOUD, 91, 2, 3, 0, 1, 1, payload), ("127.0.0.1", cloud_udp_port))
        record = cloud_browser.recv(4096)
        assert WIRE_HEADER.unpack_from(record, 2)[2:] == (KIND_CLOUD, 2, 3, 1)
    finally:
        sender.close()
        cloud_browser.close()
        pose_browser.close()
        gateway.stop()


def test_gateway_start_stop_is_serialized_under_concurrent_lifecycle_requests(monkeypatch):
    websocket_port = _free_port(socket.SOCK_STREAM)
    udp_port = _free_port(socket.SOCK_DGRAM)
    pose_udp_port = _free_port(socket.SOCK_DGRAM)
    monkeypatch.setattr(TelemetryGateway, "WEBSOCKET_PORT", websocket_port)
    monkeypatch.setattr(TelemetryGateway, "UDP_PORT", udp_port)
    monkeypatch.setattr(TelemetryGateway, "POSE_UDP_PORT", pose_udp_port)
    gateway = TelemetryGateway()
    failures: list[BaseException] = []
    barrier = threading.Barrier(2)

    def start_many() -> None:
        try:
            for _ in range(12):
                barrier.wait(timeout=2)
                gateway.start()
        except BaseException as exc:  # pragma: no cover - assertion after joining worker
            failures.append(exc)

    def stop_many() -> None:
        try:
            for _ in range(12):
                barrier.wait(timeout=2)
                gateway.stop()
        except BaseException as exc:  # pragma: no cover - assertion after joining worker
            failures.append(exc)

    starters = threading.Thread(target=start_many)
    stoppers = threading.Thread(target=stop_many)
    starters.start()
    stoppers.start()
    starters.join(timeout=10)
    stoppers.join(timeout=10)
    try:
        assert not starters.is_alive()
        assert not stoppers.is_alive()
        assert not failures
    finally:
        gateway.stop()
