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


def test_runtime_interface_paths_accepts_declared_vehicle_service_interface_packages(
    tmp_path: Path,
) -> None:
    """A frozen app must restore every ROS interface it imports at runtime."""
    master_prefix = tmp_path / "master"
    master_package = master_prefix / "local" / "lib" / "python3.10" / "dist-packages" / "master_interfaces"
    master_package.mkdir(parents=True)
    lightning_prefix = tmp_path / "lightning"
    lightning_package = lightning_prefix / "local" / "lib" / "python3.10" / "dist-packages" / "lightning"
    lightning_package.mkdir(parents=True)
    missing_prefix = tmp_path / "missing"
    namespace = _hook_namespace()
    runtime_interface_paths = namespace["runtime_interface_paths"]

    assert runtime_interface_paths(
        os.pathsep.join((str(master_prefix), str(lightning_prefix), str(missing_prefix))),
        python_version="python3.10",
    ) == [str(master_package.parent), str(lightning_package.parent)]


def test_runtime_interface_paths_leaves_frozen_nav2_action_interfaces_in_the_bundle(
    tmp_path: Path,
) -> None:
    prefix = tmp_path / "nav2"
    package = prefix / "local" / "lib" / "python3.10" / "dist-packages" / "nav2_msgs"
    package.mkdir(parents=True)

    namespace = _hook_namespace()

    assert namespace["runtime_interface_paths"](str(prefix), python_version="python3.10") == []


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
