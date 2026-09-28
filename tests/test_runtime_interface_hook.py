from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys


HOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "packaging"
    / "runtime_hooks"
    / "ros_runtime_interfaces.py"
)


def _hook_namespace() -> dict[str, object]:
    assert HOOK_PATH.is_file(), "vehicle runtime interface hook is missing"
    return runpy.run_path(str(HOOK_PATH))


def test_runtime_interface_paths_accepts_only_declared_existing_master_packages(
    tmp_path: Path,
) -> None:
    """A frozen app may only source the vehicle interface from AMENT prefixes."""
    good_prefix = tmp_path / "vehicle"
    package = good_prefix / "local" / "lib" / "python3.10" / "dist-packages" / "master_interfaces"
    package.mkdir(parents=True)
    missing_prefix = tmp_path / "missing"
    namespace = _hook_namespace()
    runtime_interface_paths = namespace["runtime_interface_paths"]

    assert runtime_interface_paths(
        os.pathsep.join((str(good_prefix), str(missing_prefix))),
        python_version="python3.10",
    ) == [str(package.parent)]


def test_prepend_runtime_interface_paths_precedes_frozen_path(
    monkeypatch, tmp_path: Path
) -> None:
    """The target package has to win over PyInstaller's temporary extraction path."""
    prefix = tmp_path / "vehicle"
    package = prefix / "local" / "lib" / "python3.10" / "dist-packages" / "master_interfaces"
    package.mkdir(parents=True)
    monkeypatch.setattr(sys, "path", ["/tmp/_MEI/frozen", str(package.parent)])
    namespace = _hook_namespace()
    prepend_runtime_interface_paths = namespace["prepend_runtime_interface_paths"]

    prepend_runtime_interface_paths(str(prefix), python_version="python3.10")

    assert sys.path == [str(package.parent), "/tmp/_MEI/frozen"]


def test_prepend_runtime_interface_paths_removes_unapproved_interface_path(
    monkeypatch, tmp_path: Path
) -> None:
    """A stray PYTHONPATH package must not become the vehicle interface fallback."""
    approved_prefix = tmp_path / "vehicle"
    approved = (
        approved_prefix
        / "local"
        / "lib"
        / "python3.10"
        / "dist-packages"
        / "master_interfaces"
    )
    approved.mkdir(parents=True)
    unapproved = tmp_path / "pythonpath" / "master_interfaces"
    unapproved.mkdir(parents=True)
    monkeypatch.setenv("AMENT_PREFIX_PATH", str(approved_prefix))
    monkeypatch.setattr(sys, "path", [str(unapproved.parent), "/tmp/_MEI/frozen"])

    namespace = _hook_namespace()
    prepend_runtime_interface_paths = namespace["prepend_runtime_interface_paths"]
    prepend_runtime_interface_paths(str(approved_prefix), python_version="python3.10")

    assert sys.path == [str(approved.parent), "/tmp/_MEI/frozen"]
