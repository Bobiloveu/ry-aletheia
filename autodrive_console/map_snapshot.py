"""按需把机器人现有 ``/map`` 缓存为实时观测可读的地图资产。

实时观测页面只消费本地 ``maps_cache``，而不是把 OccupancyGrid 通过浏览器实时
转发。采集器仅在观测已启用时运行，使用 Transient Local + depth 1 接收 map_server
当前地图及后续切图；它复用轨迹证据的 MapAssetCache 格式，不发送 ROS 控制请求。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from .map_assets import MapAssetCache, MapAssetError


LOGGER = logging.getLogger("ry_aletheia.map_snapshot")


class ObservationMapSnapshot:
    """观测期间维护当前地图缓存；地图切换时才做一次磁盘写入。"""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self._cache = MapAssetCache(cache_dir)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = "stopped"
        self._last_error: str | None = None
        self._last_asset_id: str | None = None
        self._last_updated_at = 0.0
        self._last_signature: tuple[object, ...] | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._state = "starting"
            self._last_error = None
            self._thread = threading.Thread(target=self._run, name="aletheia-map-snapshot", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            worker = self._thread
            self._stop.set()
        if worker and worker is not threading.current_thread():
            worker.join(timeout=2.0)
        with self._lock:
            if self._thread is worker:
                self._thread = None
                if self._state != "error":
                    self._state = "stopped"

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "state": self._state,
                "active_map_id": self._last_asset_id,
                "last_error": self._last_error,
                "age_ms": round((time.monotonic() - self._last_updated_at) * 1000) if self._last_updated_at else None,
            }

    def _run(self) -> None:
        node = executor = None
        try:
            import rclpy
            from nav_msgs.msg import OccupancyGrid
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

            if not rclpy.ok():
                rclpy.init(args=None)
            node = rclpy.create_node("ry_aletheia_observation_map_cache")
            qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
            node.create_subscription(OccupancyGrid, "/map", self._on_map, qos)
            executor = SingleThreadedExecutor()
            executor.add_node(node)
            with self._lock:
                self._state = "waiting_map"
            LOGGER.info("实时观测地图缓存器已订阅 /map（Transient Local, depth=1）")
            while not self._stop.is_set() and rclpy.ok():
                executor.spin_once(timeout_sec=0.5)
        except Exception as exc:
            message = f"实时观测地图缓存器启动/运行失败：{exc}"
            with self._lock:
                self._state = "error"
                self._last_error = message
            LOGGER.exception(message)
        finally:
            if executor is not None:
                try:
                    executor.shutdown(timeout_sec=0.5)
                except Exception:
                    pass
            if node is not None:
                try:
                    node.destroy_node()
                except Exception:
                    pass

    def _on_map(self, message: object) -> None:
        """缓存一个 map_server 快照；重复的 Transient Local 回放不重复落盘。"""

        try:
            info = message.info
            resolution = float(info.resolution)
            width, height = int(info.width), int(info.height)
            origin = [float(info.origin.position.x), float(info.origin.position.y)]
            frame_id = str(message.header.frame_id).strip() or "map"
            load_time_ns = int(info.map_load_time.sec) * 1_000_000_000 + int(info.map_load_time.nanosec)
            signature = (load_time_ns, resolution, width, height, origin[0], origin[1], frame_id)
            with self._lock:
                if signature == self._last_signature:
                    return
            # 若与受控地图目录中的 YAML 匹配，继承对应虚拟墙；不匹配时仍以 ROS
            # 实际 OccupancyGrid 为准绘制底图，绝不猜测墙体。
            try:
                wall_source = self._cache.find_matching_map(
                    resolution=resolution, width=width, height=height, origin=origin,
                )
            except MapAssetError:
                wall_source = None
            asset = self._cache.cache_occupancy_grid(
                resolution=resolution, width=width, height=height, origin=origin,
                frame_id=frame_id, data=list(message.data),
                label=wall_source.label if wall_source else None, wall_source=wall_source,
            )
            self._write_active_marker(asset.id, asset.label, frame_id, load_time_ns)
            with self._lock:
                self._last_signature = signature
                self._last_asset_id = asset.id
                self._last_updated_at = time.monotonic()
                self._last_error = None
                self._state = "ready"
            LOGGER.info(
                "实时观测已缓存当前 /map：id=%s %dx%d resolution=%.6f frame=%s",
                asset.id, width, height, resolution, frame_id,
            )
        except Exception as exc:
            message = f"无法缓存当前 /map：{exc}"
            with self._lock:
                self._last_error = message
                self._state = "map_error"
            LOGGER.exception(message)

    def _write_active_marker(self, asset_id: str, label: str, frame_id: str, map_epoch: int) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        target = self.cache_dir / "active_map.json"
        temporary = target.with_suffix(".tmp")
        payload = {
            "asset_id": asset_id,
            "label": label,
            "map_epoch": map_epoch,
            "updated_at_ns": time.time_ns(),
            "frame_id": frame_id,
        }
        temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, target)
