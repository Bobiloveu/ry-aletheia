from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path


def clear_legacy_fastdds_override(environment: MutableMapping[str, str] | None = None) -> bool:
    """Remove only the UDPv4 override inherited from console version 0.6.14.

    A process launched by the old console after an in-place upgrade inherits its
    environment. That release set both markers below; keeping this condition
    narrow ensures an operator's own Fast DDS transport setting is untouched.
    """
    environment = os.environ if environment is None else environment
    if environment.get("ROVER_QA_ROS_READY") != "1" or environment.get("FASTDDS_BUILTIN_TRANSPORTS") != "UDPv4":
        return False
    environment.pop("FASTDDS_BUILTIN_TRANSPORTS", None)
    return True


def should_resource_robot_setup(
    environment: MutableMapping[str, str],
    setup_script: str,
    *,
    force: bool = False,
) -> bool:
    """Decide whether the console must reload the vehicle ROS environment.

    ``ROVER_QA_ROS_READY`` is only a re-exec marker.  It cannot prove that a
    restarted binary still inherited the vehicle workspace and its type
    support libraries.
    """
    if force:
        return True
    robot_prefix = Path(setup_script).parent
    prefixes = environment.get("AMENT_PREFIX_PATH", "").split(os.pathsep)
    # A merged colcon install normally exports individual package prefixes
    # (for example ``.../master_interfaces``), not the workspace root.  The
    # interface package plus its library is the capability the console needs
    # to prove that the vehicle workspace is already active.
    interface_prefix = robot_prefix / "master_interfaces"
    library_path = str(interface_prefix / "lib")
    libraries = environment.get("LD_LIBRARY_PATH", "").split(os.pathsep)
    prefix_ready = str(robot_prefix) in prefixes or str(interface_prefix) in prefixes
    return not (prefix_ready and library_path in libraries)
