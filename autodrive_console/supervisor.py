from __future__ import annotations

import shlex
import subprocess
import re
import logging
from dataclasses import dataclass


# A Supervisor name is data, never an argument fragment.  Grouped processes
# use ``GROUP:PROGRAM``; a single program name is also valid.  Keep this shared
# boundary strict even though subprocess is invoked without a shell.
SUPERVISOR_PROCESS_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}(?::[A-Za-z0-9][A-Za-z0-9_.-]{0,127})?\Z")
LOGGER = logging.getLogger("ry_aletheia.supervisor")


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

    def tail_stdout(self, process_name: str) -> subprocess.Popen[bytes]:
        """Follow one already-validated Supervisor program's stdout.

        The caller owns the returned process and must terminate it when its
        browser connection closes.  ``process_name`` is never shell input;
        the console derives it from the active Supervisor status snapshot.
        """

        if not isinstance(process_name, str) or not SUPERVISOR_PROCESS_NAME.fullmatch(process_name):
            raise RuntimeError("Supervisor 节点名称不合法")
        try:
            return subprocess.Popen(
                [*self._base_args(), "tail", "-f", process_name, "stdout"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                bufsize=0,
            )
        except OSError as exc:
            raise RuntimeError(f"无法启动 Supervisor 日志跟随：{exc}") from exc

    def _control(self, action: str, process_name: str) -> None:
        if action not in {"start", "restart"} or not isinstance(process_name, str) or not SUPERVISOR_PROCESS_NAME.fullmatch(process_name):
            raise RuntimeError("Supervisor 节点名称不合法")
        LOGGER.info("Supervisor 控制请求：action=%s node=%s", action, process_name)
        try:
            result = self._run([*self._base_args(), action, process_name])
        except RuntimeError as exc:
            # Exception text may contain the configured supervisorctl credentials.
            LOGGER.error("Supervisor 控制调用失败：action=%s node=%s error_type=%s", action, process_name, type(exc.__cause__ or exc).__name__)
            raise
        if result.returncode != 0:
            LOGGER.error("Supervisor 控制返回失败：action=%s node=%s exit_code=%s", action, process_name, result.returncode)
            detail = (result.stderr or result.stdout).strip().replace("\n", " ")
            raise RuntimeError(detail or f"退出码 {result.returncode}")
        LOGGER.info("Supervisor 控制命令已完成：action=%s node=%s", action, process_name)

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
