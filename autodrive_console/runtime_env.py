from __future__ import annotations

import os
from collections.abc import MutableMapping


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
