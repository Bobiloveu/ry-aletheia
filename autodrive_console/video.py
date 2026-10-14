from __future__ import annotations

"""Control plane and native-process launcher for optional robot WebRTC video.

Video frames never pass through this module.  It validates the local contract,
starts MediaMTX plus native ROS/GStreamer child processes when explicitly
enabled, and exposes only small status documents to the Python HTTP console.
"""

import json
import errno
import hashlib
import logging
import os
import re
import signal
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote, urlparse, urlsplit
from urllib.request import Request, urlopen

from .video_encoder import EncoderProbeCancelled, EncoderSelection, EncoderUnavailable, HardwareEncoderSelector


def _choose_private_rtsp_port(gateway: dict[str, Any]) -> int:
    """Choose a loopback publisher port without taking over another service."""
    reserved = {gateway['api_port'], gateway['whep_port'], 8189}
    candidates = dict.fromkeys([gateway['rtsp_port'], *range(18554, 18558), 0])
    for port in candidates:
        if port in reserved:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError as exc:
                if exc.errno == errno.EADDRINUSE:
                    continue
                raise
            chosen = probe.getsockname()[1]
            if chosen not in reserved:
                return chosen
    raise OSError(errno.EADDRINUSE, '无法为私有视频网关选择空闲 RTSP 端口')


VIDEO_SCHEMA = "ry-aletheia-video/v1"
DEFAULT_ROS_DOMAIN_ID = 66
_STREAM_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_RESOLUTION = re.compile(r"[1-9][0-9]{1,4}x[1-9][0-9]{1,4}\Z")
_ROS_IMAGE_TOPIC = re.compile(r"/(?:[A-Za-z][A-Za-z0-9_]*)(?:/[A-Za-z][A-Za-z0-9_]*)*\Z")
_VIDEO_OWNER = "ry-aletheia"
_VIDEO_MAINTENANCE_LAUNCHER = "ry-aletheia-video"
_SHMSDK_CAMERA_CHANNELS = {
    "front_camera": "CamFront",
    "back_camera": "CamBack",
    "left_camera": "CamLeft",
    "right_camera": "CamRight",
}
_LEGACY_CAMERA_TOPICS = {
    "front_camera": "/front_camera/image_raw",
    "back_camera": "/back_camera/image_raw",
    "left_camera": "/left_camera/image_raw",
    "right_camera": "/right_camera/image_raw",
}
LOGGER = logging.getLogger("ry_aletheia.video")
_PROC_ROOT = Path('/proc')


def _process_identity(pid: int) -> tuple[int, int] | None:
    try:
        fields = (_PROC_ROOT / str(pid) / 'stat').read_text().rpartition(')')[2].split()
        return int(fields[2]), int(fields[19])  # pgrp, kernel starttime
    except (OSError, ValueError, IndexError):
        return None


def _owned_subgroups(root_pid: int) -> list[tuple[int, int]]:
    """Snapshot only child groups reached from this console's Popen handle.

    PID plus kernel birth time guards PID reuse. Do not claim arbitrary SDK
    descendants (notably mempool): only Aletheia native ingest / private GST
    executables can enter the outer controller's emergency cleanup list.
    """
    pending, seen, groups = [root_pid], set(), []
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        try:
            children = (_PROC_ROOT / str(pid) / 'task' / str(pid) / 'children').read_text().split()
            pending.extend(int(value) for value in children if value.isdigit())
            identity = _process_identity(pid)
            command = (_PROC_ROOT / str(pid) / 'cmdline').read_bytes().split(b'\0')
            executable = Path(os.fsdecode(command[0])).name
            private = executable == 'aletheia_video_ingest' or (
                executable in {'gst-launch-1.0', 'gst-launch-1.0.real'} and
                '/runtime/video/bin/' in os.fsdecode(command[0]))
            if pid != root_pid and identity and identity[0] == pid and private:
                groups.append((pid, identity[1]))
        except (OSError, ValueError, IndexError):
            continue
    return sorted(groups)


def _signal_owned_subgroups(groups: list[tuple[int, int]], signum: int) -> None:
    for pid, birth in groups:
        if pid > 0 and _process_identity(pid) == (pid, birth):
            try:
                os.killpg(pid, signum)
            except ProcessLookupError:
                pass


class VideoConfigurationError(ValueError):
    """The local video configuration is malformed or unsafe to use."""


@dataclass(frozen=True)
class GatewayHealth:
    online: bool
    detail: str
    paths: frozenset[str] = frozenset()


class VideoManager:
    """Expose video configuration and local MediaMTX health without data relay.

    ``VideoManager`` has no video-frame API by design.  Video must travel
    directly between the hardware encoder/MediaMTX and the browser; Python only
    reads local gateway health and returns a small JSON status document.
    """

    def __init__(self, config_path: Path, default_config_path: Path | None = None, health_timeout_s: float = 0.5) -> None:
        self.config_path = config_path
        self.default_config_path = default_config_path
        self.health_timeout_s = health_timeout_s
        # The HTTP console is threaded.  Serialise configuration updates so
        # two browser clicks cannot race a write or start two native runtimes.
        self._config_lock = threading.RLock()
        self.runtime_status_path = config_path.parent.parent / 'runtime' / 'video-status.json'

    def status(self, public_host: str | None = None) -> dict[str, Any]:
        """Return the stable API model for ``GET /api/video/status``.

        When video is disabled the gateway is intentionally not probed.  This
        keeps the feature opt-in and prevents a missing optional runtime from
        adding work or errors to normal map/point-cloud observation.
        """

        try:
            config = self._load_config()
        except VideoConfigurationError as exc:
            return {
                "enabled": False,
                "gateway": {
                    "kind": "mediamtx",
                    "online": False,
                    "management": "console",
                    "owner": _VIDEO_OWNER,
                    "detail": f"视频配置无效：{exc}",
                },
                "streams": [],
            }

        gateway = config["gateway"]
        if not config["enabled"]:
            health = GatewayHealth(False, "视频功能未启用，未探测 MediaMTX")
        else:
            health = self._probe_gateway(gateway["api_url"])

        streams = [self._stream_status(stream, gateway, health, public_host) for stream in config["streams"]]
        diagnostics = self._read_runtime_status() if config['enabled'] else {}
        stream_diagnostics = diagnostics.get('streams', {})
        if isinstance(stream_diagnostics, dict):
            for stream in streams:
                detail = stream_diagnostics.get(stream['name'])
                if isinstance(detail, dict):
                    for key in ('error_code', 'detail', 'retry_count'):
                        if key in detail:
                            stream[key] = detail[key]
        return {
            "enabled": config["enabled"],
            "runtime": diagnostics.get('runtime', {'state': 'starting' if config['enabled'] else 'disabled',
                'encoder': None, 'device': None, 'error_code': None,
                'detail': '等待视频运行时启动' if config['enabled'] else '视频已关闭'}),
            "gateway": {
                "kind": gateway["kind"],
                "online": health.online,
                "management": gateway["management"],
                "owner": gateway["owner"],
                "maintenance_launcher": _VIDEO_MAINTENANCE_LAUNCHER,
                "detail": health.detail,
            },
            "streams": streams,
        }

    def _read_runtime_status(self) -> dict[str, Any]:
        try:
            if self.runtime_status_path.stat().st_size > 65536:
                return {}
            raw = json.loads(self.runtime_status_path.read_text(encoding='utf-8'))
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            return {}

    def write_runtime_status(self, runtime: dict[str, Any], streams: dict[str, Any] | None = None) -> None:
        target = self.runtime_status_path
        temporary = target.with_suffix(f'.{os.getpid()}.tmp')
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps({'runtime': runtime, 'streams': streams or {}}, ensure_ascii=False), encoding='utf-8')
            temporary.replace(target)
        except OSError as exc:
            LOGGER.warning('无法保存视频运行时诊断：%s', exc)

    def load_config(self) -> dict[str, Any]:
        """Load the validated configuration for the native runtime launcher."""
        source = self.config_path
        if not source.is_file() and self.default_config_path is not None:
            source = self.default_config_path
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise VideoConfigurationError("未找到 config/video.json") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise VideoConfigurationError("config/video.json 无法读取为 JSON") from exc
        if not isinstance(raw, dict):
            raise VideoConfigurationError("配置根节点必须是对象")
        if raw.get("schema") != VIDEO_SCHEMA:
            raise VideoConfigurationError(f"schema 必须为 {VIDEO_SCHEMA}")
        if not isinstance(raw.get("enabled"), bool):
            raise VideoConfigurationError("enabled 必须是布尔值")
        # The vehicle camera stack is deployed on domain 66.  Keep the value
        # explicit in new configurations, while using it for pre-existing
        # configs that were installed before this field existed.
        ros_domain_id = raw.get("ros_domain_id", DEFAULT_ROS_DOMAIN_ID)
        if isinstance(ros_domain_id, bool) or not isinstance(ros_domain_id, int) or not 0 <= ros_domain_id <= 232:
            raise VideoConfigurationError("ros_domain_id 必须是 0 到 232 的整数")

        gateway = raw.get("gateway")
        if not isinstance(gateway, dict):
            raise VideoConfigurationError("gateway 必须是对象")
        kind = gateway.get("kind")
        # Older installed configurations used ``supervisor`` or
        # ``user_launcher``.  Accept them for upgrade compatibility, but the
        # console now owns the child process lifecycle in every case.
        management = gateway.get("management", "console")
        api_url = gateway.get("api_url")
        whep_port = gateway.get("whep_port")
        rtsp_port = gateway.get("rtsp_port")
        if kind != "mediamtx":
            raise VideoConfigurationError("gateway.kind 当前仅支持 mediamtx")
        if management not in {"console", "user_launcher", "supervisor"}:
            raise VideoConfigurationError("gateway.management 必须为 console")
        api_port = self._validate_loopback_url(api_url)
        if not isinstance(whep_port, int) or not 1024 <= whep_port <= 65535:
            raise VideoConfigurationError("gateway.whep_port 必须介于 1024 和 65535")
        if not isinstance(rtsp_port, int) or not 1024 <= rtsp_port <= 65535:
            raise VideoConfigurationError("gateway.rtsp_port 必须介于 1024 和 65535")

        runtime = raw.get("runtime")
        if not isinstance(runtime, dict):
            raise VideoConfigurationError("runtime 必须是对象")
        if runtime.get("encoder") not in {'auto', 'vaapih264enc', 'nvh264enc'}:
            raise VideoConfigurationError("runtime.encoder 必须为 auto、vaapih264enc 或 nvh264enc")
        device = runtime.get('vaapi_device')
        if device != 'auto' and (not isinstance(device, str) or not re.fullmatch(r'/dev/dri/renderD[0-9]{1,4}', device)):
            raise VideoConfigurationError("runtime.vaapi_device 必须为 auto 或受控 DRM render 节点")
        if runtime.get("gst_launch") != "runtime/video/bin/gst-launch-1.0":
            raise VideoConfigurationError("runtime.gst_launch 不是受控私有运行时路径")

        streams = raw.get("streams")
        if not isinstance(streams, list) or len(streams) > 6:
            raise VideoConfigurationError("streams 必须是最多六路的数组")
        clean_streams: list[dict[str, Any]] = []
        names: set[str] = set()
        paths: set[str] = set()
        for item in streams:
            if not isinstance(item, dict):
                raise VideoConfigurationError("每个 stream 必须是对象")
            name = item.get("name")
            path = item.get("path", name)
            resolution = item.get("resolution")
            fps = item.get("fps")
            encoding = item.get("encoding")
            bitrate_kbps = item.get("bitrate_kbps")
            stream_enabled = item.get("enabled", True)
            if not isinstance(name, str) or not _STREAM_NAME.fullmatch(name):
                raise VideoConfigurationError("stream.name 必须是小写字母开头的安全标识")
            if not isinstance(path, str) or not _STREAM_NAME.fullmatch(path):
                raise VideoConfigurationError(f"流 {name} 的 path 格式无效")
            if name in names or path in paths:
                raise VideoConfigurationError(f"流名称或路径重复：{name}")
            if not isinstance(resolution, str) or not _RESOLUTION.fullmatch(resolution):
                raise VideoConfigurationError(f"流 {name} 的 resolution 必须形如 1280x720")
            width, height = (int(value) for value in resolution.split('x'))
            if width > 8192 or height > 8192 or width % 2 or height % 2 or width * height > 16 * 1024 * 1024:
                raise VideoConfigurationError(f'流 {name} 的 resolution 输出分辨率必须为偶数、边长不超过 8192、总像素不超过 16 Mi')
            if not isinstance(fps, int) or not 1 <= fps <= 120:
                raise VideoConfigurationError(f"流 {name} 的 fps 必须介于 1 和 120")
            source = self._validate_stream_input(name, item)
            if encoding not in {"rgb8", "bgr8"}:
                raise VideoConfigurationError(f"流 {name} 当前仅支持 rgb8 或 bgr8 原始图像")
            if not isinstance(bitrate_kbps, int) or not 250 <= bitrate_kbps <= 20000:
                raise VideoConfigurationError(f"流 {name} 的 bitrate_kbps 必须介于 250 和 20000")
            if not isinstance(stream_enabled, bool):
                raise VideoConfigurationError(f"流 {name} 的 enabled 必须是布尔值")
            names.add(name)
            paths.add(path)
            clean_streams.append({
                "name": name,
                "path": path,
                "resolution": resolution,
                "fps": fps,
                "input": source,
                # Keep the status contract stable for ROS streams while the
                # four physical cameras move to the ShmSDK transport.
                "source_topic": source.get("topic"),
                "source_label": self._source_label(source),
                "encoding": encoding,
                "bitrate_kbps": bitrate_kbps,
                "enabled": stream_enabled,
            })
        return {
            "enabled": raw["enabled"],
            "ros_domain_id": ros_domain_id,
            "gateway": {
                "kind": kind,
                "management": "console",
                "owner": _VIDEO_OWNER,
                "api_url": api_url,
                "api_port": api_port,
                "whep_port": whep_port,
                "rtsp_port": rtsp_port,
            },
            "runtime": runtime,
            "streams": clean_streams,
        }

    @staticmethod
    def _validate_stream_input(name: str, stream: dict[str, Any]) -> dict[str, str]:
        """Validate the intentionally narrow physical-camera transport.

        ShmSDK is accepted only for the four hardware camera stream names and
        only with their fixed system channels.  Detection and segmentation
        retain the existing ROS Image path exactly as before.
        """

        input_config = stream.get("input")
        if input_config is None:
            topic = stream.get("source_topic")
            if not isinstance(topic, str) or not _ROS_IMAGE_TOPIC.fullmatch(topic):
                raise VideoConfigurationError(f"流 {name} 的 source_topic 不是安全的 ROS 图像话题")
            return {"kind": "ros", "topic": topic}
        if not isinstance(input_config, dict):
            raise VideoConfigurationError(f"流 {name} 的 input 必须是对象")
        kind = input_config.get("kind")
        if kind == "ros":
            topic = input_config.get("topic")
            if not isinstance(topic, str) or not _ROS_IMAGE_TOPIC.fullmatch(topic):
                raise VideoConfigurationError(f"流 {name} 的 input.topic 不是安全的 ROS 图像话题")
            return {"kind": "ros", "topic": topic}
        if kind == "shmsdk":
            channel = input_config.get("channel")
            expected_channel = _SHMSDK_CAMERA_CHANNELS.get(name)
            if channel != expected_channel:
                raise VideoConfigurationError(f"流 {name} 只能使用固定的 ShmSDK 通道 {expected_channel or '（无）'}")
            return {"kind": "shmsdk", "channel": channel}
        raise VideoConfigurationError(f"流 {name} 的 input.kind 当前仅支持 ros 或 shmsdk")

    @staticmethod
    def _source_label(source: dict[str, str]) -> str:
        if source["kind"] == "shmsdk":
            return f"ShmSDK/{source['channel']}"
        return f"ROS:{source['topic']}"

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        """Persist the operator's video switch without changing stream wiring.

        A disabled configuration makes the optional native pipeline opt-in on
        subsequent console launches.  On first enable, an all-disabled stream
        list is promoted to the validated vehicle defaults as well: otherwise
        a page labelled "启用视频" would successfully start no cameras.  Once
        an operator has selected one or more streams, their selection is
        retained.  The caller owns stopping an already running child process.
        """

        if not isinstance(enabled, bool):
            raise VideoConfigurationError("enabled 必须是布尔值")
        with self._config_lock:
            # Validate first: never turn a malformed arbitrary JSON document
            # into an apparently valid saved configuration.
            self.load_config()
            source = self.config_path
            if not source.is_file() and self.default_config_path is not None:
                source = self.default_config_path
            try:
                raw = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise VideoConfigurationError("config/video.json 无法读取为 JSON") from exc
            if not isinstance(raw, dict):
                raise VideoConfigurationError("配置根节点必须是对象")

            raw["enabled"] = enabled
            streams = raw.get("streams")
            # ``load_config`` above guarantees every member is a dict with a
            # boolean ``enabled`` field.  Fresh defaults intentionally ship
            # with all streams false so installation consumes no resources;
            # the webpage's explicit enable action makes the known default-camera
            # configuration useful without requiring a terminal edit.
            if enabled and isinstance(streams, list) and streams and not any(stream.get("enabled") for stream in streams):
                for stream in streams:
                    stream["enabled"] = True
            return self._save_raw_config(raw)

    def set_stream_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        """Persist one stream choice and derive the runtime's global state.

        Turning a stream on also starts the optional video runtime.  Turning
        off the final selected stream stops it, so an unused gateway or VAAPI
        encoder process never remains resident.  The browser controls only a
        validated configured name; it cannot add a topic, command or path.
        """

        if not isinstance(name, str) or not _STREAM_NAME.fullmatch(name):
            raise VideoConfigurationError("stream 必须是已配置的安全标识")
        if not isinstance(enabled, bool):
            raise VideoConfigurationError("enabled 必须是布尔值")
        with self._config_lock:
            self.load_config()
            source = self.config_path
            if not source.is_file() and self.default_config_path is not None:
                source = self.default_config_path
            try:
                raw = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise VideoConfigurationError("config/video.json 无法读取为 JSON") from exc
            streams = raw.get("streams")
            if not isinstance(streams, list):
                raise VideoConfigurationError("streams 必须是数组")
            matched = False
            for stream in streams:
                if isinstance(stream, dict) and stream.get("name") == name:
                    stream["enabled"] = enabled
                    matched = True
                    break
            if not matched:
                raise VideoConfigurationError(f"未找到已配置的视频流：{name}")
            # The global flag is strictly a process-lifecycle switch.  It is
            # derived from individual choices for per-stream actions so the
            # last closed stream tears down the full optional process tree.
            raw["enabled"] = any(isinstance(stream, dict) and stream.get("enabled") is True for stream in streams)
            return self._save_raw_config(raw)

    def migrate_config(self) -> bool:
        """Apply safe, schema-owned video configuration migrations.

        Offline ZIP upgrades deliberately preserve ``config/video.json``.  A
        new camera stream would otherwise be invisible on an already deployed
        robot forever.  Migration is intentionally narrow: existing stream
        choices, global enable state and all consumed stream fields stay
        untouched.  It may append a missing shipped stream, and removes only
        the legacy ``camera_pair`` note which was never consumed by this
        video sidecar.  Physical-camera mapping remains owned by the robot's
        original camera stack, not by this configuration.
        """

        if self.default_config_path is None or not self.config_path.is_file():
            return False
        with self._config_lock:
            # Refuse to transform an invalid user configuration.  The status
            # endpoint will report the existing diagnostic instead of hiding
            # the problem behind a partial migration.
            self.load_config()
            try:
                current = json.loads(self.config_path.read_text(encoding="utf-8"))
                defaults = json.loads(self.default_config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise VideoConfigurationError("config/video.json 无法读取为 JSON") from exc
            current_streams = current.get("streams") if isinstance(current, dict) else None
            default_streams = defaults.get("streams") if isinstance(defaults, dict) else None
            if not isinstance(current_streams, list) or not isinstance(default_streams, list):
                raise VideoConfigurationError("streams 必须是数组")
            names = {stream.get("name") for stream in current_streams if isinstance(stream, dict)}
            additions = [stream for stream in default_streams if isinstance(stream, dict) and stream.get("name") not in names]
            removed_legacy_metadata = False
            migrated_physical_camera_transport = False
            migrated_encoder = False
            runtime = current.get('runtime', {})
            # This exact pair was shipped in all legacy templates. Keep other
            # explicit hardware choices and every input/output budget intact.
            if ('hardware_selection_version' not in runtime and runtime.get('encoder') == 'vaapih264enc' and
                    runtime.get('vaapi_device') == '/dev/dri/renderD128'):
                runtime.update(encoder='auto', vaapi_device='auto', hardware_selection_version=1)
                migrated_encoder = True
                LOGGER.info('视频配置迁移：旧默认 Intel 编码设置改为自动硬件选择，保留输入与输出预算')
            default_by_name = {
                stream.get("name"): stream
                for stream in default_streams
                if isinstance(stream, dict) and isinstance(stream.get("name"), str)
            }
            for stream in current_streams:
                if isinstance(stream, dict) and "camera_pair" in stream:
                    stream.pop("camera_pair")
                    removed_legacy_metadata = True
                if not isinstance(stream, dict):
                    continue
                name = stream.get("name")
                default = default_by_name.get(name)
                expected_topic = _LEGACY_CAMERA_TOPICS.get(name)
                default_input = default.get("input") if isinstance(default, dict) else None
                # Upgrade only the shipped, now-dead physical ROS topic.  A
                # deliberately customised ROS input remains untouched.
                source = self._validate_stream_input(name, stream)
                if (name in _SHMSDK_CAMERA_CHANNELS and source == {'kind': 'ros', 'topic': expected_topic} and
                        isinstance(default_input, dict) and default_input.get("kind") == "shmsdk"):
                    stream.pop("source_topic", None)
                    stream["input"] = json.loads(json.dumps(default_input))
                    migrated_physical_camera_transport = True
            if not additions and not removed_legacy_metadata and not migrated_physical_camera_transport and not migrated_encoder:
                return False
            # JSON round-trip is a compact deep copy and avoids sharing a
            # caller-owned configuration object with the persisted document.
            current_streams.extend(json.loads(json.dumps(additions)))
            self._save_raw_config(current)
            return True

    def _save_raw_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Atomically save an already validated configuration mutation."""

        target = self.config_path
        temporary = target.with_name(f".{target.name}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.chmod(temporary, 0o644)
            temporary.replace(target)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise VideoConfigurationError("无法保存 config/video.json") from exc
        return self.load_config()

    # Keep the old private spelling as a narrow compatibility shim for code
    # written while this was status-only.  New callers must use load_config().
    def _load_config(self) -> dict[str, Any]:
        return self.load_config()

    @staticmethod
    def _validate_loopback_url(value: Any) -> int:
        if not isinstance(value, str):
            raise VideoConfigurationError("gateway.api_url 必须是 URL")
        try:
            parsed = urlparse(value)
            port = parsed.port
        except ValueError as exc:
            raise VideoConfigurationError("gateway.api_url 端口无效") from exc
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or not port:
            raise VideoConfigurationError("gateway.api_url 必须是本机 HTTP 地址并包含端口")
        if parsed.path != "/v3/paths/list" or parsed.params or parsed.query or parsed.fragment:
            raise VideoConfigurationError("gateway.api_url 必须是 /v3/paths/list")
        return port

    def _probe_gateway(self, api_url: str) -> GatewayHealth:
        request = Request(api_url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.health_timeout_s) as response:
                if response.status != 200:
                    return GatewayHealth(False, f"MediaMTX API 返回 HTTP {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return GatewayHealth(False, f"MediaMTX API 不可用：{exc}")
        paths = set()
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            for item in payload["items"]:
                # MediaMTX keeps a configured path in the listing before an
                # RTSP publisher arrives.  Treat ready:false as waiting so
                # the browser never sends a premature WHEP offer.
                if isinstance(item, dict) and isinstance(item.get("name"), str) and item.get("ready") is not False:
                    paths.add(item["name"])
        return GatewayHealth(True, "MediaMTX API 在线", frozenset(paths))

    @staticmethod
    def _stream_status(stream: dict[str, Any], gateway: dict[str, Any], health: GatewayHealth, public_host: str | None) -> dict[str, Any]:
        if not stream["enabled"] or not health.online:
            state = "disabled" if not stream["enabled"] else "offline"
        elif stream["path"] in health.paths:
            state = "online"
        else:
            state = "waiting"
        return {
            "name": stream["name"],
            "enabled": stream["enabled"],
            "status": state,
            "fps": stream["fps"],
            "resolution": stream["resolution"],
            "source_topic": stream["source_topic"],
            "source_label": stream["source_label"],
            "encoding": stream["encoding"],
            "codec": "h264",
            "latency_ms": None,
            "url": VideoManager._whep_url(public_host, gateway["whep_port"], stream["path"]),
        }

    @staticmethod
    def _whep_url(public_host: str | None, port: int, path: str) -> str | None:
        if not public_host:
            return None
        try:
            hostname = urlsplit(f"//{public_host}").hostname
        except ValueError:
            return None
        if not hostname:
            return None
        host = f"[{hostname}]" if ":" in hostname else hostname
        return f"http://{host}:{port}/{quote(path, safe='')}/whep"


class VideoRuntime:
    """Own the native MediaMTX and RGB/BGR-to-H.264 sidecar process tree.

    It is owned by the ordinary-user console process, never by an HTTP
    endpoint or a process manager.
    All executable paths are constructed from a validated configuration and
    fixed private runtime locations; no shell command is involved.
    """

    RUNTIME_MARKER = "ry-aletheia-runtime.json"

    def __init__(self, manager: VideoManager, workspace: Path, ingest_binary: Path, bundled_runtime: Path | None = None) -> None:
        self.manager = manager
        self.workspace = workspace.resolve()
        self.ingest_binary = ingest_binary.resolve()
        # In a frozen offline-ZIP upgrade this points inside PyInstaller's
        # read-only payload. Source runs and legacy installs simply omit it.
        self.bundled_runtime = bundled_runtime.resolve() if bundled_runtime is not None else None
        self.media_process: subprocess.Popen[bytes] | None = None
        self.ingest_processes: dict[str, subprocess.Popen[bytes]] = {}
        self.stopping = False
        self.encoder_selection: EncoderSelection | None = None
        self.encoder_selector = HardwareEncoderSelector()
        self._retries: dict[str, dict[str, Any]] = {}
        self._stream_diagnostics: dict[str, dict[str, Any]] = {}
        self._runtime_diagnostic: dict[str, Any] = {'state': 'starting', 'encoder': None,
            'device': None, 'error_code': None, 'detail': '正在检查私有视频运行时和硬件编码器'}
        self._last_status: str | None = None
        self._startup_pending: tuple[str, float] | None = None
        self._next_startup_probe_at = 0.0
        self._rtsp_port: int | None = None

    def _publish_status(self, **changes: Any) -> None:
        self._runtime_diagnostic.update(changes)
        serialized = json.dumps([self._runtime_diagnostic, self._stream_diagnostics], sort_keys=True)
        if serialized != self._last_status:
            self.manager.write_runtime_status(self._runtime_diagnostic, self._stream_diagnostics)
            self._last_status = serialized

    def run(self) -> int:
        try:
            config = self.manager.load_config()
        except VideoConfigurationError as exc:
            LOGGER.error("视频运行时未启动：配置无效：%s", exc)
            print(f"RY Aletheia 视频运行时未启动：配置无效：{exc}", flush=True)
            return 2
        if not config["enabled"]:
            LOGGER.info("视频运行时未启动：全局视频开关关闭")
            print("RY Aletheia 视频运行时未启动：config/video.json 的 enabled 为 false。", flush=True)
            return 0

        streams = [stream for stream in config["streams"] if stream["enabled"]]
        if not streams:
            LOGGER.error("视频运行时未启动：全局视频已启用但没有选择任何流")
            print("RY Aletheia 视频运行时未启动：已启用视频功能但没有启用任何相机流。", flush=True)
            return 2
        # A close action during the bounded probe must reach this runner's
        # handler, so it can reap the probe group before the outer five-second
        # deadline rather than leave a detached driver/scanner process behind.
        self._install_signal_handlers()
        try:
            self._publish_status()
            runtime = self._runtime_root()
            media_binary = self._require_executable(runtime / "mediamtx" / "mediamtx", "MediaMTX")
            gst_launch = self._require_executable(
                self.workspace / config["runtime"]["gst_launch"], "私有 gst-launch-1.0"
            )
            ingest_binary = self._require_executable(self.ingest_binary, "原生视频输入节点")
            media_config = runtime / "mediamtx" / "ry-aletheia-mediamtx.yml"
            # Declare every configured path once.  A per-stream switch then
            # only changes its native publisher; MediaMTX and other paths stay
            # live and existing WebRTC sessions are never needlessly reset.
            self.encoder_selection = self.encoder_selector.select(gst_launch, config['runtime']['encoder'], config['runtime']['vaapi_device'], lambda: self.stopping)
            config = self.manager.load_config()
            if self.stopping or not config['enabled']:
                self._publish_status(state='disabled', error_code=None, detail='视频已关闭')
                return 0
            streams = [stream for stream in config['streams'] if stream['enabled']]
            self._publish_status(state='ready', encoder=self.encoder_selection.encoder, device=self.encoder_selection.device,
                                 error_code=None, detail='硬件 H.264 编码预检通过')
        except EncoderProbeCancelled:
            self._publish_status(state='disabled', error_code=None, detail='视频已关闭')
            return 0
        except EncoderUnavailable as exc:
            self._publish_status(state='error', error_code='encoder_unavailable', detail=str(exc))
            LOGGER.error('视频硬件编码不可用：%s', exc)
            return 2
        except VideoConfigurationError as exc:
            self._publish_status(state='error', error_code='configuration_invalid', detail=str(exc))
            LOGGER.error('视频预检期间配置失效：%s', exc)
            return 2
        except (OSError, RuntimeError) as exc:
            self._publish_status(state='error', error_code='runtime_unavailable', detail=str(exc))
            LOGGER.error("视频运行时未启动：%s", exc)
            print(f"RY Aletheia 视频运行时未启动：{exc}", flush=True)
            return 2

        try:
            # Select after hardware preflight, immediately before launching
            # our gateway. Persist only in this runner; reloaded user settings
            # must not send a restarted publisher back to the occupied port.
            requested_port = config['gateway']['rtsp_port']
            self._rtsp_port = _choose_private_rtsp_port(config['gateway'])
            if self._rtsp_port != requested_port:
                LOGGER.warning('视频 RTSP 端口 %s 已占用或与网关端口重叠，本次使用回环端口 %s；外部服务及用户配置保持不变',
                               requested_port, self._rtsp_port)
                print(f'私有视频 RTSP 端口 {requested_port} 不可用，本次改用 {self._rtsp_port}', flush=True)
            config = {**config, 'gateway': {**config['gateway'], 'rtsp_port': self._rtsp_port}}
            self._write_media_config(media_config, config, config["streams"])
            LOGGER.info(
                "启动视频运行时：ROS_DOMAIN_ID=%s streams=%s gateway_api=%s rtsp_port=%s whep_port=%s",
                config["ros_domain_id"],
                ", ".join(f"{stream['name']}({stream['source_label']},{stream['resolution']}@{stream['fps']})" for stream in streams),
                config["gateway"]["api_url"], config["gateway"]["rtsp_port"], config["gateway"]["whep_port"],
            )
            self.media_process = subprocess.Popen([str(media_binary), str(media_config)], cwd=self.workspace)
            if not self._wait_for_gateway(config["gateway"]["api_url"]):
                self._publish_status(state='error', error_code='gateway_unavailable', detail='MediaMTX 未在 5 秒内就绪，请查看 logs/video-runtime.log')
                status = self.media_process.returncode if self.media_process is not None and self.media_process.poll() is not None else "running"
                LOGGER.error("MediaMTX 未在 5 秒内就绪：status=%s api=%s", status, config["gateway"]["api_url"])
                print("MediaMTX 未在 5 秒内就绪。", flush=True)
                return 1
            self._reconcile_streams(config, ingest_binary, gst_launch)
            print(
                f"RY Aletheia 视频运行时已启动：{', '.join(stream['name'] for stream in streams)} "
                f"(ROS_DOMAIN_ID={config['ros_domain_id']})",
                flush=True,
            )
            return self._monitor_children(ingest_binary, gst_launch)
        except OSError as exc:
            self._publish_status(state='error', error_code='process_start_failed', detail=str(exc))
            LOGGER.exception("视频子进程启动失败：%s", exc)
            print(f"RY Aletheia 视频子进程启动失败：{exc}", flush=True)
            return 1
        finally:
            self._stop_children()

    def _runtime_root(self) -> Path:
        runtime = (self.workspace / "runtime" / "video").resolve()
        if not runtime.is_relative_to(self.workspace):
            raise RuntimeError("私有视频运行时路径越界")
        self._refresh_bundled_runtime(runtime)
        return runtime

    def _refresh_bundled_runtime(self, runtime: Path) -> None:
        """Refresh the optional packaged video runtime before starting children.

        The ZIP upgrade protocol deliberately remains a two-file archive for
        compatibility with already installed consoles.  Its onefile binary
        carries this directory instead.  A small marker makes repeated video
        starts a no-op and preserves all user configuration outside runtime/.
        """

        bundled = self.bundled_runtime
        if bundled is None or not bundled.is_dir():
            return
        bundled_marker = bundled / self.RUNTIME_MARKER
        if not bundled_marker.is_file():
            return
        try:
            expected_marker = bundled_marker.read_bytes()
            current_marker = runtime / self.RUNTIME_MARKER
            marker = json.loads(expected_marker)
            required = marker.get('required_files', [])
            files_present = all(isinstance(name, str) and (runtime / name).resolve().is_relative_to(runtime) and
                                (runtime / name).is_file() for name in required)
            hashes = marker.get('file_sha256', {})
            if files_present and isinstance(hashes, dict):
                files_present = all(isinstance(name, str) and (runtime / name).resolve().is_relative_to(runtime) and
                                    (runtime / name).is_file() and hashlib.sha256((runtime / name).read_bytes()).hexdigest() == digest
                                    for name, digest in hashes.items())
            executables = marker.get('executable_files', [])
            if files_present:
                files_present = all(isinstance(name, str) and (runtime / name).resolve().is_relative_to(runtime) and
                                    (runtime / name).is_file() and os.access(runtime / name, os.X_OK)
                                    for name in executables)
            if current_marker.is_file() and current_marker.read_bytes() == expected_marker and files_present:
                return
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"无法读取私有视频运行时标记：{exc}") from exc

        parent = runtime.parent
        staging = parent / ".ry-aletheia-video-next"
        previous = parent / ".ry-aletheia-video-previous"
        try:
            parent.mkdir(parents=True, exist_ok=True)
            self._remove_runtime_tree(staging)
            self._remove_runtime_tree(previous)
            shutil.copytree(bundled, staging, symlinks=True)
            if runtime.exists() or runtime.is_symlink():
                os.replace(runtime, previous)
            try:
                os.replace(staging, runtime)
            except OSError:
                if previous.exists() or previous.is_symlink():
                    os.replace(previous, runtime)
                raise
            self._remove_runtime_tree(previous)
        except OSError as exc:
            self._remove_runtime_tree(staging)
            raise RuntimeError(f"无法更新私有视频运行时：{exc}") from exc
        print("RY Aletheia 已更新私有视频运行时。", flush=True)
        LOGGER.info('私有视频运行时已按内容指纹刷新或修复：path=%s', runtime)

    @staticmethod
    def _remove_runtime_tree(path: Path) -> None:
        # Both paths are fixed children of the validated workspace runtime
        # parent, never user-supplied paths or broad directories.
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)

    @staticmethod
    def _require_executable(path: Path, label: str) -> Path:
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError(f"未找到{label}：{path}")
        return path

    @staticmethod
    def _write_media_config(path: Path, config: dict[str, Any], streams: list[dict[str, Any]]) -> None:
        """Write a deterministic, restricted MediaMTX configuration.

        Input was fully validated by VideoManager; stream names contain only a
        conservative identifier alphabet, making this small YAML emitter safer
        and simpler than accepting arbitrary YAML from the vehicle directory.
        """
        gateway = config["gateway"]
        lines = [
            "logLevel: info",
            "api: true",
            f"apiAddress: 127.0.0.1:{gateway['api_port']}",
            'apiAllowOrigins: ["http://127.0.0.1"]',
            "rtsp: true",
            "rtspTransports: [tcp]",
            f"rtspAddress: 127.0.0.1:{gateway['rtsp_port']}",
            'rtpAddress: ""',
            'rtcpAddress: ""',
            "webrtc: true",
            f"webrtcAddress: :{gateway['whep_port']}",
            "webrtcEncryption: false",
            'webrtcAllowOrigins: ["*"]',
            "webrtcLocalUDPAddress: :8189",
            'webrtcLocalTCPAddress: ""',
            "webrtcIPsFromInterfaces: true",
            "webrtcAdditionalHosts: []",
            "hls: false",
            "rtmp: false",
            "srt: false",
            "moq: false",
            "pathDefaults:",
            "  source: publisher",
            "  overridePublisher: false",
            "paths:",
        ]
        lines.extend(f"  {stream['path']}: {{}}" for stream in streams)
        temporary = path.with_suffix(".yml.tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def _start_ingest(self, stream: dict[str, Any], config: dict[str, Any], ingest_binary: Path, gst_launch: Path) -> None:
        width, height = stream["resolution"].split("x", 1)
        command = [
            str(ingest_binary),
            "--node-name", f"ry_aletheia_video_{stream['name']}",
            "--input-kind", stream["input"]["kind"],
            "--encoder", self.encoder_selection.encoder if self.encoder_selection else
                ('vaapih264enc' if config['runtime']['encoder'] == 'auto' else config['runtime']['encoder']),
            "--encoding", stream["encoding"],
            "--gst-launch", str(gst_launch),
            "--vaapi-device", (self.encoder_selection.device if self.encoder_selection else None) or
                ('/dev/dri/renderD128' if config['runtime']['vaapi_device'] == 'auto' else config['runtime']['vaapi_device']),
            "--rtsp-url", f"rtsp://127.0.0.1:{self._rtsp_port or config['gateway']['rtsp_port']}/{stream['path']}",
            "--width", width,
            "--height", height,
            "--fps", str(stream["fps"]),
            "--bitrate-kbps", str(stream["bitrate_kbps"]),
        ]
        if stream["input"]["kind"] == "shmsdk":
            command.extend(["--shm-channel", stream["input"]["channel"]])
        else:
            command.extend(["--topic", stream["input"]["topic"]])
        # The detached user launcher can outlive its terminal.  Pass the
        # configured DDS domain explicitly instead of relying on a login
        # shell's environment.  Only native ROS ingest children need it;
        # MediaMTX is not a ROS participant.
        ingest_environment = os.environ.copy()
        ingest_environment["ROS_DOMAIN_ID"] = str(config["ros_domain_id"])
        # Warnings/errors only; media pixels and per-frame debug stay out of
        # Python. Preserve an explicitly configured GStreamer debug level.
        ingest_environment.setdefault('GST_DEBUG', '2')
        if self.encoder_selection and self.encoder_selection.encoder == 'vaapih264enc' and self.encoder_selection.device:
            ingest_environment['GST_VAAPI_DRM_DEVICE'] = self.encoder_selection.device
            ingest_environment['GST_VAAPI_DISPLAY'] = 'drm'
        self.ingest_processes[stream["name"]] = subprocess.Popen(command, cwd=self.workspace, env=ingest_environment, start_new_session=True)
        retry = self._retries.setdefault(stream['name'], {'count': 0, 'next_at': 0})
        retry['started_at'] = time.monotonic()
        self._stream_diagnostics[stream['name']] = {'error_code': None, 'detail': '原生输入进程已启动，等待媒体流', 'retry_count': retry['count']}
        LOGGER.info(
            "已启动视频输入：stream=%s pid=%s source=%s expected=%s/%s fps=%s bitrate_kbps=%s ros_domain_id=%s",
            stream["name"], self.ingest_processes[stream["name"]].pid, stream["source_label"],
            stream["encoding"], stream["resolution"], stream["fps"], stream["bitrate_kbps"], config["ros_domain_id"],
        )
        print(f"RY Aletheia 已启用视频流：{stream['name']}", flush=True)

    @staticmethod
    def _stop_ingest(process: subprocess.Popen[bytes], process_group: bool = False) -> None:
        group = process_group and isinstance(process.pid, int) and process.pid > 0
        if process.poll() is not None:
            if group:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            return
        try:
            if group:
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if not group:
                process.kill()
        finally:
            if group:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()

    def _reconcile_streams(self, config: dict[str, Any], ingest_binary: Path, gst_launch: Path) -> bool:
        """Apply per-stream choices without recreating MediaMTX or peers."""

        desired = {stream["name"]: stream for stream in config["streams"] if stream["enabled"]}
        now = time.monotonic()
        for name in list(self._retries):
            if name not in desired:
                self._retries.pop(name, None)
                self._stream_diagnostics.pop(name, None)
        for name, process in list(self.ingest_processes.items()):
            if name not in desired:
                self._stop_ingest(process, process_group=True)
                self.ingest_processes.pop(name, None)
                LOGGER.info("已停止视频输入：stream=%s（操作员关闭该路）", name)
                print(f"RY Aletheia 已关闭视频流：{name}", flush=True)
            elif process.poll() is not None:
                LOGGER.error("视频输入进程意外退出：stream=%s exit_code=%s；请查看 logs/video-runtime.log", name, process.returncode)
                print(f"视频输入进程意外退出：{name} status={process.returncode}", flush=True)
                self.ingest_processes.pop(name, None)
                self._stop_ingest(process, process_group=True)
                self._schedule_retry(name, now, f'原生输入进程退出（exit={process.returncode}）')
            else:
                retry = self._retries.get(name)
                if retry and now - retry.get('started_at', now) >= 60:
                    retry['count'] = 0
        serial_start = self.encoder_selection is not None and self.encoder_selection.encoder == 'nvh264enc'
        if self._startup_pending:
            starting, deadline = self._startup_pending
            if not serial_start or starting not in desired or starting not in self.ingest_processes:
                self._startup_pending = None
            elif now >= deadline:
                LOGGER.warning('NVENC 启动等待到期：stream=%s；继续启动下一路，当前输入与恢复保持独立', starting)
                self._startup_pending = None
            elif now >= self._next_startup_probe_at:
                self._next_startup_probe_at = now + 1.0
                health = self.manager._probe_gateway(config['gateway']['api_url'])
                if desired[starting]['path'] in health.paths:
                    LOGGER.info('NVENC 启动完成，媒体流已发布：stream=%s', starting)
                    self._stream_diagnostics[starting]['detail'] = 'H.264 媒体流已发布'
                    self._startup_pending = None
        for name, stream in desired.items():
            if self.stopping:
                break
            if name not in self.ingest_processes:
                if serial_start and self._startup_pending:
                    continue
                retry = self._retries.get(name)
                if retry and (retry['count'] > 5 or now < retry['next_at']):
                    continue
                try:
                    self._start_ingest(stream, config, ingest_binary, gst_launch)
                    if serial_start:
                        self._startup_pending = (name, now + 12.0)
                        self._next_startup_probe_at = now
                except OSError as exc:
                    self._schedule_retry(name, now, f'无法启动原生输入进程：{exc}')
        self._publish_status()
        return True

    def _schedule_retry(self, name: str, now: float, reason: str) -> None:
        retry = self._retries.setdefault(name, {'count': 0, 'next_at': 0})
        retry['count'] += 1
        exhausted = retry['count'] > 5
        delay = min(30, 2 ** (retry['count'] - 1))
        retry['next_at'] = now + delay
        self._stream_diagnostics[name] = {'error_code': 'ingest_retry_exhausted' if exhausted else 'ingest_retrying',
            'detail': reason + ('；重试已达上限，请关闭并重新启用该路' if exhausted else f'；{delay} 秒后仅重试该路'),
            'retry_count': min(retry['count'], 5)}
        LOGGER.warning('视频单路恢复：stream=%s %s', name, self._stream_diagnostics[name]['detail'])

    def _wait_for_gateway(self, api_url: str) -> bool:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not self.stopping:
            if self.media_process is not None and self.media_process.poll() is not None:
                return False
            if self.manager._probe_gateway(api_url).online:
                return True
            time.sleep(0.1)
        return False

    def _monitor_children(self, ingest_binary: Path, gst_launch: Path) -> int:
        while not self.stopping:
            if self.media_process is None or self.media_process.poll() is not None:
                status = self.media_process.returncode if self.media_process is not None else "unknown"
                LOGGER.error("MediaMTX 意外退出：exit_code=%s；请查看 logs/video-runtime.log", status)
                self._publish_status(state='error', error_code='gateway_exited', detail=f'MediaMTX 意外退出（exit={status}）')
                print(f"MediaMTX 意外退出：status={status}", flush=True)
                return 1
            try:
                config = self.manager.load_config()
            except VideoConfigurationError as exc:
                LOGGER.error("视频配置在运行中失效：%s", exc)
                print(f"视频配置已失效：{exc}", flush=True)
                return 1
            if not config["enabled"]:
                self._publish_status(state='disabled', error_code=None, detail='视频已关闭')
                LOGGER.info("视频运行时停止：全局视频开关已关闭")
                return 0
            if not self._reconcile_streams(config, ingest_binary, gst_launch):
                return 1
            time.sleep(0.2)
        return 0

    def _install_signal_handlers(self) -> None:
        def stop(_signum: int, _frame: Any) -> None:
            self.stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

    def _stop_children(self) -> None:
        # Ingest owns its own process group so a crashed SDK reader cannot leak
        # its encoder, and restarting it cannot signal any peer. Signal all
        # groups first; share one grace period across six streams so the outer
        # console's five-second shutdown timeout still covers this cleanup.
        children = [(process, True) for process in self.ingest_processes.values()]
        if self.media_process is not None:
            children.append((self.media_process, False))
        for process, group in children:
            try:
                if group and isinstance(process.pid, int) and process.pid > 0:
                    os.killpg(process.pid, signal.SIGTERM)
                elif process.poll() is None:
                    process.terminate()
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 3
        for process, group in children:
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                if not group:
                    process.kill()
            finally:
                if group and isinstance(process.pid, int) and process.pid > 0:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                process.wait()
        self.ingest_processes.clear()
        self.media_process = None


class ConsoleVideoRuntime:
    """Own an enabled video's native process for the lifetime of ``ry-aletheia``.

    It deliberately starts only after the console has claimed TCP 8087, so a
    second invocation cannot disturb video already owned by the first console.
    The child has no daemon manager: normal console shutdown, safe exit, and
    offline upgrade all terminate this parent-owned process tree.
    """

    def __init__(self, manager: VideoManager, workspace: Path, runner_command: list[str]) -> None:
        self.manager = manager
        self.workspace = workspace.resolve()
        self.runner_command = list(runner_command)
        self.process: subprocess.Popen[bytes] | None = None
        self._lock = threading.RLock()

    def start_if_enabled(self) -> bool:
        with self._lock:
            return self._start_if_enabled()

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        """Apply the webpage switch and immediately reconcile this child."""

        with self._lock:
            config = self.manager.set_enabled(enabled)
            if config["enabled"]:
                self._start_if_enabled(config)
            else:
                self._stop()
            return config

    def set_stream_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        """Apply one stream choice without disrupting active peer streams."""

        with self._lock:
            config = self.manager.set_stream_enabled(name, enabled)
            if config["enabled"]:
                # A running VideoRuntime polls the small local configuration
                # document and adds/removes only the matching ingest child.
                # If this is the first selected stream, start that runtime.
                self._start_if_enabled(config)
            else:
                # Last stream was closed: no peers remain, so immediate full
                # cleanup is both safe and more resource-efficient.
                self._stop()
            return config

    def _start_if_enabled(self, config: dict[str, Any] | None = None) -> bool:
        try:
            config = config or self.manager.load_config()
        except VideoConfigurationError as exc:
            LOGGER.error("视频未自动启动：配置无效：%s", exc)
            print(f"RY Aletheia 视频未自动启动：配置无效：{exc}", flush=True)
            return False
        if not config["enabled"]:
            return False
        if self.process is not None and self.process.poll() is None:
            return False
        self.process = None
        if self.manager._probe_gateway(config["gateway"]["api_url"]).online:
            LOGGER.warning("视频运行时未重复启动：检测到已有 MediaMTX 网关 api=%s", config["gateway"]["api_url"])
            print("RY Aletheia 视频网关已存在；保留当前进程，不重复启动。", flush=True)
            return False
        logs_dir = self.workspace / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / "video-runtime.log"
        environment = os.environ.copy()
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        self.manager.write_runtime_status({'state': 'starting', 'encoder': None, 'device': None,
            'error_code': None, 'detail': '正在启动视频运行时并检查硬件编码器'})
        with log_file.open("ab", buffering=0) as output:
            self.process = subprocess.Popen(
                self.runner_command,
                cwd=self.workspace,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                close_fds=True,
                # A frozen onefile executable has an outer bootloader and an
                # inner Python process.  A dedicated session lets stop()
                # terminate that complete tree, including native encoders.
                start_new_session=True,
            )
        LOGGER.info("已启动受控视频运行时：pid=%s log=%s", self.process.pid, log_file)
        print(f"RY Aletheia 已自动启动视频运行时：pid={self.process.pid}", flush=True)
        return True

    def stop(self) -> None:
        with self._lock:
            self._stop()

    def _stop(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        subgroups = _owned_subgroups(process.pid) if isinstance(process.pid, int) else []
        # Terminating only the onefile bootloader leaves its inner Python
        # process reparented to init, along with MediaMTX and GStreamer.  The
        # process was created in its own session above, so this exact process
        # group is the complete console-owned video tree.
        try:
            _signal_owned_subgroups(subgroups, signal.SIGTERM)
            os.killpg(process.pid, signal.SIGTERM)
            LOGGER.info("请求停止受控视频运行时：pid=%s", process.pid)
        except ProcessLookupError:
            _signal_owned_subgroups(subgroups, signal.SIGKILL)
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # This is a child process created by this console and validated by
            # its Popen handle, so forced cleanup cannot target another tool.
            try:
                os.killpg(process.pid, signal.SIGKILL)
                LOGGER.warning("视频运行时未在宽限期退出，已强制停止：pid=%s", process.pid)
            except ProcessLookupError:
                return
            process.wait()
        finally:
            # Sessions survive the runner group. Clean only the already
            # snapshotted, birth-time-validated native/encoder groups even if
            # the onefile runner needed forced termination.
            _signal_owned_subgroups(subgroups, signal.SIGKILL)
