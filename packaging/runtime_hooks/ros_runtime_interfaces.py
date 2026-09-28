"""Load vehicle-specific ROS interfaces before frozen application imports.

PyInstaller runtime hooks execute before the application entry point.  The
launcher has already sourced the robot ROS environment, so AMENT_PREFIX_PATH
is the only approved source for a vehicle's master_interfaces package.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable


def runtime_interface_paths(
    ament_prefix_path: str | None,
    *,
    python_version: str,
    exists: Callable[[str], bool] = os.path.isdir,
) -> list[str]:
    """Return declared site-package paths that actually provide master_interfaces."""
    paths: list[str] = []
    for prefix in (ament_prefix_path or "").split(os.pathsep):
        if not prefix:
            continue
        site_packages = os.path.join(
            prefix, "local", "lib", python_version, "dist-packages"
        )
        if exists(os.path.join(site_packages, "master_interfaces")):
            paths.append(site_packages)
    return list(dict.fromkeys(paths))


def prepend_runtime_interface_paths(
    ament_prefix_path: str | None,
    *,
    python_version: str,
) -> None:
    """Put declared vehicle interface paths before PyInstaller extraction paths."""
    for path in reversed(
        runtime_interface_paths(ament_prefix_path, python_version=python_version)
    ):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)


prepend_runtime_interface_paths(
    os.environ.get("AMENT_PREFIX_PATH"),
    python_version=f"python{sys.version_info.major}.{sys.version_info.minor}",
)
