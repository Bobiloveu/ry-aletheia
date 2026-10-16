"""Bind the current localizer instance without version gates or YAML inference."""
from __future__ import annotations

import os
from pathlib import Path


class RelocalizationConfigError(ValueError):
    pass


PROC_ROOT = Path("/proc")


def _start_time(process: Path) -> str:
    return (process / "stat").read_text().rsplit(")", 1)[1].split()[19]


def _running_localizer() -> Path:
    domain = int(os.environ.get("ROS_DOMAIN_ID", "0"))
    processes = []
    for process in PROC_ROOT.iterdir():
        if not process.name.isdigit():
            continue
        try:
            command = (process / "cmdline").read_bytes().split(b"\0")[0]
            if Path(os.fsdecode(command)).name != "run_loc_online":
                continue
        except OSError:
            continue
        try:
            start_time = _start_time(process)
            entries = [item for item in (process / "environ").read_bytes().split(b"\0") if item]
            if any(b"=" not in item for item in entries):
                raise ValueError("invalid process environment")
            environment = dict(item.split(b"=", 1) for item in entries)
            process_domain = int(environment.get(b"ROS_DOMAIN_ID", b"0"))
            if process_domain < 0:
                raise ValueError("invalid ROS domain")
            if process_domain == domain:
                if _start_time(process) != start_time:
                    raise RelocalizationConfigError("手动重定位期间定位进程发生变化，请恢复后重新对齐")
                processes.append(process)
        except FileNotFoundError:
            continue
        except RelocalizationConfigError:
            raise
        except (OSError, ValueError) as exc:
            raise RelocalizationConfigError("定位进程的 ROS 域无法确认，不能证明运行实例唯一") from exc
    if len(processes) != 1:
        raise RelocalizationConfigError("当前定位进程无法唯一确认")
    return processes[0]


def localizer_runtime_identity() -> tuple[int, str]:
    """Identify the unique ROS-domain instance; PID reuse changes its start time.

    Empty ``map_path`` is the Relocalize service contract, not a property inferred
    from a package version or installed file. The controller still checks this
    identity immediately before sending and requires actual service responses.
    """
    try:
        process = _running_localizer()
        start_time = _start_time(process)
        # Recheck command, domain and uniqueness after collecting the identity.
        # This catches exec/domain changes and newly appearing contenders without
        # tying an accepted instance to a version or an installed binary hash.
        if _running_localizer() != process or _start_time(process) != start_time:
            raise RelocalizationConfigError("手动重定位期间定位进程发生变化，请恢复后重新对齐")
        return int(process.name), start_time
    except RelocalizationConfigError:
        raise
    except (OSError, ValueError, IndexError) as exc:
        raise RelocalizationConfigError("当前定位进程无法唯一确认") from exc
