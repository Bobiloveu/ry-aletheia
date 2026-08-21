#!/usr/bin/env bash
set -euo pipefail

# 开发机一键生成网页离线升级 ZIP；可同时生成普通或内置私有 Bridge 的首次安装 DEB。
# 用法：./make_upgrade.sh <版本号> [--deb | --full-deb <官方 bridge .deb>]
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SETUP="$ROOT/install/setup.bash"
if [[ $# -ne 1 && $# -ne 2 && $# -ne 3 ]]; then
  echo "用法：./make_upgrade.sh <版本号> [--deb | --full-deb <官方 bridge .deb>]" >&2
  exit 2
fi
VERSION="$1"
BUILD_DEB=false
FULL_BRIDGE_DEB=""
case "$#" in
  1) ;;
  2)
    [[ "$2" == "--deb" ]] || { echo "未知参数：$2（仅支持 --deb 或 --full-deb）。" >&2; exit 2; }
    BUILD_DEB=true
    ;;
  3)
    [[ "$2" == "--full-deb" ]] || { echo "未知参数：$2（仅支持 --full-deb <Bridge DEB>）。" >&2; exit 2; }
    FULL_BRIDGE_DEB="$(realpath "$3")"
    [[ -f "$FULL_BRIDGE_DEB" ]] || { echo "未找到 Foxglove Bridge DEB：$FULL_BRIDGE_DEB" >&2; exit 1; }
    BUILD_DEB=true
    ;;
esac

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
RELEASE_DIR="$ROOT/releases/$VERSION"
if [[ -e "$RELEASE_DIR" ]]; then
  echo "发布目录已存在，拒绝覆盖：$RELEASE_DIR" >&2
  echo "请使用新的版本号，或在确认不再需要旧产物后手动处理该目录。" >&2
  exit 1
fi

TOTAL_STEPS=3
"$BUILD_DEB" && TOTAL_STEPS=4
echo "[1/$TOTAL_STEPS] 正在使用工程内小车依赖构建二进制..."
ROVER_QA_ROS_SETUP="$SETUP" "$ROOT/build_binary.sh"
echo "[2/$TOTAL_STEPS] 正在生成网页离线升级包，版本：$VERSION"
mkdir -p "$RELEASE_DIR"
"$ROOT/build_upgrade_package.sh" "$VERSION" "$RELEASE_DIR"
ZIP_FILE="$RELEASE_DIR/ry-aletheia_${VERSION}.zip"
if "$BUILD_DEB"; then
  echo "[3/$TOTAL_STEPS] 正在生成首次安装 DEB..."
  if [[ -n "$FULL_BRIDGE_DEB" ]]; then
    "$ROOT/build_deb_package.sh" "$VERSION" --output-dir "$RELEASE_DIR" --with-foxglove-bridge "$FULL_BRIDGE_DEB"
  else
    "$ROOT/build_deb_package.sh" "$VERSION" --output-dir "$RELEASE_DIR"
  fi
fi
echo "[$TOTAL_STEPS/$TOTAL_STEPS] 正在生成发布校验..."
(
  cd "$RELEASE_DIR"
  sha256sum "$(basename "$ZIP_FILE")" > SHA256SUMS
)
if "$BUILD_DEB"; then
  DEB_FILE="$RELEASE_DIR/ry-aletheia_${VERSION}_$(dpkg --print-architecture).deb"
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
  echo "如需生成内置私有 Bridge 的完整首次安装包，请执行：./make_upgrade.sh $VERSION --full-deb <Foxglove Bridge DEB>"
fi
