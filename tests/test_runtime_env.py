from __future__ import annotations

from autodrive_console.runtime_env import should_resource_robot_setup


def test_stale_ready_marker_does_not_replace_robot_ros_environment_proof():
    setup = "/opt/ry/install/setup.bash"
    environment = {
        "ROVER_QA_ROS_READY": "1",
        "AMENT_PREFIX_PATH": "/opt/ros/humble",
        "LD_LIBRARY_PATH": "/opt/ros/humble/lib",
    }

    assert should_resource_robot_setup(environment, setup) is True


def test_cleared_legacy_transport_forces_one_fresh_robot_setup_source():
    setup = "/opt/ry/install/setup.bash"
    environment = {
        "ROVER_QA_ROS_READY": "1",
        "AMENT_PREFIX_PATH": "/opt/ry/install:/opt/ros/humble",
        "LD_LIBRARY_PATH": "/opt/ry/install/master_interfaces/lib:/opt/ros/humble/lib",
    }

    assert should_resource_robot_setup(environment, setup, force=True) is True
    assert should_resource_robot_setup(environment, setup) is False


def test_merged_workspace_package_prefix_proves_robot_environment_is_ready():
    """colcon 的环境会列出包前缀，而非安装根目录本身。"""
    setup = "/opt/ry/install/setup.bash"
    environment = {
        "AMENT_PREFIX_PATH": "/opt/ry/install/master_interfaces:/opt/ry/install/nav2_monitor:/opt/ros/humble",
        "LD_LIBRARY_PATH": "/opt/ry/install/master_interfaces/lib:/opt/ros/humble/lib",
    }

    assert should_resource_robot_setup(environment, setup) is False
