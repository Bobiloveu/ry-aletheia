#!/bin/sh
# Rebuild platform launcher assets from the single vector artwork source.
# macOS `sips` is used deliberately: iOS builds already require macOS, and it
# rasterizes the source SVG without creating another editable logo source.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
svg_source="$project_dir/assets/branding/aletheia_icon_vector.svg"
generated_dir="$project_dir/tool/generated"
raster_source="$generated_dir/aletheia_launcher_source.png"

if [ ! -f "$svg_source" ]; then
  echo "Missing vector logo: $svg_source" >&2
  exit 1
fi

if ! command -v sips >/dev/null 2>&1; then
  echo "This icon generator requires macOS sips to rasterize the SVG." >&2
  exit 1
fi

mkdir -p "$generated_dir"
sips -s format png "$svg_source" --out "$raster_source" >/dev/null

cd "$project_dir"
dart run flutter_launcher_icons
