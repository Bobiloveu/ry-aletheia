#!/usr/bin/env bash
set -euo pipefail

# 在小车上运行一次，导出构建 RY Aletheia 所需的最小 ROS 覆盖层。
# 不复制整车 install；仅保留任务服务接口和 Livox CustomMsg 的编译/打包文件。
# 不下载、不安装、不修改 /opt/ry/install；仅读取并生成一个 tar.gz 文件。
SOURCE_ROOT="${ROVER_QA_ROBOT_ROOT:-/opt/ry}"
INSTALL_DIR="$SOURCE_ROOT/install"
PROJECT_NAME="ry-aletheia"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT="${1:-$PWD/${PROJECT_NAME}-robot-build-deps_${STAMP}.tar.gz}"
REQUIRED_PACKAGES=(master_interfaces livox_ros_driver2)
ROOT_FILES=(setup.bash local_setup.bash _local_setup_util_sh.py)

if [[ ! -f "$INSTALL_DIR/setup.bash" ]]; then
  echo "未找到 $INSTALL_DIR/setup.bash，请在机器人小车上执行。" >&2
  exit 1
fi
if [[ -e "$OUTPUT" || -e "$OUTPUT.sha256" ]]; then
  echo "输出或校验文件已存在，拒绝覆盖：$OUTPUT" >&2
  exit 1
fi
for command in cp tar python3 sha256sum; do
  command -v "$command" >/dev/null 2>&1 || { echo "缺少 $command。" >&2; exit 1; }
done
for root_file in "${ROOT_FILES[@]}"; do
  [[ -f "$INSTALL_DIR/$root_file" ]] || {
    echo "参考工作空间缺少根启动文件：$INSTALL_DIR/$root_file" >&2
    exit 1
  }
done
for package in "${REQUIRED_PACKAGES[@]}"; do
  [[ -d "$INSTALL_DIR/$package" ]] || {
    echo "参考工作空间缺少构建必需包：$INSTALL_DIR/$package" >&2
    exit 1
  }
done
[[ -f "$INSTALL_DIR/master_interfaces/lib/libmaster_interfaces__rosidl_typesupport_cpp.so" ]] || {
  echo "master_interfaces 类型支持库不完整。" >&2
  exit 1
}
[[ -f "$INSTALL_DIR/livox_ros_driver2/share/livox_ros_driver2/cmake/livox_ros_driver2Config.cmake" ]] || {
  echo "livox_ros_driver2 CMake 导出文件不完整。" >&2
  exit 1
}

OUTPUT_DIR="$(CDPATH= cd -- "$(dirname -- "$OUTPUT")" && pwd)"
OUTPUT="$OUTPUT_DIR/$(basename -- "$OUTPUT")"
WORK_DIR="$(mktemp -d)"
PAYLOAD_ROOT="$WORK_DIR/payload"
trap 'rm -rf "$WORK_DIR"' EXIT

mkdir -p "$PAYLOAD_ROOT/install"
for root_file in "${ROOT_FILES[@]}"; do
  cp -a "$INSTALL_DIR/$root_file" "$PAYLOAD_ROOT/install/"
done
for package in "${REQUIRED_PACKAGES[@]}"; do
  cp -a "$INSTALL_DIR/$package" "$PAYLOAD_ROOT/install/"
done

# 验证精简后的 setup.bash 本身能加载业务 Python 接口；不能只验证原完整 install。
(
  set +u
  source "$PAYLOAD_ROOT/install/setup.bash"
  set -u
  python3 -c 'import master_interfaces.srv'
)

set +u
source "$INSTALL_DIR/setup.bash"
set -u
python3 - "$PAYLOAD_ROOT/build-deps-manifest.json" "$INSTALL_DIR" <<'PY'
from __future__ import annotations

import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

target = Path(sys.argv[1])
payload = {
    "schema": "ry-aletheia-robot-build-deps/v2-minimal",
    "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "machine": platform.machine(),
    "target_platform": "ubuntu-22.04-amd64",
    "python_abi": f"cp{sys.version_info.major}{sys.version_info.minor}",
    "ros_distro": os.environ.get("ROS_DISTRO", ""),
    "included_packages": ["master_interfaces", "livox_ros_driver2"],
    "required_system_ros_packages": [
        "ament_cmake", "rclcpp", "rclpy", "sensor_msgs", "geometry_msgs",
        "tf2", "tf2_ros", "tf2_msgs", "std_msgs", "nav_msgs",
        "builtin_interfaces", "action_msgs", "rosidl_default_runtime",
    ],
}
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "正在导出最小构建覆盖层（master_interfaces、livox_ros_driver2）..."
tar --create --gzip --file "$OUTPUT" --numeric-owner \
  --exclude='*/__pycache__' \
  --exclude='install/livox_ros_driver2/local' \
  --exclude='install/livox_ros_driver2/share/livox_ros_driver2/config' \
  --exclude='install/livox_ros_driver2/share/livox_ros_driver2/launch_ROS2' \
  --exclude='install/livox_ros_driver2/share/livox_ros_driver2/msg' \
  --directory "$PAYLOAD_ROOT" install build-deps-manifest.json
(cd "$OUTPUT_DIR" && sha256sum "$(basename -- "$OUTPUT")" > "$(basename -- "$OUTPUT").sha256")

echo "依赖包已生成：$OUTPUT"
echo "校验文件：$OUTPUT.sha256"
echo "大小：$(du -h "$OUTPUT" | awk '{print $1}')"
echo "接收方解压后应得到 install/setup.bash、install/master_interfaces 和 install/livox_ros_driver2。"
