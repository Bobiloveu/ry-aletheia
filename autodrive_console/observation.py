from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import re
from pathlib import Path
from typing import Any

from .map_assets import CachedMapAsset, MapAssetCache, MapAssetError
from .map_snapshot import ObservationMapSnapshot
from .settings import RobotSettings
from .telemetry import TelemetryGateway
from .trajectory_render import TrajectoryRenderError, _png_gray, _read_pgm


LOGGER = logging.getLogger("ry_aletheia.observation")

class ObservationError(RuntimeError):
    """实时观测的配置或受控进程状态不满足启动条件。"""


class ObservationManager:
    """按需管理专用实时遥测，不接入任何通用 ROS-Web Bridge。

    地图、虚拟墙仍沿用既有缓存/API；点云、位姿和局部代价地图由彼此隔离的 C++ 预处理进程产生，
    经回环 UDP 进入 ``TelemetryGateway`` 后用专用 Binary WebSocket 交给网页。
    """

    MAP_SERVER_YAML_REFRESH_S = 10.0
    MAP_SERVER_QUERY_TIMEOUT_S = 5.0
    MAP_SERVER_YAML_FALLBACK_S = 30.0

    def __init__(self, maps_dir: Path, log_dir: Path, preprocessor_path: Path | None = None) -> None:
        self.maps_dir = maps_dir
        self.log_dir = log_dir
        # HTTP 请求、页面心跳、空闲计时器和升级路径都可能触发启停。生命周期必须
        # 串行，避免两个页面同时进入时重复 spawn 预处理器，或 stop/start 交错。
        self._lifecycle_lock = threading.RLock()
        self._lock = threading.RLock()
        self._preprocessor_processes: dict[str, subprocess.Popen] = {}
        self._preprocessor_path = preprocessor_path
        self._telemetry = TelemetryGateway(log_dir)
        self._map_snapshot = ObservationMapSnapshot(maps_dir)
        self._last_heartbeat = 0.0
        self._idle_timer: threading.Timer | None = None
        self._live_map_matches: dict[str, dict[str, Any]] = {}
        self._map_server_yaml_checked_at = 0.0
        self._map_server_yaml_verified_at = 0.0
        self._map_server_yaml: Path | None = None
        # Set only after ``live_layers`` has proven that map_server's YAML and
        # the live OccupancyGrid describe the same map.  The first item is the
        # content-hashed runtime snapshot; the second is the stable static-map
        # identity used for operator markers.  They intentionally differ.
        self._active_task_map: tuple[str, str, Path] | None = None
        self._client_metrics: dict[str, Any] = {}
        self._client_metrics_at = 0.0
        self._client_metric_alerts: set[str] = set()

    def status(self, settings: RobotSettings) -> dict[str, Any]:
        with self._lifecycle_lock:
            self._stop_if_idle(settings)
            self._reap()
            observation = self._options(settings)
            telemetry = self._telemetry.status()
            cloud_preprocessor_running = self._preprocessor_running("cloud")
            pose_preprocessor_running = self._preprocessor_running("pose")
            costmap_preprocessor_running = self._preprocessor_running("costmap")
            return {
                "enabled": observation["enabled"],
                "telemetry": {
                    **telemetry,
                    "managed": telemetry["online"],
                    "detail": "Aletheia 专用 UDP + Binary WebSocket 遥测网关；不依赖 Foxglove Bridge",
                },
                "maps": self.maps(),
                "active_map_id": self.active_map_id(),
                "map_snapshot": self._map_snapshot.status(),
                "idle_stop_seconds": observation["idle_stop_seconds"],
                "preprocessor": {
                    "available": bool(self._preprocessor_path and self._preprocessor_path.is_file()),
                    "managed": cloud_preprocessor_running or pose_preprocessor_running or costmap_preprocessor_running,
                    "cloud_managed": cloud_preprocessor_running,
                    "pose_managed": pose_preprocessor_running,
                    "costmap_managed": costmap_preprocessor_running,
                },
                "client_metrics": {**self._client_metrics, "age_seconds": round(max(0.0, time.monotonic() - self._client_metrics_at), 2)} if self._client_metrics_at else None,
            }

    def start(self, settings: RobotSettings) -> dict[str, Any]:
        with self._lifecycle_lock:
            options = self._options(settings)
            if not options["enabled"]:
                raise ObservationError("实时观测尚未在运行配置中启用")
            self._reap()
            self._last_heartbeat = time.monotonic()
            self._schedule_idle_stop(settings)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            LOGGER.info(
                "实时观测启动预检：cache_dir=%s telemetry_ws=%s cloud_udp=%s pose_udp=%s costmap_udp=%s",
                self.maps_dir,
                TelemetryGateway.WEBSOCKET_PORT,
                TelemetryGateway.UDP_PORT,
                TelemetryGateway.POSE_UDP_PORT,
                TelemetryGateway.COSTMAP_UDP_PORT,
            )
            try:
                self._telemetry.start()
                self._start_preprocessor()
                # 地图只进入既有 maps_cache；点云/位姿二进制遥测重构不改变其坐标系
                # 或前端 PixiJS 图层。即使地图暂未到达，也不能阻止轻量流启动。
                self._map_snapshot.start()
            except (OSError, ObservationError) as exc:
                self.stop()
                message = f"无法启动 Aletheia 专用遥测：{exc}"
                LOGGER.error("实时观测启动失败：%s", message)
                raise ObservationError(message) from exc
            return self.status(settings)

    def heartbeat(self, settings: RobotSettings) -> dict[str, Any]:
        with self._lifecycle_lock:
            self._last_heartbeat = time.monotonic()
            if self._telemetry.status()["online"]:
                self._schedule_idle_stop(settings)
            return self.status(settings)

    def record_client_event(self, level: str, message: str) -> None:
        """将浏览器遥测事件写入统一工具日志，便于关联本机 UDP/WS 状态。"""
        level = level.upper()
        getattr(LOGGER, {"WARNING": "warning", "ERROR": "error"}.get(level, "info"))("实时观测浏览器：%s", message)

    def record_client_metrics(self, metrics: dict[str, Any]) -> None:
        """保存浏览器端的低频性能摘要，供现场远程区分数据与合成瓶颈。"""
        allowed = {
            "pose_packet_rate_hz": (0.0, 240.0), "pose_applied_rate_hz": (0.0, 240.0),
            "pose_message_age_ms": (0.0, 5000.0), "pose_source_age_ms": (0.0, 5000.0),
            "vehicle_render_rate_hz": (0.0, 240.0), "vehicle_frame_interval_ms": (0.0, 1000.0),
            "vehicle_long_frames": (0.0, 10000.0), "cloud_packet_rate_hz": (0.0, 120.0),
            "cloud_source_age_ms": (0.0, 5000.0),
            "costmap_packet_rate_hz": (0.0, 30.0), "costmap_source_age_ms": (0.0, 15000.0),
        }
        clean: dict[str, float] = {}
        for key, (minimum, maximum) in allowed.items():
            try:
                value = float(metrics.get(key))
            except (TypeError, ValueError):
                continue
            if minimum <= value <= maximum:
                clean[key] = round(value, 2)
        if not clean:
            raise ValueError("观测性能指标无效")
        with self._lock:
            self._client_metrics = clean
            self._client_metrics_at = time.monotonic()
            self._diagnose_client_metrics(clean)

    def _diagnose_client_metrics(self, metrics: dict[str, float]) -> None:
        """Record meaningful browser-side degradation edges, not every sample."""

        conditions = {
            "pose-stale": (
                metrics.get("pose_source_age_ms", 0.0) > 1200.0,
                f"实时位姿源超过 {metrics.get('pose_source_age_ms', 0.0):.0f} ms 未更新；请检查位姿预处理和本机遥测网关",
            ),
            "cloud-stale": (
                metrics.get("cloud_source_age_ms", 0.0) > 2000.0,
                f"实时点云源超过 {metrics.get('cloud_source_age_ms', 0.0):.0f} ms 未更新；请检查点云发布和 live_preprocessor_cloud.log",
            ),
            "costmap-stale": (
                metrics.get("costmap_source_age_ms", 0.0) > 7000.0,
                f"局部代价地图源超过 {metrics.get('costmap_source_age_ms', 0.0):.0f} ms 未更新；请检查 /local_costmap/costmap、map←odom TF 与 live_preprocessor_costmap.log",
            ),
            "render-slow": (
                metrics.get("pose_applied_rate_hz", 0.0) >= 15.0 and metrics.get("vehicle_render_rate_hz", 0.0) < 15.0,
                f"浏览器车体渲染偏慢：render={metrics.get('vehicle_render_rate_hz', 0.0):.1f} Hz，pose={metrics.get('pose_applied_rate_hz', 0.0):.1f} Hz；请检查浏览器性能或前端合成负载",
            ),
        }
        for key, (active, detail) in conditions.items():
            if active and key not in self._client_metric_alerts:
                self._client_metric_alerts.add(key)
                LOGGER.warning("实时观测性能诊断：%s", detail)
            elif not active and key in self._client_metric_alerts:
                self._client_metric_alerts.remove(key)
                LOGGER.info("实时观测性能已恢复：%s", key)

    def stop(self) -> None:
        with self._lifecycle_lock:
            with self._lock:
                preprocessors = list(self._preprocessor_processes.values())
                self._preprocessor_processes = {}
                if self._idle_timer:
                    self._idle_timer.cancel()
                    self._idle_timer = None
            for preprocessor in preprocessors:
                if preprocessor.poll() is not None:
                    continue
                try:
                    os.killpg(preprocessor.pid, signal.SIGTERM)
                    preprocessor.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(preprocessor.pid, signal.SIGKILL)
                        # SIGKILL 后同样必须 wait，避免 Popen 在极端路径留下僵尸。
                        preprocessor.wait(timeout=1)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            self._map_snapshot.stop()
            # 先终止 UDP 生产者，再关闭接收网关，避免正常停止过程产生“UDP send failed”
            # 误报，也不会留下写向已关闭端口的后台线程。
            self._telemetry.stop()

    def _preprocessor_running(self, kind: str) -> bool:
        with self._lock:
            process = self._preprocessor_processes.get(kind)
            return process is not None and process.poll() is None

    def _start_preprocessor(self) -> None:
        """以独立进程启动点云、位姿与 costmap 流，避免大帧互相阻塞。"""
        target = self._preprocessor_path
        if target is None or not target.is_file():
            raise ObservationError(f"实时预处理节点不可用：{target or '未配置'}")
        definitions = {
            # collision_voxel_layer 已在自动驾驶链路完成稀疏化；网页旁路在不超过
            # 3000 点协议上限时不再二次抽稀，超过上限才均匀取样。原生 Livox
            # 回退流始终服从同一预算。
            "cloud": ["-r", "__node:=ry_aletheia_live_cloud", "-p", "enable_cloud:=true", "-p", "enable_pose:=false", "-p", "enable_costmap:=false", "-p", "preserve_primary_density:=true", "-p", "max_points:=3000", "-p", "rate_hz:=10.0", "-p", "max_input_age_ms:=140", "-p", f"telemetry_udp_port:={TelemetryGateway.UDP_PORT}"],
            "pose": ["-r", "__node:=ry_aletheia_live_pose", "-p", "enable_cloud:=false", "-p", "enable_pose:=true", "-p", "enable_costmap:=false", "-p", "pose_rate_hz:=60.0", "-p", "max_pose_age_ms:=250", "-p", f"telemetry_udp_port:={TelemetryGateway.POSE_UDP_PORT}"],
            "costmap": ["-r", "__node:=ry_aletheia_live_costmap", "-p", "enable_cloud:=false", "-p", "enable_pose:=false", "-p", "enable_costmap:=true", "-p", "max_costmap_age_ms:=5000", "-p", f"telemetry_udp_port:={TelemetryGateway.COSTMAP_UDP_PORT}"],
        }
        for kind, arguments in definitions.items():
            if self._preprocessor_running(kind):
                continue
            try:
                log = (self.log_dir / f"live_preprocessor_{kind}.log").open("ab", buffering=0)
                process = subprocess.Popen([str(target), "--ros-args", *arguments], cwd=self.maps_dir.parent, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True, env=self._ros_environment())
                log.close()
                with self._lock:
                    self._preprocessor_processes[kind] = process
                label = {"cloud": "点云", "pose": "位姿", "costmap": "局部代价地图"}[kind]
                LOGGER.info("已启动 Aletheia 轻量%s流：pid=%s", label, process.pid)
            except OSError as exc:
                try:
                    log.close()
                except (OSError, UnboundLocalError):
                    pass
                label = {"cloud": "点云", "pose": "位姿", "costmap": "局部代价地图"}[kind]
                raise ObservationError(f"实时{label}预处理启动失败：{exc}") from exc

    def maps(self) -> list[dict[str, Any]]:
        """读取已经缓存的地图元数据，不读取 PGM 像素，不触发 ROS2 通信。"""
        if not self.maps_dir.is_dir():
            return []
        assets = []
        for target in sorted(self.maps_dir.iterdir(), key=lambda item: item.stat().st_mtime_ns if item.exists() else 0, reverse=True):
            if not target.is_dir() or len(target.name) != 16:
                continue
            try:
                asset = self._cached_asset(target)
                if asset:
                    assets.append({"id": asset.id, "label": asset.label, "resolution": asset.resolution, "width": asset.width, "height": asset.height, "updated_at": int(target.stat().st_mtime)})
            except OSError:
                continue
        return assets[:24]

    def active_map_id(self) -> str | None:
        """返回轨迹采集器最近确认的实际 ROS 地图，不触发 ROS2 查询。"""
        marker = self.maps_dir / "active_map.json"
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            asset_id = payload.get("asset_id")
            if isinstance(asset_id, str) and len(asset_id) == 16 and all(char in "0123456789abcdef" for char in asset_id):
                return asset_id if (self.maps_dir / asset_id / "map.pgm").is_file() else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        return None

    def active_task_map_path(self) -> Path | None:
        """Return the already verified active YAML identity without ROS I/O.

        This is a rendering-time optimization only.  Navigation still calls
        :meth:`verify_active_task_map` immediately before it sends a goal.
        """
        active_id = self.active_map_id()
        with self._lock:
            verified = self._active_task_map
        if active_id is None or verified is None or verified[0] != active_id:
            return None
        return verified[2]

    def active_manual_map_id(self) -> str | None:
        """Return the server-only identity of the strictly verified live map."""
        active_id = self.active_map_id()
        with self._lock:
            verified = self._active_task_map
        if active_id is None or verified is None or verified[0] != active_id:
            return None
        return verified[1]

    def verify_active_manual_map_id(self, candidate_map_id: str) -> tuple[bool, str]:
        """Recheck map_server and OccupancyGrid before a marker navigation goal."""
        active_id = self.active_manual_map_id()
        if active_id is None or candidate_map_id != active_id:
            return False, "当前地图不匹配"
        with self._lock:
            verified_map = self._active_task_map
        if verified_map is None or verified_map[1] != candidate_map_id:
            return False, "当前地图尚未确认"
        active_yaml = self._map_server_yaml_path()
        if active_yaml is None:
            return False, "当前地图尚未确认"
        try:
            if active_yaml.resolve() != verified_map[2].resolve():
                return False, "当前地图不匹配"
        except OSError:
            return False, "当前地图不匹配"
        if self.active_map_id() != verified_map[0]:
            return False, "当前地图不匹配"
        active = self._cached_asset(self.maps_dir / verified_map[0])
        if (
            active is None
            or active.resolution is None
            or active.width is None
            or active.height is None
            or active.origin is None
            or len(active.origin) < 2
        ):
            return False, "当前地图尚未确认"
        try:
            strict_asset = self._map_server_asset(
                MapAssetCache(self.maps_dir), active.resolution, active.width, active.height, active.origin,
            )
        except (MapAssetError, OSError, ValueError):
            strict_asset = None
        if strict_asset is None or strict_asset.id != candidate_map_id:
            return False, "当前地图尚未确认"
        return True, "当前地图匹配"

    def verify_active_task_map(self, candidate_map: Path) -> tuple[bool, str]:
        """Fail closed unless a task's map is the current live map_server map.

        A task path alone is not sufficient: the currently displayed OccupancyGrid
        cache must exist and retain matching geometry.  This keeps task-start
        navigation from crossing a map/floor transition based on stale UI state.
        """
        try:
            candidate = Path(candidate_map).expanduser().resolve()
        except OSError:
            return False, "当前地图不匹配"
        active_yaml = self._map_server_yaml_path()
        if active_yaml is None:
            return False, "当前地图尚未确认"
        try:
            if candidate != active_yaml.resolve():
                return False, "当前地图不匹配"
        except OSError:
            return False, "当前地图不匹配"
        active_id = self.active_map_id()
        if active_id is None:
            return False, "当前地图尚未确认"
        active = self._cached_asset(self.maps_dir / active_id)
        if (
            active is None
            or active.resolution is None
            or active.width is None
            or active.height is None
            or active.origin is None
            or len(active.origin) < 2
        ):
            return False, "当前地图尚未确认"
        try:
            verified = self._map_server_asset(
                MapAssetCache(self.maps_dir), active.resolution, active.width, active.height, active.origin,
            )
        except (MapAssetError, OSError, ValueError):
            verified = None
        if verified is None:
            return False, "当前地图尚未确认"
        return True, "当前地图匹配"

    def preview(self, asset_id: str) -> bytes:
        if not asset_id or len(asset_id) != 16 or any(char not in "0123456789abcdef" for char in asset_id):
            raise ObservationError("地图标识不合法")
        target = (self.maps_dir / asset_id).resolve()
        root = self.maps_dir.resolve()
        if target.parent != root or not target.is_dir():
            raise ObservationError("地图缓存不存在")
        preview = target / "observation_preview.svg"
        source = target / "map.pgm"
        if preview.is_file() and preview.stat().st_mtime_ns >= source.stat().st_mtime_ns:
            return preview.read_bytes()
        asset = self._cached_asset(target)
        if not asset:
            raise ObservationError("地图缓存元数据不完整")
        try:
            width, height, pixels = _read_pgm(Path(asset.cache_image))
        except (OSError, TrajectoryRenderError) as exc:
            raise ObservationError(f"无法读取地图预览：{exc}") from exc
        encoded = base64.b64encode(_png_gray(width, height, pixels)).decode("ascii")
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<image width="{width}" height="{height}" href="data:image/png;base64,{encoded}"/></svg>'
        ).encode("utf-8")
        temporary = preview.with_suffix(".tmp")
        temporary.write_bytes(svg)
        os.replace(temporary, preview)
        return svg

    def preview_png(self, asset_id: str) -> bytes:
        """提供缓存的无损 PNG 底图，避免大尺寸 data-URI SVG 被浏览器拒绝。"""
        if not asset_id or len(asset_id) != 16 or any(char not in "0123456789abcdef" for char in asset_id):
            raise ObservationError("地图标识不合法")
        target = (self.maps_dir / asset_id).resolve()
        root = self.maps_dir.resolve()
        if target.parent != root or not target.is_dir():
            raise ObservationError("地图缓存不存在")
        preview, source = target / "observation_preview.png", target / "map.pgm"
        if preview.is_file() and preview.stat().st_mtime_ns >= source.stat().st_mtime_ns:
            return preview.read_bytes()
        asset = self._cached_asset(target)
        if not asset:
            raise ObservationError("地图缓存元数据不完整")
        try:
            width, height, pixels = _read_pgm(Path(asset.cache_image))
        except (OSError, TrajectoryRenderError) as exc:
            raise ObservationError(f"无法读取地图预览：{exc}") from exc
        png = _png_gray(width, height, pixels)
        temporary = preview.with_suffix(".tmp")
        temporary.write_bytes(png)
        os.replace(temporary, preview)
        return png

    def layers(self, asset_id: str) -> dict[str, Any]:
        """返回当前缓存地图可安全公开给只读观测页的矢量图层。"""
        if not asset_id or len(asset_id) != 16 or any(char not in "0123456789abcdef" for char in asset_id):
            raise ObservationError("地图标识不合法")
        target = (self.maps_dir / asset_id).resolve()
        if target.parent != self.maps_dir.resolve() or not target.is_dir():
            raise ObservationError("地图缓存不存在")
        asset = self._cached_asset(target)
        if asset is None:
            raise ObservationError("地图缓存元数据不完整")
        frame_id = "map"
        # active_map.json 由带 TRANSIENT_LOCAL QoS 的轨迹记录器写入，包含实际
        # OccupancyGrid 的 frame_id。实时观测页可据此复用缓存底图并正确投影点云。
        try:
            marker = json.loads((self.maps_dir / "active_map.json").read_text(encoding="utf-8"))
            if marker.get("asset_id") == asset.id and isinstance(marker.get("frame_id"), str) and marker["frame_id"].strip():
                frame_id = marker["frame_id"].strip()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        wall_asset = asset
        # OccupancyGrid 快照的内容哈希可能因运行时栅格的微小变化而产生新目录；
        # 若快照落盘时因多个同几何地图而无法安全推断墙文件，不应因此丢失
        # map_server 已明确选中的当前地图约束。仅对活动快照、且只在其自身没有
        # 墙文件时，复用 _map_server_asset 的严格元数据校验结果，绝不扫描或猜测
        # 历史快照的墙来源。
        if (
            asset.id == self.active_map_id()
            and not asset.cache_walls
            and asset.resolution is not None
            and asset.width is not None
            and asset.height is not None
            and asset.origin is not None
        ):
            verified = self._map_server_asset(
                MapAssetCache(self.maps_dir), asset.resolution, asset.width, asset.height, asset.origin,
            )
            if verified is not None:
                wall_asset = verified
        return {
            "map_id": asset.id,
            "map": {
                "resolution": asset.resolution,
                "width": asset.width,
                "height": asset.height,
                "origin": asset.origin,
                "frame_id": frame_id,
            },
            "virtual_walls": MapAssetCache.virtual_walls(wall_asset),
        }

    def live_layers(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """以当前 ROS ``/map`` 元数据按需解析虚拟墙。

        地图仍由既有缓存与 ``active_map.json`` 提供；实时点云/位姿迁移不触碰
        OccupancyGrid 的缓存和虚拟墙匹配机制。
        仅在地图签名变化时由浏览器调用本方法；本方法只读取受控目录内的 YAML/PGM
        头部，并把结果缓存，避免地图显示期间产生周期性磁盘扫描。
        """
        try:
            resolution = float(metadata["resolution"])
            width, height = int(metadata["width"]), int(metadata["height"])
            origin = metadata["origin"]
            if not isinstance(origin, list) or len(origin) < 2:
                raise ValueError("origin")
            origin = [float(origin[0]), float(origin[1])]
            frame_id = str(metadata.get("frame_id") or "map").strip() or "map"
        except (KeyError, TypeError, ValueError) as exc:
            raise ObservationError("实时地图元数据无效") from exc
        # OccupancyGrid.resolution 是 float32；0.05 会在浏览器端还原为
        # 0.050000000745...。用与地图匹配容差相容的稳定键，避免同一张地图
        # 因二进制浮点尾差分别得到“已匹配”和“未匹配”的缓存状态。
        runtime_map_id = self.active_map_id()
        signature = f"{runtime_map_id or '-'}|{width}|{height}|{round(resolution, 8):.8f}|{origin[0]:.12g}|{origin[1]:.12g}|{frame_id}"
        with self._lock:
            cached = self._live_map_matches.get(signature)
            verified = self._active_task_map
        if cached is not None and runtime_map_id is not None and verified is not None and verified[0] == runtime_map_id:
            return cached
        cache = MapAssetCache(self.maps_dir)
        try:
            # nav2 map_server 的 yaml_filename 是当前真实生效地图的权威来源。
            # 先验证其 YAML/PGM 元数据与浏览器收到的 /map 一致，再读取同目录的
            # map_walls.yaml；不能因参数短暂滞后把上一张地图的墙画到当前地图上。
            verified_asset = self._map_server_asset(cache, resolution, width, height, origin)
            asset = verified_asset
            if asset is None:
                asset = cache.find_matching_map(resolution=resolution, width=width, height=height, origin=origin)
        except MapAssetError as exc:
            raise ObservationError(str(exc)) from exc
        if asset is None:
            with self._lock:
                self._active_task_map = None
            result = {"matched": False, "virtual_walls": []}
        else:
            # 实时快照拥有 active_map.json。没有快照时仅为离线/直接调用保留
            # 静态地图兜底；绝不能在正常观测期间把静态 ID 写回并覆盖运行时 ID。
            if runtime_map_id is None:
                self._write_live_map_marker(asset, frame_id)
                runtime_map_id = asset.id
            with self._lock:
                if verified_asset is not None and runtime_map_id is not None:
                    try:
                        runtime_asset = self._cached_asset(self.maps_dir / runtime_map_id)
                        if runtime_asset is None:
                            raise OSError("active runtime map cache missing")
                        self._active_task_map = (
                            runtime_map_id,
                            verified_asset.id,
                            Path(verified_asset.source_yaml).resolve(),
                        )
                    except OSError:
                        self._active_task_map = None
                else:
                    # A metadata-only fallback can draw walls, but it cannot
                    # authorize task points from a similarly shaped map.
                    self._active_task_map = None
            result = {
                "matched": True,
                "map_id": asset.id,
                "label": asset.label,
                "virtual_walls": MapAssetCache.virtual_walls(asset),
            }
        with self._lock:
            # 成功匹配的静态地图可以长期复用；反之，map_server 启动、切图和
            # 缓存落盘的短暂窗口都可能造成一次性未命中。绝不能把该阴性结果
            # 永久缓存，否则页面即使随后具备地图与墙文件也不会再补画虚拟墙。
            if result["matched"]:
                self._live_map_matches[signature] = result
                # 只需记住最近少量地图，P1/P2/P3 切换不会反复扫描，也防止长期运行增长。
                if len(self._live_map_matches) > 12:
                    self._live_map_matches.pop(next(iter(self._live_map_matches)))
            else:
                self._live_map_matches.pop(signature, None)
        return result

    def _map_server_asset(
        self, cache: MapAssetCache, resolution: float, width: int, height: int, origin: list[float],
    ) -> CachedMapAsset | None:
        """Return the map_server-selected asset only when it matches live /map metadata."""
        yaml_path = self._map_server_yaml_path()
        if yaml_path is None:
            return None
        try:
            asset = cache._cache_one(yaml_path)
        except MapAssetError:
            return None
        if asset.resolution is None or asset.width is None or asset.height is None or not asset.origin:
            return None
        if asset.width != width or asset.height != height:
            return None
        tolerance = max(1e-6, resolution * 1e-3)
        if abs(asset.resolution - resolution) > max(1e-9, abs(resolution) * 1e-6):
            return None
        if abs(asset.origin[0] - origin[0]) > tolerance or abs(asset.origin[1] - origin[1]) > tolerance:
            return None
        return asset

    def _map_server_yaml_path(self) -> Path | None:
        """Read the active map path without letting a slow ROS CLI erase confirmation."""
        now = time.monotonic()
        with self._lock:
            if now - self._map_server_yaml_checked_at < self.MAP_SERVER_YAML_REFRESH_S:
                return self._map_server_yaml
            previous = self._map_server_yaml
            previous_verified_at = self._map_server_yaml_verified_at
        ros2 = shutil.which("ros2")
        candidate: Path | None = None
        fresh_verification = False
        if ros2:
            try:
                result = subprocess.run(
                    [ros2, "param", "get", "/map_server", "yaml_filename"],
                    capture_output=True, text=True, timeout=self.MAP_SERVER_QUERY_TIMEOUT_S, check=False, env=self._ros_environment(),
                )
                match = re.search(r"^String value is:\s*(.+?)\s*$", result.stdout, re.MULTILINE)
                if result.returncode == 0 and match:
                    path = Path(match.group(1)).expanduser().resolve()
                    root = MapAssetCache.ALLOWED_ROOTS[0].resolve()
                    if path.is_file() and path.is_relative_to(root):
                        candidate = path
                        fresh_verification = True
            except (OSError, subprocess.TimeoutExpired):
                pass
        if candidate is None and previous is not None and now - previous_verified_at <= self.MAP_SERVER_YAML_FALLBACK_S:
            LOGGER.warning("map_server 地图参数查询暂时不可用，继续使用最近已核验地图")
            candidate = previous
        with self._lock:
            self._map_server_yaml_checked_at = now
            self._map_server_yaml = candidate
            if fresh_verification:
                self._map_server_yaml_verified_at = now
        return candidate

    def _write_live_map_marker(self, asset: CachedMapAsset, frame_id: str) -> None:
        target = self.maps_dir / "active_map.json"
        payload = {
            "asset_id": asset.id, "label": asset.label, "map_epoch": 0,
            "updated_at_ns": time.time_ns(), "frame_id": frame_id,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, target)

    def _stop_if_idle(self, settings: RobotSettings) -> None:
        # 该方法既由 status() 调用，也由 Timer 线程直接调用；必须与 heartbeat、
        # start/stop 共享同一生命周期锁，避免刚刷新心跳的页面被旧计时器停掉。
        with self._lifecycle_lock:
            options = self._options(settings)
            if self._telemetry.status()["online"] and self._last_heartbeat and time.monotonic() - self._last_heartbeat > options["idle_stop_seconds"]:
                self.stop()

    def _schedule_idle_stop(self, settings: RobotSettings) -> None:
        """浏览器断开后仍能自动回收遥测子进程，不依赖下一次 HTTP 访问。"""
        with self._lock:
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
            delay = self._options(settings)["idle_stop_seconds"] + 1
            self._idle_timer = threading.Timer(delay, lambda: self._stop_if_idle(settings))
            self._idle_timer.daemon = True
            self._idle_timer.start()

    @staticmethod
    def _ros_environment() -> dict[str, str]:
        """保留部署者提供的 ROS 环境；遥测不注入或覆盖任何 ROS 前缀。"""
        return os.environ.copy()

    @staticmethod
    def _options(settings: RobotSettings) -> dict[str, Any]:
        defaults = {"enabled": False, "idle_stop_seconds": 45}
        defaults.update(settings.live_observation)
        return defaults

    def _reap(self) -> None:
        with self._lock:
            for kind, process in list(self._preprocessor_processes.items()):
                if process.poll() is None:
                    continue
                LOGGER.warning(
                    "Aletheia 轻量%s流已退出：pid=%s code=%s；实时遥测已停止该流发送；末尾日志：%s",
                    "点云" if kind == "cloud" else "位姿", process.pid, process.returncode,
                    self._sidecar_log_tail(f"live_preprocessor_{kind}.log"),
                )
                del self._preprocessor_processes[kind]

    def _sidecar_log_tail(self, name: str) -> str:
        """Read a bounded tail from one fixed child-process diagnostic file."""
        if name not in {"live_preprocessor_cloud.log", "live_preprocessor_pose.log"}:
            return "（不允许读取的日志）"
        target = self.log_dir / name
        try:
            with target.open("rb") as source:
                source.seek(0, 2)
                source.seek(max(source.tell() - 1600, 0))
                text = source.read().decode("utf-8", errors="replace")
        except OSError:
            return "（预处理日志不可读）"
        return " ".join(text.splitlines()[-8:])[:1400] or "（预处理尚未输出日志）"

    @staticmethod
    def _cached_asset(target: Path) -> CachedMapAsset | None:
        yaml_path, image_path = target / "map.yaml", target / "map.pgm"
        if not yaml_path.is_file() or not image_path.is_file():
            return None
        image, resolution, origin = MapAssetCache._parse_metadata(yaml_path.read_text(encoding="utf-8"))
        if image != "map.pgm" or resolution is None or origin is None:
            return None
        width, height = MapAssetCache._pgm_dimensions(image_path)
        if width is None or height is None:
            return None
        walls_path = target / "map_walls.yaml"
        return CachedMapAsset(
            target.name, f"ROS 地图 {target.name[:6]}", "", str(yaml_path), str(image_path),
            resolution, origin, width, height, str(walls_path) if walls_path.is_file() else None,
        )
