"""Per-user console autostart integration.

The console is intentionally owned by the operator's account.  Autostart
therefore writes only to the user's systemd scope (or XDG autostart fallback)
and never installs or edits a root system unit.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Callable, Sequence


class AutostartError(RuntimeError):
    """Raised when an autostart configuration cannot be installed safely."""


DEFAULT_ROS_DOMAIN_ID = 66


class AutostartManager:
    SERVICE_NAME = "ry-aletheia.service"
    DESKTOP_NAME = "ry-aletheia.desktop"

    def __init__(
        self,
        workspace: Path,
        *,
        home: Path | None = None,
        launcher: Sequence[str] | None = None,
        ros_domain_id: int | None = None,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.home = Path(home or Path.home()).expanduser().resolve()
        self.launcher = tuple(launcher or ("/usr/bin/ry-aletheia",))
        if not self.launcher or any(not str(item).strip() for item in self.launcher):
            raise ValueError("开机自启启动命令不能为空")
        self.ros_domain_id = self._resolve_ros_domain_id(ros_domain_id)
        self.runner = runner

    @property
    def service_path(self) -> Path:
        return self.home / ".config" / "systemd" / "user" / self.SERVICE_NAME

    @property
    def desktop_path(self) -> Path:
        return self.home / ".config" / "autostart" / self.DESKTOP_NAME

    def status(self) -> dict[str, object]:
        if self.service_path.is_file():
            return {
                "enabled": True,
                "supported": True,
                "mode": "systemd-user",
                "message": "已配置为当前用户登录后启动",
            }
        if self.desktop_path.is_file():
            return {
                "enabled": True,
                "supported": True,
                "mode": "desktop-autostart",
                "message": "已配置为桌面会话登录后启动",
            }
        return {
            "enabled": False,
            "supported": True,
            "mode": "none",
            "message": "未启用开机自启",
        }

    def apply(self, enabled: bool) -> dict[str, object]:
        if not isinstance(enabled, bool):
            raise AutostartError("开机自启开关必须是布尔值")
        if not enabled:
            self._disable_systemd_unit()
            self._remove(self.service_path)
            self._remove(self.desktop_path)
            return self.status()

        self._remove(self.desktop_path)
        try:
            self._write_service()
            self._systemctl("daemon-reload")
            self._systemctl("enable", self.SERVICE_NAME)
            return self.status()
        except (OSError, subprocess.SubprocessError, AutostartError):
            # A desktop session may not expose a user systemd bus.  The XDG
            # entry remains per-user and requires no elevated permission.
            self._remove(self.service_path)
            self._write_desktop_entry()
            return self.status()

    def _write_service(self) -> None:
        self.service_path.parent.mkdir(parents=True, exist_ok=True)
        command = shlex.join([str(item) for item in self.launcher])
        body = "\n".join(
            [
                "[Unit]",
                "Description=RY Aletheia automated test console",
                "After=network-online.target",
                "Wants=network-online.target",
                "",
                "[Service]",
                f"ExecStart={command}",
                f"WorkingDirectory={self.workspace}",
                "Restart=on-failure",
                "RestartSec=3",
                "Environment=PYTHONUNBUFFERED=1",
                f"Environment=ROS_DOMAIN_ID={self.ros_domain_id}",
                "",
                "[Install]",
                "WantedBy=default.target",
                "",
            ]
        )
        self.service_path.write_text(body, encoding="utf-8")

    def _write_desktop_entry(self) -> None:
        self.desktop_path.parent.mkdir(parents=True, exist_ok=True)
        command = shlex.join(["env", f"ROS_DOMAIN_ID={self.ros_domain_id}", *self.launcher])
        body = "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=RY Aletheia",
                "Comment=RY Aletheia automated test console",
                f"Exec={command}",
                "Terminal=false",
                "X-GNOME-Autostart-enabled=true",
                "",
            ]
        )
        self.desktop_path.write_text(body, encoding="utf-8")

    def _resolve_ros_domain_id(self, configured: int | None) -> int:
        """Resolve the robot DDS domain used by every autostart mode.

        The video configuration is the existing persisted source of truth for
        the robot's ROS domain.  Falling back to the inherited environment
        keeps developer launches convenient, while the fixed vehicle default
        keeps a fresh installation aligned with the deployed robot image.
        """
        candidates: list[object] = [configured]
        config_path = self.workspace / "config" / "video.json"
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                candidates.append(raw.get("ros_domain_id"))
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        candidates.append(os.environ.get("ROS_DOMAIN_ID"))
        candidates.append(DEFAULT_ROS_DOMAIN_ID)
        for value in candidates:
            try:
                domain_id = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= domain_id <= 232:
                return domain_id
        return DEFAULT_ROS_DOMAIN_ID

    def _systemctl(self, *arguments: str) -> None:
        result = self.runner(
            ["systemctl", "--user", *arguments],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            detail = str(result.stderr or "").strip()
            raise AutostartError(detail or "当前用户的 systemd 会话不可用")

    def _disable_systemd_unit(self) -> None:
        try:
            self._systemctl("disable", self.SERVICE_NAME)
            self._systemctl("daemon-reload")
        except (OSError, subprocess.SubprocessError, AutostartError):
            # Removal below is the source of truth even if a desktop session
            # has already gone away and systemctl cannot reach its user bus.
            return

    @staticmethod
    def _remove(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
