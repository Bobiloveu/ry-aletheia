"""Verify the running localizer's empty-map-path protocol without reading YAML."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
from typing import BinaryIO


class RelocalizationConfigError(ValueError):
    pass


INSTALL_ROOT = Path("/opt/ry/install/lightning")
PROC_ROOT = Path("/proc")
# Verified against the supplied vendor package and the live vehicle on 2026-10-14.
# A new build must be reviewed before granting this protocol capability; its
# version string alone does not prove that a running, unrestarted node supports it.
VERIFIED_BUILDS = {
    "1.6.5+compatible.5": (
        "818d02d78d8a05cffd50e117530f883851e52b61ce16e7531a46b22aa6caa435",
        "52cd8508916f4695de0ca9b5d5647fed2ad0eb2197237ad68afb9a28f9172610",
    ),
}


def _digest(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _identity(stat: os.stat_result) -> tuple[int, int, int, int]:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


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
            entries = [item for item in (process / "environ").read_bytes().split(b"\0") if item]
            if any(b"=" not in item for item in entries):
                raise ValueError("invalid process environment")
            environment = dict(item.split(b"=", 1) for item in entries)
            process_domain = int(environment.get(b"ROS_DOMAIN_ID", b"0"))
            if process_domain < 0:
                raise ValueError("invalid ROS domain")
            if process_domain == domain:
                processes.append(process)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            raise RelocalizationConfigError("定位进程的 ROS 域无法确认，不能证明运行实例唯一") from exc
    if len(processes) != 1:
        raise RelocalizationConfigError("当前定位进程无法唯一确认")
    return processes[0]


def localizer_runtime_identity() -> tuple[int, str]:
    """Bind an instance for pose editing without granting empty-path capability."""
    try:
        process = _running_localizer()
        return int(process.name), _start_time(process)
    except RelocalizationConfigError:
        raise
    except (OSError, ValueError, IndexError) as exc:
        raise RelocalizationConfigError("当前定位进程无法唯一确认") from exc


def verify_current_config_runtime() -> tuple[int, str]:
    """Return the unique verified process identity, not its startup YAML path.

    The request delegates configuration selection to this running node. It must
    never silently select a startup file, a behavior-tree file or a backup.
    """
    try:
        package = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}", "ry-lightning"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        expected = VERIFIED_BUILDS.get(package.stdout.strip()) if package.returncode == 0 else None
        if expected is None:
            raise RelocalizationConfigError("当前定位版本尚未核验沿用配置能力")
        executable = INSTALL_ROOT / "lib/lightning/run_loc_online"
        library = INSTALL_ROOT / "lib/liblightning.libs.so"
        process = _running_localizer()
        start_time = _start_time(process)
        # Hash the same opened files whose inode identities are checked. An
        # atomic package replacement cannot substitute new bytes after checking
        # an old running inode, nor can in-place edits escape the final stat.
        with executable.open("rb") as exe_stream, library.open("rb") as lib_stream:
            exe_stat, lib_stat = os.fstat(exe_stream.fileno()), os.fstat(lib_stream.fileno())
            if _identity((process / "exe").stat()) != _identity(exe_stat):
                raise RelocalizationConfigError("运行中的定位程序与已核验版本不一致")
            loaded = False
            for line in (process / "maps").read_text().splitlines():
                fields = line.split(maxsplit=5)
                if len(fields) != 6 or fields[5] != str(library):
                    continue
                major, minor = (int(value, 16) for value in fields[3].split(":"))
                if (major, minor, int(fields[4])) == (os.major(lib_stat.st_dev), os.minor(lib_stat.st_dev), lib_stat.st_ino):
                    loaded = True
            if not loaded or (_digest(exe_stream), _digest(lib_stream)) != expected:
                raise RelocalizationConfigError("运行中的定位库未通过沿用配置能力核验")
            if (
                _identity(executable.stat()) != _identity(exe_stat)
                or _identity(library.stat()) != _identity(lib_stat)
                or _identity(os.fstat(exe_stream.fileno())) != _identity(exe_stat)
                or _identity(os.fstat(lib_stream.fileno())) != _identity(lib_stat)
                or _start_time(process) != start_time
            ):
                raise RelocalizationConfigError("核验期间定位运行版本发生变化")
        return int(process.name), start_time
    except RelocalizationConfigError:
        raise
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
        raise RelocalizationConfigError("当前定位配置沿用能力无法确认") from exc
