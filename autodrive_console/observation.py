from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
import re
from pathlib import Path
from typing import Any

from .map_assets import CachedMapAsset, MapAssetCache
from .settings import RobotSettings
from .trajectory_render import TrajectoryRenderError, _png_gray, _read_pgm


LOGGER = logging.getLogger("ry_aletheia.observation")

# ROS 2 将任一路径段以下划线开头的话题视为内部（hidden）话题。实时观测页
# 仍会按明确名称订阅它们，但 RViz 的默认“按话题”列表不会把实现细节展示给操作者。
INTERNAL_LIVE_CLOUD_TOPIC = "/_aletheia/live_points"
INTERNAL_LIVE_POSE_TOPIC = "/_aletheia/live_pose"
DEFAULT_LIVE_CLOUD_SOURCE_TOPIC = "/collision_voxel_layer/points"


class ObservationError(RuntimeError):
    """实时观测的配置或受控进程状态不满足启动条件。"""


class ObservationManager:
    """按需管理 Aletheia 私有 Foxglove Bridge，并只读复用地图缓存。

    不订阅 ``/map``、``/odom`` 或点云。轨迹记录器仍是唯一的地图缓存生产者；
    实时数据由 Aletheia 自己创建的 Bridge 在观测页开启期间独立处理。为避免影响
    机器人上原有的 Foxglove Bridge，控制台绝不复用占用中的外部端口；受控进程仅在
    专用端口仅绑定本机回环地址，经控制台代理提供给浏览器，且在观测页空闲后自动退出。
    """

    _PACKAGE_CACHE_SECONDS = 15.0

    def __init__(self, maps_dir: Path, log_dir: Path, preprocessor_path: Path | None = None) -> None:
        self.maps_dir = maps_dir
        self.log_dir = log_dir
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._preprocessor_processes: dict[str, subprocess.Popen] = {}
        self._preprocessor_path = preprocessor_path
        self._started_by_console = False
        self._last_heartbeat = 0.0
        self._idle_timer: threading.Timer | None = None
        self._package_checked_at = 0.0
        self._package_available: bool | None = None
        self._package_detail = "尚未检查"
        self._live_map_matches: dict[str, dict[str, Any]] = {}
        self._map_server_yaml_checked_at = 0.0
        self._map_server_yaml: Path | None = None
        self._client_metrics: dict[str, Any] = {}
        self._client_metrics_at = 0.0

    def status(self, settings: RobotSettings) -> dict[str, Any]:
        self._stop_if_idle(settings)
        self._reap()
        observation = self._options(settings)
        package_available, package_detail = self._bridge_package()
        bridge_online = self._port_open("127.0.0.1", observation["bridge_port"])
        process_running = self._process is not None and self._process.poll() is None
        cloud_preprocessor_running = self._preprocessor_running("cloud")
        pose_preprocessor_running = self._preprocessor_running("pose")
        return {
            "enabled": observation["enabled"],
            "map_source": observation["map_source"],
            "embed_configured": bool(observation["embed_url"]),
            "embed_url": observation["embed_url"],
            "bridge": {
                "bind_address": "0.0.0.0", "port": observation["bridge_port"],
                "access_mode": "direct",
                "online": bridge_online, "managed": process_running and self._started_by_console,
                "cloud_topic": INTERNAL_LIVE_CLOUD_TOPIC if cloud_preprocessor_running else DEFAULT_LIVE_CLOUD_SOURCE_TOPIC,
                "pose_topic": INTERNAL_LIVE_POSE_TOPIC if pose_preprocessor_running else "",
                "package_available": package_available, "detail": package_detail,
            },
            "maps": self.maps(),
            "active_map_id": self.active_map_id(),
            "idle_stop_seconds": observation["idle_stop_seconds"],
            "preprocessor": {"available": bool(self._preprocessor_path and self._preprocessor_path.is_file()), "managed": cloud_preprocessor_running or pose_preprocessor_running, "cloud_managed": cloud_preprocessor_running, "pose_managed": pose_preprocessor_running},
            "client_metrics": {**self._client_metrics, "age_seconds": round(max(0.0, time.monotonic() - self._client_metrics_at), 2)} if self._client_metrics_at else None,
        }

    def start(self, settings: RobotSettings) -> dict[str, Any]:
        options = self._options(settings)
        if not options["enabled"]:
            raise ObservationError("实时观测尚未在运行配置中启用")
        self._reap()
        self._last_heartbeat = time.monotonic()
        self._schedule_idle_stop(settings)
        if self._port_open("127.0.0.1", options["bridge_port"]):
            if self._process is not None and self._process.poll() is None and self._started_by_console:
                return self.status(settings)
            message = (
                f"观测端口 {options['bridge_port']} 已被外部进程占用。"
                "为避免影响原有 Foxglove Bridge，请在运行配置中改用未被小车系统占用的空闲端口（默认 8767）后重试。"
            )
            LOGGER.error("实时观测启动被拒绝：%s 占用信息：%s", message, self._listener_detail(options["bridge_port"]))
            raise ObservationError(message)
        available, detail = self._bridge_package()
        if not available:
            message = f"未检测到 foxglove_bridge：{detail}"
            LOGGER.error("实时观测启动失败：%s", message)
            raise ObservationError(message)
        private_bridge = self._private_bridge_executable()
        ros2 = shutil.which("ros2") if private_bridge is None else None
        if private_bridge is None and not ros2:
            message = "未检测到 ros2 命令；请使用机器人 ROS2 环境启动控制台"
            LOGGER.error("实时观测启动失败：%s", message)
            raise ObservationError(message)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._start_preprocessor()
        log_file = self.log_dir / "foxglove_bridge.log"
        parameters = [
            f"port:={options['bridge_port']}", "address:=0.0.0.0", "tls:=false",
            # 图像与点云只用于实时观测，积压旧数据没有价值。Bridge 3.2.x 支持
            # 限制 ROS 订阅 QoS 队列深度；固定为 1，优先把最新帧交给浏览器。
            "max_qos_depth:=1",
            # 预处理流使用 /_aletheia/* 避免成为 RViz 的业务话题；Bridge 默认
            # 不公告 hidden 话题，必须显式开启，否则网页永远收不到点云/位姿频道。
            "include_hidden:=true",
        ]
        if private_bridge is not None:
            # 完整离线包的 Bridge 直接执行，既不依赖系统是否安装该包，也不让
            # 系统 ros2 CLI 按环境顺序挑中错误版本。参数与官方 launch 文件等价。
            command = [str(private_bridge), "--ros-args", *[part for item in parameters for part in ("-p", item)]]
        else:
            command = [ros2, "launch", "foxglove_bridge", "foxglove_bridge_launch.xml", *parameters]
        output = None
        try:
            output = log_file.open("ab", buffering=0)
            self._process = subprocess.Popen(
                command,
                cwd=self.maps_dir.parent, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True, env=self._bridge_environment(),
            )
            self._started_by_console = True
            LOGGER.info("已启动 Aletheia 私有 Foxglove Bridge：pid=%s port=%s command=%s", self._process.pid, options["bridge_port"], " ".join(command))
            LOGGER.warning(
                "Aletheia 私有 Foxglove Bridge 已监听 0.0.0.0:%s；"
                "同一受控测试网络中的浏览器可直连该端口，请勿暴露到不受信任网络。",
                options["bridge_port"],
            )
            # 启动后只做一次轻量诊断，方便在工具日志中直接看到 ROS/Bridge 的启动输出。
            diagnostic = threading.Timer(1.2, self._log_startup_diagnostic)
            diagnostic.daemon = True
            diagnostic.start()
        except OSError as exc:
            message = f"无法启动 Foxglove Bridge：{exc}"
            LOGGER.error("实时观测启动失败：%s", message)
            raise ObservationError(message) from exc
        finally:
            if output is not None:
                output.close()
        return self.status(settings)

    def heartbeat(self, settings: RobotSettings) -> dict[str, Any]:
        self._last_heartbeat = time.monotonic()
        if self._started_by_console:
            self._schedule_idle_stop(settings)
        return self.status(settings)

    def record_client_event(self, level: str, message: str) -> None:
        """将浏览器连接事件与当刻 Bridge 输出关联，避免人工进入终端查日志。"""
        level = level.upper()
        if level == "ERROR":
            LOGGER.error("实时观测浏览器：%s；Bridge 日志末尾：%s", message, self._bridge_log_tail())
            return
        getattr(LOGGER, "warning" if level == "WARNING" else "info")("实时观测浏览器：%s", message)

    def record_client_metrics(self, metrics: dict[str, Any]) -> None:
        """保存浏览器端的低频性能摘要，供现场远程区分数据与合成瓶颈。"""
        allowed = {
            "pose_packet_rate_hz": (0.0, 240.0), "pose_applied_rate_hz": (0.0, 240.0),
            "pose_message_age_ms": (0.0, 5000.0), "pose_source_age_ms": (0.0, 5000.0),
            "vehicle_render_rate_hz": (0.0, 240.0), "vehicle_frame_interval_ms": (0.0, 1000.0),
            "vehicle_long_frames": (0.0, 10000.0), "cloud_packet_rate_hz": (0.0, 120.0),
            "cloud_source_age_ms": (0.0, 5000.0),
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

    def stop(self) -> None:
        with self._lock:
            process = self._process
            preprocessors = list(self._preprocessor_processes.values())
            self._process = None
            self._preprocessor_processes = {}
            managed = self._started_by_console
            self._started_by_console = False
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
        if process and managed and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=4)
                LOGGER.info("已停止 Aletheia 私有 Foxglove Bridge：pid=%s", process.pid)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    LOGGER.warning("Foxglove Bridge 未在宽限期内退出，已强制停止：pid=%s", process.pid)
                except OSError:
                    pass
        for preprocessor in preprocessors:
            if preprocessor.poll() is not None:
                continue
            try:
                os.killpg(preprocessor.pid, signal.SIGTERM)
                preprocessor.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(preprocessor.pid, signal.SIGKILL)
                except OSError:
                    pass

    def _preprocessor_running(self, kind: str) -> bool:
        process = self._preprocessor_processes.get(kind)
        return process is not None and process.poll() is None

    def _start_preprocessor(self) -> None:
        """以独立进程启动点云与位姿流，避免点云转换阻塞车体位姿。"""
        target = self._preprocessor_path
        if target is None or not target.is_file():
            LOGGER.warning("实时预处理节点不可用，回退订阅 %s 和 TF：%s", DEFAULT_LIVE_CLOUD_SOURCE_TOPIC, target or "未配置")
            return
        definitions = {
            "cloud": ["-r", "__node:=ry_aletheia_live_cloud", "-p", "enable_cloud:=true", "-p", "enable_pose:=false", "-p", f"output_topic:={INTERNAL_LIVE_CLOUD_TOPIC}", "-p", "max_points:=3000", "-p", "max_input_age_ms:=140"],
            "pose": ["-r", "__node:=ry_aletheia_live_pose", "-p", "enable_cloud:=false", "-p", "enable_pose:=true", "-p", f"pose_topic:={INTERNAL_LIVE_POSE_TOPIC}", "-p", "pose_rate_hz:=60.0", "-p", "max_pose_age_ms:=250"],
        }
        for kind, arguments in definitions.items():
            if self._preprocessor_running(kind):
                continue
            try:
                log = (self.log_dir / f"live_preprocessor_{kind}.log").open("ab", buffering=0)
                process = subprocess.Popen([str(target), "--ros-args", *arguments], cwd=self.maps_dir.parent, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True, env=self._bridge_environment())
                log.close()
                self._preprocessor_processes[kind] = process
                LOGGER.info("已启动 Aletheia 轻量%s流：pid=%s", "点云" if kind == "cloud" else "位姿", process.pid)
            except OSError as exc:
                LOGGER.warning("实时%s流启动失败：%s", "点云" if kind == "cloud" else "位姿", exc)

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
        return {
            "map_id": asset.id,
            "map": {
                "resolution": asset.resolution,
                "width": asset.width,
                "height": asset.height,
                "origin": asset.origin,
                "frame_id": frame_id,
            },
            "virtual_walls": MapAssetCache.virtual_walls(asset),
        }

    def live_layers(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """以当前 ROS ``/map`` 元数据按需解析虚拟墙。

        浏览器已经直连 Bridge 接收地图，后端不再重复订阅或缓存 OccupancyGrid。
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
        signature = f"{width}|{height}|{round(resolution, 8):.8f}|{origin[0]:.12g}|{origin[1]:.12g}|{frame_id}"
        with self._lock:
            cached = self._live_map_matches.get(signature)
        if cached is not None:
            return cached
        cache = MapAssetCache(self.maps_dir)
        try:
            # nav2 map_server 的 yaml_filename 是当前真实生效地图的权威来源。
            # 先验证其 YAML/PGM 元数据与浏览器收到的 /map 一致，再读取同目录的
            # map_walls.yaml；不能因参数短暂滞后把上一张地图的墙画到当前地图上。
            asset = self._map_server_asset(cache, resolution, width, height, origin)
            if asset is None:
                asset = cache.find_matching_map(resolution=resolution, width=width, height=height, origin=origin)
        except MapAssetError as exc:
            raise ObservationError(str(exc)) from exc
        if asset is None:
            result = {"matched": False, "virtual_walls": []}
        else:
            # 同一个静态地图可直接作为观测页的活动标记；后续轨迹记录启动后会用
            # 运行时栅格缓存覆盖该标记，不会影响轨迹的实际地图判定。
            self._write_live_map_marker(asset, frame_id)
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
        """Read the active map path with a short cache; never scans arbitrary directories."""
        now = time.monotonic()
        with self._lock:
            if now - self._map_server_yaml_checked_at < 2.0:
                return self._map_server_yaml
        ros2 = shutil.which("ros2")
        candidate: Path | None = None
        if ros2:
            try:
                result = subprocess.run(
                    [ros2, "param", "get", "/map_server", "yaml_filename"],
                    capture_output=True, text=True, timeout=2, check=False, env=self._bridge_environment(),
                )
                match = re.search(r"^String value is:\s*(.+?)\s*$", result.stdout, re.MULTILINE)
                if result.returncode == 0 and match:
                    path = Path(match.group(1)).expanduser().resolve()
                    root = MapAssetCache.ALLOWED_ROOTS[0].resolve()
                    if path.is_file() and path.is_relative_to(root):
                        candidate = path
            except (OSError, subprocess.TimeoutExpired):
                pass
        with self._lock:
            self._map_server_yaml_checked_at = now
            self._map_server_yaml = candidate
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
        options = self._options(settings)
        if self._started_by_console and self._last_heartbeat and time.monotonic() - self._last_heartbeat > options["idle_stop_seconds"]:
            self.stop()

    def _schedule_idle_stop(self, settings: RobotSettings) -> None:
        """浏览器断开后仍能自动回收 Bridge，不依赖下一次 HTTP 访问。"""
        with self._lock:
            if self._idle_timer:
                self._idle_timer.cancel()
            delay = self._options(settings)["idle_stop_seconds"] + 1
            self._idle_timer = threading.Timer(delay, lambda: self._stop_if_idle(settings))
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _bridge_package(self) -> tuple[bool, str]:
        with self._lock:
            if time.monotonic() - self._package_checked_at < self._PACKAGE_CACHE_SECONDS and self._package_available is not None:
                return self._package_available, self._package_detail
            private_bridge = self._private_bridge_executable()
            if private_bridge is not None:
                self._package_available = True
                self._package_detail = f"已检测到 Aletheia 私有 Foxglove Bridge（{private_bridge}）"
            else:
                ros2 = shutil.which("ros2")
            if private_bridge is None and not ros2:
                self._package_available, self._package_detail = False, "未找到 ros2 命令"
            elif private_bridge is None:
                try:
                    result = subprocess.run(
                        [ros2, "pkg", "prefix", "foxglove_bridge"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                        timeout=3, check=False, env=self._bridge_environment(),
                    )
                    self._package_available = result.returncode == 0
                    if self._package_available:
                        source = "Aletheia 私有运行组件" if self._private_bridge_prefix() else "系统 ROS2 环境"
                        self._package_detail = f"已检测到 foxglove_bridge（{source}）"
                    else:
                        self._package_detail = result.stderr.strip() or "当前 ROS2 环境未安装 foxglove_bridge"
                except (OSError, subprocess.TimeoutExpired) as exc:
                    self._package_available, self._package_detail = False, str(exc)
            self._package_checked_at = time.monotonic()
            return self._package_available, self._package_detail

    def _private_bridge_prefix(self) -> Path | None:
        """返回随 Aletheia 安装的私有 ROS 前缀，绝不修改系统 /opt/ros。"""
        prefix = self.maps_dir.parent / "runtime" / "foxglove_bridge"
        marker = prefix / "share" / "ament_index" / "resource_index" / "packages" / "foxglove_bridge"
        return prefix if marker.is_file() else None

    def _private_bridge_executable(self) -> Path | None:
        prefix = self._private_bridge_prefix()
        if prefix is None:
            return None
        executable = prefix / "lib" / "foxglove_bridge" / "foxglove_bridge"
        return executable if executable.is_file() and os.access(executable, os.X_OK) else None

    def _bridge_environment(self) -> dict[str, str]:
        """只为 Bridge 子进程注入私有前缀，控制台和机器人 ROS 图保持原环境。"""
        env = os.environ.copy()
        prefix = self._private_bridge_prefix()
        if prefix is None:
            return env

        def prepend(name: str, value: str) -> None:
            current = env.get(name, "")
            env[name] = f"{value}{os.pathsep}{current}" if current else value

        prefix_text = str(prefix)
        prepend("AMENT_PREFIX_PATH", prefix_text)
        prepend("CMAKE_PREFIX_PATH", prefix_text)
        bin_dir = prefix / "bin"
        if bin_dir.is_dir():
            prepend("PATH", str(bin_dir))
        lib_dir = prefix / "lib"
        if lib_dir.is_dir():
            prepend("LD_LIBRARY_PATH", str(lib_dir))
        python_dir = prefix / "lib" / "python3.10" / "site-packages"
        if python_dir.is_dir():
            prepend("PYTHONPATH", str(python_dir))
        env.setdefault("ROS_VERSION", "2")
        env.setdefault("ROS_DISTRO", "humble")
        return env

    @staticmethod
    def _options(settings: RobotSettings) -> dict[str, Any]:
        defaults = {"enabled": False, "map_source": "foxglove", "embed_url": "", "bridge_port": 8767, "idle_stop_seconds": 45}
        defaults.update(settings.live_observation)
        return defaults

    def _reap(self) -> None:
        with self._lock:
            if self._process and self._process.poll() is not None:
                exit_code = self._process.returncode
                pid = self._process.pid
                self._process, self._started_by_console = None, False
                LOGGER.error(
                    "Aletheia 私有 Foxglove Bridge 已异常退出：pid=%s exit_code=%s；末尾日志：%s",
                    pid, exit_code, self._bridge_log_tail(),
                )
            for kind, process in list(self._preprocessor_processes.items()):
                if process.poll() is None:
                    continue
                LOGGER.warning("Aletheia 轻量%s流已退出：pid=%s code=%s；将启用对应回退", "点云" if kind == "cloud" else "位姿", process.pid, process.returncode)
                del self._preprocessor_processes[kind]

    def _log_startup_diagnostic(self) -> None:
        """受控 Bridge 启动后仅记录一次结果，不参与周期性状态查询。"""
        self._reap()
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                return
            pid = process.pid
        LOGGER.info("Foxglove Bridge 启动诊断：pid=%s；日志末尾：%s", pid, self._bridge_log_tail())

    def _bridge_log_tail(self) -> str:
        """仅在异常退出时读取日志末尾，避免常规状态轮询造成磁盘开销。"""
        target = self.log_dir / "foxglove_bridge.log"
        try:
            with target.open("rb") as source:
                source.seek(0, 2)
                source.seek(max(source.tell() - 1600, 0))
                text = source.read().decode("utf-8", errors="replace")
        except OSError:
            return "（Bridge 日志不可读）"
        return " ".join(text.splitlines()[-8:])[:1400] or "（Bridge 未输出日志）"

    @staticmethod
    def _listener_detail(port: int) -> str:
        """端口冲突时记录可见的监听进程；失败不影响观测主流程。"""
        lsof = shutil.which("lsof")
        if not lsof:
            return "未安装 lsof，无法识别监听进程"
        try:
            result = subprocess.run(
                [lsof, "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=2, check=False,
            )
            detail = " | ".join(result.stdout.splitlines()[:3]).strip()
            return detail[:900] if detail else "未读取到监听进程详情"
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"监听进程识别失败：{exc}"

    @staticmethod
    def _port_open(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, int(port)), timeout=0.25):
                return True
        except OSError:
            return False

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
