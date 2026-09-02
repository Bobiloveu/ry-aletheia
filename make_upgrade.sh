#!/usr/bin/env bash
set -euo pipefail

# 开发机一键生成网页离线升级 ZIP。默认嵌入 ROS 相机模板；--shm 改为
# ShmSDK 相机模板。--deb 同时生成内置 MediaMTX 与 VAAPI GStreamer runtime、
# 普通账户视频启动器的完整首次安装 DEB。
# 用法：./make_upgrade.sh <版本号> [--shm] [--deb]
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SETUP="$ROOT/install/setup.bash"
if [[ $# -lt 1 || $# -gt 3 ]]; then
  echo "用法：./make_upgrade.sh <版本号> [--shm] [--deb]" >&2
  exit 2
fi
VERSION="$1"
shift
BUILD_DEB=false
VIDEO_PROFILE="ros"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --shm)
      [[ "$VIDEO_PROFILE" == "ros" ]] || { echo "--shm 不能重复指定。" >&2; exit 2; }
      VIDEO_PROFILE="shm"
      ;;
    --deb)
      [[ "$BUILD_DEB" == false ]] || { echo "--deb 不能重复指定。" >&2; exit 2; }
      BUILD_DEB=true
      ;;
    *)
      echo "未知参数：$1（仅支持 --shm、--deb）。" >&2
      exit 2
      ;;
  esac
  shift
done
VIDEO_TEMPLATE="$ROOT/config/video.$VIDEO_PROFILE.json"

if [[ ! -f "$SETUP" ]]; then
  echo "未找到工程内 install/setup.bash。请先在小车执行 export_robot_build_deps.sh，并将生成的依赖包解压到本工程根目录。" >&2
  exit 1
fi
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "未找到前端依赖。请首次在开发机执行：cd frontend && npm install" >&2
  exit 1
fi
if [[ ! "$VERSION" =~ ^[0-9]+(\.[0-9]+)+$ ]]; then
  echo "版本号不合法，请使用数字点号格式，例如 0.1、0.2、1.1。" >&2
  exit 2
fi
if [[ ! -f "$VIDEO_TEMPLATE" ]]; then
  echo "未找到视频构建模板：$VIDEO_TEMPLATE" >&2
  exit 1
fi
RELEASE_DIR="$ROOT/releases/$VERSION-$VIDEO_PROFILE"
if [[ -e "$RELEASE_DIR" ]]; then
  echo "发布目录已存在，拒绝覆盖：$RELEASE_DIR" >&2
  echo "请使用新的版本号，或在确认不再需要旧产物后手动处理该目录。" >&2
  exit 1
fi
TOTAL_STEPS=3
"$BUILD_DEB" && TOTAL_STEPS=4
echo "[1/$TOTAL_STEPS] 正在使用工程内小车依赖构建二进制（视频输入：$VIDEO_PROFILE）..."
RY_ALETHEIA_VIDEO_CONFIG="$VIDEO_TEMPLATE" ROVER_QA_ROS_SETUP="$SETUP" "$ROOT/build_binary.sh"
echo "[2/$TOTAL_STEPS] 正在生成网页离线升级包，版本：$VERSION，视频输入：$VIDEO_PROFILE"
mkdir -p "$RELEASE_DIR"
"$ROOT/build_upgrade_package.sh" "$VERSION" "$RELEASE_DIR"
BASE_ZIP_FILE="$RELEASE_DIR/ry-aletheia_${VERSION}.zip"
ZIP_FILE="$RELEASE_DIR/ry-aletheia_${VERSION}_${VIDEO_PROFILE}.zip"
mv "$BASE_ZIP_FILE" "$ZIP_FILE"
if "$BUILD_DEB"; then
  echo "[3/$TOTAL_STEPS] 正在生成首次安装 DEB..."
  RY_ALETHEIA_VIDEO_CONFIG="$VIDEO_TEMPLATE" "$ROOT/build_deb_package.sh" "$VERSION" --output-dir "$RELEASE_DIR"
  BASE_DEB_FILE="$RELEASE_DIR/ry-aletheia_${VERSION}_$(dpkg --print-architecture).deb"
  DEB_FILE="$RELEASE_DIR/ry-aletheia_${VERSION}_${VIDEO_PROFILE}_$(dpkg --print-architecture).deb"
  mv "$BASE_DEB_FILE" "$DEB_FILE"
fi
echo "[$TOTAL_STEPS/$TOTAL_STEPS] 正在生成发布校验..."
(
  cd "$RELEASE_DIR"
  sha256sum "$(basename "$ZIP_FILE")" > SHA256SUMS
)
if "$BUILD_DEB"; then
  (
    cd "$RELEASE_DIR"
    sha256sum "$(basename "$DEB_FILE")" >> SHA256SUMS
  )
fi
echo "完成：$RELEASE_DIR"
echo "升级包：$ZIP_FILE"
if "$BUILD_DEB"; then
  echo "首次安装包：$DEB_FILE"
else
  if [[ "$VIDEO_PROFILE" == "shm" ]]; then
    echo "如需同时生成完整首次安装包，请执行：./make_upgrade.sh $VERSION --shm --deb"
  else
    echo "如需同时生成完整首次安装包，请执行：./make_upgrade.sh $VERSION --deb"
  fi
fi
