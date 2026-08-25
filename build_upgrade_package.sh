#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [[ $# -ne 1 && $# -ne 2 ]]; then
  echo "用法：./build_upgrade_package.sh <版本号> [输出目录]" >&2
  exit 2
fi
OUTPUT_DIR="${2:-$ROOT/releases}"
SIGNING_KEY="${RY_ALETHEIA_UPGRADE_SIGNING_KEY:-$ROOT/.ry-aletheia-signing/upgrade-ed25519.pem}"
if [[ ! -r "$SIGNING_KEY" ]]; then
  echo "未找到 Ed25519 发布签名密钥：$SIGNING_KEY" >&2
  echo "请设置 RY_ALETHEIA_UPGRADE_SIGNING_KEY 指向受保护的发布私钥。" >&2
  exit 1
fi
python3 "$ROOT/tools/build_upgrade_package.py" "$1" --binary "$ROOT/dist/ry-aletheia" --output-dir "$OUTPUT_DIR" --signing-key "$SIGNING_KEY"
