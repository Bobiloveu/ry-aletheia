#!/usr/bin/env bash
set -euo pipefail

# 在机器人小车本机离线执行；优先使用小车真实 /opt/ry/install 环境。
# 产物为 dist/ry-aletheia 单文件核心程序。运行阶段不需要 PyInstaller、源码或网络。
# 任务 JSON、.autodrive_console.json 和 reports/ 均是二进制外部的运行数据，不会被打包。
# 必须加载包含 master_interfaces 的机器人工作空间；否则生成的程序无法调用任务服务。
BUILD_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
FRONTEND_ROOT="$BUILD_ROOT/frontend"
VIDEO_CONFIG_DEFAULT="${RY_ALETHEIA_VIDEO_CONFIG:-$BUILD_ROOT/config/video.ros.json}"
if [[ ! -f "$VIDEO_CONFIG_DEFAULT" ]]; then
  echo "未找到要嵌入的视频默认配置：$VIDEO_CONFIG_DEFAULT" >&2
  exit 1
fi
if [[ ! -d "$FRONTEND_ROOT/node_modules" ]]; then
  echo "未找到前端依赖。请在开发机执行：cd frontend && npm install" >&2
  exit 1
fi
# Vite 7 需要 Node.js 20+。开发机可能同时安装系统 Node 12 和 nvm；在脚本
# 被 IDE、非交互 shell 或自动化任务调用时，显式激活 nvm 默认版本，避免静默回退。
if ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' >/dev/null 2>&1; then
  if [[ -s "$HOME/.nvm/nvm.sh" ]]; then
    set +e
    source "$HOME/.nvm/nvm.sh"
    nvm use --silent default >/dev/null 2>&1
    set -e
  fi
fi
if ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' >/dev/null 2>&1; then
  echo "前端构建需要 Node.js 20 或更高版本；请安装 Node 20 LTS，或执行 nvm install 20 && nvm alias default 20。" >&2
  exit 1
fi
echo "正在构建 Vue 前端资源..."
(cd "$FRONTEND_ROOT" && npm run check)
ROBOT_SETUP="${ROVER_QA_ROS_SETUP:-/opt/ry/install/setup.bash}"
if [[ -f "$ROBOT_SETUP" ]]; then
  set +u
  source "$ROBOT_SETUP"
  set -u
  ROS_INSTALL_PREFIX="$(CDPATH= cd -- "$(dirname -- "$ROBOT_SETUP")" && pwd)"
elif [[ -f "$BUILD_ROOT/install/setup.bash" ]]; then
  # colcon 的 setup.bash 会读取可选的未定义变量，与 set -u 不兼容。
  set +u
  source "$BUILD_ROOT/install/setup.bash"
  set -u
  ROS_INSTALL_PREFIX="$BUILD_ROOT/install"
else
  echo "未找到 ROS2 环境：$ROBOT_SETUP" >&2
  exit 1
fi
if ! python3 -c 'import PyInstaller' >/dev/null 2>&1; then
  OFFLINE_PYINSTALLER="$BUILD_ROOT/tools/pyinstaller"
  if [[ ! -d "$OFFLINE_PYINSTALLER/PyInstaller" ]]; then
    echo "未找到 PyInstaller。请保留工程内 tools/pyinstaller 离线构建工具。" >&2
    exit 1
  fi
  export PYTHONPATH="$OFFLINE_PYINSTALLER${PYTHONPATH:+:$PYTHONPATH}"
fi
python3 -c 'import rclpy; import master_interfaces.srv; import tf2_msgs.msg' || {
  echo "缺少 ROS2 接口包 master_interfaces 或 tf2_msgs。请确认工程内 install/ 完整，或先加载匹配的小车 install/setup.bash。" >&2
  exit 1
}
echo "正在构建实时点云预处理节点..."
cmake -S "$BUILD_ROOT/live_preprocessor" -B "$BUILD_ROOT/build/live_preprocessor" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_ROOT/build/live_preprocessor" --parallel 2
LIVE_PREPROCESSOR="$BUILD_ROOT/build/live_preprocessor/aletheia_live_cloud"
[[ -x "$LIVE_PREPROCESSOR" ]] || { echo "实时点云预处理节点构建失败。" >&2; exit 1; }
VIDEO_INGEST="$BUILD_ROOT/build/live_preprocessor/aletheia_video_ingest"
[[ -x "$VIDEO_INGEST" ]] || { echo "原生视频输入节点构建失败。" >&2; exit 1; }
# 网页 ZIP 升级只替换单文件二进制。将私有视频 runtime 一同封入该二进制，
# 新版本首次启用视频时便可安全刷新 $WORKSPACE/runtime/video，无需改用 DEB。
VIDEO_RUNTIME="${RY_ALETHEIA_VIDEO_RUNTIME:-}"
if [[ -z "$VIDEO_RUNTIME" ]]; then
  VIDEO_RUNTIME_PARENT="$(mktemp -d)"
  VIDEO_RUNTIME="$VIDEO_RUNTIME_PARENT/runtime"
  trap 'rm -rf "$VIDEO_RUNTIME_PARENT"' EXIT
  "$BUILD_ROOT/build_video_runtime.sh" --output-dir "$VIDEO_RUNTIME"
fi
[[ -f "$VIDEO_RUNTIME/ry-aletheia-runtime.json" ]] || {
  echo "私有视频 runtime 不完整：缺少 ry-aletheia-runtime.json" >&2
  exit 1
}
ROSIDL_LIBRARIES=()
# Python 的 --collect-all 不会稳定收集 ROS2 运行时动态选择的类型支持库。
# 任务服务和 TF 监听均需要它们；从所有已 source 的 prefix 收集，兼容接口包位于
# 工作空间 install 或系统 /opt/ros 下的两种部署。
AMENT_PREFIXES=("$ROS_INSTALL_PREFIX")
if [[ -n "${AMENT_PREFIX_PATH:-}" ]]; then
  IFS=: read -r -a SOURCED_PREFIXES <<< "$AMENT_PREFIX_PATH"
  AMENT_PREFIXES+=("${SOURCED_PREFIXES[@]}")
fi
for package in master_interfaces tf2_msgs; do
  found=false
  for prefix in "${AMENT_PREFIXES[@]}"; do
    # 工作空间的 isolated install 常用 <prefix>/<package>/lib；系统 ROS2
    # 与 merge-install 则使用 <prefix>/lib。两者都要支持。
    for library_dir in "$prefix/$package/lib" "$prefix/lib"; do
      for library in "$library_dir"/lib"$package"__rosidl_*.so; do
        if [[ -f "$library" ]]; then
          ROSIDL_LIBRARIES+=("$library")
          found=true
        fi
      done
    done
  done
  if [[ "$found" != true ]]; then
    echo "未找到 $package 的 ROS 类型支持库；请确认已加载完整的小车 ROS2 环境。" >&2
    exit 1
  fi
done
# 同一类型支持库可能同时出现在工作空间与 AMENT_PREFIX_PATH 中。先去重、排序，
# 保证生成的 PyInstaller spec 与打包二进制不因 source 顺序不同而产生无意义变更。
mapfile -t ROSIDL_LIBRARIES < <(printf '%s\n' "${ROSIDL_LIBRARIES[@]}" | LC_ALL=C sort -u)
ROSIDL_LIBRARY_ARGS=()
for library in "${ROSIDL_LIBRARIES[@]}"; do
  ROSIDL_LIBRARY_ARGS+=(--add-binary "$library:.")
done
python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name ry-aletheia \
  --add-data "autodrive_console/web:autodrive_console/web" \
  --add-data "autodrive_console/web-vue:autodrive_console/web-vue" \
  --add-data "$VIDEO_CONFIG_DEFAULT:config/video.json" \
  --add-data "$VIDEO_RUNTIME:runtime/video" \
  --add-binary "$LIVE_PREPROCESSOR:." \
  --add-binary "$VIDEO_INGEST:." \
  --hidden-import rclpy \
  --hidden-import master_interfaces.srv \
  --collect-all rclpy \
  --collect-all tf2_ros \
  --collect-all tf2_py \
  --collect-all tf2_msgs \
  --collect-all rpyutils \
  --collect-all master_interfaces \
  --collect-all rosidl_parser \
  --collect-all rosidl_runtime_py \
  --collect-all rcl_interfaces \
  --collect-all builtin_interfaces \
  --collect-all std_msgs \
  --collect-all unique_identifier_msgs \
  --collect-all action_msgs \
  --collect-all nav_msgs \
  --collect-all geometry_msgs \
  "${ROSIDL_LIBRARY_ARGS[@]}" \
  web_console.py
