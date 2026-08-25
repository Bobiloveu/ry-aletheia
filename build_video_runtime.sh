#!/usr/bin/env bash
set -euo pipefail

# Assemble the isolated media runtime that is embedded in the full DEB.  The
# robot never calls apt: this script runs only on the developer/build machine.
# Its archives are version- and SHA256-locked for Ubuntu 22.04 amd64, which is
# the robot operating-system baseline.
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
LOCKFILE="$ROOT/tools/video-runtime-packages.lock"
OUTPUT_DIR="$ROOT/build/video-runtime"
ARCH="${RY_ALETHEIA_VIDEO_ARCH:-amd64}"
MEDIAMTX_VERSION="1.19.2"
MEDIAMTX_ARCHIVE="mediamtx_v${MEDIAMTX_VERSION}_linux_${ARCH}.tar.gz"
MEDIAMTX_SHA256="f9c601cc303ceca8fad2883917b022882672c5bc56311e92dbceb16e5f20c60c"
MEDIAMTX_URL="https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/${MEDIAMTX_ARCHIVE}"
CACHE_DIR="$ROOT/.cache/offline-deps/video-runtime"

if [[ $# -gt 0 ]]; then
  if [[ $# -ne 2 || "$1" != "--output-dir" ]]; then
    echo "用法：$0 [--output-dir <空目录>]" >&2
    exit 2
  fi
  OUTPUT_DIR="$2"
fi
if [[ "$ARCH" != "amd64" ]]; then
  echo "私有视频运行时当前仅支持 amd64；实际为：$ARCH" >&2
  exit 1
fi
if [[ ! -f "$LOCKFILE" ]]; then
  echo "未找到视频依赖锁文件：$LOCKFILE" >&2
  exit 1
fi
if [[ -e "$OUTPUT_DIR" ]]; then
  echo "视频运行时输出目录已存在，拒绝覆盖：$OUTPUT_DIR" >&2
  exit 1
fi
if ! command -v apt-get >/dev/null 2>&1 || ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "构建私有视频运行时需要 apt-get 与 dpkg-deb（仅下载/解包，不安装系统包）。" >&2
  exit 1
fi

mkdir -p "$CACHE_DIR"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
EXTRACTED="$STAGE/extracted"
RUNTIME="$STAGE/runtime"
mkdir -p "$EXTRACTED" "$RUNTIME/bin" "$RUNTIME/lib" "$RUNTIME/libexec" "$RUNTIME/plugins" "$RUNTIME/drivers" "$RUNTIME/mediamtx"

download_deb() {
  local package="$1" version="$2" checksum="$3" cache_file="$CACHE_DIR/${package}_${version}_${ARCH}.deb"
  if [[ ! -f "$cache_file" ]]; then
    local download_dir archive
    download_dir="$(mktemp -d)"
    (
      cd "$download_dir"
      apt-get download "${package}=${version}" >/dev/null
    )
    archive="$(find "$download_dir" -maxdepth 1 -type f -name '*.deb' -print -quit)"
    if [[ -z "$archive" ]] || [[ "$(dpkg-deb -f "$archive" Package)" != "$package" ]] || [[ "$(dpkg-deb -f "$archive" Version)" != "$version" ]]; then
      echo "下载的 DEB 与锁定包不一致：$package=$version" >&2
      exit 1
    fi
    install -m 0644 "$archive" "$cache_file"
  fi
  printf '%s  %s\n' "$checksum" "$cache_file" | sha256sum -c - >&2
  dpkg-deb -x "$cache_file" "$EXTRACTED"
}

while IFS=$'\t' read -r package version checksum; do
  [[ -z "$package" || "$package" == \#* ]] && continue
  download_deb "$package" "$version" "$checksum"
done < "$LOCKFILE"

MEDIAMTX_FILE="$CACHE_DIR/$MEDIAMTX_ARCHIVE"
if [[ ! -f "$MEDIAMTX_FILE" ]]; then
  curl -fL --connect-timeout 15 --retry 2 -o "$MEDIAMTX_FILE.part" "$MEDIAMTX_URL"
  mv "$MEDIAMTX_FILE.part" "$MEDIAMTX_FILE"
fi
printf '%s  %s\n' "$MEDIAMTX_SHA256" "$MEDIAMTX_FILE" | sha256sum -c - >&2
tar -xzf "$MEDIAMTX_FILE" -C "$RUNTIME/mediamtx" mediamtx LICENSE

# Only expose plugins required by the controlled RGB/BGR -> VAAPI H.264 -> RTSP
# pipeline. ``rtspclientsink`` builds an internal appsrc/appsink + rtpbin
# graph, therefore its transport plugins must remain alongside the visible
# encoder chain. This avoids loading unrelated optional plugins on a minimal
# robot image.
PLUGIN_DIR="$EXTRACTED/usr/lib/x86_64-linux-gnu/gstreamer-1.0"
for plugin in libgstcoreelements.so libgstrawparse.so libgstvideoconvert.so libgstvideoparsersbad.so libgstrtspclientsink.so libgstvaapi.so libgstapp.so libgsttcp.so libgstudp.so libgstrtp.so libgstrtpmanager.so; do
  [[ -f "$PLUGIN_DIR/$plugin" ]] || { echo "私有 GStreamer 缺少受控插件：$plugin" >&2; exit 1; }
  install -m 0644 "$PLUGIN_DIR/$plugin" "$RUNTIME/plugins/$plugin"
done

cp -a "$EXTRACTED/usr/lib/x86_64-linux-gnu/"libgst*.so* "$RUNTIME/lib/"
cp -a "$EXTRACTED/usr/lib/x86_64-linux-gnu/"libva*.so* "$RUNTIME/lib/"
cp -a "$EXTRACTED/usr/lib/x86_64-linux-gnu/"libigdgmm*.so* "$RUNTIME/lib/"
if [[ -d "$EXTRACTED/usr/lib/x86_64-linux-gnu/dri" ]]; then
  cp -a "$EXTRACTED/usr/lib/x86_64-linux-gnu/dri/." "$RUNTIME/drivers/"
fi
SCANNER="$EXTRACTED/usr/lib/x86_64-linux-gnu/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner"
[[ -x "$SCANNER" ]] || { echo "私有 GStreamer 缺少 gst-plugin-scanner。" >&2; exit 1; }
install -m 0755 "$SCANNER" "$RUNTIME/libexec/gst-plugin-scanner"
install -m 0755 "$EXTRACTED/usr/bin/gst-launch-1.0" "$RUNTIME/bin/gst-launch-1.0.real"

cat > "$RUNTIME/bin/gst-launch-1.0" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
RUNTIME="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
# This program is started by a PyInstaller onefile child. Its inherited
# LD_LIBRARY_PATH can contain a temporary _MEI directory with an unrelated
# GLib, which is incompatible with this locked GStreamer runtime. Do not
# append it: gst-launch needs only its private GStreamer/VA libraries and the
# system ABI libraries resolved by the dynamic loader.
export LD_LIBRARY_PATH="$RUNTIME/lib"
export GST_PLUGIN_SYSTEM_PATH_1_0="$RUNTIME/plugins"
export GST_PLUGIN_SCANNER="$RUNTIME/libexec/gst-plugin-scanner"
export GST_REGISTRY_1_0="${RY_ALETHEIA_GST_REGISTRY:-$RUNTIME/gst-registry.bin}"
export LIBVA_DRIVERS_PATH="$RUNTIME/drivers"
export LIBVA_DRIVER_NAME="${LIBVA_DRIVER_NAME:-iHD}"
exec "$RUNTIME/bin/gst-launch-1.0.real" "$@"
EOF
chmod 0755 "$RUNTIME/bin/gst-launch-1.0"

cat > "$RUNTIME/README.txt" <<EOF
RY Aletheia private video runtime
MediaMTX: ${MEDIAMTX_VERSION}
GStreamer: Ubuntu 22.04 locked archives listed in tools/video-runtime-packages.lock
Only the controlled fdsrc -> RGB/BGR -> VAAPI H.264 -> RTSP plugins are exposed.
EOF
cat > "$RUNTIME/ry-aletheia-runtime.json" <<EOF
{
  "schema": "ry-aletheia-video-runtime/v1",
  "mediamtx_version": "${MEDIAMTX_VERSION}",
  "plugins": ["coreelements", "rawparse", "videoconvert", "videoparsersbad", "rtspclientsink", "vaapi", "app", "tcp", "udp", "rtp", "rtpmanager"]
}
EOF

mkdir -p "$(dirname -- "$OUTPUT_DIR")"
mv "$RUNTIME" "$OUTPUT_DIR"
echo "私有视频运行时已生成：$OUTPUT_DIR"
