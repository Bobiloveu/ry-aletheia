#!/usr/bin/env bash
set -euo pipefail

# 开发机生成首次放入小车的纯运行目录，不包含源码、install 或构建工具。
# 用法：./prepare_robot_deploy.sh <版本号>
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [[ $# -ne 1 ]]; then
  echo "用法：./prepare_robot_deploy.sh <版本号>，例如：./prepare_robot_deploy.sh 0.1" >&2
  exit 2
fi
VERSION="$1"
if [[ ! "$VERSION" =~ ^[0-9]+(\.[0-9]+)+$ ]]; then
  echo "版本号不合法，请使用数字点号格式，例如 0.1、0.2、1.1。" >&2
  exit 2
fi
if [[ ! -f "$ROOT/dist/ry-aletheia" ]]; then
  echo "未找到 dist/ry-aletheia，请先执行 ./make_upgrade.sh $VERSION。" >&2
  exit 1
fi

TARGET="$ROOT/deployments/ry-aletheia-$VERSION"
if [[ -e "$TARGET" ]]; then
  echo "部署目录已存在，拒绝覆盖：$TARGET" >&2
  exit 1
fi

mkdir -p "$TARGET/dist" "$TARGET/tasks" "$TARGET/config" "$TARGET/reports"
cp -a "$ROOT/dist/ry-aletheia" "$TARGET/dist/ry-aletheia"
cp -a "$ROOT/robot_setup.sh" "$TARGET/robot_setup.sh"
cp -a "$ROOT/deployment/README.md" "$TARGET/README.md"
cp -a "$ROOT/tasks/README.md" "$TARGET/tasks/README.md"
cp -a "$ROOT/config/README.md" "$TARGET/config/README.md"
cp -a "$ROOT/reports/README.md" "$TARGET/reports/README.md"
find "$ROOT/tasks" -maxdepth 1 -type f -name '*.json' -exec cp -a {} "$TARGET/tasks/" \;
sha256sum "$TARGET/dist/ry-aletheia" > "$TARGET/BINARY_SHA256.txt"
printf '%s\n' "$VERSION" > "$TARGET/VERSION"

echo "首次部署目录已生成：$TARGET"
echo "将整个目录复制到小车普通账户目录后，按 $TARGET/README.md 执行首次权限配置。"
