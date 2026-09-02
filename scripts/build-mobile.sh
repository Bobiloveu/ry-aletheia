#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if ! command -v fvm >/dev/null 2>&1; then
  echo "[FAIL] FVM is required for mobile builds: dart pub global activate fvm 4.3.0" >&2
  exit 2
fi
cd "$ROOT/mobile"
ALETHEIA_USE_FVM=1 ./tool/build_mobile_packages.sh --engine flutter "$@"

