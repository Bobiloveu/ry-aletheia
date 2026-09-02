"""Local Lightning mapping sessions for the deployment workspace.

The browser never launches SLAM or consumes a ROS topic itself.  A mapping
session is deliberately separate from localisation, navigation and vehicle
control: it prepares a project-owned YAML copy, owns the Lightning child
process, and (when Lightning provides it) subscribes to a local OccupancyGrid
preview topic.  Nothing in this module writes the robot's active maps or
localisation configuration.
"""
from __future__ import annotations

import logging
import os
import re
import signal
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from .map_assets import MapAssetCache, MapAssetError


LOGGER = logging.getLogger("ry_aletheia.mapping")


class MappingError(RuntimeError):
    """A requested mapping action cannot be completed safely."""


class MappingUnavailable(MappingError):
    """Lightning or the required local ROS2 runtime is not ready."""


@dataclass(frozen=True)
class MappingConfig:
    config_root: Path = Path("/opt/ry/config/localization/config")
    preview_topic: str = "/lightning/grid_map"
    map_service: str = "/lightning/save_map"
    command: tuple[str, ...] = ("ros2", "run", "lightning", "run_slam_online")
    probe_cache_s: float = 5.0


class MappingSessionController:
    """Own one explicit online Lightning mapping session at a time.

    Live preview consumes Lightning's local ``/lightning/grid_map`` publisher
    when the selected YAML enables ``system.with_g2p5``.  The controller never
    changes that user-maintained YAML: it starts the copied session file and
    clearly reports a missing first grid or an exited child process.
    """

    def __init__(
        self,
        root: Path,
        *,
        active_run_guard: Callable[[], bool] | None = None,
        config: MappingConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
        popen: Callable[..., Any] = subprocess.Popen,
        run: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.root = root
        self.config = config or MappingConfig()
        self._active_run_guard = active_run_guard or (lambda: False)
        self._clock = clock
        self._popen = popen
        self._run = run
        self._lock = threading.RLock()
        self._session: dict[str, Any] | None = None
        self._process: Any = None
        self._process_log = None
        self._node = None
        self._executor = None
        self._thread: threading.Thread | None = None
        self._probe_at = 0.0
        self._probe_result: tuple[bool, str] = (False, "尚未检查 Lightning 在线建图运行时")

    # ---- Public contract -----------------------------------------------------

    def status(self) -> dict[str, Any]:
        self._refresh_process_state()
        available, reason = self._probe_lightning()
        with self._lock:
            session = self._snapshot_locked()
        return {
            "available": available,
            "reason": reason,
            "preview_topic": self.config.preview_topic,
            "requires_gridmap": True,
            "session": session,
        }

    def store_template(
        self, project_id: object, filename: object, contents: bytes
    ) -> dict[str, str]:
        """Persist a browser-selected YAML under the Aletheia project workspace.

        The browser's local path is intentionally never sent to, stored by, or
        resolved on the robot.  This is an immutable input snapshot; the
        operator may edit the original YAML on their computer without Aletheia
        changing either copy.
        """
        cleaned_project_id = self._clean_project_id(project_id)
        name = Path(str(filename or "")).name
        if not name or name != str(filename or "") or Path(name).suffix.lower() not in {".yaml", ".yml"}:
            raise MappingError("请选择一个 YAML 建图模板文件")
        if not isinstance(contents, bytes) or not contents or len(contents) > 2 * 1024 * 1024:
            raise MappingError("建图模板大小无效或超过 2 MiB 限制")
        try:
            contents.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MappingError("建图模板必须使用 UTF-8 编码") from exc

        directory = self._template_directory(cleaned_project_id)
        directory.mkdir(parents=True, exist_ok=True)
        template_id = f"{uuid.uuid4().hex[:12]}-{name}"
        target = (directory / template_id).resolve()
        if not target.is_relative_to(directory.resolve()):
            raise MappingError("建图模板路径不安全")
        try:
            with target.open("xb") as output:
                output.write(contents)
        except OSError as exc:
            raise MappingError(f"无法保存建图模板副本：{exc}") from exc
        return {"id": template_id, "name": name, "path": str(target)}

    def prepare(
        self,
        project_id: str,
        *,
        template_id: object,
        label: object,
        kind: object,
    ) -> dict[str, Any]:
        """Copy one user-prepared mapping YAML into an isolated session."""
        if self._active_run_guard():
            raise MappingError("自动化测试正在执行，不能同时启动建图会话")
        cleaned_project_id = self._clean_project_id(project_id)
        source = self._project_template_path(cleaned_project_id, template_id)
        map_kind = str(kind or "custom")
        if map_kind not in {"outdoor", "lobby", "typical_floor", "custom"}:
            raise MappingError("地图类型无效")
        cleaned_label = " ".join(str(label or "实时建图").split())[:80] or "实时建图"
        try:
            raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise MappingError(f"无法读取定位/建图模板：{exc}") from exc
        if not isinstance(raw, dict):
            raise MappingError("建图模板必须是 YAML 对象")
        system = raw.get("system")
        common = raw.get("common")
        if not isinstance(system, dict) or not isinstance(common, dict):
            raise MappingError("建图模板的 system/common 节点格式无效")
        lidar_topic = str(common.get("lidar_topic") or "").strip()
        if not lidar_topic:
            raise MappingError("建图模板缺少 common.lidar_topic")
        if system.get("with_g2p5") is not True:
            raise MappingError("建图模板需在 YAML 中设置 system.with_g2p5: true，才能产生实时栅格和 PGM")

        session_id = f"mapping-{uuid.uuid4().hex[:12]}"
        session_dir = self.root / session_id
        session_dir.mkdir(parents=True, exist_ok=False)
        generated = session_dir / "lightning-mapping.yaml"
        # Preserve the user's original formatting and comments exactly.  This
        # isolated copy is never written back to /opt/ry/config/localization.
        shutil.copy2(source, generated)
        session = {
            "id": session_id,
            "project_id": cleaned_project_id,
            "label": cleaned_label,
            "kind": map_kind,
            "state": "prepared",
            "created_at": time.time(),
            "source_yaml": source.name.split("-", 1)[-1],
            "generated_yaml": str(generated),
            "output_dir": str(session_dir / "data" / session_id),
            "preview": {
                "state": "idle",
                "revision": 0,
                "width": None,
                "height": None,
                "resolution": None,
            },
            "error": "",
        }
        with self._lock:
            if self._session and self._session.get("state") in {"prepared", "running", "stopping"}:
                raise MappingError("已有建图会话；请先完成或停止当前会话")
            self._session = session
        return self._snapshot_locked()

    def _clean_project_id(self, project_id: object) -> str:
        value = str(project_id or "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,120}", value):
            raise MappingError("部署项目标识无效")
        return value

    def _template_directory(self, project_id: str) -> Path:
        """The only directory from which a mapping template may be prepared."""
        directory = (self.root.parent / project_id / "mapping_templates").resolve()
        workspace = self.root.parent.resolve()
        if not directory.is_relative_to(workspace):
            raise MappingError("建图模板路径不安全")
        return directory

    def _project_template_path(self, project_id: str, template_id: object) -> Path:
        identifier = str(template_id or "")
        if not identifier or Path(identifier).name != identifier:
            raise MappingError("请先选择已上传的 YAML 建图模板")
        directory = self._template_directory(project_id)
        source = (directory / identifier).resolve()
        if not source.is_file() or not source.is_relative_to(directory.resolve()):
            raise MappingError("请先选择已上传的 YAML 建图模板")
        return source

    def start(self, session_id: str) -> dict[str, Any]:
        if self._active_run_guard():
            raise MappingError("自动化测试正在执行，不能同时启动建图会话")
        available, reason = self._probe_lightning(force=True)
        if not available:
            raise MappingUnavailable(reason)
        with self._lock:
            session = self._require_session_locked(session_id, "prepared")
            command = [*self.config.command, "--config", session["generated_yaml"]]
            cwd = str((self.root / session["id"]).resolve())
            log_path = self.root / session["id"] / "lightning.log"
        try:
            self._start_preview_listener()
            # Retain the actual online-SLAM startup error in the isolated
            # session instead of discarding it to DEVNULL.  It is essential
            # when a robot package/configuration differs from the source tree.
            self._process_log = log_path.open("ab", buffering=0)
            self._process = self._popen(
                command, cwd=cwd, stdout=self._process_log, stderr=subprocess.STDOUT,
                # ros2 run may fork/exec the Lightning binary.  A dedicated
                # process group lets Stop terminate the full mapping tree.
                start_new_session=True,
            )
        except Exception as exc:
            self._close_process_log()
            self._stop_preview_listener()
            with self._lock:
                session["state"] = "failed"
                session["error"] = f"无法启动 Lightning 在线建图：{exc}"
            raise MappingUnavailable(session["error"]) from exc
        with self._lock:
            session["state"] = "running"
            session["started_at"] = time.time()
            session["error"] = ""
            session["log_path"] = str(log_path)
            session["preview"]["state"] = "waiting"
            return self._snapshot_locked()

    def stop(self, session_id: str, *, save: bool = True) -> dict[str, Any]:
        self._refresh_process_state()
        with self._lock:
            session = self._require_session_locked(session_id, "running")
            session["state"] = "stopping"
        save_error = ""
        if save:
            try:
                self._save_map(session["id"])
                self._validate_saved_capture(session)
            except Exception as exc:  # Stop still has to release the process.
                save_error = f"地图保存请求失败：{exc}"
        process = self._process
        try:
            if process and process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
                process.wait(timeout=6)
        except Exception:
            if process and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        finally:
            self._process = None
            self._close_process_log()
            self._stop_preview_listener()
        with self._lock:
            session["state"] = "saved" if save and not save_error else "stopped"
            session["stopped_at"] = time.time()
            session["error"] = save_error
            return self._snapshot_locked()

    def discard(self, session_id: str) -> dict[str, Any]:
        """Release a prepared/finished session without deleting its diagnostics.

        A running Lightning process must always use :meth:`stop`; discarding is
        intentionally limited to states that own no active vehicle or SLAM
        process.  Its on-disk session directory remains available for support
        inspection, while a fresh mapping session can be prepared immediately.
        """
        self._refresh_process_state()
        with self._lock:
            session = self._require_session_locked(session_id)
            if session.get("state") in {"running", "stopping"}:
                raise MappingError("建图正在运行；请先停止并保存地图")
            session["state"] = "discarded"
            session["discarded_at"] = time.time()
            snapshot = self._snapshot_locked()
            self._session = None
            return snapshot

    def ingest_grid(
        self,
        *,
        resolution: float,
        width: int,
        height: int,
        origin: list[float],
        frame_id: str,
        data: list[int] | tuple[int, ...],
    ) -> None:
        """Persist one latest preview frame; called by the local ROS callback.

        Keeping a stable ``live/map.pgm`` gives the web canvas a fixed URL;
        it polls only the increasing revision, not the raw grid stream.
        """
        with self._lock:
            if not self._session or self._session.get("state") != "running":
                return
            session = self._session
            session_dir = self.root / session["id"]
        cache = MapAssetCache(session_dir / "preview-cache", allowed_roots=(session_dir,))
        try:
            asset = cache.cache_occupancy_grid(
                resolution=resolution, width=width, height=height, origin=origin,
                frame_id=frame_id, data=data, label=session["label"],
            )
            live_dir = session_dir / "live"
            live_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset.cache_image, live_dir / "map.pgm")
            shutil.copy2(asset.cache_yaml, live_dir / "map.yaml")
        except (OSError, MapAssetError) as exc:
            with self._lock:
                session["error"] = f"实时地图缓存失败：{exc}"
            LOGGER.warning("实时建图预览缓存失败：%s", exc)
            return
        with self._lock:
            preview = session["preview"]
            preview.update({
                "state": "streaming",
                "revision": int(preview["revision"]) + 1,
                "width": width,
                "height": height,
                "resolution": resolution,
                "origin": [float(origin[0]), float(origin[1]), 0.0],
            })

    def preview_pgm(self, session_id: str) -> Path:
        with self._lock:
            session = self._require_session_locked(session_id)
            target = self.root / session["id"] / "live" / "map.pgm"
        if not target.is_file():
            raise MappingError("实时地图尚未产生栅格数据")
        return target

    def close(self) -> None:
        """Stop a live child process when Aletheia is shutting down."""
        with self._lock:
            session_id = self._session.get("id") if self._session else None
            running = bool(self._session and self._session.get("state") == "running")
        if session_id and running:
            try:
                # A console shutdown is not a deployment commit.  Do not
                # request SaveMap implicitly; terminate the mapping tree and
                # leave the operator to start a fresh explicit session.
                self.stop(session_id, save=False)
            except Exception:
                LOGGER.exception("关闭时停止建图会话失败")

    # ---- ROS/process implementation ------------------------------------------

    def _refresh_process_state(self) -> None:
        """Turn an unexpected Lightning exit into an operator-visible state."""
        should_stop_listener = False
        with self._lock:
            session = self._session
            process = self._process
            if not session or session.get("state") != "running" or not process:
                return
            exit_code = process.poll()
            if exit_code is None:
                return
            session["state"] = "failed"
            session["error"] = (
                f"Lightning 在线建图已退出（退出码 {exit_code}）。"
                f"请检查会话日志：{session.get('log_path') or self.root / session['id'] / 'lightning.log'}"
            )
            session["preview"]["state"] = "unavailable"
            self._process = None
            self._close_process_log()
            should_stop_listener = True
        if should_stop_listener:
            self._stop_preview_listener()

    def _close_process_log(self) -> None:
        if self._process_log:
            try:
                self._process_log.close()
            except OSError:
                LOGGER.warning("无法关闭建图会话日志", exc_info=True)
            finally:
                self._process_log = None

    def _validate_saved_capture(self, session: dict[str, Any]) -> None:
        """Verify the service generated a deployable map before importing it."""
        output_dir = Path(str(session["output_dir"])).resolve()
        map_yaml = output_dir / "map.yaml"
        if not map_yaml.is_file():
            raise MappingError(f"保存服务未生成 map.yaml：{map_yaml}")
        try:
            payload = yaml.safe_load(map_yaml.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise MappingError(f"无法读取保存后的 map.yaml：{exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("image"), str):
            raise MappingError("保存后的 map.yaml 缺少 image 字段")
        image = Path(payload["image"])
        if image.is_absolute():
            raise MappingError("保存后的 map.yaml 不允许使用绝对 image 路径")
        image = (map_yaml.parent / image).resolve()
        if not image.is_relative_to(output_dir) or not image.is_file():
            raise MappingError(f"保存后的地图图像不存在：{image}")
        try:
            MapAssetCache._pgm_dimensions(image)
        except (OSError, MapAssetError, ValueError) as exc:
            raise MappingError(f"保存后的 PGM 无法读取：{exc}") from exc

    def _probe_lightning(self, *, force: bool = False) -> tuple[bool, str]:
        now = self._clock()
        with self._lock:
            if not force and now - self._probe_at < self.config.probe_cache_s:
                return self._probe_result
        if shutil.which("ros2") is None:
            result = (False, "未找到 ros2；请通过机器人 ROS2 环境启动 Aletheia")
        else:
            try:
                outcome = self._run(
                    ["ros2", "pkg", "executables", "lightning"],
                    capture_output=True, text=True, timeout=3, check=False,
                )
                executables = outcome.stdout or ""
                result = (True, "Lightning 在线建图运行时可用") if "run_slam_online" in executables else (
                    False,
                    "Lightning 未安装 run_slam_online；需先启用并构建 localization 的在线建图目标",
                )
            except Exception as exc:
                result = (False, f"无法检查 Lightning 运行时：{exc}")
        with self._lock:
            self._probe_at = now
            self._probe_result = result
        return result

    def _start_preview_listener(self) -> None:
        if self._node:
            return
        try:
            import rclpy
            from nav_msgs.msg import OccupancyGrid
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        except ImportError as exc:
            raise MappingUnavailable(f"无法加载 ROS2 栅格地图依赖：{exc}") from exc
        if not rclpy.ok():
            rclpy.init()
        self._node = rclpy.create_node("ry_aletheia_mapping_preview")
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self._node.create_subscription(OccupancyGrid, self.config.preview_topic, self._on_grid, qos)
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._thread = threading.Thread(target=self._executor.spin, daemon=True, name="mapping-preview")
        self._thread.start()

    def _stop_preview_listener(self) -> None:
        if self._executor:
            self._executor.shutdown()
        if self._thread:
            self._thread.join(timeout=2)
        if self._node:
            self._node.destroy_node()
        self._node = self._executor = self._thread = None

    def _on_grid(self, message) -> None:
        info = message.info
        self.ingest_grid(
            resolution=float(info.resolution), width=int(info.width), height=int(info.height),
            origin=[float(info.origin.position.x), float(info.origin.position.y), 0.0],
            frame_id=str(message.header.frame_id), data=list(message.data),
        )

    def _save_map(self, map_id: str) -> None:
        # map_id is controller generated (not user shell text), passed as argv
        # and run from the session root; Lightning therefore saves only inside
        # this session's ``data/`` directory.
        outcome = self._run(
            ["ros2", "service", "call", self.config.map_service, "lightning/srv/SaveMap", f"{{map_id: '{map_id}'}}"],
            cwd=str((self.root / map_id).resolve()), timeout=20, check=True,
        )
        output = "\n".join(
            str(part or "") for part in (getattr(outcome, "stdout", ""), getattr(outcome, "stderr", ""))
        )
        responses = re.findall(r"\bresponse\s*(?:=|:)\s*(-?\d+)\b", output)
        if responses and int(responses[-1]) != 0:
            raise MappingError(f"Lightning SaveMap 返回 response={responses[-1]}")

    def _require_session_locked(self, session_id: str, expected: str | None = None) -> dict[str, Any]:
        if not self._session or self._session.get("id") != session_id:
            raise MappingError("建图会话不存在")
        if expected and self._session.get("state") != expected:
            raise MappingError(f"当前建图会话状态为 {self._session.get('state')}，不能执行该操作")
        return self._session

    def _snapshot_locked(self) -> dict[str, Any] | None:
        return {key: (dict(value) if isinstance(value, dict) else value) for key, value in self._session.items()} if self._session else None
