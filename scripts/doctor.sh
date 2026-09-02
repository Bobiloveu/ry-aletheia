#!/usr/bin/env bash
# Check only the toolchain required by a selected development profile.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
profile="full"
failures=0

usage() {
  cat <<'EOF'
Usage: ./scripts/doctor.sh [--profile PROFILE]

Profiles:
  backend          Pixi-based Python/robot backend work
  web              Pixi-based Web Console work
  mobile-android   Flutter/Dart and Android work on macOS, Linux, or Windows Bash
  mobile-ios       Flutter/Dart and iOS work (macOS only)
  full             All supported profiles on this host (default)

Compatibility aliases: mobile -> mobile-android, all -> full.
EOF
}

ok() { printf '[OK] %s\n' "$1"; }
missing() { printf '[MISSING] %s\n' "$1"; failures=1; }
optional() { printf '[OPTIONAL] %s\n' "$1"; }
unsupported() { printf '[UNSUPPORTED] %s\n' "$1"; }
has() { command -v "$1" >/dev/null 2>&1; }

needs() {
  local domain="$1"
  [[ "$profile" == "full" || "$profile" == "$domain" ]]
}

optional_domain() {
  printf '%s (not required by profile %s)' "$1" "$profile"
}

check_command() {
  local command="$1"
  local label="$2"
  local required="$3"
  if has "$command"; then
    ok "$label"
  elif [[ "$required" == "required" ]]; then
    missing "$label"
  else
    optional "$label"
  fi
}

check_pixi() {
  if has pixi; then
    ok "Pixi $(pixi --version)"
  else
    missing "Pixi; install Pixi before Backend/Web work"
  fi
}

fvm_bin=""
find_fvm() {
  if has fvm; then
    fvm_bin="$(command -v fvm)"
  elif [[ -x "$HOME/.pub-cache/bin/fvm" ]]; then
    # Dart global executables are commonly absent from non-interactive PATH.
    fvm_bin="$HOME/.pub-cache/bin/fvm"
  fi
}

check_mobile_common() {
  find_fvm
  if [[ -n "$fvm_bin" ]]; then
    ok "FVM $($fvm_bin --version)"
  else
    missing "FVM; install with: dart pub global activate fvm 4.3.0"
  fi
  if has dart; then
    ok "Dart $(dart --version 2>&1 | head -n 1)"
  else
    missing "Dart SDK; required to install and run FVM"
  fi
  if [[ -x "$ROOT/mobile/.fvm/flutter_sdk/bin/flutter" ]]; then
    ok "FVM-pinned Flutter SDK installed"
  else
    optional "FVM-pinned Flutter SDK not installed yet; run ./scripts/bootstrap.sh mobile-android"
  fi
  if has flutter; then
    optional "Bare Flutter detected; use fvm flutter for this repository"
  fi
}

java_major() {
  java -version 2>&1 | sed -n '1s/.*version "\([0-9][0-9]*\).*/\1/p'
}

android_sdk_path() {
  if [[ -n "${ANDROID_SDK_ROOT:-}" ]]; then
    printf '%s' "$ANDROID_SDK_ROOT"
  elif [[ -n "${ANDROID_HOME:-}" ]]; then
    printf '%s' "$ANDROID_HOME"
  elif [[ -d "$HOME/Library/Android/sdk" ]]; then
    printf '%s' "$HOME/Library/Android/sdk"
  elif [[ -d "$HOME/Android/Sdk" ]]; then
    printf '%s' "$HOME/Android/Sdk"
  fi
}

check_android() {
  if has java; then
    local major
    major="$(java_major)"
    if [[ -n "$major" && "$major" -ge 17 ]]; then
      ok "JDK $major (CI baseline and project JVM target: 17)"
    else
      missing "JDK 17 or newer; current Android build requires JVM 17 compatibility"
    fi
  else
    missing "JDK 17 or newer; required for Android builds"
  fi

  local sdk
  sdk="$(android_sdk_path)"
  if [[ -n "$sdk" ]]; then
    ok "Android SDK $sdk"
  else
    missing "Android SDK; set ANDROID_SDK_ROOT or install Android Studio"
  fi
  if has adb; then
    ok "adb available"
  else
    optional "adb; required only for physical-device debugging"
  fi
}

check_ios() {
  local host_os="$1"
  if [[ "$host_os" != "Darwin" ]]; then
    unsupported "iOS toolchain; iOS builds require macOS with Xcode"
    return
  fi
  if has xcodebuild; then
    ok "$(xcodebuild -version | tr '\n' ' ')"
  else
    missing "Xcode; required for iOS Simulator/device builds"
  fi
  if has pod; then
    ok "CocoaPods $(pod --version)"
  else
    missing "CocoaPods; required by the current iOS plugin dependencies"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--profile)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      profile="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

case "$profile" in
  mobile) profile="mobile-android" ;;
  all) profile="full" ;;
  backend|web|mobile-android|mobile-ios|full) ;;
  *) usage >&2; exit 2 ;;
esac

host_os="$(uname -s)"
printf 'RY Aletheia doctor: profile=%s os=%s\n' "$profile" "$host_os"

if needs backend || needs web; then
  check_pixi
else
  optional "$(optional_domain "Pixi")"
fi

if needs backend; then
  check_command python3 "Host Python (optional; Pixi provides the project interpreter)" optional
fi

if needs web; then
  check_command node "Host Node (optional; Pixi provides Node 20)" optional
  check_command npm "Host npm (optional; Pixi provides npm)" optional
elif [[ "$profile" != "backend" ]]; then
  optional "$(optional_domain "Pixi/Node Web toolchain")"
fi

if needs mobile-android || needs mobile-ios; then
  check_mobile_common
fi

if needs mobile-android; then
  check_android
elif [[ "$profile" != "mobile-ios" ]]; then
  optional "$(optional_domain "Android SDK, JDK, and adb")"
fi

if needs mobile-ios; then
  check_ios "$host_os"
elif [[ "$host_os" == "Darwin" ]]; then
  optional "$(optional_domain "Xcode and CocoaPods")"
else
  unsupported "iOS toolchain; not available on $host_os"
fi

if [[ "$profile" == "full" ]]; then
  if [[ -d "/Applications/Unity/Hub/Editor/2022.3.62f1/Unity.app" ]]; then
    optional "Unity 2022.3.62f1 available (paused PoC; not selected by any build)"
  else
    optional "Unity 2022.3.62f1 not found (paused PoC; not required)"
  fi
fi

if [[ "$failures" -ne 0 ]]; then
  exit 2
fi
