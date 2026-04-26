#!/usr/bin/env bash
#
# Resize, re-encode, and EXIF-auto-orient photos for the web before adding
# them to a gallery album. Defaults: max 2400 px on the long side, JPEG
# quality ~85, output as .jpg regardless of source format. Uses ffmpeg,
# which auto-rotates from EXIF orientation by default and strips metadata.
#
# Usage:
#   bin/optimize-photos.sh <input-dir> [output-dir]
#
# If no output dir is given, output goes to "<input-dir>-optimized/" next to
# the source. The original directory is never modified.

set -euo pipefail

MAX_DIM=2400
QSCALE=4   # ffmpeg JPEG q:v; ~q85. Lower = better; range 1-31.

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required but not found. Install with: brew install ffmpeg" >&2
  exit 1
fi

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

src_abs="$(cd "$src" && pwd)"
mkdir -p "$dst"
dst_abs="$(cd "$dst" && pwd)"

if [[ "$src_abs" == "$dst_abs" ]]; then
  echo "Refusing to write output into the source directory." >&2
  exit 1
fi

shopt -s nullglob nocaseglob

inputs=("$src"/*.jpg "$src"/*.jpeg "$src"/*.png "$src"/*.heic)
total=${#inputs[@]}

if [[ $total -eq 0 ]]; then
  echo "No images found in $src (looking for jpg/jpeg/png/heic)." >&2
  exit 1
fi

echo "Optimizing $total image(s) from $src → $dst"
echo "  max dimension: ${MAX_DIM}px, JPEG quality: q:v=${QSCALE} (~q85)"

count=0
for f in "${inputs[@]}"; do
  base="$(basename "$f")"
  stem="${base%.*}"
  out="$dst/${stem}.jpg"

  ffmpeg -y -loglevel error -i "$f" \
    -vf "scale='min(${MAX_DIM},iw)':'min(${MAX_DIM},ih)':force_original_aspect_ratio=decrease" \
    -map_metadata -1 \
    -q:v "$QSCALE" \
    "$out"

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
