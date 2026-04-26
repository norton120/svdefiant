#!/usr/bin/env bash
#
# Resize and re-encode photos for the web before adding them to a gallery
# album. Defaults: max 2400 px on the long side, JPG quality 85, output as
# .jpg regardless of source format. HEIC, PNG, and JPG inputs are handled.
#
# Usage:
#   bin/optimize-photos.sh <input-dir> [output-dir]
#
# If no output dir is given, output goes to "<input-dir>-optimized/" next to
# the source. The original directory is never modified.
#
# Notes:
#   - Uses macOS's built-in `sips`, no external deps.
#   - Re-encoding via sips strips most EXIF, but GPS tags can persist on
#     some files. Install `exiftool` and run `exiftool -all= <dir>` after
#     this script if you need a clean strip.

set -euo pipefail

MAX_DIM=2400
QUALITY=85

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <input-dir> [output-dir]" >&2
  exit 64
fi

src="${1%/}"
dst="${2:-${src}-optimized}"

if [[ ! -d "$src" ]]; then
  echo "Not a directory: $src" >&2
  exit 1
fi

if [[ "$(cd "$src" && pwd)" == "$(cd "$dst" 2>/dev/null && pwd || echo "")" ]]; then
  echo "Refusing to write output into the source directory." >&2
  exit 1
fi

mkdir -p "$dst"

shopt -s nullglob nocaseglob

inputs=("$src"/*.jpg "$src"/*.jpeg "$src"/*.png "$src"/*.heic)
total=${#inputs[@]}

if [[ $total -eq 0 ]]; then
  echo "No images found in $src (looking for jpg/jpeg/png/heic)." >&2
  exit 1
fi

echo "Optimizing $total image(s) from $src → $dst"
echo "  max dimension: ${MAX_DIM}px, JPEG quality: ${QUALITY}"

count=0
for f in "${inputs[@]}"; do
  base="$(basename "$f")"
  stem="${base%.*}"
  out="$dst/${stem}.jpg"

  sips \
    -Z "$MAX_DIM" \
    -s format jpeg \
    -s formatOptions "$QUALITY" \
    "$f" --out "$out" >/dev/null

  count=$((count + 1))
  printf '\r  [%d/%d] %s' "$count" "$total" "$base"
done

echo
echo
src_size="$(du -sh "$src" | cut -f1)"
dst_size="$(du -sh "$dst" | cut -f1)"
echo "Done."
echo "  Source:    $src_size  ($src)"
echo "  Optimized: $dst_size  ($dst)"
