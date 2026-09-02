#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
failures=0

ok() { printf '[OK] %s\n' "$1"; }
warn() { printf '[WARN] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1"; failures=1; }
has() { command -v "$1" >/dev/null 2>&1; }

if has pixi; then ok "Pixi $(pixi --version)"; else fail "Pixi missing"; fi
if has python3; then ok "Python $(python3 --version)"; else warn "Python missing"; fi
if has node; then ok "Node $(node --version)"; else warn "Node missing"; fi
if has npm; then ok "npm $(npm --version)"; else warn "npm missing"; fi
if has fvm; then ok "FVM $(fvm --version)"; else warn "FVM missing (mobile only): dart pub global activate fvm 4.3.0"; fi
if has flutter; then ok "Flutter $(flutter --version | head -n 1)"; else warn "Flutter missing (mobile only)"; fi
if has dart; then ok "Dart $(dart --version 2>&1 | head -n 1)"; else warn "Dart missing (mobile only)"; fi

if has java; then
  java_version="$(java -version 2>&1 | sed -n '1s/.*version "\([0-9][0-9]*\).*/\1/p')"
  if [[ "$java_version" == "17" ]]; then ok "JDK 17"; else warn "JDK ${java_version:-unknown}; Android project requires JDK 17"; fi
else
  warn "JDK missing (Android only; requires JDK 17)"
fi

android_sdk="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
if [[ -n "$android_sdk" ]]; then ok "Android SDK configured"; else warn "Android SDK not configured (Android only)"; fi
if has adb; then ok "adb available"; else warn "adb missing (Android only)"; fi
if has xcodebuild; then ok "$(xcodebuild -version | tr '\n' ' ')"; else warn "Xcode missing (iOS only)"; fi
if has pod; then ok "CocoaPods $(pod --version)"; else warn "CocoaPods missing (iOS only)"; fi
if [[ -d "/Applications/Unity/Hub/Editor/2022.3.62f1/Unity.app" ]]; then
  ok "Unity 2022.3.62f1 available (paused PoC)"
else
  warn "Unity 2022.3.62f1 not found (paused PoC; not required)"
fi

if [[ "$failures" -ne 0 ]]; then exit 2; fi

