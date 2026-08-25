#!/usr/bin/env bash
set -euo pipefail

# 兼容旧的发布入口：专用实时遥测已不再需要额外的 ROS-Web 运行时。
# 用法：./build_offline_foxglove_bundle.sh <版本号>
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [[ $# -ne 1 ]]; then
  echo "用法：./build_offline_foxglove_bundle.sh <版本号>" >&2
  exit 2
fi
VERSION="$1"

ARCH="${RY_ALETHEIA_DEB_ARCH:-$(dpkg --print-architecture)}"
OUT="$ROOT/releases/$VERSION-offline"
if [[ -e "$OUT" ]]; then
  echo "离线安装目录已存在，拒绝覆盖：$OUT" >&2
  exit 1
fi
mkdir -p "$OUT"
"$ROOT/build_deb_package.sh" "$VERSION" --output-dir "$OUT"
ALETHEIA_DEB="$OUT/ry-aletheia_${VERSION}_${ARCH}.deb"
[[ -f "$ALETHEIA_DEB" ]] || { echo "未生成 Aletheia DEB。" >&2; exit 1; }
(
  cd "$OUT"
  sha256sum ./*.deb > SHA256SUMS
)
echo "离线安装目录已生成：$OUT"
