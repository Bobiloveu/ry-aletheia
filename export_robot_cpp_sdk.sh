#!/usr/bin/env bash
set -euo pipefail

# 在机器人小车执行一次，导出 Aletheia 实时点云预处理节点所需的 C++ SDK。
# 仅读取已安装包，不联网、不 apt 安装、不修改 /opt/ros 或 /opt/ry。
STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT="${1:-$PWD/ry-aletheia-ros2-cpp-sdk_${STAMP}.tar.gz}"
ROS_PREFIX="${ROS_PREFIX:-/opt/ros/humble}"

if [[ ! -f "$ROS_PREFIX/setup.bash" ]]; then
  echo "未找到 $ROS_PREFIX/setup.bash；请在 ROS2 Humble 小车上执行。" >&2
  exit 1
fi
if [[ -e "$OUTPUT" ]]; then
  echo "输出已存在，拒绝覆盖：$OUTPUT" >&2
  exit 1
fi
for command in dpkg-query python3 tar sha256sum; do
  command -v "$command" >/dev/null 2>&1 || { echo "缺少 $command。" >&2; exit 1; }
done

OUTPUT_DIR="$(CDPATH= cd -- "$(dirname -- "$OUTPUT")" && pwd)"
OUTPUT="$OUTPUT_DIR/$(basename -- "$OUTPUT")"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

# 根包均为本节点直接使用的 ament / rclcpp / sensor_msgs / TF2 开发接口。
# Python 会递归收集其已安装依赖，但只保留头文件、共享库和 CMake/ament 元数据，
# 不导出小车业务程序、地图、任务、日志或 ROS 数据。
python3 - "$WORK_DIR" "$ROS_PREFIX" <<'PY'
from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

work, ros_prefix = Path(sys.argv[1]), Path(sys.argv[2])
roots = {
    "ros-humble-ament-cmake", "ros-humble-rclcpp", "ros-humble-sensor-msgs",
    "ros-humble-geometry-msgs", "ros-humble-tf2", "ros-humble-tf2-ros",
    # rclcpp 的 CMake 导出会引用这些底层 ROS 包。
    "ros-humble-rcutils", "ros-humble-rcl", "ros-humble-rmw",
    "ros-humble-rosidl-runtime-cpp", "ros-humble-rosidl-typesupport-cpp",
    "ros-humble-tf2-msgs", "ros-humble-builtin-interfaces", "ros-humble-std-msgs",
}

def query(package: str, field: str) -> str:
    result = subprocess.run(["dpkg-query", "-W", "-f", "${" + field + "}", package], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return result.stdout.strip() if result.returncode == 0 else ""

def installed(package: str) -> bool:
    return query(package, "db:Status-Abbrev").startswith("ii")

missing = sorted(package for package in roots if not installed(package))
if missing:
    raise SystemExit("小车缺少 ROS2 C++ 开发包：" + ", ".join(missing))

def dependency_names(raw: str) -> list[str]:
    values = []
    for item in raw.split(","):
        alternatives = [re.sub(r"\s*\([^)]*\)", "", value).strip() for value in item.split("|")]
        candidate = next((value for value in alternatives if value and installed(value)), "")
        if candidate:
            values.append(candidate)
    return values

packages, queue = set(), list(roots)
while queue:
    package = queue.pop()
    if package in packages or not installed(package):
        continue
    packages.add(package)
    # 仅递归运行时/开发依赖，不跟随 Recommends，避免 SDK 无边界膨胀。
    queue.extend(dependency_names(query(package, "Pre-Depends")))
    queue.extend(dependency_names(query(package, "Depends")))

paths: set[str] = {"opt/ros/humble/setup.bash", "opt/ros/humble/local_setup.bash"}
for package in sorted(packages):
    listing = subprocess.run(["dpkg-query", "-L", package], text=True, stdout=subprocess.PIPE, check=True).stdout.splitlines()
    for absolute in listing:
        path = absolute.lstrip("/")
        if not path or absolute.endswith("/"):
            continue
        # ROS 前缀完整保留其开发元数据；系统路径只取编译/链接必需内容。
        if absolute.startswith(str(ros_prefix) + "/"):
            paths.add(path)
        elif absolute.startswith("/usr/include/") or "/cmake/" in absolute or "/pkgconfig/" in absolute:
            paths.add(path)
        elif absolute.startswith("/usr/lib/") and (".so" in absolute or "/ament_index/" in absolute):
            paths.add(path)

# 某些机器人镜像中的 dpkg 文件数据库不完整，但 ROS2 头文件实际仍位于前缀内。
# 不能只依赖 dpkg -L；直接从已验证的 ROS 前缀收集本节点及其导出依赖的头文件。
header_roots = (
    "ament_index_cpp", "builtin_interfaces", "geometry_msgs", "rcl", "rcl_interfaces",
    "rclcpp", "rcpputils", "rcutils", "rmw", "rosidl_runtime_cpp",
    "rosidl_typesupport_cpp", "sensor_msgs", "statistics_collector", "std_msgs",
    "tf2", "tf2_msgs", "tf2_ros", "tracetools",
)
include_root = ros_prefix / "include"
# ROS Humble 的 Debian 安装按包名再嵌套一层 include 目录；CMake 导出的
# include 路径会进入这一层，因此源码仍然使用 <rclcpp/rclcpp.hpp>。
required_headers = (
    "rclcpp/rclcpp/rclcpp.hpp",
    "sensor_msgs/sensor_msgs/msg/point_cloud2.hpp",
    "tf2_ros/tf2_ros/buffer.h",
)
missing_headers = [str(include_root / item) for item in required_headers if not (include_root / item).is_file()]
if missing_headers:
    raise SystemExit("小车 ROS2 C++ 头文件不完整，无法导出 SDK：" + ", ".join(missing_headers))
for name in header_roots:
    directory = include_root / name
    if directory.is_dir():
        for item in directory.rglob("*"):
            if item.is_file() or item.is_symlink():
                paths.add(str(item).lstrip("/"))

existing = sorted(path for path in paths if Path("/", path).exists() or Path("/", path).is_symlink())
(work / "files.txt").write_text("\n".join(existing) + "\n", encoding="utf-8")
manifest = {
    "schema": "ry-aletheia-ros2-cpp-sdk/v1",
    "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "machine": platform.machine(),
    "ros_prefix": str(ros_prefix),
    "packages": sorted(packages),
    "file_count": len(existing),
}
(work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "正在导出 ROS2 C++ SDK（仅开发文件与链接库）..."
tar --create --gzip --file "$OUTPUT" --numeric-owner --directory / \
  --files-from "$WORK_DIR/files.txt" \
  --transform='s,^,sdk/,' \
  --directory "$WORK_DIR" manifest.json

(cd "$OUTPUT_DIR" && sha256sum "$(basename -- "$OUTPUT")" > "$(basename -- "$OUTPUT").sha256")
echo "SDK 已生成：$OUTPUT"
echo "校验文件：$OUTPUT.sha256"
echo "请将两个文件放入开发机工程根目录的 cpp_sdk/ 目录。"
