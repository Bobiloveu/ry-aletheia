#!/usr/bin/env bash
set -euo pipefail

# 生成首次离线部署用的 Debian 安装包。包内不包含源码、ROS install 或构建工具。
# 用法：./build_deb_package.sh <版本号> [--output-dir <目录>] [--with-foxglove-bridge <官方 bridge .deb>]
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [[ $# -lt 1 ]]; then
  echo "用法：./build_deb_package.sh <版本号> [--output-dir <目录>] [--with-foxglove-bridge <官方 bridge .deb>]" >&2
  exit 2
fi
VERSION="$1"
shift
BRIDGE_DEB=""
OUTPUT_DIR="$ROOT/releases"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      [[ $# -ge 2 ]] || { echo "--output-dir 缺少目录参数。" >&2; exit 2; }
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --with-foxglove-bridge)
      [[ $# -ge 2 ]] || { echo "--with-foxglove-bridge 缺少 DEB 路径。" >&2; exit 2; }
      BRIDGE_DEB="$(realpath "$2")"
      [[ -f "$BRIDGE_DEB" ]] || { echo "未找到 Foxglove Bridge DEB：$BRIDGE_DEB" >&2; exit 1; }
      [[ "$(dpkg-deb -f "$BRIDGE_DEB" Package)" == "ros-humble-foxglove-bridge" ]] || {
        echo "提供的文件不是 ros-humble-foxglove-bridge DEB。" >&2
        exit 1
      }
      shift 2
      ;;
    *)
      echo "未知参数：$1" >&2
      exit 2
      ;;
  esac
done
if [[ ! "$VERSION" =~ ^[0-9]+(\.[0-9]+)+$ ]]; then
  echo "版本号不合法，请使用 0.1、0.2、1.1 这类数字点号格式。" >&2
  exit 2
fi
if [[ ! -x "$ROOT/dist/ry-aletheia" ]]; then
  echo "未找到可执行文件 dist/ry-aletheia，请先执行 ./make_upgrade.sh $VERSION。" >&2
  exit 1
fi
if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "开发机未找到 dpkg-deb，无法生成 Debian 安装包。" >&2
  exit 1
fi

ARCH="${RY_ALETHEIA_DEB_ARCH:-$(dpkg --print-architecture)}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
PKG="$STAGE/ry-aletheia"
OUT="$OUTPUT_DIR/ry-aletheia_${VERSION}_${ARCH}.deb"
mkdir -p "$PKG/DEBIAN" "$PKG/usr/lib/ry-aletheia/defaults/tasks" "$PKG/usr/lib/ry-aletheia/defaults/config" "$PKG/usr/lib/ry-aletheia" "$PKG/usr/bin" "$PKG/usr/share/doc/ry-aletheia/docs/images"

echo "正在组装锁定的私有视频运行时（开发机下载，目标小车无需 apt）..."
VIDEO_RUNTIME="$STAGE/video-runtime"
RY_ALETHEIA_VIDEO_ARCH="$ARCH" "$ROOT/build_video_runtime.sh" --output-dir "$VIDEO_RUNTIME"

if [[ -n "$BRIDGE_DEB" ]]; then
  # 只提取官方 Bridge 的 ROS 前缀，并安装到 Aletheia 私有目录。绝不写入
  # /opt/ros，也不通过 Conflicts/Replaces 接管系统 ros-humble-foxglove-bridge。
  BRIDGE_STAGE="$STAGE/foxglove-bridge"
  [[ "$(dpkg-deb -f "$BRIDGE_DEB" Architecture)" == "$ARCH" ]] || {
    echo "Foxglove Bridge 架构必须与目标 DEB 一致：期望 $ARCH。" >&2
    exit 1
  }
  PRIVATE_RUNTIME="$PKG/usr/lib/ry-aletheia/foxglove_bridge_runtime"
  dpkg-deb -x "$BRIDGE_DEB" "$BRIDGE_STAGE"
  mkdir -p "$PRIVATE_RUNTIME"
  cp -a "$BRIDGE_STAGE/opt/ros/humble/." "$PRIVATE_RUNTIME/"
  FOXGLOVE_CONTROL=''
  DESCRIPTION="Offline package with a private Foxglove Bridge runtime."
else
  FOXGLOVE_CONTROL='Depends: ros-humble-foxglove-bridge'
  DESCRIPTION="Offline first-install package for the RY Aletheia robot QA console."
fi

{
  printf '%s\n' \
    'Package: ry-aletheia' \
    "Version: $VERSION" \
    'Section: utils' \
    'Priority: optional' \
    "Architecture: $ARCH" \
    'Maintainer: RY Robotics'
  if [[ -n "$FOXGLOVE_CONTROL" ]]; then
    printf '%s\n' "$FOXGLOVE_CONTROL"
  fi
  printf '%s\n' \
    'Description: RY Aletheia automated testing console' \
    " $DESCRIPTION"
} > "$PKG/DEBIAN/control"

# Debian 包内先保留根账户只读的母本；安装后脚本会复制到自动识别的普通账户目录。
install -m 0755 "$ROOT/dist/ry-aletheia" "$PKG/usr/lib/ry-aletheia/ry-aletheia"
install -m 0755 "$ROOT/packaging/debian/postinst" "$PKG/DEBIAN/postinst"
install -m 0755 "$ROOT/packaging/debian/prerm" "$PKG/DEBIAN/prerm"
install -m 0755 "$ROOT/packaging/debian/postrm" "$PKG/DEBIAN/postrm"
install -m 0755 "$ROOT/packaging/debian/ry-aletheia-launcher" "$PKG/usr/bin/ry-aletheia"
install -m 0755 "$ROOT/packaging/debian/ry-aletheia-video-launcher" "$PKG/usr/bin/ry-aletheia-video"
install -m 0755 "$ROOT/packaging/debian/ry-aletheia-status" "$PKG/usr/bin/ry-aletheia-status"
# 运行目录根部保留面向使用者的入口文档；不再依赖已废弃的手工部署说明。
install -m 0644 "$ROOT/USER_GUIDE.md" "$PKG/usr/lib/ry-aletheia/README.md"
install -m 0644 "$ROOT/USER_GUIDE.md" "$PKG/usr/share/doc/ry-aletheia/USER_GUIDE.md"
install -m 0644 "$ROOT/PROJECT_OVERVIEW.md" "$PKG/usr/share/doc/ry-aletheia/PROJECT_OVERVIEW.md"
install -m 0644 "$ROOT/config/video.json" "$PKG/usr/lib/ry-aletheia/defaults/config/video.json"
cp -a "$VIDEO_RUNTIME" "$PKG/usr/lib/ry-aletheia/video_runtime"
if [[ -d "$ROOT/docs/images" ]]; then
  while IFS= read -r -d '' guide_image; do
    install -m 0644 "$guide_image" "$PKG/usr/share/doc/ry-aletheia/docs/images/$(basename -- "$guide_image")"
  done < <(find "$ROOT/docs/images" -maxdepth 1 -type f -name '*.png' -print0)
fi
printf '%s\n' "$VERSION" > "$PKG/usr/lib/ry-aletheia/VERSION"

while IFS= read -r -d '' task; do
  install -m 0644 "$task" "$PKG/usr/lib/ry-aletheia/defaults/tasks/$(basename -- "$task")"
done < <(find "$ROOT/tasks" -maxdepth 1 -type f -name '*.json' -print0)

mkdir -p "$(dirname -- "$OUT")"
rm -f "$OUT"
dpkg-deb --root-owner-group --build "$PKG" "$OUT" >/dev/null
echo "首次离线安装包已生成：$OUT"
echo "复制到小车后双击安装，或执行：sudo dpkg -i ./$([[ "$OUT" == */* ]] && basename "$OUT" || echo "$OUT")"
