#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [[ $# -ne 1 && $# -ne 2 ]]; then
  echo "用法：./build_upgrade_package.sh <版本号> [输出目录]" >&2
  exit 2
fi
OUTPUT_DIR="${2:-$ROOT/releases}"
python3 "$ROOT/tools/build_upgrade_package.py" "$1" --binary "$ROOT/dist/ry-aletheia" --output-dir "$OUTPUT_DIR"
