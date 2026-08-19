#!/usr/bin/env bash
set -euo pipefail

# 在小车上运行一次，将真实 ROS 业务工作空间导出为开发机构建依赖包。
# 不下载、不安装、不修改 /opt/ry/install；仅读取并生成一个 tar.gz 文件。
SOURCE_ROOT="${ROVER_QA_ROBOT_ROOT:-/opt/ry}"
INSTALL_DIR="$SOURCE_ROOT/install"
PROJECT_NAME="ry-aletheia"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT="${1:-$PWD/${PROJECT_NAME}-robot-build-deps_${STAMP}.tar.gz}"

if [[ ! -f "$INSTALL_DIR/setup.bash" ]]; then
  echo "未找到 $INSTALL_DIR/setup.bash，请在机器人小车上执行。" >&2
  exit 1
fi
if [[ -e "$OUTPUT" ]]; then
  echo "输出文件已存在，拒绝覆盖：$OUTPUT" >&2
  exit 1
fi
if ! command -v tar >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1 || ! command -v sha256sum >/dev/null 2>&1; then
  echo "缺少 tar、python3 或 sha256sum，无法导出依赖包。" >&2
  exit 1
fi

OUTPUT_DIR="$(CDPATH= cd -- "$(dirname -- "$OUTPUT")" && pwd)"
OUTPUT="$OUTPUT_DIR/$(basename -- "$OUTPUT")"
METADATA_DIR="$(mktemp -d)"
METADATA_FILE="$METADATA_DIR/build-deps-manifest.json"
trap 'rm -rf "$METADATA_DIR"' EXIT

set +u
source "$INSTALL_DIR/setup.bash"
set -u
python3 - "$METADATA_FILE" "$INSTALL_DIR" <<'PY'
from __future__ import annotations

import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

target = Path(sys.argv[1])
install = Path(sys.argv[2])
master = install / "master_interfaces"
payload = {
    "schema": "ry-aletheia-robot-build-deps/v1",
    "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "source_install": str(install),
    "hostname": platform.node(),
    "machine": platform.machine(),
    "system": platform.platform(),
    "python": sys.version.split()[0],
    "ros_distro": os.environ.get("ROS_DISTRO", ""),
    "ament_prefix_path": os.environ.get("AMENT_PREFIX_PATH", ""),
    "master_interfaces_present": master.is_dir(),
    "master_typesupport_libraries": sorted(item.name for item in (master / "lib").glob("libmaster_interfaces__rosidl_*.so")),
}
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

if ! python3 - "$METADATA_FILE" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
if not data["master_interfaces_present"] or not data["master_typesupport_libraries"]:
    raise SystemExit("依赖导出失败：install 中缺少 master_interfaces 或 ROS 类型支持库。")
PY
then
  exit 1
fi

echo "正在导出 $INSTALL_DIR（保留符号链接和权限元数据，可能需要数分钟）..."
tar --create --gzip --file "$OUTPUT" --numeric-owner \
  --directory "$SOURCE_ROOT" install \
  --directory "$METADATA_DIR" build-deps-manifest.json

echo "依赖包已生成：$OUTPUT"
echo "大小：$(du -h "$OUTPUT" | awk '{print $1}')"
echo "SHA256：$(sha256sum "$OUTPUT" | awk '{print $1}')"
echo "请将此文件复制回开发机，在 ry_aletheia 工程根目录解压。"
