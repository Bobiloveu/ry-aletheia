#!/usr/bin/env bash
set -euo pipefail

# 生成首次离线部署用的 Debian 安装包。包内不包含源码、ROS install 或构建工具。
# 用法：./build_deb_package.sh <版本号> [--output-dir <目录>]
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [[ $# -lt 1 ]]; then
  echo "用法：./build_deb_package.sh <版本号> [--output-dir <目录>]" >&2
  exit 2
fi
VERSION="$1"
shift
OUTPUT_DIR="$ROOT/releases"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      [[ $# -ge 2 ]] || { echo "--output-dir 缺少目录参数。" >&2; exit 2; }
      OUTPUT_DIR="$2"
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

DESCRIPTION="Offline first-install package for the RY Aletheia robot QA console."

{
  printf '%s\n' \
    'Package: ry-aletheia' \
    "Version: $VERSION" \
    'Section: utils' \
    'Priority: optional' \
    "Architecture: $ARCH" \
    'Maintainer: RY Robotics'
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
