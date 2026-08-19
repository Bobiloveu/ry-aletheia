from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class SupervisorProcess:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


class SupervisorClient:
    """受限的 Supervisor 状态查询与节点启动/重启客户端。"""

    def __init__(self, status_command: str, timeout_s: int) -> None:
        self.status_command = status_command
        self.timeout_s = timeout_s

    def discover(self) -> list[SupervisorProcess]:
        result = self._run(self._status_args())
        records = []
        for line in result.stdout.splitlines():
            columns = line.split(maxsplit=2)
            if len(columns) >= 2:
                records.append(SupervisorProcess(columns[0], columns[1].upper(), columns[2] if len(columns) > 2 else ""))
        if not records:
            detail = (result.stderr or result.stdout).strip().replace("\n", " ")
            raise RuntimeError(f"Supervisor 进程发现失败：{detail or f'退出码 {result.returncode}'}")
        return records

    def restart(self, process_name: str) -> None:
        self._control("restart", process_name)

    def start(self, process_name: str) -> None:
        self._control("start", process_name)

    def _control(self, action: str, process_name: str) -> None:
        if not process_name or any(char.isspace() for char in process_name):
            raise RuntimeError("Supervisor 节点名称不合法")
        result = self._run([*self._base_args(), action, process_name])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().replace("\n", " ")
            raise RuntimeError(detail or f"退出码 {result.returncode}")

    def _status_args(self) -> list[str]:
        return [*self._base_args(), "status"]

    def _base_args(self) -> list[str]:
        try:
            args = shlex.split(self.status_command)
        except ValueError as exc:
            raise RuntimeError(f"Supervisor 命令格式错误：{exc}") from exc
        if len(args) < 2 or args[-1] != "status":
            raise RuntimeError("Supervisor 状态命令必须以 status 结尾")
        return args[:-1]

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=self.timeout_s, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"无法执行 Supervisor 命令：{exc}") from exc
