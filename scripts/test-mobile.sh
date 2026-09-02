#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
fvm_bin=""
if command -v fvm >/dev/null 2>&1; then
  fvm_bin="$(command -v fvm)"
elif [[ -x "$HOME/.pub-cache/bin/fvm" ]]; then
  fvm_bin="$HOME/.pub-cache/bin/fvm"
fi
if [[ -z "$fvm_bin" ]]; then
  echo "[FAIL] FVM is required for mobile work: dart pub global activate fvm 4.3.0" >&2
  exit 2
fi
export PATH="$(dirname "$fvm_bin"):$PATH"
# Flutter tester talks to a loopback compiler service; never proxy that link.
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost,::1"
export no_proxy="$NO_PROXY"
cd "$ROOT/mobile"
fvm flutter analyze
fvm flutter test
