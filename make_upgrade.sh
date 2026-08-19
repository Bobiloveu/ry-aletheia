#!/usr/bin/env bash
set -euo pipefail

# 开发机一键生成网页离线升级 ZIP；传 --deb 时额外生成首次部署 Debian 包。
# 用法：./make_upgrade.sh <版本号> [--deb]
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SETUP="$ROOT/install/setup.bash"
if [[ $# -ne 1 && $# -ne 2 ]]; then
  echo "用法：./make_upgrade.sh <版本号> [--deb]，例如：./make_upgrade.sh 0.1 --deb" >&2
  exit 2
fi
VERSION="$1"
BUILD_DEB=false
if [[ $# -eq 2 ]]; then
  [[ "$2" == "--deb" ]] || { echo "未知参数：$2（仅支持 --deb）" >&2; exit 2; }
  BUILD_DEB=true
fi

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
  "$ROOT/build_deb_package.sh" "$VERSION" --output-dir "$RELEASE_DIR"
fi
echo "[$TOTAL_STEPS/$TOTAL_STEPS] 正在生成发布校验与使用说明..."
sha256sum "$ZIP_FILE" > "$RELEASE_DIR/SHA256SUMS"
ZIP_MD5="$(md5sum "$ZIP_FILE" | awk '{print $1}')"
DEB_ROW=""
if "$BUILD_DEB"; then
  DEB_FILE="$RELEASE_DIR/ry-aletheia_${VERSION}_$(dpkg --print-architecture).deb"
  sha256sum "$DEB_FILE" >> "$RELEASE_DIR/SHA256SUMS"
  DEB_ROW="| \`$(basename "$DEB_FILE")\` | 首次安装或完整重装时使用的 Debian 安装包。 |"
fi
cat > "$RELEASE_DIR/README.md" <<EOF
# RY Aletheia $VERSION 升级包

本目录为本次网页离线升级交付物。

| 文件 | 用途 |
| --- | --- |
| \`ry-aletheia_${VERSION}.zip\` | 已安装 Aletheia 后，在网页“运行配置 → 工具离线升级”中上传的升级包。 |
$DEB_ROW
| \`SHA256SUMS\` | 升级 ZIP 的 SHA-256 校验值。 |

## 使用方法

1. 电脑连接小车 Wi-Fi，打开 \`http://<小车IP>:8087\`。
2. 进入“运行配置”。
3. 在“工具离线升级”拖入 \`ry-aletheia_${VERSION}.zip\`。
4. 点击“校验并应用升级”，等待工具自动重启后刷新网页。

升级不会覆盖任务文件、用例别名、运行配置、地图缓存或历史报告。

## 校验信息

- 版本：\`$VERSION\`
- ZIP 文件 MD5：\`$ZIP_MD5\`
- SHA-256：见 \`SHA256SUMS\`
EOF
echo "完成：$RELEASE_DIR"
echo "升级包：$ZIP_FILE"
if "$BUILD_DEB"; then
  echo "首次安装包：$DEB_FILE"
else
  echo "如需同时生成首次安装 DEB，请执行：./make_upgrade.sh $VERSION --deb"
fi
