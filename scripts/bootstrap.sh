#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
target="${1:-help}"

usage() {
  cat <<'EOF'
Usage: ./scripts/bootstrap.sh [backend|web|mobile|all]
  backend  install the Pixi environment
  web      install locked frontend dependencies
  mobile   install the FVM-pinned Flutter SDK and packages
  all      initialize each available domain; missing optional tools are warnings
EOF
}

bootstrap_backend() {
  (cd "$ROOT" && pixi install)
}

bootstrap_web() {
  (cd "$ROOT" && pixi run frontend-install)
}

bootstrap_mobile() {
  local fvm_bin=""
  if command -v fvm >/dev/null 2>&1; then
    fvm_bin="$(command -v fvm)"
  elif [[ -x "$HOME/.pub-cache/bin/fvm" ]]; then
    fvm_bin="$HOME/.pub-cache/bin/fvm"
  fi
  if [[ -z "$fvm_bin" ]]; then
    echo "[WARN] FVM missing; install with: dart pub global activate fvm 4.3.0" >&2
    return 0
  fi
  export PATH="$(dirname "$fvm_bin"):$PATH"
  (cd "$ROOT/mobile" && fvm install && fvm flutter pub get)
}

case "$target" in
  backend) bootstrap_backend ;;
  web) bootstrap_web ;;
  mobile) bootstrap_mobile ;;
  all) bootstrap_backend; bootstrap_web; bootstrap_mobile ;;
  help|-h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
