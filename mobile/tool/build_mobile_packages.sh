#!/usr/bin/env bash
# Build reproducible Aletheia mobile packages without storing signing secrets
# in the repository.  Run this file from any directory.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./tool/build_mobile_packages.sh [options]

Options:
  --engine flutter|unity       Renderer to package (default: flutter; Unity is paused)
  --platform android|ios|all   Platform to package (default: all)
  --ios-export METHOD          development, ad-hoc, or app-store
                               (default: development)
  --no-pub-get                 Do not run flutter pub get first
  -h, --help                   Show this help

Examples:
  # Internal Unity packages for a physical Android phone and a provisioned iPhone.
  ./tool/build_mobile_packages.sh --engine unity --platform all

  # Flutter renderer package for Android only.
  ./tool/build_mobile_packages.sh --engine flutter --platform android

Android formal release signing (environment only; never commit these values):
  export ALETHEIA_ANDROID_KEYSTORE=/absolute/path/aletheia-release.jks
  export ALETHEIA_ANDROID_KEYSTORE_PASSWORD='…'
  export ALETHEIA_ANDROID_KEY_ALIAS='aletheia'
  export ALETHEIA_ANDROID_KEY_PASSWORD='…'

The script writes timestamped APK/IPA files and SHA-256 files to
mobile/build/artifacts/.  When the Android signing variables are absent, Gradle
uses its existing debug key and the output is explicitly named
internal-debug-signed; it is not a distributable release or an update for a
formally signed installation.
EOF
}

engine='flutter'
platform='all'
ios_export='development'
run_pub_get=1

while (($# > 0)); do
  case "$1" in
    --engine)
      (($# >= 2)) || { echo 'Missing value for --engine.' >&2; exit 2; }
      engine="$2"
      shift 2
      ;;
    --platform)
      (($# >= 2)) || { echo 'Missing value for --platform.' >&2; exit 2; }
      platform="$2"
      shift 2
      ;;
    --ios-export)
      (($# >= 2)) || { echo 'Missing value for --ios-export.' >&2; exit 2; }
      ios_export="$2"
      shift 2
      ;;
    --no-pub-get)
      run_pub_get=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$engine" in flutter|unity) ;; *) echo "Unsupported engine: $engine" >&2; exit 2;; esac
case "$platform" in android|ios|all) ;; *) echo "Unsupported platform: $platform" >&2; exit 2;; esac
case "$ios_export" in development|ad-hoc|app-store) ;; *) echo "Unsupported iOS export method: $ios_export" >&2; exit 2;; esac

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mobile_dir="$(cd "$script_dir/.." && pwd)"
repo_dir="$(cd "$mobile_dir/.." && pwd)"
artifacts_dir="$mobile_dir/build/artifacts"
timestamp="$(date '+%Y%m%d-%H%M')"

mkdir -p "$artifacts_dir"

# Builds must not inherit a developer's HTTP proxy accidentally.  This matches
# the project run commands and avoids intermittent CocoaPods/Flutter failures.
clean_env=(
  env
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY
  -u http_proxy -u https_proxy -u all_proxy
  # Never inherit a previous device-only Unity CocoaPods configuration into a
  # simulator or Flutter-renderer build. The Unity branch below opts in again
  # explicitly, so each invocation is self-contained and reproducible.
  -u ALETHEIA_UNITY_ENABLED
)

# The normal repository command is still plain `flutter` for backward
# compatibility. The root module wrapper opts into the project-pinned FVM SDK
# without duplicating packaging logic or making Unity the default renderer.
flutter_command=(flutter)
if [[ "${ALETHEIA_USE_FVM:-0}" == '1' ]]; then
  command -v fvm >/dev/null 2>&1 || {
    echo 'ALETHEIA_USE_FVM=1 requires FVM. Install: dart pub global activate fvm 4.3.0' >&2
    exit 2
  }
  flutter_command=(fvm flutter)
fi
if [[ "$engine" == 'unity' ]]; then
  clean_env+=(ALETHEIA_UNITY_ENABLED=1)
fi

dart_defines=()
if [[ "$engine" == 'unity' ]]; then
  # AV_ENGINE selects the rendering seam; this second define proves the
  # package embeds the real, device-only Unity runtime. It prevents an
  # iOS-simulator/Flutter-only build from selecting an empty native surface.
  dart_defines+=(
    --dart-define=AV_ENGINE=unity
    --dart-define=AV_UNITY_RUNTIME=true
  )
fi

has_android_formal_signing=1
for required_var in \
  ALETHEIA_ANDROID_KEYSTORE \
  ALETHEIA_ANDROID_KEYSTORE_PASSWORD \
  ALETHEIA_ANDROID_KEY_ALIAS \
  ALETHEIA_ANDROID_KEY_PASSWORD; do
  if [[ -z "${!required_var:-}" ]]; then
    has_android_formal_signing=0
    break
  fi
done

if ((has_android_formal_signing)); then
  [[ -f "$ALETHEIA_ANDROID_KEYSTORE" ]] || {
    echo "ALETHEIA_ANDROID_KEYSTORE does not point to a file: $ALETHEIA_ANDROID_KEYSTORE" >&2
    exit 2
  }
  android_signing_label='release-signed'
else
  android_signing_label='internal-debug-signed'
fi

require_unity_android_export() {
  [[ -d "$repo_dir/unity/builds/android/unityLibrary" ]] || {
    echo 'Unity Android export is missing: unity/builds/android/unityLibrary' >&2
    echo 'Export it from Unity before packaging with --engine unity.' >&2
    exit 1
  }
}

require_unity_ios_export() {
  local unity_library="$mobile_dir/packages/aletheia_visualization/ios/UnityLibrary"
  [[ -f "$unity_library/UnityFramework.framework/UnityFramework" && -d "$unity_library/Data" ]] || {
    echo 'Unity iOS framework/Data is missing from mobile/packages/aletheia_visualization/ios/UnityLibrary.' >&2
    echo 'Export and copy the Unity iOS framework before packaging with --engine unity.' >&2
    exit 1
  }

  # The IL2CPP binary and `Data/Managed/Metadata/global-metadata.dat` are one
  # inseparable build pair. Copying a newly compiled UnityFramework while
  # leaving an older Data directory makes iOS crash inside Unity's allocator
  # during `runEmbedded`, before Flutter can show a map. When the local export
  # is available, fail packaging loudly instead of emitting that broken IPA.
  local export_metadata="$repo_dir/unity/builds/ios/Data/Managed/Metadata/global-metadata.dat"
  local embedded_metadata="$unity_library/Data/Managed/Metadata/global-metadata.dat"
  if [[ -f "$export_metadata" && -f "$embedded_metadata" ]] &&
     ! cmp -s "$export_metadata" "$embedded_metadata"; then
    echo 'Unity iOS Data is stale relative to unity/builds/ios/Data.' >&2
    echo 'Sync the complete Data directory (not Unity-iPhone/Data) before packaging:' >&2
    echo "  rsync -a --delete '$repo_dir/unity/builds/ios/Data/' '$unity_library/Data/'" >&2
    exit 1
  fi
}

copy_artifact() {
  local source="$1"
  local target="$2"
  [[ -f "$source" ]] || { echo "Expected build output was not produced: $source" >&2; exit 1; }
  cp "$source" "$target"
  shasum -a 256 "$target" >"$target.sha256"
  echo "Created: $target"
  echo "SHA-256: $target.sha256"
}

cd "$mobile_dir"
if ((run_pub_get)); then
  "${clean_env[@]}" "${flutter_command[@]}" pub get
fi

if [[ "$platform" == 'android' || "$platform" == 'all' ]]; then
  if [[ "$engine" == 'unity' ]]; then
    require_unity_android_export
  fi

  # macOS ships Bash 3.2, where expanding an empty array under `set -u`
  # raises "unbound variable". Keep the Flutter-renderer invocation truly
  # argument-free while Unity explicitly adds its renderer define.
  if [[ "$engine" == 'unity' ]]; then
    "${clean_env[@]}" "${flutter_command[@]}" build apk --release "${dart_defines[@]}"
  else
    "${clean_env[@]}" "${flutter_command[@]}" build apk --release
  fi
  copy_artifact \
    "$mobile_dir/build/app/outputs/flutter-apk/app-release.apk" \
    "$artifacts_dir/aletheia-$engine-$android_signing_label-$timestamp.apk"
fi

if [[ "$platform" == 'ios' || "$platform" == 'all' ]]; then
  if [[ "$engine" == 'unity' ]]; then
    require_unity_ios_export
  fi

  (
    cd "$mobile_dir/ios"
    "${clean_env[@]}" pod install
  )
  if [[ "$engine" == 'unity' ]]; then
    "${clean_env[@]}" "${flutter_command[@]}" build ipa --release \
      --export-method "$ios_export" "${dart_defines[@]}"
  else
    "${clean_env[@]}" "${flutter_command[@]}" build ipa --release \
      --export-method "$ios_export"
  fi
  copy_artifact \
    "$mobile_dir/build/ios/ipa/aletheia_mobile.ipa" \
    "$artifacts_dir/aletheia-$engine-release-$ios_export-$timestamp.ipa"
fi

if [[ "$platform" == 'android' || "$platform" == 'all' ]]; then
  if ((has_android_formal_signing)); then
    echo 'Android: formally signed release package.'
  else
    echo 'Android: internal debug-signed release-mode package (not for distribution).'
  fi
fi
if [[ "$platform" == 'ios' || "$platform" == 'all' ]]; then
  echo "iOS: $ios_export export. Its install/distribution eligibility is determined by the selected Apple signing profile."
fi
