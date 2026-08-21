#!/usr/bin/env bash
set -euo pipefail

# 构建面向无网络机器人交付的单一完整 Aletheia DEB（内置 Foxglove Bridge）。
# 用法：./build_offline_foxglove_bundle.sh <版本号> [官方 bridge .deb]
# 若省略第二个参数，开发机会从 ROS 官方仓库下载已锁定版本。
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "用法：./build_offline_foxglove_bundle.sh <版本号> [ros-humble-foxglove-bridge_*.deb]" >&2
  exit 2
fi
VERSION="$1"
BRIDGE_VERSION="3.4.3-2jammy.20260726.140144"
BRIDGE_NAME="ros-humble-foxglove-bridge_${BRIDGE_VERSION}_amd64.deb"
BRIDGE_URL="http://packages.ros.org/ros2/ubuntu/pool/main/r/ros-humble-foxglove-bridge/${BRIDGE_NAME}"
BRIDGE_SHA256="00d1c9c09102b545b0ba633f26167020f33b2ea98a0f62ef46b512d29bef3b5f"

if [[ $# -eq 2 ]]; then
  BRIDGE_SOURCE="$(realpath "$2")"
  [[ -f "$BRIDGE_SOURCE" ]] || { echo "未找到 Bridge DEB：$BRIDGE_SOURCE" >&2; exit 1; }
else
  CACHE_DIR="$ROOT/.cache/offline-deps"
  BRIDGE_SOURCE="$CACHE_DIR/$BRIDGE_NAME"
  mkdir -p "$CACHE_DIR"
  if [[ ! -f "$BRIDGE_SOURCE" ]]; then
    echo "下载官方 Foxglove Bridge：$BRIDGE_VERSION"
    curl -fL --connect-timeout 15 --retry 2 -o "$BRIDGE_SOURCE.part" "$BRIDGE_URL"
    mv "$BRIDGE_SOURCE.part" "$BRIDGE_SOURCE"
  fi
  echo "$BRIDGE_SHA256  $BRIDGE_SOURCE" | sha256sum -c -
fi

PACKAGE_NAME="$(dpkg-deb -f "$BRIDGE_SOURCE" Package)"
PACKAGE_ARCH="$(dpkg-deb -f "$BRIDGE_SOURCE" Architecture)"
[[ "$PACKAGE_NAME" == "ros-humble-foxglove-bridge" && "$PACKAGE_ARCH" == "amd64" ]] || {
  echo "提供的文件不是 amd64 版 ros-humble-foxglove-bridge。" >&2
  exit 1
}

"$ROOT/build_deb_package.sh" "$VERSION" --with-foxglove-bridge "$BRIDGE_SOURCE"
ARCH="${RY_ALETHEIA_DEB_ARCH:-$(dpkg --print-architecture)}"
ALETHEIA_DEB="$ROOT/releases/ry-aletheia_${VERSION}_${ARCH}.deb"
[[ -f "$ALETHEIA_DEB" ]] || { echo "未生成 Aletheia DEB。" >&2; exit 1; }

OUT="$ROOT/releases/$VERSION-offline"
if [[ -e "$OUT" ]]; then
  echo "离线安装目录已存在，拒绝覆盖：$OUT" >&2
  exit 1
fi
mkdir -p "$OUT"
install -m 0644 "$ALETHEIA_DEB" "$OUT/$(basename "$ALETHEIA_DEB")"
cat > "$OUT/README.md" <<EOF
# RY Aletheia $VERSION 离线安装包

本目录的 Aletheia DEB 已内置 Foxglove Bridge。首次部署机器人在离线状态下只需执行：

\`\`\`bash
cd "$(basename "$OUT")"
sudo dpkg -i ./$(basename "$ALETHEIA_DEB")
\`\`\`

安装过程会将 Bridge 放入 Aletheia 私有运行目录，不会替换、删除或影响系统已有的 \`ros-humble-foxglove-bridge\`。推荐使用 \`dpkg -i\`，避免系统中与本工具无关的 APT 未完成依赖阻塞安装；不要执行 \`apt autoremove\`。无需额外执行 \`install.sh\` 或输入 ROS 命令。该完整包要求目标小车已具备 ROS Humble 基础运行环境；安装完成后，以普通账户执行 \`ry-aletheia\` 启动工具。
EOF
sha256sum "$OUT"/*.deb > "$OUT/SHA256SUMS"
echo "Foxglove 离线安装目录已生成：$OUT"
